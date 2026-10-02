# -*- coding: utf-8 -*-
"""업종 순위 신호(search/industry_rank.py)가 **잘못된 순서를 만들지 않는지** 실제 데이터로 확인한다. OpenAI 호출 없음.

  python -X utf8 eval/industry_rank_check.py        DB·Chroma 읽기만. 결과는 reports/industry_rank_check_<시각>/

2026-09-28 사용자 요청 "가 방식": 효과(좋아졌나)가 아니라 안전(틀리게 밀지 않나)을 먼저 본다.
평가 질의 66개 중 업종이 들어 있는 질의는 6개뿐이라 효과를 잴 정답이 없다.

방법 (eval/region_eval.py 가 16개 시·도를 모두 넣어 본 것과 같은 방식)
  정상 질의마다 대표 업종 INDUSTRIES 를 하나씩 신청자 주 업종으로 넣고, 업종 규칙을 끈 결과와 켠 결과를 비교한다.
  주 업종은 질의 문장에도 들어가므로("업종: 제조업") 끈 쪽·켠 쪽 모두 같은 문장을 쓴다 — 차이는 순서 규칙뿐이다.

호출은 두 갈래다 (2026-09-28 Codex 통합 검수 P2 — 이전 판은 top=100000 이 검색 깊이까지 바꿔 서비스 조건이 아니었다)
  서비스 조건   top=10 · 서비스 기본 깊이. 상위 10 비교는 **이것만** 쓴다. 응답의 실제 depth 를 기록한다
  전체 후보     top 을 크게 줘 후보를 다 받는다(깊이도 커진다). 불변식 검사에만 쓴다 — 켜고 끈 두 호출의 깊이는 같다

확인하는 것
  불변식 1  (전체 후보) 빠지는 공고가 없다 — 켜고 끈 후보 집합이 같다. 순서만 바뀐다
  불변식 2  (전체 후보) 밀린 공고는 모두 결과 파일에서 "업종 제한 + 목록 완전 + 잘림 없음 + 통합공고 아님"이고
            허용 대분류에 신청자 대분류가 없다. **같은 업종 표로 다시 본 것이라 업종 추출이 맞는지는 증명하지 않는다**
  불변식 3  (서비스 조건) 상위 10 에서 빠진 공고는 모두 업종 규칙에 걸린 공고다
  규모      (서비스 조건) 상위 10 에서 밀려난 공고가 있었던 (질의, 업종) 쌍 수, 상위 10 이 달라진 쌍 수
  눈 검토   밀린 공고별 제목·허용 업종 원문·**원문 근거 문장**·대분류 — 업종 추출의 독립 판정(사람·Codex)에 쓴다
  참고      밀린 공고 중 주제 판정(qrels topic_rel=2)이 있는 것 — "내용은 맞지만 업종이 안 맞는" 공고다.
            topic_rel 은 업종·지역을 무시한 판정이라 이 수가 많다고 규칙이 틀린 것은 아니다
"""
import argparse
import io
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import common  # noqa: E402

