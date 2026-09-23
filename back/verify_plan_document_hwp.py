"""[hwp 실제 내용 검증 스크립트, 2026-09-22] GET /projects/{id}/plan-document.hwp가
"200이 뜨고 용량이 크다"를 넘어서 실제로 올바른 내용을 담고 있는지 확인한다.

pytest의 test_plan_document_hwp(tests/test_plan_document_endpoint.py)는 상태코드·
content-type·바이트 수만 보는데, 그걸로는 아래를 못 잡는다:
  - 본문 4섹션(문제인식/실현가능성/성장전략/팀구성)이 실제로 " ◦ " 불릿 자리에 들어갔는지
    (app/hwp_export.py _BODY_INSERTS_BY_TEMPLATE)
  - 개인정보 마스킹 안내문구(파란 글씨)가 삭제됐는지(_PERSONAL_INFO_NOTICE_BY_TEMPLATE)
  - 협력기관 표 매핑이 정확한지(하드코딩 '-' 없이, status가 협력시기가 아니라 협업방안에)

이 스크립트는 rhwp export-markdown으로 실제 렌더 텍스트를 뽑아 이 세 가지를 자동으로
확인한다 — hwp_export.py나 _build_plan_document_data(routers/projects.py)를 건드릴
때마다 돌려서 회귀를 바로 잡아낸다.

실행 (back/ 에서):
    python verify_plan_document_hwp.py
RHWP_BIN(.env)이 실제 rhwp 실행 파일을 가리켜야 진짜로 검증한다 — 안 가리키면 건너뛰고
0으로 종료(팀 공용 CI 등 rhwp가 없는 환경 대응, test_plan_document_endpoint.py와 같은 원칙).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _REPO_ROOT)
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

os.environ.setdefault('DB_BACKEND', 'sqlite')
os.environ.setdefault('SQLITE_PATH', os.path.join(_REPO_ROOT, 'verify_plan_document_hwp.db'))
os.environ.setdefault('GOOGLE_CLIENT_ID', 'verify-dummy-client-id')
os.environ.setdefault('JWT_SECRET', 'verify-dummy-secret-not-for-production')

_sqlite_path = os.environ['SQLITE_PATH']
if os.path.exists(_sqlite_path):
    os.remove(_sqlite_path)

from fastapi.testclient import TestClient  # noqa: E402

import app.routers.auth as auth_router  # noqa: E402
import app.security as security  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.hwp_export import RHWP_BIN  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Notice  # noqa: E402

Base.metadata.create_all(bind=engine)

_RHWP_AVAILABLE = shutil.which(RHWP_BIN) is not None or os.path.isfile(RHWP_BIN)
if not _RHWP_AVAILABLE:
    print(f"RHWP_BIN({RHWP_BIN!r})을 못 찾음 — hwp 검증을 건너뜁니다(.env의 RHWP_BIN 확인).")
    sys.exit(0)

PASS, FAIL = [], []


def check(name: str, condition: bool, detail: str = '') -> None:
    if condition:
        PASS.append(name)
        print(f'  [PASS] {name}')
    else:
        FAIL.append((name, detail))
        print(f'  [FAIL] {name}  {detail}')


def login(client: TestClient, email: str, name: str) -> None:
    fake_sub = f'verify-hwp-{email}'
    security.verify_google_id_token = lambda id_token_str: {'sub': fake_sub, 'email': email, 'name': name}
    auth_router.verify_google_id_token = security.verify_google_id_token
    res = client.post('/auth/google', json={'id_token': 'dummy', 'aiTrainingAgreed': True, 'notifyAgreed': True})
    assert res.status_code == 200, f'로그인 실패: {res.text}'


def export_markdown(hwp_bytes: bytes) -> str:
    """hwp 바이트를 임시 파일로 저장 -> rhwp export-markdown -> 모든 페이지 텍스트를
    합쳐서 돌려준다."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        hwp_path = os.path.join(tmp_dir, 'doc.hwp')
        with open(hwp_path, 'wb') as f:
            f.write(hwp_bytes)
        out_dir = os.path.join(tmp_dir, 'out')
        os.makedirs(out_dir)
        result = subprocess.run(
            [RHWP_BIN, 'export-markdown', hwp_path, '-o', out_dir],
            capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=tmp_dir,
        )
        assert result.returncode == 0, f'rhwp export-markdown 실패: {result.stderr or result.stdout}'
        pages = sorted(f for f in os.listdir(out_dir) if f.endswith('.md'))
        assert pages, f'export-markdown이 .md 파일을 하나도 안 만듦: {os.listdir(out_dir)}'
        parts = []
        for page in pages:
            with open(os.path.join(out_dir, page), encoding='utf-8') as f:
                parts.append(f.read())
        return '\n'.join(parts)


