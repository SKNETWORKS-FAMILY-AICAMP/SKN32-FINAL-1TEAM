# -*- coding: utf-8 -*-
"""13단계 — 공고 판정(신청자 유형·업종)을 공용 MySQL 로 올린다 (2026-09-28).

  python -X utf8 -m collect.upload_judgments --plan          올릴 것이 몇 건인지만 센다 (DB 읽기만)
  python -X utf8 -m collect.upload_judgments                 올린다 (바뀐 행만 UPSERT)
  python -X utf8 -m collect.upload_judgments --only types    신청자 유형만 (industries 도 있다)

왜 필요한가. 신청자 유형·업종 판정은 배치 PC 의 파일에만 있어 팀원·EC2 서비스가 쓸 수 없다.
8단계가 벡터를 올리는 것처럼 공용 DB 로 옮긴다. 테이블 설계: docs/guides/JUDGMENT_TABLES.md,
SQL: db/mysql_migration_006_notice_judgments.sql

무엇을 올리나
  notice_applicant_types  ← search/applicant_types.default_path() (매일 11단계가 갱신하는 누적 파일)
                            서비스 결론(pre_founder_verdict·registered_only_phrase)은 search/applicant_types 의
                            같은 함수로 계산한다 — DB 를 읽는 쪽이 서비스와 같은 결론을 보게. 발췌 밖 원문에 '예비창업'
                            이 있는 strong 불가도 서비스처럼 NULL(확인 필요)로 올린다(2026-09-29 Codex 재검수 P1-2, A안)
  notice_industries       ← data/industries/results.jsonl (12단계 누적) · 없으면 final6 · 또는 --industry-results
                            allowed_sections·usable_for_rank 는 올릴 때의 코드 규칙(industry_groups·industry_rank)으로 계산

**바뀐 행만 올린다.** DB 의 지금 값과 칸마다 비교해 다른 행만 INSERT … ON DUPLICATE KEY UPDATE 한다.
공용 DB 의 notices 에 없는 공고(수집에서 빠진 공고)는 외래 키 때문에 올리지 않고 센다.
DB 에서 행을 지우지 않는다(공고가 지워지면 외래 키 CASCADE 가 지운다).
"""
import argparse
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

INDUSTRY_SEED = os.path.join(ROOT, 'reports', 'industry_llm_full_luna_20260928_final6', 'results.jsonl')
INDUSTRY_DAILY = os.path.join(ROOT, 'data', 'industries', 'results.jsonl')     # 12단계 누적(collect/industry_daily.py)


def industry_default_path():
    """12단계 누적 파일이 있으면 그것, 없으면 2026-09-28 전량 결과(final6)."""
    return INDUSTRY_DAILY if os.path.exists(INDUSTRY_DAILY) else INDUSTRY_SEED


INDUSTRY_RESULTS = INDUSTRY_SEED      # 옛 이름(테스트·문서 호환)
BATCH = 200
MIN_FILE_RATIO = 0.9      # 결과 파일의 공고가 DB 의 이만큼도 안 되면 경고한다(2026-09-29 — 막지 않고 경고만)

TYPE_COLUMNS = ('notice_id', 'pre_founder_verdict', 'registered_only_phrase', 'varies',
                'pre_founder_status', 'pre_founder_strength', 'pre_founder_evidence',
                'sole_proprietor_status', 'sole_proprietor_strength', 'sole_proprietor_evidence',
                'corporation_status', 'corporation_strength', 'corporation_evidence', 'reason',
                'document_sha256', 'prompt_sha256', 'extractor_version', 'prompt_tokens', 'completion_tokens')
INDUSTRY_COLUMNS = ('notice_id', 'status', 'allowed_sections', 'usable_for_rank', 'allowed', 'excluded',
                    'list_complete', 'quote', 'quote_role', 'truncated', 'scope_unresolved', 'excerpt_chars',
                    'verify_profile', 'document_sha256', 'prompt_sha256', 'extractor_version', 'source_run',
                    'prompt_tokens', 'completion_tokens')
