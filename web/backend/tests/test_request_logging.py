"""app/request_logging.py RequestLoggingMiddleware — pytest 버전.

실제 web_logger(back/logs/web-<오늘날짜>.log, gitignore 대상)에 쓰는 통합 테스트다 —
UPLOAD_DIR처럼 이 프로젝트에서 이미 테스트 중 디스크에 실제로 쓰는 것과 같은 방식이라
따로 격리하지 않는다. 매 테스트 앞뒤로 오늘자 로그 파일에서 "그 테스트가 만든 구간"만
확인한다(파일 전체 길이를 커서로 기억해뒀다가 그 이후만 읽음)."""
import datetime
import json
import os

from app.logging_config import LOG_DIR

_TODAY_LOG = os.path.join(LOG_DIR, f'web-{datetime.date.today().isoformat()}.log')


def _tail_since(offset: int) -> str:
    if not os.path.exists(_TODAY_LOG):
        return ''
    with open(_TODAY_LOG, encoding='utf-8') as f:
        f.seek(offset)
        return f.read()


def _log_offset() -> int:
    return os.path.getsize(_TODAY_LOG) if os.path.exists(_TODAY_LOG) else 0


def test_request_logs_start_and_end_with_route_template(client):
    offset = _log_offset()
    r = client.get('/projects/999999')  # 미로그인 -> 401, project_id는 숫자 그대로 URL에 실림
    assert r.status_code == 401

    logged = _tail_since(offset)
    assert 'GET /projects/999999 start' in logged
    assert '999999' not in logged.split('start')[1], '끝 로그는 실제 경로가 아니라 라우트 템플릿을 써야 함'
    assert 'GET /projects/{project_id} end' in logged
    assert 'status=401' in logged
    assert 'result=fail' in logged


def test_failed_request_logs_at_warning_level(client):
    offset = _log_offset()
    client.get('/projects/999999')
    logged = _tail_since(offset)
    end_line = next(line for line in logged.splitlines() if ' end ' in line)
    assert '| WARNING' in end_line, f'4xx는 WARNING 레벨이어야 함: {end_line}'


def test_successful_request_logs_at_info_level(client):
    offset = _log_offset()
    r = client.get('/health')
    assert r.status_code == 200
    logged = _tail_since(offset)
    end_line = next(line for line in logged.splitlines() if ' end ' in line)
    assert '| INFO' in end_line
    assert 'status=200' in end_line
    assert 'result=success' in end_line


def test_log_does_not_leak_personal_info(authed_client):
    """로그인한 사용자가 이름·설명 등 개인정보성 값을 담은 요청을 보내도, 로그 줄엔
    request_id/user_id/method/path/상태코드만 남고 그 값 자체는 안 남아야 한다."""
    offset = _log_offset()
    payload = {
        'biz_type': '개인', 'ceo_name': '아주희귀한이름테스트12345',
        'founded_at': None, 'description': '아주희귀한사업설명테스트67890',
        'team_members': [], 'pricing_items': [],
    }
    r = authed_client.post('/projects', data={'payload': json.dumps(payload)})
    assert r.status_code == 201, r.text

    logged = _tail_since(offset)
    assert '아주희귀한이름테스트12345' not in logged
    assert '아주희귀한사업설명테스트67890' not in logged
    assert 'POST /projects end' in logged
    assert 'status=201' in logged


def test_authenticated_request_logs_real_user_id_not_anon(authed_client):
    offset = _log_offset()
    r = authed_client.get('/auth/me')
    assert r.status_code == 200
    user_id = r.json()['user_id']

    logged = _tail_since(offset)
    assert f'user_id={user_id}' in logged
    assert 'user_id=anon' not in logged


def test_unauthenticated_request_logs_anon_user_id(client):
    offset = _log_offset()
    client.get('/projects/999999')
    logged = _tail_since(offset)
    assert 'user_id=anon' in logged
