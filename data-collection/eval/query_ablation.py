# -*- coding: utf-8 -*-
"""검색어 구성 비교 — 신청자 입력 일부를 **검색어에서만** 뺐을 때 결과가 어떻게 달라지나. OpenAI 호출 없음.

  python -X utf8 eval/query_ablation.py
  python -X utf8 eval/query_ablation.py --judges human       사람 판정만 정답으로

사용자 요청(2026-09-21): 팀 경력, 수익모델 항목, 채용 계획을 매칭 검색어에서 빼는 게 맞는지 재 본다.
보유 인증·성별은 자격·우대와 관련돼 남긴다(이번 비교 대상이 아니다).

2026-09-21 Codex 리뷰(QUERY_ABLATION_REVIEW_20260921.md) 반영 — 처음 판은 두 가지가 틀렸다.
  · 검색 직후 순위만 쟀다. 사용자가 보는 순위는 서비스 `match()` 가 마감 공고를 숨기고 지역·대상 집단 규칙으로
    다시 정렬한 뒤의 Top N 이다. 그래서 이제 **서비스의 `match()` 를 그대로** 통과시킨다.
  · 입력에서 칸을 지웠다. 팀 경력은 대상 집단 규칙에도 쓰이므로 입력을 지우면 규칙에서도 빠진다.
    이제 입력은 그대로 두고 **검색어 문장만** 바꾼다(`build_query` 만 바꿔 끼운다).

두 순위를 따로 저장한다
  원시 Top 3    검색(의미 검색·하이브리드) 직후. 검색어 자체의 효과를 본다
  최종 Top 3    서비스 match() 결과. **운영 결정은 이것으로 한다**

변형
  전체            지금 서비스 그대로
  -팀경력         검색어에서 팀 경력을 뺀다. 기존 평가셋의 팀 경력 **전체** 제거(35/52 정상 질의에 있음) —
                  평가셋에 대표자 이력과 팀원 이력이 나뉘어 있지 않아 둘을 따로 재지 못한다
  -수익모델       검색어에서 수익모델 항목을 뺀다
  -팀경력-수익모델 둘 다
  +채용계획       (영향 크기만) 모든 질의에 채용 계획을 켠다. 평가 질의에 채용 계획이 있는 신청자가 **0명**이라
                  품질 비교가 아니다

서비스와 다른 점 (결과에 기록한다)
  · 벡터 검색은 Chroma 대신 **같은 벡터 파일**(data/embeddings_v1.npz)을 읽는 대역을 쓴다 — Chroma 원본을 열지 않기 위해서다.
    2026-09-21 정합성 검사에서 벡터 파일과 Chroma 가 같다는 것을 확인했다.
  · '오늘' 은 평가 질의의 기준일(as_of_date)로 고정한다 — 마감 숨김과 '창업 N년차' 가 날마다 바뀌지 않게.
  · 공고 정보·BM25 는 서비스 boot() 와 같은 함수로 DB 에서 SELECT 해 만든다. 모델 워밍업은 하지 않는다.

주의 — 정답(qrels)은 대부분 LLM 잠정 판정(사람 일치율 0.64 < 0.70). 미판정은 0점. 질의 52개. 사람 판정 없음.
"""
import argparse
import hashlib
import io
import json
import os
import sys
from collections import Counter
from contextlib import contextmanager
from datetime import date as real_date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import evaluate as ev  # noqa: E402

REPORTS = os.path.join(common.ROOT, 'reports')
TOP = 3                                   # 서비스 기본 top 과 P@3
RAW_DEPTH = 30

# 검색어에서만 뺄 칸. 입력(req)은 그대로 두고 build_query 에 넘기는 복사본만 바꾼다
QUERY_VARIANTS = {
    '전체': {},
    '-팀경력': {'team': []},
    '-수익모델': {'revenue': []},
    '-팀경력-수익모델': {'team': [], 'revenue': []},
}
# 입력 자체를 바꾸는 탐침 (채용 계획은 검색어에만 쓰인다 — applicant.query_extras)
PROBES = {'+채용계획': {'hiring_plan': True}}


def sha256_file(path):
    h = hashlib.sha256()
    with io.open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


# ─────────────────────────────────────────────────────────── 서비스 대역

class NumpyCollection:
    """서비스 match() 가 부르는 Chroma 메서드(count·query·get)를 벡터 파일로 흉내 낸다.

    Chroma 코사인 거리 = 1 - 내적(정규화 벡터). 결과는 벡터 파일과 Chroma 가 같을 때 서비스와 같다.
    """

    def __init__(self, ids, vectors):
        import numpy as np
        self.ids = list(ids)
        self.vectors = np.asarray(vectors, dtype='float32')
        self.index = {nid: i for i, nid in enumerate(self.ids)}

    def count(self):
        return len(self.ids)

    def query(self, query_embeddings, n_results):
        import numpy as np
        q = np.asarray(query_embeddings[0], dtype='float32')
        sims = self.vectors @ q
        order = np.argsort(-sims, kind='stable')[:n_results]
        return {'ids': [[self.ids[i] for i in order]],
                'distances': [[float(1.0 - sims[i]) for i in order]]}

    def get(self, ids=None, include=None):
        found = [nid for nid in (ids or []) if nid in self.index]
        return {'ids': found, 'embeddings': [self.vectors[self.index[nid]] for nid in found]}


