"""공통 설정(shared/config.py) — .env 해석·기존 환경 변수 우선·인코딩 키 경고·require 종료."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import io
import tempfile
import unittest
from unittest.mock import patch

from shared import config


def env_file(folder, text, name='.env'):
    path = os.path.join(folder, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return path


class ParseTests(unittest.TestCase):
    def test_comments_blank_export_and_quotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = env_file(tmp, '\n'.join([
                '# 주석',
                '',
                'PLAIN=값1',
                'export EXPORTED = 값2 ',
                'DOUBLE="따옴표 값"',
                "SINGLE='작은 따옴표'",
                'HALF="한쪽만',
                'EQUALS=a=b=c',
                '이퀄 없는 줄',
                'EMPTY=',
            ]))
            out = config._parse(path)
        self.assertEqual(out['PLAIN'], '값1')
        self.assertEqual(out['EXPORTED'], '값2')
        self.assertEqual(out['DOUBLE'], '따옴표 값')
        self.assertEqual(out['SINGLE'], '작은 따옴표')
        self.assertEqual(out['HALF'], '"한쪽만')          # 감싼 따옴표만 벗긴다
        self.assertEqual(out['EQUALS'], 'a=b=c')          # 첫 = 에서만 나눈다
        self.assertEqual(out['EMPTY'], '')
        self.assertNotIn('# 주석', out)
        self.assertEqual(len(out), 7)


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(config, '_loaded', False)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for k in ('SB_TEST_A', 'SB_TEST_B', 'SB_TEST_KEY'):
            os.environ.pop(k, None)

    def test_existing_environment_wins(self):
        path = env_file(self.tmp.name, 'SB_TEST_A=파일값\nSB_TEST_B=파일값B\n')
        os.environ['SB_TEST_A'] = '기존값'
        with patch.object(config, 'CANDIDATES', (path,)):
            config.load()
        self.assertEqual(os.environ['SB_TEST_A'], '기존값')
        self.assertEqual(os.environ['SB_TEST_B'], '파일값B')

    def test_first_found_file_only(self):
        first = os.path.join(self.tmp.name, 'a')
        second = os.path.join(self.tmp.name, 'b')
        os.makedirs(first)
        os.makedirs(second)
        p1 = env_file(first, 'SB_TEST_A=첫째\n')
        p2 = env_file(second, 'SB_TEST_A=둘째\nSB_TEST_B=둘째B\n')
        missing = os.path.join(self.tmp.name, 'none', '.env')
        with patch.object(config, 'CANDIDATES', (missing, p1, p2)):
            config.load()
        self.assertEqual(os.environ['SB_TEST_A'], '첫째')
        self.assertNotIn('SB_TEST_B', os.environ)

    def test_loads_once(self):
        path = env_file(self.tmp.name, 'SB_TEST_A=1\n')
        with patch.object(config, 'CANDIDATES', (path,)):
            config.load()
            os.environ.pop('SB_TEST_A')
            config.load()                       # 두 번째는 읽지 않는다
        self.assertNotIn('SB_TEST_A', os.environ)

    def test_url_encoded_key_warns(self):
        path = env_file(self.tmp.name, 'SB_TEST_KEY=abc%2Bdef%3D%3D\n')
        err = io.StringIO()
        with patch.object(config, 'CANDIDATES', (path,)), patch('sys.stderr', new=err):
            config.load()
        self.assertIn('SB_TEST_KEY', err.getvalue())
        self.assertIn('인코딩', err.getvalue())
        self.assertNotIn('abc%2Bdef', err.getvalue())   # 키 값 자체는 찍지 않는다

    def test_decoded_key_no_warning(self):
        path = env_file(self.tmp.name, 'SB_TEST_KEY=abc+def==\n')
        err = io.StringIO()
        with patch.object(config, 'CANDIDATES', (path,)), patch('sys.stderr', new=err):
            config.load()
        self.assertEqual(err.getvalue(), '')

    def test_get_default_and_require(self):
        with patch.object(config, 'CANDIDATES', ()):
            self.assertEqual(config.get('SB_TEST_A', '기본'), '기본')
            os.environ['SB_TEST_A'] = '있음'
            self.assertEqual(config.require('SB_TEST_A'), '있음')

    def test_require_missing_exits_with_guide(self):
        err = io.StringIO()
        with patch.object(config, 'CANDIDATES', ()), patch('sys.stderr', new=err):
            with self.assertRaises(SystemExit) as caught:
                config.require('SB_TEST_A')
        self.assertEqual(caught.exception.code, 1)
        self.assertIn('SB_TEST_A', err.getvalue())

    def test_require_empty_value_exits(self):
        os.environ['SB_TEST_A'] = ''
        with patch.object(config, 'CANDIDATES', ()), patch('sys.stderr', new=io.StringIO()):
            with self.assertRaises(SystemExit):
                config.require('SB_TEST_A')


if __name__ == '__main__':
    unittest.main()
