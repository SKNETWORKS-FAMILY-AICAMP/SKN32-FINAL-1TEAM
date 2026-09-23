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
템플릿 파일 2종 모두 `export-markdown`으로 렌더 확인까지 마쳤다(_BODY_INSERTS_BY_TEMPLATE
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
  - set_cell의 `text`는 줄바꿈을 거부한다(칸 구조가 깨진다는 이유) — 그래서 표
    셀에 들어가는 여러 줄짜리 값(요약 필드 등)도 한 줄로 눌러 담는다(_one_line).
  - 표 안 예시 행 개수(양식마다 다름 — 팀 구성 3~4행, 일정 5행, 사업비 4~5행,
    팀구성안/협력기관 3행)를 넘는 데이터는 지금은 잘린다 — insert-row로 늘릴 수
    있지만, 사업비 표는 "재료비" 라벨이 rowSpan=2로 첫 두 행을 걸쳐 있어서 행 삽입
    시 병합이 깨질 위험이 있어 일부러 손대지 않았다. 원본 양식 자체도 "행 추가
    가능, 해당 없으면 공란 유지"라고 안내하므로, 넘치는 항목은 잘리고 남는 행은
    공란 처리하는 지금 방식이 최소한 "지어내지 않는다"는 원칙은 지킨다.
  - 사업비 집행계획은 원본이 1단계/2단계 두 표로 나뉘는데 DB엔 "단계" 개념이 없다
    (plan_document_export.py와 같은 이유) — 전부 1단계 표에 몰아넣고 2단계 표는
    예시 숫자가 진짜처럼 보이지 않도록 공란으로 지운다.
  - 초기창업패키지(early_general) 표5의 "지원 분야"/"전문기술분야"는 실제 체크박스가
    아니라 빈 칸에 표시를 채워 넣는 방식이라(뒤한글 실제 체크박스 컨트롤이 아님),
    project.tech_field 값이 9개 보기 문구와 정확히 같을 때만 그 칸에 'V'를 쓴다 —
    다르거나 비어 있으면(대부분 지금은 플레이스홀더 '○○·○○') 아무 칸도 안 건드린다.
    "지방우대 지역 해당여부"도 같은 방식(4개 보기: 특별지원/우대지원/일반/비해당).
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile

from app.plan_document_export import BudgetLineItem, PartnerRow, PlanDocumentData, ScheduleRow, TeamRow

RHWP_BIN = os.environ.get('RHWP_BIN') or 'rhwp'

_HWP_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), 'assets', 'hwp_templates')
_HWP_TEMPLATE_FILES = {
    'preliminary': '예비창업패키지_사업계획서_양식.hwp',
    'early_general': '초기창업패키지_사업계획서_양식.hwp',
}


def _one_line(text: str) -> str:
    """set_cell.text는 개행/탭을 거부한다(HWP 표 칸 구조가 깨지므로) — 여러 문단은
    ' / '로 이어붙여 한 줄로 만든다."""
    if not text:
        return ''
    return ' / '.join(line.strip() for line in text.replace('\r', '').split('\n') if line.strip())


def _set_cell(steps: list[dict], table: int, row: int, col: int, text: str) -> None:
    steps.append({'action': 'set_cell', 'table': table, 'row': row, 'col': col, 'text': _one_line(text)})


def _fill_rows(
    steps: list[dict], table: int, start_row: int, cols: list[int],
    rows: list[tuple[str, ...]], slot_count: int,
) -> None:
    """rows(실제 데이터, 각 항목은 cols 개수만큼의 문자열 튜플)를 표의 고정 슬롯
    (start_row부터 slot_count행)에 채운다. 데이터가 모자라면 남는 슬롯은 공란,
    넘치면 뒤쪽은 잘린다(모듈 docstring의 "아직 안 된 것" 참고)."""
    for i in range(slot_count):
        values = rows[i] if i < len(rows) else tuple('' for _ in cols)
        for col, value in zip(cols, values):
            _set_cell(steps, table, start_row + i, col, value)


def _team_status_rows(team: list[TeamRow]) -> list[tuple[str, ...]]:
    return [(str(i + 1), t.직위, t.담당업무, t.보유역량, t.구성상태) for i, t in enumerate(team)]


def _schedule_rows_tuples(rows: list[ScheduleRow]) -> list[tuple[str, ...]]:
    return [(s.구분, s.추진내용, s.추진기간, s.세부내용) for s in rows]


def _partner_rows_tuples(rows: list[PartnerRow]) -> list[tuple[str, ...]]:
    return [(p.순번, p.파트너명, p.보유역량, p.협업방안, p.협력시기) for p in rows]