@contextmanager
def pinned_today(as_of):
    """서비스·업력 계산의 '오늘' 을 기준일로 고정한다. 서비스 코드는 고치지 않고 이 호출 동안만 바꾼다."""
    from search import app, gate

    class FixedDate(real_date):
        @classmethod
        def today(cls):
            return as_of

    original_date, original_age = app.date, gate.business_age_months
    app.date = FixedDate
    gate.business_age_months = lambda founded, today=None: original_age(founded, today or as_of)
    try:
        yield
    finally:
        app.date, gate.business_age_months = original_date, original_age


@contextmanager
def query_only(strip):
    """build_query 만 바꿔 끼운다 — 입력(req)의 팀·수익모델은 규칙에 그대로 남는다."""
    from search import app
    original = app.build_query
    app.build_query = lambda req: original(req.model_copy(update=strip)) if strip else original(req)
    try:
        yield
    finally:
        app.build_query = original


class Pipeline:
    """서비스 STATE 를 준비하고 match() 를 부른다. 질의 벡터는 같은 문장이면 다시 만들지 않는다."""

    def __init__(self, collection=None, rows=None, bm25=None, encode=None):
        from search import app
        self.app = app
        self._cache = {}
        app.STATE['collection'] = collection if collection is not None else self._numpy_collection()
        app.STATE['rows'] = rows if rows is not None else self._rows()
        app.STATE['bm25'] = bm25 if bm25 is not None else app._build_bm25()
        self._encode = encode or app._encode
        self.original_encode = app._encode

    @staticmethod
    def _numpy_collection():
        from search import vecstore
        ids, vectors, _meta = vecstore.load_vectors()
        return NumpyCollection(ids, vectors)

    def _rows(self):
        app = self.app
        connection = app._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT ' + ','.join(app.FIELDS) + ' FROM notices')
                return {r[0]: dict(zip(app.FIELDS, r)) for r in cursor.fetchall()}
        finally:
            connection.close()

    def encode(self, text):
        if text not in self._cache:
            self._cache[text] = self._encode(text)
        return self._cache[text]

    def final(self, payload, mode, strip, as_of, top=TOP):
        """서비스 최종 Top N (마감 숨김·규칙 재정렬 포함). (공고 ID 목록, 실제 쓴 검색어)."""
        app = self.app
        req = app.MatchRequest(**dict(payload, top=top, search=mode))
        app._encode, original = self.encode, app._encode
        try:
            with pinned_today(as_of), query_only(strip):
                out = app.match(req)
        finally:
            app._encode = original
        return [r['notice_id'] for r in out['results']], out['query']

    def raw(self, payload, mode, strip, as_of, depth=RAW_DEPTH):
        """검색 직후 순위(마감·규칙 전). 서비스와 같은 벡터·BM25·RRF 설정."""
        app = self.app
        from search import hybrid
        req = app.MatchRequest(**payload)
        with pinned_today(as_of), query_only(strip):
            text = app.build_query(req)
        qv = self.encode(text)
        found = app.STATE['collection'].query(query_embeddings=[qv], n_results=hybrid.DEPTH)
        dense = list(zip(found['ids'][0], found['distances'][0]))
        if mode == 'dense':
            return [nid for nid, _ in dense][:depth], text
        lexical = app.STATE['bm25'].search(text, top=hybrid.DEPTH)
        w = app.Weights()
        fused = hybrid.rrf(dense, lexical, k=w.rrf_k, weights=(w.dense, w.bm25))
        return [nid for nid, _ in fused][:depth], text


# ─────────────────────────────────────────────────────────── 채점

def metrics(ranked, rels):
    top3 = ranked[:3]
    judged = [n for n in top3 if n in rels]
    return {'top3': top3,
            'p3_rec': sum(1 for n in top3 if rels.get(n) == 2) / 3,
            'p3_rel': sum(1 for n in top3 if (rels.get(n) or 0) >= 1) / 3,
            'p3_rec_judged': (sum(1 for n in judged if rels[n] == 2) / len(judged)) if judged else None,
            'ndcg3': ev.ndcg(ranked, rels, 3),
            'unjudged3': sum(1 for n in top3 if n not in rels) / 3,
            'human_judged3': None}


