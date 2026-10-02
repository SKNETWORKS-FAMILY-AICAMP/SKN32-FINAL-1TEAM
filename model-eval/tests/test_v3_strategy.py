"""전략 T-S1·T-S2 실험 골격 테스트 — 가짜 모델로 돌린다(API 호출 없음)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clients import openai_compat as oc  # noqa: E402
from v1_verifier import run as v1run  # noqa: E402
from v3_strategy import prompt, report, run, score  # noqa: E402

CASES = prompt.load_cases()


def s1_answer(case, style='exact'):
    core = list(case['item_spec']['core_features'])
    if style == 'para':
        core = [c.replace(' ', '') + ' 기능' for c in core]        # 글자는 달라졌지만 같은 기능
    if style == 'extra':
        core = core + ['전혀 새로운 기능']
    if style == 'missing':
        core = core[:-1]
    return {'problem_statement': '문제', 'target_customer': '고객', 'feature_list': core, 'differentiator': '차별점', 'use_cases': ['장면']}


def s2_answer(case, mode):
    f = case['facts']
    ms = []
    if mode in ('facts', 'all'):
        ms += [{'label': x['label'], 'value': x['value'], 'unit': x['unit'], 'source_name': x['source'], 'source_url': '', 'basis': '자료'} for x in f]
    if mode == 'trap':
        t = case['trap']
        ms += [{'label': t['label'], 'value': t['value'], 'unit': t['unit'], 'source_name': t['source'], 'source_url': '', 'basis': '자료'}]
    if mode == 'made_up':
        ms += [{'label': '지어낸 규모', 'value': 123456, 'unit': '곳', 'source_name': '', 'source_url': '', 'basis': '추정'}]
    return {'market_definition': '시장', 'market_size': ms, 'competitors': ['대체재'], 'positioning': '포지션'}


class CaseTests(unittest.TestCase):
    def test_cases_are_consistent(self):
        self.assertEqual(len(CASES), 8)
        for c in CASES.values():
            self.assertEqual(len(c['facts']), 3)
            self.assertNotIn(c['trap']['label'], [f['label'] for f in c['facts']])
            self.assertGreaterEqual(len(c['item_spec']['core_features']), 3)
            for f in c['facts'] + [c['trap']]:
                self.assertGreater(f['value'], 0)
                self.assertTrue(f['source'].split()[0])

    def test_schema_and_prompts(self):
        c = next(iter(CASES.values()))
        self.assertIn('참고 자료', prompt.build_s2(c, 'facts')[1]['content'])
        self.assertNotIn('참고 자료', prompt.build_s2(c, 'open')[1]['content'])
        # 함정 자료는 참고 자료 목록 안에 함께 들어간다(순서로 구별할 수 없다)
        self.assertIn(c['trap']['display'], prompt.build_s2(c, 'facts')[1]['content'])
        self.assertEqual(prompt.s1_schema()['schema']['required'], list(prompt.s1_schema()['schema']['properties']))


class ScoreTests(unittest.TestCase):
    def setUp(self):
        self.c = CASES['st02']

    def test_s1_exact_paraphrase_extra_missing(self):
        e = score.eval_s1(s1_answer(self.c), self.c)
        self.assertTrue(e['strict'] and e['lenient'] and not e['paraphrased'] and e['extras'] == 0)
        p = score.eval_s1(s1_answer(self.c, 'para'), self.c)
        self.assertFalse(p['strict'])
        self.assertTrue(p['lenient'] and p['paraphrased'])
        self.assertEqual(score.eval_s1(s1_answer(self.c, 'extra'), self.c)['extras'], 1)
        m = score.eval_s1(s1_answer(self.c, 'missing'), self.c)
        self.assertFalse(m['lenient'])
        self.assertEqual(m['missing'], 1)
        self.assertFalse(score.eval_s1({'feature_list': []}, self.c)['valid'])

    def test_value_units(self):
        f = {'value': 3800000}
        self.assertTrue(score.matches({'value': 3800000, 'unit': '가구'}, f))
        self.assertTrue(score.matches({'value': 380, 'unit': '만 가구'}, f))
        self.assertFalse(score.matches({'value': 380, 'unit': '가구'}, f))
        self.assertTrue(score.matches({'value': 0.14, 'unit': '%'}, {'value': 14}))
        self.assertTrue(score.matches({'value': 30, 'unit': '조 원'}, {'value': 30000000000000}))

    def test_s2_facts_modes(self):
        ok = score.eval_s2(s2_answer(self.c, 'facts'), self.c, 'facts')
        self.assertEqual((ok['used'], ok['trap'], ok['other'], ok['misattributed']), (3, 0, 0, 0))
        self.assertEqual(ok['unlisted_numbers'], 0)
        tr = score.eval_s2(s2_answer(self.c, 'trap'), self.c, 'facts')
        self.assertEqual(tr['trap'], 1)
        mu = score.eval_s2(s2_answer(self.c, 'made_up'), self.c, 'facts')
        self.assertEqual((mu['other'], mu['unsourced']), (1, 1))
        bad = s2_answer(self.c, 'facts')
        bad['market_size'][0]['source_name'] = '어느 블로그'
        self.assertEqual(score.eval_s2(bad, self.c, 'facts')['misattributed'], 1)

    def test_derived_values_and_trap_disclaimer(self):
        c = CASES['st03']                       # 음식점 79만 · 4인 이하 84% · 디지털 발주 11%
        base = {'label': 'x', 'unit': '곳', 'source_name': '통계청', 'source_url': '', 'basis': '근거'}
        one = score.classify_items([dict(base, value=663600), dict(base, value=72996), dict(base, value=590604), dict(base, value=123457)], c)
        self.assertEqual([i['status'] for i in one], ['derived', 'derived', 'derived', 'other'])   # 79만×84%, ×11%, ×(1-11%)
        t = score.classify_items([dict(base, value=30, unit='조 원', basis='직접 시장이 아니라 인접 시장 규모'),
                                  dict(base, value=30, unit='조 원', basis='시장 규모')], c)
        self.assertEqual([(i['status'], i['disclaimed']) for i in t], [('trap', True), ('trap', False)])
        ev = score.eval_s2({'market_definition': '', 'market_size': [dict(base, value=30, unit='조 원', basis='시장 규모')],
                            'competitors': [], 'positioning': ''}, c, 'facts')
        self.assertEqual((ev['trap'], ev['trap_plain']), (1, 1))

    def test_s2_open_counts(self):
        o = score.eval_s2(s2_answer(self.c, 'made_up'), self.c, 'open')
        self.assertEqual((o['n_items'], o['unsourced'], o['hedged']), (1, 1, 1))
        self.assertEqual(score.eval_s2(s2_answer(self.c, 'none'), self.c, 'open')['n_items'], 0)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.cands = oc.load_candidates(['luna-medium', 'gpt-4.1-mini'])

    def test_jobs_kinds_and_estimate(self):
        jobs = run.make_jobs(self.cands, CASES, 3)
        self.assertEqual(len(jobs), 2 * 8 * 3 * 3)           # 후보 × 아이템 × (s1, s2 facts, s2 open) × 반복
        self.assertEqual({(j['extra']['task'], j['extra']['cond']) for j in jobs}, {('s1', 'na'), ('s2', 'facts'), ('s2', 'open')})
        self.assertGreater(v1run.estimate(jobs)['luna-medium']['usd'], 0)
        self.assertEqual(len(run.make_jobs(self.cands, CASES, 1, tasks=('s1',))), 2 * 8)

    def test_end_to_end_with_fake_model(self):
        by_sys = {}

        def fake(cand, messages):
            text = messages[1]['content']
            case = next(c for c in CASES.values() if c['item_spec']['item_name'] in text)
            if messages[0]['content'] == prompt.S1_SYSTEM:
                ans = s1_answer(case, 'para' if case['case_id'] == 'st01' else 'exact')
            else:
                ans = s2_answer(case, 'all' if '[참고 자료]' in text else 'none')
                if case['case_id'] == 'st02' and '[참고 자료]' in text:
                    ans = s2_answer(case, 'trap')
            by_sys[messages[0]['content']] = 1
            return ans, {'in': 900, 'out': 400, 'reasoning': None, 'ms': 1000, 'model': cand['model']}
        jobs = run.make_jobs(self.cands, CASES, 2)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            v1run.run_jobs(jobs, fake, out / 'calls.jsonl', set(), 1)
            (out / 'meta.json').write_text(json.dumps({'candidates': self.cands, 'reps': 2}, ensure_ascii=False), encoding='utf-8')
            run.write_outputs(out)
            self.assertEqual(len(by_sys), 2)
            m = score.compute(run.load_rows(out), CASES)['luna-medium']
            self.assertAlmostEqual(m['s1_strict'], 7 / 8)              # st01 만 말을 바꿈
            self.assertEqual(m['s1_paraphrased'], 2)                    # st01 × 반복 2
            self.assertEqual(m['f_trap_calls'], 2)                      # st02 × 반복 2
            self.assertEqual(m['o_zero_calls'], m['o_n'])               # 자료 없으면 수치 없이 서술
            self.assertTrue((out / 'report.html').exists())
            html = (out / 'report.html').read_text(encoding='utf-8')
            self.assertNotIn('__STYLE__', html)
            self.assertNotIn('__DATA__', html)
            payload = report.build_payload(out, CASES, run.load_rows(out))
            self.assertEqual(len(payload['cases']), 8)

    def test_failure_is_recorded(self):
        jobs = run.make_jobs(self.cands[:1], CASES, 1, ['st01'], ('s1',))

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
