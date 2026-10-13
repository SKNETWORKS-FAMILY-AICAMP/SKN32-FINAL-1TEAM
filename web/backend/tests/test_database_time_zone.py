"""웹의 DB 연결은 세션 시간대를 UTC로 맞춘다 (재희 님 확인: 로컬 DB가 한국 시간이면 프로젝트 생성 시각이 9시간 앞서 나옴).

`server_default=func.now()` · `DEFAULT CURRENT_TIMESTAMP(6)`로 채워지는 시각(프로젝트 생성 시각 등)은 DB 서버의 시간대를 따른다. 응답은 시간대 없는 DB 시각을
UTC로 보고 Z를 붙이므로(schemas._to_utc_z), 서버가 한국 시간이면 같은 시각이 9시간 어긋났다. 연결마다 `SET time_zone = '+00:00'`을 실행하면 서버 설정과
상관없이 UTC가 채워진다. 실제 한국 시간 서버에서 확인한 것은 testing_guide.md에 적었다(단위 테스트는 SQLite라 서버 시간대를 흉내 낼 수 없다).

실행:
    pytest tests/test_database_time_zone.py -v
"""
from app import database


def test_mysql_connections_set_the_session_time_zone_to_utc():
    assert database._connect_args(is_sqlite=False) == {'init_command': "SET time_zone = '+00:00'"}


def test_sqlite_connections_keep_their_own_settings():
    assert database._connect_args(is_sqlite=True) == {'check_same_thread': False}
