# K-Startup 모집 종료 처리 재검수 (2026-09-30)

검수: Codex. 대상: [Claude 응답·재검수 요청](KSTARTUP_CLOSE_MISSING_REVIEW_RESPONSE_20260930.md)의 현재 미커밋 변경. [직전 검수](KSTARTUP_CLOSE_MISSING_REVIEW_20260930.md)의 P1 1건·P2 2건을 다시 확인했다. 코드·DB·Git 스테이징은 수정하지 않았다.

## 결론

**재검수 승인 — 기존 지적 세 건 해결 확인, 추가 지적 없음.** 시간 순서 보호가 종료 처리에도 적용되고, 목록과 저장 ID의 정규화가 같으며, 안내 SQL이 한국 날짜를 명시한다. 아래 승인은 검토한 변경에 대한 판단이다. 실제 MySQL 통합 시험과 10/1 예약 배치는 이번에 실행하지 않았다.

## 기존 지적 확인

| 지적 | 현재 구현·확인 근거 | 판정 |
|---|---|---|
| P1-1 종료 처리가 시간 순서 보호를 우회 | [close_missing](../../../shared/store_mysql.py#L188)은 `stamp`·`run_id`를 받는다. [SELECT](../../../shared/store_mysql.py#L205)는 `snapshot_at < stamp`인 open 행만 잠그고, [UPDATE](../../../shared/store_mysql.py#L210)는 상태와 함께 `snapshot_at`·`last_import_id`를 바꾼다. [store_payload 호출](../../../shared/store_mysql.py#L261)은 upsert와 같은 트랜잭션 안에서 이번 실행 값을 넘긴다. 기존 [과거 입력 가드](../../../shared/store_mysql.py#L241)와 연결해 두 반례 해결을 확인했다. | 해결 |
| P2-1 원본 목록 ID와 DB ID 정규화 차이 | [listed_id](../../../collect/daily_job.py#L103)가 DB와 같은 `normalize.text()`를 사용한다. [is_complete](../../../collect/daily_job.py#L116)와 [kstartup_listed](../../../collect/daily_pipeline.py#L155)가 이를 공유한다. `' 100 '`은 목록·저장 모두 `'100'`이 된다. 공백만 다른 중복 ID와 정규화할 수 없는 ID는 완전성 검사를 통과하지 않는다. | 해결 |
| P2-2 안내 SQL의 UTC 날짜 | [TEAM_DATA 목록 SQL](../../guides/TEAM_DATA.md#L199)은 `DATE(UTC_TIMESTAMP() + INTERVAL 9 HOUR)`를 사용한다. UTC 세션에서도 한국 날짜로 마감일을 비교하며, `unknown`을 허용하고 `closed`를 제외하는 조건은 유지된다. | 해결 |

FLOW의 시간 순서·ID 비교 설명과 QUERIES의 SELECT·UPDATE 예시도 실제 코드와 대조했다. 추가 수정이 필요한 불일치는 확인하지 못했다.

## 독립 재현 결과

저장소 코드는 수정하지 않고 표준입력 Python 스크립트로 실제 `normalize_sources()`·`store_payload()`·`listed_id()`·`is_complete()`·`kstartup_listed()`를 호출했다. DB 연결 객체만 SQL의 조회·갱신·트랜잭션을 해석하는 메모리 대역으로 제공했다. 실제 서버 SQL·잠금 검증을 대신하는 시험은 아니다.

기준 시각은 같은 날 UTC t1=00:10, t2=00:20, t3=00:30이다.

| 경로 | 재검수 결과 |
|---|---|
| t1에 100·101 open → t2 목록 `{100}`으로 101 종료 → t1 파일 재적재(`listed` 없음) | t2 `closed_missing=1`. 101의 시각=t2, `last_import_id`=종료 실행 ID, 보고서에 `kstartup:101` 기록. t1 재적재는 `skipped_older=2`이고 101은 closed 유지. |
| 위 종료 뒤 t3에 100·101이 다시 나타남 | 두 행 정상 반영, 101은 open으로 재개. |
| t3에 두 행 open → 늦게 온 t2 목록 `{100}` | `skipped_older=1`, `closed_missing=0`. 최신 101은 open 유지. |
| t3에 두 행 open → 같은 t3 목록 `{100}` | `closed_missing=0`. 동일 시각 행도 종료 대상에서 제외. |
| 완전한 원본 `pbanc_sn=' 100 '` → 실제 목록 헬퍼·정규화·저장 | 목록 `{'100'}`, 저장 ID `'100'`. t1부터 있던 100에 t2를 반영해도 open 유지. |
| `100`·`' 100 '` 중복, None·bool·dict·list·공백 ID, 0건·부분 목록 | 중복·잘못된 ID·0건·부분 목록 모두 `is_complete=False`. 잘못된 ID를 빼고 나머지만 완전한 목록으로 인정하지 않음. |
| 종료 UPDATE에 오류 주입 | 이번 upsert와 import 기록까지 이전 상태로 복원되고 rollback·잠금 해제 호출 확인. |
| 한국 시간 10/1 00:00·00:30·08:59·09:00·23:59 | UTC+9 날짜 계산이 모두 한국 날짜와 같고, 9/30 마감 공고는 제외. 날짜 산술 확인이며 실제 SQL 실행은 아님. |

위 **8개 시나리오 그룹 모두 통과**했다.

## 회귀 시험과 범위

- 번들 Python에 프로젝트 `.venv/Lib/site-packages`를 연결하고 `-B -X utf8`, `PYTHONDONTWRITEBYTECODE=1`, `MYSQL_INTEGRATION_TEST=0` 조건으로 실행했다.
- `unittest.defaultTestLoader.discover('tests', pattern='test_pipeline.py')`와 `test_store_mysql.py`를 합쳐 실행: **34개 중 28개 통과, 6개 건너뜀, 실패·오류 0**. 건너뛴 것은 DB 생성·쓰기·삭제가 있는 MySQL 통합 시험이다.
- 기존 시험에서 수집 실패 후 과거 파일 재사용·부분/중복 목록·dry-run·저장 생략 가드와 500건 단위 종료 UPDATE를 확인했다. 시간 순서에 대한 가짜 커서 시험은 SQL 형태만 확인하므로, 위 독립 시나리오로 실제 저장 함수의 상태 변화도 확인했다.
- Claude 응답서의 전체 686개·실험용 MySQL 17개 시험 결과는 **Claude의 실행 기록**이다. 이번 Codex 결과로 재보고하지 않는다. 전체 시험은 재실행하지 않았다.
- 실제 DB 연결·쓰기·임시 DB 생성, API 호출, 배치 실행, 서비스 재시작, 예약 변경은 하지 않았다. 첫 배치 235건 예상도 이번에 DB로 재집계하지 않았다.
- 변경 파일은 이 결과와 AGENTS.md에 따른 자신의 STATUS·WORKLOG 기록 및 문서 지도 링크다. 코드·DB·운영 설명서와 다른 작업자의 항목은 수정하지 않았다.

## 다음 확인

응답서에 예정된 **10/1 09:00 배치 뒤** 로그의 모집 종료 건수와 `import_runs.report.closed_missing`을 대조해 실제 반영 건수를 확인한다. 235건은 현재 검수에서 확정한 수치가 아니다.

페이지 수집 중 API 목록이 변할 때의 스냅샷 일관성은 여전히 미검증이다. 건수·고유 ID 일치는 부분 응답과 중복을 막는 가드이며 API의 일관성 보장을 증명하지는 않는다. 직전 검수의 이 한계는 유지하되, 이번 수정에 대한 새 차단 지적으로 보지는 않는다.
