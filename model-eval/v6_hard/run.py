"""더 어려운 시험 실행기. 기본은 '계획만 보기'(API 호출 0). --execute 를 줘야 실제로 호출한다.

  python -m v6_hard.run --exp gradient                 # 검증-1: 좋음/보통/나쁨 3단계 (계획만)
  python -m v6_hard.run --exp strategy --execute       # 전략 T-S2 함정 16건
  python -m v6_hard.run --exp writer --execute         # 작성 T-W1 유혹 16건
  python -m v6_hard.run --exp gradient --resume reports/v6_gradient_… --execute
기본 후보는 luna 중심(gpt-6-luna, gpt-5.6-luna)과 비교 기준 gpt-4.1-mini. 결과는 매번 reports/ 아래 새 폴더에 쓴다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import build_index  # noqa: E402
from clients import openai_compat as oc  # noqa: E402
from v1_verifier import prompt as jprompt, run as v1run, variants as jvariants  # noqa: E402
from v3_strategy import prompt as sp  # noqa: E402
from v4_writer import prompt as wp  # noqa: E402
from v6_hard import cases as C, evaluate as E, report  # noqa: E402

DEFAULT_CANDIDATES = ['luna6-medium', 'luna-medium', 'gpt-4.1-mini']
EXPS = ('gradient', 'strategy', 'writer')
LABEL = {'gradient': '검증-1 미묘한 차이(좋음/보통/나쁨)', 'strategy': '전략 T-S2 함정', 'writer': '작성 T-W1 유혹'}


def load_cases(exp: str) -> dict[str, dict]:
    return {'gradient': C.gradient_cases, 'strategy': C.strategy_hard_cases, 'writer': C.writer_hard_cases}[exp]()


def messages_for(exp: str, case: dict) -> list[dict]:
    if exp == 'gradient':
        return jprompt.build_messages(jvariants.load_rubric(), case['text'])
    if exp == 'strategy':
        return sp.build_s2(case, 'facts')
    return C.build_writer_messages(case)


def schemas() -> dict:
    return {jprompt.SYSTEM: jprompt.output_schema(jvariants.load_rubric()), sp.S2_SYSTEM: sp.s2_schema(), wp.W1_SYSTEM: wp.w1_schema()}


def make_jobs(exp: str, cands: list[dict], cases: dict, reps: int, only=None) -> list[dict]:
    jobs = []
    for cid, case in cases.items():
        if only and cid not in only:
            continue
        msgs = messages_for(exp, case)
        for cand in cands:
            for rep in range(1, reps + 1):
                jobs.append({'key': '%s|%s|%s|%d' % (cand['id'], exp, cid, rep), 'cand': cand, 'plan': exp, 'variant': cid, 'rep': rep,
                             'messages': msgs, 'extra': {'exp': exp, 'case': cid, 'ctype': case.get('type', '')}})
    return jobs


def estimate(exp: str, jobs: list[dict]) -> dict:
    out_tok = {'gradient': 900, 'strategy': 900, 'writer': 2200}[exp]
    est = {}
    for j in jobs:
        c = j['cand']
        tin = sum(len(m['content']) for m in j['messages']) / 1.55
        tout = out_tok + (300 if c.get('reasoning') else 0)
        e = est.setdefault(c['id'], {'calls': 0, 'usd': 0.0})
        e['calls'] += 1
        e['usd'] += tin / 1e6 * c['price'][0] + tout / 1e6 * c['price'][1]
    return est


def load_rows(outdir: Path) -> list[dict]:
    from v4_writer import score as s4
    return s4.load_calls(outdir / 'calls.jsonl')


def write_outputs(outdir: Path, exp: str) -> None:
    rows = load_rows(outdir)
    cases = load_cases(exp)
    (outdir / 'summary.md').write_text(report.summarize(exp, rows, cases), encoding='utf-8')
    report.write_report(outdir, exp)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--exp', required=True, choices=EXPS)
    ap.add_argument('--candidates', nargs='*', default=DEFAULT_CANDIDATES)
    ap.add_argument('--cases', nargs='*')
    ap.add_argument('--reps', type=int, default=3)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--max-usd', type=float, default=3.0)
    ap.add_argument('--execute', action='store_true')
    ap.add_argument('--resume')
    args = ap.parse_args(argv)

    exp = args.exp
    cands = oc.load_candidates(args.candidates)
    cases = load_cases(exp)
    jobs = make_jobs(exp, cands, cases, args.reps, args.cases)
    est = estimate(exp, jobs)
    total = sum(e['usd'] for e in est.values())
    print('[%s] 총 호출 %d건 (후보 %d × 사례 %d × 반복 %d)' % (LABEL[exp], len(jobs), len(cands), len({j['variant'] for j in jobs}), args.reps))
    for cid, e in est.items():
        print('  %-14s %3d건  예상 $%.3f' % (cid, e['calls'], e['usd']))
    print('예상 합계 $%.3f  (추정치)' % total)
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
        outdir = ROOT / 'reports' / ('v6_%s_%s' % (exp, datetime.now().strftime('%Y%m%dT%H%M%S')))
        outdir.mkdir(parents=True, exist_ok=False)
    out_path = outdir / 'calls.jsonl'
    from v4_writer import score as s4
    done = {r['key'] for r in s4.load_calls(out_path) if r.get('ok')}
    (outdir / 'meta.json').write_text(json.dumps({
        'exp': exp, 'label': LABEL[exp], 'started_at': datetime.now().isoformat(timespec='seconds'),
        'candidates': oc.merge_candidates(outdir, cands), 'reps': args.reps, 'estimated_usd': round(total, 4)}, ensure_ascii=False, indent=2), encoding='utf-8')

    sch, clients = schemas(), {}

    def call_fn(cand, messages):
        if cand['id'] not in clients:
            clients[cand['id']] = oc.make_client(cand)
        return oc.call(clients[cand['id']], cand, messages, sch[messages[0]['content']])

    v1run.run_jobs(jobs, call_fn, out_path, done, args.workers)
    write_outputs(outdir, exp)
    build_index.build(ROOT / 'reports')
    print('완료: %s' % (outdir / 'report.html'))
    print('표: %s' % (outdir / 'summary.md'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
