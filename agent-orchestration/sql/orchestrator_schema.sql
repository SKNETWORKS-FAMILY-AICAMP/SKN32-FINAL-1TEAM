-- S-Brain Orchestrator 테이블 (MySQL 8 이상)
--
-- 이 파일은 코드에서 만든다. 직접 고치지 않는다.
--   정의: sbrain/store_sql/schema.py
--   생성: python -m sbrain.store_sql.ddl
--
-- 적용 순서: 웹 스키마(app_schema.sql) 다음. orch_runs.project_id가 projects(project_id)를 참조한다.
-- CREATE TABLE IF NOT EXISTS만 있다. 이미 있는 테이블은 바꾸지 않는다.
-- 웹 테이블 구조는 바꾸지 않는다. Orchestrator는 웹 테이블 중 notifications, generation_failure_alerts,
-- proofread_logs에 INSERT만 하고, verification_policies와 학습 동의(users.ai_training_agreed)를 읽는다.

CREATE TABLE IF NOT EXISTS orch_runs (
	run_id VARCHAR(64) NOT NULL COMMENT '실행 건 ID (Run.runId)', 
	account_id VARCHAR(64) NOT NULL COMMENT '계정 (Run.accountId = 웹 users.user_id)', 
	project_id BIGINT UNSIGNED COMMENT '사전 정보 출처 (Run.projectId, 확장). 완전 삭제되면 NULL — 실행 로그는 남긴다', 
	step VARCHAR(20) NOT NULL COMMENT 'RunState.step — 단계명', 
	progress VARCHAR(10) NOT NULL COMMENT 'RunState.progress — 실행 · 재개대기 · 사용자대기 · 실패 · 완료 · 중단', 
	resume_step INTEGER NOT NULL COMMENT 'RunState.resumeStep — 이어하기 복귀 화면', 
	current_phase VARCHAR(20) NOT NULL, 
	announcement_id VARCHAR(320) COMMENT '선택 공고', 
	rework_screen INTEGER, 
	current_task VARCHAR(40), 
	retry_count INTEGER NOT NULL DEFAULT 0, 
	resume_count INTEGER NOT NULL DEFAULT 0, 
	next_resume_at DATETIME(6) COMMENT '재개 예정 시각 (재개대기)', 
	last_error_kind VARCHAR(10) COMMENT '일시 · 입력 · 운영', 
	failure_reason TEXT COMMENT '실패 사유 (확장)', 
	lease_owner VARCHAR(200) COMMENT '점유자 (호스트 · 프로세스 · 스레드)', 
	lease_until DATETIME(6) COMMENT '점유 만료 시각', 
	collect_until DATETIME(6) COMMENT '재작성 요청을 모으는 시간이 끝나는 시각 (확장) — 그 전에는 워커가 가져가지 않는다', 
	abort_requested BOOL NOT NULL COMMENT '중단 요청 — 단계 사이에서 반영' DEFAULT false, 
	run_json LONGTEXT NOT NULL COMMENT 'Run 전체 (기준 문서 JSON 이름)', 
	created_at DATETIME(6) NOT NULL, 
	updated_at DATETIME(6) NOT NULL, 
	ended_at DATETIME(6), 
	PRIMARY KEY (run_id), 
	CONSTRAINT uq_orch_runs_project UNIQUE (project_id), 
	CONSTRAINT fk_orch_runs_project FOREIGN KEY(project_id) REFERENCES projects (project_id) ON DELETE SET NULL, 
	KEY ix_orch_runs_account_progress (account_id, progress), 
	KEY ix_orch_runs_progress_lease (progress, lease_until), 
	KEY ix_orch_runs_progress_resume (progress, next_resume_at)
)ENGINE=InnoDB CHARSET=utf8mb4 COMMENT='실행 건 (Run) — 실행 상태의 원본. 프로젝트 1건에 최대 1건' COLLATE utf8mb4_bin;