# 평가 질의에 실제로 들어 있는 주 업종 6개(eval/queries.jsonl)
INDUSTRIES = ('제조업', '음식점업', '정보통신업', '농업', '건설업', '도소매업')
K = 10


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', help='결과 폴더 (기본 reports/industry_rank_check_<시각>)')
    args = ap.parse_args(argv)

    from search import app, industry_rank
    started = datetime.now(timezone.utc)
    app.boot()
    table = app.STATE['industry']
    if not table['active']:
        raise SystemExit('업종 결과 파일이 없어 규칙이 꺼져 있다: %s' % table['error'])
    rows = app.STATE['rows']

    qrels = defaultdict(dict)
    for r in common.read_jsonl(common.QRELS):
        qrels[r['qid']][r['notice_id']] = r['topic_rel']

    cache, encode = {}, app._encode

    def cached(text):
        if text not in cache:
            cache[text] = encode(text)
        return cache[text]
    app._encode = cached

    queries = [q for q in common.load_queries().values() if q['kind'] == 'normal']
    depth = app._hybrid_depth()
    # 응답은 top 건에서 잘린다. 밀린 공고는 후보 맨 뒤로 가므로 top 이 작으면 응답에서 사라져 "빠진 것"처럼 보인다
    # (2026-09-28 첫 실행 industry_rank_check_20260928T021254Z 의 위반 324건이 이 착오였다). 후보 전체를 받는다
    everything = 100000
    service_depths, full_depths = Counter(), Counter()
    evidence = load_evidence()
    pairs, violations = [], []
    demoted_notices = defaultdict(lambda: {'pairs': 0, 'sections_asked': Counter(), 'rel2': 0})
    for q in queries:
        for ind in INDUSTRIES:
            section = industry_rank.applicant_section(ind)
            base = dict(q['payload'], main_industry=ind)
            # 전체 후보 — 불변식만
            full_off = app.match(app.MatchRequest(**dict(base, top=everything, demote_industry=False)))
            full_on = app.match(app.MatchRequest(**dict(base, top=everything, demote_industry=True)))
            full_depths[full_on['depth']] += 1
            ids_off = [r['notice_id'] for r in full_off['results']]
            ids_on = [r['notice_id'] for r in full_on['results']]
            flagged = {r['notice_id'] for r in full_on['results'] if r['rules'].get('off_industry')}
            if set(ids_off) != set(ids_on):
                violations.append({'qid': q['qid'], 'industry': ind, 'kind': '후보 집합이 달라짐',
                                   'missing': sorted(set(ids_off) - set(ids_on))})
            for nid in flagged:
                info = table['notices'].get(nid)
                if not info or section in info['sections']:
                    violations.append({'qid': q['qid'], 'industry': ind, 'kind': '근거 없는 밀림', 'notice_id': nid})
            # 서비스 조건 — 상위 10 비교
            svc_off = app.match(app.MatchRequest(**dict(base, top=K, demote_industry=False)))
            svc_on = app.match(app.MatchRequest(**dict(base, top=K, demote_industry=True)))
            service_depths[svc_on['depth']] += 1
            top_off = [r['notice_id'] for r in svc_off['results']]
            top_on = [r['notice_id'] for r in svc_on['results']]
            pushed = [n for n in top_off if n not in top_on]
            svc_flagged = {r['notice_id'] for r in svc_on['results'] if r['rules'].get('off_industry')} | flagged
            not_flagged = [n for n in pushed if n not in svc_flagged]
            if not_flagged:
                violations.append({'qid': q['qid'], 'industry': ind, 'kind': '규칙에 안 걸렸는데 상위 10에서 빠짐',
                                   'notice_ids': not_flagged})
            for n in pushed:
                d = demoted_notices[n]
                d['pairs'] += 1
                d['sections_asked'][section] += 1
                d['rel2'] += int(qrels[q['qid']].get(n) == 2)
            pairs.append({'qid': q['qid'], 'industry': ind, 'section': section, 'candidates': len(ids_off),
                          'flagged_in_candidates': len(flagged), 'pushed_from_top10': pushed,
                          'top10_changed': top_off != top_on, 'top10_off': top_off, 'top10_on': top_on,
                          'service_depth': svc_on['depth']})

    out_dir = args.out or os.path.join(ROOT, 'reports', 'industry_rank_check_%s'
                                       % started.strftime('%Y%m%dT%H%M%SZ'))
    os.makedirs(out_dir, exist_ok=False)
    notices = [{'notice_id': n, 'title': (rows.get(n) or {}).get('title') or '',
                'allowed': table['notices'][n]['allowed'] if n in table['notices'] else [],
                'sections': table['notices'][n]['sections'] if n in table['notices'] else [],
                'evidence': evidence.get(n, []),
                'pairs': d['pairs'], 'asked': dict(d['sections_asked']), 'rel2_pairs': d['rel2']}
               for n, d in sorted(demoted_notices.items(), key=lambda x: -x[1]['pairs'])]
    by_ind = {}
    for ind in INDUSTRIES:
        ps = [p for p in pairs if p['industry'] == ind]
        by_ind[ind] = {'section': ps[0]['section'] if ps else None, 'pairs': len(ps),
                       'with_push': sum(1 for p in ps if p['pushed_from_top10']),
                       'top10_changed': sum(1 for p in ps if p['top10_changed']),
                       'pushed_slots': sum(len(p['pushed_from_top10']) for p in ps)}
    meta = {'started_at': started.isoformat(), 'queries': len(queries), 'industries': list(INDUSTRIES), 'k': K,
            'depth': depth, 'service_depths': dict(service_depths), 'full_depths': dict(full_depths), 'industry_source': table['source'], 'rule_notices': len(table['notices']),
            'corpus_notices': len(rows), 'violations': len(violations), 'openai_calls': 0, 'db_writes': 0}
    with io.open(os.path.join(out_dir, 'results.json'), 'w', encoding='utf-8') as f:
        json.dump({'meta': meta, 'by_industry': by_ind, 'violations': violations, 'demoted_notices': notices,
                   'pairs': pairs}, f, ensure_ascii=False, indent=1)
    with io.open(os.path.join(out_dir, 'summary.md'), 'w', encoding='utf-8') as f:
        f.write(render(meta, by_ind, violations, notices))
    print(render(meta, by_ind, violations, notices))
    print('→', out_dir)
    return 0


