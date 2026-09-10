# -*- coding: utf-8 -*-
"""일일 공고 수집 작업 — 하루 한 번 돌린다.

  python daily_job.py                 수집 + 검증 + 교체 + 임베딩 + 로그
  python daily_job.py --skip-embed    임베딩 생략 (빠름)
  python daily_job.py --dry-run       수집만 하고 저장하지 않는다
  python daily_job.py --force         건수 급감 경고를 무시하고 교체

fetch.py 와 다른 점 ─ fetch.py 는 받은 것을 바로 덮어쓴다. 이 스크립트는

  1. 임시 파일에 받고
  2. 건수를 검증한 뒤에만
  3. 원자적으로 교체하고
  4. 이전 파일을 history/ 에 남기고
  5. 결과를 collect_log.jsonl 에 기록한다

API 가 절반만 응답했을 때 좋은 데이터를 덮어쓰지 않기 위해서다.
요구사항 NFR-ID-001 "외부 API 장애 시에도 전일 수집 데이터로 정상 동작한다".

수집 로그는 관리자 화면(ANN-ID-001)의 데이터 소스가 된다.
"""
import argparse
import json
import os
import shutil
import sys
import time
from datetime import date, datetime

import config
import fetch
import job_lock

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
OUT = os.path.join(DATA, 'notices.json')
TMP = os.path.join(DATA, 'notices.json.tmp')
HIST = os.path.join(DATA, 'history')
LOG = os.path.join(DATA, 'collect_log.jsonl')

RETRIES = 3
BACKOFF = 30          # 초. 실패할 때마다 2배씩 늘린다
MIN_RATIO = 0.5       # 전일 대비 이 비율 밑으로 떨어지면 교체를 막는다