def summarize(per, base=None):
    normal = [r for r in per if r['kind'] == 'normal']

    def mean(key):
        vals = [r[key] for r in normal if r[key] is not None]
        return sum(vals) / len(vals) if vals else None

    out = {'queries': len(normal)}
    for key in ('p3_rec', 'p3_rec_judged', 'p3_rel', 'ndcg3', 'unjudged3'):
        out[key] = mean(key)
    out['human_judged_slots'] = sum(r['human_judged3'] for r in normal)
    out['p3_rec_ci95'] = ev.bootstrap([r['p3_rec'] for r in normal])
    if base is not None:
        b = {r['qid']: r for r in base}
        pairs = [(b[r['qid']], r) for r in normal]
        out['diff_vs_full'] = ev.paired_diff([x['p3_rec'] for x, _ in pairs],
                                             [y['p3_rec'] for _, y in pairs])
        changed = [len(set(x['top3']) - set(y['top3'])) for x, y in pairs]
        out['top3_changed_slots'] = sum(changed)
        out['queries_with_change'] = sum(1 for c in changed if c)
        out['query_text_changed'] = sum(1 for x, y in pairs if x['query'] != y['query'])
    return out


def run_all(queries, qrels, human, pipeline, modes=('dense', 'hybrid')):
    """{(단계, 방식, 변형): (질의별 결과, 요약)}. 단계는 'raw' 와 'final'."""
    results = {}
    variants = [(name, strip, {}) for name, strip in QUERY_VARIANTS.items()] + \
               [(name, {}, change) for name, change in PROBES.items()]
    for stage in ('raw', 'final'):
        for mode in modes:
            base = None
            for name, strip, change in variants:
                per = []
                for qid, q in queries.items():
                    payload = dict(q['payload'], **change)
                    as_of = real_date.fromisoformat(q['as_of_date'])
                    fn = pipeline.final if stage == 'final' else pipeline.raw
                    ranked, text = fn(payload, mode, strip, as_of)
                    rels = qrels.get(qid, {})
                    m = metrics(ranked, rels)
                    m['human_judged3'] = sum(1 for n in m['top3'] if n in human.get(qid, set()))
                    per.append(dict(m, qid=qid, kind=q['kind'], query=text,
                                    has_team=bool(q['payload'].get('team')),
                                    has_revenue=bool(q['payload'].get('revenue'))))
                if name == '전체':
                    base = per
                results[(stage, mode, name)] = (per, summarize(per, None if name == '전체' else base))
    return results


def manifest(queries, used, judges, pipeline, started):
    """다시 돌렸을 때 같은 조건인지 가릴 지문 (Codex 리뷰 P2)."""
    from search import app, hybrid, vecstore
    from shared import embed
    rows = app.STATE['rows']
    sig = '\n'.join('%s|%s' % (nid, rows[nid].get('apply_end')) for nid in sorted(rows))
    w = app.Weights()
    defaults = app.MatchRequest(applicant_type='법인', idea='x')
    return {
        'run_at': started.isoformat(timespec='seconds'),
        'judges': judges, 'qrels_pairs': dict(used),
        'files': {'queries_sha256': sha256_file(common.QUERIES),
                  'qrels_sha256': sha256_file(common.QRELS),
                  'npz_sha256': sha256_file(vecstore.NPZ)},
        'model': {'name': embed.MODEL, 'revision': embed.resolved_revision()},
        'db': {'notices': len(rows), 'rows_sha256': hashlib.sha256(sig.encode('utf-8')).hexdigest(),
               'bm25_docs': len(app.STATE['bm25'])},
        'search': {'vector_engine': 'numpy stand-in for Chroma (data/embeddings_v1.npz)',
                   'candidate_depth': hybrid.DEPTH, 'raw_depth': RAW_DEPTH, 'top_k': TOP,
                   'rrf_k': w.rrf_k, 'rrf_weights': [w.dense, w.bm25], 'rule_mode': w.mode},
        'service_defaults': {'top': defaults.top, 'hide_expired': defaults.hide_expired,
                             'demote_groups': defaults.demote_groups,
                             'demote_region': defaults.demote_region,
                             'demote_district': defaults.demote_district,
                             'search': defaults.search},
        'as_of_dates': sorted({q['as_of_date'] for q in queries.values()}),
        'today_pinned_to_as_of': True,
        'eval_queries': {'total': len(queries),
                         'normal': sum(1 for q in queries.values() if q['kind'] == 'normal'),
                         'with_team': sum(1 for q in queries.values() if q['payload'].get('team')),
                         'with_revenue': sum(1 for q in queries.values() if q['payload'].get('revenue')),
                         'with_hiring_plan': sum(1 for q in queries.values()
                                                 if q['payload'].get('hiring_plan'))},
    }


