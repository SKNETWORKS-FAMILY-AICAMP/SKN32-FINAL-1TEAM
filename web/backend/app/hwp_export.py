"""사업계획서 공식 양식(별첨1)을 실제 .hwp로 채워 내려주는 모듈.

[2026-09-18 신규 → 실제 연동 완료(예비창업패키지·초기창업패키지 둘 다)] plan_document_export.py는
원래 ".hwp는 만들지 않는다 — 서식을 유지한 채 내용만 써넣는 오픈소스 라이브러리가
사실상 없다"고 판단했었다. 팀원이 rhwp(Rust로 만든 HWP5 편집 CLI,
https://github.com/kyunghwan-AITeam/rhwp)를 제안해서 이 판단을 뒤집었다 — 실제
원본 양식 파일 2종 모두로 검증 완료:

  1) 처음 받은 예시 코드는 `rhwp edit fill-fields`(누름틀/폼필드 채우기)를 썼는데,
     실제 원본 양식 파일(예비창업패키지)을 pyhwp로 열어보니 폼필드가 하나도 없고
     전부 "OO기술이 적용된..." 같은 예시 텍스트가 든 순수 표 문서였다 — fill-fields는
     이 문서엔 아예 적용이 안 된다.
  2) rhwp.exe(v0.8.6)를 실제로 받아 --help로 확인해보니 표 좌표 기반 `set_cell`
     (표 칸 기록)과, 여러 step을 한 파일에 원자적으로 적용하는 `run <계획.json>`
     선언적 편집 계획이 있었다 — 이게 이 문서 구조에 정확히 맞는다.
  3) `rhwp export-tables`로 실제 템플릿의 표 좌표(표 번호/행/열, 0부터, export-tables
     격자와 동일)를 전수 추출해서 아래 _PRELIMINARY_STEPS류 함수들의 좌표를 실측했다.
     스모크 테스트(2칸 실제 치환 후 export-tables로 재확인)로 왕복 검증 완료.

[2026-09-22 문제인식_본문 등 4개 본문 채우기 완료] 위에서 "아예 손을 안 대는 쪽을
택했다"고 적었던 4개 섹션 본문을 실제로 붙였다. `rhwp dump`로 실측해보니 각 섹션은
"N. 제목" 표 → 파란 안내문구 표(삭제 대상) → 그 다음에 오는 일반 문단들로 이어지는데,
그 일반 문단들은 이미 " ◦ "/"   - " 같은 글머리 기호가 문단 텍스트 자체에 박혀 있는
빈 칸(사용자가 그 뒤에 이어 쓰라고 만들어둔 자리)이었다 — 4개 템플릿(예비/초기 ×
문제인식/실현가능성/성장전략/팀구성) 전부에서 "안내문구 표가 있는 문단 번호 + 2"가
정확히 첫 " ◦ " 문단이라는 규칙이 성립해서(export-tables로 안내문구 표의 para 값을
읽고 +2), 그 자리(offset=3, "◦ " 뒤)에 `edit insert-text`로 본문 전체를 한 줄로
이어붙인다 — 아래 세부 항목 "- "/"- " 두 줄은 원본이 예시 구조 없이 비워둔 곳이라
채우지 않고 공란으로 남긴다(표 여분 슬롯과 같은 원칙, "지어내지 않는다"). 좌표는 실제
템플릿 파일 2종 모두 `export-markdown`으로 렌더 확인까지 마쳤다(_BODY_SECTIONS_BY_TEMPLATE
참고).

[2026-09-22 발견 — 표 밖 파란 안내문구 하나 추가 삭제] 팀 구성 섹션 제목 표 바로
다음에, 표가 아닌 일반 문단으로 된 개인정보 마스킹 안내문구("※ 성명, 성별, 생년월일,
출신학교, 소재지 등의 개인정보...")가 두 템플릿 모두에 있었다 — 이건 표가 아니라서
기존 `delete-table` 체인이 건드리지 않았다. 원본 양식 자체가 "파란색 안내 문구는
삭제하고 검정 글씨로 작성"이라고 명시하므로(사용자가 준 별첨1 안내 이미지와 동일한
문구), `edit delete-text`로 해당 문단의 글자만 지운다(문단 자체를 지우면 뒤 문단들의
번호가 당겨질 위험이 있어, 문단은 남기고 안을 비우는 쪽을 택했다). 좌표는
_PERSONAL_INFO_NOTICE_BY_TEMPLATE 참고.

[아직 안 된 것 / 알려진 한계]
  - [해결됨] set_cell의 `text`는 줄바꿈을 거부해 여러 줄 값을 " / "로 이어 한 줄로 눌러 담았다. 지금은 첫 줄만 set_cell로 쓰고 나머지 줄은 그 칸의
    문단을 나눠 넣는다(_write_cell_lines — `split-paragraph-in-cell` + `insert-text-in-cell`). 여러 줄이 들어가는 행은 높이도 미리 늘려 둔다(_prepare_tables).
  - [해결됨] 표 안 예시 행 개수(양식마다 다름 — 팀 구성 3~4행, 일정 5행, 사업비 4~5행, 팀구성안/협력기관 3행)를 넘는 데이터는 잘렸다. 지금은 마지막 슬롯
    행을 .hwpx xml에서 통째로 복제해 모두 넣는다(hwpx_rows.clone_rows) — rhwp의 `insert-row`는 칸 병합 · 폭이 풀린 평범한 행을 만들어 쓰지 않는다. 사업비 표는
    첫 두 행에 걸친 비목 칸("재료비" rowSpan=2)을 먼저 나눠(`split-cell`) 둘째 항목도 비목을 쓰고(예전엔 "비목: 산출근거"로 합쳤다), 늘어난 만큼 합계 행이 밀린다.
  - 사업비 집행계획은 원본이 1단계/2단계 두 표로 나뉜다. 예비창업은 사업비 줄의 단계
    (project_budget_items.phase, SB-327)로 표12(1단계) · 표14(2단계)에 나눠 채우고,
    단계가 없는 줄은 1단계 표에 넣는다. 한 단계에 줄이 없으면 그 표는 예시 숫자가
    진짜처럼 보이지 않도록 공란으로 지운다.
  - 계획서 그림(서비스 흐름도 · 서비스 구조도, SB-340)은 맨 뒤에 쪽을 하나 더 만들어 그 쪽에 붙인다(_append_diagram_page) — rhwp의 그림 삽입은
    쪽 좌표에 떠 있는 그림이라 본문 쪽에 붙이면 글자 위에 겹친다. 캡션은 없다(그림 안에 제목이 있다).
  - 템플릿은 칸 안의 파란 예시 상자(안쪽 1x1 표)를 지운 정리본(`*_양식_정리.hwp`, `scripts/clean_hwp_template.py`)을 쓴다 — 원본 양식 파일은 그대로 두고, 쪽 · 문단 · 표 번호는 원본과 같다.
  - 1 ~ 4번 절 본문은 줄마다 " ◦ " 문단으로 쓰고 양식의 빈 "-" · "◦" 뼈대 문단은 지운다(_write_body_sections). 문단을 지우거나 넣으면 뒤 문단 번호가 바뀌어 번호가 큰 절부터, 문단 번호를 쓰는 다른 편집 뒤에 한다.
  - 결과물의 인포그래픽(기준 문서 T-C4)은 그림 쪽 다음의 새 쪽에 한 장으로 붙고(쪽 높이를 넘으면 비율을 지켜 줄임), 첫 장 고지는 첫 쪽 맨 앞 문단(0)에 한 줄로 넣는다.
  - 초기창업패키지(early_general) 표5의 "지원 분야"/"전문기술분야"/"지방우대 지역"은 빈 칸이 아니라 한글의 체크 글머리표(☐)가 붙은 빈 문단이다. 값이 어느 보기인지
    알아볼 수 있을 때만(_match_choice) 그 칸의 글머리를 ☑로 바꾼다(hwpx_rows.check_cells — 문단 모양의 `checked` 속성은 .hwp로 바꾸면 사라져서 쓰지 않고, 글머리가
    ☑인 문단 모양 복사본으로 바꾼다). 보기 문구와 같거나(공백 · 가운뎃점 무시: '정보통신'), 별칭이 값 안에 들어 있고(예: '정보통신업', '특별지원 지역(강원)') 가리키는
    보기가 하나뿐일 때만 체크하고, 아니면(자리표시 '○○·○○', 지어낸 문구, 보기 둘을 가리킴) 아무 칸도 안 건드린다. 지원 분야(제조 · 지식서비스)와 전문기술분야는 입력이
    주업종 한 칸에 섞여 와서 routers/projects.py가 가른다. "해당 없음"은 입력이 없을 때 웹이 채우는 기본 문구라 지방우대 보기로 잇지 않는다.
  - [해결됨] 표가 쪽 밖으로 나가던 것: 양식의 개요 표 등은 파란 예시 상자가 있던 자리라 행이 필요 이상으로 커서(7339 ~ 52239) 표가 한 쪽을 넘쳤다. 지금은 칸에 들어갈
    글의 줄 수를 어림해 행 높이를 내용에 맞게 늘리거나(모자랄 때) 줄이고(5000보다 클 때, 3000까지)(hwpx_rows.fit_row_height), 칸에 남은 빈 문단을 지우고(trim_cell_paragraphs),
    채우는 표는 행 단위로 쪽을 넘길 수 있게 한다(allow_row_page_break). 한 쪽보다 긴 표는 최종 높이 보정 때 글자처럼 취급도 해제해 다음 쪽으로 이어지게 한다.
  - [해결됨] 첫 쪽이 고지 한 줄뿐인 빈 쪽이던 것: 양식의 목차 쪽을 지우면 제목 표 앞의 쪽 나눔 때문에 고지만 남았다. 첫 쪽 나눔을 꺼서 제목 표가 고지 뒤에 이어진다
    (hwpx_rows.remove_first_page_break). 그림 · 인포그래픽 쪽은 글이 없어도 그림이 있다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import zipfile

from app import hwpx_fit, hwpx_rows
from app.plan_document_export import (
    DEFAULT_DISCLAIMER,
    BudgetLineItem,
    PartnerRow,
    PlanDocumentData,
    ScheduleRow,
    TeamRow,
    body_line,
    split_budget_by_phase,
)

logger = logging.getLogger(__name__)

RHWP_BIN = os.environ.get('RHWP_BIN') or 'rhwp'
# Operational limit per CLI command, independent of Agent call timeout/retry policy.
RHWP_TIMEOUT_SECONDS = int(os.environ.get('RHWP_TIMEOUT_SECONDS') or '120')
if RHWP_TIMEOUT_SECONDS <= 0:
    raise ValueError('RHWP_TIMEOUT_SECONDS는 양의 정수여야 합니다')


class HwpConversionTimeout(RuntimeError):
    """A local rhwp command exceeded its configured runtime limit."""


_HWP_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), 'assets', 'hwp_templates')
_HWP_TEMPLATE_FILES = {
    'preliminary': '예비창업패키지_사업계획서_양식_정리.hwp',
    'early_general': '초기창업패키지_사업계획서_양식_정리.hwp',
}


def _one_line(text: str) -> str:
    """set_cell.text는 개행/탭을 거부한다(HWP 표 칸 구조가 깨지므로) — 여러 문단은
    ' / '로 이어붙여 한 줄로 만든다."""
    if not text:
        return ''
    return ' / '.join(line.strip() for line in text.replace('\r', '').split('\n') if line.strip())


def _lines(text: str) -> list[str]:
    """칸 값을 줄 목록으로(빈 줄 · 탭 제거) — 첫 줄은 set_cell로, 나머지는 칸 문단을 나눠 넣는다."""
    return [line.strip() for line in (text or '').replace('\r', '').replace('\t', ' ').split('\n') if line.strip()]


class _Steps(list):
    """run 계획의 단계(set_cell 등) 목록 + 계획만으로는 못 하는 편집 두 가지.

    - add_rows: 입력 줄이 표의 고정 슬롯보다 많을 때 마지막 슬롯 행을 그 아래에 복제한다(hwpx_rows.clone_rows) — run 계획보다 먼저 한다.
    - check_cells: '택 1' 칸은 한글의 체크 글머리표가 붙은 빈 문단이라 글자를 쓰지 않고 문단 모양을 체크 상태로 바꾼다(hwpx_rows.check_cells).
    - split_cells: 사업비 표 첫 두 행에 걸친 비목 칸('재료비' rowSpan=2)을 나눠 모든 행에 비목을 쓸 수 있게 한다 — run 계획보다 먼저 한다.
    - cell_lines: 칸 값이 여러 줄이면 첫 줄만 set_cell로 쓰고(set_cell은 줄바꿈을 거부한다) 나머지는 run 뒤에 그 칸의 문단을 나눠 넣는다."""

    def __init__(self) -> None:
        super().__init__()
        self.add_rows: list[tuple[int, int, int]] = []   # (표, 복제할 기준 행, 늘릴 개수) — 기준 행 아래에 복제한다
        self.split_cells: list[tuple[int, int, int]] = []   # (표, 행, 열) — 세로로 병합된 칸을 먼저 나눈다
        self.check_cells: list[tuple[int, int, int]] = []   # (표, 행, 열) — 체크 글머리표 칸을 체크 상태로 바꾼다
        self.cell_lines: list[tuple[int, int, int, list[str]]] = []   # (표, 행, 열, [첫 줄, 둘째 줄, ...])
        self.cell_texts: dict[tuple[int, int], dict[int, list[str]]] = {}   # (표, 행) → {열: 글 줄 목록} — 행 높이를 맞출 때 쓴다


def _cell_lines_marked(text: str) -> list[str]:
    """칸 값의 줄 — 글머리가 있는 줄이 하나라도 있으면 글머리를 한 가지로 모은다("• 글" → "◦ 글", "–  글" → "- 글"). 글머리 없는 줄은 그대로."""
    lines = _lines(text)
    if all(body_line(line, '')[0] == 'plain' for line in lines):
        return lines
    marked = []
    for line in lines:
        kind, mark, rest = body_line(line, '')
        marked.append(rest if kind in ('plain', 'heading') else f'{mark} {rest}')
    return marked


def _set_cell(steps: _Steps, table: int, row: int, col: int, text: str) -> None:
    lines = _cell_lines_marked(text)
    steps.append({'action': 'set_cell', 'table': table, 'row': row, 'col': col, 'text': lines[0] if lines else ''})
    if lines:
        steps.cell_texts.setdefault((table, row), {})[col] = lines
    if len(lines) > 1:
        steps.cell_lines.append((table, row, col, lines))


def _fill_rows(
    steps: _Steps, table: int, start_row: int, cols: list[int],
    rows: list[tuple[str, ...]], slot_count: int,
) -> None:
    """rows(실제 데이터, 각 항목은 cols 개수만큼의 문자열 튜플)를 표의 고정 슬롯
    (start_row부터 slot_count행)에 채운다. 데이터가 모자라면 남는 슬롯은 공란, 넘치면 마지막 슬롯 행 아래에 행을 끼워 모두 넣는다."""
    if len(rows) > slot_count:
        steps.add_rows.append((table, start_row + slot_count - 1, len(rows) - slot_count))
    for i in range(max(slot_count, len(rows))):
        values = rows[i] if i < len(rows) else tuple('' for _ in cols)
        for col, value in zip(cols, values, strict=True):
            _set_cell(steps, table, start_row + i, col, value)


def _team_status_rows(team: list[TeamRow]) -> list[tuple[str, ...]]:
    return [(str(i + 1), t.직위, t.담당업무, t.보유역량, t.구성상태) for i, t in enumerate(team)]


def _schedule_rows_tuples(rows: list[ScheduleRow]) -> list[tuple[str, ...]]:
    return [(s.구분, s.추진내용, s.추진기간, s.세부내용) for s in rows]


def _partner_rows_tuples(rows: list[PartnerRow]) -> list[tuple[str, ...]]:
    return [(p.순번, p.파트너명, p.보유역량, p.협업방안, p.협력시기) for p in rows]


def _budget_steps(steps: _Steps, table: int, budget: list[BudgetLineItem], total_text: str) -> None:
    """표12/14(사업비 집행계획) 전용 — 첫 두 행에 걸친 비목 칸('재료비' rowSpan=2)은 먼저 나눠 모든 행에 비목을 쓴다(split_cells).
    항목이 양식의 5행(row1 ~ row5)보다 많으면 row5를 복제해 행을 늘리고 합계 행은 그만큼 밀린다."""
    slots = 5
    steps.split_cells.append((table, 1, 0))
    for i in range(max(len(budget), slots)):
        row, item = 1 + i, budget[i] if i < len(budget) else None
        _set_cell(steps, table, row, 0, item.비목 if item else '')
        _set_cell(steps, table, row, 1, item.집행계획 if item else '')
        _set_cell(steps, table, row, 2, item.정부지원사업비 if item else '')
    if len(budget) > slots:
        steps.add_rows.append((table, slots, len(budget) - slots))
    _set_cell(steps, table, max(len(budget), slots) + 1, 2, total_text)


def _normalize_choice(text: str) -> str:
    """보기 문구 비교용 — 공백 · 가운뎃점 · 쉼표 · 슬래시를 없앤다('정보 · 통신', '정보통신', '정보·통신'이 같아진다)."""
    return re.sub(r'[\s·ㆍ・,/]+', '', text or '')


def _match_choice(value: str, options: dict[str, tuple[int, int]], aliases: dict[str, str] | None = None) -> tuple[int, int] | None:
    """값이 가리키는 보기 칸의 좌표 — ① 보기 문구와 같으면(공백 · 가운뎃점 무시) 그 칸 ② 별칭(예: '정보통신업', '비해당')이
    값 안에 들어 있고 가리키는 보기가 하나뿐이면 그 칸. 그 밖의 값(자리표시 '○○'나 지어낸 문구)은 None이다."""
    norm = _normalize_choice(value)
    if not norm:
        return None
    by_norm = {_normalize_choice(name): coords for name, coords in options.items()}
    if norm in by_norm:
        return by_norm[norm]
    hits = {options[option] for alias, option in {**{n: n for n in options}, **(aliases or {})}.items()
            if _normalize_choice(alias) in norm}
    return hits.pop() if len(hits) == 1 else None


def _mark_choice(steps: _Steps, table: int, value: str, options: dict[str, tuple[int, int]],
                 aliases: dict[str, str] | None = None) -> None:
    """표5/표9의 "택1" 칸 — 실제 체크박스 컨트롤이 아니라 옵션 라벨 옆의 빈 칸이라, 값이 어느 보기인지 알아볼 수 있을 때만
    그 칸에 'V'를 쓴다(_match_choice). 값이 플레이스홀더거나 보기에 없으면 아무 칸도 안 건드린다(지어내지 않는다)."""
    coords = _match_choice(value, options, aliases)
    if coords is not None:
        steps.check_cells.append((table, coords[0], coords[1]))


def _budget_steps_full(steps: _Steps, table: int, budget: list[BudgetLineItem], data: PlanDocumentData) -> None:
    """초기창업패키지 표13(사업비 집행계획) 전용 — 비목/집행계획/정부지원사업비/자기부담(현금·현물)/합계 6열. 첫 두 행에 걸친
    비목 칸('재료비' rowSpan=2)은 먼저 나눠 모든 행에 비목을 쓴다(split_cells). 항목이 양식의 4행(row3 ~ row6)보다 많으면 row6을
    복제해 행을 늘리고 합계 행은 그만큼 밀린다."""
    slots, first_row = 4, 3
    steps.split_cells.append((table, first_row, 0))
    for i in range(max(len(budget), slots)):
        row, item = first_row + i, budget[i] if i < len(budget) else None
        _set_cell(steps, table, row, 0, item.비목 if item else '')
        _set_cell(steps, table, row, 1, item.집행계획 if item else '')
        _set_cell(steps, table, row, 2, item.정부지원사업비 if item else '')
        _set_cell(steps, table, row, 3, item.자기부담_현금 if item else '')
        _set_cell(steps, table, row, 4, item.자기부담_현물 if item else '')
        _set_cell(steps, table, row, 5, item.총사업비 if item else '')
    if len(budget) > slots:
        steps.add_rows.append((table, first_row + slots - 1, len(budget) - slots))
    total_row = first_row + max(len(budget), slots)
    _set_cell(steps, table, total_row, 2, data.정부지원사업비)
    _set_cell(steps, table, total_row, 3, data.자기부담_현금)
    _set_cell(steps, table, total_row, 4, data.자기부담_현물)
    _set_cell(steps, table, total_row, 5, data.총사업비)


_SUPPORT_FIELD_OPTIONS = {'제조': (2, 3), '지식서비스': (2, 8)}
_TECH_FIELD_OPTIONS = {
    '기계·소재': (3, 3), '전기·전자': (3, 8), '정보·통신': (3, 14),
    '화공·섬유': (4, 3), '바이오·의료·생명': (4, 8), '에너지·자원': (4, 14),
    '공예·디자인': (5, 3),
}
_REGIONAL_PRIORITY_OPTIONS = {
    '특별지원 지역': (9, 3), '우대지원 지역': (9, 7), '일반지역': (9, 11), '지방우대 비해당 지역': (9, 15),
}
# 지방우대 칸의 입력은 "해당 시 지역명"까지 담는 자유 글이라 보기 이름이 그 안에 들어 있으면 그 칸으로 본다.
# "해당 없음"은 입력이 없을 때 웹이 채우는 기본 문구와 같아서 사용자가 고른 것인지 알 수 없으므로 보기로 잇지 않는다.
_REGIONAL_PRIORITY_ALIASES = {
    '특별지원': '특별지원 지역', '우대지원': '우대지원 지역', '일반지역': '일반지역', '비해당': '지방우대 비해당 지역',
}
# 전문기술분야 칸은 '정보통신업'처럼 업종 이름이 붙은 글도 같은 분야로 본다.
_TECH_FIELD_ALIASES = {
    '기계소재': '기계·소재', '전기전자': '전기·전자', '정보통신': '정보·통신', '화공섬유': '화공·섬유',
    '바이오': '바이오·의료·생명', '의료생명': '바이오·의료·생명', '에너지자원': '에너지·자원', '공예디자인': '공예·디자인',
}


def _early_general_steps(data: PlanDocumentData) -> _Steps:
    """rhwp export-tables로 실측한 초기창업패키지(일반형) 원본 양식(표 21개) 좌표."""
    steps = _Steps()

    # 표4: 일반현황(기업명/개업연월일/사업자구분/대표자유형/사업자등록번호/사업자소재지)
    _set_cell(steps, 4, 0, 1, data.기업명)
    _set_cell(steps, 4, 0, 3, data.개업연월일)
    _set_cell(steps, 4, 1, 1, data.사업자_구분)
    _set_cell(steps, 4, 1, 3, data.대표자_유형)
    _set_cell(steps, 4, 2, 1, data.사업자등록번호)
    _set_cell(steps, 4, 2, 3, data.사업자_소재지)

    # 표5: 창업아이템명/산출물/지원분야·전문기술분야(택1)/총사업비 구성계획/지방우대지역
    #      + 팀 구성 현황(20열짜리 넓은 표 — 아래 좌표는 export-tables 실측값 그대로)
    _set_cell(steps, 5, 0, 3, data.창업아이템명)
    _set_cell(steps, 5, 1, 3, data.산출물)
    _mark_choice(steps, 5, data.지원분야, _SUPPORT_FIELD_OPTIONS)
    _mark_choice(steps, 5, data.전문기술분야, _TECH_FIELD_OPTIONS, _TECH_FIELD_ALIASES)
    _set_cell(steps, 5, 8, 3, data.정부지원사업비)
    _set_cell(steps, 5, 8, 10, data.자기부담_현금)
    _set_cell(steps, 5, 8, 13, data.자기부담_현물)
    _set_cell(steps, 5, 8, 18, data.총사업비)
    _mark_choice(steps, 5, data.지방우대_지역_해당여부, _REGIONAL_PRIORITY_OPTIONS, _REGIONAL_PRIORITY_ALIASES)
    _fill_rows(steps, 5, 12, [0, 1, 2, 6, 19], _team_status_rows(data.팀구성현황), slot_count=4)

    # 표6: 창업 아이템 개요(요약)
    _set_cell(steps, 6, 0, 1, data.아이템_명칭)
    _set_cell(steps, 6, 0, 4, data.아이템_범주)
    _set_cell(steps, 6, 1, 1, data.아이템_개요)
    _set_cell(steps, 6, 2, 1, data.요약_문제인식)
    _set_cell(steps, 6, 3, 1, data.요약_실현가능성)
    _set_cell(steps, 6, 4, 1, data.요약_성장전략)
    _set_cell(steps, 6, 5, 1, data.요약_팀구성)

    # 표7/9/14/17 r0c1: "N. 제목" 다음에 오는 칸 — 본문을 넣을 자리가 아니다(모듈
    # docstring "아직 안 된 것" 참고). set_cell을 안 부른다.
    # 표11: 실현가능성 일정
    _fill_rows(steps, 11, 1, [0, 1, 2, 3], _schedule_rows_tuples(data.실현가능성_일정), slot_count=5)
    # 표13: 사업비 집행계획(정부지원사업비/자기부담 현금·현물/합계 6열)
    _budget_steps_full(steps, 13, data.사업비_집행계획, data)

    # 표16: 성장전략 일정
    _fill_rows(steps, 16, 1, [0, 1, 2, 3], _schedule_rows_tuples(data.성장전략_일정), slot_count=5)
    # 표19: 팀 구성(안)
    _fill_rows(steps, 19, 1, [0, 1, 2, 3, 4], _team_status_rows(data.팀구성_안), slot_count=3)
    # 표20: 협력기관
    _fill_rows(steps, 20, 1, [0, 1, 2, 3, 4], _partner_rows_tuples(data.협력기관), slot_count=3)

    return steps


def _preliminary_steps(data: PlanDocumentData) -> _Steps:
    """rhwp export-tables로 실측한 예비창업패키지 원본 양식(표 22개) 좌표 — 표 번호는
    export-tables/set_cell이 공유하는 문서 순서 그대로(0부터)."""
    steps = _Steps()

    # 표4: 일반현황(예비창업자 전용 — 기업명/사업자등록번호 등은 없음)
    _set_cell(steps, 4, 0, 3, data.창업아이템명)
    _set_cell(steps, 4, 1, 3, data.산출물)
    _set_cell(steps, 4, 2, 3, data.직업)
    _set_cell(steps, 4, 2, 6, data.기업예정명)
    _fill_rows(steps, 4, 5, [0, 1, 2, 4, 7], _team_status_rows(data.팀구성현황), slot_count=4)

    # 표5: 창업 아이템 개요(요약)
    _set_cell(steps, 5, 0, 1, data.아이템_명칭)
    _set_cell(steps, 5, 0, 4, data.아이템_범주)
    _set_cell(steps, 5, 1, 1, data.아이템_개요)
    _set_cell(steps, 5, 2, 1, data.요약_문제인식)
    _set_cell(steps, 5, 3, 1, data.요약_실현가능성)
    _set_cell(steps, 5, 4, 1, data.요약_성장전략)
    _set_cell(steps, 5, 5, 1, data.요약_팀구성)

    # 표6/8/15/18 r0c1: "N. 제목" 다음에 오는 칸 — 본문을 넣을 자리가 아니다(모듈
    # docstring "아직 안 된 것" 참고). set_cell을 안 부른다.
    # 표10: 실현가능성 일정
    _fill_rows(steps, 10, 1, [0, 1, 2, 3], _schedule_rows_tuples(data.실현가능성_일정), slot_count=5)
    # 표12/14: 사업비 집행계획 1단계 · 2단계(단계 없는 행은 1단계 — 모듈 docstring 참고)
    first, second = split_budget_by_phase(data.사업비_집행계획)
    _budget_steps(steps, 12, first, data.정부지원사업비_1단계)
    _budget_steps(steps, 14, second, data.정부지원사업비_2단계)

    # 표17: 성장전략 일정
    _fill_rows(steps, 17, 1, [0, 1, 2, 3], _schedule_rows_tuples(data.성장전략_일정), slot_count=5)
    # 표20: 팀 구성(안)
    _fill_rows(steps, 20, 1, [0, 1, 2, 3, 4], _team_status_rows(data.팀구성_안), slot_count=3)
    # 표21: 협력기관
    _fill_rows(steps, 21, 1, [0, 1, 2, 3, 4], _partner_rows_tuples(data.협력기관), slot_count=3)

    return steps


_STEPS_BY_TEMPLATE = {
    'preliminary': _preliminary_steps,
    'early_general': _early_general_steps,
}

# [2026-09-22] 원본 양식엔 "작성 목차(안)" 페이지와 "※ ..." 파란색 안내 문구 표가
# 실제 제출용 내용과 섞여 있는데, 원본 자체가 "신청 시 목차 페이지는 삭제하고 제출"
# 이라고 명시한다(표0/표3 등) — 사용자가 매번 수동으로 지우게 두지 않고 여기서 자동
# 삭제한다. export-tables 좌표로 실측(표 안 지우는 것: 일반현황/아이템개요/일정/
# 사업비/팀구성/협력기관처럼 실제 데이터가 들어가는 표와, "N. 제목" 섹션 헤더 표).
# **내림차순 필수** — delete-table은 지울 때마다 뒤 표들의 번호가 하나씩 당겨지므로,
# 낮은 번호부터 지우면 그다음 삭제 대상 번호가 틀어진다.
_DELETE_TABLES_BY_TEMPLATE = {
    'preliminary': [19, 16, 13, 11, 9, 7, 3, 1, 0],
    'early_general': [18, 15, 12, 10, 8, 3, 1, 0],
}

# 1~4번 섹션 본문 — `rhwp dump`로 실측한 (구역=0 고정) 문단 번호. (필드, 첫 불릿 문단, 지울 뼈대 문단 범위(처음, 끝)).
# 첫 불릿 문단은 " ◦ "(길이 3)로 시작하는 빈 칸이라 offset=3(◦ 뒤)에 첫 줄을 이어 붙이고, 둘째 줄부터는 그 뒤에 " ◦ " 문단을 새로 넣는다.
# 지울 범위는 그 뒤에 이어진 "   - " · " ◦ " · 빈 문단(양식의 작성 요령 뼈대)이다 — 지우지 않으면 빈 글머리가 그대로 남는다.
# (범위는 표 · 쪽 나눔 같은 컨트롤이 있는 문단이나 표 제목 문단 직전까지다.)
_BODY_OFFSET = 3
_BODY_BULLET = ' ◦ '
_BODY_SECTIONS_BY_TEMPLATE: dict[str, list[tuple[str, int, tuple[int, int]]]] = {
    'preliminary': [
        ('문제인식_본문', 11, (12, 22)),
        ('실현가능성_본문', 26, (27, 35)),
        ('성장전략_본문', 49, (50, 68)),
        ('팀구성_본문', 75, (76, 84)),
    ],
    'early_general': [
        ('문제인식_본문', 13, (14, 24)),
        ('실현가능성_본문', 28, (29, 33)),
        ('성장전략_본문', 44, (45, 63)),
        ('팀구성_본문', 70, (71, 79)),
    ],
}

# [SB-339] 표 항목의 서술 문장은 양식에 따로 칸이 없어, 그 표가 속한 절의 본문 뒤에 이어 붙인다 — docx는 표 아래 문단으로 쓴다.
_BODY_NARRATIVES: dict[str, tuple[str, ...]] = {
    '실현가능성_본문': ('실현가능성_일정_서술', '사업비_서술', '사업비_2단계_서술'),
    '성장전략_본문': ('성장전략_일정_서술',),
}


_PHASE_LABELS = {'사업비_서술': '1단계', '사업비_2단계_서술': '2단계'}


def _body_lines(data: PlanDocumentData, field_name: str) -> list[str]:
    """절 본문 + 그 절의 표 서술을 줄(문단) 목록으로. 본문이 안내 문구뿐이어도 서술이 있으면 서술은 붙는다."""
    parts = [getattr(data, field_name, '')]
    for extra in _BODY_NARRATIVES.get(field_name, ()):
        text = getattr(data, extra, '')
        # 예비창업자는 사업비 서술이 1단계 · 2단계 두 개라 어느 단계 서술인지 머리말을 단다
        if text and extra in _PHASE_LABELS and getattr(data, '사업비_2단계_서술', ''):
            text = f'[{_PHASE_LABELS[extra]}] {text}'
        parts.append(text)
    lines = [line.strip() for part in parts for line in (part or '').replace('\r', '').split('\n')]
    return [line for line in lines if line]


def _body_text(data: PlanDocumentData, field_name: str) -> str:
    """절 본문 + 표 서술을 ' / '로 이은 한 줄(요약 · 비교용). hwp 문서에는 줄마다 문단으로 쓴다(_write_body_sections)."""
    return ' / '.join(_body_lines(data, field_name))


_SUBHEADING_RE = re.compile(r'\[[^\[\]]+\]')


def _is_subheading(line: str) -> bool:
    """"[대표자 보유 역량]"처럼 대괄호 하나로 된 소제목 줄 — 본문 줄과 구분되게 " ◦ " 없이 쓴다(웹 프론트 확인 2026-10-13)."""
    return _SUBHEADING_RE.fullmatch(line.strip()) is not None


def _body_paragraph(line: str) -> str:
    """본문 줄 → hwp 문단 글. 줄에 붙어 온 글머리("◦ " · "• " · "- " · "* " 등)를 떼고 한 번만 단다(plan_document_export.body_line) —
    예전에는 " ◦ "를 그 위에 또 붙여 " ◦ ◦ …" · " ◦ - …"가 됐다. 소제목은 그대로, 본문 줄은 " ◦ 글", 하위 줄은 양식 뼈대와 같은 "   - 글"
    ("·"이면 "   · 글"), 번호 줄은 " ① 글"."""
    kind, mark, text = body_line(line)
    if kind == 'heading':
        return text
    if kind == 'sub':
        return f'   {mark} {text}'
    return f' {mark} {text}'


def _write_body_sections(current_output: str, template: str, data: PlanDocumentData, new_tmp) -> str:
    """1 ~ 4번 절 본문을 줄마다 문단으로 쓰고 양식의 빈 작성 요령 뼈대를 지운다. 새 파일 경로를 돌려준다.

    문단을 지우거나 넣으면 뒤 문단 번호가 바뀌므로 번호가 큰 절부터 처리한다. 절마다 ① 뼈대 문단을 지우고(큰 번호부터)
    ② 둘째 줄부터 첫 불릿 문단 뒤에 " ◦ " 문단으로 넣고(마지막 줄부터 넣어 순서가 맞게) ③ 첫 줄을 첫 불릿 문단에 쓴다.
    insert-paragraph는 지정한 문단 앞에 빈 문단을 넣고 앞 문단의 서식을 따르므로, 첫 불릿 문단 바로 뒤는 번호 + 1이다."""
    def edit(*args: str) -> None:
        nonlocal current_output
        next_output = new_tmp()
        _run_rhwp(['edit', args[0], current_output, *args[1:], '-o', next_output])
        current_output = next_output

    for field_name, first, (skeleton_from, skeleton_to) in reversed(_BODY_SECTIONS_BY_TEMPLATE.get(template, [])):
        for para in range(skeleton_to, skeleton_from - 1, -1):
            edit('delete-paragraph', '--section', '0', '--para', str(para))
        lines = [_body_paragraph(_one_line(line)) for line in _body_lines(data, field_name)]
        for line in reversed(lines[1:]):
            edit('insert-paragraph', '--section', '0', '--para', str(first + 1))
            edit('insert-text', '--section', '0', '--para', str(first + 1), '--offset', '0', '--text', line)
        if lines and not lines[0].startswith(_BODY_BULLET):
            # 첫 줄이 소제목 · 하위 줄 · 번호 줄이면 첫 불릿 문단의 " ◦ "를 지우고 그 줄을 통째로 쓴다
            edit('delete-text', '--section', '0', '--para', str(first), '--offset', '0', '--count', str(len(_BODY_BULLET)))
            edit('insert-text', '--section', '0', '--para', str(first), '--offset', '0', '--text', lines[0])
        elif lines:
            edit('insert-text', '--section', '0', '--para', str(first), '--offset', str(_BODY_OFFSET), '--text', lines[0][len(_BODY_BULLET):])
    return current_output


# 팀 구성 제목 표 다음에 오는, 표가 아닌 개인정보 마스킹 안내문구(파란 글씨) 문단 —
# (구역=0 고정 문단 번호, 글자 수). 모듈 docstring "표 밖 파란 안내문구" 참고.
_PERSONAL_INFO_NOTICE_BY_TEMPLATE: dict[str, tuple[int, int]] = {
    'preliminary': (72, 107),
    'early_general': (67, 107),
}


# 문단 모양(hwpx_rows.shape_paragraphs) — (정렬, 왼쪽 여백 em, 내어쓰기 em). em은 그 문단 글자 크기 배수다.
# 글머리 폭은 rhwp로 그린 쪽에서 잰 값이다(본문 휴먼명조 14pt: " ◦ " · " ① " 약 1.9글자, "   - " 약 2.75글자 / 칸 맑은 고딕 10pt: "◦ " 약 1.5글자, "- " 약 0.95글자).
# 본문은 양쪽 정렬이라 줄마다 빈칸이 조금씩 늘어 글 첫 글자가 한두 점 어긋날 수 있다. 본문 정렬은 양식 그대로 두고, 칸 목록은 왼쪽 정렬로 바꾼다.
_BODY_SHAPES: dict[str, hwpx_rows.Shape] = {'heading': (None, 0, 0), 'item': (None, 0, 1.9), 'sub': (None, 0, 2.75)}
_CELL_SHAPES: dict[str, hwpx_rows.Shape] = {'plain': ('LEFT', 0, 0), 'heading': ('LEFT', 0, 0), 'item': ('LEFT', 0, 1.5), 'sub': ('LEFT', 1.5, 0.95)}


def _body_paragraph_shapes(template: str, data: PlanDocumentData) -> dict[int, tuple[str, hwpx_rows.Shape]]:
    """_write_body_sections가 쓴 본문 문단의 {최종 문단 번호: (글, 모양)}. 절마다 뼈대 문단을 지우고 줄 수만큼 문단을 넣었으므로
    앞 절에서 늘거나 준 문단 수만큼 뒤 절의 번호가 밀린다(본문이 비면 양식의 첫 불릿 문단 하나가 남는다)."""
    shapes: dict[int, tuple[str, hwpx_rows.Shape]] = {}
    shift = 0
    for field_name, first, (skeleton_from, skeleton_to) in _BODY_SECTIONS_BY_TEMPLATE.get(template, []):
        texts = [_body_paragraph(_one_line(line)) for line in _body_lines(data, field_name)]
        for k, text in enumerate(texts):
            shapes[first + shift + k] = (text, _BODY_SHAPES[body_line(text)[0]])
        shift += max(len(texts), 1) - 1 - (skeleton_to - skeleton_from + 1)
    return shapes


def _cell_paragraph_shapes(template: str, steps: _Steps) -> dict[tuple[int, int, int], list[hwpx_rows.Shape]]:
    """글머리 줄이 있는 칸의 {(최종 표 번호, 행, 열): [칸 문단마다 모양]}. 목차 · 안내 표를 지웠으므로 그보다 뒤 표는 지운 수만큼 번호가 당겨진다."""
    deleted = _DELETE_TABLES_BY_TEMPLATE.get(template, [])
    cells: dict[tuple[int, int, int], list[hwpx_rows.Shape]] = {}
    for (table, row), columns in steps.cell_texts.items():
        for col, lines in columns.items():
            kinds = [body_line(line, '')[0] for line in lines]
            if all(kind == 'plain' for kind in kinds):
                continue
            cells[(table - sum(1 for d in deleted if d < table), row, col)] = [_CELL_SHAPES[kind] for kind in kinds]
    return cells


def _shape_paragraphs(current_output: str, template: str, data: PlanDocumentData, steps: _Steps, new_tmp) -> str:
    """본문 글머리 줄 · 칸 목록의 문단 모양을 맞춘다 — 넘어간 줄이 글 첫 글자에 맞게 내어쓰기를 정하고, 칸 목록은 왼쪽 정렬로(hwpx_rows.shape_paragraphs).
    rhwp에는 문단 모양을 바꾸는 편집이 없어 .hwpx로 내보내 고친 뒤 다시 .hwp로 바꾼다. 바꿀 것이 없으면 그대로 돌려준다."""
    paragraphs = _body_paragraph_shapes(template, data)
    cells = _cell_paragraph_shapes(template, steps)
    if not paragraphs and not cells:
        return current_output
    hwpx_path = new_tmp('.hwpx')
    _run_rhwp(['export-hwpx', current_output, hwpx_path])
    with zipfile.ZipFile(hwpx_path) as z:
        names = z.namelist()
        data_files = {name: z.read(name) for name in names}
    section, header = hwpx_rows.shape_paragraphs(data_files['Contents/section0.xml'].decode('utf-8'),
                                                 data_files['Contents/header.xml'].decode('utf-8'), paragraphs, cells)
    data_files['Contents/section0.xml'] = section.encode('utf-8')
    data_files['Contents/header.xml'] = header.encode('utf-8')
    return _convert_hwpx(data_files, names, new_tmp)


def _convert_hwpx(data_files: dict[str, bytes], names: list[str], new_tmp) -> str:
    """고친 .hwpx 내용을 파일로 쓰고 .hwp로 바꿔 그 경로를 돌려준다."""
    edited_path, converted = new_tmp('.hwpx'), new_tmp()
    with zipfile.ZipFile(edited_path, 'w') as z:
        for name in names:  # mimetype을 맨 앞에 두고 압축하지 않는다(HWPX 규칙)
            stored = name == 'mimetype'
            z.writestr(zipfile.ZipInfo(name) if stored else name, data_files[name],
                       compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
    try:
        _run_rhwp(['convert', edited_path, converted, '--verify-pages'])
    except RuntimeError:
        # 쪽 수 검증은 변환 전후 조판이 다르면(표가 아주 길어 쪽이 많이 늘 때) 실패한다 — 문서 내려받기를 막지 않도록 검증 없이 변환한다
        _run_rhwp(['convert', edited_path, converted])
    return converted


def _run_rhwp(args: list[str]) -> str:
    """rhwp CLI를 실행하고 실패를 일관된 예외로 바꾼다 — render_plan_hwp의 run/edit
    delete-table 호출이 공유한다. 표준 출력(--json 응답 등)을 돌려준다."""
    try:
        result = subprocess.run(
            [RHWP_BIN, *args], capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=RHWP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise HwpConversionTimeout(
            f'HWP 변환 명령이 제한 시간({RHWP_TIMEOUT_SECONDS}초)을 초과했습니다. 잠시 후 다시 시도해 주세요.'
        ) from exc
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"rhwp 실행 파일을 찾을 수 없습니다('{RHWP_BIN}') — RHWP_BIN 환경변수로 경로를 지정하세요"
        ) from exc
    if result.returncode != 0:
        error_msg = (result.stderr or result.stdout or '알 수 없는 rhwp 오류').strip()
        raise RuntimeError(f'rhwp 처리 중 오류 발생: {error_msg}')
    return result.stdout


# [SB-340] 그림(서비스 흐름도 · 서비스 구조도)은 hwp 맨 뒤에 쪽을 하나 더 만들어 그 쪽에 붙인다 — rhwp의 그림 삽입은 쪽 좌표에 떠 있는
# 그림이라, 본문 쪽에 붙이면 글자 위에 겹친다. 길이 단위는 HWPUNIT(1/7200 inch, A4 세로 59528 × 84188).
_A4_WIDTH = 59528
_PICTURE_WIDTH = 46000                           # 본문 폭(48188)보다 조금 좁게
_PICTURE_X = (_A4_WIDTH - _PICTURE_WIDTH) // 2   # 가운데
_PICTURE_TOP = 8504                              # 위 여백(3cm)
_PICTURE_GAP = 2000
_A4_HEIGHT = 84186
_INFOGRAPHIC_MAX_HEIGHT = _A4_HEIGHT - 2 * _PICTURE_TOP - hwpx_fit.ATTACHMENT_SHIFT   # 별첨 문구가 들어가도록 그림을 내리는 만큼도 뺀다 — 인포그래픽은 한 쪽에 한 장 — 세로가 쪽 높이를 넘으면 비율을 지켜 줄인다


def _append_picture_pages(current_output: str, groups: list, new_tmp) -> str:
    """hwp 맨 끝에 묶음마다 새 쪽을 하나씩 만들고, 묶음의 그림을 그 쪽에 위에서 아래로 붙인다. 새 파일 경로를 돌려준다.

    groups: [(그림 목록, 그림 하나의 세로 상한(HWPUNIT) 또는 None)]. 상한을 넘는 그림은 비율을 지켜 가로도 줄이고 가운데에 둔다(인포그래픽).
    쪽을 먼저 모두 나눈 뒤 그림을 붙인다 — rhwp의 그림은 맨 끝 문단에 매달려 있어서, 그림을 붙인 뒤 다시 쪽을 나누면 그림이 문단과 함께 뒤 쪽으로 딸려 간다."""
    info = json.loads(_run_rhwp(['explain', current_output, '--json']))
    para = info['paragraphCount'] - 1
    for _group in groups:
        paged = new_tmp()
        _run_rhwp(['edit', 'insert-page-break', current_output, '--section', '0', '--para', str(para),
                   '--offset', '0', '-o', paged])
        current_output, para = paged, para + 1
    first_page = json.loads(_run_rhwp(['explain', current_output, '--json']))['pageCount'] - len(groups)
    for offset, (pictures, max_height) in enumerate(groups):
        y = _PICTURE_TOP
        for picture in pictures:
            width_px, height_px = picture.size_px
            width = _PICTURE_WIDTH
            height = round(width * height_px / width_px)
            if max_height is not None and height > max_height:
                height = max_height
                width = round(max_height * width_px / height_px)
            image_fd, image_path = tempfile.mkstemp(suffix='.png')
            try:
                with os.fdopen(image_fd, 'wb') as f:
                    f.write(picture.png)
                next_output = new_tmp()
                _run_rhwp(['edit', 'insert-image', current_output, '--image', image_path, '--page', str(first_page + offset),
                           '--x', str((_A4_WIDTH - width) // 2), '--y', str(y), '--width', str(width), '--height', str(height),
                           '-o', next_output])
            finally:
                os.remove(image_path)
            current_output, y = next_output, y + height + _PICTURE_GAP
    return current_output


# 열 폭 조정(HWPUNIT, 표 전체 폭은 그대로) — 일정 표 '구분' 칸을 넓히고(3238 → 7000, "시제품 개발"이 한두 글자씩 끊기던 것) 초기창업 사업비 표 금액 칸을 넓힌다
# (5946 → 7300, "28,000,000원"의 '원'이 다음 줄로 넘어가던 것). 표 번호는 양식 정리본 기준이다.
_SCHEDULE_COLUMNS = [7000, 11646, 11795, 17521]
_COLUMN_WIDTHS_BY_TEMPLATE: dict[str, dict[int, list[int]]] = {
    'preliminary': {10: _SCHEDULE_COLUMNS, 17: _SCHEDULE_COLUMNS},
    'early_general': {11: _SCHEDULE_COLUMNS, 16: _SCHEDULE_COLUMNS, 13: [6509, 12215, 7300, 7300, 7300, 7300]},
}


def _prepare_tables(current_output: str, steps: _Steps, new_tmp, template: str = '') -> str:
    """표 레이아웃을 입력에 맞춘다 — ① 입력 줄이 양식의 고정 행보다 많은 표는 기준 행을 복제해 행을 늘리고(steps.add_rows)
    ② 칸에 들어갈 글(여러 줄 · 줄바꿈)에 맞게 행 높이를 늘린다(steps.cell_texts). 바꿀 것이 없으면 그대로 돌려주고, 새 파일 경로를 돌려준다.

    rhwp의 `edit insert-row`는 열 격자대로 칸이 나뉜 평범한 행을 만들어 칸 병합 · 폭 · 테두리가 어긋나므로(팀 구성 표 등) 쓰지 않고,
    .hwpx로 내보내 xml에서 기준 행을 통째로 복제한 뒤 다시 .hwp로 바꾼다(hwpx_rows). 한 번의 내보내기 · 변환으로 모든 표를 처리한다."""
    for table, row, col in steps.split_cells:
        next_output = new_tmp()
        _run_rhwp(['edit', 'split-cell', current_output, '--table', str(table), '--row', str(row), '--col', str(col), '-o', next_output])
        current_output = next_output
    if not steps.add_rows and not steps.cell_texts and not steps.check_cells:
        return current_output
    hwpx_path = new_tmp('.hwpx')
    _run_rhwp(['export-hwpx', current_output, hwpx_path])
    with zipfile.ZipFile(hwpx_path) as z:
        names = z.namelist()
        data = {name: z.read(name) for name in names}
    xml = data['Contents/section0.xml'].decode('utf-8')
    for table, widths in _COLUMN_WIDTHS_BY_TEMPLATE.get(template, {}).items():
        xml = hwpx_rows.resize_columns(xml, table, widths)
    for table, row, count in steps.add_rows:
        xml = hwpx_rows.clone_rows(xml, table, row, count)
    styles = hwpx_rows.Styles(data['Contents/header.xml'].decode('utf-8'))
    for (table, row), texts in steps.cell_texts.items():
        xml = hwpx_rows.trim_cell_paragraphs(xml, table, row, list(texts))
        xml = hwpx_rows.fit_row_height(xml, table, row, texts, styles)
    # 채우는 표는 행 단위로 쪽을 넘길 수 있게 한다 — 쪽 나눔 없는 표는 행이 늘면 쪽 아래로 넘쳐 쪽 번호와 겹친다
    for table in sorted({table for table, _ in steps.cell_texts} | {table for table, _, _ in steps.add_rows}):
        xml = hwpx_rows.allow_row_page_break(xml, table)
    xml = hwpx_rows.remove_first_page_break(xml)  # 목차 쪽을 지운 뒤 첫 쪽에 고지만 남는 빈 쪽을 없앤다
    if steps.check_cells:
        xml, header = hwpx_rows.check_cells(xml, data['Contents/header.xml'].decode('utf-8'), steps.check_cells)
        data['Contents/header.xml'] = header.encode('utf-8')
    data['Contents/section0.xml'] = xml.encode('utf-8')
    return _convert_hwpx(data, names, new_tmp)


def _write_cell_lines(current_output: str, cell_lines: list[tuple[int, int, int, list[str]]], new_tmp) -> str:
    """칸의 둘째 줄부터를 그 칸의 새 문단으로 넣는다(첫 줄은 이미 set_cell로 들어가 있다). 새 파일 경로를 돌려준다.

    줄마다: 앞 문단 끝에서 문단을 나누고 새 문단에 글을 넣는다(offset은 앞 줄의 글자 수 — 첫 줄은 set_cell이 쓴 값 그대로)."""
    for table, row, col, lines in cell_lines:
        coords = ['--table', str(table), '--row', str(row), '--col', str(col)]
        for k, line in enumerate(lines[1:]):
            split_out = new_tmp()
            _run_rhwp(['edit', 'split-paragraph-in-cell', current_output, *coords, '--cell-para', str(k),
                       '--offset', str(len(lines[k])), '-o', split_out])
            next_output = new_tmp()
            _run_rhwp(['edit', 'insert-text-in-cell', split_out, *coords, '--cell-para', str(k + 1), '--offset', '0',
                       '--text', line, '-o', next_output])
            current_output = next_output
    return current_output


def _append_diagram_page(current_output: str, pictures: list, new_tmp, max_height: int | None = None) -> str:
    """새 마지막 쪽 하나에 그림을 붙인다(_append_picture_pages의 묶음 하나짜리)."""
    return _append_picture_pages(current_output, [(pictures, max_height)], new_tmp)


def _fit_layout(current_output: str, labels: list[str], new_tmp) -> str:
    """서체 · 글자 크기를 통일하고 개요 표가 한 쪽 안에 들어가게 줄이며 별첨 문구를 넣는다(hwpx_fit). .hwpx로 내보내 고친 뒤 다시 .hwp로 바꾼다.
    그림이 붙은 뒤(맨 끝)에 한다 — 그림 쪽 맨 위 문구가 그림 문단에 매달리기 때문이다. 실패해도 문서 내려받기를 막지 않도록 고치기 전 파일을 그대로 쓴다."""
    hwpx_path = new_tmp('.hwpx')
    _run_rhwp(['export-hwpx', current_output, hwpx_path])
    with zipfile.ZipFile(hwpx_path) as z:
        names = z.namelist()
        data_files = {name: z.read(name) for name in names}
    try:
        section, header = hwpx_fit.fit_document(data_files['Contents/section0.xml'].decode('utf-8'),
                                                data_files['Contents/header.xml'].decode('utf-8'), labels)
    except (ValueError, KeyError, AttributeError, IndexError, StopIteration):
        logger.exception('hwp 한 쪽 맞춤에 실패해 고치기 전 파일을 그대로 쓴다')
        return current_output
    data_files['Contents/section0.xml'] = section.encode('utf-8')
    data_files['Contents/header.xml'] = header.encode('utf-8')
    return _convert_hwpx(data_files, names, new_tmp)


def render_plan_hwp(data: PlanDocumentData, template: str) -> bytes:
    """실제 .hwp 바이트를 만들어 돌려준다. 템플릿 파일이 없거나 이 template 유형용
    좌표 매핑이 아직 없으면 FileNotFoundError를, rhwp가 실패하면 RuntimeError를 낸다
    — 호출부(routers/projects.py)가 이 둘을 HTTPException(500)으로 변환한다."""
    template_filename = _HWP_TEMPLATE_FILES.get(template)
    steps_fn = _STEPS_BY_TEMPLATE.get(template)
    if template_filename is None or steps_fn is None:
        raise FileNotFoundError(f"'{template}' 유형의 hwp 템플릿이 아직 등록되지 않았습니다")
    template_path = os.path.join(_HWP_TEMPLATE_DIR, template_filename)
    if not os.path.exists(template_path):
        raise FileNotFoundError(f'hwp 템플릿 파일을 찾을 수 없습니다: {template_path}')

    steps = steps_fn(data)
    notice = _PERSONAL_INFO_NOTICE_BY_TEMPLATE.get(template)
    delete_tables = _DELETE_TABLES_BY_TEMPLATE.get(template, [])

    tmp_files: list[str] = []

    def _new_tmp(suffix: str = '.hwp') -> str:
        fd, path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        tmp_files.append(path)
        return path

    plan_path = _new_tmp('.plan.json')
    try:
        # 입력 줄이 양식의 고정 행보다 많은 표는 행을 먼저 늘리고, 글이 많이 들어가는 행은 높이를 미리 맞춘다(표 번호 · 행 번호는 그대로이고 늘린 행 아래의 행만 밀린다)
        plan_input = _prepare_tables(template_path, steps, _new_tmp, template)
        current_output = _new_tmp()
        with open(plan_path, 'w', encoding='utf-8') as f:
            json.dump({
                'planVersion': '1.0',
                'input': plan_input,
                'output': current_output,
                'steps': list(steps),
            }, f, ensure_ascii=False)
        _run_rhwp(['run', plan_path])

        # 여러 줄 칸 — set_cell이 줄바꿈을 거부해 첫 줄만 들어가 있으므로 나머지 줄을 칸 문단으로 나눠 넣는다
        current_output = _write_cell_lines(current_output, steps.cell_lines, _new_tmp)

        # 표 밖 개인정보 마스킹 안내문구(파란 글씨) 삭제 — 문단 자체를 지우면 뒤
        # 문단 번호가 당겨지므로 delete-text로 글자만 비운다.
        if notice is not None:
            notice_para, notice_count = notice
            next_output = _new_tmp()
            _run_rhwp([
                'edit', 'delete-text', current_output,
                '--section', '0', '--para', str(notice_para), '--offset', '0', '--count', str(notice_count),
                '-o', next_output,
            ])
            current_output = next_output

        # 목차/안내문구 표 삭제 — 매번 이전 산출물을 입력으로 체이닝한다(delete-table은
        # run 계획의 step 종류(set_cell 등)에 없는 별도 edit 하위명령이라 한 번에 못 묶는다).
        for table_index in delete_tables:
            next_output = _new_tmp()
            _run_rhwp(['edit', 'delete-table', current_output, '--table', str(table_index), '-o', next_output])
            current_output = next_output

        # 첫 장 고지(기준 문서 T-C4) — 위 표 삭제로 첫 쪽의 안내 표가 사라진 맨 앞 문단(0)에 한 줄로 넣는다
        next_output = _new_tmp()
        _run_rhwp(['edit', 'insert-text', current_output, '--section', '0', '--para', '0', '--offset', '0',
                   '--text', _one_line(data.고지) or DEFAULT_DISCLAIMER, '-o', next_output])
        current_output = next_output

        # 1~4번 절 본문 — 문단을 지우고 넣어 문단 번호가 바뀌므로, 문단 번호를 쓰는 다른 편집(위 안내문구 삭제 · 맨 앞 고지)을 마친 뒤에 한다
        current_output = _write_body_sections(current_output, template, data, _new_tmp)
        # 본문 글머리 줄의 내어쓰기 · 칸 목록의 왼쪽 정렬 — 문단 번호 · 칸 문단 수가 모두 정해진 뒤(그림 쪽을 붙이기 전)에 한다
        current_output = _shape_paragraphs(current_output, template, data, steps, _new_tmp)

        picture_pages = ([(data.그림, None)] if data.그림 else []) + (
            [([data.인포그래픽], _INFOGRAPHIC_MAX_HEIGHT)] if data.인포그래픽 is not None else [])
        if picture_pages:
            current_output = _append_picture_pages(current_output, picture_pages, _new_tmp)
        labels = (['<별첨> 서비스 흐름도 · 서비스 구조도'] if data.그림 else []) + (['<별첨> 인포그래픽'] if data.인포그래픽 is not None else [])
        current_output = _fit_layout(current_output, labels, _new_tmp)

        with open(current_output, 'rb') as f:
            return f.read()
    finally:
        for path in tmp_files:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError:
                # Never replace the conversion exception (or a successful result)
                # with a secondary cleanup error. Log it for operations instead.
                logger.warning('HWP 임시 파일 정리 실패', exc_info=True)
