"""조율 T-C1 모델 비교 실행기. 기본은 '계획만 보기'(API 호출 0). --execute 를 줘야 실제로 호출한다.

  python -m v2_coordinator.run                                    # 계획만 (전체 후보 × 사례 32건 × 3회)
  python -m v2_coordinator.run --candidates luna-medium --reps 1  # 계획만, 후보 하나
  python -m v2_coordinator.run --candidates luna-medium --reps 1 --execute
  python -m v2_coordinator.run --resume reports/v2_… --execute    # 끊긴 실행 이어서
결과는 매번 reports/ 아래 새 폴더에 쓴다(기존 폴더는 덮어쓰지 않는다).
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
from v1_verifier import run as v1run  # noqa: E402  (호출 실행·비용 추정은 검증-1과 같은 도구를 쓴다)
from v2_coordinator import prompt, report, score  # noqa: E402

CASES_PATH = ROOT / 'fixtures' / 'tc1_cases.json'
BASE_OUT = 420          # T-C1 출력 길이 실측 전 가정. 첫 실행 뒤 바로잡는다


def load_cases() -> dict[str, dict]:
    doc = json.loads(CASES_PATH.read_text(encoding='utf-8'))
    return {c['case_id']: c for c in doc['cases']}


def make_jobs(cands, cases, reps, only_cases=None):
    jobs = []
    for cid, case in cases.items():
        if only_cases and cid not in only_cases:
            continue
        messages = prompt.build_messages(case['form'])
        for cand in cands:
            for rep in range(1, reps + 1):
                jobs.append({'key': '%s|%s|%d' % (cand['id'], cid, rep), 'cand': cand, 'case': cid, 'rep': rep,
                             'messages': messages})
    return jobs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--candidates', nargs='*', help='후보 id (기본: candidates.json 전부)')
    ap.add_argument('--cases', nargs='*', help='사례 id (기본: 전부)')
    ap.add_argument('--reps', type=int, default=3)
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--max-usd', type=float, default=1.0, help='예상 비용이 이 값을 넘으면 실행하지 않는다')
    ap.add_argument('--execute', action='store_true', help='실제로 API를 호출한다(없으면 계획만 출력)')
    ap.add_argument('--resume', help='이어서 실행할 reports/ 폴더')
    ap.add_argument('--name', help='새 결과 폴더 이름 접미사')
    args = ap.parse_args(argv)

    cands = oc.load_candidates(args.candidates)
    cases = load_cases()
    jobs = make_jobs(cands, cases, args.reps, args.cases)
    v1run.BASE_OUT_TOKENS = BASE_OUT
    est = v1run.estimate(jobs)
    total = sum(e['usd'] for e in est.values())
    print('총 호출 %d건 (후보 %d × 사례 %d × 반복 %d)' % (len(jobs), len(cands), len({j['case'] for j in jobs}), args.reps))
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
        outdir = ROOT / 'reports' / ('v2_%s%s' % (stamp, ('_' + args.name) if args.name else ''))
        outdir.mkdir(parents=True, exist_ok=False)
    out_path = outdir / 'calls.jsonl'
    done = {r['key'] for r in score.load_calls(out_path) if r.get('ok')} if out_path.exists() else set()
    (outdir / 'meta.json').write_text(json.dumps({
        'prompt_version': prompt.PROMPT_VERSION, 'started_at': datetime.now().isoformat(timespec='seconds'),
        'candidates': oc.merge_candidates(outdir, cands), 'reps': args.reps, 'estimated_usd': round(total, 4)}, ensure_ascii=False, indent=2), encoding='utf-8')

    schema = prompt.output_schema()
    clients = {}

    def call_fn(cand, messages):
        if cand['id'] not in clients:
            clients[cand['id']] = oc.make_client(cand)
        return oc.call(clients[cand['id']], cand, messages, schema)

    # v1 의 실행기는 job 에 plan/variant 를 기대하지 않으므로 행을 v2 모양으로 다시 쓴다
    for j in jobs:
        j['plan'], j['variant'] = 'tc1', j['case']
    v1run.run_jobs(jobs, call_fn, out_path, done, args.workers)
    write_outputs(outdir)
    build_index.build(ROOT / 'reports')
    print('완료: %s' % (outdir / 'report.html'))
    print('표: %s' % (outdir / 'summary.md'))
    return 0


def write_outputs(outdir: Path) -> None:
    cases = load_cases()
    rows = load_rows(outdir)
    (outdir / 'summary.md').write_text(score.summarize(rows, cases), encoding='utf-8')
    report.write_report(outdir)


def load_rows(outdir: Path) -> list[dict]:
    rows = score.load_calls(outdir / 'calls.jsonl')
    for r in rows:
        r['case'] = r.get('case') or r['variant']
    return rows


if __name__ == '__main__':
    raise SystemExit(main())
