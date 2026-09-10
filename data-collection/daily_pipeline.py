# -*- coding: utf-8 -*-
"""일 1회 전체 수집 — K-Startup + 기업마당 → 정규화 → MySQL.

  python daily_pipeline.py                 전체 실행
  python daily_pipeline.py --dry-run       수집·정규화만. 교체와 DB 저장 안 함
  python daily_pipeline.py --skip-store    MySQL 저장 생략
  python daily_pipeline.py --force         건수 급감 경고를 무시한다
  python daily_pipeline.py --skip-attach   첨부 수집을 건너뛴다
  python daily_pipeline.py --skip-embed    임베딩을 건너뛴다

기존 `daily_job.py` 는 K-Startup → `data/notices.json` 경로만 담당한다.
화면(`chat_app.py`)과 추천(`match.py`)이 아직 그 파일을 읽으므로 그대로 두고,
이 스크립트가 그 위에 기업마당·정규화·MySQL 을 얹는다.

  daily_job.run()      K-Startup 수집 · 검증 · 백업 · 원자적 교체
        ↓
  기업마당 수집          실패하면 직전 스냅샷을 그대로 쓴다
        ↓
  normalize.py         두 소스를 공통 스키마로
        ↓
  store_mysql.py       notices / notice_attachments / import_runs

**소스별로 따로 검증하고 따로 실패한다** (decisions.md D1).
합쳐서 세면 한 소스가 통째로 죽어도 전체 건수가 절반을 넘어 검증을 통과한다.
한 소스가 실패해도 나머지는 갱신하고, 실패한 소스는 직전 데이터를 유지한다.

종료 코드는 daily_job 과 맞춘다. 0 성공 / 1 실패 / 2 부분 실패 / 3 이미 실행 중
"""
import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

import config
import daily_job
import job_lock
import normalize

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
RAW = os.path.join(DATA, 'raw')
NORM = os.path.join(DATA, 'normalized')
LOG = os.path.join(DATA, 'collect_log.jsonl')
LOCK = os.path.join(DATA, 'collection.lock')

MIN_RATIO = 0.5     # 직전 대비 이 비율 밑으로 떨어지면 교체를 막는다
KEEP_RAW = 14       # 원본 스냅샷 보관 일수 대신 개수. 소스별로 이만큼 남긴다


def stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')


def snapshots(source):
    """해당 소스의 원본 스냅샷을 오래된 순으로 돌려준다."""
    if not os.path.isdir(RAW):
        return []
    names = sorted(n for n in os.listdir(RAW) if n.startswith(source + '_') and n.endswith('.json'))
    return [os.path.join(RAW, n) for n in names]


def rows_in(path, source):
    """스냅샷 파일의 공고 건수. 못 읽으면 0."""
    try:
        with open(path, 'rb') as f:
            payload = json.loads(f.read().decode('utf-8-sig'))
        return len(normalize.rows_from(payload, source))
    except Exception:
        return 0


def prune(source, keep=KEEP_RAW):
    """오래된 스냅샷을 지운다. 디스크가 무한정 늘지 않게."""
    old = snapshots(source)[:-keep]
    for path in old:
        try:
            os.remove(path)
        except OSError:
            pass
    return len(old)


def collect_bizinfo(force, say):
    """기업마당 수집. (경로, 건수, 상태, 사유) 를 돌려준다.

    실패하거나 건수가 급감하면 **직전 스냅샷을 그대로 쓴다.**
    이 소스만 전일 데이터로 남고 나머지는 정상 갱신된다.
    """
    import fetch_bizinfo

    previous = snapshots('bizinfo')
    prev_path = previous[-1] if previous else None
    prev_count = rows_in(prev_path, 'bizinfo') if prev_path else 0

    if not config.get('BIZINFO_KEY'):
        return prev_path, prev_count, 'skipped', 'BIZINFO_KEY 가 없다'

    try:
        path, count = fetch_bizinfo.fetch_snapshot()
    except Exception as exc:
        say('  기업마당 수집 실패: %s' % exc)
        return prev_path, prev_count, 'stale', str(exc)

    if prev_count and count < prev_count * MIN_RATIO and not force:
        # 새로 받은 것은 남기되 쓰지 않는다. 원인 확인용으로 파일은 보존한다.
        why = ('직전 %d건 → 오늘 %d건 (%.0f%% 감소)'
               % (prev_count, count, 100 * (1 - count / prev_count)))
        say('  기업마당 건수 급감으로 직전 스냅샷을 유지한다 — %s' % why)
        return prev_path, prev_count, 'rejected', why

    say('  기업마당 %d건' % count)
    return path, count, 'ok', ''


def load(path, source):
    with open(path, 'rb') as f:
        raw = f.read()
    return (json.loads(raw.decode('utf-8-sig')),
            {'source': source, 'input_file': os.path.abspath(path),
             'sha256': hashlib.sha256(raw).hexdigest()})


