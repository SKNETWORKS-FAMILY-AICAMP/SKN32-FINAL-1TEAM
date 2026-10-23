"""hwp 한 쪽 맞춤 · 글자 통일 · 별첨 표시 — 다 채운 .hwp를 .hwpx로 내보내 xml에서 고친 뒤 다시 .hwp로 바꿀 때 쓴다(hwp_export._fit_layout).

① 서체를 하나(함초롬바탕)로 통일하고 본문 · 표 글자 크기를 하나로 맞춘다. 크기는 후보(BODY_SIZES) 중 '창업 아이템 개요(요약)' 표가 한 쪽 안에 들어가는
   가장 큰 것으로 정한다 — 이 표는 양식에서 글자 12pt에 행 높이가 고정돼 있어 글이 길면 쪽 아래로 넘친다. 제목류(원래 14pt 넘는 글자)는 같은 비율로 줄인다.
② 표 행 높이를 줄어든 글자에 맞춘다. rhwp는 표 높이를 xml에 적힌 값 그대로 쓰므로(내용에 맞춰 줄이지 않는다) 개요 표는 내용에서 어림해 다시 쓰고,
   다른 표는 비율만큼 줄이되 내용보다 낮아지지 않게 한다. 줄 나눔 정보(linesegarray)는 지워 다시 계산하게 한다.
③ 그림 쪽(맨 뒤)의 맨 위에 `<별첨> …` 문구를 넣고, 개요 표의 '이미지' 칸 빈 칸에는 `<별첨 참고>`를 쓴다.
"""
from __future__ import annotations

import re

from app import hwpx_rows

BODY_SIZES = (1000, 950, 900, 850, 800)   # 본문 · 표 글자 크기 후보(1/100pt), 큰 것부터
KEEP_SIZE_MAX = 1400                      # 원래 이 크기 이하의 글자는 본문으로 보고 같은 크기로 맞춘다. 더 큰 글자(제목)는 비율로 줄인다
HEADING_BASE = 1200                       # 개요 표 본문(12pt)이 BODY 크기가 되는 비율을 제목에도 쓴다
FACE_NAME = '함초롬바탕'
FACE_LANGS = ('HANGUL', 'LATIN', 'HANJA', 'JAPANESE', 'OTHER', 'SYMBOL', 'USER')   # fontRef 속성 순서
ROW_SAFETY = 1.05                         # 줄 수 어림에 곱하는 여유(낱말 단위 줄바꿈으로 어림보다 줄이 늘어나는 만큼)
RESERVED_ABOVE_TABLE = 4500               # 개요 표 위 제목 문단 + 여유(HWPUNIT)
IMAGE_ROW_HEIGHT = 3500                   # '<별첨 참고>' 한 줄이 들어가는 이미지 칸 높이
ATTACHMENT_SHIFT = 1500                   # 별첨 문구가 들어가도록 그림을 내리는 만큼(HWPUNIT)

_CHAR_PR = re.compile(r'<hh:charPr id="(\d+)" height="(\d+)"')
_TC = re.compile(r'<hp:tc .*?</hp:tc>', re.S)
_TR = re.compile(r'<hp:tr>.*?</hp:tr>', re.S)
_LINESEG = re.compile(r'<hp:linesegarray>.*?</hp:linesegarray>', re.S)
_PIC_PARA = re.compile(r'(<hp:p [^>]*>)(<hp:run charPrIDRef="\d+">)((?:(?!</hp:p>).)*?<hp:pic.*?)(</hp:run></hp:p>)', re.S)


def _face_ids(header: str) -> dict[str, str]:
    """언어별 함초롬바탕 글꼴 번호 — 양식 header에 없는 언어는 빠진다."""
    ids: dict[str, str] = {}
    for match in re.finditer(r'<hh:fontface lang="(\w+)"[^>]*>(.*?)</hh:fontface>', header, re.S):
        font = re.search(rf'<hh:font id="(\d+)" face="{FACE_NAME}"', match.group(2))
        if font:
            ids[match.group(1)] = font.group(1)
    return ids


