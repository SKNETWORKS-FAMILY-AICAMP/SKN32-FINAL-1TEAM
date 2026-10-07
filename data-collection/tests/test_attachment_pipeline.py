"""첨부 본문 추출(collect/attachment_pipeline.py) — 인터넷·공용 DB 없이 가짜 응답·임시 폴더로 확인한다.

파일 종류 판별, 크기 상한, 다운로드 실패 기록, 결과 기록 모양, 이어 하기, 연속 실패 상한, 적재 후 결과 파일 정리.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hashlib
import io
import json
import tempfile
import time
import unittest
import zipfile
from unittest.mock import MagicMock, patch

import requests

from collect import attachment_pipeline as pipe
from collect import doctext


def zip_bytes(names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name in names:
            z.writestr(name, '<x/>')
    return buf.getvalue()


class FakeResponse(object):
    def __init__(self, status=200, body=b'', ctype='application/octet-stream', chunk=65536):
        self.status_code = status
        self.headers = {'Content-Type': ctype}
        self.body = body
        self.chunk = chunk

    def iter_content(self, size):
        for i in range(0, len(self.body), self.chunk):
            yield self.body[i:i + self.chunk]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession(object):
    def __init__(self, response=None, error=None):
        self.response, self.error, self.urls = response, error, []

    def get(self, url, timeout=None, stream=False):
        self.urls.append(url)
        if self.error:
            raise self.error
        return self.response


class ClassifyTests(unittest.TestCase):
    def test_image_is_ocr_target(self):
        for data in (b'\x89PNG\r\n\x1a\n' + b'0' * 20, b'\xff\xd8\xff\xe0' + b'0' * 20, b'GIF89a'):
            status, kind, text, error = pipe.classify(data)
            self.assertEqual((status, kind, text), ('image_only', 'image', None))
            self.assertIn('OCR', error)

    def test_zip_rtf_unknown_are_unsupported(self):
        cases = ((zip_bytes(['a.txt']), 'zip'), (b'{\\rtf1 abc}', 'rtf'), (b'hello world', 'unknown'))
        for data, kind in cases:
            status, got_kind, text, error = pipe.classify(data)
            self.assertEqual((status, got_kind, text), ('unsupported', kind, None))
            self.assertIn(kind, error)

    def test_zip_inside_decides_hwpx_docx(self):
        self.assertEqual(doctext.sniff(zip_bytes(['Contents/section0.xml'])), 'hwpx')
        self.assertEqual(doctext.sniff(zip_bytes(['word/document.xml'])), 'docx')
        self.assertEqual(doctext.sniff(b'%PDF-1.7'), 'pdf')
        self.assertEqual(doctext.sniff(b'\xd0\xcf\x11\xe0' + b'\x00' * 12), 'ole')

    def test_ok_text(self):
        text = '지원 대상은 창업 7년 미만 중소기업이며 신청 기간은 10월 31일까지입니다.'
        with patch.object(doctext, 'extract_bytes', return_value=(text, {'kind': 'pdf'})):
            self.assertEqual(pipe.classify(b'%PDF-1.7 ...'), ('ok', 'pdf', text, None))

    def test_short_text_small_file_is_empty(self):
        with patch.object(doctext, 'extract_bytes', return_value=('  짧음 ', {'kind': 'pdf'})):
            status, kind, text, error = pipe.classify(b'%PDF-1.7' + b'0' * 100)
        self.assertEqual((status, kind, text), ('empty_text', 'pdf', None))
        self.assertIn('2자', error)

    def test_short_text_large_file_is_image_only(self):
        # 글꼴을 곡선으로 바꾼 PDF — 글자 0자인데 파일이 크다
        data = b'%PDF-1.7' + b'0' * (50 * 1024)
        with patch.object(doctext, 'extract_bytes', return_value=('', {'kind': 'pdf'})):
            status, kind, text, error = pipe.classify(data)
        self.assertEqual((status, kind), ('image_only', 'pdf'))
        self.assertIn('OCR', error)

    def test_hwp_image_only_flag(self):
        with patch.object(doctext, 'extract_bytes',
                          return_value=('본문' * 50, {'kind': 'hwp', 'image_only': True})):
            status, kind, text, error = pipe.classify(b'\xd0\xcf\x11\xe0' + b'\x00' * 12)
        self.assertEqual((status, kind, text), ('image_only', 'hwp', None))

    def test_unsupported_and_parse_error(self):
        ole = b'\xd0\xcf\x11\xe0' + b'\x00' * 12
        with patch.object(doctext, 'extract_bytes', side_effect=doctext.UnsupportedFormat('구 워드')):
            self.assertEqual(pipe.classify(ole), ('unsupported', None, None, '구 워드'))
        with patch.object(doctext, 'extract_bytes', side_effect=RuntimeError('깨짐')):
            status, kind, text, error = pipe.classify(b'%PDF-1.7')
        self.assertEqual((status, kind, text), ('parse_error', 'pdf', None))
        self.assertEqual(error, 'RuntimeError: 깨짐')


class DownloadTests(unittest.TestCase):
    def test_ok(self):
        body = b'%PDF-1.7' + b'x' * 200000
        got, why = pipe.download(FakeSession(FakeResponse(body=body)), 'http://example.invalid/a')
        self.assertEqual((got, why), (body, None))

    def test_http_status(self):
        self.assertEqual(pipe.download(FakeSession(FakeResponse(status=404)), 'u'), (None, 'HTTP 404'))

    def test_html_instead_of_file(self):
        got, why = pipe.download(FakeSession(FakeResponse(body=b'<html>', ctype='text/html; charset=utf-8')), 'u')
        self.assertIsNone(got)
        self.assertIn('HTML', why)

    def test_empty_body(self):
        self.assertEqual(pipe.download(FakeSession(FakeResponse(body=b'')), 'u'), (None, '빈 응답'))

    def test_size_cap(self):
        with patch.object(pipe, 'MAX_BYTES', 1000):
            got, why = pipe.download(FakeSession(FakeResponse(body=b'x' * 1001, chunk=100)), 'u')
        self.assertIsNone(got)
        self.assertIn('상한 초과', why)
        self.assertEqual(pipe.MAX_BYTES, 30 * 1024 * 1024)

    def test_request_error_reason_has_no_url(self):
        url = 'http://secret.example.invalid/file?key=abc'
        got, why = pipe.download(FakeSession(error=requests.ConnectionError(url)), url)
        self.assertIsNone(got)
        self.assertEqual(why, 'HTTP 요청 실패: ConnectionError')
        self.assertNotIn('secret', why)


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = {'attachment_fk': 7, 'url': 'http://example.invalid/f',
                       'notice_id': 'PBLN_1', 'source_updated_at': '2026-10-01 00:00:00'}

    def test_process_download_fail_shape(self):
        record = pipe.process(FakeSession(FakeResponse(status=500)), self.target, 'v-test')
        self.assertEqual(record['status'], 'download_fail')
        self.assertEqual(record['error'], 'HTTP 500')
        for key in ('kind', 'text', 'content_sha256'):
            self.assertIsNone(record[key])
        for key in ('attachment_fk', 'notice_id', 'url', 'source_updated_at'):
            self.assertEqual(record[key], self.target[key])
        self.assertEqual(record['role'], 'notice')
        self.assertEqual(record['extractor_version'], 'v-test')
        self.assertIn('attempt_started_at', record)
        self.assertIn('attempted_at', record)

    def test_process_ok_stores_file_by_hash(self):
        body = b'%PDF-1.7 body'
        text = '본문 텍스트가 충분히 길게 들어 있는 공고문입니다. 신청 자격을 확인하세요.'
        with patch.object(pipe, 'FILES', self.tmp.name), \
                patch.object(doctext, 'extract_bytes', return_value=(text, {'kind': 'pdf'})):
            record = pipe.process(FakeSession(FakeResponse(body=body)), self.target, 'v')
        digest = hashlib.sha256(body).hexdigest()
        self.assertEqual(record['status'], 'ok')
        self.assertEqual(record['content_sha256'], digest)
        self.assertEqual(record['file_sha256'], digest)
        self.assertEqual(record['bytes'], len(body))
        path = os.path.join(self.tmp.name, digest[:2], digest + '.pdf')
        with open(path, 'rb') as f:
            self.assertEqual(f.read(), body)

    def test_process_non_ok_has_no_contract_hash(self):
        body = b'\x89PNG\r\n\x1a\n' + b'0' * 10
        with patch.object(pipe, 'FILES', self.tmp.name):
            record = pipe.process(FakeSession(FakeResponse(body=body)), self.target, 'v')
        self.assertEqual(record['status'], 'image_only')
        self.assertIsNone(record['content_sha256'])           # 성공일 때만 계약상의 해시
        self.assertEqual(record['file_sha256'], hashlib.sha256(body).hexdigest())

    def test_same_content_one_file(self):
        with patch.object(pipe, 'FILES', self.tmp.name):
            a = pipe.store_file(b'same', 'pdf')
            b = pipe.store_file(b'same', 'pdf')
            pipe.store_file(b'other', 'nope')
        self.assertEqual(a, b)
        files = [n for _, _, names in os.walk(self.tmp.name) for n in names]
        self.assertEqual(len(files), 2)
        self.assertTrue(any(n.endswith('.bin') for n in files))   # 모르는 종류는 .bin

    def test_append_and_done_already_skip_broken_lines(self):
        path = os.path.join(self.tmp.name, 'sub', 'results.jsonl')
        pipe.append({'attachment_fk': 1, 'status': 'ok'}, path)
        pipe.append({'attachment_fk': 2, 'status': 'download_fail'}, path)
        with open(path, 'a', encoding='utf-8') as f:
            f.write('\n{"attachment_fk": 3, "sta')               # 전원이 나가 잘린 마지막 줄
        self.assertEqual(pipe.done_already(path), {1, 2})
        self.assertEqual(pipe.done_already(os.path.join(self.tmp.name, 'none.jsonl')), set())


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.results = os.path.join(self.tmp.name, 'results.jsonl')
        self.started = time.time()
        # 기록 함수의 기본 경로는 정의할 때 묶이므로 함수 자체를 임시 파일 쪽으로 돌린다
        done, append = pipe.done_already, pipe.append
        for p in (patch.object(pipe, 'RESULTS', self.results),
                  patch.object(pipe, 'done_already', lambda path=None: done(self.results)),
                  patch.object(pipe, 'append', lambda record, path=None: append(record, self.results)),
                  patch.object(pipe.store_mysql, 'connect', return_value=MagicMock()),
                  patch.object(pipe.time, 'sleep'),
                  patch.object(pipe.doctext, 'version', return_value='v')):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        real = os.path.join(pipe.ROOT, 'data', 'attachment_results.jsonl')
        self.assertFalse(os.path.exists(real) and os.path.getmtime(real) >= self.started,
                         '시험이 실제 결과 파일을 건드렸다')

    def targets(self, n):
        return [{'attachment_fk': i, 'url': 'u%d' % i, 'notice_id': 'n%d' % i,
                 'source_updated_at': None} for i in range(1, n + 1)]

    def test_plan_only_counts_resume(self):
        pipe.append({'attachment_fk': 1}, self.results)
        pipe.append({'attachment_fk': 2}, self.results)
        with patch.object(pipe, 'targets', return_value=self.targets(5)), \
                patch.object(pipe, 'process') as process:
            out = pipe.run(plan_only=True, say=lambda *_: None)
        self.assertEqual(out, {'targets': 5, 'todo': 3})
        process.assert_not_called()

    def test_resume_skips_done_and_records_each(self):
        pipe.append({'attachment_fk': 1, 'status': 'ok'}, self.results)
        seen = []

        def fake(session, target, version):
            seen.append(target['attachment_fk'])
            return {'attachment_fk': target['attachment_fk'], 'status': 'ok'}
        with patch.object(pipe, 'targets', return_value=self.targets(3)), \
                patch.object(pipe, 'process', side_effect=fake):
            out = pipe.run(say=lambda *_: None)
        self.assertEqual(seen, [2, 3])
        self.assertEqual(out['counts'], {'ok': 2})
        self.assertEqual(pipe.done_already(), {1, 2, 3})

    def test_limit(self):
        with patch.object(pipe, 'targets', return_value=self.targets(10)), \
                patch.object(pipe, 'process', side_effect=lambda s, t, v: {'attachment_fk': t['attachment_fk'],
                                                                           'status': 'ok'}) as process:
            out = pipe.run(limit=4, say=lambda *_: None)
        self.assertEqual(process.call_count, 4)
        self.assertEqual(out['todo'], 4)

    def test_gives_up_after_consecutive_failures(self):
        said = []
        with patch.object(pipe, 'targets', return_value=self.targets(30)), \
                patch.object(pipe, 'process', side_effect=lambda s, t, v: {'attachment_fk': t['attachment_fk'],
                                                                           'status': 'download_fail'}) as process:
            out = pipe.run(say=said.append)
        self.assertEqual(process.call_count, pipe.GIVE_UP)
        self.assertEqual(out['counts'], {'download_fail': pipe.GIVE_UP})
        self.assertTrue(any('연속 실패' in s for s in said))

    def test_success_resets_failure_streak(self):
        statuses = (['download_fail'] * 15 + ['ok']) * 2 + ['download_fail'] * 5

        def fake(session, target, version):
            return {'attachment_fk': target['attachment_fk'], 'status': statuses[target['attachment_fk'] - 1]}
        with patch.object(pipe, 'targets', return_value=self.targets(len(statuses))), \
                patch.object(pipe, 'process', side_effect=fake) as process:
            pipe.run(say=lambda *_: None)
        self.assertEqual(process.call_count, len(statuses))

    def test_nothing_to_do(self):
        with patch.object(pipe, 'targets', return_value=[]):
            out = pipe.run(say=lambda *_: None)
        self.assertEqual(out, {'targets': 0, 'todo': 0, 'counts': {}})


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.results = os.path.join(self.tmp.name, 'results.jsonl')
        self.history = os.path.join(self.tmp.name, 'history')
        for p in (patch.object(pipe, 'HISTORY', self.history),
                  patch.object(pipe.store_mysql, 'connect', return_value=MagicMock())):
            p.start()
            self.addCleanup(p.stop)

    def write(self, rows):
        for row in rows:
            pipe.append(row, self.results)

    def test_saved_results_move_to_history(self):
        from collect import attachment_store
        self.write([{'attachment_fk': 1}, {'attachment_fk': 2}])
        with patch.object(attachment_store, 'save_attachment_result', return_value={'status': 'saved'}):
            counts = pipe.store(self.results, say=lambda *_: None)
        self.assertEqual(counts, {'saved': 2})
        self.assertFalse(os.path.exists(self.results))
        self.assertEqual(len(os.listdir(self.history)), 1)

    def test_rejected_result_keeps_file(self):
        from collect import attachment_store
        self.write([{'attachment_fk': 1}, {'attachment_fk': 2}])
        with patch.object(attachment_store, 'save_attachment_result',
                          side_effect=[{'status': 'saved'}, ValueError('계약 위반')]):
            counts = pipe.store(self.results, say=lambda *_: None)
        self.assertEqual(counts, {'saved': 1, 'rejected': 1})
        self.assertTrue(os.path.exists(self.results))

    def test_no_file(self):
        self.assertEqual(pipe.store(self.results, say=lambda *_: None), {})

    def test_prune_history_keeps_latest(self):
        os.makedirs(self.history)
        for i in range(20):
            open(os.path.join(self.history, 'attachment_results_2026%04d.jsonl' % i), 'w').close()
        open(os.path.join(self.history, 'other.txt'), 'w').close()
        self.assertEqual(pipe.prune_history(keep=14), 6)
        names = sorted(os.listdir(self.history))
        self.assertIn('other.txt', names)
        self.assertEqual(len(names), 15)
        self.assertIn('attachment_results_20260019.jsonl', names)
        self.assertNotIn('attachment_results_20260005.jsonl', names)


class DailyTests(unittest.TestCase):
    def test_nothing_to_do_is_success(self):
        with patch.object(pipe, 'run', return_value={'targets': 0, 'todo': 0}), \
                patch.object(pipe, 'store') as store:
            self.assertEqual(pipe.daily(say=lambda *_: None)[1], 0)
        store.assert_not_called()

    def test_all_store_failed_is_failure(self):
        with patch.object(pipe, 'run', return_value={'todo': 3}), \
                patch.object(pipe, 'store', return_value={'rejected': 3}):
            self.assertEqual(pipe.daily(say=lambda *_: None)[1], 1)

    def test_some_saved_or_unchanged_is_success(self):
        for counts in ({'saved': 1, 'rejected': 2}, {'unchanged': 3}):
            with patch.object(pipe, 'run', return_value={'todo': 3}), \
                    patch.object(pipe, 'store', return_value=counts):
                summary, code = pipe.daily(say=lambda *_: None)
            self.assertEqual(code, 0)
            self.assertEqual(summary['stored'], counts)


if __name__ == '__main__':
    unittest.main()
