# -*- coding: utf-8 -*-
"""daily_pipeline 회귀 검증 — 실제 API·DB·기존 공고 파일을 건드리지 않는다.

  .\.venv\Scripts\python.exe -X utf8 -m unittest test_pipeline -v

핵심은 **소스별 실패 격리**다. 한 소스가 죽어도 나머지는 갱신되고,
죽은 소스는 직전 스냅샷을 그대로 쓴다 (decisions.md D1).
"""
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import daily_job
import daily_pipeline

KS_ROW = {'pbanc_sn': '1', 'biz_pbanc_nm': 'K 표본', 'pbanc_rcpt_end_dt': '20990101',
          'biz_enyy': '7년미만', 'rcrt_prgs_yn': 'Y'}


def biz_row(n):
    return {'pblancId': 'PBLN_%09d' % n, 'pblancNm': '기업마당 표본 %d' % n,
            'reqstBeginEndDe': '2026-01-01 ~ 2026-12-31'}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = self.stack.enter_context(tempfile.TemporaryDirectory())
        raw = os.path.join(self.root, 'raw')
        os.makedirs(raw)

        for mod, names in ((daily_job, ('DATA', 'OUT', 'TMP', 'HIST', 'LOG')),
                           (daily_pipeline, ('DATA', 'RAW', 'NORM', 'LOG', 'LOCK'))):
            for name in names:
                value = {
                    'DATA': self.root, 'RAW': raw,
                    'NORM': os.path.join(self.root, 'normalized'),
                    'OUT': os.path.join(self.root, 'notices.json'),
                    'TMP': os.path.join(self.root, 'notices.json.tmp'),
                    'HIST': os.path.join(self.root, 'history'),
                    'LOG': os.path.join(self.root, 'collect_log.jsonl'),
                    'LOCK': os.path.join(self.root, 'collection.lock'),
                }[name]
                self.stack.enter_context(patch.object(mod, name, value))

        self.stack.enter_context(patch.object(daily_job.config, 'get', return_value='test'))
        self.stack.enter_context(patch.object(daily_pipeline.config, 'get', return_value='test'))
        self.stack.enter_context(patch.object(daily_job, 'collect', return_value=([KS_ROW], 1)))

    # ── 도구 ────────────────────────────────────────────────
    def snapshot(self, rows, stamp='20260101T000000000000Z'):
        """기업마당 원본 스냅샷을 직접 만든다."""
        path = os.path.join(daily_pipeline.RAW, 'bizinfo_%s.json' % stamp)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'jsonArray': rows}, f, ensure_ascii=False)
        return path

    def fake_fetch(self, rows, stamp='20260102T000000000000Z'):
        """fetch_bizinfo.fetch_snapshot 을 대신한다. 파일을 실제로 쓴다."""
        def inner():
            return self.snapshot(rows, stamp), len(rows)
        return inner

    def run_pipeline(self, **kw):
        kw.setdefault('skip_store', True)
        kw.setdefault('say', lambda *a, **k: None)
        return daily_pipeline.run(**kw)

    # ── 정상 ────────────────────────────────────────────────
    def test_두_소스가_모두_정상이면_합쳐서_정규화한다(self):
        import fetch_bizinfo
        with patch.object(fetch_bizinfo, 'fetch_snapshot', self.fake_fetch([biz_row(i) for i in range(5)])):
            r = self.run_pipeline()
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(r['normalized_count'], 6)          # K 1건 + 기업마당 5건
        self.assertEqual(r['sources']['kstartup']['status'], 'ok')
        self.assertEqual(r['sources']['bizinfo']['status'], 'ok')
        self.assertEqual(r['degraded'], [])

    # ── 소스별 실패 격리 ──────────────────────────────────────
    def test_기업마당이_실패해도_직전_스냅샷으로_이어간다(self):
        import fetch_bizinfo
        self.snapshot([biz_row(i) for i in range(3)])       # 어제치
        with patch.object(fetch_bizinfo, 'fetch_snapshot', side_effect=RuntimeError('API 다운')):
            r = self.run_pipeline()
        self.assertEqual(r['status'], 'partial')
        self.assertEqual(r['sources']['bizinfo']['status'], 'stale')
        self.assertEqual(r['sources']['kstartup']['status'], 'ok', 'K-Startup 은 갱신돼야 한다')
        self.assertEqual(r['normalized_count'], 4, '어제 기업마당 3건 + 오늘 K 1건')
        self.assertIn('bizinfo', r['degraded'])

    def test_기업마당_건수가_급감하면_직전_스냅샷을_쓴다(self):
        import fetch_bizinfo
        self.snapshot([biz_row(i) for i in range(10)])      # 어제 10건
        with patch.object(fetch_bizinfo, 'fetch_snapshot',
                          self.fake_fetch([biz_row(99)])):  # 오늘 1건 = 90% 감소
            r = self.run_pipeline()
        self.assertEqual(r['sources']['bizinfo']['status'], 'rejected')
        self.assertEqual(r['normalized_count'], 11, '어제 10건이 그대로 쓰여야 한다')

    def test_force_면_급감해도_교체한다(self):
        import fetch_bizinfo
        self.snapshot([biz_row(i) for i in range(10)])
        with patch.object(fetch_bizinfo, 'fetch_snapshot', self.fake_fetch([biz_row(99)])):
            r = self.run_pipeline(force=True)
        self.assertEqual(r['sources']['bizinfo']['status'], 'ok')
        self.assertEqual(r['normalized_count'], 2)

    def test_기업마당_스냅샷이_아예_없으면_K만_처리한다(self):
        import fetch_bizinfo
        with patch.object(fetch_bizinfo, 'fetch_snapshot', side_effect=RuntimeError('API 다운')):
            r = self.run_pipeline()
        self.assertEqual(r['status'], 'partial')
        self.assertEqual(r['normalized_count'], 1)

    def test_K_수집이_실패해도_기업마당은_처리된다(self):
        import fetch_bizinfo
        with patch.object(daily_job, 'collect', side_effect=RuntimeError('K 다운')), \
                patch.object(fetch_bizinfo, 'fetch_snapshot',
                             self.fake_fetch([biz_row(i) for i in range(4)])):
            r = self.run_pipeline()
        self.assertEqual(r['status'], 'partial')
        self.assertEqual(r['sources']['kstartup']['status'], 'error')
        self.assertEqual(r['sources']['bizinfo']['status'], 'ok')
        self.assertIn('kstartup', r['degraded'])

    # ── 안전장치 ────────────────────────────────────────────
    def test_dry_run_은_기존_공고_파일을_교체하지_않는다(self):
        import fetch_bizinfo
        with patch.object(fetch_bizinfo, 'fetch_snapshot', self.fake_fetch([biz_row(1)])):
            self.run_pipeline(dry_run=True)
        self.assertFalse(os.path.exists(daily_job.OUT))

    def test_이미_실행_중이면_busy(self):
        import job_lock
        with job_lock.acquire(daily_pipeline.LOCK):
            r = daily_pipeline.run(say=lambda *a, **k: None)
        self.assertEqual(r['status'], 'busy')

    def test_저장을_건너뛰면_stored_는_거짓이다(self):
        import fetch_bizinfo
        with patch.object(fetch_bizinfo, 'fetch_snapshot', self.fake_fetch([biz_row(1)])):
            r = self.run_pipeline()
        self.assertFalse(r['stored'])

    def test_로그가_한_줄_쌓인다(self):
        import fetch_bizinfo
        with patch.object(fetch_bizinfo, 'fetch_snapshot', self.fake_fetch([biz_row(1)])):
            self.run_pipeline()
        with open(daily_pipeline.LOG, encoding='utf-8') as f:
            entries = [json.loads(l) for l in f if l.strip()]
        pipeline = [e for e in entries if e.get('job') == 'pipeline']
        self.assertEqual(len(pipeline), 1)
        self.assertIn('sources', pipeline[0])

    def test_오래된_스냅샷을_정리한다(self):
        for i in range(20):
            self.snapshot([biz_row(1)], stamp='2026010%02dT000000000000Z' % i)
        self.assertEqual(len(daily_pipeline.snapshots('bizinfo')), 20)
        removed = daily_pipeline.prune('bizinfo', keep=5)
        self.assertEqual(removed, 15)
        self.assertEqual(len(daily_pipeline.snapshots('bizinfo')), 5)


if __name__ == '__main__':
    unittest.main()