def write_report(outdir, results, mani):
    os.makedirs(outdir, exist_ok=True)
    table = [dict(stage=stage, mode=mode, variant=name, **s)
             for (stage, mode, name), (_per, s) in results.items()]
    with io.open(os.path.join(outdir, 'summary.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump({'manifest': mani, 'table': table}, f, ensure_ascii=False, indent=1, default=str)
    run_id = mani['run_at']
    with io.open(os.path.join(outdir, 'per_query.jsonl'), 'w', encoding='utf-8', newline='\n') as f:
        for (stage, mode, name), (per, _s) in results.items():
            for r in per:
                f.write(json.dumps(dict(r, run_at=run_id, stage=stage, mode=mode, variant=name),
                                   ensure_ascii=False) + '\n')

    fmt = lambda v: '  -  ' if v is None else '%.3f' % v   # noqa: E731
    lines = ['# 검색어 구성 비교 — %s' % run_id, '',
             '정답 %s (judges=%s) · **LLM 잠정 판정 포함** · 정상 질의 %d개 · 기준일 %s 고정'
             % (mani['qrels_pairs'], mani['judges'], mani['eval_queries']['normal'],
                ', '.join(mani['as_of_dates'])), '',
             '**운영 결정은 "최종 Top 3"(서비스 match() — 마감 숨김·규칙 재정렬 포함) 기준으로 본다.** '
             '입력은 그대로 두고 검색어 문장만 바꿨다(팀 경력은 대상 집단 규칙에 계속 쓰인다).', '']
    for stage, title in (('final', '최종 Top 3 (서비스 match)'), ('raw', '원시 Top 3 (검색 직후)')):
        lines += ['## %s' % title, '',
                  '| 방식 | 변형 | P@3(2) | 판정칸만 | P@3≥1 | nDCG@3 | 미판정@3 | 사람판정 칸 | 전체 대비 P@3(2) (95%) | 바뀐 칸 | 바뀐 질의 |',
                  '|---|---|---|---|---|---|---|---|---|---|---|']
        for row in table:
            if row['stage'] != stage:
                continue
            d = row.get('diff_vs_full')
            lines.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (
                '의미 검색만' if row['mode'] == 'dense' else '하이브리드', row['variant'],
                fmt(row['p3_rec']), fmt(row['p3_rec_judged']), fmt(row['p3_rel']), fmt(row['ndcg3']),
                fmt(row['unjudged3']), row['human_judged_slots'],
                ('%+.3f (%+.3f ~ %+.3f)' % d) if d else '기준',
                row.get('top3_changed_slots', '-'), row.get('queries_with_change', '-')))
        lines.append('')
    lines += ['- 전체 대비 차이의 95% 구간이 0 을 포함하면 **차이가 있다고 말할 수 없다.**',
              '- 미판정은 0점이다. 판정칸만 값과 미판정 비율을 함께 본다. 사람판정 칸은 상위 3 (52질의 × 3 = 156칸) 중 사람이 판정한 칸 수.',
              '- `-팀경력` 은 기존 평가셋의 팀 경력 전체 제거다(대표자 이력과 팀원 이력을 나눠 재지 못했다).',
              '- `+채용계획` 은 채용 계획이 있는 평가 질의가 0개라 품질 비교가 아니다. 켰을 때 상위 결과가 바뀐 정도만 본다.',
              '- 벡터 검색은 Chroma 대신 같은 벡터 파일을 쓰는 대역이다(정합성 검사로 둘이 같음을 확인).', '']
    with io.open(os.path.join(outdir, 'summary.md'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines))
    return '\n'.join(lines)


def load_qrels(judges):
    allowed = ev.JUDGE_LEVELS[judges]
    qrels, human, used = {}, {}, Counter()
    for r in common.read_jsonl(common.QRELS):          # evaluate.py 와 같은 규칙
        if r['judge'] == 'human':
            human.setdefault(r['qid'], set()).add(r['notice_id'])
        if r['judge'] in allowed:
            qrels.setdefault(r['qid'], {})[r['notice_id']] = r['topic_rel']
            used[r['judge']] += 1
    if not used:
        raise SystemExit('qrels.jsonl 이 비었다.')
    return qrels, human, used


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--judges', default='all', choices=list(ev.JUDGE_LEVELS))
    args = ap.parse_args()

    queries = common.load_queries()
    qrels, human, used = load_qrels(args.judges)
    print('질의 %d · 정답 %s (judges=%s)' % (len(queries), dict(used), args.judges))
    started = datetime.now(timezone.utc)
    pipeline = Pipeline()
    results = run_all(queries, qrels, human, pipeline)
    mani = manifest(queries, used, args.judges, pipeline, started)
    outdir = os.path.join(REPORTS, 'query_ablation_' + started.strftime('%Y%m%dT%H%M%SZ'))
    print(write_report(outdir, results, mani))
    print('결과 → %s' % outdir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
