"""작성 T-W1·T-W2·T-W3 실험 골격 테스트 — 가짜 모델로 돌린다(API 호출 없음)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clients import openai_compat as oc  # noqa: E402
from v1_verifier import prompt as jprompt, run as v1run  # noqa: E402
from v4_writer import prompt, report, run, score  # noqa: E402

CASES = prompt.load_cases()


def good_w1(case):
    """규칙을 모두 지키는 본문. 입력에 있는 수치만 쓴다."""
    spec, co = case['item_spec'], case['company']
    feats = spec['core_features']
    texts = {
        '1-1': '%s를 대상으로 하는 서비스임. 현재 방식의 불편을 해소하는 것이 목표임. %s를 주요 고객으로 설정함. 문제의 원인을 구체적으로 분석하여 해결 방향을 도출함. 이용 현장의 어려움을 사례로 확인함.' % (spec['item_name'], spec['target_customer']),
        '1-2': '핵심 기능은 %s임. 각 기능은 고객의 불편과 직접 연결됨. %s임. 사용 흐름을 단순화하여 도입 부담을 낮춤. 기능별 제공 방식을 단계적으로 설계함.' % (', '.join(feats), case['differentiator'].rstrip('.')),
        '2-1': ' '.join('%s은 %s임(출처: %s).' % (f['label'], f['display'], f['source']) for f in case['facts']) + ' 이를 근거로 초기 목표 시장을 설정함. 시장 진입 전략은 단계적으로 수립함.',
        '2-2': '기존 대체 방식은 수기 관리에 머무름. 본 서비스는 자동화된 처리로 차별화함. 도입이 쉽고 유지 비용이 낮음. 지속적인 개선 체계를 운영할 계획임. 고객 피드백을 반영하여 기능을 보완함.',
        '3-1': '총 지원금 범위 내에서 ' + ', '.join('%s {:,}원'.format(f['amount']) % f['label'] for f in case['funds']) + '을 사용할 계획임. 합계는 ' + '{:,}원'.format(sum(f['amount'] for f in case['funds'])) + '임.',
        '3-3': '개발 기간은 %s임. 초기에는 기획과 설계를 진행함. 중반에는 개발과 내부 시험을 수행함. 후반에는 시범 운영과 개선을 진행할 예정임. 단계별 점검으로 일정을 관리함.' % co['development_period'],
        '4-1': '대표자 경력은 %s임. 팀 경력은 %s임. 역할은 경력에 맞게 분담함. 대표자는 사업 총괄을 담당함. 팀원은 개발과 운영을 나누어 맡음.' % (', '.join(co['representative_career']), ', '.join(co['team_careers'])),
    }
    return {'sections': [{'section_code': s['code'], 'title': s['title'], 'text': texts[s['code']]} for s in case['form']['sections']],
            'feature_list': list(feats)}


def good_w2(case):
    pts = [{'label': f['label'], 'value': float(f['value'])} for f in case['facts'] if f['unit'] != '%']
    return {'charts': [{'chart_id': 'c1', 'type': 'bar', 'title': '시장 지표', 'axis_labels': ['지표', '수치'], 'series': pts, 'source_ref': '2-1'}]}


def good_w3(case):
    funds = case['funds']
    total = sum(f['amount'] for f in funds)
    rows = [[f['label'], '{:,}원'.format(f['amount'])] for f in funds] + [['합계', '{:,}원'.format(total)]]
    return {'tables': [{'table_id': 't1', 'title': '자금 운용표', 'headers': ['항목', '금액'], 'rows': rows, 'source_ref': '3-1'},
                       {'table_id': 't2', 'title': '추진 일정표', 'headers': ['시기', '내용'], 'rows': [['1~2개월차', '기획'], ['3~4개월차', '개발']], 'source_ref': '3-3'}]}


class CaseTests(unittest.TestCase):
    def test_cases_are_consistent(self):
        self.assertEqual(len(CASES), 8)
        for c in CASES.values():
            self.assertEqual([s['code'] for s in c['form']['sections']], ['1-1', '1-2', '2-1', '2-2', '3-1', '3-3', '4-1'])
            self.assertEqual([s['section_code'] for s in c['fixed_doc']], ['1-1', '1-2', '2-1', '3-1', '3-3', '4-1'])
            self.assertLessEqual(sum(f['amount'] for f in c['funds']), c['announcement']['support_amount_max'])
        self.assertEqual(sum(1 for c in CASES.values() if c['form']['max_chars_per_section']), 4)

    def test_prompts_and_schemas(self):
        c = CASES['st01']
        self.assertIn('지원규모 상한', prompt.build_w1(c)[1]['content'])
        self.assertIn('자금 운용 계획', prompt.build_w2(c)[1]['content'])
        self.assertEqual(prompt.w1_schema()['schema']['required'], ['sections', 'feature_list'])


class ParserTests(unittest.TestCase):
    def test_korean_numbers(self):
        v = lambda t: [(n['value'], n['unit']) for n in score.parse_numbers(t)]
        self.assertEqual(v('약 1만 1천 곳'), [(11000.0, '곳')])
        self.assertEqual(v('380만 가구'), [(3800000.0, '가구')])
        self.assertEqual(v('5천만 원'), [(50000000.0, '원')])
        self.assertEqual(v('45,000,000원'), [(45000000.0, '원')])
        self.assertEqual(v('2026-11-30 마감'), [])                          # 날짜는 뺀다
        self.assertTrue(score._skippable(score.parse_numbers('3개월차')[0]))  # 시간 단위는 검사에서 뺀다

    def test_section_numbers(self):
        c = CASES['st02']
        inv, car = score.section_numbers('2-1', '반려견 양육 가구는 380만 가구임. 시장은 5,000억 원임.', c)
        self.assertEqual((len(inv), car), (1, []))
        self.assertEqual(score.section_numbers('4-1', '수의사 9년, 개발 12년 경력임.', c)[1], ['12년'])
        self.assertEqual(score.section_numbers('3-1', '인건비 999,000,000원임.', c), ([], []))    # 자금 섹션은 따로 본다


class ScoreTests(unittest.TestCase):
    def test_w1_good_and_violations(self):
        c = CASES['st02']
        g = score.eval_w1(good_w1(c), c)
        self.assertTrue(g['valid'] and g['hard_ok'], g)
        self.assertEqual((g['invented'], g['invented_career'], g['banned'], g['over']), (0, 0, 0, 0))
        self.assertEqual(g['coverage'], 1.0)
        self.assertEqual(g['facts_used'], 1.0)

        d = good_w1(c)
        d['sections'] = d['sections'][:-1]                                    # 팀 구성 섹션 누락
        self.assertEqual(score.eval_w1(d, c)['missing'], 1)
        d = good_w1(c)
        d['feature_list'] = d['feature_list'][:-1]
        self.assertFalse(score.eval_w1(d, c)['list_same'])
        d = good_w1(c)
        d['sections'][6]['text'] += ' 공동창업자는 10년 이상 경력을 보유함.'
        self.assertEqual(score.eval_w1(d, c)['invented_career'], 1)
        d = good_w1(c)
        d['sections'][4]['text'] = '총 지원금 120,000,000원을 사용할 계획임.'   # 상한 1억 초과
        self.assertTrue(score.eval_w1(d, c)['fund_over'])
        d = good_w1(c)
        d['sections'][1]['text'] += ' 획기적인 서비스이다.'
        e = score.eval_w1(d, c)
        self.assertEqual(e['banned'], 1)
        self.assertGreater(e['bad_end_rate'], 0)
        d = good_w1(c)
        d['sections'][0]['text'] += ' 시장은 매년 25% 성장함.'
        self.assertEqual(score.eval_w1(d, c)['invented'], 1)

    def test_schedule_over(self):
        self.assertFalse(score.schedule_over('개발 기간은 8개월임. 1~2개월차 기획, 7~8개월차 시범 운영함.', '8개월'))
        self.assertTrue(score.schedule_over('1~2개월차 기획. 9~12개월차 확산함.', '8개월'))
        c = CASES['st02']
        d = good_w1(c)
        self.assertFalse(score.eval_w1(d, c)['sched_over'])
        d['sections'][5]['text'] += ' 9~12개월차에는 확산을 진행함.'
        self.assertTrue(score.eval_w1(d, c)['sched_over'])
        self.assertTrue(score.eval_w1(d, c)['hard_ok'])            # 관찰 지표라 필수 규칙 통과에는 영향 없음

    def test_w1_max_chars(self):
        c = CASES['st01']                                                     # 분량 700자 제한
        d = good_w1(c)
        d['sections'][0]['text'] = '문제 인식 내용임. ' * 100
        self.assertEqual(score.eval_w1(d, c)['over'], 1)
        self.assertEqual(score.eval_w1(good_w1(CASES['st05']), CASES['st05'])['over'], 0)   # 제한 없는 아이템

    def test_fund_check_handles_cap_and_total_mentions(self):
        M = 100000000
        # 상한 언급 + 항목 + 합계 언급 (실제 모델 응답 모양): 항목 합 1억 → 초과 아님
        self.assertEqual(score.fund_check([1e8, 6e7, 2e7, 1e7, 1e7, 1e8], M), (1e8, False))
        self.assertEqual(score.fund_check([4e7, 3e7, 2e7, 9e7], M), (9e7, False))                # 항목 + 합계
        self.assertEqual(score.fund_check([1e8, 4e7, 3e7, 2e7], M), (9e7, False))                # 상한 언급 + 항목 합 9천만 → 총액은 항목 합
        self.assertEqual(score.fund_check([6e7, 5e7], M), (1.1e8, True))                         # 항목만, 합이 상한 초과
        self.assertEqual(score.fund_check([1.2e8, 6e7, 6e7], M), (1.2e8, True))                  # 총액이 상한 초과
        self.assertEqual(score.fund_check([], M), (None, False))
        self.assertEqual(score.fund_check([4.9e7, 5e7, 2e7, 1.2e7, 1.2e7, 5e6, 4.9e7], 5e7), (4.9e7, False))   # 총액 49M + 상한 50M 언급
        self.assertEqual(score.fund_check([1e8, 1e8], M), (1e8, False))                          # 상한만 두 번 언급
        self.assertFalse(score.fund_check([1e8, 5e7, 3e7, 2e7, 2.5e7], M, exclude=(2.5e7,))[1])   # 제품 단가는 항목이 아님(초과 아님)

    def test_range_prefix_and_pie_remainder(self):
        c = CASES['st02']
        self.assertEqual(score.section_numbers('3-3', '11~12개월차: 확산 진행함. 9~10개월차: 개선함.', c), ([], []))
        d = good_w2(c)
        d['charts'][0]['series'] = [{'label': '이용 경험', 'value': 14.0}, {'label': '이용 경험 없음', 'value': 86.0}]   # 100-14
        self.assertTrue(score.eval_w2(d, c)['ok'])
        d['charts'][0]['series'][1]['value'] = 80.0                                                                    # 계산이 안 맞으면 실패
        self.assertEqual(score.eval_w2(d, c)['invented'], 1)

    def test_w3_amount_column_and_small_counts(self):
        c = CASES['st02']
        d = good_w3(c)
        d['tables'][0]['headers'] = ['항목', '금액', '세부 내용']
        d['tables'][0]['rows'] = [r + ['설명'] for r in d['tables'][0]['rows'][:-1]] + [['합계', '95,000,000원', '지원규모 상한 100,000,000원 이내']]
        self.assertTrue(score.eval_w3(d, c)['ok'])               # 세부 내용 칸의 상한 문구를 합계로 읽지 않는다
        self.assertEqual(score.section_numbers('1-1', '보호자 1명과 수의사 3명이 참여함.', c), ([], []))

    def test_w2_source_ref_formats(self):
        c = CASES['st02']
        for ref in ('2-1', '[2-1]', '섹션 2-1', 'S2-1'):
            d = good_w2(c)
            d['charts'][0]['source_ref'] = ref
            self.assertTrue(score.eval_w2(d, c)['ok'], ref)
        d = good_w2(c)
        d['charts'][0]['source_ref'] = '[9-9]'
        self.assertFalse(score.eval_w2(d, c)['ok'])

    def test_w2(self):
        c = CASES['st02']
        self.assertTrue(score.eval_w2(good_w2(c), c)['ok'])
        bad = good_w2(c)
        bad['charts'][0]['series'][0]['value'] = 380                          # 단위 환산은 본문에 없는 수치
        self.assertEqual(score.eval_w2(bad, c)['invented'], 1)
        bad = good_w2(c)
        bad['charts'][0]['axis_labels'] = ['지표', '']
        bad['charts'][0]['source_ref'] = '9-9'
        e = score.eval_w2(bad, c)
        self.assertEqual((e['bad_axis'], e['bad_ref'], e['ok']), (1, 1, False))
        self.assertFalse(score.eval_w2({'charts': []}, c)['ok'])

    def test_w3(self):
        c = CASES['st02']
        self.assertTrue(score.eval_w3(good_w3(c), c)['ok'])
        bad = good_w3(c)
        bad['tables'][0]['rows'][-1][1] = '90,000,000원'                       # 합계 ≠ 항목 합
        self.assertTrue(score.eval_w3(bad, c)['sum_mismatch'])
        bad = good_w3(c)
        bad['tables'][0]['rows'] = [['인건비', '99,000,000원'], ['개발', '30,000,000원']]      # 합 129M > 상한 100M, 본문에 없는 금액
        e = score.eval_w3(bad, c)
        self.assertTrue(e['over'])
        self.assertGreaterEqual(e['invented_amounts'], 1)
        bad = good_w3(c)
        bad['tables'][1]['rows'][0] = ['1~2개월차']                            # 칸 수 불일치
        self.assertEqual(score.eval_w3(bad, c)['row_bad'], 1)
        bad = good_w3(c)
        bad['tables'] = bad['tables'][:1]
        self.assertFalse(score.eval_w3(bad, c)['has_sched'])


class RunTests(unittest.TestCase):
    def setUp(self):
        self.cands = oc.load_candidates(['luna-medium', 'gpt-4.1-mini'])

    def test_jobs_and_estimate(self):
        jobs = run.make_jobs(self.cands, CASES, 3)
        self.assertEqual(len(jobs), 2 * 8 * 3 * 3)
        self.assertEqual({j['plan'] for j in jobs}, {'w1', 'w2', 'w3'})
        self.assertGreater(v1run.estimate(jobs)['luna-medium']['usd'], 0)

    def test_end_to_end_with_fake_model_and_judge(self):
        def fake(cand, messages):
            sys_p, text = messages[0]['content'], messages[1]['content']
            usage = {'in': 1500, 'out': 900, 'reasoning': None, 'ms': 2000, 'model': cand['model']}
            if sys_p == jprompt.SYSTEM:                                      # 채점자
                codes = [i['item_code'] for i in json.loads(json.dumps([{'item_code': k} for k in ('E1', 'E2', 'E3', 'E4', 'E5')]))]
                return {'items': [{'item_code': k, 'score': 12.0 if k != 'E5' else 8.0, 'evidence_locator': '없음', 'comment': 'x'} for k in codes]}, usage
            case = next(c for c in CASES.values() if c['item_spec']['one_line_summary'] in text)
            if sys_p == prompt.W1_SYSTEM:
                d = good_w1(case)
                if cand['id'] == 'gpt-4.1-mini' and case['case_id'] == 'st01':
                    d['sections'][6]['text'] += ' 대표자는 15년 경력을 보유함.'      # 지어낸 경력
                return d, usage
            return (good_w2(case) if sys_p == prompt.W2_SYSTEM else good_w3(case)), usage
        jobs = run.make_jobs(self.cands, CASES, 2)
        from v1_verifier import variants as jv
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            v1run.run_jobs(jobs, fake, out / 'calls.jsonl', set(), 1)
            jj = run.make_judge_jobs(run.load_rows(out), self.cands[0], jv.load_rubric())
            self.assertEqual(len(jj), 2 * 8 * 2)                              # 본문 호출마다 하나
            v1run.run_jobs(jj, fake, out / 'judge.jsonl', set(), 1)
            (out / 'meta.json').write_text(json.dumps({'candidates': self.cands, 'reps': 2, 'judge': 'luna-medium'}, ensure_ascii=False), encoding='utf-8')
            run.write_outputs(out)
            judge, _ = run.load_judge(out)
            m = score.compute(run.load_rows(out), CASES, judge)
            self.assertEqual(m['luna-medium']['w1_hard_ok'], 1.0)
            self.assertAlmostEqual(m['gpt-4.1-mini']['w1_hard_ok'], 7 / 8)      # st01 만 지어낸 경력
            self.assertEqual(m['gpt-4.1-mini']['w1_career_calls'], 2)
            self.assertAlmostEqual(m['luna-medium']['judge'], 56.0)
            self.assertEqual(m['luna-medium']['w2_ok'], 1.0)
            self.assertEqual(m['luna-medium']['w3_ok'], 1.0)
            self.assertIn('지어낸 경력', (out / 'summary.md').read_text(encoding='utf-8'))
            html = (out / 'report.html').read_text(encoding='utf-8')
            self.assertNotIn('__DATA__', html)
            payload = report.build_payload(out, CASES, run.load_rows(out), judge)
            w1 = next(c for c in payload['calls'] if c['task'] == 'w1' and c['cand'] == 'gpt-4.1-mini' and c['case'] == 'st01')
            self.assertEqual(w1['sections'][6]['career'], ['15년'])

    def test_failure_is_recorded(self):
        jobs = run.make_jobs(self.cands[:1], CASES, 1, ['st01'], ('w1',))

        def boom(cand, messages):
            raise RuntimeError('호출 실패')
        with tempfile.TemporaryDirectory() as tmp:
            v1run.run_jobs(jobs, boom, Path(tmp) / 'calls.jsonl', set(), 1)
            rows = run.load_rows(Path(tmp))
            self.assertTrue(all(not r['ok'] for r in rows))
            self.assertIn('실패·형식 불량', score.summarize(rows, CASES))


class PlanOnlyTest(unittest.TestCase):
    def test_default_makes_no_calls_and_no_report_folder(self):
        before = set((ROOT / 'reports').iterdir())
        self.assertEqual(run.main(['--candidates', 'luna-medium', '--reps', '1']), 0)
        self.assertEqual(set((ROOT / 'reports').iterdir()), before)

    def test_budget_guard(self):
        self.assertEqual(run.main(['--execute', '--max-usd', '0.0001']), 2)


if __name__ == '__main__':
    unittest.main()
