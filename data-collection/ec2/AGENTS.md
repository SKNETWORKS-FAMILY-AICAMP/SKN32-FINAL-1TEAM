# ec2/ — 팀 EC2에서만 도는 것

## 맡는 것
- `ec2_vecstore.py`: 공용 MySQL에 올라간 벡터로 Chroma 색인(`notices_v1`)을 만든다. 증분(기본, `embedding_updated_at`이 워터마크보다 새로운 공고만 upsert) · `--rebuild` · `--stat` · `--plan`. 팀 EC2 crontab `10 0 * * *`(UTC = 한국 09:10). 리눅스용 DB 접속 `connect()`와 Chroma 열기 `open_store()`도 여기 있다.
- `ec2_search.py`: EC2에서 쓰는 대화형 검색. `ec2_check_model.py`: 모델 적재 확인.

## 맡지 않는 것
- 벡터 만들기(임베딩 모델 실행)는 하지 않는다. 배치 6단계가 만들고 8단계가 올린 것을 옮기기만 한다(torch·sentence-transformers 불필요 — pymysql·numpy·chromadb만).
- 공고 검색 로직(`search/`). 공고 서버는 리눅스에서 이 폴더의 `connect`·`open_store`를 빌려 쓸 뿐이다.

## 항상 지켜야 할 것
- 설정은 환경 변수 → `.env` 순서로 읽는다(`setting`). 빈 문자열은 "설정 안 함"과 구분해 그대로 돌려준다.
- `MYSQL_USER`·`MYSQL_PASSWORD`가 비면 연결하지 않고 빠진 이름을 알린다(비워 두면 OS 계정으로 붙어 엉뚱한 오류가 난다).
- 색인 위치는 `VECSTORE_PATH`, 없으면 `ec2/data/vecstore/chroma`. 워터마크 문서 ID `__watermark__`는 공고가 아니다 — 공고 ID 집합에서 뺀다.
- 색인이 비었거나 처음 만들 때는 시각을 믿지 않고 전체를 넣는다.
- 서버 시간대는 UTC다. 예약 시각을 한국 시각으로 적지 않는다.

## 이 폴더의 방식
- 색인은 벡터에서 결정되는 파생물이라, 파일을 PC에서 보내지 않고 EC2가 DB를 읽어 직접 만든다(2,050건 1.3초 · 14MB 실측).
- 500건씩 나눠 넣는다(`BATCH`).

## 시험
- 이 폴더를 직접 부르는 시험은 없다. 공고 서버 boot 시험(`tests/test_match_deh.py`)은 `ON_EC2=False`로 두고 `_connect`·`_collection`을 가짜로 바꿔 끼워 이 폴더를 피한다. `tests/test_chroma_integrity.py`는 색인과 DB의 정합성 검사 도구(`eval/chroma_integrity.py`) 쪽이다.
- 고치면 손으로 확인할 것: 빈 색인(전체 넣기), 워터마크 제외, 접속 정보 누락(연결 거부와 안내) — `--plan`·`--stat`으로 먼저 본다.
