# -*- coding: utf-8 -*-
"""판정 후보(풀) 만들기.

  python -X utf8 eval/build_pool.py              전 질의
  python -X utf8 eval/build_pool.py --qids q001 q002
  python -X utf8 eval/build_pool.py --plan       색인 정합성과 질의 문장만 확인

후보 = Dense(Chroma)@20 ∪ BM25@10. 중복을 빼고 **자르지 않는다**(최대 30).
판정 순서는 seed 로 섞는다. 판정 화면은 순위·점수·출처 시스템을 보여주지 않는다.

이미 풀이 있으면 **기존 행은 그대로 두고 새 쌍만 더한다.** 판정이 붙은 쌍이
사라지면 안 된다. 새 검색 방식의 상위 결과를 추가 판정할 때도 이 경로를 쓴다.
"""
import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

DENSE_K = 20
BM25_K = 10
SHUFFLE_SEED = 20260915


def corpus():
    """(docs, 공고집합 해시). 문서 텍스트는 임베딩과 **같은 입력**(embed.build_input)."""
    import embed
    import store_mysql
    connection = store_mysql.connect()
    try:
        rows = embed.load_rows(connection)
    finally:
        connection.close()
    docs, shas = [], {}
    for row in rows:
        text = embed.build_input(row)
        if text:
            docs.append((row['notice_id'], text))
            shas[row['notice_id']] = embed.input_sha256(text)
    sig = '\n'.join('%s %s' % (nid, shas[nid]) for nid in sorted(shas))
    return docs, hashlib.sha256(sig.encode()).hexdigest(), shas


def index_check(docs, shas, say):
    """벡터 파일·Chroma 가 지금 공고와 맞는지. 낡은 색인을 모델 성능 문제로 오인하지 않게."""
    import numpy as np
    import vecstore
    data = np.load(vecstore.NPZ, allow_pickle=False)
    vec_sha = dict(zip([str(x) for x in data['notice_ids']], [str(x) for x in data['input_sha256']]))
    meta = json.loads(str(data['meta']))
    col = vecstore.open_chroma()
    doc_ids = {d for d, _ in docs}
    stale = [n for n in doc_ids if n in vec_sha and vec_sha[n] != shas[n]]
    missing = [n for n in doc_ids if n not in vec_sha]
    info = {'notices': len(doc_ids), 'vectors': len(vec_sha), 'chroma': col.count(),
            'stale_vectors': len(stale), 'missing_vectors': len(missing),
            'embed_meta': meta}
    say('공고 %d · 벡터 %d · Chroma %d · 낡은 벡터 %d · 벡터 없음 %d'
        % (info['notices'], info['vectors'], info['chroma'], len(stale), len(missing)))
    if stale or missing or info['chroma'] != info['vectors']:
        say('  ⚠ 색인이 공고와 어긋난다. daily_pipeline 을 먼저 돌리는 것이 좋다.')
    return info


