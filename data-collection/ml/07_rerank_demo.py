# -*- coding: utf-8 -*-
"""리랭커 시연 · 속도 측정. GPU 가 있으면 GPU, 없으면 CPU 로 돈다.

  python ml/07_rerank_demo.py                        기본 시연 (자동 감지)
  python ml/07_rerank_demo.py --device cpu           CPU 로 강제
  python ml/07_rerank_demo.py --bench                설정별 속도 표
  python ml/07_rerank_demo.py --qid q001             평가셋 질의로 시연
  python ml/07_rerank_demo.py --idea "금형공장 불량 검출 비전 AI 장비"

## 무엇을 보여주나

검색이 뽑은 후보를 리랭커가 **다시 읽고 순서를 바꾸는 과정**을 눈으로 본다.
그리고 그게 **몇 밀리초 걸리는지**를 이 PC 에서 직접 잰다.

## --bench 가 중요한 이유

리랭커를 서비스에 올리려면 "얼마나 느린가"를 알아야 한다. 후보 수와 문장 길이를
줄이면 빨라지는데, 얼마나 빨라지는지는 **PC 마다 다르므로 직접 재야 한다.**
`--bench` 가 조합별로 재서 표로 보여준다.

## 준비물

- `.env` (EC2 DB 접속)
- 벡터 색인 — 없으면 `python ec2_vecstore.py --rebuild`
- `ml/models/reranker_lora/` — 없으면 사전학습 모델로만 시연한다
- 처음 실행 시 BGE-M3(2.2GB)·BGE-reranker(2.2GB)를 내려받는다
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.environ.setdefault('HF_HUB_OFFLINE', '0')
os.chdir(ROOT)
sys.path[:0] = [ROOT, os.path.join(ROOT, 'eval'), HERE]

import rerank_common as rc

DEFAULT_IDEA = '중소 금형공장의 불량 검출을 위한 비전 AI 검사 장비를 만든다'


def say(*a):
    print(*a, flush=True)


def build_query(args):
    """평가셋 질의를 쓰거나, 직접 준 문장을 쓴다."""
    if args.qid:
        import common
        queries = common.load_queries()
        if args.qid not in queries:
            raise SystemExit('그런 질의가 없다: %s' % args.qid)
        return common.query_text(queries[args.qid]), '평가셋 %s' % args.qid
    return args.idea, '직접 입력'


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--device', choices=['cpu', 'cuda'], help='기본은 자동 감지')
    ap.add_argument('--candidates', type=int, default=30, help='리랭커가 다시 읽을 후보 수')
    ap.add_argument('--max-len', dest='max_len', type=int, default=512, help='질의+공고 최대 길이')
    ap.add_argument('--qid', help='평가셋 질의 번호 (예: q001)')
    ap.add_argument('--idea', default=DEFAULT_IDEA, help='직접 넣을 사업 설명')
    ap.add_argument('--base', action='store_true', help='학습 전(사전학습) 모델로')
    ap.add_argument('--bench', action='store_true', help='설정별 속도만 잰다')
    args = ap.parse_args()

    import torch
    device = args.device or ('cuda' if torch.cuda.is_available() else 'cpu')
    name = torch.cuda.get_device_name(0) if device == 'cuda' else 'CPU'
    say('장치 : %s (%s)' % (device, name))
    if device == 'cpu':
        say('      ⚠ CPU 는 GPU 보다 10~20배 느리다. 실제 값을 아래에서 잰다.')

    adapter = None if args.base else rc.ADAPTER_DIR
    if adapter and not os.path.exists(adapter):
        say('학습한 모델이 없어 사전학습 모델로 시연한다 (%s)' % adapter)
        adapter = None

    # ── 후보 뽑기 ─────────────────────────────────────────
    query, source = build_query(args)
    say('')
    say('질의 (%s)' % source)
    say('  %s' % query[:150])

    from search import vecstore
    import common

    # 첫 호출에는 모델을 메모리에 올리는 시간(수십 초)이 섞인다.
    # 서비스에서는 한 번만 겪는 비용이므로, 예열한 뒤 두 번째부터 잰다.
    t0 = time.time()
    qv = vecstore.embed_query(query)
    vecstore.search(query, top=2, engine='chroma', qv=qv)
    warmup_s = time.time() - t0

    t0 = time.time()
    qv = vecstore.embed_query(query)
    embed_ms = (time.time() - t0) * 1000

    t0 = time.time()
    hits, _ = vecstore.search(query, top=args.candidates + 1, engine='chroma', qv=qv)
    hits = [(n, s) for n, s in hits if n != '__watermark__'][:args.candidates]
    search_ms = (time.time() - t0) * 1000

    ids = [n for n, _ in hits]
    notices = common.load_notices(ids, with_attachment=False)
    texts = [rc.notice_text(notices[n]) if n in notices else '' for n in ids]
    titles = {n: (notices[n].get('title') or '')[:52] for n in notices}

    say('')
    say('후보 %d건 · 질의 벡터화 %.0fms · 검색 %.1fms  (첫 준비 %.0f초는 뺐다)'
        % (len(ids), embed_ms, search_ms, warmup_s))

    # ── 속도 표 ───────────────────────────────────────────
    if args.bench:
        say('')
        say('설정별 리랭킹 시간 (%s)' % name)
        say('%-12s %-12s %-14s %s' % ('후보 수', '문장 길이', '리랭킹 시간', '질의당 총 시간'))
        say('-' * 62)
        for n_cand in (30, 20, 10):
            for max_len in (512, 256):
                scorer = rc.Scorer(adapter=adapter, device=device, max_len=max_len)
                sub = texts[:n_cand]
                scorer.score(query, sub[:max(2, len(sub)//2)])   # 예열
                t0 = time.time()
                scorer.score(query, sub)
                ms = (time.time() - t0) * 1000
                say('%-12d %-12d %-14s %s'
                    % (n_cand, max_len, '%.0f ms' % ms,
                       '%.0f ms' % (ms + embed_ms + search_ms)))
                del scorer
        say('')
        say('기존 검색만 쓰면 질의당 약 %.0f ms 다. 위 값과 견주어 판단한다.'
            % (embed_ms + search_ms))
        return

    # ── 시연 ──────────────────────────────────────────────
    t0 = time.time()
    scorer = rc.Scorer(adapter=adapter, device=device, max_len=args.max_len)
    load_s = time.time() - t0

    scorer.score(query, texts[:max(2, len(texts)//2)])    # 예열
    t0 = time.time()
    scores = scorer.score(query, texts)
    rerank_ms = (time.time() - t0) * 1000

    before = ids[:5]
    after = [n for n, _ in sorted(zip(ids, scores), key=lambda x: -x[1])][:5]
    rank_before = {n: i + 1 for i, n in enumerate(ids)}

    say('')
    say('모델 준비 %.1f초 · 리랭킹 %.0f ms (%s%s)'
        % (load_s, rerank_ms, '사전학습' if adapter is None else '학습한 모델',
           ' · 후보 %d · 길이 %d' % (len(ids), args.max_len)))
    say('')
    say('%-4s %-54s   %-4s %-54s' % ('전', '', '후', ''))
    say('-' * 124)
    for i in range(5):
        b = before[i] if i < len(before) else None
        a = after[i] if i < len(after) else None
        moved = ''
        if a is not None:
            was = rank_before.get(a)
            if was and was != i + 1:
                moved = ' (%d위→%d위)' % (was, i + 1)
        say('%-4d %-54s   %-4d %-54s'
            % (i + 1, titles.get(b, '')[:52], i + 1, (titles.get(a, '') + moved)[:52]))

    up = [n for n in after if rank_before.get(n, 99) > 5]
    say('')
    if up:
        say('5위 밖에서 올라온 공고 %d건 — 리랭커가 끌어올린 것이다' % len(up))
        for n in up:
            say('   %d위 → %d위  %s' % (rank_before[n], after.index(n) + 1, titles.get(n, '')))
    else:
        say('상위 5건의 구성은 바뀌지 않았다 (순서만 달라졌을 수 있다).')

    say('')
    say('질의당 총 시간 : %.0f ms  (벡터화 %.0f + 검색 %.1f + 리랭킹 %.0f)'
        % (embed_ms + search_ms + rerank_ms, embed_ms, search_ms, rerank_ms))
    say('리랭커 없이 쓰면 %.0f ms 다.' % (embed_ms + search_ms))


if __name__ == '__main__':
    main()
