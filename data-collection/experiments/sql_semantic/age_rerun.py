# -*- coding: utf-8 -*-
"""10단계 자격요건 추출에서 업력이 버려진 공고를 gpt-5.6-luna 로 다시 뽑는다 (2026-09-28, 사용자 요청 C).

  python -X utf8 -m experiments.sql_semantic.age_rerun --plan        대상·예상 비용만 (호출 없음)
  python -X utf8 -m experiments.sql_semantic.age_rerun               실제 호출 → reports/age_rerun_luna_<시각>/
  python -X utf8 -m experiments.sql_semantic.age_rerun --resume reports/age_rerun_luna_...   이어 하기
  python -X utf8 -m experiments.sql_semantic.age_rerun --apply reports/age_rerun_luna_…/results.jsonl [--plan]
      재추출 결과의 업력을 공용 DB notice_conditions 에 반영한다(C-3, 2026-09-28 사용자 요청). --plan 은 쓰지 않는다
  python -X utf8 -m experiments.sql_semantic.age_rerun --missing --sample 100 [--plan]
      4o-mini 가 업력을 **못 찾은** 공고(값 없음·버림 아님·"제한 없음" 명시 아님)에서 무작위 표본 (2026-09-28 사용자 요청)
      → reports/age_rerun_luna_missing_<시각>/. 새 규칙으로 업력이 얼마나 더 나오는지 본다

왜: 공용 DB notice_conditions 의 업력 값 중 204건이 "근거에 업력 표현이 없음"으로 버려졌다. 검사 목록
(AGE_EVIDENCE)이 "사업자등록 후 1년 이상 10년 미만", "사업개시일로부터 7년" 같은 실제 업력 표현을 몰랐기 때문이다.
버릴 때 숫자를 지우고 근거 문장만 남겨서, 다시 뽑아야 값을 알 수 있다.

어떻게: 문서 만들기·프롬프트·스키마는 매일 배치 10단계(collect/extract_conditions.py)와 **같다**. 모델만 luna 로 바꾼다.
결과는 넓힌 verify_age·verify_amount·dedupe_types 를 거친다.

**DB 에 쓰지 않는다.** 공용 DB 는 SELECT 만 한다. 결과는 reports/ 폴더에만 남기고, 반영(공용 DB 쓰기)은
사용자가 결과를 본 뒤 따로 정한다. 반영할 때는 매일 배치의 already_done 이 extractor_version 으로 거르므로
luna 결과를 4o-mini 로 덮어쓰지 않게 함께 고쳐야 한다(README 에 적는다).
"""
import argparse
import hashlib
import io
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MODEL = 'gpt-5.6-luna'
EFFORT = 'medium'
REJECTED = '근거에 업력 표현이 없음'
SEED = 20260928
REPORTS = os.path.join(ROOT, 'reports')
PREFIX = 'age_rerun_luna_'
# 호출 전 예상(보수적으로). 한글 1.3자 ≈ 1토큰, 프롬프트 약 2,000토큰, 출력(추론 포함) 약 1,500토큰
PROMPT_TOKENS, OUT_TOKENS, CHARS_PER_TOKEN = 2000, 1500, 1.3


def prompt_sha():
    from collect import extract_conditions as ec
    return hashlib.sha256((ec.SYSTEM + json.dumps(ec.SCHEMA, ensure_ascii=False, sort_keys=True)).encode('utf-8')).hexdigest()


