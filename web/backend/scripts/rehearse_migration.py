"""마이그레이션 리허설 (SB-265) — 옛 웹 스키마에 migrations/001 · 002 · 004를 적용해 새 스키마(app_schema.sql)와 같아지는지 본다.

    python scripts/rehearse_migration.py                       # 옛 스키마 = git origin/main 의 app_schema.sql
    python scripts/rehearse_migration.py --old-ref <git ref>   # 다른 옛 스키마 기준
    python scripts/rehearse_migration.py --old-schema-file 공유DB_덤프.sql   # 공유 DB 사본의 스키마 덤프를 쓸 때

★ 공유 DB 사본이 없어서 옛 스키마를 git(main)으로 대신한다 — 공유 DB가 실제로 main 스키마와 같은지는 이 스크립트가 알 수 없다. 사본이 생기면
  `--old-schema-file`(mysqldump --no-data 결과)로 같은 리허설을 다시 돌린다. 로컬 호스트의 MySQL만 받고 DB는 아래 두 개를 새로 만든다(있으면 지운다).
    sbrain_test_mig_old   옛 스키마 + 시드 데이터 → 001 → 002 → 004 → orch_ 표 적용 (리허설 대상)
    sbrain_test_mig_new   새 스키마(app_schema.sql) + orch_ 표 (비교 기준)

차례대로:
  1. 옛 DB 만들기(공고 스키마 + 옛 웹 스키마)와 시드 데이터(사용자 · 프로젝트 · 계획서 · 검수 기록 · 알림 · 실패 알림)
  2. 001 적용 → proofread_logs의 plan_id NULL 허용 · project_id · model_version, 기존 행의 project_id가 채워졌는지, 데이터가 그대로인지
  3. 002 적용 → 더미 테이블 13개 · 컬럼이 사라졌는지, 입력 · 알림 · 검수 기록 데이터가 남았는지
     004 적용(SB-328) → project_budget_items.phase(NULL 허용)가 생겼는지, 기존 사업비 행이 NULL로 남았는지
     ※ 003(feature/sb-269-web-final의 checklist_items)은 이 브랜치에 없어 건너뛴다 — 병합 뒤 003 단계를 002와 004 사이에 넣는다
  4. orch_ 표 적용(projects를 참조) → 이어서 001 · 002 · 004를 다시 적용해도 오류가 없고 스키마가 그대로인지(멱등)
  5. 새 DB와 스키마 비교(표 · 열 형식 · NULL 허용 · 기본값 · 인덱스 · 외래 키 규칙) — 다르면 마이그레이션에 빠진 것이 있다는 뜻

마이그레이션 SQL은 DELIMITER · 저장 프로시저를 써서 mysql 클라이언트가 필요하다 — 로컬 MySQL 컨테이너(--container)의 mysql을 `docker exec`로 부른다.
"""
import argparse
import pathlib
import subprocess
import sys

import pymysql
from prepare_local_mysql import NOTICE_SCHEMA_DIR, ORCH_SCHEMA, REPO_ROOT, WEB_SCHEMA, notice_schema_files, split_sql

MIGRATIONS = REPO_ROOT / 'web' / 'backend' / 'migrations'
OLD_DB, NEW_DB = 'sbrain_test_mig_old', 'sbrain_test_mig_new'
LOCAL_HOSTS = {'127.0.0.1', 'localhost', '::1'}
DROPPED_TABLES = (
    'business_plans', 'plan_sections', 'plan_canonical_data', 'plan_score_reasons', 'artifacts', 'artifact_score_reasons', 'verdicts',
    'match_candidates', 'match_score_reasons', 'eligibility_checks', 'format_findings', 'agent_executions', 'verification_score_history')

if hasattr(sys.stdout, 'reconfigure'):  # 콘솔 인코딩(cp949 등)에 없는 문자(— 등)가 있어도 출력이 죽지 않게
    sys.stdout.reconfigure(errors='replace')

results: list[tuple[str, bool, str]] = []


def step(name: str, ok: bool, detail: str = '') -> bool:
    results.append((name, ok, detail))
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f' — {detail}' if detail else ''), flush=True)
    return ok


def connect(args, database: str | None = None):
    return pymysql.connect(host=args.host, port=args.port, user=args.user, password=args.password, database=database,
                           charset='utf8mb4', autocommit=True)