def build_normalized(sources, say):
    """정규화 결과를 새 파일로 쓴다. (경로, 요약) 을 돌려준다."""
    payloads, meta = [], []
    for source, path in sources:
        payload, info = load(path, source)
        payloads.append((source, payload))
        meta.append(info)

    result = normalize.normalize_sources(payloads)
    now = datetime.now(timezone.utc)
    result.update({'generated_at': now.isoformat(), 'inputs': meta})

    os.makedirs(NORM, exist_ok=True)
    out = os.path.join(NORM, 'notices_%s.json' % now.strftime('%Y%m%dT%H%M%S%fZ'))
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    s = result['summary']
    say('  정규화 %d건 (거부 %d, 소스내 중복 %d, 교차 후보 %d)'
        % (s['accepted_count'], s['rejected_count'],
           s['same_source_duplicate_count'], s['cross_source_candidate_groups']))
    return out, s


def store(path, say):
    """MySQL 저장. 실패해도 예외를 올리지 않고 (성공여부, 결과) 를 돌려준다."""
    import store_mysql

    connection = None
    try:
        with open(path, 'rb') as f:
            content = f.read()
        payload = json.loads(content.decode('utf-8-sig'))
        store_mysql.validate_payload(payload)
        connection = store_mysql.connect()
        result = store_mysql.store_payload(
            connection, payload, hashlib.sha256(content).hexdigest())
        say('  MySQL 저장 %s' % json.dumps(result, ensure_ascii=False)[:160])
        return True, result
    except Exception as exc:
        # 예외 원문에 SQL 값이나 접속 정보가 섞일 수 있어 종류만 남긴다.
        say('  MySQL 저장 실패: %s' % type(exc).__name__)
        return False, {'error': type(exc).__name__}
    finally:
        if connection:
            connection.close()


