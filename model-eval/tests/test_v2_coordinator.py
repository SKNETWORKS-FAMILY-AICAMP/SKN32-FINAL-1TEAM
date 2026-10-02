"""조율 T-C1 실험 골격 테스트 — 가짜 모델로 돌린다(API 호출 없음)."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clients import openai_compat as oc  # noqa: E402
from v1_verifier import run as v1run  # noqa: E402
from v2_coordinator import prompt, report, run, score  # noqa: E402

CATS = ['원페이지', '웹개발', 'AI_API']


def fake_factory(mistakes=None):
    """정답 카테고리를 그대로 내는 가짜 모델. mistakes = {사례 id: 틀린 답}."""
    cases = run.load_cases()
    by_text = {c['form']['idea_text']: c for c in cases.values()}
    mistakes = mistakes or {}

    def fake(cand, messages):
        idea = messages[1]['content'].split('아이템 설명: ')[1].split('\n')[0]
        case = by_text[idea]
        cat = mistakes.get(case['case_id'], case['expected'])
        return ({'item_name': '이름', 'one_line_summary': '한 줄 요약', 'target_customer': '고객',
                 'core_features': ['기능 하나'], 'keywords': ['키워드'], 'category': cat,
                 'category_reason': '이유', 'confidence': 0.9 if cat == case['expected'] else 0.85},
                {'in': 700, 'out': 300, 'reasoning': None, 'ms': 1500, 'model': cand['model']})
    return fake


class CaseTests(unittest.TestCase):
    def test_cases_are_consistent(self):
        cases = run.load_cases()
        self.assertEqual(len(cases), 32)
        for c in cases.values():
            self.assertIn(c['expected'], CATS)
            self.assertIn(c['expected'], c['accept'])
            self.assertTrue(set(c['accept']) <= set(CATS))
            self.assertIn(c['kind'], ('clear', 'boundary', 'injection'))
            self.assertEqual(len(c['accept']) == 2, c['kind'] == 'boundary')
        for cat in CATS:
            self.assertGreaterEqual(sum(1 for c in cases.values() if c['expected'] == cat and c['kind'] == 'clear'), 9)

    def test_schema_enum_matches_categories(self):
        self.assertEqual(prompt.output_schema()['schema']['properties']['category']['enum'], CATS)


class ScoreTests(unittest.TestCase):
    def test_check_format(self):
        ok = fake_factory()({'model': 'x'}, prompt.build_messages(next(iter(run.load_cases().values()))['form']))[0]
        self.assertIsNone(score.check_format(ok))
        self.assertIn('필드 누락', score.check_format({k: v for k, v in ok.items() if k != 'keywords'}))
        self.assertIn('카테고리', score.check_format(dict(ok, category='기타')))
        self.assertIn('core_features', score.check_format(dict(ok, core_features=[])))
        self.assertIn('confidence', score.check_format(dict(ok, confidence=1.5)))

    def test_invented_numbers(self):
        form = {'idea_text': '월 3만 원 구독', 'revenue_unit_price': 30000, 'development_period': '5개월',
                'team_careers': ['개발 3년'], 'facilities': '없음'}
        base = {'item_name': 'a', 'one_line_summary': '5개월 만에 3만 원', 'target_customer': 'c', 'core_features': ['x'], 'keywords': []}
        self.assertEqual(score.invented_numbers(base, form), 0)
        self.assertEqual(score.invented_numbers(dict(base, one_line_summary='시장 규모 2조 원, 성장률 40%'), form), 2)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.cands = oc.load_candidates(['luna-medium', 'gpt-4.1-mini'])
        self.cases = run.load_cases()

    def test_jobs_and_estimate(self):
        jobs = run.make_jobs(self.cands, self.cases, 3)
        self.assertEqual(len(jobs), 2 * 32 * 3)
        self.assertGreater(v1run.estimate(jobs)['luna-medium']['usd'], 0)

    def test_end_to_end_with_fake_model(self):
        jobs = run.make_jobs(self.cands, self.cases, 2)
        for j in jobs:
            j['plan'], j['variant'] = 'tc1', j['case']
        # inj01 은 지시문에 속아 AI_API 로, bd01 은 허용 범위 밖으로 답하는 가짜 모델
        fake = fake_factory({'inj01': 'AI_API', 'bd01': 'AI_API'})
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            v1run.run_jobs(jobs, fake, out / 'calls.jsonl', set(), 1)
            (out / 'meta.json').write_text('{"candidates": %s, "reps": 2}' % __import__('json').dumps(self.cands, ensure_ascii=False), encoding='utf-8')
            run.write_outputs(out)
            text = (out / 'summary.md').read_text(encoding='utf-8')
            self.assertIn('틀린 호출', text)
            self.assertIn('inj01', text)
            self.assertTrue((out / 'report.html').exists())
            m = score.compute(run.load_rows(out), self.cases)['luna-medium']
            self.assertEqual(m['acc_injection'], 0.5)          # 삽입 2건 중 1건만 맞음
            self.assertEqual(m['acc_boundary'], 2 / 3)         # 경계 3건 중 bd01 틀림
            self.assertEqual(m['acc_clear'], 1.0)
            self.assertEqual(m['stable'], 1.0)
            self.assertEqual(m['overconfident'], 4)            # 틀린 4호출(2사례×2회) 모두 확신 0.85
            payload = report.build_payload(out, self.cases, run.load_rows(out))
            self.assertEqual(len(payload['cases']), 32)

    def test_failure_is_recorded_not_raised(self):
        jobs = run.make_jobs(self.cands[:1], self.cases, 1, ['op01'])
        for j in jobs:
            j['plan'], j['variant'] = 'tc1', j['case']

        def boom(cand, messages):
            raise RuntimeError('호출 실패')
        with tempfile.TemporaryDirectory() as tmp:
            v1run.run_jobs(jobs, boom, Path(tmp) / 'calls.jsonl', set(), 1)
            rows = run.load_rows(Path(tmp))
            self.assertTrue(all(not r['ok'] for r in rows))
            self.assertIn('실패·형식 불량', score.summarize(rows, self.cases))


class PlanOnlyTest(unittest.TestCase):
    def test_default_makes_no_calls_and_no_report_folder(self):
        before = set((ROOT / 'reports').iterdir())
        self.assertEqual(run.main(['--candidates', 'luna-medium', '--reps', '1']), 0)
        self.assertEqual(set((ROOT / 'reports').iterdir()), before)

    def test_budget_guard(self):
        self.assertEqual(run.main(['--execute', '--max-usd', '0.0001']), 2)


if __name__ == '__main__':
    unittest.main()