CREATE TABLE IF NOT EXISTS orch_start_requests (
	request_id VARCHAR(64) NOT NULL COMMENT '시작 요청 ID', 
	project_id BIGINT UNSIGNED COMMENT '웹 projects.project_id. 테스트 · 시연용 직접 시작은 NULL', 
	account_id VARCHAR(64) NOT NULL, 
	status VARCHAR(10) NOT NULL COMMENT '대기 · 처리중 · 완료 · 실패 · 취소', 
	form_json LONGTEXT COMMENT '검사를 통과한 PreInput. 완전 삭제 때 지운다', 
	result_code VARCHAR(40) COMMENT '실패 코드 (시트 6)', 
	result_message TEXT COMMENT '안내 문구', 
	result_detail LONGTEXT COMMENT '실패 상세 — 누락 항목 · 진행 중 작업 등 (확장)', 
	notices LONGTEXT COMMENT '안내 목록', 
	run_id VARCHAR(64) COMMENT '만든 실행 건', 
	cancel_requested BOOL NOT NULL COMMENT '처리 중 취소 요청' DEFAULT false, 
	claim_count INTEGER NOT NULL COMMENT '워커가 가져간 횟수 (확장)' DEFAULT 0, 
	lease_owner VARCHAR(200), 
	lease_until DATETIME(6), 
	created_at DATETIME(6) NOT NULL, 
	updated_at DATETIME(6) NOT NULL, 
	finished_at DATETIME(6), 
	PRIMARY KEY (request_id), 
	KEY ix_orch_start_requests_account_status (account_id, status), 
	KEY ix_orch_start_requests_project (project_id), 
	KEY ix_orch_start_requests_status_created (status, created_at)
)ENGINE=InnoDB CHARSET=utf8mb4 COMMENT='사전 단계 시작 요청 — 웹이 넣고 워커가 처리' COLLATE utf8mb4_bin;

CREATE TABLE IF NOT EXISTS orch_artifact_versions (
	run_id VARCHAR(64) NOT NULL COMMENT '실행 건', 
	artifact_key VARCHAR(200) NOT NULL COMMENT '산출물 이름', 
	version INTEGER NOT NULL, 
	value LONGTEXT COMMENT '산출물 내용 (JSON). 완전 삭제 때 지운다', 
	producer VARCHAR(200) NOT NULL COMMENT '만든 실행 ID 또는 user:… · orchestrator:…', 
	created_at DATETIME(6) NOT NULL, 
	PRIMARY KEY (run_id, artifact_key, version)
)ENGINE=InnoDB CHARSET=utf8mb4 COMMENT='산출물 버전 — 산출물 내용은 여기에만 있다' COLLATE utf8mb4_bin;

CREATE TABLE IF NOT EXISTS orch_artifact_pointers (
	run_id VARCHAR(64) NOT NULL COMMENT '실행 건', 
	artifact_key VARCHAR(200) NOT NULL, 
	version INTEGER NOT NULL COMMENT '현재 버전', 
	PRIMARY KEY (run_id, artifact_key)
)ENGINE=InnoDB CHARSET=utf8mb4 COMMENT='산출물 현재 버전 포인터' COLLATE utf8mb4_bin;

CREATE TABLE IF NOT EXISTS orch_pointer_events (
	seq BIGINT UNSIGNED NOT NULL COMMENT '기록 순서' AUTO_INCREMENT, 
	run_id VARCHAR(64) NOT NULL COMMENT '실행 건', 
	artifact_key VARCHAR(200) NOT NULL, 
	from_version INTEGER, 
	to_version INTEGER NOT NULL, 
	reason VARCHAR(500) NOT NULL, 
	cycle_id VARCHAR(64) COMMENT '재작성 사이클', 
	at DATETIME(6) NOT NULL, 
	PRIMARY KEY (seq), 
	KEY ix_orch_pointer_events_run (run_id)
)ENGINE=InnoDB CHARSET=utf8mb4 COMMENT='포인터 이동 (되돌리기) 기록' COLLATE utf8mb4_bin;

