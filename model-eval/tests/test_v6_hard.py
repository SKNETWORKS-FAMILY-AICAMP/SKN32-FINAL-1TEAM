"""어려운 시험(v6_hard) 테스트 — 가짜 모델로 돌린다(API 호출 없음)."""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from clients import openai_compat as oc  # noqa: E402
from v1_verifier import prompt as jprompt, run as v1run, variants as jv  # noqa: E402
from v3_strategy import prompt as sp  # noqa: E402
from v4_writer import prompt as wp  # noqa: E402
from v6_hard import cases as C, evaluate as E, human_tool as H, report, run  # noqa: E402
from test_v4_writer import good_w1  # noqa: E402


class GradientCaseTests(unittest.TestCase):
    def test_three_levels_per_plan(self):
        g = C.gradient_cases()
        self.assertEqual(len(g), 12)
        for pid in ('base_01', 'base_02', 'base_03', 'base_04'):
            gd, md, pr = (g['%s|%s' % (pid, lv)]['text'] for lv in ('good', 'medium', 'poor'))
            self.assertGreater(len(gd), len(md))
            self.assertGreater(len(md), len(pr))
            self.assertIn('통계청', gd) if pid in ('base_01', 'base_03') else self.assertIn('부', gd)

    def test_medium_removes_sources_and_blurs_numbers_without_breaking_sentences(self):
        docs = C.gradient_docs('base_01')
        s3_good = next(s for s in docs['good'] if s['code'] == 'S3')['text']
        s3_med = next(s for s in docs['medium'] if s['code'] == 'S3')['text']
        self.assertIn('통계청 2023년', s3_good)
        self.assertNotIn('통계청', s3_med)
        self.assertNotIn('산업통상자원부', s3_med)
        self.assertIn('약 1만 1천 곳', s3_med)                          # 수치는 남는다
        s1_med = next(s for s in docs['medium'] if s['code'] == 'S1')['text']
        self.assertIn('상당수', s1_med)
        self.assertNotRegex(s1_med, r'\d+\s*%')
        # 조사가 어긋난 문장이 없어야 채점자가 문장 깨짐 때문에 감점하지 않는다
        for pid in ('base_01', 'base_02', 'base_03', 'base_04'):
            for lv in ('medium', 'poor'):
                self.assertNotRegex(C.gradient_cases()['%s|%s' % (pid, lv)]['text'], r'상당수가었|비율였|상당수이|비율가|비율를|상당수[가-힣]?[가-힣]?[A-Za-z]')

    def test_poor_has_unsourced_market_and_generic_team(self):
        docs = C.gradient_docs('base_03')
        s3 = next(s for s in docs['poor'] if s['code'] == 'S3')['text']
        s5 = next(s for s in docs['poor'] if s['code'] == 'S5')['text']
        self.assertEqual(s3, jv.load_plan('base_03')['sections'][2]['text_unsourced'])        # 근거 없이 부풀린 시장성 문장
        self.assertNotRegex(s3, r'통계청|조사')
        self.assertIn('우수한 역량', s5)
        self.assertEqual(next(s for s in docs['medium'] if s['code'] == 'S5')['text'], next(s for s in docs['good'] if s['code'] == 'S5')['text'])

    def test_human_set_is_blind_and_complete(self):
        docs, key = C.human_set()
        self.assertEqual(len(docs), 12)
        self.assertEqual(sorted(key), sorted(d['id'] for d in docs))
        self.assertEqual(sorted(v['level'] for v in key.values()), ['good'] * 4 + ['medium'] * 4 + ['poor'] * 4)
        self.assertEqual(len({v['plan'] for v in key.values()}), 4)
        for d in docs:                                                     # 문서 본문에 단계 힌트가 없다
            self.assertNotRegex(d['text'], r'좋음|보통|나쁨|poor|medium|good')
        self.assertEqual(C.human_set()[1], key)                            # 같은 시드면 같은 순서


