"""작성 T-W1·T-W2·T-W3 모델 비교 실행기. 기본은 '계획만 보기'(API 호출 0). --execute 를 줘야 실제로 호출한다.

  python -m v4_writer.run                                        # 계획만 (전체 후보 × 아이템 8건 × Task 3종 × 3회 + 채점자 호출)
  python -m v4_writer.run --candidates luna-medium --reps 1      # 계획만, 후보 하나
  python -m v4_writer.run --candidates luna-medium --reps 1 --execute
  python -m v4_writer.run --resume reports/v4_… --execute        # 끊긴 실행 이어서(생성·채점 모두)
T-W1(본문) 결과는 자동으로 검증-1 채점자(luna-medium)에게 넘겨 글 품질 점수를 받는다(--no-judge 로 끔).
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
from v1_verifier import prompt as jprompt, run as v1run, variants as jvariants  # noqa: E402
from v4_writer import prompt, report, score  # noqa: E402

BASE_OUT = 1100         # T-W1 약 1,800 · T-W2 약 400 · T-W3 약 500 토큰 가정. 첫 실행 뒤 바로잡는다
JUDGE_ID = 'luna-medium'
TASKS = ('w1', 'w2', 'w3')


def make_jobs(cands, cases, reps, only_cases=None, tasks=TASKS):
    builders = {'w1': prompt.build_w1, 'w2': prompt.build_w2, 'w3': prompt.build_w3}
    jobs = []
    for cid, case in cases.items():
        if only_cases and cid not in only_cases:
            continue
        for task in tasks:
            messages = builders[task](case)
            for cand in cands:
                for rep in range(1, reps + 1):
                    jobs.append({'key': '%s|%s|%s|%d' % (cand['id'], task, cid, rep), 'cand': cand, 'plan': task, 'variant': cid,
                                 'rep': rep, 'messages': messages, 'extra': {'task': task, 'case': cid}})
    return jobs


def plan_text(data: dict) -> str:
    return '\n\n'.join('%s\n%s' % (s['title'], s['text']) for s in data['sections'])


def make_judge_jobs(rows: list[dict], judge_cand: dict, rubric: dict) -> list[dict]:
    jobs = []
    for r in rows:
        if r['task'] == 'w1' and r.get('ok') and isinstance(r['data'].get('sections'), list):
            jobs.append({'key': 'judge|' + r['key'], 'cand': judge_cand, 'plan': 'judge', 'variant': r['case'], 'rep': r['rep'],
                         'messages': jprompt.build_messages(rubric, plan_text(r['data'])),
                         'extra': {'src': r['key'], 'task': 'judge', 'case': r['case']}})
    return jobs


def load_rows(outdir: Path) -> list[dict]:
    return score.load_calls(outdir / 'calls.jsonl')


def load_judge(outdir: Path):
    rows = score.load_calls(outdir / 'judge.jsonl')
    return score.judge_scores(rows, jvariants.load_rubric()), sum(r.get('cost') or 0 for r in rows)


def write_outputs(outdir: Path) -> None:
    cases = prompt.load_cases()
    judge, jcost = load_judge(outdir)
    (outdir / 'summary.md').write_text(score.summarize(load_rows(outdir), cases, judge, jcost), encoding='utf-8')
    report.write_report(outdir)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--candidates', nargs='*', help='후보 id (기본: candidates.json 전부)')
    ap.add_argument('--cases', nargs='*', help='아이템 id (기본: 전부)')
    ap.add_argument('--tasks', nargs='*', default=list(TASKS), choices=list(TASKS))
    ap.add_argument('--reps', type=int, default=3)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--no-judge', action='store_true', help='글 품질 채점자 호출을 건너뛴다')
    ap.add_argument('--max-usd', type=float, default=1.0, help='예상 비용이 이 값을 넘으면 실행하지 않는다')
    ap.add_argument('--execute', action='store_true', help='실제로 API를 호출한다(없으면 계획만 출력)')
    ap.add_argument('--resume', help='이어서 실행할 reports/ 폴더')
    ap.add_argument('--name', help='새 결과 폴더 이름 접미사')
    args = ap.parse_args(argv)

    cands = oc.load_candidates(args.candidates)
    cases = prompt.load_cases()
    jobs = make_jobs(cands, cases, args.reps, args.cases, tuple(args.tasks))
    v1run.BASE_OUT_TOKENS = BASE_OUT
    est = v1run.estimate(jobs)
    total = sum(e['usd'] for e in est.values())
    judge_cand = oc.load_candidates([JUDGE_ID])[0]
    n_judge = 0 if args.no_judge or 'w1' not in args.tasks else sum(1 for j in jobs if j['plan'] == 'w1')
    judge_est = n_judge * (2500 / 1e6 * judge_cand['price'][0] + 1000 / 1e6 * judge_cand['price'][1])
    print('총 호출 %d건 (후보 %d × 아이템 %d × Task %d × 반복 %d) + 채점자 %d건' % (
        len(jobs), len(cands), len({j['variant'] for j in jobs}), len(args.tasks), args.reps, n_judge))
    for cid, e in est.items():
        print('  %-14s %3d건  입력 약 %.0fk·출력 약 %.0fk 토큰  예상 $%.3f' % (cid, e['calls'], e['tin'] / 1e3, e['tout'] / 1e3, e['usd']))
    print('  %-14s %3d건  (채점자 %s)  예상 $%.3f' % ('채점자', n_judge, JUDGE_ID, judge_est))
    total += judge_est
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
        outdir = ROOT / 'reports' / ('v4_%s%s' % (stamp, ('_' + args.name) if args.name else ''))
        outdir.mkdir(parents=True, exist_ok=False)
    out_path, judge_path = outdir / 'calls.jsonl', outdir / 'judge.jsonl'
    done = {r['key'] for r in score.load_calls(out_path) if r.get('ok')}
    (outdir / 'meta.json').write_text(json.dumps({
        'prompt_version': prompt.PROMPT_VERSION, 'judge': JUDGE_ID, 'started_at': datetime.now().isoformat(timespec='seconds'),
        'candidates': oc.merge_candidates(outdir, cands), 'reps': args.reps, 'estimated_usd': round(total, 4)}, ensure_ascii=False, indent=2), encoding='utf-8')

    schemas = {prompt.W1_SYSTEM: prompt.w1_schema(), prompt.W2_SYSTEM: prompt.w2_schema(), prompt.W3_SYSTEM: prompt.w3_schema(),
               jprompt.SYSTEM: jprompt.output_schema(jvariants.load_rubric())}
    clients = {}

    def call_fn(cand, messages):
        if cand['id'] not in clients:
            clients[cand['id']] = oc.make_client(cand)
        return oc.call(clients[cand['id']], cand, messages, schemas[messages[0]['content']])

    v1run.run_jobs(jobs, call_fn, out_path, done, args.workers)
    if n_judge:
        jdone = {r['key'] for r in score.load_calls(judge_path) if r.get('ok')}
        v1run.run_jobs(make_judge_jobs(load_rows(outdir), judge_cand, jvariants.load_rubric()), call_fn, judge_path, jdone, args.workers)
    write_outputs(outdir)
    build_index.build(ROOT / 'reports')
    print('완료: %s' % (outdir / 'report.html'))
    print('표: %s' % (outdir / 'summary.md'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