def _budget_steps(steps: list[dict], table: int, budget: list[BudgetLineItem], total_text: str) -> None:
    """표12/14(사업비 집행계획) 전용 — row1/row2는 '재료비' 라벨이 rowSpan=2로 걸쳐
    있어 row2엔 col0(라벨) 칸이 없다(병합에 덮여 set_cell이 거부한다). 그래서 두 번째
    항목은 라벨 없이 col1에 '비목명: 산출근거' 형태로 합쳐 넣는다."""
    items = budget[:5]
    if items:
        first = items[0]
        _set_cell(steps, table, 1, 0, first.비목)
        _set_cell(steps, table, 1, 1, first.집행계획)
        _set_cell(steps, table, 1, 2, first.정부지원사업비)
    else:
        _set_cell(steps, table, 1, 0, '')
        _set_cell(steps, table, 1, 1, '')
        _set_cell(steps, table, 1, 2, '')
    if len(items) > 1:
        second = items[1]
        _set_cell(steps, table, 2, 1, f'{second.비목}: {second.집행계획}')
        _set_cell(steps, table, 2, 2, second.정부지원사업비)
    else:
        _set_cell(steps, table, 2, 1, '')
        _set_cell(steps, table, 2, 2, '')
    for slot, i in enumerate(range(2, 5)):  # 표의 row3/row4/row5 <- items[2:5]
        row = 3 + slot
        if i < len(items):
            item = items[i]
            _set_cell(steps, table, row, 0, item.비목)
            _set_cell(steps, table, row, 1, item.집행계획)
            _set_cell(steps, table, row, 2, item.정부지원사업비)
        else:
            _set_cell(steps, table, row, 0, '')
            _set_cell(steps, table, row, 1, '')
            _set_cell(steps, table, row, 2, '')
    _set_cell(steps, table, 6, 2, total_text)


def _mark_choice(steps: list[dict], table: int, value: str, options: dict[str, tuple[int, int]]) -> None:
    """표5/표9의 "택1" 칸 — 실제 체크박스 컨트롤이 아니라 옵션 라벨 옆의 빈 칸이라,
    값이 그 9개(또는 4개) 보기 문구와 정확히 같을 때만 그 칸에 'V'를 쓴다. 값이
    플레이스홀더거나 목록에 없으면 아무 칸도 안 건드린다(지어내지 않는다)."""
    coords = options.get(value)
    if coords is not None:
        _set_cell(steps, table, coords[0], coords[1], 'V')


def _budget_steps_full(steps: list[dict], table: int, budget: list[BudgetLineItem], data: PlanDocumentData) -> None:
    """초기창업패키지 표13(사업비 집행계획) 전용 — 비목/집행계획/정부지원사업비/
    자기부담(현금·현물)/합계 6열. row3/row4는 '재료비' 라벨이 rowSpan=2라 row4엔
    col0(라벨) 칸이 없다(표12/14의 3열 버전과 같은 제약, _budget_steps 참고)."""
    items = budget[:4]

    def _row(row: int, item: BudgetLineItem | None, with_label: bool) -> None:
        if item is None:
            cols = (0, 1, 2, 3, 4, 5) if with_label else (1, 2, 3, 4, 5)
            for col in cols:
                _set_cell(steps, table, row, col, '')
            return
        if with_label:
            _set_cell(steps, table, row, 0, item.비목)
            _set_cell(steps, table, row, 1, item.집행계획)
        else:
            _set_cell(steps, table, row, 1, f'{item.비목}: {item.집행계획}')
        _set_cell(steps, table, row, 2, item.정부지원사업비)
        _set_cell(steps, table, row, 3, item.자기부담_현금)
        _set_cell(steps, table, row, 4, item.자기부담_현물)
        _set_cell(steps, table, row, 5, item.총사업비)

    _row(3, items[0] if len(items) > 0 else None, with_label=True)
    _row(4, items[1] if len(items) > 1 else None, with_label=False)
    _row(5, items[2] if len(items) > 2 else None, with_label=True)
    _row(6, items[3] if len(items) > 3 else None, with_label=True)
    _set_cell(steps, table, 7, 2, data.정부지원사업비)
    _set_cell(steps, table, 7, 3, data.자기부담_현금)
    _set_cell(steps, table, 7, 4, data.자기부담_현물)
    _set_cell(steps, table, 7, 5, data.총사업비)


_SUPPORT_FIELD_OPTIONS = {'제조': (2, 3), '지식서비스': (2, 8)}
_TECH_FIELD_OPTIONS = {
    '기계·소재': (3, 3), '전기·전자': (3, 8), '정보·통신': (3, 14),
    '화공·섬유': (4, 3), '바이오·의료·생명': (4, 8), '에너지·자원': (4, 14),
    '공예·디자인': (5, 3),
}
_REGIONAL_PRIORITY_OPTIONS = {
    '특별지원 지역': (9, 3), '우대지원 지역': (9, 7), '일반지역': (9, 11), '지방우대 비해당 지역': (9, 15),
}


def _early_general_steps(data: PlanDocumentData) -> list[dict]:
    """rhwp export-tables로 실측한 초기창업패키지(일반형) 원본 양식(표 21개) 좌표."""
    steps: list[dict] = []

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
    _mark_choice(steps, 5, data.전문기술분야, _TECH_FIELD_OPTIONS)
    _set_cell(steps, 5, 8, 3, data.정부지원사업비)
    _set_cell(steps, 5, 8, 10, data.자기부담_현금)
    _set_cell(steps, 5, 8, 13, data.자기부담_현물)
    _set_cell(steps, 5, 8, 18, data.총사업비)
    _mark_choice(steps, 5, data.지방우대_지역_해당여부, _REGIONAL_PRIORITY_OPTIONS)
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


