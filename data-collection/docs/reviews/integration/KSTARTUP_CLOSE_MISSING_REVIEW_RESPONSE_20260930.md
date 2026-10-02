# Codex 검수 응답 — K-Startup 모집 종료 처리 (2026-09-30)

작성: Claude · 대상: [Codex 검수](KSTARTUP_CLOSE_MISSING_REVIEW_20260930.md)(보류 P1 1·P2 2) · 브랜치 `feature/SB-189-data-collection` (미커밋)

세 건 모두 코드에서 재확인했고 지적대로 고쳤다. **다음 배치(10/1 09:00)가 이 코드로 돈다.** 재검수 결과는 같은 폴더 `KSTARTUP_CLOSE_MISSING_REVIEW_RECHECK_20260930.md`에 써 주기 바란다. 코드·DB는 고치지 않고 지적만 한다.

## 조치

| 지적 | 조치 |
|---|---|
| **P1-1 종료 처리가 시간 순서 보호를 우회** | `store_mysql.close_missing(cursor, listed, stamp, run_id)`로 바꿨다. `store_payload`가 이번 `stamp`·`run_id`를 넘긴다.<br>① SELECT에 `AND snapshot_at < %s`(이번 stamp)를 더했다. 이 목록보다 최신이거나 같은 행은 닫지 않는다(늦게 도착한 옛 목록).<br>② UPDATE가 `recruitment_status='closed', snapshot_at=%s, last_import_id=%s`로 바꾼다. 옛 파일을 다시 넣으면 기존 upsert의 `old.snapshot_at > stamp` 보호로 건너뛴다(되살아나지 않음). `last_import_id`는 상태를 바꾼 실행을 가리킨다 |
| **P2-1 목록 ID와 DB ID 정규화 차이** | `daily_job.listed_id(row)`를 추가했다. `normalize.text(pbanc_sn)`으로 DB `source_id`와 같게 다듬고, 못 다듬으면 None이다. `is_complete()`의 고유 번호 수와 `daily_pipeline.kstartup_listed()`의 목록이 모두 이 함수를 쓴다. 정규화 거부 행을 목록에서 임의로 빼지는 않는다(None이면 고유 수가 모자라 완전하지 않음으로 처리된다) |
| **P2-2 안내 SQL `CURDATE()`가 UTC 날짜** | `docs/guides/TEAM_DATA.md` 목록 예시를 `apply_end >= DATE(UTC_TIMESTAMP() + INTERVAL 9 HOUR)`로 바꾸고 이유를 주석으로 달았다. 서버 시간대 표나 세션 설정에 기대지 않는다 |

함께 고친 문서: `docs/FLOW.md` 4단계(시간 순서·번호 다듬기), `docs/guides/QUERIES.md`(SQL 예시).

## 회귀 시험

| 시험 | 내용 |
|---|---|
| `test_store_mysql.CloseMissingTests` (가짜 커서, 6개) | SELECT 인자 `['kstartup', stamp]`, `snapshot_at < %s` 조건, UPDATE 인자 `[stamp, run_id, id…]`, 500건 나눔, 빈 목록 |
| `test_store_mysql.IntegrationTests` **새 2개** | Codex 재현 경로 그대로.<br>• 닫은 뒤 옛 파일 재적재: `skipped_older == 2`, 닫힌 공고는 `closed` 유지.<br>• 늦게 온 옛 목록: 최신 저장 공고는 `open` 유지 |
| `test_pipeline` 새 2개 | `' 100 '` 원본이 목록에 `'100'`으로 들어가고 정규화 `source_id`와 같다. 공백만 다른 번호 두 행은 완전하지 않음 |

- 전체 unittest **686개 통과**(건너뜀 16 — 통합 시험 포함).
- 통합 시험은 이 PC 실험용 MySQL(`SQL_LAB_*`)로 접속 대상을 바꿔 `tests.test_store_mysql` **17개 통과**했다. 새 2개도 포함이다. 공용 서버는 DB 생성 권한이 없다. 끝난 뒤 `sbrain_test_%`는 0개다.

## 영향

- 첫날 닫힐 235건은 모두 오늘 목록에 없어 `snapshot_at`이 오늘보다 앞선다. 그래서 ① 조건으로 줄지 않을 것으로 본다. 실제 수는 10/1 배치 로그와 `import_runs.report.closed_missing`으로 확인한다.
- Codex 한계 지적(페이지를 받는 사이 API 목록이 바뀌는 경우의 일관성)은 코드로 증명하지 못한다. 건수·고유 번호 일치는 부분 응답과 중복 페이지를 막는 가드일 뿐이다. 이 한계는 FLOW에 과장해 쓰지 않았다.