def git_rev():
    try:
        return subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'],
                                       cwd=common.ROOT, text=True).strip()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--qids', nargs='*')
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--add-from', dest='add_from',
                    help='다른 검색 방식의 상위 결과 JSONL 을 읽어 쌍만 더한다. '
                         '{qid, notice_id, rank, system} 행. Dense·BM25 는 다시 돌리지 않는다.')
    args = ap.parse_args()

    queries = common.load_queries()
    targets = [q for qid, q in queries.items() if not args.qids or qid in args.qids]
    print('질의 %d개' % len(targets))

    docs, corpus_hash, shas = corpus()
    if args.add_from:
        # 쌍만 더하는 경로에서는 Dense·BM25 를 다시 돌리지 않으므로 색인 정합성도 보지 않는다.
        # (색인 검사는 data/embeddings_v1.npz 를 읽는데, 학습용 PC 에는 그 파일이 없다)
        info = {'skipped': 'add-from 경로라 색인 검사를 하지 않았다'}
        print('색인 검사 건너뜀 (쌍 추가 전용 경로)')
    else:
        info = index_check(docs, shas, print)

    if args.plan:
        for q in targets[:5]:
            print('  %s  %s' % (q['qid'], common.query_text(q)))
        return 0

    existing = common.read_jsonl(common.POOL)
    have = {(p['qid'], p['notice_id']) for p in existing}
    added = []

    if args.add_from:
        # 다른 검색 방식(리랭커 등)이 상위에 올린 공고를 판정 대상에 더한다.
        # 기존 쌍은 건드리지 않는다. 순서는 여기서도 섞어 판정자가 순위를 못 보게 한다.
        rows = common.read_jsonl(args.add_from)
        if not rows:
            print('⚠ %s 에서 읽은 행이 0개다. 경로를 확인한다.' % args.add_from)
            return 1
        want = {q['qid'] for q in targets}
        max_order = {}
        for p in existing:
            max_order[p['qid']] = max(max_order.get(p['qid'], -1), p.get('order', -1))
        by_qid = {}
        for r in rows:
            if r['qid'] in want:
                by_qid.setdefault(r['qid'], []).append(r)
        for qid in sorted(by_qid):
            fresh = sorted({r['notice_id'] for r in by_qid[qid]}
                           - {n for (q_, n) in have if q_ == qid})
            random.Random('%s:%s:add' % (SHUFFLE_SEED, qid)).shuffle(fresh)
            systems = sorted({r.get('system', '?') for r in by_qid[qid]})
            for i, nid in enumerate(fresh):
                added.append({
                    'qid': qid, 'notice_id': nid,
                    'order': max_order.get(qid, -1) + 1 + i,
                    'dense_rank': None, 'dense_score': None,
                    'bm25_rank': None, 'bm25_score': None,
                    'added_by': '+'.join(systems),
                })
            print('  %s  받은 후보 %2d · 새로 %2d  | %s'
                  % (qid, len(by_qid[qid]), len(fresh), ','.join(systems)))
        print('\n새 쌍 %d개를 더한다.' % len(added))
        return finish(existing, added, shas, info, corpus_hash, targets,
                      method={'added_from': os.path.basename(args.add_from),
                              'shuffle_seed': SHUFFLE_SEED})

    import vecstore
    from bm25 import BM25
    print('BM25 색인...')
    bm25 = BM25(docs)

    for q in targets:
        text = common.query_text(q)
        qv = vecstore.embed_query(text)
        dense, _ = vecstore.search(text, top=DENSE_K + 1, engine='chroma', qv=qv)
        dense = [(n, s) for n, s in dense if n != '__watermark__'][:DENSE_K]
        lexical = bm25.search(text, top=BM25_K)

        cand = {}
        for rank, (nid, score) in enumerate(dense, 1):
            cand[nid] = {'dense_rank': rank, 'dense_score': round(float(score), 4)}
        for rank, (nid, score) in enumerate(lexical, 1):
            cand.setdefault(nid, {}).update({'bm25_rank': rank, 'bm25_score': round(score, 3)})

        rng = random.Random('%s:%s' % (SHUFFLE_SEED, q['qid']))
        ids = sorted(cand)
        rng.shuffle(ids)
        new = 0
        for order, nid in enumerate(ids):
            if (q['qid'], nid) in have:
                continue
            row = {'qid': q['qid'], 'notice_id': nid, 'order': order,
                   'dense_rank': None, 'dense_score': None, 'bm25_rank': None, 'bm25_score': None,
                   'added_by': 'dense@%d+bm25@%d' % (DENSE_K, BM25_K)}
            row.update(cand[nid])
            added.append(row)
            new += 1
        overlap = sum(1 for v in cand.values() if 'dense_rank' in v and 'bm25_rank' in v)
        print('  %s  후보 %2d (겹침 %d) 새로 %2d  | %s'
              % (q['qid'], len(cand), overlap, new, text[:60]))

    return finish(existing, added, shas, info, corpus_hash, targets,
                  method={'dense': 'chroma@%d' % DENSE_K, 'bm25': 'char2gram@%d' % BM25_K,
                          'bm25_input': 'embed.build_input (임베딩과 동일)', 'truncate': False,
                          'shuffle_seed': SHUFFLE_SEED})


def finish(existing, added, shas, info, corpus_hash, targets, method):
    """풀 저장 · 스냅샷 갱신 · 메타 기록. 두 경로(신규 생성 / 쌍 추가)가 같이 쓴다."""
    pool = existing + added
    common.write_jsonl(common.POOL, pool)

    # 판정 시점 공고 내용 스냅샷. 이미 있는 공고는 덮어쓰지 않는다(판정 당시 내용 보존).
    snap = common.load_snapshot()
    need = sorted({p['notice_id'] for p in pool} - set(snap))
    if need:
        fresh = common.load_notices(need)
        for nid in need:
            if nid in fresh:
                item = fresh[nid]
                item['input_sha256'] = shas.get(nid)
                item['snapshot_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
                snap[nid] = item
    os.makedirs(os.path.dirname(common.SNAPSHOT), exist_ok=True)
    common.write_jsonl(common.SNAPSHOT, [snap[k] for k in sorted(snap)])
    snap_hash = hashlib.sha256(open(common.SNAPSHOT, 'rb').read()).hexdigest()

    meta = {}
    if os.path.exists(common.POOL_META):
        with open(common.POOL_META, encoding='utf-8') as f:
            meta = json.load(f)
    meta.setdefault('history', []).append({
        'at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'git': git_rev(), 'qids': [q['qid'] for q in targets],
        'method': method,
        'corpus_sha256': corpus_hash, 'index': info,
        'snapshot_sha256': snap_hash, 'added_pairs': len(added)})
    meta.update({'label_version': common.LABEL_VERSION, 'pairs': len(pool),
                 'queries': len({p['qid'] for p in pool}), 'snapshot_notices': len(snap)})
    with open(common.POOL_META, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

    print('\n풀 %d쌍 (새로 %d) · 스냅샷 공고 %d건 · %s'
          % (len(pool), len(added), len(snap), common.POOL))
    return 0


if __name__ == '__main__':
    sys.exit(main())
