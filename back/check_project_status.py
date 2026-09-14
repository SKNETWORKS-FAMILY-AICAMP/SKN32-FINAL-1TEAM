"""create_test_project.py로 만든 project_id의 GET /projects/{id}/status 결과를
터미널에서 바로 확인한다.

Swagger(/docs)나 브라우저에서 직접 GET /projects/{id}/status를 호출하면 "로그인이
필요합니다"(401)가 뜨는 게 정상이다 — create_test_project.py의 가짜 로그인은 그
스크립트를 실행한 TestClient 안에서만 유효한 세션 쿠키라서, 실제 브라우저에는 아무
쿠키도 안 남는다(둘은 완전히 다른 프로세스). 진짜 구글 로그인이 아직 안 되는 동안
브라우저 없이 상태를 확인하려면 이 스크립트처럼 같은 방식(monkeypatch 가짜 로그인)으로
한 번에 로그인 + 조회까지 같이 해야 한다.

실행:
    python check_project_status.py 2
    python check_project_status.py 2 --email test2@example.com   # 다른 계정으로 만든 프로젝트면

--email은 그 project_id를 만들 때 create_test_project.py에 준 --email과 같아야 한다
(다르면 "본인 프로젝트가 아님" 취급돼서 404가 난다 — 소유권 체크가 실제로 동작하는
것도 이 스크립트로 확인 가능).
"""
import argparse
import os
import sys

# 이 스크립트는 repo 루트(back/, app/ 패키지가 바로 옆에 있는 위치)에서
# `python check_project_status.py <project_id>`로 실행하는 걸 전제로 한다.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault('DB_BACKEND', 'sqlite')
os.environ.setdefault('GOOGLE_CLIENT_ID', 'ci-dummy-client-id')
os.environ.setdefault('JWT_SECRET', 'ci-dummy-secret-not-for-production')

import app.security as security  # noqa: E402
from app.main import app  # noqa: E402

import app.routers.auth as auth_router  # noqa: E402
from app.database import IS_SQLITE  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def main() -> None:
    if not IS_SQLITE:
        print(
            '[check_project_status] DB_BACKEND가 sqlite가 아니다 — 팀 공유 AWS MySQL로 보인다.\n'
            '                       가짜 로그인을 여기 쓰면 안 되니 중단한다.',
            file=sys.stderr,
        )
        raise SystemExit(1)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('project_id', type=int)
    parser.add_argument('--email', default='test@example.com', help='create_test_project.py에 줬던 --email과 동일하게')
    parser.add_argument('--name', default='테스트유저')
    args = parser.parse_args()

    # create_test_project.py와 완전히 같은 규칙(email -> fake_sub)으로 로그인해야
    # 같은 계정(=같은 company)으로 인식돼서 그 project_id에 접근할 수 있다.
    fake_sub = f'test-sub-{args.email}'
    security.verify_google_id_token = lambda id_token_str: {
        'sub': fake_sub, 'email': args.email, 'name': args.name,
    }
    auth_router.verify_google_id_token = security.verify_google_id_token

    client = TestClient(app)
    login_res = client.post('/auth/google', json={
        'id_token': 'dummy', 'aiTrainingAgreed': True, 'notifyAgreed': True,
    })
    if login_res.status_code != 200:
        print(f'로그인 실패: {login_res.status_code} {login_res.text}', file=sys.stderr)
        raise SystemExit(1)

    res = client.get(f'/projects/{args.project_id}/status')
    print(f'GET /projects/{args.project_id}/status -> {res.status_code}')
    print(res.text)
    if res.status_code == 404:
        print(
            '\n(참고) 404면 두 가지 중 하나: project_id가 실제로 없거나,'
            ' --email이 그 프로젝트를 만든 계정과 달라서 "본인 프로젝트 아님"으로 처리된 것.',
            file=sys.stderr,
        )


if __name__ == '__main__':
    main()