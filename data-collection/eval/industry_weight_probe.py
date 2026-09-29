# -*- coding: utf-8 -*-
"""업종(main_industry)을 검색어에서 강조하면 결과가 좋아지나 — 별도 탐침. OpenAI 호출 없음.

  python -X utf8 eval/industry_weight_probe.py

배경 (사용자 요청)

  기존 평가 질의 60개(`eval/queries.jsonl`)에는 `main_industry` 가 채워진 질의가
  하나도 없었다. 그래서 업종 강조 효과를 잴 정답이 아예 없었다. 이번에 업종이
  분명한 질의 6개(q053~q058, 제조업·음식점업·정보통신업·농업·건설업·도소매업)를
  새로 추가하고 LLM 로 주제 관련도 판정을 받았다(2026-09-22, 340호출·약 $0.317).
  **기존 52개 정상 질의는 건드리지 않았다** — 새 6개만 이 탐침의 대상이다.

`eval/query_ablation.py` 의 `Pipeline`·`pinned_today`·`metrics`·`summarize` 를 그대로 가져다 쓴다.
그 파일과 `search/app.py` 는 고치지 않는다 — `app.build_query` 를 실행 중에만 바꿔 끼운다.

변형 (검색어 문장만 바꾼다. 입력 자체는 그대로 둔다)

  그대로       지금 서비스와 완전히 같다 (main_industry 가 있으면 문장 끝에 "업종: X" 한 번)
  업종 없음    "업종: X" 조각을 아예 뺀다 — 업종을 검색어에 쓰는 것 자체가 도움이 되는지
  업종 반복    "업종: X" 를 문장 끝에 한 번 더 추가한다 (임베딩·BM25 양쪽에서 그 단어 비중을 늘리는 값싼 방법)
  업종 앞배치  "업종: X" 를 문장 맨 앞으로 옮긴다 (BM25 는 위치를 안 보지만 그래도 같이 잰다)

정답은 이 6개 질의만 새로 LLM 판정을 받았다. 나머지 qrels 는 그대로다.
LLM 잠정 판정(사람 일치율 기준 미달)이고 질의 6개뿐이라 신뢰구간이 넓다 — 결론은 방향성 참고용이다.
"""
import io
import json
import os
import sys
from contextlib import contextmanager
from datetime import date as real_date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import evaluate as ev  # noqa: E402
from query_ablation import Pipeline, pinned_today, metrics, summarize, load_qrels  # noqa: E402

REPORTS = os.path.join(common.ROOT, 'reports')
TOP = 3
QIDS = ('q053', 'q054', 'q055', 'q056', 'q057', 'q058')


def industry_clause(main_industry):
    main_industry = (main_industry or '').strip()
    return ('업종: ' + main_industry) if main_industry else ''


def make_build_fn(original, mode):
    """app.build_query 대신 쓸 함수. `original` 은 지금 서비스의 build_query (패치 전에 잡아 둔다)."""
    if mode == '그대로':
        return lambda req: original(req)
    if mode == '업종 없음':
        return lambda req: original(req.model_copy(update={'main_industry': ''}))
    if mode == '업종 반복':
        def build(req):
            text = original(req)
            clause = industry_clause(req.main_industry)
            return (text + '. ' + clause) if clause else text
        return build
    if mode == '업종 앞배치':
        def build(req):
            text = original(req.model_copy(update={'main_industry': ''}))
            clause = industry_clause(req.main_industry)
            return (clause + '. ' + text) if clause else text
        return build
    raise ValueError(mode)


@contextmanager
def query_custom(build_fn):
    from search import app
    original = app.build_query
    app.build_query = build_fn
    try:
        yield
    finally:
        app.build_query = original


VARIANTS = ('그대로', '업종 없음', '업종 반복', '업종 앞배치')


