# -*- coding: utf-8 -*-
"""BM25 — 오프라인 비교·풀링 전용. 서비스 검색 경로에 넣지 않는다(HANDOFF 2절).

형태소 분석기를 새로 들이지 않고 문자 2-gram 으로 자른다. 한국어는 띄어쓰기와
조사 때문에 어절 단위로 자르면 '스마트공장을' 과 '스마트공장' 이 다른 단어가 된다.
2-gram 이면 둘이 대부분의 토큰을 공유한다. 영문·숫자는 단어 단위로 둔다.
"""
import math
import re
from collections import Counter

_WORD = re.compile(r'[A-Za-z0-9]+|[가-힣]+')


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