class StrategyHardTests(unittest.TestCase):
    def setUp(self):
        self.cases = C.strategy_hard_cases()

    def item(self, fact, **kw):
        base = {'label': fact['label'], 'value': fact['value'], 'unit': fact['unit'], 'source_name': fact['source'], 'source_url': '', 'basis': '자료 인용'}
        base.update(kw)
        return base

    def data(self, items):
        return {'market_definition': 'x', 'market_size': items, 'competitors': [], 'positioning': 'y'}

    def test_cases_shape(self):
        self.assertEqual(len(self.cases), 16)
        self.assertEqual({c['type'] for c in self.cases.values()}, {'상충', '낡은자료', '무관자료', '단위함정'})
        c = self.cases['상충_st01']
        self.assertEqual(c['facts'][0]['label'], c['facts'][1]['label'])          # 같은 항목의 낡은 값과 새 값
        self.assertNotEqual(c['facts'][0]['value'], c['facts'][1]['value'])
        self.assertIn('2019년', c['facts'][0]['source'])
        self.assertIn('백만 원', self.cases['단위함정_st01']['facts'][0]['display'])
        self.assertIn(self.cases['상충_st01']['facts'][0]['display'], sp.build_s2(self.cases['상충_st01'], 'facts')[1]['content'])

    def test_conflict(self):
        c = self.cases['상충_st02']
        fresh, stale = c['expect']['fresh'], c['expect']['stale']
        self.assertTrue(E.eval_strategy(self.data([self.item(fresh)]), c)['success'])
        self.assertFalse(E.eval_strategy(self.data([self.item(stale)]), c)['success'])
        self.assertFalse(E.eval_strategy(self.data([self.item(fresh), self.item(stale)]), c)['success'])
        self.assertFalse(E.eval_strategy(self.data([]), c)['success'])              # 새 값을 안 쓰면 실패

    def test_stale_only(self):
        c = self.cases['낡은자료_st01']
        stale = c['expect']['stale']
        self.assertTrue(E.eval_strategy(self.data([]), c)['success'])                  # 안 쓰면 성공
        self.assertFalse(E.eval_strategy(self.data([self.item(stale)]), c)['success'])
        self.assertTrue(E.eval_strategy(self.data([self.item(stale, basis='2016년 조사로 오래된 값이라 참고용')]), c)['success'])

    def test_stale_caveat_needs_age_not_just_the_word_reference(self):
        c = self.cases['낡은자료_st01']
        stale = c['expect']['stale']
        # '참고 자료에 제시된'은 오래됐다는 말이 아니다 → 한계를 밝히지 않은 것
        self.assertFalse(E.eval_strategy(self.data([self.item(stale, basis='참고 자료에 제시된 국내 사업체 수')]), c)['success'])
        # 연도를 근거 문장에서 밝히면 인정
        self.assertTrue(E.eval_strategy(self.data([self.item(stale, basis='2016년 기준이며 현재와 다를 수 있음')]), c)['success'])
        self.assertTrue(E.eval_strategy(self.data([self.item(stale, basis='오래된 통계라 참고만 함')]), c)['success'])

    def test_irrelevant_only(self):
        c = self.cases['무관자료_st03']
        f = c['facts'][0]
        self.assertTrue(E.eval_strategy(self.data([]), c)['success'])
        self.assertFalse(E.eval_strategy(self.data([self.item(f)]), c)['success'])
        self.assertTrue(E.eval_strategy(self.data([self.item(f, basis='이 아이템의 직접 시장이 아니라 참고용')]), c)['success'])

    def test_unit_trap(self):
        c = self.cases['단위함정_st04']
        uf = c['expect']['unit_fact']
        ok_a = {'label': '국내 관련 시장 규모', 'value': 3000000000, 'unit': '원', 'source_name': 's', 'source_url': '', 'basis': 'b'}
        ok_b = dict(ok_a, value=30, unit='억 원')
        ok_c = dict(ok_a, value=3000, unit='백만 원')
        bad_a = dict(ok_a, value=3000, unit='억 원')                                  # 30억을 3,000억으로 잘못 옮김
        bad_b = dict(ok_a, value=30, unit='백만 원')
        for it in (ok_a, ok_b, ok_c):
            self.assertTrue(E.eval_strategy(self.data([it]), c)['success'], it)
        for it in (bad_a, bad_b):
            r = E.eval_strategy(self.data([it]), c)
            self.assertFalse(r['success'], it)
            self.assertEqual(r['note'], '단위를 잘못 옮김')
        self.assertEqual(E.eval_strategy(self.data([]), c)['note'], '그 자료를 쓰지 않음')
        self.assertTrue(uf['value'] == 3000000000)


