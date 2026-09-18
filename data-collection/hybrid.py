# -*- coding: utf-8 -*-
"""하이브리드 검색 부품 — BM25(단어 검색)와 RRF(순위 합치기).

서비스(app.py)와 평가(eval/evaluate.py)가 **이 파일 하나를** 같이 쓴다.
평가에서 잰 숫자가 서비스 동작과 어긋나지 않게 하기 위해서다.

  의미 검색   BGE-M3 → Chroma          뜻이 비슷한 공고 ("불량 검출" ↔ "품질 검사")
  단어 검색   BM25 (이 파일)            같은 단어가 들어간 공고 (사업명·지역명·고유명사)
  합치기      RRF (이 파일)             점수 단위가 달라 점수 대신 순위로 합친다

2026-09-17 평가 (정상 52질의, LLM 잠정 판정)
  P@3(2) dense 0.500 → rrf 0.641, 짝지은 차이 +0.141 (95% 구간 +0.045 ~ +0.237)

BM25 는 형태소 분석기를 새로 들이지 않고 문자 2-gram 으로 자른다. 한국어는 띄어쓰기와
조사 때문에 어절 단위로 자르면 '스마트공장을' 과 '스마트공장' 이 다른 단어가 된다.
2-gram 이면 둘이 대부분의 토큰을 공유한다. 영문·숫자는 단어 단위로 둔다.
"""
import math
import re
from collections import Counter

_WORD = re.compile(r'[A-Za-z0-9]+|[가-힣]+')

# RRF 상수. 널리 쓰는 기본값이며 평가도 이 값으로 했다
RRF_K = 60
# 각 검색에서 합치기 전에 가져올 후보 수. 평가와 같은 값
DEPTH = 50


def tokenize(text):
    out = []
    for w in _WORD.findall((text or '').lower()):
        if w[0].isascii():
            out.append(w)
        elif len(w) == 1:
            out.append(w)
        else:
            out.extend(w[i:i + 2] for i in range(len(w) - 1))
    return out


class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        """docs: [(doc_id, text)]"""
        self.k1, self.b = k1, b
        self.ids = [d for d, _ in docs]
        self.tfs = [Counter(tokenize(t)) for _, t in docs]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avg = sum(self.lens) / max(len(self.lens), 1)
        df = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def __len__(self):
        return len(self.ids)

    def search(self, query, top=10):
        q = Counter(tokenize(query))
        scores = []
        for i, tf in enumerate(self.tfs):
            s = 0.0
            norm = self.k1 * (1 - self.b + self.b * self.lens[i] / self.avg)
            for term in q:
                f = tf.get(term)
                if f:
                    s += self.idf[term] * f * (self.k1 + 1) / (f + norm)
            if s > 0:
                scores.append((s, self.ids[i]))
        scores.sort(key=lambda x: (-x[0], x[1]))
        return [(nid, s) for s, nid in scores[:top]]


def rrf(*ranked_lists, k=RRF_K):
    """여러 검색 결과 [(id, score)] 를 순위로 합친다 → [(id, rrf점수)] 높은 순.

    심사위원 여럿의 순위표를 합치는 것과 같다. 한 목록에서만 1위인 공고보다
    두 목록 모두에서 상위권인 공고가 위로 온다. 동점은 id 순으로 고정한다.
    """
    fused = {}
    for hits in ranked_lists:
        for rank, (nid, _) in enumerate(hits, 1):
            fused[nid] = fused.get(nid, 0) + 1 / (k + rank)
    return sorted(fused.items(), key=lambda x: (-x[1], x[0]))
