# -*- coding: utf-8 -*-
"""매일 배치 11단계 — 새 공고·바뀐 공고의 신청자 유형(예비창업자·개인사업자·법인)을 LLM 으로 뽑는다 (2026-09-28).

  python -X utf8 -m collect.applicant_type_daily            단독 실행(배치와 같은 동작)
  python -X utf8 -m collect.applicant_type_daily --plan     할 일·예상 비용만 (호출 없음)

2026-09-28 사용자 요청 — 매칭·자격 확인이 쓰는 신청자 유형(search/applicant_types.py)을 새로 수집된 공고에도 채운다.
추출 방법은 전량 실행과 **같다**(experiments/sql_semantic/applicant_type_llm.py 의 문서 만들기·프롬프트·코드 검사).

  누적 결과  data/applicant_types/results.jsonl   서비스가 이 파일을 먼저 읽는다(search/applicant_types.default_path)
  체크포인트 data/applicant_types/checkpoint.jsonl  성공한 호출을 바로 적는다 — 중간에 끊겨도 쓴 비용의 결과가 남는다
  기록      data/applicant_types/meta.json

**바뀐 것만 부른다.** 공고문 발췌의 해시(document_sha256)가 누적 결과와 같으면 건너뛴다. 처음 실행하면 전량 실행 결과
(`reports/applicant_type_llm_full_20260928T023916Z/`)에서 해시가 같은 공고를 그대로 가져와 시작한다(다시 부르지 않는다).
하루 상한 DAILY_LIMIT 건(기본 300, 약 $0.25) — 넘치면 다음 날 이어서 한다. DB 에는 쓰지 않는다(SELECT 만).

**상한은 실행당이 아니라 날짜(한국 시간)당이다**(2026-09-28 Codex 통합 검수 P2). 부르기 **전에** 이번에 부를 건수를
data/applicant_types/daily_state.json 에 더해 둔다(성공·실패·중간 종료 모두 센다). 같은 날 배치를 다시 돌려도 합이 상한을 넘지 않는다.
**재시도**: 실패한 공고는 다음 실행에서 다시 고르되, 같은 발췌(해시)로 MAX_FAILURES 번 실패하면 더 부르지 않는다.
공고문이 바뀌면(해시가 달라지면) 다시 부른다.
data/ 는 배치 PC 에만 있다. EC2 서비스가 쓰려면 이 파일을 옮기거나 DB 저장을 따로 정해야 한다.
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

OUT_DIR = os.path.join(ROOT, 'data', 'applicant_types')
RESULTS = os.path.join(OUT_DIR, 'results.jsonl')
CHECKPOINT = os.path.join(OUT_DIR, 'checkpoint.jsonl')
META = os.path.join(OUT_DIR, 'meta.json')
STATE_FILE = 'daily_state.json'
SEED_RUN = os.path.join(ROOT, 'reports', 'applicant_type_llm_full_20260928T023916Z', 'results.jsonl')
DAILY_LIMIT = 300
MAX_FAILURES = 3
KST = timezone(timedelta(hours=9))
KEEP = ('notice_id', 'source', 'title', 'target_category', 'age_condition_raw', 'legacy', 'llm', 'raw', 'usage',
        'document_sha256', 'engine')
# 엔진을 적지 않은 옛 결과 행은 이 엔진으로 뽑은 것이다(2026-10-07 전 결과 전부)
LEGACY_ENGINE = 'gpt-5.6-luna@medium'


def engine_of(row):
    return (row or {}).get('engine') or LEGACY_ENGINE


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with io.open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def load_existing(results=RESULTS, seed=None):
    """{공고 ID: 결과 행}. 누적 파일이 없으면 전량 실행 결과(SEED_RUN)로 시작한다."""
    rows = read_jsonl(results) or read_jsonl(seed or SEED_RUN)
    return {r['notice_id']: r for r in rows if r.get('llm')}


def plan(population, existing, limit=DAILY_LIMIT, engine=None):
    """(할 일, 건너뛴 수, 상한 때문에 미룬 수). 해시가 같으면 건너뛴다. 오래된 공고 ID 순으로 고른다.

    engine 을 주면 그 엔진(모델@생각 강도)으로 뽑지 않은 결과도 다시 뽑는다 — 모델을 바꾼 뒤 옛·새 결과가 섞이지 않게
    (2026-10-07 결정 0013). 엔진이 없는 옛 행은 LEGACY_ENGINE 으로 본다.
    """
    def stale(it):
        row = existing.get(it['notice_id']) or {}
        if row.get('document_sha256') != it['document_sha256']:
            return True
        return engine is not None and engine_of(row) != engine
    todo = [it for it in population if stale(it)]
    todo.sort(key=lambda it: it['notice_id'])
    deferred = max(0, len(todo) - limit)
    return todo[:limit], len(population) - len(todo), deferred


def load_state(path, today):
    """{'date', 'attempted', 'failures': {공고 ID: {'sha', 'count'}}}. 날짜가 바뀌면 attempted 만 0 으로."""
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


def gave_up(population, failures):
    """같은 발췌로 MAX_FAILURES 번 실패한 공고 ID. 발췌가 바뀌면 다시 부른다."""
    return {it['notice_id'] for it in population
            if (failures.get(it['notice_id']) or {}).get('sha') == it['document_sha256']
            and failures[it['notice_id']].get('count', 0) >= MAX_FAILURES}


def write_atomic(path, rows):
    tmp = path + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    os.replace(tmp, path)


def run_batch(limit=None, say=print, workers=4, connection=None, call=None, out_dir=None, today=None):
    """배치·단독 실행의 진입점. 같은 폴더를 쓰는 실행은 하나만 돈다(2026-09-28 Codex 검수 P2).

    단독 실행(`python -m collect.applicant_type_daily`)은 배치의 collection.lock 을 잡지 않으므로, 두 실행이 같은
    attempted 를 읽고 각자 상한만큼 부를 수 있었다. 이 단계만의 잠금(<out_dir>/run.lock)으로 막는다.
    배치가 collection.lock 을 잡은 채 부르므로 다른 파일을 써야 서로 막히지 않는다.
    """
    from collect import job_lock
    out_dir = out_dir or OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    try:
        with job_lock.acquire(os.path.join(out_dir, 'run.lock')):
            return _run_batch(limit, say, workers, connection, call, out_dir, today)
    except job_lock.JobBusy:
        say('신청자 유형 추출이 이미 실행 중이다. 이번에는 건너뛴다')
        return {'error': 'busy', 'extracted': 0, 'skipped': 0, 'deferred': 0}


def _run_batch(limit, say, workers, connection, call, out_dir, today):
    """run_batch 본체(잠금 안). {'extracted', 'skipped', 'deferred', 'failed', 'gave_up', 'attempted_today', ...}.

    limit 은 **그날(한국 시간) 전체** 호출 상한이다. call(item) → (data, usage) 를 주면 그것을 쓴다(테스트).
    주지 않으면 OpenAI 를 부른다. today 는 테스트용('YYYY-MM-DD').
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from experiments.sql_semantic import applicant_type_llm as atl, industry_llm_sample as ils

    out_dir = out_dir or OUT_DIR
    results_path = os.path.join(out_dir, 'results.jsonl')
    checkpoint_path = os.path.join(out_dir, 'checkpoint.jsonl')
    state_path = os.path.join(out_dir, STATE_FILE)
    os.makedirs(out_dir, exist_ok=True)
    started = time.time()
    limit = DAILY_LIMIT if limit is None else max(0, limit)
    state = load_state(state_path, today or datetime.now(KST).date().isoformat())

    own = connection is None
    if own:
        from shared import store_mysql
        connection = store_mysql.connect()
    try:
        population = atl.load_population(connection)
    finally:
        if own:
            connection.close()

    existing = load_existing(results_path)
    # 이전 실행이 끊겼으면 체크포인트의 결과를 먼저 반영한다(같은 해시일 때만)
    by_id = {it['notice_id']: it for it in population}
    engine = '%s@%s' % (atl.MODEL, atl.EFFORT)
    for row in read_jsonl(checkpoint_path):
        it = by_id.get(row.get('notice_id'))
        if (it and row.get('document_sha256') == it['document_sha256'] and row.get('prompt_sha256') == atl.prompt_sha()
                and engine_of(row) == engine):
            existing[row['notice_id']] = _result_row(it, row['data'], row['usage'], atl)
    stuck = gave_up(population, state['failures'])
    remaining = max(0, limit - state['attempted'])
    todo, skipped, deferred = plan([it for it in population if it['notice_id'] not in stuck], existing, remaining,
                                   engine=engine)
    say('대상 %d건 · 이미 있음 %d건 · 이번에 부를 것 %d건 (오늘 이미 %d/%d건)%s%s' % (
        len(population), skipped, len(todo), state['attempted'], limit,
        (' · 상한으로 미룸 %d건' % deferred) if deferred else '',
        (' · %d번 실패해 멈춘 공고 %d건' % (MAX_FAILURES, len(stuck))) if stuck else ''))

    if todo and call is None:
        from shared import config
        key = config.get('OPENAI_API_KEY')
        if not key:
            say('OPENAI_API_KEY 가 없다. 신청자 유형 추출을 건너뛴다')
            return {'error': 'no_api_key', 'extracted': 0, 'skipped': skipped, 'deferred': deferred + len(todo)}
        import openai
        client = openai.OpenAI(api_key=key)
        call = lambda it: atl.ask(client, it)                       # noqa: E731

    extracted = failed = t_in = t_out = 0
    if todo:
        # 부르기 전에 센다 — 중간에 끊겨도 같은 날 다시 돌린 실행이 상한을 넘지 않는다
        state['attempted'] += len(todo)
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
                                                   'prompt_sha256': atl.prompt_sha(), 'engine': engine,
                                                   'data': data, 'usage': usage})
                existing[it['notice_id']] = _result_row(it, data, usage, atl)
                extracted += 1
                t_in += usage.get('in') or 0
                t_out += usage.get('out') or 0

    save_state(state_path, state)
    write_atomic(results_path, [existing[k] for k in sorted(existing)])
    # 누적 파일에 모두 반영했으면 체크포인트를 비운다(다음 실행이 다시 읽지 않게)
    if os.path.exists(checkpoint_path) and not failed:
        os.remove(checkpoint_path)
    price_in, price_out = ils.PRICES[atl.MODEL]
    out = {'extracted': extracted, 'skipped': skipped, 'deferred': deferred, 'failed': failed,
           'gave_up': len(stuck), 'attempted_today': state['attempted'], 'daily_limit': limit,
           'total': len(existing), 'tokens_in': t_in, 'tokens_out': t_out,
           'cost_usd': round(t_in / 1e6 * price_in + t_out / 1e6 * price_out, 4),
           'elapsed_sec': round(time.time() - started, 1)}
    with io.open(os.path.join(out_dir, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(dict(out, run_at=datetime.now(timezone.utc).isoformat(), engine='%s@%s' % (atl.MODEL, atl.EFFORT),
                       prompt_sha256=atl.prompt_sha(), seed=os.path.relpath(SEED_RUN, ROOT)), f,
                  ensure_ascii=False, indent=1)
    say('추출 %d건 · 실패 %d건 · 누적 %d건 · 약 $%.4f' % (extracted, failed, len(existing), out['cost_usd']))
    return out


def _result_row(item, data, usage, atl):
    row = {k: item.get(k) for k in KEEP}
    row.update({'raw': data, 'usage': usage, 'llm': atl.verify(data, item['document']),
                'document_sha256': item['document_sha256'], 'engine': '%s@%s' % (atl.MODEL, atl.EFFORT)})
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plan', action='store_true', help='할 일·예상 비용만 본다. 호출하지 않는다')
    ap.add_argument('--limit', type=int, default=DAILY_LIMIT, help='그날(한국 시간) 전체 호출 상한 (기본 %d)' % DAILY_LIMIT)
    args = ap.parse_args(argv)
    if args.plan:
        from experiments.sql_semantic import applicant_type_llm as atl
        from shared import store_mysql
        conn = store_mysql.connect()
        try:
            population = atl.load_population(conn)
        finally:
            conn.close()
        state = load_state(os.path.join(OUT_DIR, STATE_FILE), datetime.now(KST).date().isoformat())
        stuck = gave_up(population, state['failures'])
        # 실제 실행과 같은 기준(문서가 바뀌었거나 엔진이 다르면 다시 뽑기)으로 센다
        todo, skipped, deferred = plan([it for it in population if it['notice_id'] not in stuck], load_existing(),
                                       max(0, args.limit - state['attempted']),
                                       engine='%s@%s' % (atl.MODEL, atl.EFFORT))
        print('대상 %d건 · 이미 있음 %d건 · 부를 것 %d건 · 미룸 %d건 · 멈춤 %d건 · 오늘 이미 %d건 · 예상 약 $%.3f (건당 약 $0.0004, %s)'
              % (len(population), skipped, len(todo), deferred, len(stuck), state['attempted'], len(todo) * 0.0004,
                 '%s@%s' % (atl.MODEL, atl.EFFORT)))
        return 0
    out = run_batch(limit=args.limit)
    return 1 if out.get('error') else 0


if __name__ == '__main__':
    sys.exit(main())
