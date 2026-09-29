# -*- coding: utf-8 -*-
"""실험 DB 준비 — 스키마 → 스냅샷 적재 → 정형화 → 임베딩.

  python -X utf8 -m experiments.sql_semantic.prepare --plan       무엇을 할지만 본다
  python -X utf8 -m experiments.sql_semantic.prepare --schema     실험 DB·테이블 만들기
  python -X utf8 -m experiments.sql_semantic.prepare --snapshot   공고 읽어와 저장 + 정형화
  python -X utf8 -m experiments.sql_semantic.prepare --embed      새 계약으로 벡터 만들기
  python -X utf8 -m experiments.sql_semantic.prepare --all
  python -X utf8 -m experiments.sql_semantic.prepare --reextract  저장된 공고로 조건만 다시 (EC2 안 읽음)

소스(운영) DB 는 **읽기만** 한다. 쓰기는 전부 로컬 실험 DB 에만 한다(config.guard 가 막는다).
기본 스냅샷 범위는 **접수 중인 공고**(마감일이 없거나 기준일 이후)다. 규칙을 먼저 정해 두고
결과를 보고 바꾸지 않는다.
"""
import argparse
import hashlib
import io
import json
import os
import sys
import time
import uuid
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from experiments.sql_semantic import conditions, config, embedding  # noqa: E402

SOURCE_FIELDS = ('notice_id', 'source', 'title', 'body', 'target_text', 'target_category',
                 'category', 'subcategory', 'organizer', 'region', 'age_condition_raw',
                 'apply_start', 'apply_end', 'apply_period_type', 'recruitment_status', 'url')

# 스냅샷 범위 — 결과를 보기 전에 정한 규칙
SCOPE_SQL = "(apply_end IS NULL OR apply_end >= %s)"
SCOPE_NAME = '접수 중(마감일 없음 또는 기준일 이후)'


# 조건 한 줄 UPSERT. 스냅샷 적재와 재추출이 **같은 SQL** 을 쓴다.
COND_SQL = (
    'INSERT INTO lab_conditions (notice_id,field,status,value_text,value_min,'
    'value_max,bound_note,evidence,extractor) VALUES (' + ','.join(['%s'] * 9) + ') '
    'ON DUPLICATE KEY UPDATE status=VALUES(status),value_text=VALUES(value_text),'
    'value_min=VALUES(value_min),value_max=VALUES(value_max),'
    'bound_note=VALUES(bound_note),evidence=VALUES(evidence),'
    'extractor=VALUES(extractor)')

# 벡터 한 줄 UPSERT. 다시 만들 때 **벡터와 함께 그 벡터를 설명하는 칸을 전부** 갱신한다
# (2026-09-18 Codex 리뷰 F3). 예전에는 model·dim·dtype·normalized 가 빠져 있어서, 차원이 틀린 행을
# 다시 만들어도 옛 dim 이 남아 검색에서 계속 손상으로 빠지고 다음 생성도 끝없이 반복됐다.
# 키(notice_id, contract)를 뺀 모든 칸이 UPDATE 에 있어야 한다 — 테스트가 이 SQL 문자열을 직접 확인한다.
VECTOR_COLUMNS = ('notice_id', 'contract', 'model', 'model_revision', 'dim', 'dtype', 'normalized',
                  'input_sha256', 'truncated', 'token_count', 'vector', 'created_at')
VECTOR_KEY = ('notice_id', 'contract')
VECTOR_SQL = (
    'INSERT INTO lab_vectors (' + ','.join(VECTOR_COLUMNS) + ') '
    'VALUES (' + ','.join(['%s'] * len(VECTOR_COLUMNS)) + ') '
    'ON DUPLICATE KEY UPDATE ' + ','.join('%s=VALUES(%s)' % (c, c) for c in VECTOR_COLUMNS
                                          if c not in VECTOR_KEY))


