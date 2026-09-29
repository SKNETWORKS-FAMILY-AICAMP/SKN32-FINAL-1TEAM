# -*- coding: utf-8 -*-
"""리랭커가 상위에 올린 공고를 판정 대상 목록으로 뽑는다. GPU 로 돌린다.

  python ml/06_rerank_pool.py --plan     대상 질의·후보 수만 확인
  python ml/06_rerank_pool.py            목록 생성

## 왜 필요한가

05 번 평가에서 **미판정 47%** 가 나왔다. 리랭커가 뒤쪽에 묻혀 있던 공고를
위로 끌어올리는데, 그 공고들은 아무도 판정한 적이 없어서 전부 0 점으로 처리된다.
`eval/evaluate.py` 설명문에 "미판정이 높으면 그 시스템 숫자를 믿지 않는다" 고
적혀 있는 그 상황이다.

`eval/README.md` 의 절차는 이렇다 —
**새 방식이 미판정 공고를 올리면 쌍을 추가하고 판정을 보충한 뒤 전부 다시 평가한다.**
이 스크립트가 그 첫 단계다.

## 무엇을 뽑나

시험 질의 20개에 대해, 사전학습 리랭커와 학습한 리랭커가 각각 매긴 **상위 TOP_N**.
두 모델을 다 넣는 이유는 한쪽에 유리한 판정 쏠림을 막기 위해서다.

## 다음 단계

  python -X utf8 eval/build_pool.py --add-from ml/data/rerank_candidates.jsonl \\
                                    --qids <시험 질의들>
  python -X utf8 eval/judge_llm.py --plan      ← 비용 확인 (유료 API)
  python -X utf8 eval/judge_llm.py
  python -X utf8 eval/merge_qrels.py
  그리고 05_reranker_report.ipynb 를 다시 돌린다
"""
import argparse
import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.environ.setdefault('HF_HUB_OFFLINE', '0')
sys.path[:0] = [ROOT, os.path.join(ROOT, 'eval'), HERE]

import rerank_common as rc

POOL_SIZE = 30      # 리랭커가 다시 읽는 후보 수. 05 노트북과 같아야 한다
TOP_N = 10          # 그중 상위 몇 개를 판정 대상으로 올릴지
OUT = os.path.join(HERE, 'data', 'rerank_candidates.jsonl')


def say(*a):
    print(*a, flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--top', type=int, default=TOP_N)
    ap.add_argument('--out', default=OUT)
    ap.add_argument('--plan', action='store_true')
    args = ap.parse_args()

    import common
    import evaluate as ev

    splits = rc.load_splits()
    queries = common.load_queries()
    test_queries = {q: queries[q] for q in splits['test'] if q in queries}
    qrels = rc.load_qrels()

    say('시험 질의 %d개 · 후보 %d건 중 상위 %d건을 판정 대상으로 올린다'
        % (len(test_queries), POOL_SIZE, args.top))
    say('질의 목록 : %s' % ' '.join(sorted(test_queries)))

    if args.plan:
        say('')
        say('--plan 이라 여기서 멈춘다.')
        return

    # 공고 본문은 한 번에 받아둔다 (질의마다 DB 를 열면 원격에서 끊긴다)
    t0 = time.time()
    notices = common.load_notices(None, with_attachment=False)
    texts = {nid: rc.notice_text(n) for nid, n in notices.items()}
    del notices
    say('공고 %d건 준비 %.1f초' % (len(texts), time.time() - t0))

    plain = ev.Systems()
    rows = []
    stats = {}

    for label, adapter in (('rerank_base', None), ('rerank_tuned', rc.ADAPTER_DIR)):
        if adapter and not os.path.exists(adapter):
            say('건너뜀 (%s 없음): %s' % (adapter, label))
            continue
        scorer = rc.Scorer(adapter=adapter)
        say('')
        say('[%s] 장치 %s' % (label, scorer.device))
        new_here = 0
        for qid, q in sorted(test_queries.items()):
            hits = plain.run('rrf', q, k=POOL_SIZE)
            ids = [n for n, _ in hits]
            if not ids:
                continue
            scores = scorer.score(common.query_text(q), [texts.get(i, '') for i in ids])
            ranked = sorted(zip(ids, scores), key=lambda x: -x[1])[:args.top]
            judged = qrels.get(qid, {})
            for rank, (nid, score) in enumerate(ranked, 1):
                rows.append({'qid': qid, 'notice_id': nid, 'rank': rank,
                             'score': round(float(score), 4), 'system': label})
                if nid not in judged:
                    new_here += 1
        stats[label] = new_here
        say('  미판정 %d개를 상위 %d 안에 올렸다' % (new_here, args.top))
        del scorer

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with io.open(args.out, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    unjudged_pairs = {(r['qid'], r['notice_id']) for r in rows
                      if r['notice_id'] not in qrels.get(r['qid'], {})}
    say('')
    say('저장 → %s' % args.out)
    say('행 %d개 · 서로 다른 미판정 쌍 %d개 ← 이만큼이 새로 판정할 대상이다'
        % (len(rows), len(unjudged_pairs)))
    say('')
    say('다음 :')
    say('  python -X utf8 eval/build_pool.py --add-from %s --qids %s'
        % (os.path.relpath(args.out, ROOT).replace('\\', '/'), ' '.join(sorted(test_queries))))


if __name__ == '__main__':
    main()
