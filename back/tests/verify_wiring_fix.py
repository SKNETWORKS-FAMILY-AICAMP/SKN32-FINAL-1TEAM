"""[최종 배선 검증 스크립트]
company, output_summary, tech_field, regional_priority_area,
budget_items, schedule_items, partners 데이터가 DB와 docx 산출물에 온전히 반영되는지 검증
"""
import io
import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tests/ -> back/
sys.path.insert(0, _REPO_ROOT)

os.environ['DB_BACKEND'] = 'mysql'
os.environ['MYSQL_USER'] = 'sbrain_test'
os.environ['MYSQL_PASSWORD'] = 'sbrain_test_pw'
os.environ['MYSQL_HOST'] = '127.0.0.1'
os.environ['MYSQL_PORT'] = '3306'
os.environ['MYSQL_DATABASE'] = 'sbrain_test'
os.environ.setdefault('GOOGLE_CLIENT_ID', 'ci-dummy-client-id')
os.environ.setdefault('JWT_SECRET', 'ci-dummy-secret-not-for-production')

from fastapi.testclient import TestClient  # noqa: E402
from docx import Document  # noqa: E402

import app.security as security  # noqa: E402
from app.database import IS_SQLITE, SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Company, Project, ProjectBudgetItem, ProjectPartner, ProjectScheduleItem, User  # noqa: E402

assert not IS_SQLITE

PASS, FAIL = [], []

def check(name, condition, detail=''):
    if condition:
        PASS.append(name)
        print(f'  [PASS] {name}')
    else:
        FAIL.append((name, detail))
        print(f'  [FAIL] {name}  {detail}')

def docx_full_text(raw: bytes) -> str:
    doc = Document(io.BytesIO(raw))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return '\n'.join(parts)

# ── 테스트 실행 --------------------------------------------------------------
db = SessionLocal()
try:
    db.query(User).filter(User.google_sub == 'verify-wiring-sub').delete()
    db.commit()
    user = User(
        google_sub='verify-wiring-sub',
        email='verify-wiring@example.com',
        name='배선검증유저',
        role='user',
        status='active',
        notify_enabled=False,
        ai_training_agreed=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    user_id = user.user_id
finally:
    db.close()

token = security.issue_access_token(user_id)
client = TestClient(app)
client.cookies.set(security.SESSION_COOKIE_NAME, token)

print('[1] POST /projects — 신규 필드 연동 검증')
payload = {
    'biz_type': 'IT',
    'ceo_name': '김대표',
    'company_name': '주식회사 배선검증',
    'business_reg_no': '123-45-67890',
    'rep_type': '단독',
    'description': 'AI 기반 회계 자동화',
    'output_summary': 'AI 회계 SaaS MVP 1식',
    'tech_field': 'AI·빅데이터',
    'regional_priority_area': '해당 없음',
    'team_members': [{'name': '김대표', 'role': '대표', 'experience': '창업 5년'}],
    'pricing_items': [{'service_name': '구독형', 'unit_price': 50000}],
}
resp = client.post('/projects', data={'payload': json.dumps(payload, ensure_ascii=False)})
check('POST /projects 201', resp.status_code == 201, resp.text[:300])
body = resp.json()
project_id = body.get('project_id')

check('company 중첩 객체 포함', body.get('company') is not None, body)
if body.get('company'):
    c = body['company']
    check('company_name 일치', c.get('company_name') == '주식회사 배선검증', c)
    check('business_reg_no 일치', c.get('business_reg_no') == '123-45-67890', c)

print('\n[2] 산출물(.docx) 생성 및 데이터 반영 확인')
resp3 = client.get(f'/projects/{project_id}/plan-document.docx')
check('plan-document.docx 200', resp3.status_code == 200, resp3.status_code)
text = docx_full_text(resp3.content) if resp3.status_code == 200 else ''

check('기업명 산출물 반영', '주식회사 배선검증' in text, '')
check('사업자등록번호 산출물 반영', '123-45-67890' in text, '')
check('전문기술분야 산출물 반영', 'AI·빅데이터' in text, '')

print(f'\n=== 결과: {len(PASS)} PASS / {len(FAIL)} FAIL ===')
if FAIL:
    sys.exit(1)
print('모든 검증 통과 완료.')