def needs_vector(row, digest, meta):
    """저장된 벡터를 그대로 써도 되는지. 하나라도 다르면 다시 만든다.

    입력 해시만 보면 모델 교체를 놓친다(리뷰 2번). 모델·리비전·차원에 더해 dtype·정규화까지 본다.
    """
    if not row.get('input_sha256'):
        return True
    return not (row.get('input_sha256') == digest
                and row.get('model') == meta['model']
                and (row.get('model_revision') or None) == (meta['model_revision'] or None)
                and row.get('dim') == meta['dim']
                and (row.get('dtype') or '') == meta['dtype']
                and bool(row.get('normalized')) == bool(meta['normalized']))


# 재추출에 쓰는 저장 공고 칸. lab_notices 는 지역을 region_raw 로 저장한다.
STORED_FIELDS = ('notice_id', 'title', 'body', 'target_text', 'target_category', 'category',
                 'subcategory', 'region_raw', 'age_condition_raw', 'apply_start', 'apply_end',
                 'apply_period_type')


def content_sha(row):
    parts = [str(row.get(k) or '') for k in
             ('title', 'body', 'target_text', 'target_category', 'category', 'subcategory')]
    return hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()


def read_source(as_of):
    """소스 DB 읽기 전용. SELECT 만 보낸다."""
    connection = config.source_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT ' + ','.join(SOURCE_FIELDS) +
                           ' FROM notices WHERE ' + SCOPE_SQL + ' ORDER BY notice_id',
                           (as_of.isoformat(),))
            columns = [d[0] for d in cursor.description]
            return [dict(zip(columns, r)) for r in cursor.fetchall()]
    finally:
        connection.close()


def apply_schema(say=print):
    connection = config.connect(create_database=True)
    try:
        sql = io.open(os.path.join(HERE, 'schema.sql'), encoding='utf-8').read()
        # 여러 번 실행해도 되게 만든다. CREATE TABLE 은 IF NOT EXISTS 가 있지만
        # CREATE INDEX 에는 없어서 두 번째 실행에서 1061(이미 있는 인덱스)이 난다.
        SKIP = {1061: '이미 있는 인덱스', 1060: '이미 있는 칼럼'}
        applied, skipped = 0, []
        with connection.cursor() as cursor:
            for statement in sql.split(';'):
                if not statement.strip():
                    continue
                try:
                    cursor.execute(statement)
                    applied += 1
                except Exception as exc:
                    code = exc.args[0] if exc.args else None
                    if code in SKIP:
                        skipped.append('%s (%s)' % (SKIP[code], statement.strip()[:40]))
                        continue
                    raise
        connection.commit()
        say('스키마 적용 완료 → %s (실행 %d · 건너뜀 %d)'
            % (config.lab_settings()['database'], applied, len(skipped)))
        for line in skipped:
            say('  건너뜀: %s' % line)
    finally:
        connection.close()


def store_snapshot(rows, as_of, say=print):
    """스냅샷 + 정형 조건 저장. 같은 공고를 다시 넣으면 갱신한다."""
    connection = config.connect()
    run_id = uuid.uuid4().hex
    started = datetime.now()
    try:
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO lab_runs (run_id,started_at,kind,as_of_date,note) '
                           'VALUES (%s,%s,%s,%s,%s)',
                           (run_id, started, 'snapshot', as_of, SCOPE_NAME))
            notice_sql = (
                'INSERT INTO lab_notices (notice_id,source,title,body,target_text,target_category,'
                'category,subcategory,organizer,region_raw,age_condition_raw,apply_start,apply_end,'
                'apply_period_type,recruitment_status,url,snapshot_at,content_sha256) '
                'VALUES (' + ','.join(['%s'] * 18) + ') '
                'ON DUPLICATE KEY UPDATE title=VALUES(title),body=VALUES(body),'
                'target_text=VALUES(target_text),target_category=VALUES(target_category),'
                'category=VALUES(category),subcategory=VALUES(subcategory),'
                'organizer=VALUES(organizer),region_raw=VALUES(region_raw),'
                'age_condition_raw=VALUES(age_condition_raw),apply_start=VALUES(apply_start),'
                'apply_end=VALUES(apply_end),apply_period_type=VALUES(apply_period_type),'
                'recruitment_status=VALUES(recruitment_status),url=VALUES(url),'
                'snapshot_at=VALUES(snapshot_at),content_sha256=VALUES(content_sha256)')
            cond_sql = COND_SQL
            now = datetime.now()
            all_conditions = []
            for row in rows:
                cursor.execute(notice_sql, (
                    row['notice_id'], row['source'], row['title'], row['body'],
                    row['target_text'], row['target_category'], row['category'],
                    row['subcategory'], row['organizer'], row['region'],
                    row['age_condition_raw'], row['apply_start'], row['apply_end'],
                    row['apply_period_type'], row['recruitment_status'], row['url'],
                    now, content_sha(row)))
                for cond in conditions.build(row):
                    all_conditions.append(cond)
                    cursor.execute(cond_sql, (
                        row['notice_id'], cond['field'], cond['status'], cond['value_text'],
                        cond['value_min'], cond['value_max'], cond['bound_note'],
                        cond['evidence'], cond['extractor']))
            cursor.execute('UPDATE lab_runs SET finished_at=%s WHERE run_id=%s',
                           (datetime.now(), run_id))
        connection.commit()
        say('공고 %d건 저장 · 조건 %d줄' % (len(rows), len(all_conditions)))
        return conditions.coverage(all_conditions)
    finally:
        connection.close()


