"""HWPX(section0.xml) 안 표의 행을 복제한다 — hwp 표에 입력 줄이 양식의 고정 행 수보다 많을 때 쓴다.

rhwp의 `edit insert-row`는 열 격자대로 칸이 나뉜 평범한 행을 만들어, 칸 병합(팀 구성 표의 '담당 업무'가 두 열에 걸치는 것 등)이 풀리고 칸 폭 ·
테두리가 어긋난다. 그래서 .hwp를 .hwpx로 내보내 기준 행(`<hp:tr>`)을 통째로 복제한 뒤 다시 .hwp로 바꾼다(hwp_export._prepare_tables).
복제한 행은 글자를 비우고 행 번호(rowAddr)를 이어 붙이며, 뒤 행의 번호와 표의 행 수(rowCnt) · 높이를 그만큼 고친다.

표 번호는 rhwp의 `export-tables`와 같다(본문 최상위 표를 문서 순서로 0부터). 칸 안에 든 표(양식의 파란 예시 상자)는 정리한 양식에서
이미 지웠으므로 표 안에 표가 있으면 복제하지 않고 오류를 낸다.
"""
from __future__ import annotations

import re

_TBL_TAG = re.compile(r'<(/?)hp:tbl\b[^>]*?(/?)>')
_TEXT = re.compile(r'<hp:t>.*?</hp:t>', re.S)
_ROW = re.compile(r'<hp:tr>.*?</hp:tr>', re.S)
_ROW_ADDR = re.compile(r'rowAddr="(\d+)"')
_CELL_HEIGHT = re.compile(r'<hp:cellSz width="\d+" height="(\d+)"')
_ROW_SPAN = re.compile(r'<hp:cellSpan colSpan="\d+" rowSpan="(\d+)"')


def top_level_tables(xml: str) -> list[tuple[int, int]]:
    """본문 최상위 표(`<hp:tbl>`)의 (시작, 끝) 위치를 문서 순서대로."""
    spans: list[tuple[int, int]] = []
    depth, start = 0, 0
    for match in _TBL_TAG.finditer(xml):
        if match.group(2):  # <hp:tbl .../> 자기 닫힘
            continue
        if not match.group(1):
            if depth == 0:
                start = match.start()
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                spans.append((start, match.end()))
    return spans


def clone_rows(xml: str, table_index: int, row: int, count: int) -> str:
    """표 `table_index`의 `row`번 행을 그 아래에 `count`개 복제한 xml을 돌려준다(복제한 행의 글자는 비운다)."""
    if count <= 0:
        return xml
    tables = top_level_tables(xml)
    if not 0 <= table_index < len(tables):
        raise ValueError(f'표 {table_index}이 없습니다(최상위 표 {len(tables)}개)')
    start, end = tables[table_index]
    table = xml[start:end]
    if len(_TBL_TAG.findall(table)) != 2:
        raise ValueError(f'표 {table_index} 안에 다른 표가 들어 있어 행을 복제할 수 없습니다')
    rows = list(_ROW.finditer(table))
    if not 0 <= row < len(rows):
        raise ValueError(f'표 {table_index}에 {row}번 행이 없습니다(행 {len(rows)}개)')
    source = rows[row]
    source_xml = source.group(0)
    if any(int(span) != 1 for span in _ROW_SPAN.findall(source_xml)):
        raise ValueError(f'표 {table_index}의 {row}번 행에 세로로 병합된 칸이 있어 복제할 수 없습니다')
    heights = [int(h) for h in _CELL_HEIGHT.findall(source_xml)]
    row_height = max(heights) if heights else 0

    blank = _TEXT.sub('<hp:t></hp:t>', source_xml)
    clones = ''.join(_ROW_ADDR.sub(f'rowAddr="{row + offset}"', blank) for offset in range(1, count + 1))
    tail = _ROW_ADDR.sub(lambda m: f'rowAddr="{int(m.group(1)) + count}"', table[source.end():])
    new_table = table[:source.end()] + clones + tail

    new_table = re.sub(r'rowCnt="(\d+)"', lambda m: f'rowCnt="{int(m.group(1)) + count}"', new_table, count=1)
    if row_height:
        new_table = re.sub(r'(<hp:sz width="\d+" widthRelTo="ABSOLUTE" height=")(\d+)(")',
                           lambda m: f'{m.group(1)}{int(m.group(2)) + row_height * count}{m.group(3)}', new_table, count=1)
    return xml[:start] + new_table + xml[end:]


