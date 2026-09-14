"""GET /projects/{id}/status 실제 왕복 검증.

verify_resume_cases.py에서는 아직 엔드포인트가 없어 DB를 직접 조회하는 함수
(detect_resume_screen)로 이어하기 8케이스 판별 로직 자체를 검증했다. 이 스크립트는
그 로직이 실제로 라우터에 옮겨진 뒤, TestClient로 진짜 HTTP 요청을 보내서
1) 8케이스가 여전히 올바른 화면 번호로 내려오는지,
2) 소유권 체크(다른 사용자 401/404)와 존재하지 않는 프로젝트 404가 같이 동작하는지
를 같이 확인한다. google-auth 검증 함수만 monkeypatch로 우회하고 나머지는 실제 코드
경로(로그인 -> 프로젝트 생성 -> 매칭 상태 조작 -> 상태 조회)를 그대로 탄다."""
import json
import os
import shutil
import sys

# 이 스크립트는 repo 루트(back/, app/ 패키지가 바로 옆에 있는 위치)에서
# `python verify_status_endpoint.py`로 실행하는 걸 전제로 한다.
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _REPO_ROOT)

os.environ.setdefault('DB_BACKEND', 'sqlite')
os.environ.setdefault('GOOGLE_CLIENT_ID', 'ci-dummy-client-id')
os.environ.setdefault('JWT_SECRET', 'ci-dummy-secret-not-for-production')

# dev.db가 예전 스키마로 이미 있으면 create_all()이 기존 테이블을 안 건드리고
# 넘어가버리니 매번 지우고 새로 만든다 (uploads 폴더도 이전 실행의 더미 파일이
# 남아있지 않도록 같이 비운다).
_DEV_DB = os.path.join(_REPO_ROOT, 'dev.db')
_UPLOAD_DIR = os.path.join(_REPO_ROOT, 'uploads')
if os.path.exists(_DEV_DB):
    os.remove(_DEV_DB)
if os.path.exists(_UPLOAD_DIR):
    shutil.rmtree(_UPLOAD_DIR)

import app.security as security  # noqa: E402
from app.main import app  # noqa: E402

security.verify_google_id_token = lambda id_token_str: {
    'sub': 'google-sub-abc', 'email': 'hjwon2001@gmail.com', 'name': '하정원',
}
import app.routers.auth as auth_router  # noqa: E402

auth_router.verify_google_id_token = security.verify_google_id_token

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

import app.database as appdb  # noqa: E402
from app import pipeline_stages as ps  # noqa: E402
from app.models import EligibilityCheck, MatchResult, Notice  # noqa: E402

PAYLOAD = {
    'start_type': '온라인',
    'biz_type': 'AI 서비스',
    'ceo_name': '하정원',
    'description': '이어하기 상태 조회 엔드포인트 검증용 프로젝트',
    'notify_region': '서울',
    'notify_industry': 'IT',
    'team_members': [],
    'pricing_items': [],
}

db = appdb.SessionLocal()


def seed_notice_once():
    """공고를 한 번만 만든다. db.get()의 identity-map 조회에 기대지 않고 insert-then-catch로
    처리한다 — TestClient 요청들이 앱 쪽의 별도 세션으로 이 스크립트의 세션과 나란히
    커밋을 반복하다 보니, 매번 새 쿼리로 존재 여부를 다시 확인하는 편이 더 안전하다."""
    try:
        db.add(Notice(
            notice_id='kstartup:STATUS_EP_TEST', source='kstartup', title='상태 조회 테스트용 공고',
            recruitment_status='open',
        ))
        db.commit()
    except IntegrityError:
        db.rollback()  # 이미 존재 — 그대로 재사용


def set_match(project_id: int, stage: str | None, progress_percent: int | None = None) -> int:
    """해당 프로젝트에 매칭을 하나 만들고(기존 매칭이 있으면 그대로 두지 않고 새로 추가 —
    상태 조회는 match_id desc로 최신 것만 보므로 새로 추가해도 최신 것이 반영됨) match_id를
    돌려준다."""
    seed_notice_once()
    m = MatchResult(project_id=project_id, notice_id='kstartup:STATUS_EP_TEST', status='in_progress',
                     stage=stage, progress_percent=progress_percent)
    db.add(m)
    db.commit()
    db.add(EligibilityCheck(match_id=m.match_id, passed=True))
    db.commit()
    return m.match_id


