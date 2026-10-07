"""구 HWP 본문 추출(collect/hwp5.py) — 실제 HWP 파일 없이 레코드 해석·본문 글자 해석만 확인한다.

OLE 파일을 여는 부분(extract)은 실제 HWP 샘플이 필요해 여기서 시험하지 않는다.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import struct
import tempfile
import unittest
import zlib

from collect import hwp5


def record(tag, payload, level=0):
    size = len(payload)
    if size >= 0xFFF:
        return struct.pack('<I', tag | (level << 10) | (0xFFF << 20)) + struct.pack('<I', size) + payload
    return struct.pack('<I', tag | (level << 10) | (size << 20)) + payload


def utf16(text):
    return text.encode('utf-16-le')


def wide(code):
    """8 WCHAR 를 차지하는 제어문자(코드 + 7칸 덧붙임)."""
    return struct.pack('<H', code) + b'\x00\x00' * 7


class RecordTests(unittest.TestCase):
    def test_tag_and_size(self):
        buf = record(hwp5.HWPTAG_PARA_TEXT, utf16('안녕')) + record(66, b'\x01\x02\x03')
        got = list(hwp5._records(buf))
        self.assertEqual(got, [(67, utf16('안녕')), (66, b'\x01\x02\x03')])

    def test_level_bits_do_not_change_tag(self):
        buf = record(hwp5.HWPTAG_PARA_TEXT, utf16('가'), level=3)
        self.assertEqual(list(hwp5._records(buf)), [(67, utf16('가'))])

    def test_extended_size(self):
        payload = utf16('가' * 3000)          # 6,000바이트 > 0xFFF
        got = list(hwp5._records(record(hwp5.HWPTAG_PARA_TEXT, payload)))
        self.assertEqual(got, [(67, payload)])

    def test_truncated_buffer_stops_quietly(self):
        buf = record(66, b'abcd') + b'\x01\x02'          # 헤더도 못 채운 끝부분
        self.assertEqual(list(hwp5._records(buf)), [(66, b'abcd')])
        cut = struct.pack('<I', 67 | (0xFFF << 20))      # 확장 크기 자리가 잘림
        self.assertEqual(list(hwp5._records(cut)), [])

    def test_raw_deflate_round_trip(self):
        # 압축 문서는 raw deflate(-15)로 풀린다 — extract 와 같은 방식
        raw = record(hwp5.HWPTAG_PARA_TEXT, utf16('압축 본문'))
        packer = zlib.compressobj(9, zlib.DEFLATED, -15)
        packed = packer.compress(raw) + packer.flush()
        got = list(hwp5._records(zlib.decompress(packed, -15)))
        self.assertEqual(hwp5._para_text(got[0][1]), '압축 본문')


class ParaTextTests(unittest.TestCase):
    def test_plain_korean(self):
        self.assertEqual(hwp5._para_text(utf16('지원 대상: 예비창업자')), '지원 대상: 예비창업자')

    def test_line_breaks_kept_other_single_controls_dropped(self):
        data = utf16('가') + struct.pack('<H', 13) + utf16('나') + struct.pack('<H', 10) \
            + struct.pack('<H', 24) + utf16('다')
        self.assertEqual(hwp5._para_text(data), '가\n나\n다')

    def test_wide_controls_skip_eight_units(self):
        data = utf16('표') + wide(11) + utf16('끝') + wide(2) + utf16('!')
        self.assertEqual(hwp5._para_text(data), '표끝!')

    def test_surrogate_pair_survives(self):
        self.assertEqual(hwp5._para_text(utf16('창업🚀지원')), '창업🚀지원')

    def test_odd_trailing_byte_ignored(self):
        self.assertEqual(hwp5._para_text(utf16('가나') + b'\x00'), '가나')


class ExtractGuardTests(unittest.TestCase):
    def test_non_ole_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'fake.hwp')
            with open(path, 'wb') as f:
                f.write(b'%PDF-1.4 not hwp')
            with self.assertRaises(hwp5.NotHwp5):
                hwp5.extract(path)


if __name__ == '__main__':
    unittest.main()
