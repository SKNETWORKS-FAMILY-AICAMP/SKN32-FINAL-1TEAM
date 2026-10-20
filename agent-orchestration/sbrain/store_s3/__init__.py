"""S3 파일 저장소 (확장) — 산출물 파일을 S3에 두는 FileStore 구현. 엔진(orchestrator/)은 이 패키지를 모르고,
조립(bootstrap.py)만 SBRAIN_ARTIFACT_ROOT 값('s3://<버킷>[/<접두어>]')을 보고 고른다.

- address: S3 주소 해석 — is_s3_address · s3_address_problem · parse_s3_address(→ S3Address) · bucket_name_problem ·
  prefix_problem · normalize_prefix · split_s3_address. AWS 라이브러리 없이 돈다.
- store: S3FileStore(버킷, 접두어, 리전, *, read_only=False, client=None) · S3FileStore.from_address(주소, 리전, …) —
  FileStore 약속(쓰기 · 읽기 · 메타데이터 · 접두어째 지우기). 클라이언트는 처음 쓸 때 client.make_s3_client로 만든다.
- errors: 오류 바꾸기 표 — S3TemporaryError(ConnectionError, 일시) · S3TimeoutError(TimeoutError, 일시) · ProviderError
  (영구 — orchestrator.errors) · S3StoreError(RuntimeError, 설정 · 코드 오류), TEMPORARY_ERROR_CODES, s3_error_code.
- client: AWS 라이브러리를 늦게 불러오는 곳 — make_s3_client(region)(테스트가 바꿔 끼우는 모듈 수준 함수) · client_config.
- probe: 워커 시작 확인 check_s3_store(store) → S3CheckResult(· raise_if_failed → S3StartupCheckFailed).

이 패키지를 불러와도 AWS 라이브러리(boto3 · botocore)를 불러오지 않는다 — 저장소를 클라이언트 주입 없이 만들 때 불러온다
(로컬 폴더로 도는 프로세스 · 테스트는 불러오지 않는다). 가져다 쓰는 것은 orchestrator(FileStore · FileMeta · 파일 예외 ·
errors.ProviderError) · models뿐이다. 값(버킷 · 접두어 · 리전 · 키)은 예외 메시지 · 로그에 넣지 않는다.
"""
from .address import (  # noqa: F401
    PREFIX_MAX_LEN, S3_SCHEME, S3Address, bucket_name_problem, is_s3_address, normalize_prefix, parse_s3_address,
    prefix_problem, s3_address_problem, split_s3_address,
)
from .errors import (  # noqa: F401
    TEMPORARY_ERROR_CODES, S3StoreError, S3TemporaryError, S3TimeoutError, s3_error_code,
)
from .probe import PROBE_DIR, S3CheckResult, S3StartupCheckFailed, check_s3_store  # noqa: F401
from .store import S3FileStore  # noqa: F401
