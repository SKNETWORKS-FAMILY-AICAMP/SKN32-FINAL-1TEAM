"""S3 클라이언트 만들기 — AWS 라이브러리(boto3 · botocore)를 불러오는 곳은 이 모듈의 함수 안뿐이다(늦은 import).

- make_s3_client(region): 저장소가 클라이언트를 주입받지 않았을 때 처음 쓸 때 부르는 모듈 수준 함수다. 저장소는 부를 때마다
  이 모듈의 속성으로 찾으므로 테스트가 바꿔 끼울 수 있다(tests/conftest.py가 모든 테스트에서 막고, tests/s3_fake.py
  patch_client_factory가 가짜를 돌려주게 한다). 실제 클라이언트는 만들기만 해도 ~/.aws 설정 · 자격 증명 순서를 읽는다.
- 자격 증명은 AWS 기본 순서 그대로다(EC2에서는 서버 IAM 역할). 우리 코드는 AWS 키를 읽거나 넘기지 않는다. 리전은 넘긴 값을
  region_name으로 직접 준다(읽는 것은 조립 몫).
- 라이브러리 자체 재시도는 끈다: 첫 요청 포함 1번(total_max_attempts=1), 재시도 방식은 standard로 고정해 ~/.aws/config ·
  AWS_RETRY_MODE · AWS_MAX_ATTEMPTS가 바꾸지 못하게 한다(max_attempts=1은 '1번 더 재시도'라 쓰지 않는다). 재시도 규칙은 tools
  한 곳이고, 대기열 · 시작 확인은 각자 정한 대로 다시 한다.
- 시간 제한: 연결 10초 · 읽기 60초(잠정 — 파일 하나 30MB 이하). 연결 수는 라이브러리 기본값(잠정).
- AWS 라이브러리 로거는 따로 붙이지 않는다.
"""
from __future__ import annotations

from typing import Any

__all__ = ["CONNECT_TIMEOUT_SEC", "READ_TIMEOUT_SEC", "RETRY_MODE", "TOTAL_MAX_ATTEMPTS", "client_config",
           "load_library", "make_s3_client", "region_shape_ok"]

CONNECT_TIMEOUT_SEC = 10     # 연결 시간 제한 (잠정)
READ_TIMEOUT_SEC = 60        # 읽기 시간 제한 (잠정 — 파일 하나 30MB 이하)
TOTAL_MAX_ATTEMPTS = 1       # 라이브러리 재시도 끔 — 첫 요청 포함 1번 (잠정)
RETRY_MODE = "standard"      # 재시도 방식 고정 — 설정 파일 · 환경 변수가 바꾸지 못하게 (잠정)


def load_library() -> None:
    """AWS 라이브러리를 불러온다 — 클라이언트는 만들지 않고 설정 파일 · 네트워크에 닿지 않는다. 없으면 ImportError."""
    import boto3  # noqa: F401
    import botocore.config  # noqa: F401
    import botocore.utils  # noqa: F401


def region_shape_ok(region: str) -> bool:
    """리전 값 모양 — 클라이언트를 만들 때 라이브러리가 하는 검사(botocore.utils.validate_region_name)를 미리 한다.
    load_library 뒤에 부른다. 모양만 본다(실제로 있는 리전인지는 보지 않는다)."""
    from botocore.exceptions import InvalidRegionError
    from botocore.utils import validate_region_name

    try:
        validate_region_name(region)
    except InvalidRegionError:
        return False
    return True


def client_config() -> Any:
    """S3 클라이언트 설정(botocore Config) — 재시도 끔 · standard 고정 · 시간 제한. 만들기만 해도 설정 파일을 읽지 않는다.
    연결 수(max_pool_connections)는 넣지 않는다 — 라이브러리 기본값 10 (잠정)."""
    from botocore.config import Config

    return Config(retries={"total_max_attempts": TOTAL_MAX_ATTEMPTS, "mode": RETRY_MODE},
                  connect_timeout=CONNECT_TIMEOUT_SEC, read_timeout=READ_TIMEOUT_SEC)


def make_s3_client(region: str) -> Any:
    """실제 S3 클라이언트를 만든다(새 세션 — 세션은 스레드 안전이 아니라 저장소가 잠금 안에서 한 번 부른다).
    키 · 프로필 · 엔드포인트를 넘기지 않는다. 실패하면 라이브러리 예외를 그대로 올린다 — 저장소가 가른다
    (ImportError → 라이브러리 없음, 자격 증명 예외 → 일시, 그 밖 → 클라이언트를 만들지 못함)."""
    import boto3

    session = boto3.session.Session()
    return session.client("s3", region_name=region, config=client_config())
