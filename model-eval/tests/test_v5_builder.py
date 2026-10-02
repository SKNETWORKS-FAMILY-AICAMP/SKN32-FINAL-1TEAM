"""구현 T-B1·T-B2 실험 골격 테스트 — 가짜 모델로 돌린다(API 호출 없음)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clients import openai_compat as oc  # noqa: E402
from v1_verifier import run as v1run  # noqa: E402
from v5_builder import checks as C, prompt, report, run, score  # noqa: E402

CASES = prompt.load_cases()
CASE = CASES['st03']                                            # 웹개발


def good_html(case=CASE):
    feats = ''.join('<section><h2>%s</h2><p>%s 기능을 시연합니다. 아래 버튼으로 결과를 확인하세요.</p></section>' % (f, f) for f in case['item_spec']['core_features'])
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>%s</title><style>:root{--fg:#111;--bg:#fff}'
            'body{color:var(--fg);background:var(--bg)} .btn{background:#1a4d8f;color:#fff}</style></head><body><h1>%s</h1>%s'
            '<label for="f">재고 사진</label><input id="f" type="file"><button class="btn">실행</button></body></html>') % (
        case['item_spec']['item_name'], case['item_spec']['item_name'], feats)


BAD_HTML = ('<html><head><script src="https://cdn.tailwindcss.com"></script><style>body{color:#aaa;background:#fff}</style></head>'
            '<body><h3>제목</h3><img src="x.png"><input type="text"><script>const api_key="sk-abcdefghijklmnopqrstuvwxyz123456";</script>텍스트 텍스트 텍스트 텍스트</body></html>')


def good_svg(case=CASE):
    s, co = case['item_spec'], case['company']
    texts = [(48, s['item_name']), (28, s['target_customer']), (20, s['one_line_summary']), (20, ' · '.join(s['core_features'])),
             (18, '수익모델 단가 {:,}원'.format(co['revenue_unit_price'])), (16, '개발 기간 %s · 접수 마감 %s' % (co['development_period'], case['announcement']['apply_end']))]
    body = ''.join('<text x="60" y="%d" font-size="%d" fill="#111">%s</text>' % (100 + 60 * i, sz, t) for i, (sz, t) in enumerate(texts))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 800"><title>%s</title><desc>설명</desc>'
            '<rect width="1200" height="800" fill="#ffffff"/>%s</svg>') % (s['item_name'], body)


class CheckerTests(unittest.TestCase):
    def test_extract_code(self):
        self.assertIn('<h1>', C.extract_code('설명\n```html\n<!doctype html><html><body><h1>x</h1></body></html>\n```\n끝', 'html'))
        self.assertEqual(C.extract_code('<svg viewBox="0 0 1 1"><text>a</text></svg> 뒤', 'svg'), '<svg viewBox="0 0 1 1"><text>a</text></svg>')
        self.assertIsNone(C.extract_code('코드가 없음', 'html'))
        self.assertIsNone(C.extract_code('코드가 없음', 'svg'))

    def test_contrast_math(self):
        self.assertAlmostEqual(C.contrast((0, 0, 0), (255, 255, 255)), 21.0, places=1)
        self.assertLess(C.contrast(C.parse_color('#aaa'), (255, 255, 255)), 4.5)
        self.assertEqual(C.parse_color('var(--x)', {'--x': '#fff'}), (255, 255, 255))
        self.assertIsNone(C.parse_color('linear-gradient(red, blue)'))

    def test_good_html_full_score(self):
        r = C.html_checks(good_html(), CASE)
        self.assertEqual(r['code'], 15, [c for c in r['checks'] if not c['ok']])
        self.assertEqual(r['features']['score'], 15)

    def test_bad_html_fails_each_item(self):
        r = C.html_checks(BAD_HTML, CASE)
        fails = {c['no'] for c in r['checks'] if not c['ok']}
        self.assertEqual(fails, {1, 2, 3, 4, 5, 6, 8})            # 7(안내 문서)은 규칙 모듈이라 자동 통과
        self.assertEqual(r['code'], 0)                             # 진입 파일 미충족이면 코드 점수 0
        self.assertEqual(r['external'], ['https://cdn.tailwindcss.com'])
        self.assertEqual(r['features']['score'], 3)                # 기능 3개 모두 누락 → 15-12

    def test_html_individual_checks(self):
        no_lang = good_html().replace(' lang="ko"', '')
        self.assertFalse(C.html_checks(no_lang, CASE)['checks'][3]['ok'])
        skip = good_html().replace('<h2>', '<h4>', 1).replace('</h2>', '</h4>', 1)
        self.assertFalse(C.html_checks(skip, CASE)['checks'][5]['ok'])          # h1 → h4
        nolabel = good_html().replace('<label for="f">재고 사진</label>', '')
        self.assertFalse(C.html_checks(nolabel, CASE)['checks'][2]['ok'])
        aria = nolabel.replace('<input id="f"', '<input aria-label="사진"')
        self.assertTrue(C.html_checks(aria, CASE)['checks'][2]['ok'])
        lowc = good_html().replace('.btn{background:#1a4d8f;color:#fff}', '.btn{background:#ffffff;color:#cccccc}')
        self.assertFalse(C.html_checks(lowc, CASE)['checks'][4]['ok'])
        missing = good_html().replace(CASE['item_spec']['core_features'][0], '다른 내용')
        self.assertEqual(len(C.html_checks(missing, CASE)['features']['missing']), 1)

    def test_svg_good_and_bad(self):
        r = C.svg_checks(good_svg(), CASE, '웹개발')
        self.assertEqual(r['code'], 15, [c for c in r['checks'] if not c['ok']])
        self.assertTrue(all(i['ok'] for i in r['info']))
        bad = good_svg().replace('<title>%s</title><desc>설명</desc>' % CASE['item_spec']['item_name'], '')
        self.assertFalse(C.svg_checks(bad, CASE, '웹개발')['checks'][1]['ok'])
        raster = good_svg().replace('</svg>', '<image href="data:image/png;base64,AAAA" width="10" height="10"/></svg>')
        self.assertFalse(C.svg_checks(raster, CASE, '웹개발')['checks'][5]['ok'])
        flat = good_svg()
        for sz in ('48', '28', '18', '16'):
            flat = flat.replace('font-size="%s"' % sz, 'font-size="20"')
        self.assertFalse(C.svg_checks(flat, CASE, '웹개발')['checks'][4]['ok'])     # 글자 크기 단계 부족
        tiny = good_svg().replace('font-size="16"', 'font-size="9"')
        self.assertFalse(C.svg_checks(tiny, CASE, '웹개발')['checks'][6]['ok'])
        low = good_svg().replace('fill="#111"', 'fill="#ddd"')
        self.assertFalse(C.svg_checks(low, CASE, '웹개발')['checks'][3]['ok'])
        broken = C.svg_checks('<svg><text>', CASE, '웹개발')
        self.assertEqual(broken['code'], 0)

    def test_problem_label_and_gradient_background(self):
        # 문제 정의: '문제 정의' 이름표 + 내용 글자면 인정(한 줄 설명과 달라도)
        svg = good_svg().replace('<text x="60" y="220" font-size="20" fill="#111">%s</text>' % CASE['item_spec']['one_line_summary'],
                                 '<text x="60" y="200" font-size="20" fill="#111">문제 정의</text><text x="60" y="230" font-size="20" fill="#111">재고 관리와 발주가 번거롭고 예측이 어려움</text>')
        info = {i['name']: i['ok'] for i in C.svg_checks(svg, CASE, '웹개발')['info']}
        self.assertTrue(info['문제 정의'])
        # 그라데이션 배경 위 흰 글자: 배경을 못 읽으니 판정하지 않는다(흰 배경으로 잘못 가정해 실패시키지 않는다)
        grad = good_svg().replace('<rect width="1200" height="800" fill="#ffffff"/>',
                                  '<defs><linearGradient id="bg"><stop offset="0" stop-color="#001"/><stop offset="1" stop-color="#013"/></linearGradient></defs><rect width="1200" height="800" fill="url(#bg)"/>'
                                  ).replace('fill="#111"', 'fill="#ffffff"')
        self.assertTrue(C.svg_checks(grad, CASE, '웹개발')['checks'][3]['ok'])

    def test_abbreviated_target_and_line_broken_problem(self):
        svg = good_svg().replace(CASE['item_spec']['target_customer'], '4인 이하 식당 사장')       # 줄여 쓴 고객(이름표 없음, 40% 이상 겹침)
        self.assertTrue({i['name']: i['ok'] for i in C.svg_checks(svg, CASE, '웹개발')['info']}['목표 고객'])
        broken = good_svg().replace('<text x="60" y="220" font-size="20" fill="#111">%s</text>' % CASE['item_spec']['one_line_summary'],
                                    '<text x="60" y="200" font-size="20" fill="#111">문제 정의</text><text x="60" y="215" font-size="20" fill="#111">목표</text>'
                                    '<text x="60" y="230" font-size="20" fill="#111">재고 관리와 발주가 번거롭고 예측이 어려움</text>')
        self.assertTrue({i['name']: i['ok'] for i in C.svg_checks(broken, CASE, '웹개발')['info']}['문제 정의'])

    def test_svg_missing_info_gives_partial_credit(self):
        r = C.svg_checks(good_svg().replace('{:,}원'.format(CASE['company']['revenue_unit_price']), '무료'), CASE, '웹개발')
        item3 = r['checks'][2]
        self.assertFalse(item3['ok'])
        self.assertAlmostEqual(item3['earned'], 2 * 5 / 6, places=2)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.cands = oc.load_candidates(['codex-5.3', 'luna-medium'])

    def test_jobs_exclude_b1_for_onepage(self):
        jobs = run.make_jobs(self.cands, CASES, 1)
        b1 = [j for j in jobs if j['plan'] == 'b1']
        self.assertEqual(len(b1), 2 * 6)                           # 웹개발·AI API 6건
        self.assertEqual(len([j for j in jobs if j['plan'] == 'b2']), 2 * 8)
        self.assertFalse(any(CASES[j['variant']]['item_spec']['category'] == '원페이지' for j in b1))

    def test_b2_prompt_contains_item_name_and_required_info(self):
        m = prompt.build_b2(CASE)[1]['content']
        self.assertIn(CASE['item_spec']['item_name'], m)                     # 아이템명은 SVG 6항목 중 하나라 입력에 있어야 한다
        self.assertIn('{:,}'.format(CASE['company']['revenue_unit_price']), m)
        self.assertIn(CASE['announcement']['apply_end'], m)

    def test_candidates_registered(self):
        by = {c['id']: c for c in oc.load_candidates()}
        self.assertEqual(by['codex-5.3']['api'], 'responses')
        self.assertEqual(by['codex-5.3']['price'], [1.75, 14.0])

    def test_end_to_end_with_fake_model(self):
        def fake(cand, messages):
            text = messages[1]['content']
            case = next(c for c in CASES.values() if c['item_spec']['item_name'] in text)
            usage = {'in': 2000, 'out': 4000, 'reasoning': None, 'ms': 5000, 'model': cand['model']}
            if messages[0]['content'] == prompt.B1_SYSTEM:
                src = good_html(case) if cand['id'] == 'luna-medium' else BAD_HTML
                return {'text': '```html\n%s\n```' % src}, usage
            return {'text': '설명\n' + good_svg(case)}, usage
        jobs = run.make_jobs(self.cands, CASES, 1)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            v1run.run_jobs(jobs, fake, out / 'calls.jsonl', set(), 1)
            (out / 'meta.json').write_text(json.dumps({'candidates': self.cands, 'reps': 1}, ensure_ascii=False), encoding='utf-8')
            run.write_outputs(out)
            m = score.compute(run.load_rows(out), CASES)
            self.assertEqual(m['luna-medium']['b1_code'], 15)
            self.assertEqual(m['luna-medium']['b1_full_features'], 1.0)
            self.assertEqual(m['codex-5.3']['b1_code'], 0)
            self.assertEqual(m['codex-5.3']['b1_external'], 6)
            self.assertEqual(m['codex-5.3']['b2_code'], 15)
            self.assertEqual(m['luna-medium']['b2_info'], 1.0)
            self.assertIn('진입 파일 실패', (out / 'summary.md').read_text(encoding='utf-8'))
            html = (out / 'report.html').read_text(encoding='utf-8')
            self.assertNotIn('__DATA__', html)
            payload = report.build_payload(out, CASES, run.load_rows(out))
            self.assertEqual(len(payload['calls']), 2 * (6 + 8))
            self.assertIn('<h1>', next(c for c in payload['calls'] if c['cand'] == 'luna-medium' and c['task'] == 'b1')['src'])

    def test_no_code_in_response_is_a_format_failure(self):
        jobs = run.make_jobs(self.cands[:1], CASES, 1, ['st03'], ('b1',))
        with tempfile.TemporaryDirectory() as tmp:
            v1run.run_jobs(jobs, lambda cand, msgs: ({'text': '죄송합니다, 만들 수 없습니다.'}, {'in': 1, 'out': 1, 'reasoning': None, 'ms': 1, 'model': 'x'}),
                           Path(tmp) / 'calls.jsonl', set(), 1)
            rows = run.load_rows(Path(tmp))
            self.assertFalse(score.evaluate(rows[0], CASES['st03'])['valid'])
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
