# 검수 요청 — K-Startup 모집 종료 처리 (2026-09-30)

작성: Claude · 결정: 사용자(이근준) · 검수: Codex · 브랜치 `feature/SB-189-data-collection` (미커밋)

결과는 같은 폴더 `KSTARTUP_CLOSE_MISSING_REVIEW_20260930.md`에 쓴다. 코드·DB·Git 스테이징은 고치지 않고 지적만 한다. 공용 DB는 조회만 한다.

**★ 이 변경은 다음 매일 배치(10/1 09:00)부터 공용 DB `notices`에 쓴다.** 배치는 이 PC의 체크아웃된 코드로 돈다. 첫날 K-Startup 공고 **235건**이 `open`에서 `closed`로 바뀐다(아래 3절).

## 1. 문제

- K-Startup API는 모집 중 목록만 받는다(`collect/fetch.py:39-41`, `cond[rcrt_prgs_yn::EQ]=Y`). 마감일 전에 모집이 끝난 공고는 목록에서 사라질 뿐이다.
- 저장 단계(`shared/store_mysql.store_payload`)는 입력에 없는 공고를 건드리지 않는다. 그래서 그런 공고가 DB에 `recruitment_status='open'`으로 계속 남았다.
- 9/30 실제 사례: 마감일이 9/30인데 목록에서 빠진 공고 5건(175808·176937·178706·179096·179204). 매칭 필터(`search/gate.prefilter`)가 추천에 남기고, 자격 확인은 "모집 중 O"로 보여 줬다.
- 다른 팀 안내서(`docs/guides/TEAM_DATA.md`)의 `WHERE recruitment_status = 'open'` 예시로 조회하면, 마감일이 지난 230건도 목록에 나왔다.

## 2. 사용자 결정과 변경

- 사용자 결정: 방식 **A** — 새 칸(DDL)을 만들지 않고, 기존 칸에 `closed`를 쓴다. 대안 B(마지막으로 목록에서 본 날짜 칸 추가)는 택하지 않았다.

| 파일 | 변경 |
|---|---|
| `collect/daily_job.py` | `is_complete(rows, total)`를 추가했다(103행). 받은 행 수와 고유 `pbanc_sn` 수가 모두 서버 보고 건수와 같을 때만 True다. 결과 `complete`를 `notices.json`·로그·dry-run 결과에 넣는다. 맞지 않으면 경고 한 줄을 남긴다. **수집·검증·교체 동작은 그대로다**(덜 받아도 저장은 한다) |
| `collect/daily_pipeline.py` | `kstartup_listed(ks)`를 추가했다(155행). K-Startup `status == 'ok'`이고 `complete`일 때만 방금 쓴 `notices.json`에서 공고 번호 집합을 꺼낸다. 파일의 `complete`와 `reported_total`도 다시 확인한다. 아니면 None이다. `store(path, say, listed)`로 넘기고(279행), 닫은 건수를 진행 줄과 마지막 요약에 찍는다. 로그의 `sources.kstartup`에 `complete`가 들어간다 |
| `shared/store_mysql.py` | `missing_open()`(182행)과 `close_missing(cursor, listed)`(188행)를 추가했다. `store_payload(..., listed=None)`가 모든 upsert 뒤 **같은 트랜잭션**에서 부른다(256행). `source=%s AND recruitment_status='open' FOR UPDATE`로 읽고, 목록에 없는 행만 500건씩 `closed`로 바꾼다. 결과에 `closed_missing`(건수)를, `import_runs.report.closed_missing`에 `{출처: [notice_id…]}`를 남긴다. 빈 집합이면 아무것도 하지 않는다 |
| 테스트 | `tests/test_store_mysql.py`: 가짜 커서로 닫기 SQL 4건, 임시 DB 통합 시험 1건(닫았다가 다시 나오면 `open`, `MYSQL_INTEGRATION_TEST=1`일 때만). `tests/test_pipeline.py`: 완전하면 목록 넘김, 덜 받음·겹침·K 실패(어제 파일 재사용)면 None, `is_complete` 경계 |
| 문서 | `docs/FLOW.md` 4단계, `guides/QUERIES.md`(DELETE 없음 아래), `guides/FIELD_MAP.md`, `guides/TEAM_DATA.md`(주의 표와 목록 화면 예시 SQL을 `<> 'closed' AND (apply_end IS NULL OR apply_end >= CURDATE())`로), `db/mysql_schema.sql` 칸 주석(파일만. 공용 DB 주석은 바꾸지 않았다 — ALTER 없음) |