def _unify_header(header: str, body_size: int) -> str:
    """서체를 하나로, 크기를 body_size 하나(본문)와 비율로 줄인 제목으로 바꾼 header."""
    scale = body_size / HEADING_BASE

    def size(match: re.Match) -> str:
        height = int(match.group(2))
        if 800 <= height <= KEEP_SIZE_MAX:
            height = body_size
        else:
            height = max(min(height, 800), int(round(height * scale / 50.0) * 50))
        return f'<hh:charPr id="{match.group(1)}" height="{height}"'

    header = _CHAR_PR.sub(size, header)
    faces = _face_ids(header)
    if 'HANGUL' not in faces:
        return header   # 양식에 함초롬바탕이 없으면 서체는 그대로 둔다

    def font_ref(match: re.Match) -> str:
        current = dict(zip(FACE_LANGS, re.findall(r'="(\d+)"', match.group(1)), strict=False))
        return '<hh:fontRef ' + ' '.join(f'{lang.lower()}="{faces.get(lang, current[lang])}"' for lang in FACE_LANGS) + '/>'

    return re.sub(r'<hh:fontRef ([^/]*)/>', font_ref, header)


def _text(xml: str) -> str:
    return re.sub(r'<[^>]+>', '', ''.join(re.findall(r'<hp:t>(.*?)</hp:t>', xml, re.S)))


def _paragraph_text(para: str) -> str:
    """문단 글 — 줄바꿈(<hp:lineBreak/>)은 개행으로 살린다."""
    return re.sub(r'<[^>]+>', '', ''.join(re.findall(r'<hp:t>(.*?)</hp:t>', para.replace('<hp:lineBreak/>', '\n'), re.S)))


