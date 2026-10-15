# db/ — 공용 DB 테이블 정의

## 맡는 것
- `mysql_schema.sql`: 기본 테이블 `import_runs`·`notices`·`notice_attachments`·`attachment_texts`(MySQL 8.0, InnoDB, utf8mb4_bin). `shared.store_mysql --init-db`가 이 파일을 `;`로 나눠 실행한다.
- 변경 SQL `mysql_migration_NNN_<내용>.sql`: 002 임베딩 칸 5개, 003 `attachment_files`, 004 `notice_conditions`, 005 금액 버림 표시, 006 `notice_applicant_types`·`notice_industries`, 007 `notice_bonus`, 008 `notice_bonus.content_version`.

## 맡지 않는 것
- 실행 코드. 이 폴더 SQL을 자동으로 적용하는 코드는 없다(`--init-db`는 기본 스키마만).
- 실험 DB 테이블(`experiments/sql_semantic/schema.sql`) — 공용 DB에 만들지 않는다.

## 항상 지켜야 할 것
- 새 변경은 다음 번호의 새 파일로 쓴다(지금 008까지). 기존 파일을 고쳐 이미 적용된 DB와 어긋나게 만들지 않는다.
- `CREATE TABLE IF NOT EXISTS`·칸 추가처럼 **기존 테이블·행을 지우거나 바꾸지 않는** 형태로 쓴다. 칸 삭제·형 변경·`DROP`·`TRUNCATE`를 넣지 않는다.
- 모든 칸에 한국어 `COMMENT`를 단다. "모름"과 "없음"을 구분해 적는다(예: `age_condition_raw` "미확보는 제한 없음을 뜻하지 않음").
- 시각 칸은 UTC `DATETIME(6)`이다(주석에 UTC를 적는다).
- 공용 DB 적용은 사용자 승인 뒤 손으로 한다. 적용 뒤 배치 서버 코드가 새 칸을 쓰는 판인지 확인한다.
- 식별자 칸 규칙: `notice_id`는 `출처:원본ID`(VARCHAR 320), 해시는 `CHAR(64)` ascii.

## 이 폴더의 방식
- 판정·추출 결과 테이블은 판정 당시 문서 지문·추출기 버전 칸을 함께 둔다. 읽는 쪽이 지금 공고와 대조해 옛 판정을 버린다.
- 각 파일 머리말에 무엇을 왜 더하는지, 언제 만들었는지를 적는다.

## 시험
- SQL 자체의 자동 시험은 없다. 저장 코드 시험(`tests/test_store_mysql.py` 통합 시험, `MYSQL_INTEGRATION_TEST=1`)이 기본 스키마를 쓴다.
- 새 변경 SQL은 로컬 MySQL에 기본 스키마 → 002부터 차례로 적용해 오류가 없는지 먼저 확인한다.
