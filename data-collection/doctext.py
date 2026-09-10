# -*- coding: utf-8 -*-
"""문서에서 본문 텍스트를 뽑는다 — PDF · HWP · HWPX · DOCX.

이 파일과 `hwp5.py` 두 개만 복사하면 어느 파트에서든 쓸 수 있다.
프로젝트의 다른 모듈(config·gate·normalize 등)에 의존하지 않는다.

  import doctext
  text, info = doctext.extract('공고문.hwp')

  print(info['kind'])        'pdf' | 'hwp' | 'hwpx' | 'docx'
  print(info['image_only'])  True 면 스캔 이미지 문서. OCR 이 필요하다

명령줄로도 쓴다.

  python doctext.py 문서.hwp                앞부분을 화면에 출력
  python doctext.py 문서.pdf -o 결과.txt     파일로 저장
  python doctext.py 폴더 -o 출력폴더          폴더 안 문서를 일괄 변환
  python doctext.py 폴더 --report            형식·성공률만 표로 본다

## 필요한 것

  pdfplumber   PDF 를 읽을 때만
  olefile      구 HWP 를 읽을 때만 (hwp5.py 가 쓴다)

둘 다 없어도 모듈은 임포트된다. 해당 형식을 만났을 때만 안내와 함께 실패한다.
HWPX · DOCX 는 표준 라이브러리만으로 처리한다.

## 왜 확장자를 믿지 않는가

실측 1,300여 건에서 `.hwp` 인데 실제로는 HWPX 인 파일, `.hwpx` 인데 구 HWP 인
파일이 각각 나왔다. **매직바이트(파일 앞 몇 바이트)로 판별한다.**

## 알아둘 한계

- 표는 평탄화된다. 셀 구분이 사라지고 텍스트만 이어진다
- 머리말·꼬리말·각주는 빠진다. 본문만 읽는다
- 그림 안의 글자는 나오지 않는다. `info['image_only']` 로 구분할 수 있다
- 구 워드(`.doc`)와 암호가 걸린 문서는 지원하지 않는다
"""
import os
import re
import sys
import zipfile

__version__ = '1.0'
__all__ = ['extract', 'extract_bytes', 'sniff', 'version', 'SUPPORTED',
           'DocTextError', 'UnsupportedFormat']

# 파일 앞부분으로 형식을 정한다. 순서가 중요하다 — zip 계열은 안을 더 봐야 한다.
MAGIC = [
    (b'%PDF', 'pdf'),
    (b'\x89PNG\r\n\x1a\n', 'image'),
    (b'\xff\xd8\xff', 'image'),
    (b'GIF8', 'image'),
    (b'PK\x03\x04', 'zip'),          # hwpx · docx · 그냥 zip
    (b'\xd0\xcf\x11\xe0', 'ole'),    # 구 HWP · 구 워드 · 구 엑셀
    (b'{\\rt', 'rtf'),
]

# zip 안에 이 파일이 있으면 해당 형식이다
ZIP_MARKERS = [
    ('hwpx', re.compile(r'^Contents/section\d+\.xml$')),
    ('docx', re.compile(r'^word/document\.xml$')),
]

SUPPORTED = ('pdf', 'hwp', 'hwpx', 'docx')


def version():
    """추출기 버전 문자열. 결과를 저장할 때 함께 남긴다.

    추출 규칙이나 의존 라이브러리가 바뀌면 값이 달라진다. 저장 쪽에서 이 값을
    비교해 **원본이 그대로여도 다시 추출할지** 판단할 수 있다.

        doctext/1.0 hwp5/1.0 pdfplumber/0.11.4
    """
    parts = ['doctext/' + __version__]
    try:
        import hwp5
        parts.append('hwp5/' + getattr(hwp5, '__version__', '?'))
    except ImportError:
        parts.append('hwp5/-')
    try:
        import pdfplumber
        parts.append('pdfplumber/' + getattr(pdfplumber, '__version__', '?'))
    except ImportError:
        parts.append('pdfplumber/-')
    return ' '.join(parts)