def prev_payload():
    if not os.path.exists(OUT):
        return None
    try:
        with open(OUT, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def write_log(entry):
    entry['run_at'] = datetime.now().isoformat(timespec='seconds')
    os.makedirs(DATA, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    return entry


def collect(key):
    """실패하면 잠시 쉬었다 다시 시도한다. 마지막까지 실패하면 예외를 올린다."""
    wait = BACKOFF
    for attempt in range(1, RETRIES + 1):
        try:
            rows, total = fetch.fetch_all(key)
            return rows, total
        except Exception as e:
            if attempt == RETRIES:
                raise
            print('  수집 실패 (%d/%d): %s — %d초 후 재시도'
                  % (attempt, RETRIES, e, wait))
            time.sleep(wait)
            wait *= 2


def validate(rows, prev, force):
    """교체해도 되는지 판단한다. (ok, 사유) 를 돌려준다."""
    if not rows:
        return False, '수집 건수가 0이다'

    prev_count = (prev or {}).get('count') or 0
    if prev_count and len(rows) < prev_count * MIN_RATIO:
        msg = ('전일 %d건 → 오늘 %d건 (%.0f%% 감소). API 부분 응답을 의심한다'
               % (prev_count, len(rows), 100 * (1 - len(rows) / prev_count)))
        if not force:
            return False, msg
        print('  경고 무시(--force): ' + msg)

    # 필수 필드가 비어 있으면 파싱이 깨진 것이다
    need = ('pbanc_sn', 'biz_pbanc_nm', 'pbanc_rcpt_end_dt')
    bad = [r for r in rows[:50] if not all(r.get(k) for k in need)]
    if len(bad) > 25:
        return False, '필수 필드가 비어 있는 행이 많다 (표본 50건 중 %d건)' % len(bad)

    return True, ''


def archive(prev):
    """교체 전 파일을 날짜별로 남긴다. 신규 공고 탐지(INT-ID-001)에도 쓴다."""
    if not prev or not os.path.exists(OUT):
        return None
    os.makedirs(HIST, exist_ok=True)
    stamp = prev.get('fetched_at') or date.today().isoformat()
    dst = os.path.join(HIST, 'notices_%s.json' % stamp.replace('-', ''))
    shutil.copy2(OUT, dst)
    return os.path.basename(dst)


def build_embeddings(notices):
    """수집 시점에 임베딩을 만들어 둔다 (ANN-ID-005).

    사용자 요청 시점에 만들면 첫 검색이 몇 분씩 걸린다.
    """
    import match_bge
    match_bge.Index(notices)
    return True


def new_notice_ids(rows, prev):
    """전일에 없던 공고. 관심 공고 알림(INT-ID-001)의 입력이 된다."""
    if not prev:
        return []
    old = {r.get('pbanc_sn') for r in prev.get('notices', [])}
    return [r.get('pbanc_sn') for r in rows if r.get('pbanc_sn') not in old]


def run(skip_embed=False, dry_run=False, force=False, say=print):
    """예약 CLI와 수동 화면에 공통 실행 잠금을 적용한다."""
    try:
        with job_lock.acquire(os.path.join(DATA, 'collection.lock')):
            return _run(skip_embed, dry_run, force, say)
    except job_lock.JobBusy as exc:
        return {'status': 'busy', 'stage': 'lock', 'error': str(exc)}


def _run(skip_embed=False, dry_run=False, force=False, say=print):
    """수집 한 사이클. 결과를 dict 로 돌려준다.

    CLI 와 화면(chat_app.py 의 수동 재수집 버튼)이 같은 코드를 쓰도록 분리했다.
    say 로 진행 메시지를 받아갈 함수를 넘길 수 있다.
    """
    started = time.time()
    key = config.get('KSTARTUP_KEY')
    if not key:
        return write_log({'status': 'error', 'stage': 'key',
                          'error': '환경변수 KSTARTUP_KEY 가 없다'})

    prev = prev_payload()
    prev_count = (prev or {}).get('count') or 0
    say('전일 데이터: %s %d건' % ((prev or {}).get('fetched_at', '없음'), prev_count))

    # ── 1. 수집 ──────────────────────────────────────────────
    try:
        rows, total = collect(key)
    except Exception as e:
        return write_log({'status': 'error', 'stage': 'fetch', 'error': str(e),
                          'prev_count': prev_count,
                          'elapsed_sec': round(time.time() - started, 1)})
    say('수집 %d건 (서버 보고 %d건)' % (len(rows), total))

    # ── 2. 검증 ──────────────────────────────────────────────
    ok, why = validate(rows, prev, force)
    if not ok:
        return write_log({'status': 'rejected', 'stage': 'validate', 'error': why,
                          'count': len(rows), 'prev_count': prev_count,
                          'elapsed_sec': round(time.time() - started, 1)})

    added = new_notice_ids(rows, prev)
    say('신규 공고 %d건' % len(added))

    if dry_run:
        return {'status': 'dry-run', 'count': len(rows), 'prev_count': prev_count,
                'new_count': len(added),
                'elapsed_sec': round(time.time() - started, 1)}

    # ── 3. 임시 파일에 쓰고 원자적으로 교체 ──────────────────────
    payload = {
        'fetched_at': date.today().isoformat(),
        'source': 'K-Startup getAnnouncementInformation01 (rcrt_prgs_yn=Y)',
        'count': len(rows),
        'reported_total': total,
        'notices': rows,
    }
    os.makedirs(DATA, exist_ok=True)
    with open(TMP, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    archived = archive(prev)
    os.replace(TMP, OUT)          # 같은 볼륨이면 원자적이다
    say('교체 완료%s' % (' (이전본 %s)' % archived if archived else ''))

    # ── 4. 임베딩 ────────────────────────────────────────────
    embedded, embed_err = False, None
    if not skip_embed:
        try:
            say('임베딩 생성 중… 몇 분 걸린다')
            embedded = build_embeddings(rows)
        except Exception as e:
            embed_err = str(e)
            say('임베딩 실패: %s (공고 데이터는 교체됐다)' % e)

    return write_log({
        'status': 'ok' if (embedded or skip_embed) else 'partial',
        'count': len(rows),
        'prev_count': prev_count,
        'new_count': len(added),
        'reported_total': total,
        'embedded': embedded,
        'embed_error': embed_err,
        'archived': archived,
        'elapsed_sec': round(time.time() - started, 1),
    })


def recent_logs(n=10):
    """최근 수집 기록. 관리자 수집상태 화면(ANN-ID-001)이 읽는다."""
    if not os.path.exists(LOG):
        return []
    out = []
    with open(LOG, encoding='utf-8') as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out[-n:][::-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--skip-embed', action='store_true', help='임베딩 생성을 건너뛴다')
    ap.add_argument('--dry-run', action='store_true', help='수집만 하고 저장하지 않는다')
    ap.add_argument('--force', action='store_true', help='건수 급감 경고를 무시한다')
    args = ap.parse_args()

    r = run(skip_embed=args.skip_embed, dry_run=args.dry_run, force=args.force)

    if r['status'] == 'busy':
        print(r['error'], file=sys.stderr)
        return 3
    if r['status'] in ('error', 'rejected'):
        print('%s — %s' % (r['status'], r.get('error')), file=sys.stderr)
        print('기존 데이터를 그대로 둔다. 서비스는 전일 데이터로 동작한다.')
        return 1

    print('\n%s — %d건 / 신규 %d건 / %.1f초'
          % (r['status'], r.get('count', 0), r.get('new_count', 0),
             r.get('elapsed_sec', 0)))
    return 2 if r['status'] == 'partial' else 0


if __name__ == '__main__':
    raise SystemExit(main())
