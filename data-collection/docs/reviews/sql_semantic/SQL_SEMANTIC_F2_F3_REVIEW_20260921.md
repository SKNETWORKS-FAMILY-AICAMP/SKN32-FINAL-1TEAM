# SQL 의미 검색 F2·F3 재검토

2026-09-21 · Codex · 구현 변경 없이 코드·회귀 테스트·로컬 실험 DB 읽기 전용 검토

대상:

- `experiments/sql_semantic/search.py`
- `experiments/sql_semantic/prepare.py`
- `experiments/sql_semantic/embedding.py`
- `experiments/sql_semantic/fixtures.py`
- `experiments/sql_semantic/viewer.py`
- `tests/test_sql_semantic.py`
- `tests/test_verify_ui.py`
- `web/verify.html`

원래 지적사항은 [SQL 정형 필터 + 의미 검색 실험 리뷰](SQL_SEMANTIC_REVIEW_20260918.md)의
F2(검색 시 모델 리비전 미검사), F3(벡터 재생성 UPSERT의 메타데이터 갱신 누락)다.

## 판정

**F2 승인, F3 승인.** 이번 재검토 범위에서 새로 수정해야 할 기능 결함은 발견하지 못했다.

## F2 — 모델 리비전 대조

`search.run()`은 현재 다음 조건을 모두 만족한 저장 벡터만 유사도 계산에 사용한다.

1. 현재 공고 내용으로 다시 계산한 입력 해시가 같다.
2. 입력 계약과 모델 이름이 같다.
3. 저장 `model_revision`과 현재 질의 인코더 리비전이 같다.
4. 어느 쪽 리비전이든 알 수 없으면 사용하지 않는다.
5. 리비전 불일치·확인 불가는 `stale_vector`로 세고 공고 ID와 사유를 남긴다.

응답의 `encoder`에도 모델·리비전·계약이 기록된다. 따라서 같은 모델명·입력 해시·차원이라도
리비전만 다른 원래 반례는 결과에서 제외된다. 저장 리비전 없음, 현재 리비전 없음, 정상 일치도
각각 회귀 테스트로 확인했다.

검증 화면 fixture의 `fx-007`은 같은 모델 이름과 다른 리비전을 가진 벡터다. 화면 데이터에서
`다른 모델 리비전` 사유로 제외되고 정상 결과에는 포함되지 않는다.

## F3 — 재생성 메타데이터 갱신

벡터 UPSERT는 기본키인 `notice_id`, `contract`를 제외한 아래 모든 칸을 새 값으로 갱신한다.

- `model`, `model_revision`, `dim`, `dtype`, `normalized`
- `input_sha256`, `truncated`, `token_count`, `vector`, `created_at`

재사용 판정도 입력 해시·모델·리비전·차원뿐 아니라 dtype과 정규화 여부까지 비교한다.
가짜 테이블을 사용한 회귀 테스트에서 잘못된 옛 행을 재생성한 뒤 다음 흐름을 확인했다.

```text
불일치 행 발견 → 새 벡터와 메타데이터 UPSERT → 검색 정상 통과 → 다음 생성은 skipped
```

테스트의 가짜 테이블은 실제 `VECTOR_SQL`의 UPDATE 절에 적힌 칸만 변경한다. 따라서 UPDATE에서
메타데이터 칸이 다시 빠지면 회귀 테스트가 실패하는 구조다.

## 독립 검증 결과

### 테스트

- F2·F3 및 검증 화면 표적 테스트: **30개 통과**
- 전체 테스트: **246개 통과, 13개 건너뜀**
- Claude가 기록한 전체 테스트 수와 일치한다.

프로젝트 `.venv` 실행기는 원래 Python 설치 경로가 없어 시작되지 않았다. 설치나 환경 변경 없이
Codex 번들 Python에 기존 `.venv/Lib/site-packages`를 연결해 실행했다.

`tests/test_sql_semantic.py` docstring의 invalid escape `SyntaxWarning`과
`eval/search_comparison.py`의 미닫힌 파일 `ResourceWarning`은 남아 있지만 F2·F3 동작이나 테스트 성공에는
영향이 없으며 이번 수정 범위의 회귀는 아니다.

### 로컬 실험 DB — SELECT만 수행

`lab_vectors` 1,852건을 현재 `embedding.meta()` 및 현재 입력 해시와 대조했다.

- 계약: `sql_lab_v1:title+purpose+content+eligibility`
- 모델: `BAAI/bge-m3`
- 모델 리비전: `5617a9f61b028005a4858fdac845db406aefb181`
- 차원·dtype·정규화: `1024` · `float32` · `1`
- 위 메타데이터 조합: **1,852건 전부 동일**
- 현재 재사용 조건으로 재생성이 필요한 행: **0건**

따라서 현재 로컬 실험 DB에서는 F2 검사 때문에 정상 벡터가 제외되거나 F3 재생성이 필요한 상태가 아니다.
DB에는 쓰지 않았고 실제 벡터 재생성도 하지 않았다.

## 한계와 후속 처리

- 다른 실제 모델 리비전을 내려받아 라이브 DB 행을 재생성하는 시험은 하지 않았다. 그 경로는 가짜 연결·가짜
  인코더 회귀 테스트로 검증했다.
- Claude가 기록한 실제 case01 검색의 `stale=0` 및 저장 Top-5 일치는 이번에 모델을 다시 올려 독립 재실행하지 않았다.
  대신 1,852건 메타데이터·입력 해시·재사용 판정을 읽기 전용으로 전수 대조했다.
- 현재 리비전 탐색은 로컬 Hugging Face 기본 캐시의 `refs/main`을 사용한다. 리비전을 찾지 못하면 조용히
  호환으로 간주하지 않고 모든 해당 벡터를 stale로 처리하는 안전한 실패 정책이다. 다른 캐시 경로를 쓰는
  환경에서는 먼저 리비전 탐색이 되는지 확인해야 한다.
- Chroma 내용 정합성과 사람 관련성 판정은 이번 검토 범위가 아니다.

Claude는 검증 화면과 상태 문서의 F2·F3를 `해결 · Codex 승인 (2026-09-21)`으로 갱신해도 된다.
구현·테스트·DB·기존 결과 파일은 수정하지 않았으며, 이 리뷰 문서만 추가했다.
Git 스테이징·커밋·push는 하지 않았다.