def load_evidence():
    """업종 결과 파일의 허용값별 원문 근거. {공고 ID: ['값: 근거', ...]}"""
    from search import industry_rank
    out = {}
    path = industry_rank.default_path()
    if not os.path.exists(path):
        return out
    for row in common.read_jsonl(path):
        out[row['notice_id']] = [('%s: %s' % (a.get('text'), a.get('evidence') or '')).strip()
                                 for a in (row.get('llm') or {}).get('allowed') or []]
    return out


def render(meta, by_ind, violations, notices):
    lines = ['# 업종 순위 신호 안전 확인', '',
             '- 정상 질의 %d개 × 대표 업종 %d개. 상위 %d 기준. OpenAI 0 · DB 쓰기 0'
             % (meta['queries'], len(meta['industries']), meta['k']),
             '- 상위 10 비교는 **서비스 조건**(top=%d, 응답 검색 깊이 %s). 불변식 1·2는 전체 후보 호출(응답 깊이 %s)'
             % (meta['k'], meta.get('service_depths'), meta.get('full_depths')),
             '- 불변식 2(근거 없는 밀림)는 순위 규칙과 **같은 업종 표**로 본 것이라 업종 추출이 맞는지는 증명하지 않는다. '
             '아래 밀린 공고의 원문 근거로 독립 판정해야 한다',
             '- 업종 결과 %s: 순위에 쓰는 공고 %d건 / 공고 %d건'
             % (meta['industry_source'], meta['rule_notices'], meta['corpus_notices']),
             '- **불변식 위반 %d건** (공고가 빠짐 · 근거 없는 밀림)' % meta['violations'], '',
             '| 신청자 업종 | 대분류 | 쌍 | 상위 10에서 밀린 쌍 | 상위 10이 바뀐 쌍 | 밀린 칸 |', '|---|---|---:|---:|---:|---:|']
    for ind, s in by_ind.items():
        lines.append('| %s | %s | %d | %d | %d | %d |' % (ind, s['section'], s['pairs'], s['with_push'],
                                                         s['top10_changed'], s['pushed_slots']))
    lines += ['', '## 밀린 공고 (눈 검토용 — 허용 업종 추출이 맞는지 본다)', '',
              '| 공고 | 허용 업종(원문) · 근거 | 대분류 | 밀린 쌍 | 주제 판정 2 |', '|---|---|---|---:|---:|']
    for n in notices:
        ev = '<br>'.join(e.replace('|', '/')[:160] for e in n.get('evidence') or [])
        lines.append('| %s<br>`%s` | %s%s | %s | %d | %d |' % (
            n['title'].replace('|', '/'), n['notice_id'], ', '.join(n['allowed']).replace('|', '/'),
            ('<br><small>%s</small>' % ev) if ev else '', ','.join(n['sections']), n['pairs'], n['rel2_pairs']))
    if violations:
        lines += ['', '## 위반', ''] + ['- %s' % json.dumps(v, ensure_ascii=False) for v in violations[:50]]
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    sys.exit(main())
