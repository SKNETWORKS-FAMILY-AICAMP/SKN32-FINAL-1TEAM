"""웹서비스 로그 — 팀 로깅 정책("로그는 DB엔 남기지 말자, 로그 파일로 최대한 관리 -> 일자별
관리, 용량 초과 시 회전, 3일 지나면 삭제") 중 "웹서비스" 담당 분량. Agent/공고 수집 쪽 로그는
각 담당자가 별도로 만든다 — 이 모듈은 back/logs/ 밑에 파일로만 쌓고, DB 테이블은 전혀 안 쓴다.

표준 라이브러리의 TimedRotatingFileHandler(일자별)와 RotatingFileHandler(용량별)는 하나로
합쳐 쓸 수 없어서(TimedRotatingFileHandler.doRollover가 하루 안에 여러 번 불리면 같은
이름의 회전 파일을 서로 덮어써 버림 — 확인해서 배제한 방식), 그 대신 직접 파일명에 날짜를
박아 넣는 핸들러를 새로 짰다: web-YYYY-MM-DD.log로 쓰다가 용량을 넘으면 web-YYYY-MM-DD.2.log,
.3.log ...로 순번을 늘려간다.

[2026-09-23] "3일 지나면 로그 파일 삭제"(보관 기간 청소)는 구현은 다 돼 있지만
WEB_LOG_RETENTION_DAYS 기본값을 0(비활성)으로 꺼둔 상태다 — 지금 당장은 켜지 말라는
요청이 있어서. 나중에 켤 땐 환경변수 WEB_LOG_RETENTION_DAYS=3 을 넣거나, 아래 상수
기본값을 바꾸면 된다(코드 변경 없이 그대로 동작 — DailySizeRotatingFileHandler._reopen
참고).

{시각} | {INFO/WARNING/ERROR} | req_id={같은 id} user_id={...} {메소드} {라우트템플릿} end status={상태코드} elapsed_ms={처리시간} result={success/fail} [error_type={예외클래스명}]

"""
import datetime
import logging
import os
import re

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(_REPO_ROOT, 'logs')

# 하루 안에서도 이 크기를 넘으면 순번을 늘려 새 파일로 넘어간다(팀 정책 "용량 초과 시" 대응).
WEB_LOG_MAX_BYTES = int(os.environ.get('WEB_LOG_MAX_BYTES', 20 * 1024 * 1024))  # 기본 20MB
# 이보다 오래된 날짜의 로그 파일은 자동 삭제(팀 정책 "3일 지나면 로그 파일 삭제" 대응) —
# 0 이하면 청소 안 함. 지금은 0(비활성)이 기본값 — 나중에 켤 땐 환경변수로 3을 넣으면 된다.
WEB_LOG_RETENTION_DAYS = int(os.environ.get('WEB_LOG_RETENTION_DAYS', 0))


class DailySizeRotatingFileHandler(logging.Handler):
    """일자별 파일(<base_name>-YYYY-MM-DD.log)로 로그를 쓰고, 하루 안에서도 용량을
    넘으면 순번을 붙여 새 파일로 넘어간다. retention_days가 0보다 크면, 날짜가 바뀔 때
    그보다 오래된 파일을 청소한다 — 0(기본값)이면 청소 기능 자체가 꺼진다."""

    def __init__(
        self, log_dir: str, base_name: str = 'web',
        max_bytes: int = WEB_LOG_MAX_BYTES, retention_days: int = WEB_LOG_RETENTION_DAYS,
        encoding: str = 'utf-8',
    ) -> None:
        super().__init__()
        self.log_dir = log_dir
        self.base_name = base_name
        self.max_bytes = max_bytes
        self.retention_days = retention_days
        self.encoding = encoding
        os.makedirs(log_dir, exist_ok=True)
        self._current_date: datetime.date | None = None
        self._current_seq = 1
        self._stream = None
        self._filename_re = re.compile(rf'^{re.escape(base_name)}-(\d{{4}}-\d{{2}}-\d{{2}})(?:\.\d+)?\.log$')

    def _path_for(self, date: datetime.date, seq: int) -> str:
        suffix = '' if seq == 1 else f'.{seq}'
        return os.path.join(self.log_dir, f'{self.base_name}-{date.isoformat()}{suffix}.log')

    def _cleanup_old_files(self) -> None:
        cutoff = datetime.date.today() - datetime.timedelta(days=self.retention_days)
        try:
            names = os.listdir(self.log_dir)
        except OSError:
            return
        for name in names:
            m = self._filename_re.match(name)
            if not m:
                continue
            try:
                file_date = datetime.date.fromisoformat(m.group(1))
            except ValueError:
                continue
            if file_date < cutoff:
                try:
                    os.remove(os.path.join(self.log_dir, name))
                except OSError:
                    pass

    def _reopen(self, today: datetime.date) -> None:
        if today != self._current_date:
            self._current_date = today
            self._current_seq = 1
            if self.retention_days > 0:
                self._cleanup_old_files()
        path = self._path_for(self._current_date, self._current_seq)
        while self.max_bytes > 0 and os.path.exists(path) and os.path.getsize(path) >= self.max_bytes:
            self._current_seq += 1
            path = self._path_for(self._current_date, self._current_seq)
        if self._stream is not None:
            self._stream.close()
        self._stream = open(path, 'a', encoding=self.encoding)  # noqa: SIM115 -- 핸들러가 직접 수명 관리

    def emit(self, record: logging.LogRecord) -> None:
        try:
            today = datetime.date.today()
            needs_reopen = (
                self._stream is None
                or today != self._current_date
                or (self.max_bytes > 0 and self._stream.tell() >= self.max_bytes)
            )
            if needs_reopen:
                self._reopen(today)
            self._stream.write(self.format(record) + '\n')
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        super().close()


def _build_web_logger() -> logging.Logger:
    logger = logging.getLogger('sbrain.web')
    if logger.handlers:  # uvicorn --reload 등으로 모듈이 다시 import돼도 핸들러가 중복 안 붙게
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False  # uvicorn 루트 로거(콘솔)로 두 번 안 나가게

    handler = DailySizeRotatingFileHandler(LOG_DIR, base_name='web')
    handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)-7s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    logger.addHandler(handler)
    return logger


web_logger = _build_web_logger()
