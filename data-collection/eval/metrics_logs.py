# -*- coding: utf-8 -*-
"""배치 기록(collect_log.jsonl · run.log)을 배치 서버에서 읽기만 해서 가져오고, 이 PC 복사본과 합친다(2026-10-14).

  python -X utf8 -m eval.metrics_logs --snapshot     지금 배치 서버 기록을 이 PC data/ 복사본에 합쳐 둔다
  python -X utf8 -m eval.metrics_logs                합친 기록을 요약만 한다(서버에서 새로 읽어 합치되 저장은 안 함)

배치는 10/2부터 서버에서 돈다(그 전 PC 기록도 서버로 옮겨 갔다). 서버를 옮기면 새 서버 기록은 처음부터
시작하므로, 이전 전에 --snapshot 으로 이 PC 에 복사해 두고 지표는 "복사본 + 그때 배치 서버 기록"을 합쳐 센다.

서버 쪽에서는 파일 복사(scp)만 한다. 서버 주소·키 파일·원격 폴더는 인자나 환경 변수로 바꾼다:
  METRICS_BATCH_HOST (기본 ubuntu@13.125.40.88 — 공용 DB 에 쓰는 배치 서버 sbrain-web)
  METRICS_BATCH_KEY  (기본 ~/.ssh/sbrain-web.pem)
  METRICS_BATCH_DIR  (기본 ~/sbrain/data-collection/data)
  METRICS_BATCH_NAME (기본 sbrain-web — 복사본 파일 이름과 화면 표시에 쓰는 이름)
보고서에는 주소·키 경로를 쓰지 않고 이름만 쓴다.

합치기 규칙
  collect_log  같은 실행 = 같은 (run_at, job). 한 번만 남기고 run_at 순서.
  run.log      "[날짜 시각]" 머리줄로 시작하는 덩어리 단위. 똑같은 덩어리는 한 번만, 머리줄 시각 순서.
               (머리줄 없는 줄만 같다고 지우면 날마다 같은 문구가 사라지므로 줄 단위로 지우지 않는다)
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, 'data')

DEFAULTS = {
    'host': 'ubuntu@13.125.40.88',
    'key': os.path.join('~', '.ssh', 'sbrain-web.pem'),
    'remote': '~/sbrain/data-collection/data',
    'name': 'sbrain-web',
}
FILES = ('collect_log.jsonl', 'run.log')
HEADER = re.compile(r'^\[(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2}):(\d{2})')


def settings(host=None, key=None, remote=None, name=None):
    env = os.environ
    return {
        'host': host or env.get('METRICS_BATCH_HOST') or DEFAULTS['host'],
        'key': os.path.expanduser(key or env.get('METRICS_BATCH_KEY') or DEFAULTS['key']),
        'remote': remote or env.get('METRICS_BATCH_DIR') or DEFAULTS['remote'],
        'name': name or env.get('METRICS_BATCH_NAME') or DEFAULTS['name'],
    }


def snapshot_paths(name, data_dir=DATA):
    """이 PC 복사본 경로. data/ 바로 아래라 .gitignore(data/*.jsonl, data/*.log)에 걸린다."""
    return {'collect_log.jsonl': os.path.join(data_dir, 'collect_log.%s.jsonl' % name),
            'run.log': os.path.join(data_dir, 'run.%s.log' % name)}


# ── 합치기 (서버 없이 시험할 수 있는 순수 함수) ────────────────────────────
def parse_collect_log(text):
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue                       # 쓰다 만 줄 등은 건너뛴다
    return rows


def merge_collect_logs(*texts):
    """여러 collect_log 내용을 합친다. 같은 (run_at, job)은 먼저 나온 것 하나만, run_at 순서."""
    seen, out = set(), []
    for text in texts:
        for row in parse_collect_log(text or ''):
            key = (row.get('run_at'), row.get('job'))
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
    out.sort(key=lambda r: str(r.get('run_at') or ''))
    return out


def dump_collect_log(rows):
    return ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows)


def _header_key(line):
    m = HEADER.match(line)
    if not m:
        return None
    d, h, mi, s = m.groups()
    return '%s %02d:%s:%s' % (d, int(h), mi, s)


def split_blocks(text):
    """run.log 를 머리줄 단위 덩어리로 나눈다. [(정렬 키, 덩어리 글)] — 첫 머리줄 앞의 줄은 키 ''."""
    blocks, cur, key = [], [], ''
    # 줄은 '\n' 으로만 나눈다(진행 막대가 줄 안에 '\r' 을 남기므로 splitlines 를 쓰면 줄이 쪼개진다)
    lines = (text or '').split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    for line in (ln[:-1] if ln.endswith('\r') else ln for ln in lines):
        k = _header_key(line)
        if k is not None:
            if cur:
                blocks.append((key, '\n'.join(cur)))
            cur, key = [line], k
        else:
            cur.append(line)
    if cur:
        blocks.append((key, '\n'.join(cur)))
    return blocks


def merge_run_logs(*texts):
    """여러 run.log 내용을 덩어리 단위로 합친다. 똑같은 덩어리는 하나만, 머리줄 시각 순서(같은 시각은 들어온 순서)."""
    seen, out = set(), []
    for text in texts:
        for key, block in split_blocks(text):
            if block in seen:
                continue
            seen.add(block)
            out.append((key, len(out), block))
    out.sort(key=lambda x: (x[0], x[1]))
    return '\n'.join(b for _, _, b in out) + ('\n' if out else '')


# ── 서버에서 읽기 ───────────────────────────────────────────────────────
def fetch(cfg, timeout=60):
    """배치 서버의 두 파일을 임시 폴더로 복사해 내용을 돌려준다. {파일: 내용 또는 None}, 못 읽은 이유 목록."""
    got, errors = {}, []
    tmp = tempfile.mkdtemp(prefix='metrics_logs_')
    try:
        for fname in FILES:
            dest = os.path.join(tmp, fname)
            cmd = ['scp', '-q', '-i', cfg['key'], '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
                   '%s:%s/%s' % (cfg['host'], cfg['remote'], fname), dest]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            except (OSError, subprocess.TimeoutExpired) as exc:
                got[fname] = None
                errors.append('%s: %s' % (fname, type(exc).__name__))
                continue
            if r.returncode != 0 or not os.path.exists(dest):
                got[fname] = None
                # 오류 원문에는 주소가 들어 있을 수 있어 종료 코드만 남긴다
                errors.append('%s: 복사 실패(종료 코드 %d)' % (fname, r.returncode))
                continue
            with open(dest, encoding='utf-8', errors='replace', newline='') as f:
                got[fname] = f.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return got, errors


def _read(path):
    if not os.path.exists(path):
        return ''
    with open(path, encoding='utf-8', errors='replace', newline='') as f:
        return f.read()


def load(cfg=None, refresh=True, data_dir=DATA):
    """합친 기록을 돌려준다.

    {'collect_rows': [...], 'run_log': str, 'sources': [...], 'errors': [...]}
    sources 는 화면용 이름만(예: 'sbrain-web 서버', '이 PC 복사본(sbrain-web)').
    """
    cfg = cfg or settings()
    paths = snapshot_paths(cfg['name'], data_dir)
    snap_cl, snap_rl = _read(paths['collect_log.jsonl']), _read(paths['run.log'])
    sources, errors = [], []
    if snap_cl or snap_rl:
        sources.append('이 PC 복사본(%s)' % cfg['name'])
    live = {}
    if refresh:
        live, errors = fetch(cfg)
        if any(v is not None for v in live.values()):
            sources.append('%s 서버' % cfg['name'])
    rows = merge_collect_logs(snap_cl, live.get('collect_log.jsonl') or '')
    run_log = merge_run_logs(snap_rl, live.get('run.log') or '')
    return {'collect_rows': rows, 'run_log': run_log, 'sources': sources, 'errors': errors}


def snapshot(cfg=None, data_dir=DATA):
    """서버 기록을 이 PC 복사본에 합쳐 저장한다(복사본에만 있던 줄은 지우지 않는다)."""
    cfg = cfg or settings()
    paths = snapshot_paths(cfg['name'], data_dir)
    live, errors = fetch(cfg)
    if errors and all(v is None for v in live.values()):
        return {'saved': False, 'errors': errors}
    os.makedirs(data_dir, exist_ok=True)
    rows = merge_collect_logs(_read(paths['collect_log.jsonl']), live.get('collect_log.jsonl') or '')
    with open(paths['collect_log.jsonl'], 'w', encoding='utf-8', newline='\n') as f:
        f.write(dump_collect_log(rows))
    run_log = merge_run_logs(_read(paths['run.log']), live.get('run.log') or '')
    with open(paths['run.log'], 'w', encoding='utf-8', newline='\n') as f:
        f.write(run_log)
    return {'saved': True, 'errors': errors, 'rows': len(rows), 'paths': paths}


def summary(rows):
    pipe = [r for r in rows if r.get('job') == 'pipeline']
    days = sorted({str(r.get('run_at', ''))[:10] for r in pipe if r.get('run_at')})
    return {'rows': len(rows), 'pipeline_runs': len(pipe), 'first_day': days[0] if days else None,
            'last_day': days[-1] if days else None}


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--snapshot', action='store_true', help='서버 기록을 이 PC 복사본에 합쳐 저장')
    ap.add_argument('--host')
    ap.add_argument('--key')
    ap.add_argument('--remote')
    ap.add_argument('--name')
    args = ap.parse_args(argv)
    cfg = settings(args.host, args.key, args.remote, args.name)
    if args.snapshot:
        r = snapshot(cfg)
        if not r['saved']:
            print('복사 못 함:', '; '.join(r['errors']))
            return 2
        print('복사본 저장: collect_log %d줄 → %s, run.log → %s' % (
            r['rows'], os.path.relpath(r['paths']['collect_log.jsonl'], ROOT), os.path.relpath(r['paths']['run.log'], ROOT)))
        for e in r['errors']:
            print('경고:', e)
    got = load(cfg)
    s = summary(got['collect_rows'])
    print('합친 기록: %d줄 · 배치 실행 %d회 · %s ~ %s · 출처 %s' % (
        s['rows'], s['pipeline_runs'], s['first_day'], s['last_day'], ', '.join(got['sources']) or '없음'))
    for e in got['errors']:
        print('못 읽음:', e)
    return 0


if __name__ == '__main__':
    sys.exit(main())
