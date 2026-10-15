"""내려받기 문서의 추진 일정 표 — 입력한 칸이 같은 이름의 열에 들어간다 (SB-329 · SB-339).

입력 화면은 일정 한 줄을 구분 · 추진 내용 · 추진 기간 · 세부 내용으로 받는다. 예전에는 문서 쪽이 구분 열에 순번을, 추진 내용 열에
입력한 '구분'을 넣고 입력한 '추진 내용'은 세부 내용이 있으면 버렸다. 세부 내용은 비워도 되는 칸이라 비우면 빈칸이다.
입력한 줄이 없을 때만 자리표시 한 줄이 나온다.

실행:
    pytest tests/test_schedule_table_export.py -v
"""
import io
import json

from docx import Document

from app.hwp_export import _preliminary_steps
from app.models import Project
from app.plan_texts import PlanTexts
from app.routers.projects import _build_plan_document_data

FEASIBILITY = [
    {'section': 'feasibility', 'category': '개발', 'content': '모델 고도화', 'period': '2026.05~2026.07', 'detail': '정확도 80%'},
    {'section': 'feasibility', 'category': '검증', 'content': '시범 운영', 'period': '2026.08', 'detail': ''},
]
GROWTH = [{'section': 'growth', 'category': '확장', 'content': '해외 진출', 'period': '2027.01~2027.12', 'detail': '동남아 2개국'}]


def _create(client, schedule_items):
    payload = {'applicant_type': 'individual', 'biz_type': '개인', 'ceo_name': '박테스트', 'description': 'AI 서비스',
               'team_members': [], 'pricing_items': [], 'schedule_items': schedule_items}
    r = client.post('/projects', data={'payload': json.dumps(payload)})
    assert r.status_code == 201, r.text
    return r.json()['project_id']


def _tables_with_header(client, project_id, caption_words):
    r = client.get(f'/projects/{project_id}/plan-document.docx')
    assert r.status_code == 200, r.text
    doc = Document(io.BytesIO(r.content))
    return [[[c.text for c in row.cells] for row in t.rows] for t in doc.tables if [c.text for c in t.rows[0].cells] == caption_words]


HEADER = ['구분', '추진 내용', '추진 기간', '세부 내용']


def test_docx_schedule_tables_put_each_input_in_its_own_column(authed_client):
    pid = _create(authed_client, [*FEASIBILITY, *GROWTH])

    inside, after = _tables_with_header(authed_client, pid, HEADER)

    assert inside[1:] == [['개발', '모델 고도화', '2026.05~2026.07', '정확도 80%'], ['검증', '시범 운영', '2026.08', '']]
    assert after[1:] == [['확장', '해외 진출', '2027.01~2027.12', '동남아 2개국']]


def test_docx_without_input_rows_shows_one_placeholder_row(authed_client):
    pid = _create(authed_client, [])

    inside, after = _tables_with_header(authed_client, pid, HEADER)

    assert inside[1][0] == '1' and inside[1][1] == '○○' and after[1][0] == '1'


def test_hwp_schedule_tables_use_the_same_columns(authed_client, db_session):
    pid = _create(authed_client, [*FEASIBILITY, *GROWTH])
    data, _template = _build_plan_document_data(db_session, db_session.get(Project, pid), PlanTexts())

    # 예비창업이 아니어도 표10(실현가능성 일정)과 표17(성장전략 일정)은 같은 열 순서다
    rows = {(s['table'], s['row'], s['col']): s['text'] for s in _preliminary_steps(data) if s['action'] == 'set_cell'}

    assert [rows[(10, 1, c)] for c in range(4)] == ['개발', '모델 고도화', '2026.05~2026.07', '정확도 80%']
    assert [rows[(10, 2, c)] for c in range(4)] == ['검증', '시범 운영', '2026.08', '']
    assert [rows[(17, 1, c)] for c in range(4)] == ['확장', '해외 진출', '2027.01~2027.12', '동남아 2개국']
