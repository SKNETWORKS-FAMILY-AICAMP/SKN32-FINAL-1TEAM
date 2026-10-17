"""S3 시작 확인 — 워커 조립이 S3 저장소를 만든 뒤 한 번 부른다(웹은 부르지 않는다).

확인 내용 — 접두어 아래 시험 객체 '<접두어>.probe/<고유값>'(잠정)으로:
  ① 없는 시험 객체를 읽어 '없음'(NoSuchKey)이 나오는지 — 목록 권한(s3:ListBucket)이 없으면 S3가 없는 객체에도 권한 없음(403)을
     주어 실행 중 모든 넣기(메타 확인)가 실패한다
  ② 작은 내용을 쓰고 → 읽고(같은지) → 지운다
  이름이 '.'으로 시작해 산출물 키(첫 마디가 실행 건 ID — '.'으로 시작할 수 없음)와 겹치지 않고, 파일 삭제 대기열이 지우는
  접두어('<runId>/')에도 들지 않는다. 리전 불일치를 잡는다고 약속하지 않는다.

결과 S3CheckResult(ok, permanent, step, kind, status, code, message) — 워커 조립(bootstrap.build_app · worker.main)이 종료 코드로 바꾼다:
  - 성공: ok=True
  - 영구(permanent=True — 설정 오류, 워커 종료 코드 2): 권한 없음 · 버킷 없음 · 그 밖의 4xx 영구 오류(ProviderError — status ·
    code), ①에서 '없음'이 아닌 결과, 읽은 내용이 다름, 클라이언트를 만들지 못함 · AWS 라이브러리 없음(step=클라이언트,
    kind=S3StoreError.kind), 표에 없는 라이브러리 오류. 메시지 예:
      '설정 오류: S3 산출물 위치를 쓸 수 없음(쓰기) — 권한 · 버킷 · 리전 · 접두어를 확인 (status=403 code=access_denied)'
      '설정 오류: AWS 라이브러리(boto3 · botocore)를 불러오지 못함 — 패키지를 다시 설치'
  - 일시(permanent=False — 워커 종료 코드 1): 연결 · 시간 초과 · 5xx · 속도 제한 · 자격 증명을 얻지 못함(EC2 메타데이터에서
    역할 자격을 못 받음 · 자격 없음). kind=종류(errors.KIND_*). 메시지 'S3 시작 확인 실패(일시) — <종류>'
  - 메시지에는 종류 · 단계 · 상태 · 오류 코드만 — 버킷 · 접두어 · 리전 · 시험 객체 이름 · AWS 메시지를 넣지 않는다.
  - result.raise_if_failed()는 실패면 S3StartupCheckFailed(RuntimeError — .result · .permanent, 메시지 = result.message)를 올린다.
중간에 실패하면 남은 시험 객체를 지우려고 한 번 해 보고(실패는 무시) 위 분류로 끝낸다. 이 함수는 기다리거나 다시 시도하지 않는다.
읽기 전용 저장소에는 쓰지 않는다(ValueError — 워커 저장소에서만 부른다).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from ..orchestrator.errors import ProviderError
from .errors import S3StoreError, S3TemporaryError, S3TimeoutError, status_code_text
from .store import S3FileStore

__all__ = ["PROBE_CONTENT_TYPE", "PROBE_DIR", "STEP_ABSENT", "STEP_CLIENT", "STEP_DELETE", "STEP_READ", "STEP_WRITE",
           "S3CheckResult", "S3StartupCheckFailed", "check_s3_store"]

PROBE_DIR = ".probe/"                # 시험 객체가 놓이는 곳(접두어 아래) — '<접두어>.probe/<고유값>' (잠정)
PROBE_CONTENT_TYPE = "text/plain"    # 시험 객체의 형식 표시 (잠정)

# 단계 — 결과 · 메시지에 그대로 나간다
STEP_ABSENT = "없는 객체 읽기"
STEP_WRITE = "쓰기"
STEP_READ = "읽기"
STEP_DELETE = "지우기"
STEP_CLIENT = "클라이언트"

_HEAD = "설정 오류: S3 산출물 위치를 쓸 수 없음"
_CHECK = "권한 · 버킷 · 리전 · 접두어를 확인"
_LIST_HINT = " · 목록 권한(s3:ListBucket) 필요"


@dataclass(frozen=True)
class S3CheckResult:
    """시작 확인 결과. ok가 거짓이면 permanent(참 = 설정 오류 · 거짓 = 일시)와 message를 본다."""
    ok: bool
    permanent: bool = False
    step: str | None = None      # 실패한 단계(STEP_*)
    kind: str | None = None      # 일시 종류(errors.KIND_*) 또는 설정 오류 종류(S3StoreError.kind). S3 응답 오류면 None
    status: int | None = None
    code: str | None = None
    message: str = ""

    def raise_if_failed(self) -> None:
        if not self.ok:
            raise S3StartupCheckFailed(self)


class S3StartupCheckFailed(RuntimeError):
    """시작 확인 실패 — 조립이 워커 종료 코드로 바꾼다(permanent면 2, 아니면 1). 메시지 = result.message."""

    def __init__(self, result: S3CheckResult) -> None:
        super().__init__(result.message)
        self.result = result
        self.permanent = result.permanent


def _permanent(step: str, *, status: int | None = None, code: str | None = None,
               reason: str | None = None) -> S3CheckResult:
    hint = _LIST_HINT if step == STEP_ABSENT and status == 403 else ""
    tail = reason or status_code_text(status, code)
    message = f"{_HEAD}({step}) — {_CHECK}{hint}" + (f" ({tail})" if tail else "")
    return S3CheckResult(ok=False, permanent=True, step=step, status=status, code=code, message=message)


def _temporary(step: str, e: S3TemporaryError | S3TimeoutError) -> S3CheckResult:
    tail = status_code_text(e.status, e.code)
    message = f"S3 시작 확인 실패(일시) — {e.kind}" + (f" ({tail})" if tail else "")
    return S3CheckResult(ok=False, permanent=False, step=step, kind=e.kind, status=e.status, code=e.code,
                         message=message)


def _setup(step: str, e: S3StoreError) -> S3CheckResult:
    if e.kind in (S3StoreError.LIBRARY, S3StoreError.CLIENT):
        step = STEP_CLIENT
    return S3CheckResult(ok=False, permanent=True, step=step, kind=e.kind, message=f"설정 오류: {e}")


def check_s3_store(store: S3FileStore) -> S3CheckResult:
    """워커 S3 저장소 시작 확인 — 모듈 설명의 순서 · 분류. 클라이언트가 없으면 이때 처음 만든다."""
    if store.read_only:
        raise ValueError("읽기 전용 S3 저장소에는 시작 확인을 하지 않는다 — 워커 저장소에서만 부른다")
    name = f"{store.prefix}{PROBE_DIR}{uuid.uuid4().hex}"
    body = f"sbrain-probe {uuid.uuid4().hex}".encode("ascii")
    step, wrote = STEP_ABSENT, False
    try:
        if store._get_object(name) is not None:
            return _permanent(STEP_ABSENT, reason="없는 시험 객체가 있다고 나옴")
        step, wrote = STEP_WRITE, True
        store._put_object(name, body, PROBE_CONTENT_TYPE)
        step = STEP_READ
        if store._get_object(name) != body:
            return _permanent(STEP_READ, reason="읽은 내용이 다름")
        step = STEP_DELETE
        store._delete_object(name)
        wrote = False
        return S3CheckResult(ok=True)
    except ProviderError as e:
        return _permanent(step, status=e.status, code=e.code)
    except (S3TemporaryError, S3TimeoutError) as e:
        return _temporary(step, e)
    except S3StoreError as e:
        return _setup(step, e)
    finally:
        if wrote:   # 중간에 실패 — 남은 시험 객체를 한 번 지워 본다(실패는 무시)
            try:
                store._delete_object(name)
            except Exception:
                pass