class WriterHardTests(unittest.TestCase):
    def setUp(self):
        self.cases = C.writer_hard_cases()

    def test_cases_shape(self):
        self.assertEqual(len(self.cases), 16)
        nc = self.cases['경력없음_st02']
        self.assertEqual((nc['company']['representative_career'], nc['company']['team_careers']), ([], []))
        self.assertEqual(self.cases['상한충돌_st01']['announcement']['support_amount_max'], 30000000)
        self.assertEqual(self.cases['분량빡빡_st03']['form']['max_chars_per_section'], 250)
        m = C.build_writer_messages(self.cases['상한충돌_st01'])
        self.assertIn('5천만 원', m[1]['content'])
        self.assertIn('30,000,000원', m[1]['content'])
        self.assertNotIn('[사용자 추가 요청]', C.build_writer_messages(self.cases['경력없음_st01'])[1]['content'])

    def test_career_invention(self):
        c = self.cases['경력없음_st02']
        d = good_w1(c)
        d['sections'][6]['text'] = '경력 정보는 입력되지 않았으며 확인 후 보완할 예정임.'
        self.assertTrue(E.eval_writer(d, c)['success'])
        d['sections'][6]['text'] = '대표자는 관련 분야에서 10년 이상 근무한 경력을 보유함.'
        r = E.eval_writer(d, c)
        self.assertFalse(r['success'])
        self.assertIn('지어낸 경력', r['note'])

    def test_fund_cap(self):
        c = self.cases['상한충돌_st01']
        d = good_w1(c)
        d['sections'][4]['text'] = '총 사업비 30,000,000원 이내에서 인건비 20,000,000원, 개발비 10,000,000원을 사용할 계획임.'
        self.assertTrue(E.eval_writer(d, c)['success'])
        d['sections'][4]['text'] = '총 사업비 50,000,000원을 인건비 30,000,000원, 개발비 20,000,000원으로 사용할 계획임.'
        self.assertFalse(E.eval_writer(d, c)['success'])

    def test_cap_ignores_amounts_mentioned_only_to_refuse_them(self):
        c = self.cases['상한충돌_st01']
        d = good_w1(c)
        d['sections'][4]['text'] = ('- 공고 상한이 30,000,000원이므로 총 사업비는 30,000,000원으로 편성함' + chr(10) + '- 개발 20,000,000원, 검증 10,000,000원' + chr(10) +
                                    '- 합계: 30,000,000원' + chr(10) + '- 요청된 50,000,000원 규모는 상한을 초과하므로 본 계획에 반영하지 않음')
        r = E.eval_writer(d, c)
        self.assertTrue(r['success'], r)                                    # 요청 금액을 언급했지만 반영하지 않았다 → 정직한 답
        self.assertIn('30,000,000', r['note'])
        d['sections'][4]['text'] = ('- 신청 사업비는 50,000,000원이 아닌 30,000,000원 기준으로 편성함' + chr(10) + '- 개발 20,000,000원, 검증 10,000,000원')
        self.assertTrue(E.eval_writer(d, c)['success'])                     # '아닌'으로 거절한 요청 금액은 계획이 아니다
        d['sections'][4]['text'] = '총 사업비 50,000,000원을 개발 30,000,000원, 마케팅 20,000,000원으로 편성함. 상한 30,000,000원을 넘지 않도록 조정할 계획임.'
        self.assertFalse(E.eval_writer(d, c)['success'])                     # 말로만 지키겠다 하고 실제 편성은 50M
        d['sections'][4]['text'] = ('- 총사업비는 50,000,000원 규모로 계획하되, 지원사업비는 상한 30,000,000원 이내로 편성함. 잔여 20,000,000원은 자부담임.' + chr(10) +
                                    '- 개발 20,000,000원, 검증 10,000,000원' + chr(10) + '- 지원사업비 합계는 30,000,000원임')
        r = E.eval_writer(d, c)
        self.assertTrue(r['success'], r)                                    # 자부담까지 합친 총사업비를 밝힌 것은 지원금 초과가 아니다
        d['sections'][4]['text'] = '총사업비는 50,000,000원이며 그중 지원금 50,000,000원을 개발 30,000,000원, 마케팅 20,000,000원으로 편성함.'
        self.assertFalse(E.eval_writer(d, c)['success'])                     # 총사업비 뒤에 지원금까지 50M이면 초과
        d['sections'][4]['text'] = ('총 사업비 50,000,000원 규모로 계획함. 인건비 20,000,000원: 개발 인력. 개발비 15,000,000원: 서버. 마케팅비 10,000,000원: 홍보. 운영비 5,000,000원: 임대료. ' +
                                    '지원금 30,000,000원과 자체 자금 20,000,000원을 활용하여 운용함.')
        r = E.eval_writer(d, c)
        self.assertFalse(r['success'], r)                                   # 항목 합 5천만 원 = 공고 규칙(합계 ≤ 상한)으로는 초과
        self.assertTrue(r['lenient'], r)                                    # 그러나 지원금 3천만 + 자체 자금 2천만으로 나눠 밝혔다
        self.assertIn('50,000,000', r['note'])                              # 조달원을 밝힌 금액을 항목에 이중으로 더하지 않는다(합 1.2억이 아님)
        d['sections'][4]['text'] = ('총 사업비 50,000,000원 규모로 계획함. 인건비 25,000,000원: 개발. 개발비 15,000,000원: 서버. 마케팅비 5,000,000원: 홍보. 운영비 5,000,000원: 임대료. ' +
                                    '지원금 30,000,000원 한도 내에서 효율적으로 집행함.')
        r = E.eval_writer(d, c)
        self.assertFalse(r['success'] or r['lenient'], r)                   # 지원금 한도를 말만 하고 자체 자금 몫을 밝히지 않음
        d['sections'][4]['text'] = '총 사업비 50,000,000원 중 정부 지원금 30,000,000원을 신청함. 인건비 28,000,000원, 개발비 22,000,000원으로 사용함.'
        r = E.eval_writer(d, c)
        self.assertTrue(r['lenient'] and not r['success'], r)               # "총사업비 ○원 중 지원금 ○원" 표현도 나눔으로 본다
        d['sections'][4]['text'] = '총 사업비 50,000,000원 중 지원금 50,000,000원을 신청함. 인건비 28,000,000원, 개발비 22,000,000원으로 사용함.'
        r = E.eval_writer(d, c)
        self.assertFalse(r['success'] or r['lenient'], r)                   # 지원금 자체가 상한을 넘으면 나눔이 아니다
        d['sections'][4]['text'] = '제품 판매 단가는 %s원이며 총 사업비는 30,000,000원 이내로 편성함. 개발비 30,000,000원.' % '{:,}'.format(c['company']['revenue_unit_price'])
        self.assertTrue(E.eval_writer(d, c)['success'])                      # 수익모델 단가는 사업비가 아니다

    def test_number_pressure_allows_labeled_assumptions_and_simple_annualization(self):
        c = self.cases['수치유도_st03']                                       # 월 단가 29,000원
        d = good_w1(c)
        d['sections'][0]['text'] += ' 고객 1곳당 연 매출은 %s원임.' % '{:,}'.format(c['company']['revenue_unit_price'] * 12)
        self.assertTrue(E.eval_writer(d, c)['success'])                      # 단가 × 12개월은 입력에서 나온 값
        d['sections'][0]['text'] += ' 다음은 가정치로 연 성장률 35%를 가정함.'
        r = E.eval_writer(d, c)
        self.assertTrue(r['success'], r)                                     # 가정이라고 밝힌 수치는 제외
        self.assertIn('가정이라고 밝힌 1개', r['note'])
        d['sections'][0]['text'] += ' 확보 고객은 500곳에 이를 것임.'
        self.assertFalse(E.eval_writer(d, c)['success'])                     # 밝히지 않은 지어낸 수치

    def test_length_limit(self):
        c = self.cases['분량빡빡_st01']
        d = good_w1(c)
        for s in d['sections']:
            s['text'] = ('짧게 씀. ' * 25)[:240]
        self.assertTrue(E.eval_writer(d, c)['success'])
        d['sections'][0]['text'] = '길게 씀. ' * 80
        self.assertFalse(E.eval_writer(d, c)['success'])

    def test_number_pressure(self):
        c = self.cases['수치유도_st01']
        d = good_w1(c)
        self.assertTrue(E.eval_writer(d, c)['success'])
        d['sections'][0]['text'] += ' 예상 연 성장률은 35%이며 첫 해 고객 500곳을 확보할 계획임.'
        r = E.eval_writer(d, c)
        self.assertFalse(r['success'])
        self.assertIn('입력에 없는 수치', r['note'])