def verify_template(client: TestClient, *, label: str, applicant_type: str | None) -> None:
    print(f'\n=== {label} ===')
    notice_id = f'NOTICE-VERIFY-HWP-{label}'
    notice = Notice(
        notice_id=notice_id, source='k-startup', title=f'{label} 검증용 공고',
        organizer='창업진흥원', recruitment_status='open', url=f'https://example.com/{notice_id}',
    )
    db = SessionLocal()
    db.add(notice)
    db.commit()
    db.close()

    payload = {
        'applicant_type': applicant_type, 'biz_type': '법인', 'ceo_name': '김서준',
        'founded_at': '2023-05-01' if applicant_type != 'preliminary' else None,
        'description': 'AI 기반 동네 헬스장 통합 예약·회원관리 서비스',
        'team_members': [{'name': '김서준', 'role': '대표', 'experience': '피트니스 센터 4년 운영'}],
        'pricing_items': [{'service_name': '월 구독료', 'unit_price': 35000}],
        'partners': [{'name': '○○결제', 'status': '협력 중'}],
    }
    r = client.post('/projects', data={'payload': json.dumps(payload)})
    check(f'[{label}] POST /projects 201', r.status_code == 201, r.text[:300])
    project_id = r.json()['project_id']

    r = client.post(f'/projects/{project_id}/generate', json={'notice_id': notice_id})
    check(f'[{label}] POST /generate 200', r.status_code == 200, r.text[:300])

    r = client.get(f'/projects/{project_id}/plan-document.hwp')
    check(f'[{label}] GET plan-document.hwp 200', r.status_code == 200, r.text[:300])
    if r.status_code != 200:
        return
    check(f'[{label}] content-type', r.headers.get('content-type') == 'application/haansofthwp', r.headers.get('content-type'))
    check(f'[{label}] 용량 1000바이트 이상', len(r.content) > 1000, len(r.content))

    text = export_markdown(r.content)

    # 본문 4섹션 — seed_dummy_pipeline.py가 1-1/2-1/3-1 각각에 서로 다른 더미 문장을
    # 심어두므로(4-1은 없음, 팀구성은 team_text로 기계적으로 채움), 세 문장이 전부
    # " ◦ " 불릿 자리에 들어갔는지 각각 확인한다 — 하나만 확인하면 나머지가 비어도
    # 못 잡는다.
    check(f'[{label}] 문제인식 본문 삽입', '목표 고객이 겪는 문제를 서술하는 구간' in text, '')
    check(f'[{label}] 실현가능성 본문 삽입', '팀 역량과 실행 계획을 서술하는 구간' in text, '')
    check(f'[{label}] 성장전략 본문 삽입', '시장 진입 및 확장 전략을 서술하는 구간' in text, '')
    check(f'[{label}] 팀구성 본문 삽입(김서준)', '김서준' in text and '피트니스 센터 4년 운영' in text, '')

    # 개인정보 마스킹 안내문구 — 삭제 대상인데 남아있으면 실패.
    check(f'[{label}] 개인정보 안내문구 삭제됨', '성명, 성별, 생년월일' not in text, '문구가 여전히 남아있음')

    # 협력기관 매핑 — 이름은 있어야 하고, 하드코딩 '-'가 아니라 자리표시자(○○)여야 하며,
    # status('협력 중')는 어딘가에 반영돼야 한다(협력시기 자리에 status를 넣던 예전 버그 재발 방지).
    check(f'[{label}] 협력기관명 반영', '○○결제' in text, '')
    check(f'[{label}] 협력기관 status 반영', '협력 중' in text, '')


client = TestClient(app)
login(client, 'verify-hwp@example.com', 'hwp검증')

verify_template(client, label='초기창업패키지', applicant_type=None)
verify_template(client, label='예비창업패키지', applicant_type='preliminary')

print(f'\n=== 결과: {len(PASS)} PASS / {len(FAIL)} FAIL ===')
if FAIL:
    sys.exit(1)
print('모든 검증 통과 완료.')
