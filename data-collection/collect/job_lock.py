"""자동·수동 수집의 프로세스 잠금. 프로세스 종료 시 OS가 해제한다."""
import os
from contextlib import contextmanager


class JobBusy(Exception):
    pass


@contextmanager
def acquire(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    # 삭제하면 다른 프로세스가 다른 파일을 잠글 수 있으므로 파일을 유지한다.
    with open(path, 'a+b') as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise JobBusy('이미 수집 작업이 실행 중입니다.') from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
