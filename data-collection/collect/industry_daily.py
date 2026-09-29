# -*- coding: utf-8 -*-
"""매일 배치 12단계 — 새 공고·바뀐 공고의 신청 가능 업종을 LLM 으로 뽑는다 (2026-09-28).

  python -X utf8 -m collect.industry_daily            단독 실행(배치와 같은 동작)
  python -X utf8 -m collect.industry_daily --plan     할 일·예상 비용만 (호출 없음)

2026-09-28 사용자 요청 — 업종 판정도 신청자 유형(11단계)처럼 매일 채워 공용 DB(notice_industries, 13단계)에 올린다.
추출 방법은 전량 실행과 **같다**(experiments/sql_semantic/industry_llm_sample.py 의 문서 만들기·프롬프트 v3·
코드 검사 rough, gpt-5.6-luna@medium). 공고는 공용 DB 에서 읽는다(SELECT 만).

  누적 결과  data/industries/results.jsonl   13단계가 이 파일을 공용 DB 로 올린다
  체크포인트 data/industries/checkpoint.jsonl  성공한 호출을 바로 적는다
  상태      data/industries/daily_state.json  날짜별 호출 수·실패 횟수
  기록      data/industries/meta.json

**바뀐 것만 부른다.** 문서 해시가 누적 결과와 같으면 건너뛴다. 18,000자로 길게 다시 읽은 행은 그 길이로 비교한다
(industry_llm_sample.only_new). 처음 실행하면 2026-09-28 전량 결과(final6, 2,476건)로 시작한다.
**하루 상한** DAILY_LIMIT 건(날짜 기준, 부르기 전에 센다). 같은 문서로 MAX_FAILURES 번 실패하면 멈춘다.
같은 폴더를 쓰는 실행은 하나만 돈다(run.lock). 6,000자 발췌에서 잘린 공고는 truncated 로 남는다 — 순위에 쓰지 않는다.
"""
import argparse
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUT_DIR = os.path.join(ROOT, 'data', 'industries')
REPORTS = os.path.join(ROOT, 'reports')
SEED_RUN = os.path.join(REPORTS, 'industry_llm_full_luna_20260928_final6', 'results.jsonl')
MODEL, EFFORT, PROMPT, PROFILE = 'gpt-5.6-luna', 'medium', 'v3', 'rough'
DAILY_LIMIT = 300
MAX_FAILURES = 3
KST = timezone(timedelta(hours=9))
KEEP = ('notice_id', 'title', 'category', 'target_category', 'regex', 'llm', 'usage', 'doc_chars',
        'attachments_count', 'document_sha256', 'attachment_sha256', 'source_run', 'run_at')


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with io.open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def write_atomic(path, rows):
    tmp = path + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    os.replace(tmp, path)


def load_state(path, today):
    state = {}
    if os.path.exists(path):
        with io.open(path, encoding='utf-8') as f:
            state = json.load(f)
    if state.get('date') != today:
        state['date'], state['attempted'] = today, 0
    state.setdefault('attempted', 0)
    state.setdefault('failures', {})
    return state


def save_state(path, state):
    tmp = path + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def ensure_seed(out_dir, seed=None):
    """누적 파일이 없으면 전량 결과(final6)를 복사해 시작한다. 이미 있으면 그대로."""
    results = os.path.join(out_dir, 'results.jsonl')
    if not os.path.exists(results):
        rows = read_jsonl(seed or SEED_RUN)
        if rows:
            write_atomic(results, rows)
    return results


def run_batch(limit=None, say=print, workers=4, connection=None, call=None, out_dir=None, today=None,
              reports_dir=None, seed=None):
    """배치·단독 실행의 진입점. {'extracted', 'skipped', 'deferred', 'failed', 'gave_up', 'attempted_today', ...}."""
    from collect import job_lock
    out_dir = out_dir or OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    try:
        with job_lock.acquire(os.path.join(out_dir, 'run.lock')):
            return _run_batch(limit, say, workers, connection, call, out_dir, today, reports_dir, seed)
    except job_lock.JobBusy:
        say('업종 추출이 이미 실행 중이다. 이번에는 건너뛴다')
        return {'error': 'busy', 'extracted': 0, 'skipped': 0, 'deferred': 0}