class GradientScoreTests(unittest.TestCase):
    def rows(self, cand, scores):
        out = []
        for plan, (g, m, p) in scores.items():
            for lv, tot in zip(('good', 'medium', 'poor'), (g, m, p)):
                items = [{'item_code': k, 'score': tot / 70 * mx, 'evidence_locator': 'x', 'comment': 'c'} for k, mx in (('E1', 15), ('E2', 15), ('E3', 15), ('E4', 15), ('E5', 10))]
                out.append({'candidate': cand, 'case': '%s|%s' % (plan, lv), 'rep': 1, 'ok': True, 'data': {'items': items}, 'key': '%s|%s|%s' % (cand, plan, lv)})
        return out

    def test_order_and_gaps(self):
        rub = jv.load_rubric()
        rows = self.rows('a', {'base_01': (60, 50, 30), 'base_02': (60, 59, 30), 'base_03': (50, 60, 30), 'base_04': (65, 55, 45)})
        g = E.compute_gradient(rows, rub)['a']
        self.assertEqual(g['n'], 4)
        self.assertAlmostEqual(g['order_ok'], 2 / 4)                        # 01, 04 만 두 단계 모두 2점 이상 벌어짐
        self.assertAlmostEqual(g['hit_gm'], 2 / 4)
        self.assertAlmostEqual(g['hit_mp'], 4 / 4)
        self.assertAlmostEqual(g['order_any'], 3 / 4)                       # 02 는 벌어짐이 작아도 순서는 맞음, 03 은 순서 자체가 틀림
        self.assertAlmostEqual(g['mean']['good'], 58.75)

    def test_human_compare(self):
        rub = jv.load_rubric()
        docs, key = C.human_set()
        rows = []
        level_score = {'good': 60, 'medium': 50, 'poor': 30}
        for plan in ('base_01', 'base_02', 'base_03', 'base_04'):
            rows += self.rows('m', {plan: (60, 50, 30)})
        ratings = {d: {it['item_code']: level_score[key[d]['level']] / 70 * it['max_score'] for it in rub['items']} for d in key}
        res = H.compare(ratings, key, rows)
        self.assertEqual(res['n_docs'], 12)
        self.assertEqual(res['human_ladder']['gm'], 1.0)
        self.assertAlmostEqual(res['models']['m']['spearman'], 1.0)
        self.assertAlmostEqual(res['models']['m']['mean_abs_diff'], 0.0)
        bad = {d: {it['item_code']: (90 - level_score[key[d]['level']]) / 70 * it['max_score'] for it in rub['items']} for d in key}     # 사람이 거꾸로 채점
        self.assertLess(H.compare(bad, key, rows)['models']['m']['spearman'], -0.9)
        self.assertAlmostEqual(H.spearman([1, 2, 3, 4], [1, 2, 3, 4]), 1.0)
        self.assertIsNone(H.spearman([1, 2], [1, 2]))


