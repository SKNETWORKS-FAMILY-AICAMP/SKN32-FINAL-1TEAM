"""초기창업패키지(일반형)·예비창업패키지 사업계획서 공식 양식(별첨1)에 내용을 채워
실제 .docx로 만들어주는 모듈.

[2026-09-18 신규] 두 공고 양식을 사용자가 준 원본 파일 2종(초기창업패키지(일반형)/
예비창업패키지)을 직접 비교해서 찾은 실제 차이만 반영했다:
  - 일반현황: 예비창업패키지는 아직 사업자가 없으므로 기업명/개업연월일/사업자구분/
    대표자유형/사업자등록번호/사업자소재지/지원분야/전문기술분야/지방우대지역/총사업비
    항목 자체가 없다 — 대신 "직업(직장명 기재 불가)"/"기업(예정)명" 두 항목만 쓴다.
  - 사업비 집행계획: 초기창업패키지는 정부지원사업비+자기부담사업비(현금/현물) 3분할
    표를 쓰지만, 예비창업패키지는 자기부담금 개념이 없어 정부지원사업비 단일 열 표를
    쓴다. 원본처럼 1단계/2단계 두 표로 나눈다(사업비 줄의 단계 — project_budget_items.phase,
    SB-327. 단계가 없는 줄은 1단계 표).
  - 제목: "초기창업패키지 창업기업 사업계획서" vs "예비창업패키지 사업계획서".
그 외(창업 아이템 개요 요약, PSST 4개 섹션 본문, 사업추진일정, 팀 구성(안), 협력기관)는
두 양식이 표 구조까지 동일해서 공통으로 쓴다.

[2026-09-15] 사용자가 준 원본 파일(.docx/.hwp)은 텍스트 추출 요약본만 받을 수 있어서
(표 구조·스타일 정보 없이 순수 텍스트만) 원본 바이트를 그대로 열어 자리표시자만
치환하는 방식은 못 쓴다. 대신 그 추출 텍스트에 담긴 항목·표 구조(일반현황/창업
아이템 개요/1~4번 섹션과 각 표의 열 이름)를 그대로 재현해서 python-docx로 새로
만든다 — 원본과 글자 그대로 동일한 스타일(폰트·표 테두리 색 등)까지는 보장 못 하지만,
항목 구성과 순서는 원본 공식 양식과 1:1로 맞춘다.

render_plan_docx() · render_plan_hwp()가 받는 PlanDocumentData는 계획서 내려받기가 채워 넘긴다 — 본문은 오케스트레이터가 만든
계획서(app/orch/mapping.py section_bodies), 표는 웹에 저장된 입력이다. 옛 더미 계획서(seed_dummy_pipeline.py)는 없어졌다.
모양(문제인식/실현가능성/성장전략/팀 구성 4개 섹션 + 각 표)이 바뀌지 않는 한 템플릿 코드는 그대로다.

.hwp는 만들지 않는다 — 바이너리 포맷이라 서식을 유지한 채 내용만 써넣는 걸 지원하는
오픈소스 라이브러리가 사실상 없다(pyhwp는 읽기 전용). 이 .docx를 한글에서 열어
"다른 이름으로 저장 → hwp"로 변환하는 게 현실적인 대안이다.

의존성: python-docx (pip install python-docx). requirements.txt에 추가 필요.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

if TYPE_CHECKING:
    from app.diagram_images import DiagramPicture

_HEADER_FILL = 'E8ECF1'


@dataclass
class ScheduleRow:
    구분: str
    추진내용: str
    추진기간: str
    세부내용: str


@dataclass
class BudgetLineItem:
    비목: str
    집행계획: str
    총사업비: str
    정부지원사업비: str
    자기부담_현금: str = ''
    자기부담_현물: str = ''
    단계: str = ''  # 예비창업자만 '1단계' · '2단계'(SB-327). 비어 있으면 1단계 표에 들어간다


PHASE_SECOND = '2단계'


def split_budget_by_phase(rows: list[BudgetLineItem]) -> tuple[list[BudgetLineItem], list[BudgetLineItem]]:
    """예비창업 사업비 행 → (1단계 표 행, 2단계 표 행). 단계가 없는 행은 1단계 쪽이다."""
    second = [r for r in rows if r.단계 == PHASE_SECOND]
    first = [r for r in rows if r.단계 != PHASE_SECOND]
    return first, second


@dataclass
class TeamRow:
    순번: str
    직위: str
    담당업무: str
    보유역량: str
    구성상태: str


@dataclass
class PartnerRow:
    순번: str
    파트너명: str
    보유역량: str
    협업방안: str
    협력시기: str


@dataclass
class PlanDocumentData:
    """render_plan_docx()에 넘길 계획서 내용. 필드 이름은 전부 원본 양식(별첨1)의
    항목명을 그대로 따랐다 — 나중에 이 값들을 실제 Agent 생성 결과로 채울 때 매핑을
    헷갈리지 않도록."""

    # 일반현황
    기업명: str
    개업연월일: str
    사업자_구분: str  # 개인사업자 / 법인사업자
    대표자_유형: str  # 단독 / 공동 / 각자대표
    사업자등록번호: str
    사업자_소재지: str
    창업아이템명: str
    산출물: str
    지원분야: str  # 제조 / 지식서비스
    전문기술분야: str
    정부지원사업비: str
    자기부담_현금: str
    자기부담_현물: str
    총사업비: str
    지방우대_지역_해당여부: str
    팀구성현황: list[TeamRow]

    # 창업 아이템 개요(요약)
    아이템_명칭: str
    아이템_범주: str
    아이템_개요: str
    요약_문제인식: str
    요약_실현가능성: str
    요약_성장전략: str
    요약_팀구성: str

    # 1~4번 섹션 본문
    문제인식_본문: str
    실현가능성_본문: str
    실현가능성_일정: list[ScheduleRow]
    사업비_집행계획: list[BudgetLineItem]
    성장전략_본문: str
    성장전략_일정: list[ScheduleRow]
    팀구성_본문: str
    팀구성_안: list[TeamRow]
    협력기관: list[PartnerRow] = field(default_factory=list)

    # 예비창업패키지 전용(template='preliminary') — 사업자가 아직 없어 기업명/사업자
    # 등록번호 대신 이 두 항목을 쓴다. 초기창업패키지(일반형) 렌더링에서는 안 쓰인다.
    직업: str = '○○○'
    기업예정명: str = '○○○'

    # [SB-339] 표 항목(개발계획 · 사업비 집행계획 · 전체 일정)의 서술 문장 — 표는 위 행 목록으로 그리고, 서술은 계획서(planDoc)에서 온다
    # (app/plan_texts.py). docx는 표 아래 문단으로, hwp는 양식에 따로 칸이 없어 그 절의 본문 뒤에 이어 붙는다.
    실현가능성_일정_서술: str = ''
    사업비_서술: str = ''          # 예비창업자는 1단계 표의 서술(x.5.3), 그 밖은 사업비 표 하나의 서술
    사업비_2단계_서술: str = ''    # 예비창업자 2단계 표의 서술(x.5.4)
    성장전략_일정_서술: str = ''
    # 예비창업자 단계별 정부지원사업비 합계(표 아래 합계 칸). 단계 입력이 없으면 비어 있다
    정부지원사업비_1단계: str = ''
    정부지원사업비_2단계: str = ''
    # [SB-340] 그림 항목(2.3.6 · 3.3.6)의 서비스 흐름도 · 서비스 구조도(PNG로 바꾼 것, app/diagram_images.py). docx는 개요(요약) 표 아래,
    # hwp는 맨 뒤에 새로 만든 쪽에 넣는다. 그림이 없으면 문서에 아무것도 더하지 않는다.
    그림: list[DiagramPicture] = field(default_factory=list)
    # [SB-354 · 기준 문서 T-C4] 결과물의 인포그래픽(PNG로 바꾼 것)과 첫 장 고지 문구(`deliverable.disclaimer`). docx는 계획서 그림 다음에, hwp는 그림 쪽
    # 다음의 새 쪽에 인포그래픽을 넣는다. 고지가 비어 있으면(결과물이 아직 없을 때) 기본 문구를 쓴다.
    인포그래픽: DiagramPicture | None = None
    고지: str = ''


def _set_cell_text(cell, text: str, bold: bool = False, shade: str | None = None) -> None:
    cell.text = ''
    p = cell.paragraphs[0]
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(10)
    if shade:
        tc_pr = cell._tc.get_or_add_tcPr()
        shd = tc_pr.makeelement(qn('w:shd'), {qn('w:val'): 'clear', qn('w:color'): 'auto', qn('w:fill'): shade})
        tc_pr.append(shd)


def _kv_table(doc: Document, rows: list[tuple[str, str]]) -> None:
    """'항목 | 값' 2열 표 — 일반현황/창업 아이템 개요(요약) 같은 key-value 블록에 쓴다."""
    table = doc.add_table(rows=0, cols=2)
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.columns[0].width = Cm(4.2)
    table.columns[1].width = Cm(12.8)
    for label, value in rows:
        row = table.add_row()
        _set_cell_text(row.cells[0], label, bold=True, shade=_HEADER_FILL)
        _set_cell_text(row.cells[1], value)


def _grid_table(doc: Document, headers: list[str], rows: list[list[str]], caption: str | None = None) -> None:
    if caption:
        p = doc.add_paragraph()
        run = p.add_run(caption)
        run.bold = True
        run.font.size = Pt(10.5)
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        _set_cell_text(table.rows[0].cells[i], h, bold=True, shade=_HEADER_FILL)
    for r in rows:
        cells = table.add_row().cells
        for i, v in enumerate(r):
            _set_cell_text(cells[i], v)


def _heading(doc: Document, text: str, level: int = 1) -> None:
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.color.rgb = RGBColor(0, 0, 0)


_TEMPLATE_TITLES = {
    'early_general': '초기창업패키지 창업기업 사업계획서',
    'preliminary': '예비창업패키지 사업계획서',
}


def _add_general_status_early(doc: Document, data: PlanDocumentData) -> None:
    """초기창업패키지(일반형) — 이미 사업자가 있다는 전제로 기업 정보·사업비 3분할
    (정부지원+자기부담 현금/현물)을 담는다."""
    _kv_table(doc, [
        ('기업명', data.기업명),
        ('개업연월일', data.개업연월일),
        ('사업자 구분\n(모집마감일 기준)', data.사업자_구분),
        ('대표자 유형\n(모집마감일 기준)', data.대표자_유형),
        ('사업자등록번호\n(법인등록번호)', data.사업자등록번호),
        ('사업자 소재지\n(본사(점))', data.사업자_소재지),
        ('창업아이템명', data.창업아이템명),
        ('산출물\n(협약기간 내 목표)', data.산출물),
        ('지원 분야(택1)', data.지원분야),
        ('전문기술분야(택1)', data.전문기술분야),
        ('지방우대 지역 해당여부', data.지방우대_지역_해당여부),
    ])
    _grid_table(
        doc,
        ['정부지원사업비(A)', '자기부담사업비(B) 현금', '자기부담사업비(B) 현물', '총 사업비(C=A+B)'],
        [[data.정부지원사업비, data.자기부담_현금, data.자기부담_현물, data.총사업비]],
        caption='총 사업비 구성 계획',
    )


def _add_general_status_preliminary(doc: Document, data: PlanDocumentData) -> None:
    """예비창업패키지 — 아직 사업자등록 전이라는 전제로, 기업명·사업자등록번호·지원분야·
    전문기술분야·지방우대지역·총사업비 항목 자체가 없다(원본 양식에도 없음). 대신 신청자의
    현재 직업과 창업 예정 상호(기업(예정)명)만 받는다."""
    _kv_table(doc, [
        ('창업아이템명', data.창업아이템명),
        ('산출물\n(협약기간 내 목표)', data.산출물),
        ('직업\n(직장명 기재 불가)', data.직업),
        ('기업(예정)명', data.기업예정명),
    ])


def _picture(doc: Document, picture: DiagramPicture, max_height_cm: float | None = None) -> None:
    """그림 하나 — 위에 '< 서비스 흐름도 >' 같은 제목을 달고 본문 폭에 맞춰 넣는다(PNG, 가운데). 세로가 max_height_cm를 넘으면 비율을 지켜 줄인다."""
    caption = doc.add_paragraph()
    run = caption.add_run(f'< {picture.title} >')
    run.bold = True
    run.font.size = Pt(10.5)
    width_px, height_px = picture.size_px
    width_cm = float(_PICTURE_WIDTH_CM)
    if max_height_cm is not None and width_px and width_cm * height_px / width_px > max_height_cm:
        width_cm = max_height_cm * width_px / height_px
    doc.add_picture(io.BytesIO(picture.png), width=Cm(width_cm))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER


_PICTURE_WIDTH_CM = 16
_INFOGRAPHIC_MAX_HEIGHT_CM = 22   # 인포그래픽은 세로로 긴 한 장이라 쪽 높이(여백 뺀 약 25cm)를 넘지 않게 줄인다
# 기준 문서(기능정의서 T-C4)의 첫 장 고지 — 결과물(deliverable.disclaimer)이 아직 없을 때의 기본 문구
DEFAULT_DISCLAIMER = '본 문서는 S-Brain이 생성한 초안입니다. 제출 전 작성자 본인의 확인과 수정이 필요합니다.'


def _bullets(doc: Document, text: str) -> None:
    """절 본문 — 줄(계획서의 문단)마다 " ◦ " 문단 하나(hwp 본문과 같은 모양)."""
    for line in (text or '').replace('\r', '').split('\n'):
        if line.strip():
            doc.add_paragraph(f' ◦ {line.strip()}')


def _narrative(doc: Document, text: str) -> None:
    """표 아래 서술 문장(줄마다 한 문단). 서술이 없으면 아무것도 쓰지 않는다."""
    for line in (text or '').splitlines():
        if line.strip():
            doc.add_paragraph(line.strip())


def render_plan_docx(data: PlanDocumentData, template: str = 'early_general') -> bytes:
    """template: 'early_general'(초기창업패키지 일반형, 기본값) | 'preliminary'(예비창업패키지).
    두 원본 양식(별첨1)을 비교해 실제로 다른 부분(일반현황 항목, 사업비 집행계획 표 구성,
    제목)만 갈라 렌더링한다 — 나머지 섹션은 두 양식이 표 구조까지 동일해 공통으로 쓴다
    (모듈 docstring 참고)."""
    if template not in _TEMPLATE_TITLES:
        raise ValueError(f"template은 {tuple(_TEMPLATE_TITLES)} 중 하나여야 합니다: {template!r}")

    doc = Document()
    style = doc.styles['Normal']
    style.font.name = '맑은 고딕'
    style.font.size = Pt(10.5)

    title = doc.add_heading(_TEMPLATE_TITLES[template], level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    disclaimer = doc.add_paragraph()
    disclaimer_run = disclaimer.add_run(data.고지.strip() or DEFAULT_DISCLAIMER)
    disclaimer_run.bold = True
    disclaimer_run.font.size = Pt(10.5)

    _heading(doc, '□ 일반현황', level=1)
    if template == 'preliminary':
        _add_general_status_preliminary(doc, data)
    else:
        _add_general_status_early(doc, data)
    _grid_table(
        doc,
        ['순번', '직위', '담당 업무', '보유 역량(경력 및 학력 등)', '구성 상태'],
        [[t.순번, t.직위, t.담당업무, t.보유역량, t.구성상태] for t in data.팀구성현황],
        caption='팀 구성 현황(대표자 본인 제외)',
    )

    _heading(doc, '□ 창업 아이템 개요(요약)', level=1)
    _kv_table(doc, [
        ('명 칭', data.아이템_명칭),
        ('범 주', data.아이템_범주),
        ('아이템 개요', data.아이템_개요),
        ('문제 인식(Problem)', data.요약_문제인식),
        ('실현 가능성(Solution)', data.요약_실현가능성),
        ('성장전략(Scale-up)', data.요약_성장전략),
        ('팀 구성(Team)', data.요약_팀구성),
    ])
    for picture in data.그림:
        _picture(doc, picture)
    if data.인포그래픽 is not None:
        _picture(doc, data.인포그래픽, max_height_cm=_INFOGRAPHIC_MAX_HEIGHT_CM)

    _heading(doc, '1. 문제 인식(Problem)_창업 아이템의 필요성', level=1)
    _bullets(doc, data.문제인식_본문)

    _heading(doc, '2. 실현 가능성(Solution)_창업 아이템의 개발 계획', level=1)
    _bullets(doc, data.실현가능성_본문)
    _grid_table(
        doc,
        ['구분', '추진 내용', '추진 기간', '세부 내용'],
        [[s.구분, s.추진내용, s.추진기간, s.세부내용] for s in data.실현가능성_일정],
        caption='< 사업추진 일정(협약기간 내) >',
    )
    _narrative(doc, data.실현가능성_일정_서술)
    if template == 'preliminary':
        # 예비창업패키지는 자기부담금 개념이 없어 정부지원사업비 단일 열만 쓴다. 원본 양식처럼
        # 1단계 · 2단계 두 표로 나눈다(project_budget_items.phase, SB-327) — 단계가 없는 행은 1단계 표.
        first, second = split_budget_by_phase(data.사업비_집행계획)
        for label, rows, total, narrative in (
            ('1단계', first, data.정부지원사업비_1단계, data.사업비_서술),
            ('2단계', second, data.정부지원사업비_2단계, data.사업비_2단계_서술),
        ):
            _grid_table(
                doc,
                ['비목', '산출 근거', '정부지원사업비(원)'],
                [[b.비목, b.집행계획, b.정부지원사업비] for b in rows] or [['○○', '○○', '○○']],
                caption=f'< 정부지원사업비 집행계획({label}) >',
            )
            if total:
                doc.add_paragraph(f'{label} 합계: {total}')
            _narrative(doc, narrative)
    else:
        _grid_table(
            doc,
            ['비목', '집행 계획', '총사업비(ⓐ+ⓑ)', '정부지원사업비(ⓐ)', '자기부담사업비(ⓑ) 현금', '자기부담사업비(ⓑ) 현물'],
            [[b.비목, b.집행계획, b.총사업비, b.정부지원사업비, b.자기부담_현금, b.자기부담_현물] for b in data.사업비_집행계획],
            caption='< 사업비 집행 계획 >',
        )
        _narrative(doc, data.사업비_서술)

    _heading(doc, '3. 성장전략(Scale-up)_사업화 추진 전략', level=1)
    _bullets(doc, data.성장전략_본문)
    _grid_table(
        doc,
        ['구분', '추진 내용', '추진 기간', '세부 내용'],
        [[s.구분, s.추진내용, s.추진기간, s.세부내용] for s in data.성장전략_일정],
        caption='< 사업추진 일정(전체 사업단계) >',
    )
    _narrative(doc, data.성장전략_일정_서술)

    _heading(doc, '4. 팀 구성(Team)_대표자 및 팀원 구성 계획', level=1)
    _bullets(doc, data.팀구성_본문)
    _grid_table(
        doc,
        ['순번', '직위', '담당 업무', '보유 역량(경력 및 학력 등)', '구성 상태'],
        [[t.순번, t.직위, t.담당업무, t.보유역량, t.구성상태] for t in data.팀구성_안],
        caption='< 팀 구성(안) >',
    )
    if data.협력기관:
        _grid_table(
            doc,
            ['순번', '파트너명', '보유 역량', '협업 방안', '협력 시기'],
            [[p.순번, p.파트너명, p.보유역량, p.협업방안, p.협력시기] for p in data.협력기관],
            caption='< 협력 기관 현황 및 협업 방안 >',
        )

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
