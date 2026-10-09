# -*- coding: utf-8 -*-
"""가산점 순위 반영 세기 비교 — 실제 가산점 공고가 검색에 뜨는 사례(Codex 재재검수 §8, 결정 0016). OpenAI 호출·DB 쓰기 없음.

  .\\.venv\\Scripts\\python.exe -X utf8 -m eval.bonus_rank_cases [--boostable reports/bonus_boostable_<시각>Z]

eval/bonus_rank_eval.py 는 9/16 평가 공고라 가산점 공고가 거의 없다. 이 도구는 지금 열린 공고에서 가산점이 관측된 공고
(bonus_boostable 결과)마다, 그 공고에 점수가 나오는 입력 + 아이디어 = 공고 제목인 가상 신청자를 만들어 서비스 match() 를
세기 0 과 0.2 로 부르고, 그 공고와 앞뒤 경쟁 공고의 순위·검색 점수·가산점을 남긴다. 서비스 기본값은 바꾸지 않는다(요청에 세기를 넣음).
가상 신청자: 신청자 유형·설립일은 그 공고의 정형 필터를 통과하는 첫 조합(법인·개인사업자 × 설립 2021-01-01·2025-01-01),
소재지는 공고 지역(전국이면 비움). 세기 0 에서 20위 안에 없으면 "검색에 안 뜸".
아이디어는 세 가지로 잰다: title(공고 제목 그대로 — 그 공고가 거의 1위) · keywords(제목에서 지역·연도·'공고·모집' 같은 말을 뺀
핵심어 — 비슷한 공고들과 점수가 가까운 중간 경우) · topic(공고 분야만 같은 평범한 문장 — 대개 20위 밖).
결과: reports/bonus_rank_cases_<UTC 시각>Z/ (results.json · summary.md)
"""
import glob
import json
import os
import sys
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

WEIGHTS = (0.0, 0.2)
SCENARIOS = ('title', 'keywords', 'topic')
_NOISE = r'\[[^\]]*\]|\([^)]*\)|\d{4}\s*년(?:도)?|\d+\s*차|공고|모집|지원계획|변경|수정|연장|재공고|참여기업|참가기업|참가|사업|안내'
TOP = 20
TYPES = ('법인', '개인사업자')
FOUNDED = ('2021-01-01', '2025-01-01')


def latest_boostable():
    found = sorted(glob.glob(os.path.join(ROOT, 'reports', 'bonus_boostable_*')))
    return found[-1] if found else None


def first_region(value):
    """공고 지역 칸('전북', '경북,대구', '전국') → 가상 신청자 시·도. 전국·없음은 ''."""
    from shared import region as region_mod
    for part in str(value or '').split(','):
        sido = region_mod.canonical(part)
        if sido and sido != region_mod.NATIONWIDE:
            return sido
    return ''


def moves(base, other, focus=None):
    """두 순위 목록(공고 ID) → 자리가 바뀐 공고 [(공고, 예전 순위 또는 None, 새 순위)]. focus 를 주면 그 공고만."""
    out = []
    for i, nid in enumerate(other, 1):
        was = base.index(nid) + 1 if nid in base else None
        if was != i and (focus is None or nid == focus):
            out.append((nid, was, i))
    return out


def keyword_idea(title):
    """제목 핵심어 문장 — 대괄호 지역·괄호·연도·차수·'공고·모집·지원계획' 같은 말을 뺀다."""
    import re
    core = ' '.join(re.sub(_NOISE, ' ', str(title or '')).split())
    return '%s 관련 지원을 알아보는 중소기업입니다' % (core or '중소기업 지원')


def topic_idea(row):
    """공고 분야만 같은 평범한 아이디어 문장 — 분야(category) 칸, 없으면 '창업·경영'."""
    topic = str(row.get('category') or '').split(',')[0].strip() or '창업·경영'
    return '%s 분야 지원사업을 찾고 있는 중소기업입니다' % topic


def pick_applicant(app, gate, nid, row, today):
    """그 공고의 정형 필터를 통과하는 (신청자 유형, 설립일) 첫 조합. 없으면 None."""
    for kind in TYPES:
        for founded in FOUNDED:
            age = gate.applicant_age(kind, founded, today)
            if app.eligible_with_types(nid, row, age, today, True, None)[0]:
                return kind, founded
    return None


def run(boostable_dir=None, say=print):
    from search import app, gate
    started = datetime.now(timezone.utc)
    boostable_dir = boostable_dir or latest_boostable()
    data = json.load(open(os.path.join(boostable_dir, 'results.json'), encoding='utf-8'))
    app.boot()
    today = date.today()
    cases = []
    for n in data['notices']:
        nid = n['notice_id']
        row = app.STATE['rows'].get(nid)
        if row is None:
            cases.append({'notice_id': nid, 'title': n['title'], 'skipped': '공고 서버에 없음'})
            continue
        picked = pick_applicant(app, gate, nid, row, today)
        if picked is None:
            cases.append({'notice_id': nid, 'title': n['title'], 'skipped': '정형 필터를 통과하는 가상 신청자를 못 만듦'})
            continue
        given = n['positive_inputs'][0]['input']
        for scenario in SCENARIOS:
            cases.append(one_case(app, n, nid, row, picked, given, scenario))
    return finish(started, today, boostable_dir, cases, say)