def _preliminary_steps(data: PlanDocumentData) -> list[dict]:
    """rhwp export-tables로 실측한 예비창업패키지 원본 양식(표 22개) 좌표 — 표 번호는
    export-tables/set_cell이 공유하는 문서 순서 그대로(0부터)."""
    steps: list[dict] = []

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
    # 표12/14: 사업비 집행계획(1단계에 전부, 2단계는 공란 — 모듈 docstring 참고)
    _budget_steps(steps, 12, data.사업비_집행계획, data.정부지원사업비)
    _budget_steps(steps, 14, [], '')

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

# 1~4번 섹션 본문 — `rhwp dump`로 실측한 (구역=0 고정) 문단 번호. 각 문단은 이미
# " ◦ "(길이 3)로 시작하는 빈 칸이라 offset=3(◦ 뒤)에 이어붙인다. 모듈 docstring
# "2026-09-22 문제인식_본문 등 4개 본문 채우기 완료" 참고.
_BODY_INSERT_OFFSET = 3
_BODY_INSERTS_BY_TEMPLATE: dict[str, list[tuple[str, int]]] = {
    'preliminary': [
        ('문제인식_본문', 11),
        ('실현가능성_본문', 26),
        ('성장전략_본문', 49),
        ('팀구성_본문', 75),
    ],
    'early_general': [
        ('문제인식_본문', 13),
        ('실현가능성_본문', 28),
        ('성장전략_본문', 44),
        ('팀구성_본문', 70),
    ],
}

# 팀 구성 제목 표 다음에 오는, 표가 아닌 개인정보 마스킹 안내문구(파란 글씨) 문단 —
# (구역=0 고정 문단 번호, 글자 수). 모듈 docstring "표 밖 파란 안내문구" 참고.
_PERSONAL_INFO_NOTICE_BY_TEMPLATE: dict[str, tuple[int, int]] = {
    'preliminary': (72, 107),
    'early_general': (67, 107),
}


def _run_rhwp(args: list[str]) -> None:
    """rhwp CLI를 실행하고 실패를 일관된 예외로 바꾼다 — render_plan_hwp의 run/edit
    delete-table 호출이 공유한다."""
    try:
        result = subprocess.run(
            [RHWP_BIN, *args], capture_output=True, text=True, encoding='utf-8', errors='replace',
        )
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"rhwp 실행 파일을 찾을 수 없습니다('{RHWP_BIN}') — RHWP_BIN 환경변수로 경로를 지정하세요"
        ) from exc
    if result.returncode != 0:
        error_msg = (result.stderr or result.stdout or '알 수 없는 rhwp 오류').strip()
        raise RuntimeError(f'rhwp 처리 중 오류 발생: {error_msg}')


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
    body_inserts = _BODY_INSERTS_BY_TEMPLATE.get(template, [])
    notice = _PERSONAL_INFO_NOTICE_BY_TEMPLATE.get(template)
    delete_tables = _DELETE_TABLES_BY_TEMPLATE.get(template, [])

    tmp_files: list[str] = []

    def _new_tmp() -> str:
        fd, path = tempfile.mkstemp(suffix='.hwp')
        os.close(fd)
        tmp_files.append(path)
        return path

    plan_fd, plan_path = tempfile.mkstemp(suffix='.plan.json')
    try:
        current_output = _new_tmp()
        with os.fdopen(plan_fd, 'w', encoding='utf-8') as f:
            json.dump({
                'planVersion': '1.0',
                'input': template_path,
                'output': current_output,
                'steps': steps,
            }, f, ensure_ascii=False)
        _run_rhwp(['run', plan_path])

        # 1~4번 섹션 본문 삽입 — set_cell처럼 run 계획에 못 묶는 별도 edit
        # 하위명령이라(export-plan-schema에 insert_text step이 없음) 여기서도
        # delete-table처럼 이전 산출물을 체이닝한다. 빈 문자열은 insert-text가
        # 거부하므로(그리고 채울 내용이 없으면 빈 칸 유지가 원칙이므로) 건너뛴다.
        for field_name, para in body_inserts:
            text = _one_line(getattr(data, field_name, ''))
            if not text:
                continue
            next_output = _new_tmp()
            _run_rhwp([
                'edit', 'insert-text', current_output,
                '--section', '0', '--para', str(para), '--offset', str(_BODY_INSERT_OFFSET),
                '--text', text, '-o', next_output,
            ])
            current_output = next_output

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

        with open(current_output, 'rb') as f:
            return f.read()
    finally:
        if os.path.exists(plan_path):
            os.remove(plan_path)
        for path in tmp_files:
            if os.path.exists(path):
                os.remove(path)