def _run_batch(limit, say, workers, connection, call, out_dir, today, reports_dir, seed):
    from experiments.sql_semantic import industry_llm_sample as ils
    started = time.time()
    limit = DAILY_LIMIT if limit is None else max(0, limit)
    results_path = ensure_seed(out_dir, seed)
    checkpoint_path = os.path.join(out_dir, 'checkpoint.jsonl')
    state_path = os.path.join(out_dir, 'daily_state.json')
    state = load_state(state_path, today or datetime.now(KST).date().isoformat())
    engine = ils.engine_id(MODEL, EFFORT)

    own = connection is None
    if own:
        from shared import store_mysql
        connection = store_mysql.connect()
    try:
        items = ils.load_items_shared(connection, ils.pick_shared(connection))
    finally:
        if own:
            connection.close()
    by_id = {it['notice_id']: it for it in items}
    existing = {r['notice_id']: r for r in read_jsonl(results_path)}
    run_name = 'industry_daily_' + state['date'].replace('-', '')

    # 끊긴 실행의 체크포인트 반영(같은 문서·같은 프롬프트일 때만)
    for row in read_jsonl(checkpoint_path):
        it = by_id.get(row.get('notice_id'))
        # 문서·프롬프트·스키마·모델이 모두 같을 때만 다시 쓴다(Codex 검수 — 모델·스키마를 바꾼 뒤 옛 원답 재사용 방지)
        if (it and row.get('document_sha256') == it['document_sha256']
                and row.get('prompt_sha256') == ils.prompt_sha256(PROMPT)
                and row.get('schema_sha256') == ils.schema_sha256(PROMPT) and row.get('engine') == engine):
            existing[it['notice_id']] = _result_row(it, row['data'], row['usage'], ils, row.get('run_name') or run_name)

    todo_all, skipped = ils.only_new(items, out_dir, reports_dir or REPORTS) if existing else (items, 0)
    todo_all = [it for it in todo_all if not (it['notice_id'] in existing and
                                              existing[it['notice_id']].get('document_sha256') == it['document_sha256'])]
    stuck = {it['notice_id'] for it in todo_all
             if (state['failures'].get(it['notice_id']) or {}).get('sha') == it['document_sha256']
             and state['failures'][it['notice_id']].get('count', 0) >= MAX_FAILURES}
    todo_all = sorted((it for it in todo_all if it['notice_id'] not in stuck), key=lambda it: it['notice_id'])
    remaining = max(0, limit - state['attempted'])
    todo, deferred = todo_all[:remaining], max(0, len(todo_all) - remaining)
    say('대상 %d건 · 이미 있음 %d건 · 이번에 부를 것 %d건 (오늘 이미 %d/%d건)%s%s' % (
        len(items), len(items) - len(todo_all) - len(stuck), len(todo), state['attempted'], limit,
        (' · 상한으로 미룸 %d건' % deferred) if deferred else '',
        (' · %d번 실패해 멈춘 공고 %d건' % (MAX_FAILURES, len(stuck))) if stuck else ''))

    if todo and call is None:
        from shared import config
        key = config.get('OPENAI_API_KEY')
        if not key:
            say('OPENAI_API_KEY 가 없다. 업종 추출을 건너뛴다')
            return {'error': 'no_api_key', 'extracted': 0, 'skipped': skipped, 'deferred': deferred + len(todo)}
        import openai
        client = openai.OpenAI(api_key=key)
        call = lambda it: ils.ask(client, it, PROMPT, MODEL, EFFORT)          # noqa: E731

    extracted = failed = t_in = t_out = 0
    if todo:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        state['attempted'] += len(todo)          # 부르기 전에 센다 — 같은 날 다시 돌려도 상한을 넘지 않는다
        save_state(state_path, state)
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(call, it): it for it in todo}
            for fut in as_completed(futures):
                it = futures[fut]
                try:
                    data, usage = fut.result()
                except Exception as exc:
                    failed += 1
                    prev = state['failures'].get(it['notice_id']) or {}
                    count = prev.get('count', 0) + 1 if prev.get('sha') == it['document_sha256'] else 1
                    state['failures'][it['notice_id']] = {'sha': it['document_sha256'], 'count': count,
                                                          'error': type(exc).__name__}
                    say('  실패 %s — %s (%d번째)' % (it['notice_id'], type(exc).__name__, count))
                    continue
                state['failures'].pop(it['notice_id'], None)
                ils.append_jsonl(checkpoint_path, {'notice_id': it['notice_id'], 'document_sha256': it['document_sha256'],
                                                   'prompt_sha256': ils.prompt_sha256(PROMPT),
                                                   'schema_sha256': ils.schema_sha256(PROMPT), 'engine': engine,
                                                   'run_name': run_name,
                                                   'data': data, 'usage': usage})
                existing[it['notice_id']] = _result_row(it, data, usage, ils, run_name)
                extracted += 1
                t_in += usage.get('in') or 0
                t_out += usage.get('out') or 0

    save_state(state_path, state)
    write_atomic(results_path, [existing[k] for k in sorted(existing)])
    if os.path.exists(checkpoint_path) and not failed:
        os.remove(checkpoint_path)
    price_in, price_out = ils.PRICES[MODEL]
    out = {'extracted': extracted, 'skipped': skipped, 'deferred': deferred, 'failed': failed, 'gave_up': len(stuck),
           'attempted_today': state['attempted'], 'daily_limit': limit, 'total': len(existing),
           'tokens_in': t_in, 'tokens_out': t_out,
           'cost_usd': round(t_in / 1e6 * price_in + t_out / 1e6 * price_out, 4),
           'elapsed_sec': round(time.time() - started, 1)}
    with io.open(os.path.join(out_dir, 'meta.json'), 'w', encoding='utf-8') as f:
        # 13단계(upload_judgments)가 읽는 칸: engine·prompt·prompt_sha256·profile
        json.dump(dict(out, run_at=datetime.now(timezone.utc).isoformat(), engine=engine, model=MODEL,
                       reasoning_effort=EFFORT, prompt=PROMPT, prompt_sha256=ils.prompt_sha256(PROMPT),
                       schema_sha256=ils.schema_sha256(PROMPT), profile=PROFILE, source='shared',
                       seed=os.path.relpath(seed or SEED_RUN, ROOT)), f, ensure_ascii=False, indent=1)
    say('추출 %d건 · 실패 %d건 · 누적 %d건 · 약 $%.4f' % (extracted, failed, len(existing), out['cost_usd']))
    return out