class DocTextError(Exception):
    """텍스트를 뽑지 못했다."""


class UnsupportedFormat(DocTextError):
    """지원하지 않는 형식이다."""


def _zip_kind(source):
    try:
        with zipfile.ZipFile(source) as z:
            names = z.namelist()
    except Exception:
        return 'zip'
    for kind, pattern in ZIP_MARKERS:
        if any(pattern.match(n) for n in names):
            return kind
    return 'zip'


def sniff(source):
    """형식 이름을 돌려준다. 경로나 bytes 를 받는다.

    확장자를 보지 않는다. 파일 앞부분과 zip 내부 구성만 본다.
    """
    if isinstance(source, (bytes, bytearray)):
        head, zip_source = bytes(source[:16]), None
        if head.startswith(b'PK\x03\x04'):
            import io as _io
            zip_source = _io.BytesIO(source)
    else:
        with open(source, 'rb') as f:
            head = f.read(16)
        zip_source = source

    kind = next((k for m, k in MAGIC if head.startswith(m)), 'unknown')
    if kind == 'zip':
        return _zip_kind(zip_source) if zip_source is not None else 'zip'
    return kind


# ── 형식별 추출 ────────────────────────────────────────────
def _from_pdf(path, max_pages):
    try:
        import pdfplumber
    except ImportError:
        raise DocTextError('PDF 를 읽으려면 pdfplumber 가 필요하다: pip install pdfplumber')
    with pdfplumber.open(path) as pdf:
        pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
        return '\n'.join((p.extract_text() or '') for p in pages)


def _from_xml_zip(path, member_pattern, para_tags, text_tag=None):
    """HWPX·DOCX 공통. 해당 XML 에서 태그를 벗기고 문단 경계를 살린다."""
    parts = []
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist() if member_pattern.match(n))
        for name in names:
            xml = z.read(name).decode('utf-8', 'replace')
            for tag in para_tags:
                xml = re.sub(r'</%s>' % tag, '\n', xml)
            if text_tag:
                # 텍스트 런 사이에 공백이 끼지 않도록 여는 태그만 지운다
                xml = re.sub(r'<%s[^>]*>' % text_tag, '', xml)
            xml = re.sub(r'<[^>]+>', '', xml)
            parts.append(xml)
    text = '\n'.join(parts)
    # XML 엔티티 되돌리기
    for a, b in (('&lt;', '<'), ('&gt;', '>'), ('&quot;', '"'),
                 ('&apos;', "'"), ('&#39;', "'"), ('&amp;', '&')):
        text = text.replace(a, b)
    return text


def _from_hwpx(path):
    return _from_xml_zip(path, re.compile(r'^Contents/section\d+\.xml$'),
                         para_tags=('hp:p',), text_tag='hp:t')


def _from_docx(path):
    return _from_xml_zip(path, re.compile(r'^word/document\.xml$'),
                         para_tags=('w:p', 'w:tr'), text_tag='w:t')


def _from_hwp(path):
    try:
        import hwp5
    except ImportError:
        raise DocTextError('구 HWP 를 읽으려면 같은 폴더에 hwp5.py 가 있어야 한다')
    return hwp5.extract(path)


