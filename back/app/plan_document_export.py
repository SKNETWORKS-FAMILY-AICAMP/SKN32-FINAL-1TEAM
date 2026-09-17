"""초기창업패키지(일반형) 사업계획서 공식 양식(별첨1)에 내용을 채워 실제 .docx로
만들어주는 모듈.

[2026-09-15] 사용자가 준 원본 파일(.docx/.hwp)은 텍스트 추출 요약본만 받을 수 있어서
(표 구조·스타일 정보 없이 순수 텍스트만) 원본 바이트를 그대로 열어 자리표시자만
치환하는 방식은 못 쓴다. 대신 그 추출 텍스트에 담긴 항목·표 구조(일반현황/창업
아이템 개요/1~4번 섹션과 각 표의 열 이름)를 그대로 재현해서 python-docx로 새로
만든다 — 원본과 글자 그대로 동일한 스타일(폰트·표 테두리 색 등)까지는 보장 못 하지만,
항목 구성과 순서는 원본 공식 양식과 1:1로 맞춘다.

이 모듈은 지금 당장은 seed_dummy_pipeline.py의 더미 계획서 내용을 채우는 용도로 쓰지만,
render_plan_docx()가 받는 PlanDocumentData가 실제 Agent가 만들 계획서 내용과 같은
모양(문제인식/실현가능성/성장전략/팀 구성 4개 섹션 + 각 표)이라, 나중에 진짜 생성
파이프라인이 붙으면 이 함수에 넘기는 데이터만 더미 대신 실제 값으로 바꾸면 된다 —
템플릿 코드 자체는 안 바뀐다.

.hwp는 만들지 않는다 — 바이너리 포맷이라 서식을 유지한 채 내용만 써넣는 걸 지원하는
오픈소스 라이브러리가 사실상 없다(pyhwp는 읽기 전용). 이 .docx를 한글에서 열어
"다른 이름으로 저장 → hwp"로 변환하는 게 현실적인 대안이다.

의존성: python-docx (pip install python-docx). requirements.txt에 추가 필요.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

_GUIDE_COLOR = RGBColor(0x1F, 0x4E, 0x79)  # 원본 양식의 '파란색 안내 문구'와 같은 취지 — 작성자 안내용, 제출 전 삭제 대상
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


def _guide_note(doc: Document, text: str) -> None:
    """원본 양식의 '파란색 안내 문구'와 같은 역할 — 실제 제출 전엔 삭제 대상이므로
    이탤릭+옅은 색으로 구분해서 넣는다(검정 굵은 본문과 섞이지 않도록)."""
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.italic = True
    run.font.size = Pt(8.5)
    run.font.color.rgb = _GUIDE_COLOR


def render_plan_docx(data: PlanDocumentData) -> bytes:
    doc = Document()
    style = doc.styles['Normal']
    style.font.name = '맑은 고딕'
    style.font.size = Pt(10.5)

    title = doc.add_heading('초기창업패키지 창업기업 사업계획서', level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    _guide_note(
        doc,
        '※ 사업계획서는 15페이지 내외로 작성(증빙서류는 제한 없음) · 양식은 변경·삭제 불가, '
        '이미지·표 삽입은 가능 · 개인정보는 마스킹하여 작성 — 본 문서는 S-Brain이 생성한 초안입니다.',
    )

    _heading(doc, '□ 일반현황', level=1)
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

    _heading(doc, '1. 문제 인식(Problem)_창업 아이템의 필요성', level=1)
    doc.add_paragraph(data.문제인식_본문)

    _heading(doc, '2. 실현 가능성(Solution)_창업 아이템의 개발 계획', level=1)
    doc.add_paragraph(data.실현가능성_본문)
    _grid_table(
        doc,
        ['구분', '추진 내용', '추진 기간', '세부 내용'],
        [[s.구분, s.추진내용, s.추진기간, s.세부내용] for s in data.실현가능성_일정],
        caption='< 사업추진 일정(협약기간 내) >',
    )
    _guide_note(doc, '※ 정부지원사업비는 최대 1억원 한도 이내로 작성 · 자기부담사업비는 지방우대 지역 여부에 따라 비율이 다름')
    _grid_table(
        doc,
        ['비목', '집행 계획', '총사업비(ⓐ+ⓑ)', '정부지원사업비(ⓐ)', '자기부담사업비(ⓑ) 현금', '자기부담사업비(ⓑ) 현물'],
        [[b.비목, b.집행계획, b.총사업비, b.정부지원사업비, b.자기부담_현금, b.자기부담_현물] for b in data.사업비_집행계획],
        caption='< 사업비 집행 계획 >',
    )

    _heading(doc, '3. 성장전략(Scale-up)_사업화 추진 전략', level=1)
    doc.add_paragraph(data.성장전략_본문)
    _grid_table(
        doc,
        ['구분', '추진 내용', '추진 기간', '세부 내용'],
        [[s.구분, s.추진내용, s.추진기간, s.세부내용] for s in data.성장전략_일정],
        caption='< 사업추진 일정(전체 사업단계) >',
    )

    _heading(doc, '4. 팀 구성(Team)_대표자 및 팀원 구성 계획', level=1)
    doc.add_paragraph(data.팀구성_본문)
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
