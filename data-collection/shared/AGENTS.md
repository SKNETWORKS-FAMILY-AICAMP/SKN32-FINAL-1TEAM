# shared/ — 배치와 서버가 함께 쓰는 바탕

## 맡는 것
- `config.py`: `.env` 읽기. 찾는 순서 `shared/.env` → `data-collection/.env`(먼저 찾은 하나만). `get`·`require`. 인코딩된 인증키 경고.
- `store_mysql.py`: 공용 DB 접속(`connect`, TLS)과 정규화 파일 저장(`validate_payload` → `store_payload`: `notices`·`notice_attachments` upsert + `import_runs`, K-Startup 모집 종료 처리 `close_missing`), 명령 `python -m shared.store_mysql <정규화 파일> [--init-db|--check]`.
- `embed.py`: 공고 검색 입력의 **유일한 정의** `build_input`(제목·사업개요·지원대상·지원대상 분류·대분류·중분류), BGE-M3 인코딩, 설정 지문 `fingerprint`, `data/embeddings_v1.npz` 증분 갱신(`run`).
- `region.py`: 시·도 이름 정규화(별칭 → 16개 표준, `전남광주` 통합 포함), 시·군·구 목록, 공고 지역·제목 판정(`matches`·`district_matches`·`districts_in_title`).

## 맡지 않는 것
- 다른 폴더(`collect/`·`search/`·`experiments/` 등)를 import하지 않는다. 이 폴더는 의존성의 맨 아래다.
- 리눅스(EC2)용 DB 접속은 `ec2/ec2_vecstore.connect`가 따로 한다.
- 실험 DB 접속(`experiments/sql_semantic/config`, `SQL_LAB_*`).

## 항상 지켜야 할 것
- `config.py`는 표준 라이브러리만 쓴다. 이미 있는 환경 변수를 `.env` 값으로 덮지 않는다(배치 컨테이너가 이 규칙으로 경로를 덮는다).
- 저장 검증은 엄격하다: `schema_version == 1`, 출처는 `kstartup`·`bizinfo`, `notice_id == source + ':' + source_id`, 격리된 행(`rejected`)이 있으면 저장 거부, 같은 `notice_id` 두 번 거부.
- 저장은 시간 순서를 지킨다: 이미 저장된 행보다 오래된 입력(`snapshot_at`)은 덮어쓰지 않는다. 모집 종료 처리는 이번 목록보다 최신 행을 닫지 않고, 닫은 행의 `snapshot_at`·`last_import_id`를 이번 값으로 바꾼다.
- 공고 번호 비교는 저장과 같은 정규화(`normalize.text`)로 한다.
- DB 예외 메시지를 그대로 출력하지 않는다(SQL 값·비밀번호가 섞일 수 있다). 예외 종류와 코드만 낸다.
- `MYSQL_USER`·`MYSQL_PASSWORD`가 비면 연결하지 않고 무엇이 빠졌는지 알린다. `MYSQL_SSL_CA`가 있으면 서버 신원 검증 TLS, `MYSQL_SSL=1`이면 암호화만.
- `build_input`을 바꾸면 모든 공고의 입력 해시가 바뀌어 전량 재임베딩이 되고, BM25·평가 코퍼스도 함께 바뀐다. 입력 버전(`input_version`)을 올리고 사용자와 정한 뒤 바꾼다.
- 임베딩 설정 지문 7개(모델·리비전·입력 버전·토큰 상한·차원 1024·float32·정규화) 중 하나라도 바뀌면 전량 재생성이다. 리비전은 HuggingFace 캐시 `refs/main`에서 읽고, `HF_HUB_OFFLINE=1`로 돈다.

## 이 폴더의 방식
- torch·sentence-transformers는 함수 안에서 import한다(`--skip-embed`면 없어도 배치가 돈다).
- 벡터는 float32 리틀엔디안 연속 바이트(1건 4,096바이트)로 다루고 정규화돼 있어 내적 = 코사인.
- 지역 판정은 True(맞음)·False(다른 지역 전용)·None(공고 지역 없음·신청자 미선택)이다. None을 False로 바꾸지 않는다.

## 시험
- 관련 시험: `tests/test_store_mysql.py`(검증·upsert·시간 순서·모집 종료, MySQL 통합은 `MYSQL_INTEGRATION_TEST=1`), `test_pipeline.py`, `test_match_rules.py`(지역).
- 반드시 덮을 경우: 오래된 입력 재적재(덮지 않음), 늦게 온 옛 목록(최신 공고를 닫지 않음), 공고 번호 공백·표기 차이, 격리 행 있는 파일(거부), 설정 지문 변경(전량 재생성 판정), 시·도 별칭(`광주`·`전라남도` → `전남광주`).