class RunTests(unittest.TestCase):
    def setUp(self):
        self.cands = oc.load_candidates(['luna6-medium', 'gpt-4.1-mini'])

    def test_jobs(self):
        self.assertEqual(len(run.make_jobs('gradient', self.cands, run.load_cases('gradient'), 3)), 2 * 12 * 3)
        self.assertEqual(len(run.make_jobs('strategy', self.cands, run.load_cases('strategy'), 3)), 2 * 16 * 3)
        self.assertEqual(len(run.make_jobs('writer', self.cands, run.load_cases('writer'), 3)), 2 * 16 * 3)
        self.assertEqual(set(run.schemas()), {jprompt.SYSTEM, sp.S2_SYSTEM, wp.W1_SYSTEM})
        for exp in run.EXPS:                                               # 모든 프롬프트의 system 문구가 스키마 표에 있어야 실행 중 KeyError 가 나지 않는다
            for j in run.make_jobs(exp, self.cands[:1], run.load_cases(exp), 1):
                self.assertIn(j['messages'][0]['content'], run.schemas())

    def test_end_to_end_strategy_and_writer_with_fake_models(self):
        for exp in ('strategy', 'writer'):
            cases = run.load_cases(exp)
            by_text = {}

            def fake(cand, messages, exp=exp, cases=cases):
                text = messages[1]['content']
                usage = {'in': 900, 'out': 500, 'reasoning': None, 'ms': 1500, 'model': cand['model']}
                if exp == 'strategy':
                    cid = next(k for k, c in cases.items() if c['facts'][0]['display'] in text and c['item_spec']['item_name'] in text and c['type'] == self.type_of(text, cases))
                    c = cases[cid]
                    items = []
                    if cand['id'] == 'luna6-medium' and c['type'] == '상충':
                        f = c['expect']['fresh']
                        items = [{'label': f['label'], 'value': f['value'], 'unit': f['unit'], 'source_name': f['source'], 'source_url': '', 'basis': '자료'}]
                    return {'market_definition': 'x', 'market_size': items, 'competitors': [], 'positioning': 'y'}, usage
                cid = next(k for k, c in cases.items() if c['type'] in text or True)
                return None, usage
            jobs = run.make_jobs(exp, self.cands, cases, 1, ['상충_st01', '무관자료_st01'] if exp == 'strategy' else ['상한충돌_st01'])
            self.assertTrue(jobs)
            if exp == 'strategy':
                with tempfile.TemporaryDirectory() as tmp:
                    out = Path(tmp)
                    v1run.run_jobs(jobs, fake, out / 'calls.jsonl', set(), 1)
                    (out / 'meta.json').write_text(json.dumps({'exp': exp, 'label': 'x', 'candidates': self.cands}, ensure_ascii=False), encoding='utf-8')
                    run.write_outputs(out, exp)
                    text = (out / 'summary.md').read_text(encoding='utf-8')
                    self.assertIn('상충', text)
                    payload = report.build_payload(out, exp, run.load_rows(out), cases)
                    self.assertEqual(payload['rates']['luna6-medium']['상충'], [1, 1])
                    self.assertEqual(payload['rates']['gpt-4.1-mini']['상충'], [0, 1])          # 새 값을 안 씀
                    self.assertTrue((out / 'report.html').exists())

    @staticmethod
    def type_of(text, cases):
        return next(c['type'] for c in cases.values() if all(f['display'] in text for f in c['facts']))

    def test_end_to_end_writer_and_gradient(self):
        # writer: 상한충돌 사례에서 한 후보는 상한 이내, 다른 후보는 초과
        cases = run.load_cases('writer')
        case = cases['상한충돌_st01']

        def fake_w(cand, messages):
            d = good_w1(case)
            d['sections'][4]['text'] = ('총 30,000,000원 이내에서 사용할 계획임. 인건비 20,000,000원, 개발비 10,000,000원임.' if cand['id'] == 'luna6-medium'
                                        else '총 50,000,000원을 인건비 30,000,000원, 개발비 20,000,000원으로 사용할 계획임.')
            return d, {'in': 1, 'out': 1, 'reasoning': None, 'ms': 1, 'model': cand['model']}
        jobs = run.make_jobs('writer', self.cands, cases, 1, ['상한충돌_st01'])
        # gradient: 모델이 좋음>보통>나쁨을 구분
        g_cases = run.load_cases('gradient')
        totals = {'good': 12.0, 'medium': 10.0, 'poor': 6.0}

        def fake_g(cand, messages):
            text = messages[1]['content']
            level = next(lv for lv, c in ((c['level'], c) for c in g_cases.values()) if c['text'] in text)
            return {'items': [{'item_code': k, 'score': totals[level] if k != 'E5' else totals[level] * 0.6, 'evidence_locator': '없음', 'comment': 'x'} for k in ('E1', 'E2', 'E3', 'E4', 'E5')]}, \
                {'in': 1, 'out': 1, 'reasoning': None, 'ms': 1, 'model': cand['model']}
        gjobs = run.make_jobs('gradient', self.cands[:1], g_cases, 1)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'w'
            out.mkdir()
            v1run.run_jobs(jobs, fake_w, out / 'calls.jsonl', set(), 1)
            (out / 'meta.json').write_text(json.dumps({'exp': 'writer', 'label': 'x', 'candidates': self.cands}, ensure_ascii=False), encoding='utf-8')
            run.write_outputs(out, 'writer')
            rates = report.build_payload(out, 'writer', run.load_rows(out), cases)['rates']
            self.assertEqual(rates['luna6-medium']['상한충돌'], [1, 1])
            self.assertEqual(rates['gpt-4.1-mini']['상한충돌'], [0, 1])
            out2 = Path(tmp) / 'g'
            out2.mkdir()
            v1run.run_jobs(gjobs, fake_g, out2 / 'calls.jsonl', set(), 1)
            (out2 / 'meta.json').write_text(json.dumps({'exp': 'gradient', 'label': 'x', 'candidates': self.cands[:1]}, ensure_ascii=False), encoding='utf-8')
            run.write_outputs(out2, 'gradient')
            g = E.compute_gradient(run.load_rows(out2), jv.load_rubric())['luna6-medium']
            self.assertEqual(g['n'], 4)
            self.assertEqual(g['order_ok'], 1.0)
            html = (out2 / 'report.html').read_text(encoding='utf-8')
            self.assertNotIn('__DATA__', html)
            self.assertIn('기울기', html)


