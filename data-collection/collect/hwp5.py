# -*- coding: utf-8 -*-
"""구 HWP(5.0) 본문 텍스트 추출 — olefile + zlib 만 쓴다.

HWP 5.0 은 OLE 복합문서다.
  FileHeader        32바이트 서명 + 버전 + 속성 비트(bit0 = 압축)
  BodyText/Section* 본문. 압축이면 raw deflate

레코드 헤더는 uint32 하나다.
  tag  = h & 0x3FF          size = (h >> 20) & 0xFFF
  level= (h >> 10) & 0x3FF  size 가 0xFFF 면 다음 uint32 가 실제 크기

본문 텍스트는 HWPTAG_PARA_TEXT(67) 레코드에 UTF-16LE 로 들어 있다.
32 미만은 제어문자이며 일부는 8 WCHAR 를 차지한다.
"""
import os
import struct
import sys
import zlib

import olefile

__version__ = '1.0'

HWPTAG_PARA_TEXT = 0x10 + 51          # 67

_SINGLE = {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}
_WIDE = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}


class NotHwp5(Exception):
    pass


def _header(ole):
    if not ole.exists('FileHeader'):
        raise NotHwp5('FileHeader 스트림이 없다')
    h = ole.openstream('FileHeader').read()
    if not h.startswith(b'HWP Document File'):
        raise NotHwp5('HWP 5.0 서명이 아니다')
    props = struct.unpack('<I', h[36:40])[0]
    return {'compressed': bool(props & 1), 'encrypted': bool(props & 2),
            'distributed': bool(props & 4)}


def _records(buf):
    i, n = 0, len(buf)
    while i + 4 <= n:
        h = struct.unpack_from('<I', buf, i)[0]
        i += 4
        tag = h & 0x3FF
        size = (h >> 20) & 0xFFF
        if size == 0xFFF:
            if i + 4 > n:
                break
            size = struct.unpack_from('<I', buf, i)[0]
            i += 4
        yield tag, buf[i:i + size]
        i += size


def _para_text(data):
    """UTF-16LE 코드유닛을 그대로 모았다가 마지막에 한 번에 디코딩한다.

    chr() 로 한 유닛씩 만들면 BMP 밖 문자의 대리쌍이 깨져
    'surrogates not allowed' 로 터진다.
    """
    buf = bytearray()
    i, n = 0, len(data) // 2
    NL = chr(10).encode('utf-16-le')
    while i < n:
        ch = struct.unpack_from('<H', data, i * 2)[0]
        if ch in _SINGLE:
            if ch in (10, 13):
                buf += NL
            i += 1
        elif ch in _WIDE:
            i += 8
        else:
            buf += data[i * 2:i * 2 + 2]
            i += 1
    return buf.decode('utf-16-le', 'replace')


def extract(path):
    """본문 텍스트를 돌려준다. HWP 5.0 이 아니면 NotHwp5 를 올린다."""
    if not olefile.isOleFile(path):
        raise NotHwp5('OLE 파일이 아니다')
    ole = olefile.OleFileIO(path)
    try:
        info = _header(ole)
        if info['encrypted']:
            raise NotHwp5('암호가 걸린 문서다')
        secs = sorted(
            ('/'.join(e) for e in ole.listdir()
             if len(e) == 2 and e[0] == 'BodyText' and e[1].startswith('Section')),
            key=lambda s: int(s.rsplit('Section', 1)[1]))
        if not secs:
            raise NotHwp5('BodyText 섹션이 없다')
        parts = []
        for s in secs:
            raw = ole.openstream(s).read()
            if info['compressed']:
                raw = zlib.decompress(raw, -15)
            for tag, data in _records(raw):
                if tag == HWPTAG_PARA_TEXT:
                    parts.append(_para_text(data))
        text = chr(10).join(parts)

        # 본문이 거의 없고 그림이 대부분이면 스캔/이미지 문서다.
        # 실측 1,309건 중 3건이 이랬다 — BinData 91%, BodyText 0KB.
        # 파싱 실패가 아니라 문서에 텍스트가 없는 것이므로, 호출부가
        # OCR 대상으로 돌릴 수 있게 구분해 준다.
        info['bindata_bytes'] = sum(
            ole.get_size('/'.join(e)) for e in ole.listdir() if e[0] == 'BinData')
        info['text_chars'] = len(text)
        info['image_only'] = (len(text.strip()) < 200
                              and info['bindata_bytes'] > 10 * max(len(text), 1))
        return text, info
    finally:
        ole.close()


def main():
    """확인용 CLI.

      python hwp5.py 공고문.hwp                  본문을 화면에 출력
      python hwp5.py 공고문.hwp -o 결과.txt       파일로 저장
      python hwp5.py 폴더 -o 출력폴더             폴더 안 HWP 를 일괄 변환
    """
    import argparse
    import glob as _glob

    ap = argparse.ArgumentParser(description='구 HWP(5.0) 본문 텍스트 추출')
    ap.add_argument('path', help='HWP 파일 또는 폴더')
    ap.add_argument('-o', '--out', help='저장할 파일(또는 폴더). 생략하면 화면에 출력')
    ap.add_argument('-n', '--head', type=int, default=0,
                    help='앞의 N 글자만 출력한다 (기본: 전체)')
    args = ap.parse_args()

    targets = ([args.path] if os.path.isfile(args.path)
               else sorted(_glob.glob(os.path.join(args.path, '*.hwp*'))))
    if not targets:
        print('대상 파일이 없다: %s' % args.path, file=sys.stderr)
        return 1

    many = len(targets) > 1
    if many and args.out:
        os.makedirs(args.out, exist_ok=True)

    fails = 0
    for path in targets:
        try:
            text, info = extract(path)
        except NotHwp5 as e:
            print('건너뜀  %s — %s' % (os.path.basename(path), e), file=sys.stderr)
            fails += 1
            continue
        except Exception as e:
            print('실패    %s — %s: %s'
                  % (os.path.basename(path), type(e).__name__, e), file=sys.stderr)
            fails += 1
            continue

        if args.out:
            dst = (os.path.join(args.out, os.path.basename(path) + '.txt')
                   if many else args.out)
            with open(dst, 'w', encoding='utf-8') as f:
                f.write(text)
            print('%6d자 → %s' % (len(text), dst))
        else:
            if many:
                print('\n===== %s (%d자) =====' % (os.path.basename(path), len(text)))
            print(text[:args.head] if args.head else text)

    if many:
        print('\n성공 %d / %d' % (len(targets) - fails, len(targets)), file=sys.stderr)
    return 1 if fails and not many else 0


if __name__ == '__main__':
    raise SystemExit(main())
