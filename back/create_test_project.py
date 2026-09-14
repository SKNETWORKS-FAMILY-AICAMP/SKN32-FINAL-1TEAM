"""구글 로그인 없이(가짜 로그인) 테스트용 프로젝트를 하나 만들어서 project_id를 출력한다.

login_test.html로 실제 구글 로그인을 테스트하는 게 막혀 있을 때도(Google Cloud Console
승인된 origin 설정 문제 등), seed_dummy_pipeline.py나 GET /projects/{id}/status 테스트는
project_id만 있으면 되니까, verify_status_endpoint.py와 똑같은 방식(구글 id_token 검증
함수만 monkeypatch)으로 로그인 -> POST /projects까지 실제 코드 경로 그대로 태워서
project_id를 받아온다. FastAPI TestClient로 인메모리에서 앱을 직접 호출하기 때문에
uvicorn 서버가 켜져 있을 필요는 없다.

verify_*.py 스크립트들과 달리 이 스크립트는 dev.db를 지우지 않는다 — 이미 만들어둔 더미
공고(seed_dummy_notices.py) 등을 그대로 유지한 채 프로젝트만 하나 추가하는 용도라서다.
나중에 그 project_id로 uvicorn 서버(Swagger 등)에서 상태를 확인하려면, DB_BACKEND=sqlite로
같은 dev.db(repo 루트)를 보고 있으면 된다 — 기본 경로 그대로 두면 자동으로 같은 파일이다.

실행:
    python create_test_project.py
    python create_test_project.py --email test2@example.com --description "다른 아이디어"

같은 --email로 다시 실행하면 같은 계정으로 로그인된다. 그 계정에 이미 진행 중인
프로젝트(매칭)가 있으면 POST /projects가 409를 내는 게 정상 동작(동시 실행 1건 제한)이니,
새 프로젝트를 또 만들고 싶으면 --email로 다른 이메일을 주면 된다.
"""
import argparse
import json
import os
import sys

# 이 스크립트는 repo 루트(back/, app/ 패키지가 바로 옆에 있는 위치)에서
# `python create_test_project.py`로 실행하는 걸 전제로 한다.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault('DB_BACKEND', 'sqlite')
os.environ.setdefault('GOOGLE_CLIENT_ID', 'ci-dummy-client-id')
os.environ.setdefault('JWT_SECRET', 'ci-dummy-secret-not-for-production')

from fastapi.testclient import TestClient  # noqa: E402

import app.routers.auth as auth_router  # noqa: E402
import app.security as security  # noqa: E402
from app.database import IS_SQLITE  # noqa: E402
from app.main import app  # noqa: E402


def main() -> None:
    if not IS_SQLITE:
        print(
            '[create_test_project] DB_BACKEND가 sqlite가 아니다 — 팀 공유 AWS MySQL로 보인다.\n'
            '                      여기에 가짜 로그인/더미 프로젝트를 만들면 안 되니 중단한다.\n'
            '                      .env에 DB_BACKEND=sqlite 를 설정하고 다시 실행하세요.',
            file=sys.stderr,
        )
        raise SystemExit(1)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--email', default='test@example.com', help='가짜 로그인에 쓸 이메일(계정 구분용)')
    parser.add_argument('--name', default='테스트유저')
    parser.add_argument('--description', default='더미 파이프라인 테스트용 프로젝트')
    parser.add_argument('--region', default='서울')
    parser.add_argument('--industry', default='IT')
    args = parser.parse_args()

    # google-auth 검증 함수만 가짜로 바꾼다 — 실제 구글 서버에 요청 안 보내고 바로 통과시킨다.
    # google_sub을 email 기준으로 만들어서, 같은 --email로 다시 실행하면 같은 계정으로
    # 로그인된다(users.email/google_sub UNIQUE 제약과 자연스럽게 맞물림).
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
    print(f'로그인 성공 ({args.email})')

    payload = {
        'start_type': '온라인',
        'biz_type': 'AI 서비스',
        'ceo_name': args.name,
        'description': args.description,
        'notify_region': args.region,
        'notify_industry': args.industry,
        'team_members': [],
        'pricing_items': [{'service_name': '기본 서비스', 'unit_price': 1000000}],
    }
    # multipart/form-data 로 보내야 한다 — ProjectCreateRequest는 'payload' 폼 필드에
    # JSON 문자열로 담겨 온다(app/routers/projects.py의 create_project 참고). 파일 첨부는
    # 이 스크립트에서는 생략(files 필드 자체를 안 보내면 빈 리스트로 처리됨).
    create_res = client.post('/projects', data={'payload': json.dumps(payload)})
    if create_res.status_code != 201:
        print(f'프로젝트 생성 실패: {create_res.status_code} {create_res.text}', file=sys.stderr)
        raise SystemExit(1)

    project = create_res.json()
    project_id = project['project_id']
    print(f'프로젝트 생성 완료 — project_id={project_id}')
    print()
    print('이제 이 project_id로 더미 파이프라인을 채워 넣으면 됨:')
    print(f'  python seed_dummy_pipeline.py {project_id}')
    print()
    print('그리고 서버를 켜서(uvicorn app.main:app --reload --port 8000)')
    print(f'  GET http://127.0.0.1:8000/projects/{project_id}/status')
    print('로 확인하면 됨. (Swagger: http://127.0.0.1:8000/docs)')


if __name__ == '__main__':
    main()