def reextract_conditions(say=print, connection=None):
    """이미 저장된 `lab_notices` 에서 **조건만** 다시 뽑는다 (2026-09-21, F1 수정 반영용).

    `--snapshot` 과 다른 점
      · **소스(EC2) 를 부르지 않는다.** 공고 목록·본문이 그대로라 벡터가 낡지 않는다.
        스냅샷을 다시 뜨면 9/18 이후 공고가 섞여, 결과 차이가 추출기 때문인지 공고 때문인지 가릴 수 없다.
      · 덮어쓰기 전에 `lab_conditions` 를 `lab_conditions_bak_<시각>` 으로 통째로 복사한다.
        복사한 줄 수가 원본과 다르면 아무것도 덮어쓰지 않고 멈춘다.
      · 추출기 버전(`conditions.EXTRACTOR`)이 각 줄에 새로 찍힌다.
    """
    own = connection is None
    connection = connection or config.connect()
    stamp = datetime.now().strftime('%Y%m%d%H%M%S')
    backup = 'lab_conditions_bak_' + stamp       # 시각만 쓴다. 외부 입력이 들어가지 않는다
    run_id = uuid.uuid4().hex
    try:
        with connection.cursor() as cursor:
            # ① 백업. CREATE TABLE 은 MySQL 에서 자동 커밋되므로 덮어쓰기보다 **먼저** 끝난다
            cursor.execute('CREATE TABLE `%s` LIKE lab_conditions' % backup)
            cursor.execute('INSERT INTO `%s` SELECT * FROM lab_conditions' % backup)
            cursor.execute('SELECT COUNT(*) FROM lab_conditions')
            original = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM `%s`' % backup)
            copied = cursor.fetchone()[0]
            if copied != original:
                raise RuntimeError('백업 줄 수가 다르다 (원본 %s · 백업 %s). 덮어쓰지 않는다.'
                                   % (original, copied))
            say('백업 %s — %d줄' % (backup, copied))
            connection.commit()

            # ② 전후 비교용으로 지금 값을 읽어 둔다
            cursor.execute('SELECT notice_id, field, status, value_text, extractor FROM lab_conditions')
            before = {(r[0], r[1]): (r[2], r[3], r[4]) for r in cursor.fetchall()}

            # ③ 저장된 공고에서 다시 뽑는다
            cursor.execute('SELECT ' + ','.join(STORED_FIELDS) + ' FROM lab_notices ORDER BY notice_id')
            columns = [d[0] for d in cursor.description]
            notices = [dict(zip(columns, r)) for r in cursor.fetchall()]
            cursor.execute('INSERT INTO lab_runs (run_id,started_at,kind,as_of_date,note) '
                           'VALUES (%s,%s,%s,%s,%s)',
                           (run_id, datetime.now(), 'reextract', None,
                            '%s 재추출 · 백업 %s' % (conditions.EXTRACTOR, backup)))
            all_conditions, changed = [], {}
            for notice in notices:
                notice['region'] = notice.pop('region_raw')   # 추출기는 region 칸을 읽는다
                for cond in conditions.build(notice):
                    all_conditions.append(cond)
                    old = before.get((notice['notice_id'], cond['field']))
                    if not old or old[0] != cond['status'] or (old[1] or '') != (cond['value_text'] or ''):
                        key = '%s %s->%s' % (cond['field'], old[0] if old else '(없음)', cond['status'])
                        changed[key] = changed.get(key, 0) + 1
                    cursor.execute(COND_SQL, (
                        notice['notice_id'], cond['field'], cond['status'], cond['value_text'],
                        cond['value_min'], cond['value_max'], cond['bound_note'],
                        cond['evidence'], cond['extractor']))
            cursor.execute('UPDATE lab_runs SET finished_at=%s WHERE run_id=%s',
                           (datetime.now(), run_id))
        connection.commit()
        say('공고 %d건 · 조건 %d줄 재추출 (%s)' % (len(notices), len(all_conditions),
                                             conditions.EXTRACTOR))
        return {'backup_table': backup, 'notices': len(notices),
                'condition_rows': len(all_conditions), 'extractor': conditions.EXTRACTOR,
                'changed': dict(sorted(changed.items(), key=lambda kv: -kv[1])),
                'coverage': conditions.coverage(all_conditions)}
    except Exception:
        connection.rollback()
        raise
    finally:
        if own:
            connection.close()