JSON_COLUMNS = {'allowed_sections', 'allowed', 'excluded'}
BOOL_COLUMNS = {'varies', 'usable_for_rank', 'list_complete', 'truncated', 'scope_unresolved'}
TABLES = {'types': ('notice_applicant_types', TYPE_COLUMNS), 'industries': ('notice_industries', INDUSTRY_COLUMNS)}


def read_jsonl(path):
    with io.open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def read_meta(results_path):
    path = os.path.join(os.path.dirname(results_path), 'meta.json')
    if not os.path.exists(path):
        return {}
    with io.open(path, encoding='utf-8') as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────── 행 만들기 (DB 없이 테스트한다)

def type_rows(path, documents=None):
    """신청자 유형 결과 파일 → 테이블 행 목록.

    documents: search.applicant_types.current_documents() 값(지금 공고문). 서비스와 같이 발췌 밖 언급을 확인한다.
    없거나 그 공고의 지문이 다르면 strong 불가를 'blocked' 로 올리지 않는다(NULL, 확인 필요 — Codex 재재검수 P2).
    """
    from search import applicant_types as at
    from experiments.sql_semantic import applicant_type_llm as atl
    from collect import applicant_type_daily as atd
    meta = read_meta(path)
    table = at.load(path)
    table['notices'] = at.mark_unread(table['notices'], documents)
    out = []
    for row in read_jsonl(path):
        llm = row.get('llm')
        if not llm:
            continue
        nid = row['notice_id']
        info = table['notices'].get(nid) or {}
        reg = info.get('registered_only')

        def cell(key):
            c = llm.get(key) or {}
            return c.get('status') or 'not_mentioned', c.get('strength'), c.get('evidence')

        pre, sole, corp = cell('pre_founder'), cell('sole_proprietor'), cell('corporation')
        usage = row.get('usage') or {}
        out.append({
            'notice_id': nid, 'pre_founder_verdict': at.pre_founder(table, nid),
            'registered_only_phrase': (reg or {}).get('phrase'), 'varies': bool(llm.get('varies')),
            'pre_founder_status': pre[0], 'pre_founder_strength': pre[1], 'pre_founder_evidence': pre[2],
            'sole_proprietor_status': sole[0], 'sole_proprietor_strength': sole[1], 'sole_proprietor_evidence': sole[2],
            'corporation_status': corp[0], 'corporation_strength': corp[1], 'corporation_evidence': corp[2],
            'reason': llm.get('reason') or None,
            'document_sha256': row['document_sha256'], 'prompt_sha256': meta.get('prompt_sha256'),
            # 행마다 뽑은 엔진(2026-10-07 결정 0013). 엔진이 없는 옛 행은 gpt-5.6-luna@medium
            'extractor_version': ('applicant_type_llm ' + atd.engine_of(row))[:64],
            'prompt_tokens': usage.get('in'), 'completion_tokens': usage.get('out')})
    return out


