# -*- coding: utf-8 -*-
"""매일 배치 11단계 신청자 유형 추출 — 가짜 공고·가짜 호출로 (2026-09-28). DB·LLM 없음."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collect import applicant_type_daily as daily  # noqa: E402
from experiments.sql_semantic import applicant_type_llm as atl  # noqa: E402


def item(nid, doc='□ 지원대상: 사업자등록증 보유 중소기업'):
    return atl.prepare({'notice_id': nid, 'source': 'bizinfo', 'title': nid, 'body': doc, 'target_text': '',
                        'attachments': []})


ANSWER = {'pre_founder': {'status': 'not_allowed', 'evidence': '사업자등록증 보유 중소기업'},
          'sole_proprietor': {'status': 'not_mentioned', 'evidence': None},
          'corporation': {'status': 'not_mentioned', 'evidence': None}, 'varies': False, 'reason': ''}


class DailyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.calls = []
        # 실제 전량 결과를 씨앗으로 읽지 않게 한다
        seed = patch.object(daily, 'SEED_RUN', os.path.join(self.tmp, 'no-seed.jsonl'))
        seed.start()
        self.addCleanup(seed.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def call(self, it):
        self.calls.append(it['notice_id'])
        return ANSWER, {'in': 1000, 'out': 100, 'model': 'fake'}

    def run_batch(self, population, call=None, **kw):
        kw.setdefault('today', '2026-09-28')
        with patch.object(atl, 'load_population', lambda conn: population):
            return daily.run_batch(connection=object(), call=call or self.call, out_dir=self.tmp,
                                   say=lambda *_: None, **kw)

    def test_only_new_or_changed_notices_are_called(self):
        seed = os.path.join(self.tmp, 'seed.jsonl')
        old = item('a')
        with io.open(seed, 'w', encoding='utf-8') as f:
            f.write(json.dumps({'notice_id': 'a', 'document_sha256': old['document_sha256'],
                                'llm': {'pre_founder': {'status': 'allowed'}}}) + '\n')
        # 누적 파일이 없을 때는 전량 실행 결과(seed)에서 시작한다
        existing = daily.load_existing(os.path.join(self.tmp, 'none.jsonl'), seed)
        self.assertIn('a', existing)
        changed = item('b', doc='바뀐 공고문')
        todo, skipped, deferred = daily.plan([old, changed, item('c')], existing, limit=300)
        self.assertEqual([t['notice_id'] for t in todo], ['b', 'c'])
        self.assertEqual((skipped, deferred), (1, 0))

    def test_run_writes_results_and_verifies(self):
        out = self.run_batch([item('x'), item('y')])
        self.assertEqual(out['extracted'], 2)
        self.assertEqual(sorted(self.calls), ['x', 'y'])
        rows = daily.read_jsonl(os.path.join(self.tmp, 'results.jsonl'))
        self.assertEqual([r['notice_id'] for r in rows], ['x', 'y'])
        self.assertEqual(rows[0]['llm']['pre_founder']['status'], 'not_allowed')   # 코드 검사(verify)를 거친 값
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'checkpoint.jsonl')))   # 다 반영했으면 비운다
        # 두 번째 실행은 해시가 같아 부르지 않는다
        self.calls.clear()
        again = self.run_batch([item('x'), item('y')])
        self.assertEqual((again['extracted'], again['skipped'], self.calls), (0, 2, []))

    def test_daily_limit_defers_the_rest(self):
        out = self.run_batch([item('n%02d' % i) for i in range(5)], limit=2)
        self.assertEqual((out['extracted'], out['deferred']), (2, 3))

    def test_limit_is_per_day_not_per_run(self):
        # 같은 날 두 번 돌려도 합이 상한을 넘지 않는다(2026-09-28 Codex 통합 검수 P2)
        population = [item('n%02d' % i) for i in range(5)]
        first = self.run_batch(population, limit=2)
        second = self.run_batch(population, limit=2)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual((first['extracted'], second['extracted'], second['attempted_today']), (2, 0, 2))
        # 다음 날에는 이어서 부른다
        third = self.run_batch(population, limit=2, today='2026-09-29')
        self.assertEqual((third['extracted'], len(self.calls)), (2, 4))

    def test_failed_calls_count_toward_the_limit(self):
        def broken(it):
            self.calls.append(it['notice_id'])
            raise RuntimeError('api down')
        population = [item('n%02d' % i) for i in range(5)]
        self.run_batch(population, call=broken, limit=3)
        self.run_batch(population, call=broken, limit=3)
        self.assertEqual(len(self.calls), 3)

    def test_gives_up_after_repeated_failures_until_document_changes(self):
        def flaky(it):
            if it['notice_id'] == 'bad':
                self.calls.append('bad')
                raise RuntimeError('api down')
            return self.call(it)
        for day in ('2026-09-28', '2026-09-29', '2026-09-30', '2026-10-01'):
            out = self.run_batch([item('ok'), item('bad')], call=flaky, today=day)
        self.assertEqual(self.calls.count('bad'), daily.MAX_FAILURES)     # 넷째 날은 부르지 않는다
        self.assertEqual(out['gave_up'], 1)
        # 공고문이 바뀌면 다시 부른다
        self.calls.clear()
        self.run_batch([item('ok'), item('bad', doc='고친 공고문')], call=flaky, today='2026-10-02')
        self.assertEqual(self.calls, ['bad'])

    def test_second_run_while_first_holds_lock_is_skipped(self):
        # 단독 실행 두 개가 동시에 돌면 두 번째는 부르지 않는다(2026-09-28 Codex 검수 P2)
        from collect import job_lock
        with job_lock.acquire(os.path.join(self.tmp, 'run.lock')):
            out = self.run_batch([item('x')])
        self.assertEqual(out['error'], 'busy')
        self.assertEqual(self.calls, [])

    def test_failure_keeps_checkpoint_and_others(self):
        def flaky(it):
            if it['notice_id'] == 'bad':
                raise RuntimeError('api down')
            return self.call(it)
        with patch.object(atl, 'load_population', lambda conn: [item('ok'), item('bad')]):
            out = daily.run_batch(connection=object(), call=flaky, out_dir=self.tmp, say=lambda *_: None)
        self.assertEqual((out['extracted'], out['failed']), (1, 1))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, 'checkpoint.jsonl')))   # 실패가 있으면 남긴다
        rows = daily.read_jsonl(os.path.join(self.tmp, 'results.jsonl'))
        self.assertEqual([r['notice_id'] for r in rows], ['ok'])


class PipelineStatusTests(unittest.TestCase):
    """10·11단계 실패는 수집 status 를 바꾸지 않고 stage_warnings 로 남는다(2026-09-28 Codex 통합 검수 P2)."""

    def test_stage_warnings(self):
        from collect import daily_pipeline as dp
        self.assertEqual(dp.stage_warnings_of({'conditions': None, 'applicant_types': {'extracted': 3, 'failed': 0}}), [])
        self.assertEqual(dp.stage_warnings_of({'applicant_types': {'error': 'no_api_key'}}),
                         [{'stage': 'applicant_types', 'error': 'no_api_key'}])
        self.assertEqual(dp.stage_warnings_of({'applicant_types': {'extracted': 1, 'failed': 2}}),
                         [{'stage': 'applicant_types', 'failed': 2}])
        # 13단계 판정 올리기: 한 표라도 실패하면 경고, 둘 다 정상이면 없음
        ok = {'types': {'uploaded': 3}, 'industries': {'uploaded': 0}, 'error': None}
        self.assertEqual(dp.stage_warnings_of({'judgments_upload': ok}), [])
        self.assertEqual(dp.stage_warnings_of({'judgments_upload': dict(ok, error='types: 결과 파일이 없다')}),
                         [{'stage': 'judgments_upload', 'error': 'types: 결과 파일이 없다'}])


class ServicePathTests(unittest.TestCase):
    def test_service_prefers_daily_file(self):
        from search import applicant_types as at
        tmp = tempfile.mkdtemp()
        try:
            daily_file = os.path.join(tmp, 'results.jsonl')
            with patch.object(at, 'DAILY_RESULTS', daily_file), patch.dict(os.environ, {}, clear=False):
                os.environ.pop(at.ENV, None)
                self.assertIn('reports', at.default_path())               # 누적 파일이 없으면 전량 결과
                io.open(daily_file, 'w', encoding='utf-8').close()
                self.assertEqual(at.default_path(), daily_file)          # 있으면 누적 파일
        finally:
            shutil.rmtree(tmp)


if __name__ == '__main__':
    unittest.main()