def fresh_database(args, name: str) -> None:
    conn = connect(args)
    try:
        cur = conn.cursor()
        cur.execute(f'DROP DATABASE IF EXISTS `{name}`')
        cur.execute(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')
    finally:
        conn.close()


def run_statements(args, database: str, script: str) -> None:
    conn = connect(args, database)
    try:
        cur = conn.cursor()
        for stmt in split_sql(script):
            cur.execute(stmt)
    finally:
        conn.close()


def run_migration(args, database: str, path: pathlib.Path) -> tuple[bool, str]:
    """mysql 클라이언트로 마이그레이션을 적용한다(DELIMITER · 저장 프로시저가 있어 pymysql로는 못 부른다)."""
    proc = subprocess.run(
        ['docker', 'exec', '-i', '-e', f'MYSQL_PWD={args.password}', args.container, 'mysql', f'-u{args.user}', '--default-character-set=utf8mb4',
         database],
        input=path.read_bytes(), capture_output=True)
    out = (proc.stdout + proc.stderr).decode('utf-8', 'replace').strip()
    return proc.returncode == 0 and 'ERROR' not in out, out[-300:]


def query(args, database: str, sql: str, params=()):
    conn = connect(args, database)
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        conn.close()


def schema_snapshot(args, database: str) -> dict:
    """표 · 열 · 인덱스 · 외래 키를 비교용으로 모은다. 열 주석 · 외래 키 이름 · 인덱스 이름은 비교하지 않는다(자동으로 붙는 이름이라 흔들린다)."""
    columns = {(t, c): (ty, nl, df, ex) for t, c, ty, nl, df, ex in query(
        args, database,
        "SELECT table_name, column_name, column_type, is_nullable, column_default, extra FROM information_schema.columns "
        "WHERE table_schema=%s", (database,))}
    index_rows = query(
        args, database,
        "SELECT table_name, index_name, non_unique, seq_in_index, column_name FROM information_schema.statistics "
        "WHERE table_schema=%s ORDER BY table_name, index_name, seq_in_index", (database,))
    grouped: dict[tuple, list] = {}
    for table, index, non_unique, _seq, column in index_rows:
        grouped.setdefault((table, index, non_unique), []).append(column)
    indexes = {(t, tuple(cols), nu) for (t, _name, nu), cols in grouped.items()}
    fks = {(t, c): (rt, rc, dr, ur) for t, c, rt, rc, dr, ur in query(
        args, database,
        "SELECT k.table_name, k.column_name, k.referenced_table_name, k.referenced_column_name, r.delete_rule, r.update_rule "
        "FROM information_schema.key_column_usage k JOIN information_schema.referential_constraints r "
        "ON r.constraint_schema=k.constraint_schema AND r.constraint_name=k.constraint_name AND r.table_name=k.table_name "
        "WHERE k.table_schema=%s AND k.referenced_table_name IS NOT NULL", (database,))}
    return {'tables': {t for t, _ in columns}, 'columns': columns, 'indexes': indexes, 'fks': fks}


def diff_snapshots(old: dict, new: dict) -> list[str]:
    lines = []
    for t in sorted(old['tables'] - new['tables']):
        lines.append(f'새 스키마에 없는 표가 남음: {t}')
    for t in sorted(new['tables'] - old['tables']):
        lines.append(f'마이그레이션 뒤에 없는 표: {t}')
    for key in sorted(set(old['columns']) | set(new['columns'])):
        if key[0] not in old['tables'] or key[0] not in new['tables']:
            continue
        if old['columns'].get(key) != new['columns'].get(key):
            lines.append(f'열이 다름 {key[0]}.{key[1]}: 마이그레이션 뒤 {old["columns"].get(key)} / 새 스키마 {new["columns"].get(key)}')
    for item in sorted(old['indexes'] ^ new['indexes'], key=str):
        side = '마이그레이션 뒤에만' if item in old['indexes'] else '새 스키마에만'
        lines.append(f'인덱스 {side}: {item}')
    for key in sorted(set(old['fks']) | set(new['fks'])):
        if old['fks'].get(key) != new['fks'].get(key):
            lines.append(f'외래 키가 다름 {key[0]}.{key[1]}: 마이그레이션 뒤 {old["fks"].get(key)} / 새 스키마 {new["fks"].get(key)}')
    return lines


SEED = [
    "INSERT INTO users (email, name, google_sub, ai_training_agreed) VALUES ('a@x.test', '가', 'sub-a', 1), ('b@x.test', '나', 'sub-b', 0)",
    "INSERT INTO companies (user_id, applicant_type, ceo_name) VALUES (1, 'preliminary', '가'), (2, 'preliminary', '나')",
    "INSERT INTO projects (company_id, description, status, stage, fit_score, reason, resume_count, retry_count, is_regenerating) "
    "VALUES (1, '프로젝트1', 'completed', 'done', 0.9, '잘 맞음', 2, 0, 0), (2, '프로젝트2', 'failed', 'plan_writing', 0.5, '보통', 5, 0, 0)",
    "INSERT INTO business_plans (project_id, doc_score) VALUES (1, 60.0), (2, 50.0)",
    "INSERT INTO plan_sections (plan_id, tag, title, body) VALUES (1, '1-1', '문제인식', '본문')",
    "INSERT INTO proofread_logs (plan_id, section_id, original_text, corrected_text, attempt_no, passed, recovery_status) "
    "VALUES (1, 1, '원문1', '시도1', 1, 0, 'pending'), (1, 1, '원문2', '시도2', 1, 0, 'labeled'), (2, NULL, '원문3', '시도3', 1, 1, NULL)",
    "INSERT INTO project_budget_items (project_id, item_order, category, execution_plan, total_amount, government_amount, self_cash_amount, self_in_kind_amount) "
    "VALUES (1, 1, '외주용역비', '앱 개발 외주', 1000000, 1000000, 0, 0)",
    "INSERT INTO notifications (project_id, kind, target_step) VALUES (1, '문서평가', 6), (2, '실패', NULL)",
    "INSERT INTO generation_failure_alerts (project_id, stage, resume_count, last_error_kind, failure_reason, regenerate_exhausted) "
    "VALUES (2, '계획서작성', 5, '일시', '재개 상한 초과', 0)",
]
KEEP_COUNTS = {'users': 2, 'companies': 2, 'projects': 2, 'notifications': 2, 'generation_failure_alerts': 1, 'proofread_logs': 3,
               'project_budget_items': 1}


def counts(args, database: str) -> dict[str, int]:
    return {t: query(args, database, f'SELECT COUNT(*) FROM `{t}`')[0][0] for t in KEEP_COUNTS}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=3307)
    parser.add_argument('--user', default='root')
    parser.add_argument('--password', default='sbrain-test')
    parser.add_argument('--container', default='sbrain-mysql-test-mysql-1', help='mysql 클라이언트를 부를 로컬 MySQL 컨테이너 이름')
    parser.add_argument('--old-ref', default='origin/main', help='옛 웹 스키마를 읽을 git 기준(app_schema.sql)')
    parser.add_argument('--old-schema-file', help='옛 스키마 SQL 파일(공유 DB 사본의 --no-data 덤프 등). 주면 --old-ref 대신 쓴다')
    parser.add_argument('--keep', action='store_true', help='끝나도 두 DB를 지우지 않는다(결과를 직접 보려고)')
    args = parser.parse_args()

    if args.host not in LOCAL_HOSTS:
        print(f'거부: 로컬 호스트의 MySQL만 받습니다 (호스트={args.host}) — DB를 지우고 다시 만들기 때문입니다.')
        return 2

    if args.old_schema_file:
        old_schema = pathlib.Path(args.old_schema_file).read_text(encoding='utf-8')
        source = args.old_schema_file
    else:
        old_schema = subprocess.run(['git', 'show', f'{args.old_ref}:web/backend/app_schema.sql'], cwd=REPO_ROOT, capture_output=True, check=True).stdout.decode('utf-8')
        source = f'git {args.old_ref}'
    notice_sql = [p.read_text(encoding='utf-8') for p in notice_schema_files()]

    # 1) 옛 DB
    fresh_database(args, OLD_DB)
    for script in [*notice_sql, old_schema]:
        run_statements(args, OLD_DB, script)
    old_tables = {r[0] for r in query(args, OLD_DB, 'SELECT table_name FROM information_schema.tables WHERE table_schema=%s', (OLD_DB,))}
    step(f'1. 옛 스키마 적용({source})', all(t in old_tables for t in DROPPED_TABLES), f'표 {len(old_tables)}개, 더미 표 13개 있음')
    conn = connect(args, OLD_DB)
    try:
        cur = conn.cursor()
        for stmt in SEED:
            cur.execute(stmt)
    finally:
        conn.close()
    before = counts(args, OLD_DB)
    step('1. 시드 데이터', before == KEEP_COUNTS, f'{before}')

    # 2) 001
    ok, out = run_migration(args, OLD_DB, MIGRATIONS / '001_proofread_logs_worker_table.sql')
    step('2. 001 적용', ok, out if not ok else '')
    cols = {r[0]: r[1] for r in query(args, OLD_DB, "SELECT column_name, is_nullable FROM information_schema.columns "
                                      "WHERE table_schema=%s AND table_name='proofread_logs'", (OLD_DB,))}
    step('2. proofread_logs: plan_id NULL 허용 · project_id · model_version 추가', cols.get('plan_id') == 'YES' and 'project_id' in cols and 'model_version' in cols, f'{cols}')
    rows = query(args, OLD_DB, 'SELECT original_text, project_id FROM proofread_logs ORDER BY log_id')
    step('2. 기존 행의 project_id가 계획서의 프로젝트로 채워짐', list(rows) == [('원문1', 1), ('원문2', 1), ('원문3', 2)], f'{rows}')
    step('2. 001은 데이터를 지우지 않음', counts(args, OLD_DB) == before, f'{counts(args, OLD_DB)}')

    # 3) 002
    ok, out = run_migration(args, OLD_DB, MIGRATIONS / '002_drop_dummy_pipeline.sql')
    step('3. 002 적용', ok, out if not ok else '')
    left = {r[0] for r in query(args, OLD_DB, 'SELECT table_name FROM information_schema.tables WHERE table_schema=%s', (OLD_DB,))} & set(DROPPED_TABLES)
    step('3. 더미 표 13개가 사라짐', not left, f'남은 표 {sorted(left)}')
    after = counts(args, OLD_DB)
    step('3. 입력 · 알림 · 실패 알림 · 검수 기록 데이터가 그대로', after == before, f'{after}')
    rows = query(args, OLD_DB, 'SELECT original_text, project_id FROM proofread_logs ORDER BY log_id')
    step('3. 검수 기록의 project_id가 002 뒤에도 남음(plan_id를 떼어도 연결이 유지)', list(rows) == [('원문1', 1), ('원문2', 1), ('원문3', 2)], f'{rows}')

    # 3b) 004 (SB-328)
    ok, out = run_migration(args, OLD_DB, MIGRATIONS / '004_budget_phase.sql')
    step('3. 004 적용', ok, out if not ok else '')
    phase_cols = query(args, OLD_DB, "SELECT column_type, is_nullable FROM information_schema.columns "
                       "WHERE table_schema=%s AND table_name='project_budget_items' AND column_name='phase'", (OLD_DB,))
    step('3. project_budget_items.phase(VARCHAR(10), NULL 허용) 추가', list(phase_cols) == [('varchar(10)', 'YES')], f'{phase_cols}')
    phases = query(args, OLD_DB, 'SELECT phase FROM project_budget_items')
    step('3. 기존 사업비 행의 phase는 NULL로 남고 데이터가 그대로', list(phases) == [(None,)] and counts(args, OLD_DB) == before, f'{phases}')

    # 4) orch_ 표 + 멱등
    run_statements(args, OLD_DB, ORCH_SCHEMA.read_text(encoding='utf-8'))
    orch_ok = query(args, OLD_DB, "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s AND table_name LIKE 'orch\\_%%'", (OLD_DB,))[0][0]
    step('4. orch_ 표 적용(projects를 참조)', orch_ok > 0, f'orch_ 표 {orch_ok}개')
    first = schema_snapshot(args, OLD_DB)
    for name in ('001_proofread_logs_worker_table.sql', '002_drop_dummy_pipeline.sql', '004_budget_phase.sql'):
        ok, out = run_migration(args, OLD_DB, MIGRATIONS / name)
        step(f'4. {name[:3]} 다시 적용해도 오류 없음(멱등)', ok, out if not ok else '')
    second = schema_snapshot(args, OLD_DB)
    step('4. 다시 적용해도 스키마가 그대로', not diff_snapshots(first, second), '; '.join(diff_snapshots(first, second))[:300])
    step('4. 다시 적용해도 데이터가 그대로', counts(args, OLD_DB) == before, f'{counts(args, OLD_DB)}')

    # 5) 새 스키마와 비교
    fresh_database(args, NEW_DB)
    for script in [*notice_sql, WEB_SCHEMA.read_text(encoding='utf-8'), ORCH_SCHEMA.read_text(encoding='utf-8')]:
        run_statements(args, NEW_DB, script)
    diffs = diff_snapshots(second, schema_snapshot(args, NEW_DB))
    step('5. 마이그레이션한 DB가 새 스키마(app_schema.sql)와 같음', not diffs, f'차이 {len(diffs)}건')
    for line in diffs[:40]:
        print(f'      - {line}')

    if not args.keep:
        conn = connect(args)
        try:
            cur = conn.cursor()
            cur.execute(f'DROP DATABASE IF EXISTS `{OLD_DB}`')
            cur.execute(f'DROP DATABASE IF EXISTS `{NEW_DB}`')
        finally:
            conn.close()

    failed = [r for r in results if not r[1]]
    print(f'\n요약: {len(results) - len(failed)}/{len(results)} 통과' + (f', 실패: {[r[0] for r in failed]}' if failed else ''))
    return 1 if failed else 0


if __name__ == '__main__':
    _ = NOTICE_SCHEMA_DIR  # prepare_local_mysql에서 함께 가져온 경로(공고 스키마 위치) — 설명용
    sys.exit(main())