CREATE TABLE IF NOT EXISTS orch_executions (
	seq BIGINT UNSIGNED NOT NULL COMMENT '기록 순서' AUTO_INCREMENT, 
	execution_id VARCHAR(64) NOT NULL COMMENT '실행 ID', 
	run_id VARCHAR(64) NOT NULL COMMENT '실행 건', 
	project_id BIGINT UNSIGNED COMMENT '관리자 조회용 (실행 건에서 복사)', 
	task_id VARCHAR(40) NOT NULL, 
	attempt INTEGER NOT NULL, 
	`trigger` VARCHAR(10) NOT NULL COMMENT '첫실행 · 재작성 · 재수행', 
	bundle_id VARCHAR(500), 
	agent VARCHAR(20) NOT NULL, 
	step_kind VARCHAR(10) NOT NULL COMMENT 'task · rule · merge', 
	model VARCHAR(100), 
	provider VARCHAR(50), 
	temperature DOUBLE, 
	reasoning_effort VARCHAR(20), 
	status VARCHAR(10) NOT NULL COMMENT '실행 · 성공 · 실패 · 재개대기 · 생략', 
	error_kind VARCHAR(10), 
	error TEXT, 
	cycle_id VARCHAR(64) COMMENT '재작성 사이클', 
	redo_count INTEGER NOT NULL DEFAULT 0, 
	resume_count INTEGER NOT NULL DEFAULT 0, 
	input_tokens BIGINT UNSIGNED COMMENT '입력 토큰 합계 (캐시 입력 포함)', 
	cached_input_tokens BIGINT UNSIGNED COMMENT '캐시 입력 토큰 합계 (입력의 일부)', 
	output_tokens BIGINT UNSIGNED COMMENT '출력 토큰 합계 (추론 포함)', 
	reasoning_tokens BIGINT UNSIGNED COMMENT '추론 토큰 합계 (출력의 일부)', 
	created_at DATETIME(6) NOT NULL, 
	started_at DATETIME(6), 
	ended_at DATETIME(6), 
	record_json LONGTEXT NOT NULL COMMENT 'ExecutionRecord 전체 (산출물 내용 없음)', 
	PRIMARY KEY (seq), 
	CONSTRAINT uq_orch_executions_execution UNIQUE (execution_id), 
	KEY ix_orch_executions_project_task_started (project_id, task_id, started_at), 
	KEY ix_orch_executions_run (run_id), 
	KEY ix_orch_executions_started (started_at), 
	KEY ix_orch_executions_status_started (status, started_at)
)ENGINE=InnoDB CHARSET=utf8mb4 COMMENT='단계 실행 기록 (AttemptRef 확장) — 관리자 에이전트 테스크 조회' COLLATE utf8mb4_bin;

CREATE TABLE IF NOT EXISTS orch_call_logs (
	seq BIGINT UNSIGNED NOT NULL COMMENT '기록 순서' AUTO_INCREMENT, 
	call_id VARCHAR(64) NOT NULL COMMENT '호출 ID', 
	run_id VARCHAR(64) NOT NULL COMMENT '실행 건', 
	execution_id VARCHAR(64) NOT NULL COMMENT '실행 ID', 
	task_id VARCHAR(40) NOT NULL, 
	agent VARCHAR(20) NOT NULL, 
	call_type VARCHAR(20) NOT NULL COMMENT 'llm · search', 
	purpose VARCHAR(200) NOT NULL, 
	item_key VARCHAR(200) COMMENT 'T-P2 문장 ID 등', 
	provider VARCHAR(50), 
	model VARCHAR(100), 
	temperature DOUBLE, 
	reasoning_effort VARCHAR(20), 
	timeout_sec DOUBLE NOT NULL, 
	final_outcome VARCHAR(10) NOT NULL, 
	error VARCHAR(10) COMMENT '호출실패 · 응답지연 · 형식오류', 
	error_kind VARCHAR(10), 
	tries LONGTEXT NOT NULL COMMENT '시도별 결과 (토큰 포함)', 
	input_tokens BIGINT UNSIGNED COMMENT '입력 토큰 합계 (캐시 입력 포함)', 
	cached_input_tokens BIGINT UNSIGNED COMMENT '캐시 입력 토큰 합계 (입력의 일부)', 
	output_tokens BIGINT UNSIGNED COMMENT '출력 토큰 합계 (추론 포함)', 
	reasoning_tokens BIGINT UNSIGNED COMMENT '추론 토큰 합계 (출력의 일부)', 
	started_at DATETIME(6) COMMENT '첫 시도 시작', 
	ended_at DATETIME(6) COMMENT '마지막 시도 끝', 
	PRIMARY KEY (seq), 
	CONSTRAINT uq_orch_call_logs_call UNIQUE (call_id), 
	KEY ix_orch_call_logs_execution (execution_id), 
	KEY ix_orch_call_logs_run (run_id)
)ENGINE=InnoDB CHARSET=utf8mb4 COMMENT='LLM · 검색 호출 기록 — 재시도는 tries에 쌓인다. 프롬프트 · 응답 내용 없음' COLLATE utf8mb4_bin;