def industry_rows(path):
    """업종 결과 파일 → 테이블 행 목록."""
    from search import industry_rank
    from experiments.sql_semantic import industry_groups
    from collect import industry_daily as ind
    meta = read_meta(path)
    out = []
    for row in read_jsonl(path):
        llm = row.get('llm')
        if not llm:
            continue
        allowed = [{'text': a.get('text'), 'label': a.get('label') or None, 'evidence': a.get('evidence')}
                   for a in llm.get('allowed') or []]
        excluded = [{'text': a.get('text'), 'label': a.get('label') or None, 'evidence': a.get('evidence')}
                    for a in llm.get('excluded') or []]
        status = llm.get('industry_status') or llm.get('status') or 'unknown'
        sections = industry_groups.allowed_sections([a['text'] for a in allowed]) if status == 'known' and allowed else None
        usage = row.get('usage') or {}
        out.append({
            'notice_id': row['notice_id'], 'status': status,
            'allowed_sections': sorted(sections) if sections else None,
            'usable_for_rank': bool(industry_rank.usable_sections(llm)),
            'allowed': allowed or None, 'excluded': excluded or None,
            'list_complete': llm.get('list_complete'), 'quote': llm.get('quote') or None,
            'quote_role': llm.get('quote_role'), 'truncated': bool(llm.get('truncated')),
            'scope_unresolved': bool(llm.get('scope_unresolved')), 'excerpt_chars': llm.get('excerpt_cap'),
            'verify_profile': llm.get('profile') or meta.get('profile'),
            'document_sha256': row['document_sha256'], 'prompt_sha256': meta.get('prompt_sha256'),
            # 행마다 뽑은 엔진(2026-10-07 결정 0013). 엔진이 없는 옛 행은 gpt-5.6-luna@medium
            'extractor_version': ('industry_llm %s %s' % (meta.get('prompt') or '', ind.engine_of(row))).replace('  ', ' ')[:64],
            'source_run': (row.get('source_run') or '')[:80] or None,
            'prompt_tokens': usage.get('in'), 'completion_tokens': usage.get('out')})
    return out


def normalize(row, columns):
    """비교용으로 값을 맞춘다(JSON 은 파싱, 불리언은 0/1)."""
    out = {}
    for c in columns:
        v = row.get(c)
        if c in JSON_COLUMNS and isinstance(v, (str, bytes)):
            v = json.loads(v)
        if c in BOOL_COLUMNS or (c == 'list_complete'):
            v = None if v is None else int(bool(v))
        out[c] = v
    return out


def plan(rows, current, known_notices, columns):
    """(올릴 행, {'new', 'changed', 'same', 'no_notice'})."""
    todo, counts = [], {'new': 0, 'changed': 0, 'same': 0, 'no_notice': 0}
    for row in rows:
        if row['notice_id'] not in known_notices:
            counts['no_notice'] += 1
            continue
        now = current.get(row['notice_id'])
        if now is None:
            counts['new'] += 1
        elif normalize(now, columns) == normalize(row, columns):
            counts['same'] += 1
            continue
        else:
            counts['changed'] += 1
        todo.append(row)
    return todo, counts


# ─────────────────────────────────────────────────────────── DB

def read_current(connection, table, columns):
    with connection.cursor() as cur:
        cur.execute('SELECT %s FROM %s' % (', '.join(columns), table))
        return {r[0]: dict(zip(columns, r)) for r in cur.fetchall()}


def notice_ids(connection):
    with connection.cursor() as cur:
        cur.execute('SELECT notice_id FROM notices')
        return {r[0] for r in cur.fetchall()}


def upsert(connection, table, columns, rows):
    sql = 'INSERT INTO %s (%s) VALUES (%s) ON DUPLICATE KEY UPDATE %s' % (
        table, ', '.join(columns), ', '.join(['%s'] * len(columns)),
        ', '.join('%s=VALUES(%s)' % (c, c) for c in columns[1:]))

    def value(row, c):
        v = row.get(c)
        if c in JSON_COLUMNS and v is not None:
            return json.dumps(v, ensure_ascii=False)
        if c in BOOL_COLUMNS or c == 'list_complete':
            return None if v is None else int(bool(v))
        return v

    with connection.cursor() as cur:
        for i in range(0, len(rows), BATCH):
            cur.executemany(sql, [tuple(value(r, c) for c in columns) for r in rows[i:i + BATCH]])
            connection.commit()


