# -*- coding: utf-8 -*-
"""메모리 벡터 묶음 — 공용 DB 의 공고 벡터를 메모리에 올려 의미 검색을 직접 계산한다 (2026-10-07).

2026-10-06 결정(벡터 DB 미사용, 결과서 제출)에 따라 공고 서버의 의미 검색은 Chroma 를 열지 않는다.
공고 2,800건 안팎 × 1,024차원 float32 는 약 11MB 라 모두 메모리에 두고 하나하나 비교해도 빠르다
(10/6 실측: 메모리 0.77ms vs Chroma 3.41ms, Chroma 는 근사 검색이라 순서가 조금씩 달랐다).

  from search import memvec
  col, info = memvec.load(connection)      # 공용 DB notices.embedding → MemoryCollection
  col.query(query_embeddings=[q], ids=[...], n_results=50)

MemoryCollection 은 app.match() 가 쓰던 Chroma 의 세 가지 동작(count · query · get)을 같은 모양으로 준다.
그래서 평가 도구가 이 묶음을 감싸 쓰는 방식(eval/filter_first_eval.CorpusCollection 등)도 그대로 돈다.

거리 = 1 - 내적. 벡터가 정규화돼 있어 코사인 거리와 같다. 가까운 순, 같은 거리면 공고 ID 순(Chroma 와 달리 근사 없음).
읽기 전용이다. DB 에 쓰지 않는다.
"""
DIM = 1024
NBYTES = DIM * 4          # float32 리틀엔디안


class MemoryCollection:
    """공고 ID 목록과 (N, DIM) 벡터 행렬. 행 i 가 ids[i] 의 벡터다."""

    def __init__(self, ids, vectors):
        import numpy as np
        self.ids = list(ids)
        self.vectors = np.asarray(vectors, dtype='float32').reshape(len(self.ids), -1) if self.ids \
            else np.zeros((0, DIM), dtype='float32')
        self.index = {nid: i for i, nid in enumerate(self.ids)}

    def count(self):
        return len(self.ids)

    def query(self, query_embeddings, n_results=10, ids=None):
        """ids(없으면 전부) 안에서 질의와 가까운 n_results 건. Chroma 와 같은 {'ids': [[…]], 'distances': [[…]]}.

        ids 에 묶음에 없는 공고가 섞여 있으면 조용히 뺀다(Chroma 는 오류를 내므로 부르는 쪽이 미리 걸렀다).
        """
        import numpy as np
        if ids is None:
            rows = list(range(len(self.ids)))
        else:
            rows = [self.index[nid] for nid in ids if nid in self.index]
        if not rows or n_results <= 0:
            return {'ids': [[]], 'distances': [[]]}
        q = np.asarray(query_embeddings[0], dtype='float32')
        sims = self.vectors[rows] @ q
        # 가까운 순(유사도 큰 순), 같으면 공고 ID 순 — 실행할 때마다 같은 순서
        order = sorted(range(len(rows)), key=lambda k: (-float(sims[k]), self.ids[rows[k]]))[:n_results]
        return {'ids': [[self.ids[rows[k]] for k in order]],
                'distances': [[1.0 - float(sims[k]) for k in order]]}

    def get(self, ids=None, include=None):
        """{'ids': […], 'embeddings': […]} — ids 가 없으면 전체 ID. 없는 공고는 뺀다."""
        found = list(self.ids) if ids is None else [nid for nid in ids if nid in self.index]
        out = {'ids': found}
        if include and 'embeddings' in include:
            out['embeddings'] = [self.vectors[self.index[nid]] for nid in found]
        return out


def rows_to_collection(rows):
    """[(notice_id, embedding bytes, embedding_dim, fingerprint)] → (MemoryCollection, info).

    차원이 DIM 이 아니거나 바이트 길이가 NBYTES 가 아닌 행은 버린다. info 에 건수와 지문별 건수를 담는다.
    """
    import numpy as np
    ids, vectors, fingerprints, dropped = [], [], {}, 0
    for nid, blob, dim, fp in rows:
        if blob is None:
            continue
        if isinstance(blob, memoryview):
            blob = blob.tobytes()
        if dim is not None and int(dim) != DIM or len(blob) != NBYTES:
            dropped += 1
            continue
        ids.append(nid)
        vectors.append(np.frombuffer(blob, dtype='<f4'))
        fingerprints[fp] = fingerprints.get(fp, 0) + 1
    col = MemoryCollection(ids, np.vstack(vectors) if vectors else np.zeros((0, DIM), dtype='float32'))
    return col, {'count': len(ids), 'dropped': dropped, 'fingerprints': fingerprints}


def load(connection):
    """공용 DB notices 의 벡터 → (MemoryCollection, info). SELECT 만 한다."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT notice_id, embedding, embedding_dim, embedding_fingerprint FROM notices '
                       'WHERE embedding IS NOT NULL')
        rows = cursor.fetchall()
    return rows_to_collection(rows)


def fingerprint_warning(info, current):
    """벡터 설정 지문이 질의 인코더 지문과 다르면 경고 문장, 아니면 None. current·벡터 지문 정보가 없으면 None."""
    fps = info.get('fingerprints') or {}
    if not current or not fps:            # 지문을 계산하지 못했거나 벡터 쪽 지문 정보가 없으면 판단하지 않는다
        return None
    others = {fp: n for fp, n in fps.items() if fp != current}
    if not fps.get(current):
        return '공고 벡터에 지금 질의 인코더 설정 지문(%s)이 없다 — 벡터 지문 %s' % (current, others)
    if others:
        return '공고 벡터 중 %d건이 다른 설정 지문이다(%s) — 지금 지문 %s' % (sum(others.values()), others, current)
    return None