with TestClient(app) as client:
    login = client.post('/auth/google', json={'id_token': 'dummy'})
    assert login.status_code == 200, login.text
    print('0) 로그인 -> 200 OK')

    # ---- 존재하지 않는 프로젝트 ----
    r = client.get('/projects/999999/status')
    assert r.status_code == 404, r.text
    print('1) 존재하지 않는 프로젝트 -> 404 OK')

    # ---- 케이스 ①: 프로젝트는 있지만 매칭 자체가 없음 (공고 선택 전) ----
    r = client.post('/projects', data={'payload': json.dumps(PAYLOAD)}, files=[])
    assert r.status_code == 201, r.text
    project_no_match = r.json()['project_id']
    r = client.get(f'/projects/{project_no_match}/status')
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {
        'project_id': project_no_match, 'screen': ps.NO_MATCH_SCREEN,
        'stage': None, 'progress_percent': None, 'match_id': None, 'match_status': None,
    }, body
    print(f'2) ① 매칭 없음 -> 200 OK, screen={body["screen"]} (기대: {ps.NO_MATCH_SCREEN})')

    # ---- 8케이스 중 매칭이 있는 나머지 케이스들: stage/progress_percent -> screen 매핑 확인 ----
    CASES = [
        ('② 자격요건 통과 후 작성 전', ps.STAGE_PLAN_WRITING, 0, 5),
        ('③ 계획서 작성 중 (진행률 이어받기)', ps.STAGE_PLAN_WRITING, 45, 5),
        ('④ 문서 평가 판단 대기', ps.STAGE_PLAN_REVIEW_PENDING, None, 6),
        ('⑤ 프로토타입 제작 중', ps.STAGE_PROTOTYPE_BUILDING, 60, 7),
        ('⑥ 산출물 확인 중', ps.STAGE_ARTIFACT_REVIEW, None, 8),
        ('⑦ 종합 평가 판단 대기', ps.STAGE_FINAL_REVIEW_PENDING, None, 9),
        ('⑧ 검수 이후', ps.STAGE_DONE, None, 11),
    ]
    all_ok = True
    for label, stage, progress, expected_screen in CASES:
        r = client.post('/projects', data={'payload': json.dumps(PAYLOAD)}, files=[])
        assert r.status_code == 201, r.text
        pid = r.json()['project_id']
        match_id = set_match(pid, stage, progress)

        r = client.get(f'/projects/{pid}/status')
        assert r.status_code == 200, r.text
        body = r.json()
        ok = (
            body['screen'] == expected_screen and body['stage'] == stage
            and body['progress_percent'] == progress and body['match_id'] == match_id
            and body['match_status'] == 'in_progress'
        )
        all_ok = all_ok and ok
        mark = 'OK' if ok else 'FAIL'
        print(f'   [{mark}] {label:32s} -> screen={body["screen"]} (기대 {expected_screen}), '
              f'progress_percent={body["progress_percent"]}')

        # 이 매칭을 진행 중(in_progress)에서 빼줘야 다음 케이스의 POST /projects가
        # 동시 실행 1건 제한(409)에 안 걸린다 — 상태 조회 엔드포인트 자체와는 무관한
        # 테스트 준비 절차라서 매칭이 끝난 것처럼(archived) 표시만 해둔다.
        m = db.get(MatchResult, match_id)
        m.status = 'archived'
        db.commit()
    assert all_ok, '위 케이스 중 FAIL이 있음'
    print('3) 매칭 있는 7케이스 전부 기대한 화면/진행률로 정확히 내려옴')

    # ---- 마이그레이션 이전 데이터 등 stage가 NULL인 경우 -> screen도 None ----
    r = client.post('/projects', data={'payload': json.dumps(PAYLOAD)}, files=[])
    pid_null_stage = r.json()['project_id']
    set_match(pid_null_stage, stage=None)
    r = client.get(f'/projects/{pid_null_stage}/status')
    body = r.json()
    assert body['screen'] is None and body['stage'] is None, body
    print('4) stage=NULL(마이그레이션 이전 데이터 등) -> screen=None으로 정직하게 내려옴 확인')

    # ---- 소유권 체크: 다른 사용자는 이 프로젝트의 상태를 못 봄 ----
    auth_router.verify_google_id_token = lambda id_token_str: {
        'sub': 'google-sub-other', 'email': 'other@example.com', 'name': '다른사람',
    }
    security.verify_google_id_token = auth_router.verify_google_id_token
    client.cookies.clear()
    other_login = client.post('/auth/google', json={'id_token': 'dummy'})
    assert other_login.status_code == 200
    r = client.get(f'/projects/{project_no_match}/status')
    assert r.status_code == 404, '다른 사람 프로젝트 상태가 보이면 안 됨'
    print('5) 다른 사용자 계정으로 상태 조회 -> 404 OK (소유권 체크 확인)')

db.close()
print('ALL OK')