def run(only=None, dry_run=False, connection=None, types_path=None, industry_path=None, say=print):
    """배치·명령에서 부르는 진입점. {'types': {...}, 'industries': {...}}. dry_run 이면 쓰지 않는다."""
    from search import applicant_types as at
    sources = {'types': (types_path or at.default_path(), type_rows),
               'industries': (industry_path or industry_default_path(), industry_rows)}
    own = connection is None
    if own:
        from shared import store_mysql
        connection = store_mysql.connect()
    result = {}
    try:
        known = notice_ids(connection)
        for key, (path, build) in sources.items():
            if only and key != only:
                continue
            table, columns = TABLES[key]
            if not os.path.exists(path):
                result[key] = {'error': '결과 파일이 없다: %s' % path}
                say('  %s — 결과 파일이 없다' % table)
                continue
            if key == 'types':
                # 서비스(load_auto)와 같은 결론을 올리려면 지금 공고문이 필요하다. 못 읽으면 이 표는 올리지 않는다
                try:
                    rows = build(path, at.current_documents(connection))
                except Exception as exc:
                    result[key] = {'error': '지금 공고문을 읽지 못해 올리지 않는다(%s)' % type(exc).__name__}
                    say('  %s — %s' % (table, result[key]['error']))
                    continue
            else:
                rows = build(path)
            current = read_current(connection, table, columns)
            todo, counts = plan(rows, current, known, columns)
            counts.update(source=os.path.relpath(path, ROOT), rows=len(rows), uploaded=0)
            # 같은 공고가 파일에 두 번 이상 있으면 어느 줄이 맞는지 모른다 — 파일 이상으로 보고 이 표는 올리지 않는다
            # (2026-09-29 Codex 재검수 P2: 중복 줄이 행 수를 부풀려 90% 검사를 통과하던 문제). DB 는 전날 값 그대로다
            ids = [r['notice_id'] for r in rows]
            duplicated = len(ids) - len(set(ids))
            if duplicated:
                counts['error'] = '같은 공고가 결과 파일에 겹쳐 있다(%d줄) — 파일 이상으로 보고 올리지 않는다' % duplicated
                say('  %s — %s' % (table, counts['error']))
                result[key] = counts
                continue
            # 파일에 있는 공고가 DB 보다 크게 적으면 **경고만** 남기고 맞는 행은 올린다(2026-09-29 — 예전에는 전부 막아
            # 정상 갱신까지 멈췄다). 올리지 않아도 DB 행을 지우지는 않고, 서비스가 공고마다 지문을 확인해 옛 판정은
            # 쓰지 않으므로(search/applicant_types.fresh_only) 여기서 전부 막을 이유가 없다. 공고 수는 지금 notices 에 있는 것만 센다
            in_file = set(ids) & known
            in_db = set(current) & known
            if in_db and len(in_file) < MIN_FILE_RATIO * len(in_db):
                counts['warning'] = '결과 파일의 공고(%d)가 DB(%d)의 %d%% 미만 — 파일이 줄었는지 확인 필요(맞는 행은 올림)' % (
                    len(in_file), len(in_db), MIN_FILE_RATIO * 100)
                say('  %s — 경고: %s' % (table, counts['warning']))
            if todo and not dry_run:
                upsert(connection, table, columns, todo)
                counts['uploaded'] = len(todo)
            say('  %s ← %s · 새로 %d · 바뀜 %d · 같음 %d · 공고 없음 %d%s' % (
                table, counts['source'], counts['new'], counts['changed'], counts['same'], counts['no_notice'],
                ' · 올림 %d' % counts['uploaded'] if not dry_run else ' (계획만, 쓰지 않음)'))
            result[key] = counts
    finally:
        if own:
            connection.close()
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plan', action='store_true', help='올릴 건수만 센다(DB 읽기만)')
    ap.add_argument('--only', choices=sorted(TABLES), help='한 테이블만')
    ap.add_argument('--industry-results', dest='industry_results', help='업종 결과 파일(기본: 12단계 누적 → 없으면 final6)')
    args = ap.parse_args(argv)
    result = run(only=args.only, dry_run=args.plan, industry_path=args.industry_results)
    return 1 if any(v.get('error') for v in result.values()) else 0


if __name__ == '__main__':
    sys.exit(main())