def load_targets(connection, missing=False, sample=None):
    """대상 공고와 문서. [{notice_id, title, document, document_sha256, old}] (공고 ID 순).

    missing=False  업력이 "근거에 업력 표현이 없음"으로 버려진 공고
    missing=True   업력을 못 찾은 공고(값 없음·버림 없음·no_age_limit 아님). sample 이 있으면 SEED 로 무작위 표본
    """
    from collect import extract_conditions as ec
    import random
    cols_sql = ('SELECT notice_id, age_years_max, age_years_min, age_source_quote, age_rejected, '
                'pre_startup_allowed, business_type, amount_max_won, input_sha256, extractor_version '
                'FROM notice_conditions ')
    with connection.cursor() as cur:
        if missing:
            cur.execute(cols_sql + 'WHERE age_years_max IS NULL AND age_years_min IS NULL AND age_rejected IS NULL '
                        'AND NOT no_age_limit ORDER BY notice_id')
        else:
            cur.execute(cols_sql + 'WHERE age_rejected = %s ORDER BY notice_id', (REJECTED,))
        cols = [d[0] for d in cur.description]
        old = [dict(zip(cols, r)) for r in cur.fetchall()]
    population = len(old)
    if sample and sample < len(old):
        old = sorted(random.Random(SEED).sample(old, sample), key=lambda r: r['notice_id'])
    items = []
    for row in old:
        found = ec.pick_targets(connection, 1, only_missing_age=False, notice_id=row['notice_id'])
        if not found:
            continue                                # 첨부 본문이 사라졌다
        t = found[0]
        document = ec.build_document(t)
        bt = row['business_type']
        if isinstance(bt, (bytes, str)):
            try:
                bt = json.loads(bt)
            except ValueError:
                pass
        items.append({'notice_id': t['notice_id'], 'title': t['title'], 'source': t['notice_id'].split(':')[0],
                      'age_condition_raw': t['age_condition_raw'], 'document': document,
                      'document_sha256': ec.doc_hash(document),
                      'old': {'age_source_quote': row['age_source_quote'], 'pre_startup_allowed': row['pre_startup_allowed'],
                              'business_type': bt, 'amount_max_won': row['amount_max_won'],
                              'input_sha256': row['input_sha256'], 'extractor_version': row['extractor_version'],
                              'same_document': row['input_sha256'] == ec.doc_hash(document)}})
    return items, population


def reusable(checkpoint_rows, items):
    """체크포인트에서 다시 쓸 원답. 공고 ID 와 문서 해시가 **둘 다** 같은 줄만({공고 ID: 줄})."""
    sha_now = {it['notice_id']: it['document_sha256'] for it in items}
    return {r['notice_id']: r for r in checkpoint_rows
            if r.get('document_sha256') and r['document_sha256'] == sha_now.get(r['notice_id'])}


def estimate(items):
    from experiments.sql_semantic import industry_llm_sample as ils
    t_in = sum(PROMPT_TOKENS + len(it['document']) / CHARS_PER_TOKEN for it in items)
    t_out = OUT_TOKENS * len(items)
    p_in, p_out = ils.PRICES[MODEL]
    return int(t_in), int(t_out), round(t_in / 1e6 * p_in + t_out / 1e6 * p_out, 3)


def ask(client, item):
    from collect import extract_conditions as ec
    from experiments.sql_semantic import industry_llm_sample as ils
    started = time.time()
    response = client.chat.completions.create(
        model=MODEL, **ils.request_options(MODEL, EFFORT),
        messages=[{'role': 'system', 'content': ec.SYSTEM},
                  {'role': 'user', 'content': '공고 제목: %s\n\n공고문 발췌:\n%s' % (item['title'], item['document'])}],
        response_format={'type': 'json_schema', 'json_schema': ec.SCHEMA})
    data = json.loads(response.choices[0].message.content)
    usage = response.usage
    details = getattr(usage, 'completion_tokens_details', None)
    return data, {'in': usage.prompt_tokens, 'out': usage.completion_tokens,
                  'reasoning': getattr(details, 'reasoning_tokens', None) if details is not None else None,
                  'ms': round((time.time() - started) * 1000), 'model': getattr(response, 'model', None)}


def verified(raw):
    from collect import extract_conditions as ec
    data = json.loads(json.dumps(raw))
    data, age_reason = ec.verify_age(data)
    data, _ = ec.verify_amount(data)
    return ec.dedupe_types(data), age_reason


def outcome(row):
    """비교 한 줄: '살아남' | '업력 없음' | '다시 버림' ."""
    new = row['new']
    if new.get('age_years_max') is not None or new.get('age_years_min') is not None:
        return '살아남'
    if row['raw'].get('age_years_max') is not None or row['raw'].get('age_years_min') is not None:
        return '다시 버림'
    return '업력 없음'