# ── 행 높이 ─────────────────────────────────────────────────────────────────────
# 양식의 칸 높이(cellSz height)는 한 줄 기준이거나, 파란 예시 상자가 들어 있던 자리라 필요 이상으로 크다(예: 개요 표 행 7339 ~ 10169). 그래서 칸에 들어갈 글의
# 줄 수를 어림해 ① 모자라면 행 높이를 늘리고(여러 줄 · 줄바꿈 글이 잘리지 않게) ② 지나치게 크면 내용에 맞게 줄인다(표가 한 쪽을 넘쳐 쪽 밖으로 나가지 않게).
# 한글이 행 높이를 자동으로 늘려 주는지는 확인하지 못했으므로 계산한 높이를 파일에 직접 적는다.
_TC = re.compile(r'<hp:tc\b.*?</hp:tc>', re.S)
_CELL_ADDR = re.compile(r'<hp:cellAddr colAddr="(\d+)" rowAddr="(\d+)"/>')
_CELL_SZ = re.compile(r'<hp:cellSz width="(\d+)" height="(\d+)"/>')
_CELL_MARGIN = re.compile(r'<hp:cellMargin left="(\d+)" right="(\d+)" top="(\d+)" bottom="(\d+)"/>')
_LINESEG = re.compile(r'<hp:lineseg [^>]*?vertsize="(\d+)"[^>]*?spacing="(\d+)"')
_TABLE_SZ = re.compile(r'(<hp:sz width="\d+" widthRelTo="ABSOLUTE" height=")(\d+)(")')
_CHAR_HEIGHT = re.compile(r'<hh:charPr id="(\d+)" height="(\d+)"')
_LINE_SPACING = re.compile(r'<hh:lineSpacing type="PERCENT" value="(\d+)"')
_RUN_CHAR = re.compile(r'<hp:run charPrIDRef="(\d+)"')
_NARROW_CHAR = 0.55   # 영문 · 숫자 · 기호 한 글자의 폭(한글 한 글자 = 글자 크기 1.0)
OVERSIZED_ROW = 5000  # 이보다 큰 행은 내용에 맞게 줄인다
MIN_ROW = 3000        # 줄여도 이보다 작게 하지는 않는다