def final(pipeline, original_build_query, payload, mode, variant, as_of, top=TOP):
    app = pipeline.app
    req = app.MatchRequest(**dict(payload, top=top, search=mode))
    app._encode, original_encode = pipeline.encode, app._encode
    build_fn = make_build_fn(original_build_query, variant)
    try:
        with pinned_today(as_of), query_custom(build_fn):
            out = app.match(req)
    finally:
        app._encode = original_encode
    return [r['notice_id'] for r in out['results']], out['query']


def run_all(queries, qrels, human, pipeline):
    from search import app
    original_build_query = app.build_query
    results = {}
    for mode in ('dense', 'hybrid'):
        base = None
        for variant in VARIANTS:
            per = []
            for qid in QIDS:
                q = queries[qid]
                as_of = real_date.fromisoformat(q['as_of_date'])
                ranked, text = final(pipeline, original_build_query, q['payload'], mode, variant, as_of)
                rels = qrels.get(qid, {})
                m = metrics(ranked, rels)
                m['human_judged3'] = sum(1 for n in m['top3'] if n in human.get(qid, set()))
                per.append(dict(m, qid=qid, kind=q['kind'], query=text,
                                main_industry=q['payload'].get('main_industry')))
            if variant == '그대로':
                base = per
            results[(mode, variant)] = (per, summarize(per, None if variant == '그대로' else base))
    return results


def write_report(outdir, results, started):
    os.makedirs(outdir, exist_ok=True)
    table = [dict(mode=mode, variant=variant, **s) for (mode, variant), (_per, s) in results.items()]
    with io.open(os.path.join(outdir, 'summary.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump({'run_at': started.isoformat(timespec='seconds'), 'qids': list(QIDS),
                   'table': table}, f, ensure_ascii=False, indent=1, default=str)
    with io.open(os.path.join(outdir, 'per_query.jsonl'), 'w', encoding='utf-8', newline='\n') as f:
        for (mode, variant), (per, _s) in results.items():
            for r in per:
                f.write(json.dumps(dict(r, mode=mode, variant=variant), ensure_ascii=False) + '\n')

    fmt = lambda v: '  -  ' if v is None else '%.3f' % v   # noqa: E731
    lines = ['# 업종 강조 탐침 — %s' % started.isoformat(timespec='seconds'), '',
             '질의 6개(q053~q058, 새로 LLM 판정) · **결론이 아니라 방향성 참고용** (표본 6개, 95% 구간 넓음)', '']
    for mode in ('dense', 'hybrid'):
        lines.append('## %s' % ('의미 검색만' if mode == 'dense' else '하이브리드 (서비스 기본)'))
        lines.append('')
        lines.append('| 변형 | P@3(2) | 95% 구간 | nDCG@3 | 그대로 대비 차이 |')
        lines.append('|---|---|---|---|---|')
        for variant in VARIANTS:
            _per, s = results[(mode, variant)]
            ci = s.get('p3_rec_ci95')
            ci_txt = ('%.3f~%.3f' % tuple(ci)) if ci else '-'
            diff = s.get('diff_vs_full')
            diff_txt = ('%+.3f (95%% %+.3f~%+.3f)' % diff) if diff else '(기준)'
            lines.append('| %s | %s | %s | %s | %s |'
                         % (variant, fmt(s['p3_rec']), ci_txt, fmt(s['ndcg3']), diff_txt))
        lines.append('')
    with io.open(os.path.join(outdir, 'summary.md'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    return lines


def main():
    started = datetime.now(timezone.utc)
    queries = common.load_queries()
    missing = [q for q in QIDS if q not in queries]
    if missing:
        raise SystemExit('질의를 찾을 수 없다: %s' % missing)
    qrels, human, used = load_qrels('all')
    print('질의 %d · 정답 %s (judges=all)' % (len(QIDS), dict(used)))
    pipeline = Pipeline()
    results = run_all(queries, qrels, human, pipeline)
    run_id = started.strftime('%Y%m%dT%H%M%SZ')
    outdir = os.path.join(REPORTS, 'industry_weight_probe_' + run_id)
    lines = write_report(outdir, results, started)
    print('\n'.join(lines))
    print('결과 → %s' % outdir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
