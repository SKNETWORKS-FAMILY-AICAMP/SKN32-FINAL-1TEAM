"""DB 칸 설명(COMMENT)에 이미 지운 옛 표 이름이 남지 않았는지, 그리고 운영 DB용 마이그레이션 007과 app_schema.sql의 새 문구가 같은지 본다 (SB-420).

마이그레이션 002가 business_plans · artifacts 같은 옛 파이프라인 표를 지웠는데 살아 있는 표의 칸 설명에는 그 이름이 남아 있었다.
관리자 화면 · ERD · 설계 문서가 DB 칸 설명을 그대로 옮겨 쓰므로 없는 표 이름이 문서까지 퍼졌다.
MySQL이 없어도 도는 정적 시험이며, 007을 실제 DB에서 실행하는 확인은 scripts/rehearse_migration.py(로컬 MySQL)가 맡는다.

실행:
    pytest tests/test_schema_comments.py -v
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA = (ROOT / 'app_schema.sql').read_text(encoding='utf-8')
MIGRATION = (ROOT / 'migrations' / '007_fix_stale_column_comments.sql').read_text(encoding='utf-8')

DROPPED_TABLES = (
    'agent_executions', 'artifact_score_reasons', 'artifacts', 'business_plans', 'eligibility_checks', 'format_findings',
    'match_candidates', 'match_score_reasons', 'plan_canonical_data', 'plan_score_reasons', 'plan_sections', 'verdicts',
    'verification_score_history',
)
COMMENT = re.compile(r"""COMMENT\s+('(?:[^']|'')*'|"[^"]*")""")

# (표, 칸, 새 칸 설명, 칸 정의) — 새 문구는 app_schema.sql과 007에 같게 들어 있어야 한다
FIXES = [
    ('proofread_logs', 'score', '이 시도의 윤문 품질 점수(0~100, 소수 둘째 자리까지)', 'DECIMAL(5,2) NOT NULL DEFAULT 100.00'),
    ('verification_checklist_items', 'item_code', '산출물 채점 결과(점수 보고서)의 항목 코드와 매칭되는 항목 코드', 'VARCHAR(50) NOT NULL'),
    ('verification_checklist_items', 'category', "산출물 카테고리: 'html'(웹개발·AI API 카테고리) | 'svg'(원페이지 카테고리)", 'VARCHAR(20) NOT NULL'),
    ('rubric_items', 'item_code', '계획서 채점 결과(점수 보고서)의 항목 코드와 매칭되는 항목 코드', 'VARCHAR(50) NOT NULL'),
]


def _comments(sql: str) -> list[str]:
    return [m.group(1)[1:-1] for m in COMMENT.finditer(sql)]


def test_no_column_comment_mentions_a_dropped_table():
    bad = [(name, c[:60]) for c in _comments(SCHEMA) for name in DROPPED_TABLES if re.search(rf'\b{name}\b', c)]
    assert bad == [], f'칸 설명에 지운 표 이름이 남아 있다: {bad}'


@pytest.mark.parametrize(('table', 'column', 'comment', 'definition'), FIXES)
def test_schema_has_the_new_comment(table, column, comment, definition):
    block = re.search(rf'CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\) ', SCHEMA, re.S).group(1)
    line = next(ln for ln in block.splitlines() if re.match(rf'\s*{column} ', ln))
    assert definition in line
    assert comment in line


@pytest.mark.parametrize(('table', 'column', 'comment', 'definition'), FIXES)
def test_migration_007_sets_the_same_comment_and_definition(table, column, comment, definition):
    sql = MIGRATION.replace("''", "'")      # PREPARE에 넘기는 문자열 안의 따옴표 두 개를 풀어 비교한다
    statement = next(s for s in sql.split('PREPARE') if f'MODIFY COLUMN {column} ' in s and f'ALTER TABLE {table} ' in s)
    assert definition in statement
    assert comment in statement


def test_migration_007_changes_only_comments_and_is_guarded():
    upper = MIGRATION.upper()
    for forbidden in ('DROP TABLE', 'DROP COLUMN', 'DELETE FROM', 'TRUNCATE', 'UPDATE ', 'INSERT '):
        assert forbidden not in upper, f'007은 칸 설명만 바꿔야 한다: {forbidden}'
    assert MIGRATION.count('ALTER TABLE') == len(FIXES)
    assert MIGRATION.count('LOCATE(') == len(FIXES)       # 옛 이름이 남은 칸만 고치는 보호 조건(멱등)이 칸마다 있다
