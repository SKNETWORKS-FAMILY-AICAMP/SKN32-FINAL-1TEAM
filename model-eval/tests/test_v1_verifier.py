"""검증-1 실험 골격 테스트 — 가짜 모델로 돌린다(API 호출 없음)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clients import openai_compat as oc  # noqa: E402
from v1_verifier import prompt, run, score, variants  # noqa: E402


def fake_call_factory(noise=0.0):
    """텍스트에 담긴 내용을 보고 점수를 주는 가짜 심사위원: 섹션이 없거나 무관하면 0점."""
    rubric = variants.load_rubric()

    def fake(cand, messages):
        text = messages[1]['content'].split('[사업계획서]')[1]
        items = []
        for it in rubric['items']:
            title = {'E1': '1. 문제 인식', 'E2': '2. 해결 방안', 'E3': '3. 시장성', 'E4': '4. 실현 가능성', 'E5': '5. 팀 역량'}[it['item_code']]
            present = title in text
            bad = (it['item_code'] == 'E2' and '카페' in text) or (it['item_code'] == 'E3' and '매우 크고' in text)
            frac = 0.0 if not present else (0.2 if bad else 0.9)
            frac = frac * (0.5 if len(text) < 700 else 1)
            items.append({'item_code': it['item_code'], 'score': it['max_score'] * frac,
                          'evidence_locator': '없음', 'comment': 'x'})
        return {'items': items}, {'in': 1000, 'out': 500, 'reasoning': 100, 'ms': 1200, 'model': cand['model']}
    return fake


class VariantTests(unittest.TestCase):
    def test_variants_and_expectations(self):
        vs = {v['variant_id']: v for v in variants.build_variants(variants.load_plan('base_01'))}
        self.assertEqual(set(vs), {'original', 'drop_E3', 'drop_E5', 'unsourced_E3', 'offtopic_E2', 'halved'})
        self.assertNotIn('3. 시장성', vs['drop_E3']['text'])
        self.assertEqual(vs['offtopic_E2']['expect_lower'], ['E2'])
        self.assertLess(len(vs['halved']['text']), len(vs['original']['text']))

    def test_halve_keeps_one_sentence_at_least(self):
        self.assertEqual(variants.halve('한 문장이다.'), '한 문장이다.')
        self.assertEqual(variants.halve('가. 나. 다. 라.'), '가. 나.')


class ScoreTests(unittest.TestCase):
    def test_item_scores_rejects_missing_and_duplicate(self):
        rubric = variants.load_rubric()
        full = {'items': [{'item_code': it['item_code'], 'score': 99} for it in rubric['items']]}
        got = score.item_scores(full, rubric)
        self.assertEqual(got['E1'], 15.0)            # 상한으로 잘린다
        self.assertIsNone(score.item_scores({'items': full['items'][:-1]}, rubric))
        self.assertIsNone(score.item_scores({'items': full['items'] + [full['items'][0]]}, rubric))

    def test_schema_matches_rubric_codes(self):
        rubric = variants.load_rubric()
        enum = prompt.output_schema(rubric)['schema']['properties']['items']['items']['properties']['item_code']['enum']
        self.assertEqual(enum, ['E1', 'E2', 'E3', 'E4', 'E5'])


class RunTests(unittest.TestCase):
    def setUp(self):
        self.cands = oc.load_candidates(['luna-medium', 'gpt-4.1-mini'])

    def test_estimate_and_jobs(self):
        jobs = run.make_jobs(self.cands, ['base_01'], 3, None)
        self.assertEqual(len(jobs), 2 * 6 * 3)
        est = run.estimate(jobs)
        self.assertEqual(est['luna-medium']['calls'], 18)
        self.assertGreater(est['luna-medium']['usd'], 0)

    def test_request_options(self):
        self.assertEqual(oc.request_options(self.cands[0]), {'reasoning_effort': 'medium'})
        self.assertEqual(oc.request_options(self.cands[1]), {'temperature': 0})

    def test_full_run_with_fake_model_and_resume(self):
        jobs = run.make_jobs(self.cands, ['base_01'], 2, None)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'calls.jsonl'
            run.run_jobs(jobs[:5], fake_call_factory(), out, set())
            done = {r['key'] for r in score.load_calls(out) if r['ok']}
            self.assertEqual(len(done), 5)
            run.run_jobs(jobs, fake_call_factory(), out, done)      # 이어서: 나머지만
            self.assertEqual(len(score.load_calls(out)), len(jobs))
            run.write_summary(Path(tmp), jobs)
            text = (Path(tmp) / 'summary.md').read_text(encoding='utf-8')
            self.assertIn('luna-medium', text)
            # 가짜 심사위원은 모든 변형을 원본보다 낮게 준다 → 순서 맞힘 5/5, 원인 짚기 4/4 (뚜렷한 차이 기준)
            self.assertIn('5/5', text)
            self.assertIn('4/4', text)

    def test_failure_is_recorded_not_raised(self):
        jobs = run.make_jobs(self.cands[:1], ['base_01'], 1, ['halved'])

        def boom(cand, messages):
            raise RuntimeError('호출 실패')
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'calls.jsonl'
            run.run_jobs(jobs, boom, out, set())
            rows = score.load_calls(out)
            self.assertTrue(all(not r['ok'] for r in rows))
            run.write_summary(Path(tmp), jobs)
            self.assertIn('실패한 호출', (Path(tmp) / 'summary.md').read_text(encoding='utf-8'))


class PlanOnlyTest(unittest.TestCase):
    def test_default_makes_no_calls_and_no_report_folder(self):
        before = set((ROOT / 'reports').iterdir())
        self.assertEqual(run.main(['--candidates', 'luna-medium', '--reps', '1']), 0)
        self.assertEqual(set((ROOT / 'reports').iterdir()), before)

    def test_budget_guard(self):
        self.assertEqual(run.main(['--execute', '--max-usd', '0.0001']), 2)


if __name__ == '__main__':
    unittest.main()