def _result_row(item, data, usage, ils, run_name):
    row = {k: item.get(k) for k in KEEP}
    # 발췌 상한을 꼭 넘긴다 — None 이면 잘림(truncated) 판정이 꺼진다
    row.update({'llm': ils.verify_for(PROMPT, data, item['document'], PROFILE, ils.ec.MAX_CHARS, item.get('title') or ''),
                'usage': usage, 'doc_chars': len(item['document']), 'attachments_count': len(item['attachments']),
                'source_run': run_name, 'run_at': datetime.now(timezone.utc).isoformat(timespec='seconds')})
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plan', action='store_true', help='할 일·예상 비용만 본다. 호출하지 않는다')
    ap.add_argument('--limit', type=int, default=DAILY_LIMIT, help='그날(한국 시간) 전체 호출 상한 (기본 %d)' % DAILY_LIMIT)
    args = ap.parse_args(argv)
    if args.plan:
        from experiments.sql_semantic import industry_llm_sample as ils
        from shared import store_mysql
        conn = store_mysql.connect()
        try:
            items = ils.load_items_shared(conn, ils.pick_shared(conn))
        finally:
            conn.close()
        results = os.path.join(OUT_DIR, 'results.jsonl')
        base = OUT_DIR if os.path.exists(results) else os.path.dirname(SEED_RUN)
        todo, skipped = ils.only_new(items, base, REPORTS)
        state = load_state(os.path.join(OUT_DIR, 'daily_state.json'), datetime.now(KST).date().isoformat())
        n = min(len(todo), max(0, args.limit - state['attempted']))
        print('대상 %d건 · 이미 있음 %d건 · 부를 것 %d건 · 미룸 %d건 · 오늘 이미 %d건 · 예상 약 $%.3f (건당 약 $0.0012)'
              % (len(items), skipped, n, len(todo) - n, state['attempted'], n * 0.0012))
        return 0
    out = run_batch(limit=args.limit)
    return 1 if out.get('error') else 0


if __name__ == '__main__':
    sys.exit(main())