def one_case(app, n, nid, row, picked, given, scenario):
    """한 공고 × 한 아이디어 문장 → 세기별 순위."""
    payload = {'applicant_type': picked[0], 'founded_at': picked[1],
               'idea': {'title': n['title'] or '', 'keywords': keyword_idea(n['title'])}.get(scenario) or topic_idea(row),
               'region': given.get('region') or first_region(row.get('region')), 'district': given.get('district', ''),
               'gender': given.get('gender', ''), 'certifications': given.get('certifications', []),
               'birth_date': given.get('birth_date', ''), 'first_startup': given.get('first_startup')}
    per = {}
    for w in WEIGHTS:
        req = app.MatchRequest(**dict(payload, top=TOP, offset=0, weights={'bonus': w}))
        results = app.match(req)['results'][:TOP]
        per[str(w)] = [{'notice_id': r['notice_id'], 'rank': i, 'rrf_score': r.get('rrf_score'),
                        'bonus_score': r.get('bonus_score'), 'title': r.get('title')}
                       for i, r in enumerate(results, 1)]
    base = [r['notice_id'] for r in per['0.0']]
    boosted = [r['notice_id'] for r in per['0.2']]
    rank0 = base.index(nid) + 1 if nid in base else None
    rank2 = boosted.index(nid) + 1 if nid in boosted else None
    return {'notice_id': nid, 'title': n['title'], 'scenario': scenario, 'idea': payload['idea'],
            'applicant': {k: v for k, v in payload.items() if k != 'idea'},
            'bonus_score': n['positive_inputs'][0]['score'],
            'rank_w0': rank0, 'rank_w02': rank2, 'surfaced': rank0 is not None,
            'moved': [{'notice_id': m[0], 'from': m[1], 'to': m[2]} for m in moves(base, boosted)],
            'results': per}


def finish(started, today, boostable_dir, cases, say):
    out = os.path.join(ROOT, 'reports', 'bonus_rank_cases_' + started.strftime('%Y%m%dT%H%M%SZ'))
    os.makedirs(out)
    meta = {'run_at': started.isoformat(timespec='seconds'), 'today': today.isoformat(), 'boostable': os.path.basename(boostable_dir),
            'weights': WEIGHTS, 'top': TOP, 'search': 'hybrid(서비스 기본)', 'openai_calls': 0, 'db_writes': 0}
    json.dump({'meta': meta, 'cases': cases}, open(os.path.join(out, 'results.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=str)
    md = summary_md(meta, cases)
    open(os.path.join(out, 'summary.md'), 'w', encoding='utf-8').write(md)
    say(md)
    say('결과: ' + out)
    return out


def summary_md(meta, cases):
    lines = ['# 가산점 공고가 검색에 뜨는 사례 — 세기 0 vs 0.2 (%s)' % meta['run_at'], '',
             '- 기준일 %s · 가산점 공고 출처 `%s` · 상위 %d · %s · OpenAI 0 · DB 쓰기 0'
             % (meta['today'], meta['boostable'], meta['top'], meta['search']),
             '- 가상 신청자: 그 공고에 점수가 나오는 입력 + 아이디어 = 공고 제목, 유형·설립일은 정형 필터를 통과하는 첫 조합', '',
             '| 공고 | 아이디어 | 가산점 | 세기 0 순위 | 세기 0.2 순위 | 자리 바뀐 공고 수 | 앞 공고와 검색 점수 차(세기 0) |',
             '|---|---|---|---|---|---|---|']
    for c in cases:
        if c.get('skipped'):
            lines.append('| %s %s | - | - | - | - | - | 건너뜀: %s |' % (c['notice_id'][-6:], c['title'], c['skipped']))
            continue
        gap = '-'
        r0 = c['results']['0.0']
        if c['rank_w0'] and c['rank_w0'] > 1:
            me, prev = r0[c['rank_w0'] - 1]['rrf_score'], r0[c['rank_w0'] - 2]['rrf_score']
            if me and prev:
                gap = '%.1f%%' % ((prev - me) / me * 100)
        lines.append('| %s %s | %s | %s | %s | %s | %d | %s |' % (
            c['notice_id'][-6:], c['title'], '공고 제목' if c.get('scenario') == 'title' else c.get('idea', ''), c['bonus_score'], c['rank_w0'] or '20위 밖(검색에 안 뜸)',
            c['rank_w02'] or '20위 밖', len(c['moved']), gap))
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='가산점 공고 사례별 세기 0 vs 0.2 순위(공용 DB SELECT 만)')
    ap.add_argument('--boostable', help='bonus_boostable 결과 폴더(기본: 가장 최근)')
    run(ap.parse_args().boostable)
