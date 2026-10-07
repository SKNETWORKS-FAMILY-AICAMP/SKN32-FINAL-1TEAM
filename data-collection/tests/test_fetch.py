"""K-Startup 공고 수집(collect/fetch.py) — 인터넷 없이 가짜 응답으로 쪽 나눔·인증키 전달을 확인한다."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import io
import json
import unittest
import urllib.parse
from unittest.mock import patch

from collect import fetch


class FakeResponse(object):
    def __init__(self, payload):
        self.body = payload if isinstance(payload, bytes) else json.dumps(payload).encode('utf-8')

    def read(self):
        return self.body


def pages_server(total, per_page=100, report='matchCount', urls=None):
    """total 건을 per_page 씩 나눠 돌려주는 가짜 서버."""
    def opener(url):
        if urls is not None:
            urls.append(url)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        page = int(query['page'][0])
        start = (page - 1) * per_page
        rows = [{'pbanc_sn': i} for i in range(start, min(start + per_page, total))]
        return FakeResponse({report: total, 'data': rows})
    return opener


class FetchPageTests(unittest.TestCase):
    def test_key_page_and_open_condition_are_sent(self):
        urls = []
        with patch('urllib.request.urlopen', side_effect=pages_server(3, urls=urls)):
            out = fetch.fetch_page('k+ey/=', 2)
        url = urls[0]
        self.assertTrue(url.startswith(fetch.BASE + '?'))
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        # 디코딩된 원본 키를 한 번만 인코딩해 보낸다
        self.assertEqual(query['serviceKey'], ['k+ey/='])
        self.assertEqual(query['page'], ['2'])
        self.assertEqual(query['perPage'], ['100'])
        self.assertEqual(query['returnType'], ['json'])
        # 모집중 조건은 대괄호가 깨지지 않게 그대로 붙인다
        self.assertTrue(url.endswith('&cond[rcrt_prgs_yn::EQ]=Y'))
        self.assertEqual(out['data'], [])

    def test_only_open_false_omits_condition(self):
        urls = []
        with patch('urllib.request.urlopen', side_effect=pages_server(1, urls=urls)):
            fetch.fetch_page('key', 1, only_open=False)
        self.assertNotIn('cond[', urls[0])

    def test_broken_json_raises(self):
        with patch('urllib.request.urlopen', return_value=FakeResponse(b'<html>error</html>')):
            with self.assertRaises(ValueError):
                fetch.fetch_page('key', 1)


class FetchAllTests(unittest.TestCase):
    def test_collects_every_page_until_total(self):
        urls = []
        with patch('urllib.request.urlopen', side_effect=pages_server(250, urls=urls)):
            rows, total = fetch.fetch_all('key')
        self.assertEqual(total, 250)
        self.assertEqual(len(rows), 250)
        self.assertEqual([r['pbanc_sn'] for r in rows], list(range(250)))
        self.assertEqual(len(urls), 3)            # 100 + 100 + 50

    def test_total_count_is_used_when_match_count_missing(self):
        with patch('urllib.request.urlopen', side_effect=pages_server(120, report='totalCount')):
            rows, total = fetch.fetch_all('key')
        self.assertEqual((len(rows), total), (120, 120))

    def test_stops_on_empty_page_even_if_total_is_larger(self):
        # 서버가 보고한 건수보다 실제 자료가 적으면 빈 쪽에서 멈춘다(무한 반복 방지)
        def opener(url):
            page = int(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['page'][0])
            rows = [{'pbanc_sn': 1}] if page == 1 else []
            return FakeResponse({'matchCount': 500, 'data': rows})
        with patch('urllib.request.urlopen', side_effect=opener) as mocked:
            rows, total = fetch.fetch_all('key')
        self.assertEqual((len(rows), total), (1, 500))
        self.assertEqual(mocked.call_count, 2)

    def test_empty_response_returns_nothing(self):
        with patch('urllib.request.urlopen', return_value=FakeResponse({'data': None})) as mocked:
            rows, total = fetch.fetch_all('key')
        self.assertEqual((rows, total), ([], 0))
        self.assertEqual(mocked.call_count, 1)


class MainTests(unittest.TestCase):
    def test_main_writes_payload_with_counts(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'data', 'notices.json')
            with patch.object(fetch, 'OUT', out), \
                    patch.object(fetch.config, 'require', return_value='key'), \
                    patch('urllib.request.urlopen', side_effect=pages_server(5)), \
                    patch('sys.stdout', new=io.StringIO()):
                self.assertEqual(fetch.main(), 0)
            with open(out, encoding='utf-8') as f:
                payload = json.load(f)
        self.assertEqual(payload['count'], 5)
        self.assertEqual(payload['reported_total'], 5)
        self.assertEqual(len(payload['notices']), 5)
        self.assertIn('rcrt_prgs_yn=Y', payload['source'])

    def test_main_stops_without_key(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('KSTARTUP_KEY', None)
            with patch.object(fetch.config, 'get', return_value=None), \
                    patch('sys.stderr', new=io.StringIO()), \
                    patch('urllib.request.urlopen') as mocked:
                with self.assertRaises(SystemExit):
                    fetch.main()
        mocked.assert_not_called()


if __name__ == '__main__':
    unittest.main()