def _cell_need(cell: str, styles: hwpx_rows.Styles) -> int:
    """칸 글이 차지하는 높이(HWPUNIT) 어림 — 문단마다 줄 수 × 줄 높이 + 칸 위 · 아래 여백."""
    width = int(re.search(r'<hp:cellSz width="(\d+)"', cell).group(1))
    left, right, top, bottom = (int(v) for v in re.search(
        r'<hp:cellMargin left="(\d+)" right="(\d+)" top="(\d+)" bottom="(\d+)"', cell).groups())
    available = max(1, width - left - right)
    total = 0
    for para in re.finditer(r'<hp:p id="\d+" paraPrIDRef="(\d+)".*?</hp:p>', cell, re.S):
        runs = re.findall(r'<hp:run charPrIDRef="(\d+)">', para.group(0))
        font = max([styles.char_height.get(run, 1000) for run in runs] or [1000])
        percent = styles.line_spacing.get(para.group(1), 130)
        lines = 0
        for line in _paragraph_text(para.group(0)).split('\n'):
            line_width = sum(font * (1.0 if ord(ch) > 0xFF else 0.55) for ch in line)
            lines += max(1, -(-int(line_width * ROW_SAFETY) // available))
        total += lines * round(font * percent / 100)
    return total + top + bottom


def _row_heights(table: str, styles: hwpx_rows.Styles, scale: float, from_content: bool) -> list[int]:
    """표 행마다 새 높이. from_content면 내용 어림값(원래 높이가 아무리 커도 내용에 맞춰 줄인다), 아니면 원래 높이 × scale이되 내용 어림값보다 낮아지지 않게."""
    heights = []
    for row in _TR.finditer(table):
        best = 0
        for cell in _TC.finditer(row.group(0)):
            text = cell.group(0)
            if int(re.search(r'rowSpan="(\d+)"', text).group(1)) != 1:
                continue   # 세로로 병합된 칸은 걸친 행들의 합으로 따로 정한다
            old = int(re.search(r'<hp:cellSz width="\d+" height="(\d+)"', text).group(1))
            scaled, need = max(500, int(old * scale)), _cell_need(text, styles)
            best = max(best, max(need, 1500) if from_content else max(scaled, need))
        heights.append(best or int(3000 * scale))
    return heights


def _apply_heights(table: str, heights: list[int]) -> str:
    """행 높이를 칸(세로 병합은 걸친 행의 합)과 표 전체 높이에 쓴다."""
    out, offset = table, 0
    for index, row in enumerate(_TR.finditer(table)):
        def cell(match: re.Match, index: int = index) -> str:
            text = match.group(0)
            span = int(re.search(r'rowSpan="(\d+)"', text).group(1))
            return re.sub(r'(<hp:cellSz width="\d+" height=")\d+"', lambda k: f'{k.group(1)}{sum(heights[index:index + span])}"', text)
        fixed = _TC.sub(cell, row.group(0))
        start, end = row.span()
        out = out[:start + offset] + fixed + out[end + offset:]
        offset += len(fixed) - (end - start)
    return re.sub(r'(<hp:tbl [^>]*><hp:sz width="\d+" widthRelTo="ABSOLUTE" height=")\d+"',
                  lambda k: f'{k.group(1)}{sum(heights)}"', out, count=1)


def _find_overview(xml: str) -> int | None:
    """'창업 아이템 개요(요약)' 표 — 문제 인식 · 성장전략 행과 '이미지' 칸이 함께 있는 본문 최상위 표 번호."""
    for index, (start, end) in enumerate(hwpx_rows.top_level_tables(xml)):
        text = _text(xml[start:end])
        if '문제 인식' in text and '성장전략' in text and '이미지' in text:
            return index
    return None


def _page_body_height(xml: str) -> int:
    page = re.search(r'<hp:pagePr[^>]* height="(\d+)"', xml)
    margin = re.search(r'<hp:margin header="(\d+)" footer="(\d+)"[^>]* top="(\d+)" bottom="(\d+)"', xml)
    if not page or not margin:
        return 70015   # A4 세로, 양식의 기본 여백
    header, footer, top, bottom = (int(v) for v in margin.groups())
    return int(page.group(1)) - header - footer - top - bottom


def _heading_char_id(header: str) -> str | None:
    """양식에서 제목에 쓰는 글자 모양 — 원래 16pt인 검은 글자. 없으면 None(그림 쪽 문구를 본문 글자로 쓴다)."""
    for match in re.finditer(r'<hh:charPr id="(\d+)" height="1600" textColor="#000000"', header):
        return match.group(1)
    return None


def fit_document(section: str, header: str, attachment_labels: list[str]) -> tuple[str, str]:
    """다 채운 hwpx의 (section0.xml, header.xml)을 한 쪽 맞춤 · 글자 통일 · 별첨 표시로 고쳐 돌려준다.

    attachment_labels: 그림 쪽마다 맨 위에 넣을 문구(순서대로). 비어 있으면 별첨 표시를 하지 않는다."""
    heading_char = _heading_char_id(header)   # 크기를 줄이기 전 header에서 찾는다
    section = _LINESEG.sub('', section)
    overview = _find_overview(section)
    spans = hwpx_rows.top_level_tables(section)
    body_height = _page_body_height(section) - RESERVED_ABOVE_TABLE

    chosen = BODY_SIZES[-1]
    for size in BODY_SIZES:
        styles = hwpx_rows.Styles(_unify_header(header, size))
        if overview is None or sum(_row_heights(section[slice(*spans[overview])], styles, size / HEADING_BASE, True)) <= body_height:
            chosen = size
            break
    header = _unify_header(header, chosen)
    styles = hwpx_rows.Styles(header)
    scale = chosen / HEADING_BASE

    for index in range(len(spans) - 1, -1, -1):
        start, end = spans[index]
        table = section[start:end]
        heights = _row_heights(table, styles, scale, index == overview)
        if index == overview:
            heights = _image_row(table, heights)
        # 긴 팀원·일정·사업비 표도 쪽 나눔과 글자처럼 취급 해제를 함께 적용한다.
        if sum(heights) > body_height:
            table = _allow_page_split(table)
        section = section[:start] + _apply_heights(table, heights) + section[end:]

    if attachment_labels:
        section = _label_attachments(section, attachment_labels, heading_char)
        section = _mark_overview_images(section)
    return section, header


_TABLE_PAGE_BREAK = re.compile(r'(<hp:tbl\b[^>]*?\bpageBreak=")[A-Z]+(")')


def _allow_page_split(table: str) -> str:
    """표를 행 단위로 쪽 경계에서 나눌 수 있게(`pageBreak="CELL"`) 바꾼다 — 한 쪽보다 길어진 표가 쪽 아래로 넘치는 대신 다음 쪽으로 이어진다."""
    table = _TABLE_PAGE_BREAK.sub(r'\1CELL\2', table, count=1)
    # '글자처럼 취급'인 표는 글자 한 줄처럼 쪽 경계에서 나뉘지 않는다 — 풀어야 행이 다음 쪽으로 이어진다
    return re.sub(r'(<hp:pos [^>]*?\btreatAsChar=")1(")', r'\g<1>0\2', table, count=1)


def _image_row(table: str, heights: list[int]) -> list[int]:
    """개요 표의 '이미지' 행은 내용이 비어 있어 내용 어림으로는 낮아지므로, '<별첨 참고>' 한 줄 높이로 정한다."""
    for index, row in enumerate(_TR.finditer(table)):
        if _text(row.group(0)).startswith('이미지'):
            heights[index] = IMAGE_ROW_HEIGHT
    return heights


def _mark_overview_images(section: str) -> str:
    """개요 표 '이미지' 행의 빈 칸에 `<별첨 참고>` — 양식의 빈 칸 글자는 파란 안내색이라, 개요 칸 본문 글자 모양과 아래 제목 줄(가운데 정렬) 문단 모양을 쓴다."""
    index = _find_overview(section)
    if index is None:
        return section
    start, end = hwpx_rows.top_level_tables(section)[index]
    table = section[start:end]
    rows = list(_TR.finditer(table))
    image = next((i for i, row in enumerate(rows) if _text(row.group(0)).startswith('이미지')), None)
    body = next((row for row in rows if _text(row.group(0)).startswith('아이템 개요')), None)
    if image is None or body is None or image + 1 >= len(rows):
        return section
    char = re.findall(r'<hp:run charPrIDRef="(\d+)"', body.group(0))[-1]   # 같은 행 맨 오른쪽 칸(개요 본문)의 글자 모양
    para = re.search(r'<hp:p id="\d+" paraPrIDRef="(\d+)"', rows[image + 1].group(0)).group(1)   # 이미지 아래 제목 줄 문단 모양

    def fill(match: re.Match) -> str:
        return (f'<hp:p id="{match.group(1)}" paraPrIDRef="{para}"{match.group(2)}><hp:run charPrIDRef="{char}">'
                '<hp:t>&lt;별첨 참고&gt;</hp:t></hp:run></hp:p>')
    fixed = re.sub(r'<hp:p id="(\d+)" paraPrIDRef="\d+"( [^>]*)><hp:run charPrIDRef="\d+"><hp:t></hp:t></hp:run></hp:p>',
                   fill, rows[image].group(0))
    table = table[:rows[image].start()] + fixed + table[rows[image].end():]
    return section[:start] + table + section[end:]


def _label_attachments(section: str, labels: list[str], heading_char: str | None) -> str:
    """그림이 붙은 쪽(맨 뒤)마다 맨 위에 별첨 문구를 넣고 그림은 그만큼 아래로 내린다. 그림 쪽 수가 문구 수와 다르면 그대로 둔다."""
    pages = list(_PIC_PARA.finditer(section))
    if len(pages) != len(labels):
        return section
    texts = iter(labels)

    def label(match: re.Match) -> str:
        text = next(texts).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        body = re.sub(r'(<hp:pos [^>]*vertOffset=")(\d+)"', lambda k: f'{k.group(1)}{int(k.group(2)) + ATTACHMENT_SHIFT}"', match.group(3))
        char = heading_char or re.search(r'charPrIDRef="(\d+)"', match.group(2)).group(1)
        return f'{match.group(1)}<hp:run charPrIDRef="{char}"><hp:t>{text}</hp:t></hp:run>{match.group(2)}{body}{match.group(4)}'

    return _PIC_PARA.sub(label, section)
