"""양식 .hwp의 표 안 파란 예시 상자(안쪽 1x1 표)를 지운 템플릿을 만든다 — `app/assets/hwp_templates/*_정리.hwp`가 이 스크립트의 결과다.

양식은 항목마다 칸 안에 "※ 예시 …" · "※ 개발하고자 하는 …" 같은 안내 상자(칸 안에 든 1x1 표)가 있고, 웹이 그 칸에 글을 쓰면 안내 상자와
겹쳐 값이 가려졌다. rhwp의 delete-table은 본문 최상위 표만 지우고 칸 안 표를 지우는 편집 명령이 없어서, .hwp → .hwpx로 내보내
section0.xml에서 칸 안쪽의 표(<hp:tbl>)를 지우고 다시 .hwp로 바꾼다(--verify-pages로 쪽 수가 같은지 확인).

    RHWP_BIN=<rhwp 경로> python scripts/clean_hwp_template.py <원본 양식.hwp> <출력.hwp>

바꾼 뒤 확인한 것: 두 양식 모두 쪽 수 · 문단 수 · 최상위 표 수가 원본과 같고(예비창업 8쪽 91문단 22표, 초기창업 8쪽 86문단 21표), 지운 안쪽 표는
예비창업 10개 · 초기창업 12개다. 그래서 hwp_export.py의 문단 · 표 번호는 그대로 쓴다. 원본 양식 파일은 그대로 두었다.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

RHWP = os.environ.get('RHWP_BIN') or 'rhwp'


def run(*args):
    out = subprocess.run([RHWP, *args], capture_output=True, text=True, encoding='utf-8')
    if out.returncode != 0:
        raise SystemExit(f'rhwp 실패: {args}\n{out.stdout}\n{out.stderr}')
    return out.stdout


def strip_nested_tables(xml: str) -> tuple[str, int]:
    """셀(<hp:tc>) 안에 든 표(<hp:tbl>)를 통째로 지운다(바깥 표는 둔다). 지운 개수를 함께 돌려준다."""
    tokens = list(re.finditer(r'<(/?)hp:(tbl|tc)\b[^>]*?(/?)>', xml))
    stack, spans = [], []  # spans: 지울 (시작, 끝)
    for m in tokens:
        close, tag, selfclose = m.group(1), m.group(2), m.group(3)
        if selfclose:
            continue
        if not close:
            if tag == 'tbl' and any(s[0] == 'tc' for s in stack) and not any(s[0] == 'del' for s in stack):
                stack.append(('del', m.start()))
                stack.append(('tbl', m.start()))
            else:
                stack.append((tag, m.start()))
        else:
            name, start = stack.pop()
            assert name == tag, (name, tag)
            if tag == 'tbl' and stack and stack[-1][0] == 'del':
                _, begin = stack.pop()
                spans.append((begin, m.end()))
    out, last = [], 0
    for begin, end in sorted(spans):
        out.append(xml[last:begin])
        last = end
    out.append(xml[last:])
    return ''.join(out), len(spans)


def main(src: str, dst: str) -> None:
    work = tempfile.mkdtemp(prefix='hwp_strip_')
    try:
        hwpx = os.path.join(work, 'a.hwpx')
        run('export-hwpx', src, hwpx)
        with zipfile.ZipFile(hwpx) as z:
            names = z.namelist()
            data = {n: z.read(n) for n in names}
        xml, removed = strip_nested_tables(data['Contents/section0.xml'].decode('utf-8'))
        data['Contents/section0.xml'] = xml.encode('utf-8')
        stripped = os.path.join(work, 'b.hwpx')
        with zipfile.ZipFile(stripped, 'w') as z:
            for n in names:  # mimetype을 맨 앞에 두고 압축하지 않는다(HWPX 규칙)
                z.writestr(zipfile.ZipInfo(n) if n == 'mimetype' else n, data[n],
                           compress_type=zipfile.ZIP_STORED if n == 'mimetype' else zipfile.ZIP_DEFLATED)
        run('convert', stripped, dst, '--verify-pages')
        print(f'지운 안쪽 표 {removed}개 → {dst}')
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