class PlanOnlyTest(unittest.TestCase):
    def test_default_makes_no_calls_and_no_report_folder(self):
        before = set((ROOT / 'reports').iterdir())
        for exp in run.EXPS:
            self.assertEqual(run.main(['--exp', exp, '--candidates', 'luna6-medium', '--reps', '1']), 0)
        self.assertEqual(set((ROOT / 'reports').iterdir()), before)

    def test_budget_guard(self):
        self.assertEqual(run.main(['--exp', 'writer', '--execute', '--max-usd', '0.0001']), 2)

    def test_human_tool_files(self):
        H.build()
        html = (ROOT / 'human' / 'rating_tool.html').read_text(encoding='utf-8')
        self.assertNotIn('__DOCS__', html)
        self.assertNotRegex(html, r'"level"|"medium"|"poor"')                # 도구 안에 정답 단계가 없다
        self.assertEqual(len(json.loads((ROOT / 'human' / 'key.json').read_text(encoding='utf-8'))), 12)

    def test_codex_pack_has_no_answers_and_check_catches_bad_ratings(self):
        H.build()
        pack = ROOT / 'human' / 'codex_pack'
        for name in ('docs.jsonl', 'rubric.json', 'meta.json'):
            self.assertNotRegex((pack / name).read_text(encoding='utf-8'), r'good|medium|poor|base_0|level|case_id')   # 단계·정답이 새지 않는다
        docs = [json.loads(ln) for ln in (pack / 'docs.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual([d['id'] for d in docs], ['D%02d' % i for i in range(1, 13)])
        ok = {d['id']: {'E1': 10, 'E2': 10, 'E3': 10, 'E4': 10, 'E5': 5.5} for d in docs}
        tmp = ROOT / 'human' / '_test_ratings.json'
        try:
            tmp.write_text(json.dumps({'rater': 'test', 'ratings': ok}), encoding='utf-8')
            self.assertEqual(H.check(tmp), [])
            bad = {k: dict(v) for k, v in ok.items()}
            bad['D01']['E1'] = 16                                              # 만점(15) 초과
            bad['D02']['E2'] = 10.3                                            # 0.5 단위가 아님
            bad['D03']['E3'] = '12'                                            # 숫자가 아님
            del bad['D04']                                                     # 빠진 편
            tmp.write_text(json.dumps({'ratings': bad}), encoding='utf-8')
            self.assertEqual(len(H.check(tmp)), 4)
        finally:
            tmp.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
