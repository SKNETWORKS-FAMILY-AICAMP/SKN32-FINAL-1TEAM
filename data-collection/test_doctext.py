# -*- coding: utf-8 -*-
"""doctext 검증 — 외부 파일 없이 문서를 직접 만들어 확인한다.

  .\.venv\Scripts\python.exe -X utf8 -m unittest test_doctext -v

핵심은 **확장자를 믿지 않는다**는 것이다. 실측에서 `.hwp` 인데 HWPX 인 파일,
`.hwpx` 인데 구 HWP 인 파일이 각각 나왔다.
"""
import os
import tempfile
import unittest
import zipfile
from contextlib import ExitStack

import doctext

HWPX_XML = ('<?xml version="1.0"?><hml><hp:p><hp:t>업력 7년 이내 창업기업</hp:t></hp:p>'
            '<hp:p><hp:t>국세를 체납 중인 기업은 제외</hp:t></hp:p></hml>')
DOCX_XML = ('<?xml version="1.0"?><w:document><w:body>'
            '<w:p><w:r><w:t>지원대상</w:t></w:r><w:r><w:t> 안내</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>창업 3년 미만</w:t></w:r></w:p>'
            '</w:body></w:document>')


class Base(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.dir = self.stack.enter_context(tempfile.TemporaryDirectory())

    def write(self, name, data):
        path = os.path.join(self.dir, name)
        with open(path, 'wb') as f:
            f.write(data)
        return path

    def zipped(self, name, members):
        path = os.path.join(self.dir, name)
        with zipfile.ZipFile(path, 'w') as z:
            for member, body in members.items():
                z.writestr(member, body)
        return path


class 형식판별(Base):
    def test_확장자가_아니라_내용으로_정한다(self):
        """.hwp 로 위장한 HWPX 를 HWPX 로 읽어야 한다."""
        path = self.zipped('위장.hwp', {'Contents/section0.xml': HWPX_XML})
        self.assertEqual(doctext.sniff(path), 'hwpx')
        text, info = doctext.extract(path)
        self.assertEqual(info['kind'], 'hwpx')
        self.assertIn('업력 7년 이내', text)

    def test_docx_와_hwpx_를_구분한다(self):
        self.assertEqual(doctext.sniff(
            self.zipped('a.zip', {'word/document.xml': DOCX_XML})), 'docx')
        self.assertEqual(doctext.sniff(
            self.zipped('b.zip', {'Contents/section0.xml': HWPX_XML})), 'hwpx')

    def test_알맹이_없는_zip_은_zip_이다(self):
        path = self.zipped('c.zip', {'readme.txt': 'hello'})
        self.assertEqual(doctext.sniff(path), 'zip')
        with self.assertRaises(doctext.UnsupportedFormat):
            doctext.extract(path)

    def test_그림_파일은_OCR_안내와_함께_거부한다(self):
        path = self.write('scan.hwp', b'\x89PNG\r\n\x1a\n' + b'0' * 40)
        self.assertEqual(doctext.sniff(path), 'image')
        with self.assertRaises(doctext.UnsupportedFormat) as cm:
            doctext.extract(path)
        self.assertIn('OCR', str(cm.exception))

    def test_빈_파일과_알_수_없는_형식(self):
        for name, data in (('empty.hwp', b''), ('junk.pdf', b'\x00\x01\x02\x03')):
            with self.subTest(name=name), self.assertRaises(doctext.UnsupportedFormat):
                doctext.extract(self.write(name, data))

    def test_bytes_로도_판별한다(self):
        self.assertEqual(doctext.sniff(b'%PDF-1.7 ...'), 'pdf')
        self.assertEqual(doctext.sniff(b'\xd0\xcf\x11\xe0' + b'0' * 20), 'ole')


class 추출(Base):
    def test_hwpx_문단이_줄바꿈으로_나뉜다(self):
        text, _ = doctext.extract(
            self.zipped('a.hwpx', {'Contents/section0.xml': HWPX_XML}))
        self.assertEqual(text.splitlines(),
                         ['업력 7년 이내 창업기업', '국세를 체납 중인 기업은 제외'])

    def test_docx_는_런이_붙고_문단은_나뉜다(self):
        text, info = doctext.extract(
            self.zipped('a.docx', {'word/document.xml': DOCX_XML}))
        self.assertEqual(info['kind'], 'docx')
        self.assertEqual(text.splitlines(), ['지원대상 안내', '창업 3년 미만'])

    def test_여러_섹션을_순서대로_잇는다(self):
        path = self.zipped('a.hwpx', {
            'Contents/section1.xml': '<hp:p><hp:t>둘째</hp:t></hp:p>',
            'Contents/section0.xml': '<hp:p><hp:t>첫째</hp:t></hp:p>'})
        text, _ = doctext.extract(path)
        self.assertEqual(text.splitlines(), ['첫째', '둘째'])

    def test_xml_엔티티를_되돌린다(self):
        path = self.zipped('a.hwpx', {
            'Contents/section0.xml': '<hp:p><hp:t>기술개발&amp;사업화 &lt;주의&gt;</hp:t></hp:p>'})
        text, _ = doctext.extract(path)
        self.assertEqual(text, '기술개발&사업화 <주의>')

    def test_tidy_가_빈_줄과_중복_공백을_없앤다(self):
        path = self.zipped('a.hwpx', {
            'Contents/section0.xml': '<hp:p><hp:t>가   나</hp:t></hp:p><hp:p></hp:p>'})
        self.assertEqual(doctext.extract(path)[0], '가 나')
        self.assertIn('\n', doctext.extract(path, tidy=False)[0])

    def test_정보_dict_가_기본값을_갖춘다(self):
        _, info = doctext.extract(
            self.zipped('a.hwpx', {'Contents/section0.xml': HWPX_XML}))
        for key in ('kind', 'chars', 'image_only', 'bytes'):
            self.assertIn(key, info)
        self.assertGreater(info['chars'], 0)
        self.assertFalse(info['image_only'])

    def test_메모리에서_바로_읽는다(self):
        path = self.zipped('a.hwpx', {'Contents/section0.xml': HWPX_XML})
        with open(path, 'rb') as f:
            data = f.read()
        text, info = doctext.extract_bytes(data, suffix='.hwpx')
        self.assertEqual(info['kind'], 'hwpx')
        self.assertIn('업력', text)


class 계약(unittest.TestCase):
    """다른 파트가 기대할 수 있는 것."""

    def test_공개_이름이_유지된다(self):
        for name in ('extract', 'extract_bytes', 'sniff',
                     'DocTextError', 'UnsupportedFormat'):
            self.assertTrue(hasattr(doctext, name), name)

    def test_지원_형식_목록(self):
        self.assertEqual(doctext.SUPPORTED, ('pdf', 'hwp', 'hwpx', 'docx'))

    def test_모든_실패가_DocTextError_하위다(self):
        self.assertTrue(issubclass(doctext.UnsupportedFormat, doctext.DocTextError))

    def test_프로젝트_모듈에_의존하지_않는다(self):
        """다른 파트가 파일만 복사해 쓸 수 있어야 한다."""
        import ast
        with open(doctext.__file__, encoding='utf-8') as f:
            tree = ast.parse(f.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split('.')[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split('.')[0])
        project = {'config', 'gate', 'match', 'normalize', 'daily_job',
                   'store_mysql', 'fetch', 'fetch_bizinfo'}
        self.assertEqual(imported & project, set(),
                         'doctext 는 hwp5 외의 프로젝트 모듈을 쓰면 안 된다')


if __name__ == '__main__':
    unittest.main()
