"""검증-1 모델 비교 실행기.

기본은 '계획만 보기'다 — 호출 수와 예상 비용을 출력하고 끝난다(API 호출 0, 비용 0).
--execute 를 줘야 실제로 호출한다. 결과는 매번 reports/ 아래 새 폴더에 쓴다(기존 폴더는 덮어쓰지 않는다).

  python -m v1_verifier.run                                   # 계획만 (전체 후보 × 원본+변형 × 3회)
  python -m v1_verifier.run --candidates luna-medium --reps 1 # 계획만, 후보 하나
  python -m v1_verifier.run --candidates luna-medium --reps 1 --execute
  python -m v1_verifier.run --resume reports/v1_20260930T120000 --execute   # 끊긴 실행 이어서
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import build_index  # noqa: E402
from clients import openai_compat as oc  # noqa: E402
from v1_verifier import prompt, report, score, variants  # noqa: E402

CHARS_PER_TOKEN = 1.55                    # 한국어 토큰 수 추정. 2026-09-30 실측(입력 약 1,320토큰)에 맞춤
BASE_OUT_TOKENS = 850                     # 항목 5개 JSON 출력 길이. 실측(gpt-4.1-mini 평균 856)
THINK_TOKENS = {None: 0, 'low': 125, 'medium': 230, 'high': 440}   # 2026-09-30 실측(luna 출력 평균 − 850). 다른 작업(작성·구현)에는 맞지 않는다


def make_jobs(cands: list[dict], plan_ids: list[str], reps: int, only_variants: list[str] | None) -> list[dict]:
    rubric = variants.load_rubric()
    jobs = []
    for pid in plan_ids:
        plan = variants.load_plan(pid)
        for var in variants.build_variants(plan):
            if only_variants and var['variant_id'] not in only_variants and var['variant_id'] != 'original':
                continue
            messages = prompt.build_messages(rubric, var['text'])
            for cand in cands:
                for rep in range(1, reps + 1):
                    jobs.append({'key': '%s|%s|%s|%d' % (cand['id'], pid, var['variant_id'], rep),
                                 'cand': cand, 'plan': pid, 'variant': var['variant_id'], 'rep': rep,
                                 'messages': messages, 'expect_lower': var['expect_lower']})
    return jobs


def estimate(jobs: list[dict]) -> dict[str, dict]:
    """후보별 (호출 수, 예상 비용). 가정값 기반 추정이다."""
    est: dict[str, dict] = {}
    for j in jobs:
        c = j['cand']
        tin = sum(len(m['content']) for m in j['messages']) / CHARS_PER_TOKEN
        tout = BASE_OUT_TOKENS + (THINK_TOKENS.get(c.get('reasoning_effort'), 500) if c.get('reasoning') else 0)
        e = est.setdefault(c['id'], {'calls': 0, 'usd': 0.0, 'tin': 0, 'tout': 0})
        e['calls'] += 1
        e['tin'] += tin
        e['tout'] += tout
        e['usd'] += tin / 1e6 * c['price'][0] + tout / 1e6 * c['price'][1]
    return est


def run_jobs(jobs: list[dict], call_fn, out_path: Path, done: set[str], workers: int = 4) -> None:
    """call_fn(cand, messages) -> (data, usage). 한 건 끝날 때마다 calls.jsonl 에 바로 적는다(끊겨도 이어서 가능)."""
    lock = threading.Lock()

    def one(job):
        row = {'key': job['key'], 'candidate': job['cand']['id'], 'plan': job['plan'],
               'variant': job['variant'], 'rep': job['rep']}
        row.update(job.get('extra', {}))          # 다른 실험(v3 등)이 넣는 추가 필드
        try:
            data, usage = call_fn(job['cand'], job['messages'])
            row.update(ok=True, data=data, usage=usage, cost=oc.cost_usd(job['cand'], usage))
        except Exception as exc:                  # noqa: BLE001 — 실패도 결과로 남긴다
            row.update(ok=False, error='%s: %s' % (type(exc).__name__, exc))
        with lock:
            with out_path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')

    todo = [j for j in jobs if j['key'] not in done]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, todo))


def write_summary(outdir: Path, jobs: list[dict]) -> None:
    rubric = variants.load_rubric()
    expects = {(j['plan'], j['variant']): j['expect_lower'] for j in jobs}
    rows = score.load_calls(outdir / 'calls.jsonl')
    (outdir / 'summary.md').write_text(score.summarize(rows, rubric, expects), encoding='utf-8')
    report.write_report(outdir)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--candidates', nargs='*', help='후보 id (기본: candidates.json 전부)')
    ap.add_argument('--plans', nargs='*', default=['base_01'])
    ap.add_argument('--variants', nargs='*', help='쓸 변형 id (원본은 항상 포함). 기본: 전부')
    ap.add_argument('--reps', type=int, default=3, help='같은 입력 반복 횟수')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--max-usd', type=float, default=1.0, help='예상 비용이 이 값을 넘으면 실행하지 않는다')
    ap.add_argument('--execute', action='store_true', help='실제로 API를 호출한다(없으면 계획만 출력)')
    ap.add_argument('--resume', help='이어서 실행할 reports/ 폴더')
    ap.add_argument('--name', help='새 결과 폴더 이름 접미사')
    args = ap.parse_args(argv)

    cands = oc.load_candidates(args.candidates)
    jobs = make_jobs(cands, args.plans, args.reps, args.variants)
    est = estimate(jobs)
    total = sum(e['usd'] for e in est.values())

    print('총 호출 %d건 (후보 %d × 계획서 %d × 변형 포함 × 반복 %d)' % (len(jobs), len(cands), len(args.plans), args.reps))
    for cid, e in est.items():
        print('  %-14s %3d건  입력 약 %.0fk·출력 약 %.0fk 토큰  예상 $%.3f' % (cid, e['calls'], e['tin'] / 1e3, e['tout'] / 1e3, e['usd']))
    print('예상 합계 $%.3f  (추정: 출력·추론 토큰은 가정값이라 실제와 다를 수 있음)' % total)
    if not args.execute:
        print('계획만 출력했다. 실제로 호출하려면 --execute 를 붙인다.')
        return 0
    if total > args.max_usd:
        print('예상 비용이 --max-usd %.2f 를 넘어 실행하지 않는다.' % args.max_usd, file=sys.stderr)
        return 2

    if args.resume:
        outdir = Path(args.resume)
        if not (outdir / 'calls.jsonl').exists():
            raise SystemExit('--resume 폴더에 calls.jsonl 이 없다: %s' % outdir)
    else:
        stamp = datetime.now().strftime('%Y%m%dT%H%M%S')
        outdir = ROOT / 'reports' / ('v1_%s%s' % (stamp, ('_' + args.name) if args.name else ''))
        outdir.mkdir(parents=True, exist_ok=False)
    out_path = outdir / 'calls.jsonl'
    done = set()
    if out_path.exists():
        done = {r['key'] for r in score.load_calls(out_path) if r.get('ok')}
    (outdir / 'meta.json').write_text(json.dumps({
        'prompt_version': prompt.PROMPT_VERSION, 'started_at': datetime.now().isoformat(timespec='seconds'),
        'candidates': oc.merge_candidates(outdir, cands), 'plans': args.plans, 'reps': args.reps, 'estimated_usd': round(total, 4)},
        ensure_ascii=False, indent=2), encoding='utf-8')

    rubric = variants.load_rubric()
    schema = prompt.output_schema(rubric)
    clients = {}

    def call_fn(cand, messages):
        if cand['id'] not in clients:
            clients[cand['id']] = oc.make_client(cand)
        return oc.call(clients[cand['id']], cand, messages, schema)

    run_jobs(jobs, call_fn, out_path, done, args.workers)
    write_summary(outdir, jobs)
    build_index.build(ROOT / 'reports')
    print('완료: %s' % (outdir / 'report.html'))
    print('표: %s' % (outdir / 'summary.md'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