def write_log(entry):
    entry['run_at'] = datetime.now().isoformat(timespec='seconds')
    os.makedirs(DATA, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    return entry


def run(dry_run=False, skip_store=False, force=False, say=print,
        skip_attach=False, attach_limit=None, attach_interval=1.0,
        skip_embed=False, embed_limit=None):
    try:
        with job_lock.acquire(LOCK):
            return _run(dry_run, skip_store, force, say,
                        skip_attach, attach_limit, attach_interval,
                        skip_embed, embed_limit)
    except job_lock.JobBusy as exc:
        return {'status': 'busy', 'job': 'pipeline', 'error': str(exc)}


def _run(dry_run, skip_store, force, say,
         skip_attach=False, attach_limit=None, attach_interval=1.0,
         skip_embed=False, embed_limit=None):
    started = time.time()
    sources = {}

    # ── 1. K-Startup — 기존 경로를 그대로 쓴다 ──────────────────
    say('K-Startup 수집')
    # 잠금은 이 함수 바깥에서 이미 잡았다. daily_job.run() 을 부르면 같은 잠금을
    # 다시 잡으려다 스스로 busy 가 되므로 잠금 없는 _run() 을 직접 부른다.
    ks = daily_job._run(skip_embed=True, dry_run=dry_run, force=force, say=say)
    sources['kstartup'] = {'status': ks['status'], 'count': ks.get('count'),
                           'new_count': ks.get('new_count'), 'error': ks.get('error')}
    # ── 2. 기업마당 — 실패해도 직전 스냅샷으로 이어간다 ────────────
    say('기업마당 수집')
    biz_path, biz_count, biz_status, biz_why = collect_bizinfo(force, say)
    sources['bizinfo'] = {'status': biz_status, 'count': biz_count, 'error': biz_why or None}

    # ── 3. 정규화 ────────────────────────────────────────────
    inputs = []
    ks_path = daily_job.OUT
    if os.path.exists(ks_path):
        inputs.append(('kstartup', ks_path))
    if biz_path and os.path.exists(biz_path):
        inputs.append(('bizinfo', biz_path))

    if not inputs:
        return write_log({'status': 'error', 'job': 'pipeline', 'stage': 'normalize',
                          'error': '정규화할 입력이 없다', 'sources': sources,
                          'elapsed_sec': round(time.time() - started, 1)})

    say('정규화 (%s)' % ', '.join(s for s, _ in inputs))
    try:
        norm_path, summary = build_normalized(inputs, say)
    except Exception as exc:
        return write_log({'status': 'error', 'job': 'pipeline', 'stage': 'normalize',
                          'error': '%s: %s' % (type(exc).__name__, exc), 'sources': sources,
                          'elapsed_sec': round(time.time() - started, 1)})

    # ── 4. MySQL 저장 ───────────────────────────────────────
    stored, store_result = False, None
    if dry_run:
        say('dry-run — DB 저장을 건너뛴다')
    elif skip_store:
        say('--skip-store — DB 저장을 건너뛴다')
    else:
        say('MySQL 저장')
        stored, store_result = store(norm_path, say)

    # ── 5. 첨부 받기·본문 추출 ────────────────────────────────
    # 공고 저장이 끝난 뒤에 한다. 여기서 실패해도 공고 데이터는 이미 최신이다.
    attach = None
    if stored and not skip_attach:
        say('첨부 수집')
        try:
            import attachment_pipeline
            attach, _ = attachment_pipeline.daily(
                limit=attach_limit, interval=attach_interval,
                say=lambda line: say('  ' + line))
        except Exception as exc:
            say('  첨부 수집 실패: %s' % type(exc).__name__)
            attach = {'error': '%s: %s' % (type(exc).__name__, str(exc)[:200])}
    elif skip_attach:
        say('--skip-attach — 첨부 수집을 건너뛴다')

    # ── 6·7. 임베딩 생성 → 벡터 색인 갱신 ─────────────────────
    # 벡터가 없거나 내용이 바뀐 공고만 만든다. 보통 하루 수십 건이다.
    # 여기서 실패해도 1~5 단계는 이미 끝나 있다.
    embed_result = None
    if stored and not skip_embed:
        say('임베딩')
        try:
            import embed
            import vecstore
            embed_result = embed.run(limit=embed_limit,
                                     say=lambda line: say('  ' + line))
            changed = embed_result.get('changed_ids')
            if embed_result.get('made') or changed is None:
                say('벡터 색인')
                embed_result['index'] = vecstore.sync(
                    changed_ids=changed, say=lambda line: say('  ' + line))
        except Exception as exc:
            say('  임베딩 실패: %s' % type(exc).__name__)
            embed_result = {'error': '%s: %s' % (type(exc).__name__, str(exc)[:200])}
    elif skip_embed:
        say('--skip-embed — 임베딩을 건너뛴다')

    removed = prune('bizinfo') + prune('kstartup')
    if removed:
        say('오래된 원본 스냅샷 %d개 정리' % removed)

    # 한 소스라도 정상이 아니면 부분 실패로 본다
    degraded = [s for s, v in sources.items() if v['status'] not in ('ok', 'dry-run')]
    ok = not degraded and (stored or dry_run or skip_store)

    return write_log({
        'status': 'ok' if ok else 'partial',
        'job': 'pipeline',
        'sources': sources,
        'degraded': degraded,
        'normalized': os.path.basename(norm_path),
        'normalized_count': summary['accepted_count'],
        'rejected_count': summary['rejected_count'],
        'cross_source_candidate_groups': summary['cross_source_candidate_groups'],
        'stored': stored,
        'store_result': store_result,
        'attachments': attach,
        'embeddings': embed_result,
        'elapsed_sec': round(time.time() - started, 1),
    })


def main():
    ap = argparse.ArgumentParser(description='K-Startup + 기업마당 → 정규화 → MySQL')
    ap.add_argument('--dry-run', action='store_true', help='수집·정규화만. 교체와 DB 저장 안 함')
    ap.add_argument('--skip-store', action='store_true', help='MySQL 저장을 건너뛴다')
    ap.add_argument('--force', action='store_true', help='건수 급감 경고를 무시한다')
    ap.add_argument('--skip-attach', action='store_true', help='첨부 수집을 건너뛴다')
    ap.add_argument('--attach-limit', type=int, help='이번 실행에서 받을 첨부 상한')
    ap.add_argument('--attach-interval', type=float, default=1.0,
                    help='첨부 요청 간격(초). 기본 1.0')
    ap.add_argument('--skip-embed', action='store_true', help='임베딩을 건너뛴다')
    ap.add_argument('--embed-limit', type=int, help='이번 실행에서 만들 벡터 상한')
    args = ap.parse_args()

    r = run(dry_run=args.dry_run, skip_store=args.skip_store, force=args.force,
            skip_attach=args.skip_attach, attach_limit=args.attach_limit,
            attach_interval=args.attach_interval,
            skip_embed=args.skip_embed, embed_limit=args.embed_limit)

    if r['status'] == 'busy':
        print('이미 수집 작업이 실행 중이다.', file=sys.stderr)
        return 3
    if r['status'] == 'error':
        print('실패 — %s' % r.get('error'), file=sys.stderr)
        print('기존 데이터를 그대로 둔다.')
        return 1

    print('\n%s — 정규화 %d건 / %.1f초'
          % (r['status'], r.get('normalized_count', 0), r.get('elapsed_sec', 0)))
    for source, v in (r.get('sources') or {}).items():
        print('  %-10s %-9s %s건%s'
              % (source, v['status'], v.get('count'),
                 ' — ' + v['error'] if v.get('error') else ''))
    a = r.get('attachments') or {}
    if a.get('counts') or a.get('error'):
        print('  %-10s %s' % ('첨부', a.get('error') or
              ' · '.join('%s %d' % kv for kv in sorted(a['counts'].items()))))
    e = r.get('embeddings') or {}
    if e:
        idx = e.get('index') or {}
        print('  %-10s %s' % ('임베딩', e.get('error') or
              ('새로 %d건 · 색인 %d건%s'
               % (e.get('made', 0), idx.get('indexed', 0),
                  '  ⚠ 색인 누락 %d건' % idx['missing'] if idx.get('missing') else ''))))
    if r['status'] == 'partial':
        print('\n일부 소스가 갱신되지 않았다. 해당 소스는 직전 데이터를 유지한다.')
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
