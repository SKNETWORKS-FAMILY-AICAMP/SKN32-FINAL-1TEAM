"""app/logging_config.py의 DailySizeRotatingFileHandler — pytest 버전.

팀 로깅 정책(로그는 DB엔 안 남기고 파일로만, 일자별 관리 + 용량 초과 시 회전 + 3일 지나면
삭제) 중 회전·보관 로직만 tmp_path에서 격리해 검증한다 — 실제 앱 로거(web_logger)는 건드리지
않는다."""
import datetime
import logging

from app.logging_config import DailySizeRotatingFileHandler


def _make_record(msg: str) -> logging.LogRecord:
    return logging.LogRecord(
        name='test', level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=None,
    )


def test_writes_to_todays_dated_file(tmp_path):
    handler = DailySizeRotatingFileHandler(str(tmp_path), base_name='web')
    handler.setFormatter(logging.Formatter('%(message)s'))
    handler.emit(_make_record('hello'))
    handler.close()

    today = datetime.date.today().isoformat()
    expected = tmp_path / f'web-{today}.log'
    assert expected.exists()
    assert expected.read_text(encoding='utf-8').strip() == 'hello'


def test_size_overflow_rolls_to_next_sequence(tmp_path):
    handler = DailySizeRotatingFileHandler(str(tmp_path), base_name='web', max_bytes=10)
    handler.setFormatter(logging.Formatter('%(message)s'))
    handler.emit(_make_record('첫 줄이 10바이트를 넘김'))  # 파일1을 채움
    handler.emit(_make_record('두 번째 줄'))  # 파일1이 이미 넘었으니 파일2로 넘어가야 함
    handler.close()

    today = datetime.date.today().isoformat()
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == [f'web-{today}.2.log', f'web-{today}.log'], files
    assert '첫 줄' in (tmp_path / f'web-{today}.log').read_text(encoding='utf-8')
    assert '두 번째 줄' in (tmp_path / f'web-{today}.2.log').read_text(encoding='utf-8')


def test_retention_cleanup_is_disabled_by_default(tmp_path):
    """[2026-09-23] "3일 지나면 삭제"는 구현은 돼 있지만 지금 당장은 끄기로 함 —
    retention_days를 안 주면(기본값 0) 아무리 오래된 파일이 있어도 안 지워야 한다."""
    handler = DailySizeRotatingFileHandler(str(tmp_path), base_name='web')  # retention_days 생략
    handler.setFormatter(logging.Formatter('%(message)s'))

    ancient_date = datetime.date.today() - datetime.timedelta(days=365)
    ancient_path = tmp_path / f'web-{ancient_date.isoformat()}.log'
    ancient_path.write_text('아주 오래된 로그', encoding='utf-8')

    handler.emit(_make_record('오늘 로그'))
    handler.close()

    assert ancient_path.exists(), '기본값(비활성) 상태에서는 아무리 오래된 파일도 지우면 안 됨'


def test_old_files_are_cleaned_up_when_date_changes(tmp_path, monkeypatch):
    handler = DailySizeRotatingFileHandler(str(tmp_path), base_name='web', retention_days=3)
    handler.setFormatter(logging.Formatter('%(message)s'))

    old_date = datetime.date.today() - datetime.timedelta(days=10)
    stale_path = tmp_path / f'web-{old_date.isoformat()}.log'
    stale_path.write_text('오래된 로그', encoding='utf-8')
    fresh_date = datetime.date.today() - datetime.timedelta(days=1)
    fresh_path = tmp_path / f'web-{fresh_date.isoformat()}.log'
    fresh_path.write_text('하루 전 로그', encoding='utf-8')

    handler.emit(_make_record('오늘 로그'))  # 날짜가 바뀐 것으로 감지돼 청소가 한 번 돎
    handler.close()

    assert not stale_path.exists(), '보관 기간(3일)보다 오래된 파일은 지워져야 함'
    assert fresh_path.exists(), '보관 기간 안의 파일은 남아있어야 함'


def test_non_matching_filenames_are_left_alone(tmp_path):
    """다른 base_name의 로그나 무관한 파일까지 지우면 안 된다."""
    handler = DailySizeRotatingFileHandler(str(tmp_path), base_name='web', retention_days=0)
    handler.setFormatter(logging.Formatter('%(message)s'))

    unrelated = tmp_path / 'notes.txt'
    unrelated.write_text('건드리면 안 됨', encoding='utf-8')
    other_logger_old = tmp_path / f'agent-{(datetime.date.today() - datetime.timedelta(days=10)).isoformat()}.log'
    other_logger_old.write_text('다른 담당 로그', encoding='utf-8')

    handler.emit(_make_record('x'))
    handler.close()

    assert unrelated.exists()
    assert other_logger_old.exists()