def build_vectors(limit=None, batch=8, say=print, connection=None, model=None):
    """새 계약으로 벡터를 만들어 저장한다. 저장된 벡터가 지금 조건과 다 맞으면 건너뛴다.

    connection·model 을 주면 그대로 쓴다(테스트에서 가짜를 넣는다).
    """
    own = connection is None
    connection = connection or config.connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT n.notice_id,n.title,n.body,n.target_text,n.target_category,'
                'n.category,n.subcategory, v.input_sha256, v.model, v.model_revision, v.dim,'
                ' v.dtype, v.normalized '
                'FROM lab_notices n LEFT JOIN lab_vectors v '
                ' ON v.notice_id=n.notice_id AND v.contract=%s ORDER BY n.notice_id',
                (embedding.CONTRACT,))
            columns = [d[0] for d in cursor.description]
            rows = [dict(zip(columns, r)) for r in cursor.fetchall()]

        meta = embedding.meta()
        todo = []
        for row in rows:
            text, sources = embedding.build_input(row)
            digest = embedding.input_sha256(text)
            if needs_vector(row, digest, meta):
                todo.append((row['notice_id'], text, digest, sources))
        if limit:
            todo = todo[:limit]
        say('벡터를 만들 공고 %d건 (전체 %d건 중)' % (len(todo), len(rows)))
        if not todo:
            return {'created': 0, 'skipped': len(rows)}

        model = model or embedding.load_model()
        created, started = 0, time.time()
        with connection.cursor() as cursor:
            for i in range(0, len(todo), batch):
                chunk = todo[i:i + batch]
                vectors = embedding.encode(model, [t for _n, t, _d, _s in chunk])
                for (notice_id, text, digest, _sources), vector in zip(chunk, vectors):
                    tokens, truncated = embedding.token_info(text)
                    values = {'notice_id': notice_id, 'contract': meta['contract'],
                              'model': meta['model'], 'model_revision': meta['model_revision'],
                              'dim': int(len(vector)), 'dtype': meta['dtype'],
                              'normalized': 1 if meta['normalized'] else 0,
                              'input_sha256': digest, 'truncated': 1 if truncated else 0,
                              'token_count': tokens, 'vector': embedding.pack(vector),
                              'created_at': datetime.now()}
                    cursor.execute(VECTOR_SQL, tuple(values[c] for c in VECTOR_COLUMNS))
                    created += 1
                connection.commit()
                if (i // batch) % 10 == 0 or i + batch >= len(todo):
                    done = min(i + batch, len(todo))
                    say('  %d/%d · %.0f초' % (done, len(todo), time.time() - started))
        return {'created': created, 'skipped': len(rows) - len(todo)}
    finally:
        if own:
            connection.close()


def fix_token_meta(say=print, batch=200):
    """이미 저장된 벡터의 토큰 수·잘림 여부만 채운다. **벡터는 다시 만들지 않는다.**

    Codex 리뷰 5번 지적처럼 초기 구현이 `truncated=0` 을 상수로 넣었다. 메타데이터만
    틀린 것이므로 전량 재임베딩 대신 이 경로로 보정한다.
    """
    connection = config.connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT n.notice_id,n.title,n.body,n.target_text,n.target_category,'
                'n.category,n.subcategory,v.token_count '
                'FROM lab_vectors v JOIN lab_notices n ON n.notice_id=v.notice_id '
                'WHERE v.contract=%s ORDER BY n.notice_id', (embedding.CONTRACT,))
            columns = [d[0] for d in cursor.description]
            rows = [dict(zip(columns, r)) for r in cursor.fetchall()]
        todo = [r for r in rows if r.get('token_count') is None]
        say('토큰 정보를 채울 벡터 %d건 (전체 %d건)' % (len(todo), len(rows)))
        updated, truncated_count, started = 0, 0, time.time()
        with connection.cursor() as cursor:
            for i, row in enumerate(todo, 1):
                text, _sources = embedding.build_input(row)
                tokens, truncated = embedding.token_info(text)
                truncated_count += 1 if truncated else 0
                cursor.execute('UPDATE lab_vectors SET token_count=%s, truncated=%s '
                               ' WHERE notice_id=%s AND contract=%s',
                               (tokens, 1 if truncated else 0, row['notice_id'],
                                embedding.CONTRACT))
                updated += 1
                if i % batch == 0:
                    connection.commit()
                    say('  %d/%d · %.0f초' % (i, len(todo), time.time() - started))
        connection.commit()
        say('보정 %d건 · 상한(%d토큰) 초과 %d건' % (updated, embedding.MAX_TOKENS, truncated_count))
        return {'updated': updated, 'truncated': truncated_count}
    finally:
        connection.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--schema', action='store_true')
    ap.add_argument('--snapshot', action='store_true')
    ap.add_argument('--embed', action='store_true')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--as-of', dest='as_of', default='')
    ap.add_argument('--limit', type=int, help='벡터 생성 건수 상한 (시험용)')
    ap.add_argument('--reextract', action='store_true',
                    help='저장된 공고에서 조건만 다시 뽑는다. 소스(EC2)를 읽지 않고 먼저 백업한다')
    ap.add_argument('--fix-token-meta', dest='fix_meta', action='store_true',
                    help='이미 저장된 벡터의 토큰 수·잘림만 채운다 (재임베딩 없음)')
    args = ap.parse_args()
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()

    try:
        lab = config.lab_settings()
        config.guard(lab)
    except config.LabConfigError as exc:
        print('실험 DB 설정 확인 실패\n%s' % exc)
        return 2
    print('실험 DB : %s@%s:%s / %s' % (lab['user'], lab['host'], lab['port'], lab['database']))
    print('스냅샷 범위 : %s · 기준일 %s' % (SCOPE_NAME, as_of))

    if args.plan:
        rows = read_source(as_of)
        print('소스에서 읽을 공고 %d건' % len(rows))
        sample = conditions.coverage([c for row in rows[:200] for c in conditions.build(row)])
        print('앞 200건 기준 필드별 확보율:')
        for field, info in sample.items():
            print('  %-20s known %4d · no_limit %4d · unknown %4d (%.0f%%)'
                  % (field, info['known'], info['no_limit'], info['unknown'],
                     info['known_ratio'] * 100))
        print('\n--plan 이라 아무것도 쓰지 않았다.')
        return 0

    if args.schema or args.all:
        apply_schema()
    if args.snapshot or args.all:
        rows = read_source(as_of)
        coverage = store_snapshot(rows, as_of)
        print(json.dumps(coverage, ensure_ascii=False, indent=1))
    if args.embed or args.all:
        print(json.dumps(build_vectors(limit=args.limit), ensure_ascii=False))
    if args.fix_meta:
        print(json.dumps(fix_token_meta(), ensure_ascii=False))
    if args.reextract:
        print(json.dumps(reextract_conditions(), ensure_ascii=False, indent=1))
    if not any((args.schema, args.snapshot, args.embed, args.all, args.fix_meta, args.reextract)):
        ap.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