## 3. 영향 (공용 DB 조회만)

- 9/30 배치 뒤 K-Startup `open` 477건 중 오늘 목록(242건)에 없는 것은 **235건**이다. 230건은 마감일이 지났고, 5건은 마감일이 9/30이다. 이 수는 이 PC의 `data/notices.json`(242/242, complete 조건 충족)과 DB를 대조해 셌다.
- 매칭 필터는 원래 `closed`를 뺀다(`gate.py:243-247`). 마감일이 지난 230건은 이미 날짜로 빠지고 있었으므로 매칭 결과에서는 달라지지 않는다. 달라지는 것은 마감일 전에 닫힌 공고와 `recruitment_status`로 조회하는 SQL이다.
- 서비스(8000)는 켤 때 한 번 읽으므로 다시 켜야 반영된다. EC2 Chroma 메타데이터의 `status`는 임베딩이 바뀔 때만 다시 쓰여 옛 값이 남는다. 다만 이 값으로 거르는 코드는 없다(`ec2/ec2_search.py`는 `apply_end`만 본다).
- 조율 쪽(`agent-orchestration/`)은 `recruitment_status`를 읽지 않는다(문자열 0건).

## 4. 검증

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
```

- 전체 **673개 통과**(건너뜀 14). 9/29 663개에 새 시험 10개(통합 시험 1개는 건너뜀)가 더해졌다.
- 임시 DB 통합 시험(`MYSQL_INTEGRATION_TEST=1`, 사용자 승인):
  - 공용 서버는 팀 계정에 DB 생성 권한이 없어 첫 단계(`CREATE DATABASE`)에서 멈췄다. 아무것도 만들어지지 않았다.
  - 대신 이 PC의 실험용 MySQL(`SQL_LAB_*`, localhost)로 `MYSQL_HOST/PORT/USER/PASSWORD`를 바꿔 돌렸다. `tests.test_store_mysql` **13개 모두 통과**했다. 새 시험 "목록에서 빠지면 닫고 다시 나오면 연다"도 포함이다. 끝난 뒤 `sbrain_test_%` DB는 0개로 남지 않았다.
  - 공용 서버와 MySQL 판이 다를 수 있다는 점은 확인하지 않았다.
- 실제 배치로는 아직 돌려 보지 않았다. 첫 실행은 10/1 09:00 배치다.

## 5. 봐 줄 것

1. **잘못 닫을 경로가 있는가.**
   - 수집 실패·검증 거부·dry-run·어제 파일 재사용일 때 `listed`가 None인가.
   - 서버가 `matchCount`와 `totalCount`를 다르게 줄 때(`fetch.py:49`)의 판단은 안전한가.
   - 정규화가 일부 행을 거부할 때도 괜찮은가. 목록은 정규화 결과가 아니라 원본 `pbanc_sn`에서 꺼내므로, 거부된 공고는 닫히지 않는다.
   - `skipped_older` 행은 목록에 있으므로 닫히지 않는다.
   - `source_id` 형식(`str(pbanc_sn)`)과 DB 값이 맞는가.
2. **트랜잭션.** 닫기가 같은 트랜잭션 안에 있어 실패하면 저장 전체가 되돌려지는가. 잠금(`GET_LOCK`, `FOR UPDATE`) 범위는 괜찮은가.
3. **되돌림.** 목록에 다시 나타나면 upsert가 `open`으로 되돌리는가. 모집이 끝나 `closed`로 바뀐 뒤 K-Startup이 `rcrt_prgs_yn=N`을 보낼 일은 없지만(서버 조건), 있다면 문제가 없는가.
4. **첫날 235건이 한 번에 바뀌는 것**에 대한 추가 가드(예: 비율 상한)가 필요한가. Claude는 필요 없다고 봤다. 조건이 "오늘 받은 목록이 서버 보고 건수와 정확히 같음"이고, 첫날 외에는 하루 수 건 수준으로 예상하기 때문이다.
5. 문서의 뜻 바꿈("API가 준 값" → "API 값, 또는 모집 중 목록에서 빠짐")이 빠진 곳 없이 반영됐는가. `TEAM_DATA.md`의 새 예시 SQL은 적절한가.