def estimate_lines(lines: list[str], available_width: int, font_size: int) -> int:
    """글 줄들이 폭 `available_width`(HWPUNIT)인 칸에서 차지할 줄 수(어림) — 빈 줄도 한 줄."""
    total = 0
    for line in lines:
        width = sum(font_size * (1.0 if ord(ch) > 0xFF else _NARROW_CHAR) for ch in line)
        total += max(1, -(-int(width) // max(1, available_width)))
    return max(1, total)


class Styles:
    """header.xml에서 글자 크기(charPr)와 줄 간격(paraPr)을 읽는다 — 칸의 줄 높이를 계산할 때 쓴다."""

    def __init__(self, header_xml: str) -> None:
        self.char_height = {m.group(1): int(m.group(2)) for m in _CHAR_HEIGHT.finditer(header_xml)}
        self.line_spacing: dict[str, int] = {}
        for m in re.finditer(r'<hh:paraPr id="(\d+)".*?</hh:paraPr>', header_xml, re.S):
            spacing = _LINE_SPACING.search(m.group(0))
            if spacing:
                self.line_spacing[m.group(1)] = int(spacing.group(1))

    def line_pitch(self, cell_xml: str) -> tuple[int, int]:
        """칸 첫 문단의 (글자 크기, 줄 높이)."""
        run = _RUN_CHAR.search(cell_xml)
        para = re.search(r'<hp:p id="\d+" paraPrIDRef="(\d+)"', cell_xml)
        font = self.char_height.get(run.group(1), 1000) if run else 1000
        percent = self.line_spacing.get(para.group(1), 130) if para else 130
        return font, round(font * percent / 100)


def fit_row_height(xml: str, table_index: int, row: int, texts: dict[int, list[str]], styles: Styles | None = None) -> str:
    """표 `table_index`의 `row`번 행 높이를 `texts`({열: 글 줄 목록})에 맞춘다 — 모자라면 늘리고, `OVERSIZED_ROW`보다 크면 내용에 맞게(`MIN_ROW`까지) 줄인다.
    행의 모든 칸 높이와 표 높이를 맞춘다. `styles`가 없으면 칸 첫 줄 높이 정보(lineseg)로 어림한다.

    세로로 병합된 칸이 걸친 행은 높이를 건드리지 않는다(그 칸의 높이가 여러 행의 합이라 한 행만 바꾸면 어긋난다)."""
    start, end = top_level_tables(xml)[table_index]
    table = xml[start:end]
    source = list(_ROW.finditer(table))[row]
    if any(int(m.group(1)) != 1 for m in _ROW_SPAN.finditer(source.group(0))):
        return xml
    needed, current = 0, 0
    for cell in _TC.finditer(source.group(0)):
        text = cell.group(0)
        col = int(_CELL_ADDR.search(text).group(1))
        width, height = (int(v) for v in _CELL_SZ.search(text).groups())
        current = max(current, height)
        if col not in texts:
            continue
        left, right, top, bottom = (int(v) for v in _CELL_MARGIN.search(text).groups())
        if styles is not None:
            font, pitch = styles.line_pitch(text)
        else:
            seg = _LINESEG.search(text)
            font, pitch = (int(seg.group(1)), int(seg.group(1)) + int(seg.group(2))) if seg else (1000, 1300)
        needed = max(needed, estimate_lines(texts[col], width - left - right, font) * pitch + top + bottom)
    if needed > current:
        target = needed
    elif current > OVERSIZED_ROW:
        target = max(needed, MIN_ROW)
    else:
        return xml
    if target == current:
        return xml

    def resize(match: re.Match) -> str:
        return _CELL_SZ.sub(lambda m: f'<hp:cellSz width="{m.group(1)}" height="{target}"/>', match.group(0))

    new_row = _TC.sub(resize, source.group(0))
    new_table = table[:source.start()] + new_row + table[source.end():]
    new_table = _TABLE_SZ.sub(lambda m: f'{m.group(1)}{int(m.group(2)) + target - current}{m.group(3)}', new_table, count=1)
    return xml[:start] + new_table + xml[end:]


# ── 체크 칸 ─────────────────────────────────────────────────────────────────────
# 양식의 '택 1' 칸(지원 분야 · 전문기술분야 · 지방우대 지역)은 빈 칸이 아니라 글머리표(`<hh:bullet>`, 글머리 ☐)가 붙은 빈 문단이다. 문단 모양의 `checked`
# 속성은 .hwp로 바꾸면 사라지므로(rhwp가 읽지 않는다) 쓰지 않고, 고른 칸의 문단만 글머리가 ☑인 복사본 문단 모양으로 바꾼다.
_PARA_PR = re.compile(r'<hh:paraPr id="(\d+)".*?</hh:paraPr>', re.S)
_BULLET = re.compile(r'<hh:bullet id="(\d+)".*?</hh:bullet>', re.S)
_HEADING_REF = re.compile(r'<hh:heading type="BULLET" idRef="(\d+)"')
_P_PARA_PR = re.compile(r'(<hp:p id="\d+" paraPrIDRef=")(\d+)(")')
CHECKED_BULLET = '☑'


def check_cells(section_xml: str, header_xml: str, cells: list[tuple[int, int, int]]) -> tuple[str, str]:
    """(표, 행, 열) 칸들의 글머리를 ☑로 바꾼 (section xml, header xml)을 돌려준다.

    칸의 문단 모양이 글머리표가 아니면 ValueError — 양식이 바뀐 것이다."""
    para_blocks = {m.group(1): m.group(0) for m in _PARA_PR.finditer(header_xml)}
    bullet_blocks = {m.group(1): m.group(0) for m in _BULLET.finditer(header_xml)}
    next_para = max(int(i) for i in para_blocks) + 1
    next_bullet = max((int(i) for i in bullet_blocks), default=0) + 1
    checked_para: dict[str, str] = {}      # 원래 문단 모양 → ☑ 복사본
    checked_bullet: dict[str, str] = {}    # 원래 글머리 → ☑ 복사본
    new_paras: list[str] = []
    new_bullets: list[str] = []
    for table_index, row, col in cells:
        start, end = top_level_tables(section_xml)[table_index]
        table = section_xml[start:end]
        row_match = list(_ROW.finditer(table))[row]
        for cell in _TC.finditer(row_match.group(0)):
            if int(_CELL_ADDR.search(cell.group(0)).group(1)) != col:
                continue
            source = _P_PARA_PR.search(cell.group(0)).group(2)
            if source not in checked_para:
                heading = _HEADING_REF.search(para_blocks[source])
                if heading is None or heading.group(1) not in bullet_blocks:
                    raise ValueError(f'표 {table_index}의 ({row}, {col}) 칸이 글머리표가 아닙니다')
                bullet = heading.group(1)
                if bullet not in checked_bullet:
                    checked_bullet[bullet] = str(next_bullet)
                    block = bullet_blocks[bullet].replace(f'<hh:bullet id="{bullet}"', f'<hh:bullet id="{next_bullet}"', 1)
                    new_bullets.append(re.sub(r'char="[^"]*"', f'char="{CHECKED_BULLET}"', block, count=1))
                    next_bullet += 1
                checked_para[source] = str(next_para)
                block = para_blocks[source].replace(f'<hh:paraPr id="{source}"', f'<hh:paraPr id="{next_para}"', 1)
                new_paras.append(block.replace(f'idRef="{bullet}"', f'idRef="{checked_bullet[bullet]}"', 1))
                next_para += 1
            new_id = checked_para[source]
            changed_cell = _P_PARA_PR.sub(rf'\g<1>{new_id}\g<3>', cell.group(0), count=1)
            new_row = row_match.group(0)[:cell.start()] + changed_cell + row_match.group(0)[cell.end():]
            table = table[:row_match.start()] + new_row + table[row_match.end():]
            section_xml = section_xml[:start] + table + section_xml[end:]
            break
        else:
            raise ValueError(f'표 {table_index}에 ({row}, {col}) 칸이 없습니다')
    if new_bullets:
        header_xml = header_xml.replace('</hh:bullets>', ''.join(new_bullets) + '</hh:bullets>', 1)
        header_xml = re.sub(r'<hh:bullets itemCnt="(\d+)"', lambda m: f'<hh:bullets itemCnt="{int(m.group(1)) + len(new_bullets)}"', header_xml, count=1)
    if new_paras:
        header_xml = header_xml.replace('</hh:paraProperties>', ''.join(new_paras) + '</hh:paraProperties>', 1)
        header_xml = re.sub(r'<hh:paraProperties itemCnt="(\d+)"', lambda m: f'<hh:paraProperties itemCnt="{int(m.group(1)) + len(new_paras)}"', header_xml, count=1)
    return section_xml, header_xml


def allow_row_page_break(xml: str, table_index: int) -> str:
    """표가 쪽 나눔 없음(`pageBreak="NONE"`)이면 행 단위로 쪽을 넘길 수 있게(`CELL`) 바꾼다.

    쪽 나눔이 없는 표는 행이 늘어 한 쪽보다 길어지면 쪽 아래로 넘쳐 꼬리말(쪽 번호)과 겹친다. 행 단위로 나누면 넘치는 행이 다음 쪽으로 이어진다."""
    start, _ = top_level_tables(xml)[table_index]
    tag_end = xml.index('>', start)
    tag = xml[start:tag_end]
    return xml[:start] + tag.replace('pageBreak="NONE"', 'pageBreak="CELL"', 1) + xml[tag_end:]


# ── 칸의 남는 문단 ──────────────────────────────────────────────────────────────
# 양식 칸에는 예시 상자가 있던 자리라 빈 문단이 여러 개 남아 있다(예: 개요 표 '문제 인식' 칸 5문단). set_cell은 첫 문단에만 쓰므로 나머지가 빈 줄로 남아 칸이 길어진다.
_PARAGRAPH = re.compile(r'<hp:p\b.*?</hp:p>', re.S)
_SUBLIST = re.compile(r'(<hp:subList\b[^>]*>)(.*?)(</hp:subList>)', re.S)


def trim_cell_paragraphs(xml: str, table_index: int, row: int, cols: list[int]) -> str:
    """표 `table_index`의 `row`번 행에서 `cols` 칸의 첫 문단만 남기고 나머지 문단을 지운다(쓸 글은 첫 문단에 쓰고 줄마다 새 문단을 나눠 넣는다)."""
    start, end = top_level_tables(xml)[table_index]
    table = xml[start:end]
    source = list(_ROW.finditer(table))[row]

    def trim(match: re.Match) -> str:
        paragraphs = _PARAGRAPH.findall(match.group(2))
        return match.group(1) + (paragraphs[0] if paragraphs else match.group(2)) + match.group(3)

    def cell(match: re.Match) -> str:
        if int(_CELL_ADDR.search(match.group(0)).group(1)) not in cols:
            return match.group(0)
        return _SUBLIST.sub(trim, match.group(0), count=1)

    new_row = _TC.sub(cell, source.group(0))
    return xml[:start] + table[:source.start()] + new_row + table[source.end():] + xml[end:]


# ── 첫 쪽의 빈 쪽 ───────────────────────────────────────────────────────────────
_PAGE_BREAK_PARA = re.compile(r'(<hp:p id="\d+" paraPrIDRef="\d+" styleIDRef="\d+" pageBreak=")1(")')


def remove_first_page_break(xml: str) -> str:
    """문서에서 처음으로 '쪽 나눔'이 켜진 문단의 쪽 나눔을 끈다.

    양식은 첫 쪽이 작성 목차 쪽이고 그 다음 문단(제목 표)부터 새 쪽이다. 목차 표를 지우면 첫 쪽에는 맨 앞 문단(고지)만 남아 빈 쪽이 되므로,
    제목 표가 앞 쪽에 이어지도록 그 쪽 나눔을 끈다. 쪽 나눔이 있는 문단이 없으면 그대로 돌려준다."""
    return _PAGE_BREAK_PARA.sub(lambda m: f'{m.group(1)}0{m.group(2)}', xml, count=1)


# ── 열 폭 ───────────────────────────────────────────────────────────────────────
_COL_SPAN = re.compile(r'<hp:cellSpan colSpan="(\d+)" rowSpan="\d+"/>')
_COL_CNT = re.compile(r'colCnt="(\d+)"')


def resize_columns(xml: str, table_index: int, widths: list[int]) -> str:
    """표 `table_index`의 열 폭을 `widths`(열 격자마다 HWPUNIT)로 바꾼다 — 칸이 걸친 열의 폭을 더한 값이 그 칸의 폭이 된다.

    양식의 일정 표 '구분' 칸(3238)은 순번용이라 "시제품 개발" 같은 글이 끊기고, 초기창업 사업비 표 금액 칸(5946)은 "28,000,000원"의 '원'이 다음 줄로 넘어간다.
    표 전체 폭은 그대로 두는 것이 좋으므로 `widths`의 합은 원래 폭과 같게 준다. 열 수가 다르면 ValueError."""
    start, end = top_level_tables(xml)[table_index]
    table = xml[start:end]
    columns = int(_COL_CNT.search(table).group(1))
    if len(widths) != columns:
        raise ValueError(f'표 {table_index}은 {columns}열인데 폭을 {len(widths)}개 받았습니다')

    def resize(match: re.Match) -> str:
        cell = match.group(0)
        col = int(_CELL_ADDR.search(cell).group(1))
        span = int(_COL_SPAN.search(cell).group(1))
        width = sum(widths[col:col + span])
        return _CELL_SZ.sub(lambda m: f'<hp:cellSz width="{width}" height="{m.group(2)}"/>', cell, count=1)

    return xml[:start] + _TC.sub(resize, table) + xml[end:]