def write_report(outdir, rows, failures, meta):
    from experiments.sql_semantic import industry_llm_sample as ils
    with io.open(os.path.join(outdir, 'results.jsonl'), 'w', encoding='utf-8', newline='\n') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + '\n')
    counts = {}
    for r in rows:
        counts[outcome(r)] = counts.get(outcome(r), 0) + 1
    t_in = sum(r['usage'].get('in') or 0 for r in rows)
    t_out = sum(r['usage'].get('out') or 0 for r in rows)
    p_in, p_out = ils.PRICES[MODEL]
    meta.update({'rows': len(rows), 'failed': len(failures), 'outcome': counts, 'tokens_in': t_in, 'tokens_out': t_out,
                 'cost_usd': round(t_in / 1e6 * p_in + t_out / 1e6 * p_out, 4)})
    with io.open(os.path.join(outdir, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(dict(meta, failures=failures), f, ensure_ascii=False, indent=1)

    def age_text(d):
        lo, hi = d.get('age_years_min'), d.get('age_years_max')
        if lo is None and hi is None:
            return '—'
        return '%s~%s년' % ('' if lo is None else lo, '' if hi is None else hi)

    lines = ['# 업력 재추출 (luna) — %s' % meta['run_at'][:19], '',
             ('대상: 공용 DB notice_conditions 에서 4o-mini 가 업력을 **못 찾은** %d건 중 무작위 표본 %d건(seed %d). '
              '**DB 에 쓰지 않았다.**' % (meta['population'], len(rows) + len(failures), SEED) if meta.get('missing') else
              '대상: 공용 DB notice_conditions 에서 업력이 "%s"으로 버려진 %d건 중 문서가 있는 %d건. '
              '**DB 에 쓰지 않았다.**' % (REJECTED, meta['population'], len(rows) + len(failures))), '',
             '| 결과 | 건수 |', '|---|---|']
    lines += ['| %s | %d |' % (k, v) for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]
    lines += ['| 호출 실패 | %d |' % len(failures), '',
              '토큰 입력 {:,} · 출력 {:,} · 약 ${:.4f} ({}@{})'.format(t_in, t_out, meta['cost_usd'], MODEL, EFFORT), '',
              '예비창업자 허용(pre_startup_allowed)이 true 인데 업력 값이 있으면, 업력은 기존 기업 쪽 조건이다(프롬프트 규칙 9).', '',
              '| 공고 | 결과 | 업력 | 예비 | 근거(새) | 예전 근거(버려짐) |', '|---|---|---|---|---|---|']
    for r in sorted(rows, key=lambda r: (outcome(r), r['notice_id'])):
        new = r['new']
        clip = lambda s: (s or '').replace('|', '/').replace('\n', ' ')[:90]     # noqa: E731
        lines.append('| `%s` %s | %s | %s | %s | %s | %s |' % (
            r['notice_id'].split(':')[-1], clip(r['title'])[:30], outcome(r) + (' (%s)' % r['age_rejected'] if r['age_rejected'] else ''),
            age_text(new), {True: '가능', False: '불가'}.get(new.get('pre_startup_allowed'), '—'),
            clip(new.get('age_source_quote') or r['raw'].get('age_source_quote')), clip(r['old']['age_source_quote'])))
    with io.open(os.path.join(outdir, 'summary.md'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    return meta


APPLY_NOTE = '업력 출처: luna 재추출(%s) — 추출기 버전은 4o-mini 그대로(배치가 덮어쓰지 않게)'


def apply_plan(results_path, db_rows):
    """재추출 결과 → notice_conditions 에 쓸 업력 값 목록과 건너뛴 이유별 수.

    db_rows: {공고 ID: {'input_sha256', 'age_years_min', 'age_years_max', 'age_source_quote', 'age_rejected', 'uncertain'}}
    반영 조건 — 원답에 **지금의** 업력 검사를 적용해 값이 남고(하한 0년만 있는 값 제외), 공용 DB 의 input_sha256 이
    재추출 때 문서 해시와 같을 것(공고문이 그 사이 바뀌었으면 그 결과는 옛 문서의 것이다).
    """
    from collect import extract_conditions as ec
    run = os.path.basename(os.path.dirname(os.path.abspath(results_path)))
    updates, skipped = [], {'no_age': 0, 'zero_only': 0, 'doc_changed': 0, 'not_in_db': 0, 'same': 0}
    with io.open(results_path, encoding='utf-8') as f:
        rows = [json.loads(line) for line in f if line.strip()]
    for row in rows:
        new, _ = ec.verify_age(json.loads(json.dumps(row.get('raw') or {})))
        lo, hi = new.get('age_years_min'), new.get('age_years_max')
        if lo is None and hi is None:
            skipped['no_age'] += 1
            continue
        if not lo and hi is None:
            skipped['zero_only'] += 1
            continue
        cur = db_rows.get(row['notice_id'])
        if cur is None:
            skipped['not_in_db'] += 1
            continue
        if cur['input_sha256'] != row['document_sha256']:
            skipped['doc_changed'] += 1
            continue
        if (cur['age_years_min'], cur['age_years_max'], cur['age_source_quote']) == (lo, hi, new.get('age_source_quote')):
            skipped['same'] += 1
            continue
        uncertain = cur.get('uncertain') or []
        if isinstance(uncertain, (str, bytes)):
            uncertain = json.loads(uncertain)
        note = APPLY_NOTE % run
        uncertain = [u for u in uncertain if not str(u).startswith('업력 추출 버림') and not str(u).startswith('업력 출처:')]
        updates.append({'notice_id': row['notice_id'], 'age_years_min': lo, 'age_years_max': hi,
                        'age_source_quote': new.get('age_source_quote'), 'age_rejected': None,
                        'uncertain': uncertain + [note], 'before': cur})
    return updates, skipped


def apply_to_db(results_path, dry_run=True, connection=None, backup_dir=None, say=print):
    """C-3 — 재추출 업력을 notice_conditions 에 반영한다. 업력 칸·uncertain 만 바꾸고 다른 칸·추출기 버전은 두지 않는다.

    쓰기 전에 바꿀 행의 원래 값을 backup_dir(기본: 결과 폴더)/applied_backup_<시각>.jsonl 에 남긴다.
    """
    own = connection is None
    if own:
        from shared import store_mysql
        connection = store_mysql.connect()
    try:
        cols = ('notice_id', 'input_sha256', 'age_years_min', 'age_years_max', 'age_source_quote', 'age_rejected',
                'uncertain', 'extractor_version')
        with connection.cursor() as cur:
            cur.execute('SELECT %s FROM notice_conditions' % ', '.join(cols))
            db_rows = {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}
        updates, skipped = apply_plan(results_path, db_rows)
        say('반영할 행 %d · 건너뜀 %s%s' % (len(updates), skipped, ' (계획만, 쓰지 않음)' if dry_run else ''))
        if dry_run or not updates:
            return {'updated': 0, 'planned': len(updates), 'skipped': skipped}
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup = os.path.join(backup_dir or os.path.dirname(os.path.abspath(results_path)), 'applied_backup_%s.jsonl' % stamp)
        with io.open(backup, 'w', encoding='utf-8', newline='\n') as f:
            for u in updates:
                f.write(json.dumps(u['before'], ensure_ascii=False, default=str) + '\n')
        # 한 행씩 실행해 실제로 바뀐 행 수를 센다(Codex 검수 — executemany 는 계획 수를 반영 수로 보고했다).
        # WHERE input_sha256 이 막은 행(그 사이 공고문이 바뀜)은 missed 로 따로 적는다
        changed, missed = 0, []
        with connection.cursor() as cur:
            for u in updates:
                n = cur.execute(
                    'UPDATE notice_conditions SET age_years_min=%s, age_years_max=%s, age_source_quote=%s, '
                    'age_rejected=%s, uncertain=%s WHERE notice_id=%s AND input_sha256=%s',
                    (u['age_years_min'], u['age_years_max'], u['age_source_quote'], u['age_rejected'],
                     json.dumps(u['uncertain'], ensure_ascii=False), u['notice_id'], u['before']['input_sha256']))
                if n:
                    changed += 1
                else:
                    missed.append(u['notice_id'])
        connection.commit()
        say('반영 %d행%s · 백업 %s' % (changed, (' · 반영 안 됨 %d행(문서 변경)' % len(missed)) if missed else '',
                                     os.path.relpath(backup, ROOT)))
        return {'updated': changed, 'planned': len(updates), 'missed': missed, 'skipped': skipped, 'backup': backup}
    finally:
        if own:
            connection.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plan', action='store_true', help='대상·예상 비용만. 호출하지 않는다')
    ap.add_argument('--resume', help='이어 할 결과 폴더')
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--missing', action='store_true', help='업력을 못 찾은 공고에서 고른다(기본: 버려진 공고)')
    ap.add_argument('--sample', type=int, help='무작위 표본 크기(--missing 과 함께)')
    ap.add_argument('--apply', help='이 재추출 결과(results.jsonl)의 업력을 공용 DB notice_conditions 에 반영한다')
    args = ap.parse_args(argv)
    if args.apply:
        apply_to_db(args.apply, dry_run=args.plan)
        return 0

    from shared import store_mysql
    from experiments.sql_semantic import industry_llm_sample as ils
    conn = store_mysql.connect()
    try:
        items, population = load_targets(conn, missing=args.missing, sample=args.sample)
    finally:
        conn.close()
    t_in, t_out, cost = estimate(items)
    head = ('못 찾은 %d건 중 표본' if args.missing else '버려진 %d건') % population
    print('{} · 문서 있음 {}건 · 예상 입력 약 {:,} · 출력 약 {:,} 토큰 · 약 ${:.2f} ({}@{})'.format(
        head, len(items), t_in, t_out, cost, MODEL, EFFORT))
    if args.plan:
        return 0

    from shared import config
    key = config.get('OPENAI_API_KEY')
    if not key:
        print('OPENAI_API_KEY 가 없다')
        return 1
    import openai
    client = openai.OpenAI(api_key=key)

    if args.resume:
        outdir = args.resume
        with io.open(os.path.join(outdir, 'run_spec.json'), encoding='utf-8') as f:
            spec = json.load(f)
        # 대상·프롬프트뿐 아니라 모델·모드·표본도 같아야 이어 한다(2026-09-28 Codex 검수 P2)
        now = {'notice_ids': [it['notice_id'] for it in items], 'prompt_sha256': prompt_sha(), 'model': MODEL,
               'effort': EFFORT, 'missing': args.missing, 'sample': args.sample}
        diff = [k for k, v in now.items() if spec.get(k, v if k in ('missing', 'sample') else None) != v]
        if diff:
            raise SystemExit('재개 폴더와 지금 실행이 다르다(%s) — 결과를 쓰지 않았다' % ', '.join(diff))
    else:
        outdir = os.path.join(REPORTS, PREFIX + ('missing_' if args.missing else '')
                              + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
        if os.path.exists(outdir):
            raise SystemExit('결과 폴더가 이미 있다: %s' % outdir)
        os.makedirs(outdir)
        with io.open(os.path.join(outdir, 'run_spec.json'), 'w', encoding='utf-8') as f:
            json.dump({'notice_ids': [it['notice_id'] for it in items], 'prompt_sha256': prompt_sha(),
                       'model': MODEL, 'effort': EFFORT, 'missing': args.missing, 'sample': args.sample,
                       'seed': SEED}, f, ensure_ascii=False, indent=1)

    from concurrent.futures import ThreadPoolExecutor, as_completed
    ck = os.path.join(outdir, 'checkpoint.jsonl')
    # 체크포인트 원답은 **같은 문서**일 때만 다시 쓴다. 중단 뒤 공고문이 바뀌었으면 다시 부른다(Codex 검수 P2).
    # 문서 해시가 없는 옛 체크포인트 줄은 쓰지 않는다
    done = reusable(ils.read_jsonl(ck) if os.path.exists(ck) else [], items)
    todo = [it for it in items if it['notice_id'] not in done]
    print('호출 %d건 (이미 있음 %d건) → %s' % (len(todo), len(done), os.path.relpath(outdir, ROOT)))
    failures = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(ask, client, it): it for it in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            it = futures[fut]
            try:
                data, usage = fut.result()
            except Exception as exc:
                failures.append({'notice_id': it['notice_id'], 'error': '%s: %s' % (type(exc).__name__, str(exc)[:200])})
                continue
            row = {'notice_id': it['notice_id'], 'document_sha256': it['document_sha256'], 'data': data, 'usage': usage}
            done[it['notice_id']] = row
            ils.append_jsonl(ck, row)
            if i % 25 == 0:
                print('  %d/%d' % (i, len(todo)))

    rows = []
    for it in items:
        r = done.get(it['notice_id'])
        if not r:
            continue
        new, reason = verified(r['data'])
        rows.append({'notice_id': it['notice_id'], 'title': it['title'], 'source': it['source'],
                     'document_sha256': it['document_sha256'], 'old': it['old'], 'raw': r['data'], 'new': new,
                     'age_rejected': reason, 'usage': r['usage']})
    meta = write_report(outdir, rows, failures, {
        'run_at': datetime.now(timezone.utc).isoformat(), 'model': MODEL, 'effort': EFFORT,
        'prompt_sha256': prompt_sha(), 'population': population, 'targets': len(items), 'db_write': False,
        'missing': args.missing, 'sample': args.sample, 'seed': SEED})
    print('결과 %s · 실패 %d · 약 $%.4f → %s' % (meta['outcome'], len(failures), meta['cost_usd'],
                                         os.path.join(os.path.relpath(outdir, ROOT), 'summary.md')))
    return 0 if not failures else 2


if __name__ == '__main__':
    sys.exit(main())