CREATE TABLE IF NOT EXISTS orch_feedback_links (
	seq BIGINT UNSIGNED NOT NULL COMMENT '기록 순서' AUTO_INCREMENT, 
	feedback_id VARCHAR(64) NOT NULL COMMENT '피드백 ID', 
	run_id VARCHAR(64) NOT NULL COMMENT '실행 건', 
	kind VARCHAR(10) NOT NULL COMMENT '재수행 · 재작성 · 재작성반영', 
	cycle_id VARCHAR(64) COMMENT '재작성 사이클', 
	source_execution_id VARCHAR(64) COMMENT '보낸 실행', 
	target_execution_id VARCHAR(64) NOT NULL COMMENT '받는 실행', 
	created_at DATETIME(6) NOT NULL, 
	record_json LONGTEXT NOT NULL, 
	PRIMARY KEY (seq), 
	KEY ix_orch_feedback_links_run (run_id)
)ENGINE=InnoDB CHARSET=utf8mb4 COMMENT='검사 · 검증 피드백 전달 기록' COLLATE utf8mb4_bin;

CREATE TABLE IF NOT EXISTS orch_rework_comparisons (
	seq BIGINT UNSIGNED NOT NULL COMMENT '기록 순서' AUTO_INCREMENT, 
	run_id VARCHAR(64) NOT NULL COMMENT '실행 건', 
	bundle_id VARCHAR(500) NOT NULL, 
	cycle_id VARCHAR(64) NOT NULL COMMENT '재작성 사이클', 
	screen INTEGER NOT NULL, 
	kept VARCHAR(2) NOT NULL COMMENT '전 · 후', 
	basis VARCHAR(20) NOT NULL, 
	compared_at DATETIME(6) NOT NULL, 
	record_json LONGTEXT NOT NULL, 
	PRIMARY KEY (seq), 
	KEY ix_orch_rework_comparisons_run (run_id)
)ENGINE=InnoDB CHARSET=utf8mb4 COMMENT='재작성 전후 비교 (ReworkComparison)' COLLATE utf8mb4_bin;

CREATE TABLE IF NOT EXISTS orch_trace_events (
	seq BIGINT UNSIGNED NOT NULL COMMENT '기록 순서' AUTO_INCREMENT, 
	run_id VARCHAR(64) NOT NULL COMMENT '실행 건', 
	kind VARCHAR(40) NOT NULL, 
	execution_id VARCHAR(64) COMMENT '실행 ID', 
	cycle_id VARCHAR(64) COMMENT '재작성 사이클', 
	at DATETIME(6) NOT NULL, 
	record_json LONGTEXT NOT NULL, 
	PRIMARY KEY (seq), 
	KEY ix_orch_trace_events_run (run_id)
)ENGINE=InnoDB CHARSET=utf8mb4 COMMENT='그 밖의 추적 사건' COLLATE utf8mb4_bin;
