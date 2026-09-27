"""오늘(2026-09-22) 작업 확인용 — 구글 로그인 없이 실제 코드 경로(로그인 monkeypatch만)로
1) 협력기관/직업 등 ProjectPlanInput 필드가 실제로 저장·복원되는지
2) 사업계획서 .docx/.hwp가 그 값을 반영해서 실제로 만들어지는지
를 확인한다. 값은 실행할 때 직접 입력받는다(Enter만 누르면 괄호 안 기본값 사용).
.hwp는 RHWP_BIN(.env)이 실제 rhwp 실행 파일을 가리켜야 진짜로 생성된다 — 안 그러면
500이 나는 게 정상이고, 이 경우 hwp는 건너뛰고 나머지만 확인한다.

실행법 (back/ 에서):
    python verify_today.py
결과 파일은 back/verify_output/ 에 저장되고, 직접 한글/워드에서 열어서 눈으로 확인할 수 있다.
"""
import json
import os
import shutil
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tests/ -> back/
sys.path.insert(0, _REPO_ROOT)

# Windows 콘솔 기본 코드페이지(cp949)로는 em-dash 등 일부 문자를 못 찍어서 죽는다 —
# 콘솔 출력을 UTF-8로 강제한다.
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

os.environ.setdefault('DB_BACKEND', 'sqlite')
os.environ.setdefault('GOOGLE_CLIENT_ID', 'verify-dummy-client-id')
os.environ.setdefault('JWT_SECRET', 'verify-dummy-secret-not-for-production')

_DEV_DB = os.path.join(_REPO_ROOT, 'dev.db')
_UPLOAD_DIR = os.path.join(_REPO_ROOT, 'uploads')
_OUT_DIR = os.path.join(_REPO_ROOT, 'verify_output')
if os.path.exists(_DEV_DB):
    os.remove(_DEV_DB)
if os.path.exists(_UPLOAD_DIR):
    shutil.rmtree(_UPLOAD_DIR)
os.makedirs(_OUT_DIR, exist_ok=True)


def ask(prompt, default):
    v = input(f'{prompt} [{default}]: ').strip()
    return v or default


def ask_yn(prompt, default_yes):
    d = 'Y/n' if default_yes else 'y/N'
    v = input(f'{prompt} ({d}): ').strip().lower()
    if not v:
        return default_yes
    return v.startswith('y')


print('=== 사업계획서 생성 확인 — 값을 입력해 주세요(Enter만 누르면 기본값) ===\n')

print('신청자 유형: 1) 초기창업패키지(개인/법인)  2) 예비창업자')
type_choice = ask('선택', '1')
applicant_type = 'preliminary' if type_choice.strip() == '2' else 'individual'
is_preliminary = applicant_type == 'preliminary'

description = ask('아이디어 설명', 'AI 기반 동네 헬스장 통합 예약 서비스')
ceo_name = ask('대표자 이름', '박테스트')
region_sido = ask('지역(시/도)', '서울특별시')
region_sigungu = ask('지역(시/군/구)', '강남구')
main_industry = ask('주업종', '정보·통신')
dev_start_month = ask('개발 시작월(YYYY-MM)', '2026-10')
dev_end_month = ask('개발 종료월(YYYY-MM)', '2027-03')

occupation = None
if is_preliminary:
    occupation = ask('직업(예비창업자 전용, 직장명 기재 불가)', '대학생')
    budget_scale_manwon = int(ask('예산 규모(만원, 0~2000)', '1500'))
else:
    founded_at = ask('설립일(YYYY-MM-DD)', '2024-01-01')

has_hires = ask_yn('채용 계획이 있나요', True)
hires = []
if has_hires:
    job = ask('  채용할 직무', '백엔드 개발')
    headcount = ask('  인원', '1명')
    hires = [{'job': job, 'headcount': headcount, 'required_skill': '', 'hire_month': dev_start_month}]

has_partners = ask_yn('협력 기관이 있나요', True)
partners = []
if has_partners:
    name = ask('  협력 기관명 · 협력 내용', '○○대학 · 실증 지원')
    status = ask('  상태(협력 중/예정)', '협력 중')
    partners = [{'name': name, 'status': status}]

payload = {
    'applicant_type': applicant_type, 'biz_type': '개인', 'ceo_name': ceo_name,
    'description': description,
    'team_members': [{'name': ceo_name, 'role': '대표', 'experience': '4년'}],
    'pricing_items': [{'service_name': '서버 호스팅', 'unit_price': 50000}],
    'region_sido': region_sido, 'region_sigungu': region_sigungu,
    'main_industry': main_industry,
    'dev_start_month': dev_start_month, 'dev_end_month': dev_end_month,
    'no_hires': not has_hires, 'hires': hires,
    'no_equipment': True, 'equipment': [],
    'no_partners': not has_partners, 'partners': partners,
}
if is_preliminary:
    payload['occupation'] = occupation
    payload['budget_scale_manwon'] = budget_scale_manwon
else:
    payload['founded_at'] = founded_at
    payload['self_funding_allowed'] = True
    payload['self_cash_limit'] = 500
    payload['self_in_kind_resources'] = '사무공간 무상 제공'

print('\n입력 완료 — 실행합니다...\n')

import app.security as security  # noqa: E402
from app.main import app  # noqa: E402
from app.hwp_export import RHWP_BIN  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(app)
security.verify_google_id_token = lambda id_token_str: {
    'sub': 'verify-today-sub', 'email': 'verify-today@example.com', 'name': '검증용',
}
import app.routers.auth as auth_router  # noqa: E402
auth_router.verify_google_id_token = security.verify_google_id_token

r = client.post('/auth/google', json={'id_token': 'dummy', 'aiTrainingAgreed': True, 'notifyAgreed': True})
assert r.status_code == 200, f'로그인 실패: {r.text}'
print('[1/4] 로그인 OK')

r = client.post('/projects', data={'payload': json.dumps(payload)})
assert r.status_code == 201, f'프로젝트 생성 실패: {r.text}'
project_id = r.json()['project_id']
print(f'[2/4] 프로젝트 생성 OK (project_id={project_id})')

plan_input = client.get(f'/projects/{project_id}').json()['plan_input']
print(f'[3/4] 저장된 값 확인:')
for key in ('region_sido', 'main_industry', 'dev_start_month', 'dev_end_month', 'hires', 'partners', 'occupation'):
    if key in plan_input:
        print(f'  - {key}: {plan_input[key]}')

label = '예비' if is_preliminary else '초기'

r = client.get(f'/projects/{project_id}/plan-document.docx')
assert r.status_code == 200, f'docx 생성 실패: {r.text}'
docx_path = os.path.join(_OUT_DIR, f'사업계획서_{label}.docx')
with open(docx_path, 'wb') as f:
    f.write(r.content)
print(f'[4/4] docx 저장: {docx_path}')

r = client.get(f'/projects/{project_id}/plan-document.hwp')
if r.status_code == 200:
    hwp_path = os.path.join(_OUT_DIR, f'사업계획서_{label}.hwp')
    with open(hwp_path, 'wb') as f:
        f.write(r.content)
    print(f'      hwp 저장: {hwp_path}  <- 한글에서 직접 열어서 확인')
else:
    print(f'      hwp 생성 안 됨(RHWP_BIN={RHWP_BIN!r}) — {r.json().get("detail")}')

print('\n완료.')
