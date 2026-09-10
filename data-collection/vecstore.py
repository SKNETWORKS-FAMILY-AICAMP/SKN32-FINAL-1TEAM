# -*- coding: utf-8 -*-
"""벡터 색인 — 같은 벡터를 여러 엔진에 담아 비교한다.

  python vecstore.py --build              전 엔진 색인 생성
  python vecstore.py --build --engine chroma
  python vecstore.py --stat
  python vecstore.py "사업아이템" --engine qdrant

**MySQL 이 원본이고 여기는 파생 색인이다.** 색인이 깨지면 다시 만들면 된다.
공고와 벡터의 정합성은 MySQL 이 책임진다.

지금은 `notices` 에 임베딩 컬럼이 없어 `data/embeddings_v1.npz` 를 읽는다.
컬럼이 생기면 `load_vectors()` 만 DB 를 읽도록 바꾸면 된다.

엔진이 달라도 **결과는 같아야 한다.** 다르면 근사 검색이 개입한 것이고,
이 규모(2천 건)에서는 그럴 이유가 없다.
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
NPZ = os.path.join(HERE, 'data', 'embeddings_v1.npz')
STORE = os.path.join(HERE, 'data', 'vecstore')
COLLECTION = 'notices_v1'

ENGINES = ('chroma', 'qdrant', 'faiss', 'numpy')
_model = None
_cache = {}


def load_vectors(path=NPZ):
    """(notice_ids, vectors, meta). 나중에 여기만 DB 읽기로 바꾼다."""
    import numpy as np
    data = np.load(path, allow_pickle=False)
    meta = json.loads(str(data['meta']))
    return ([str(x) for x in data['notice_ids']],
            np.ascontiguousarray(data['vectors'], dtype='float32'), meta)


def embed_query(text):
    """질의도 공고와 **같은 모델·같은 설정**이어야 한다."""
    global _model
    import embed as embed_mod
    if _model is None:
        os.environ.setdefault('HF_HUB_OFFLINE', '1')
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(embed_mod.MODEL)
        _model.max_seq_length = embed_mod.MAX_TOKENS
    import numpy as np
    return np.asarray(_model.encode([text], normalize_embeddings=True)[0], dtype='float32')


# ── Chroma ────────────────────────────────────────────────
def _chroma_path():
    return os.path.join(STORE, 'chroma')


def build_chroma(ids, vectors, meta, say):
    import chromadb
    os.makedirs(_chroma_path(), exist_ok=True)
    conn = chromadb.PersistentClient(path=_chroma_path())
    try:
        conn.delete_collection(COLLECTION)
    except Exception:
        pass
    col = conn.create_collection(COLLECTION, metadata={'hnsw:space': 'cosine',
                                                       'embed_meta': json.dumps(meta)})
    for i in range(0, len(ids), 1000):
        chunk = ids[i:i + 1000]
        col.add(ids=chunk, embeddings=vectors[i:i + 1000].tolist(),
                metadatas=[{'notice_id': x, 'source': x.split(':')[0]} for x in chunk])
        say('  chroma %d/%d' % (min(i + 1000, len(ids)), len(ids)))
    return col.count()


def open_chroma():
    import chromadb
    return chromadb.PersistentClient(path=_chroma_path()).get_collection(COLLECTION)


def search_chroma(col, qv, top, allow):
    kw = {'query_embeddings': [qv.tolist()], 'n_results': top}
    if allow is not None:
        kw['n_results'] = min(top, len(allow))
        kw['where'] = {'notice_id': {'$in': list(allow)}}
    out = col.query(**kw)
    # Chroma 는 코사인 '거리' 를 준다. 유사도 = 1 - 거리
    return [(i, 1.0 - d) for i, d in zip(out['ids'][0], out['distances'][0])]


# ── Qdrant (로컬 모드, 서버 없음) ────────────────────────────
def _qdrant_path():
    return os.path.join(STORE, 'qdrant')


def build_qdrant(ids, vectors, meta, say):
    from qdrant_client import QdrantClient, models
    import shutil
    shutil.rmtree(_qdrant_path(), ignore_errors=True)
    os.makedirs(_qdrant_path(), exist_ok=True)
    client = QdrantClient(path=_qdrant_path())
    client.create_collection(
        COLLECTION,
        vectors_config=models.VectorParams(size=vectors.shape[1],
                                           distance=models.Distance.COSINE))
    say('  qdrant 업로드 중 (다른 엔진보다 오래 걸린다)')
    client.upload_collection(collection_name=COLLECTION, vectors=vectors,
                             payload=[{'notice_id': x} for x in ids],
                             ids=list(range(len(ids))), batch_size=512)
    count = client.count(COLLECTION).count
    client.close()
    return count


def open_qdrant():
    from qdrant_client import QdrantClient
    return QdrantClient(path=_qdrant_path())


def search_qdrant(client, qv, top, allow):
    from qdrant_client import models
    flt = None
    if allow is not None:
        flt = models.Filter(must=[models.FieldCondition(
            key='notice_id', match=models.MatchAny(any=list(allow)))])
    hits = client.query_points(COLLECTION, query=qv.tolist(),
                               limit=top, query_filter=flt).points
    return [(h.payload['notice_id'], float(h.score)) for h in hits]


# ── FAISS ─────────────────────────────────────────────────
def _faiss_path():
    return os.path.join(STORE, 'faiss.index')


def build_faiss(ids, vectors, meta, say):
    import faiss
    os.makedirs(STORE, exist_ok=True)
    index = faiss.IndexFlatIP(vectors.shape[1])   # 정규화돼 있으니 내적 = 코사인
    index.add(vectors)
    faiss.write_index(index, _faiss_path())
    with open(_faiss_path() + '.ids', 'w', encoding='utf-8') as f:
        json.dump({'ids': ids, 'meta': meta}, f, ensure_ascii=False)
    return index.ntotal


def open_faiss():
    import faiss
    with open(_faiss_path() + '.ids', encoding='utf-8') as f:
        side = json.load(f)
    return faiss.read_index(_faiss_path()), side['ids']


def search_faiss(handle, qv, top, allow):
    import faiss
    import numpy as np
    index, ids = handle
    params = None
    if allow is not None:
        keep = np.array([i for i, x in enumerate(ids) if x in allow], dtype='int64')
        if not len(keep):
            return []
        params = faiss.SearchParameters(sel=faiss.IDSelectorBatch(keep))
    scores, idx = index.search(qv.reshape(1, -1), top, params=params)
    return [(ids[i], float(s)) for i, s in zip(idx[0], scores[0]) if i >= 0]


# ── numpy (기준선) ─────────────────────────────────────────
def open_numpy():
    ids, vectors, _ = load_vectors()
    return ids, vectors


def search_numpy(handle, qv, top, allow):
    import numpy as np
    ids, vectors = handle
    if allow is None:
        keep = np.arange(len(ids))
    else:
        keep = np.array([i for i, x in enumerate(ids) if x in allow])
        if not len(keep):
            return []
    scores = vectors[keep] @ qv
    order = np.argsort(-scores)[:top]
    return [(ids[keep[i]], float(scores[i])) for i in order]


BACKENDS = {
    'chroma': (build_chroma, open_chroma, search_chroma),
    'qdrant': (build_qdrant, open_qdrant, search_qdrant),
    'faiss': (build_faiss, open_faiss, search_faiss),
    'numpy': (lambda *a: len(a[0]), open_numpy, search_numpy),
}


def sync(changed_ids=None, path=NPZ, say=print):
    """바뀐 벡터만 Chroma 에 밀어 넣는다. 전체를 다시 만들지 않는다.

    `changed_ids` 가 None 이면 벡터 파일과 색인을 대조해 빠진 것을 찾아 넣는다.
    같은 `notice_id` 를 다시 넣으면 건수는 그대로고 벡터만 바뀐다(upsert).
    """
    import numpy as np
    ids, vectors, meta = load_vectors(path)
    index = {nid: i for i, nid in enumerate(ids)}

    try:
        col = open_chroma()
    except Exception:
        say('  색인이 없다. 전체를 새로 만든다.')
        count = build_chroma(ids, vectors, meta, say)
        return {'created': count, 'upserted': count, 'missing': 0}

    if changed_ids is None:
        have = set(col.get(include=[])['ids'])
        changed_ids = [n for n in ids if n not in have]
        if changed_ids:
            say('  색인에 없는 공고 %d건을 찾았다' % len(changed_ids))

    targets = [n for n in changed_ids if n in index]
    for i in range(0, len(targets), 500):
        chunk = targets[i:i + 500]
        col.upsert(ids=chunk,
                   embeddings=[vectors[index[n]].tolist() for n in chunk],
                   metadatas=[{'notice_id': n, 'source': n.split(':')[0]} for n in chunk])

    # 벡터 파일과 색인 건수가 어긋나면 검색에서 조용히 빠진다. 반드시 알린다.
    after = col.count()
    missing = len(ids) - after
    say('  Chroma %d건 넣음 · 색인 %d건 · 벡터 파일 %d건' % (len(targets), after, len(ids)))
    if missing:
        say('  ⚠ 색인에 %d건이 없다. 검색 결과에서 빠진다.' % missing)
    return {'upserted': len(targets), 'indexed': after,
            'vectors': len(ids), 'missing': missing}


def build(engines=ENGINES, path=NPZ, say=print):
    ids, vectors, meta = load_vectors(path)
    result = {}
    for name in engines:
        t0 = time.perf_counter()
        count = BACKENDS[name][0](ids, vectors, meta, say)
        result[name] = {'count': count, 'build_sec': round(time.perf_counter() - t0, 2)}
        say('%s 색인 %d건 · %.2f초' % (name, count, result[name]['build_sec']))
    return result


def handle(engine):
    if engine not in _cache:
        _cache[engine] = BACKENDS[engine][1]()
    return _cache[engine]


def search(text, top=10, allow_ids=None, engine='chroma', qv=None):
    """(결과목록, 소요ms). 결과는 (notice_id, 유사도)."""
    qv = embed_query(text) if qv is None else qv
    allow = None if allow_ids is None else list(allow_ids)
    h = handle(engine)
    t0 = time.perf_counter()
    out = BACKENDS[engine][2](h, qv, top, allow)
    return out, (time.perf_counter() - t0) * 1000


def _count(name, h):
    if name == 'chroma':
        return h.count()
    if name == 'qdrant':
        return h.count(COLLECTION).count
    if name == 'faiss':
        return h[0].ntotal
    return len(h[0])


def stat():
    """색인 상태. **이미 열어둔 손잡이를 재사용한다** —
    Qdrant 로컬 모드는 같은 경로를 두 번 열 수 없다."""
    info = {'store': STORE, 'engines': {}}
    for name in ENGINES:
        try:
            h = handle(name)                     # 캐시된 것이 있으면 그대로 쓴다
            info['engines'][name] = {'count': _count(name, h)}
            if name == 'chroma':
                meta = h.metadata or {}
                if 'embed_meta' in meta:
                    info['embed_meta'] = json.loads(meta['embed_meta'])
        except Exception as exc:
            info['engines'][name] = {'error': type(exc).__name__}
    if 'embed_meta' not in info:
        try:
            info['embed_meta'] = load_vectors()[2]
        except Exception:
            pass
    return info


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('query', nargs='?')
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--stat', action='store_true')
    parser.add_argument('--engine', choices=ENGINES + ('all',), default='chroma')
    parser.add_argument('--top', type=int, default=10)
    args = parser.parse_args()

    if args.build:
        build(ENGINES if args.engine == 'all' else (args.engine,))
        return 0
    if args.stat:
        print(json.dumps(stat(), ensure_ascii=False, indent=1))
        return 0
    if not args.query:
        parser.print_help()
        return 1

    engines = ENGINES if args.engine == 'all' else (args.engine,)
    qv = embed_query(args.query)
    for name in engines:
        hits, ms = search(args.query, top=args.top, engine=name, qv=qv)
        print('\n[%s] %.2fms' % (name, ms))
        for nid, score in hits:
            print('  %.4f  %s' % (score, nid))
    return 0


if __name__ == '__main__':
    sys.exit(main())
