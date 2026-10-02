"""구현 T-B1(HTML)·T-B2(SVG 인포그래픽) 모델 비교 실행기. 기본은 '계획만 보기'(API 호출 0). --execute 를 줘야 실제로 호출한다.

  python -m v5_builder.run                                        # 계획만 (기본 후보 5개 × 아이템 × 반복 2)
  python -m v5_builder.run --candidates luna-medium --reps 1      # 계획만, 후보 하나
  python -m v5_builder.run --reps 1 --execute                     # 반복 1회로 먼저 시험 실행
  python -m v5_builder.run --resume reports/v5_… --reps 2 --execute   # 남은 반복만 이어서(이미 한 호출은 건너뜀)
T-B1 은 웹개발·AI API 아이템 6건(HTML), T-B2 는 8건 모두(SVG). 결과는 매번 reports/ 아래 새 폴더에 쓴다.
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
from v1_verifier import run as v1run  # noqa: E402  (병렬 실행 도구를 검증-1과 같이 쓴다)
from v5_builder import prompt, report, score  # noqa: E402

DEFAULT_CANDIDATES = ['codex-5.3', 'luna-medium', 'gpt-5.4-mini', 'gpt-4.1', 'gpt-4.1-mini']
OUT_TOKENS = {'b1': 6000, 'b2': 3500}            # 코드 길이 가정(첫 실행 뒤 실측으로 바로잡는다)
THINK_TOKENS = {'low': 1000, 'medium': 2500, 'high': 6000}


def make_jobs(cands, cases, reps, only_cases=None, tasks=('b1', 'b2')):
    jobs = []
    for cid, case in cases.items():
        if only_cases and cid not in only_cases:
            continue
        for task in tasks:
            if task == 'b1' and case['item_spec']['category'] == '원페이지':
                continue                                  # 원페이지는 실행 파일 Task를 생략한다(기능정의서 T-B1)
            messages = prompt.build_b1(case) if task == 'b1' else prompt.build_b2(case)
            for cand in cands:
                for rep in range(1, reps + 1):
                    jobs.append({'key': '%s|%s|%s|%d' % (cand['id'], task, cid, rep), 'cand': cand, 'plan': task, 'variant': cid,
                                 'rep': rep, 'messages': messages, 'extra': {'task': task, 'case': cid}})
    return jobs


def estimate(jobs):
    est = {}
    for j in jobs:
        c = j['cand']
        tin = sum(len(m['content']) for m in j['messages']) / 1.55
        tout = OUT_TOKENS[j['plan']] + (THINK_TOKENS.get(c.get('reasoning_effort'), 2500) if c.get('reasoning') else 0)
        e = est.setdefault(c['id'], {'calls': 0, 'usd': 0.0})
        e['calls'] += 1
        e['usd'] += tin / 1e6 * c['price'][0] + tout / 1e6 * c['price'][1]
    return est


def load_rows(outdir: Path) -> list[dict]:
    return score.load_calls(outdir / 'calls.jsonl')


def write_outputs(outdir: Path) -> None:
    (outdir / 'summary.md').write_text(score.summarize(load_rows(outdir), prompt.load_cases()), encoding='utf-8')
    report.write_report(outdir)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--candidates', nargs='*', default=DEFAULT_CANDIDATES, help='후보 id (기본: %s)' % ' '.join(DEFAULT_CANDIDATES))
    ap.add_argument('--cases', nargs='*', help='아이템 id (기본: 전부)')
    ap.add_argument('--tasks', nargs='*', default=['b1', 'b2'], choices=['b1', 'b2'])
    ap.add_argument('--reps', type=int, default=2)
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--max-usd', type=float, default=8.0, help='예상 비용이 이 값을 넘으면 실행하지 않는다')
    ap.add_argument('--execute', action='store_true', help='실제로 API를 호출한다(없으면 계획만 출력)')
    ap.add_argument('--resume', help='이어서 실행할 reports/ 폴더')
    ap.add_argument('--name', help='새 결과 폴더 이름 접미사')
    args = ap.parse_args(argv)

    cands = oc.load_candidates(args.candidates)
    cases = prompt.load_cases()
    jobs = make_jobs(cands, cases, args.reps, args.cases, tuple(args.tasks))
    est = estimate(jobs)
    total = sum(e['usd'] for e in est.values())
    print('총 호출 %d건 (후보 %d × 아이템 × Task × 반복 %d; T-B1은 원페이지 제외)' % (len(jobs), len(cands), args.reps))
    for cid, e in est.items():
        print('  %-14s %3d건  예상 $%.3f' % (cid, e['calls'], e['usd']))
    print('예상 합계 $%.2f  (추정: 코드 길이·추론 토큰은 가정값이라 실제와 다를 수 있음)' % total)
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
        outdir = ROOT / 'reports' / ('v5_%s%s' % (stamp, ('_' + args.name) if args.name else ''))
        outdir.mkdir(parents=True, exist_ok=False)
    out_path = outdir / 'calls.jsonl'
    done = {r['key'] for r in score.load_calls(out_path) if r.get('ok')}
    (outdir / 'meta.json').write_text(json.dumps({
        'prompt_version': prompt.PROMPT_VERSION, 'started_at': datetime.now().isoformat(timespec='seconds'),
        'candidates': oc.merge_candidates(outdir, cands), 'reps': args.reps, 'estimated_usd': round(total, 4)}, ensure_ascii=False, indent=2), encoding='utf-8')

    clients = {}

    def call_fn(cand, messages):
        if cand['id'] not in clients:
            clients[cand['id']] = oc.make_client(cand)
        text, usage = oc.call_text(clients[cand['id']], cand, messages)
        return {'text': text}, usage

    v1run.run_jobs(jobs, call_fn, out_path, done, args.workers)
    write_outputs(outdir)
    build_index.build(ROOT / 'reports')
    print('완료: %s' % (outdir / 'report.html'))
    print('표: %s' % (outdir / 'summary.md'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