# ── 공개 함수 ──────────────────────────────────────────────
def extract(path, max_pages=40, tidy=True):
    """문서 → (본문 텍스트, 정보 dict).

    정보 dict
        kind         판별된 형식
        chars        글자 수
        image_only   본문이 거의 없고 그림이 대부분이다 (구 HWP 만 판정한다)
        bytes        파일 크기

    실패하면 DocTextError 또는 UnsupportedFormat 을 올린다.
    """
    kind = sniff(path)
    info = {'kind': kind, 'bytes': os.path.getsize(path),
            'image_only': False, 'chars': 0}

    if kind == 'pdf':
        text = _from_pdf(path, max_pages)
    elif kind == 'hwpx':
        text = _from_hwpx(path)
    elif kind == 'docx':
        text = _from_docx(path)
    elif kind == 'hwp' or kind == 'ole':
        text, meta = _from_hwp(path)
        info['kind'] = 'hwp'
        info['image_only'] = bool(meta.get('image_only'))
        info['bindata_bytes'] = meta.get('bindata_bytes', 0)
    elif kind == 'image':
        raise UnsupportedFormat('그림 파일이다. 글자를 읽으려면 OCR 이 필요하다')
    elif kind == 'rtf':
        raise UnsupportedFormat('RTF 는 지원하지 않는다')
    elif kind == 'zip':
        raise UnsupportedFormat('내용을 알 수 없는 zip 이다')
    else:
        raise UnsupportedFormat('알 수 없는 형식이다 (매직바이트 불일치)')

    if tidy:
        lines = [re.sub(r'[^\S\n]+', ' ', line).strip() for line in text.splitlines()]
        text = '\n'.join(line for line in lines if line)
    info['chars'] = len(text)
    return text, info


def extract_bytes(data, suffix='.bin', **kw):
    """메모리에 있는 파일을 처리한다. 임시 파일을 만들었다 지운다.

    파일을 디스크에 남기고 싶지 않을 때 쓴다.
    """
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        return extract(tmp, **kw)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ── 명령줄 ────────────────────────────────────────────────
def _targets(path):
    if os.path.isfile(path):
        return [path]
    import glob
    return sorted(f for f in glob.glob(os.path.join(path, '*')) if os.path.isfile(f))


def main():
    import argparse
    from collections import Counter

    ap = argparse.ArgumentParser(description='문서에서 본문 텍스트를 뽑는다')
    ap.add_argument('path', help='문서 파일 또는 폴더')
    ap.add_argument('-o', '--out', help='저장할 파일(또는 폴더). 생략하면 화면에 출력')
    ap.add_argument('-n', '--head', type=int, default=600,
                    help='화면에 출력할 글자 수. 0 이면 전체 (기본 600)')
    ap.add_argument('--report', action='store_true', help='형식·성공률만 표로 본다')
    args = ap.parse_args()

    files = _targets(args.path)
    if not files:
        print('대상 파일이 없다: %s' % args.path, file=sys.stderr)
        return 1

    many = len(files) > 1
    if many and args.out:
        os.makedirs(args.out, exist_ok=True)

    stat, fails = Counter(), []
    for path in files:
        name = os.path.basename(path)
        try:
            text, info = extract(path)
        except DocTextError as e:
            stat['실패'] += 1
            fails.append((name, str(e)))
            if not args.report:
                print('건너뜀  %s — %s' % (name, e), file=sys.stderr)
            continue
        except Exception as e:
            stat['오류'] += 1
            fails.append((name, '%s: %s' % (type(e).__name__, e)))
            if not args.report:
                print('실패    %s — %s: %s' % (name, type(e).__name__, e), file=sys.stderr)
            continue

        stat[info['kind']] += 1
        if info['image_only']:
            stat['그림문서'] += 1

        if args.report:
            continue
        if args.out:
            dst = os.path.join(args.out, name + '.txt') if many else args.out
            with open(dst, 'w', encoding='utf-8') as f:
                f.write(text)
            print('%-9s %7d자 → %s' % (info['kind'], info['chars'], dst))
        else:
            if many:
                print('\n===== %s  [%s] %d자 =====' % (name, info['kind'], info['chars']))
            print(text[:args.head] if args.head else text)

    if many or args.report:
        print('\n대상 %d건' % len(files), file=sys.stderr)
        for k, v in stat.most_common():
            print('  %-10s %4d' % (k, v), file=sys.stderr)
        if fails:
            print('\n실패 %d건' % len(fails), file=sys.stderr)
            for name, why in fails[:10]:
                print('  %-46s %s' % (name[:46], why), file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
