"""더 어려운 시험의 요약표(summary.md)와 시각 리포트(report.html). API 호출 없음. 스타일은 v2 리포트 템플릿과 같다."""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from v1_verifier import score as v1score, variants as jvariants  # noqa: E402
from v6_hard import evaluate as E  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent / 'report_template.html'
V2_TEMPLATE = ROOT / 'v2_coordinator' / 'report_template.html'
LEVELS = [('good', '좋음'), ('medium', '보통'), ('poor', '나쁨')]


def _pct(x):
    return '-' if x is None else '%.0f%%' % (100 * x)


def _f(x, n=1):
    return '-' if x is None else '%.*f' % (n, x)


def evaluate_rows(exp: str, rows: list[dict], cases: dict) -> list[dict]:
    """strategy·writer 행마다 (행, 판정)."""
    fn = E.eval_strategy if exp == 'strategy' else E.eval_writer
    out = []
    for r in rows:
        ev = fn(r['data'], cases[r['case']]) if r.get('ok') else {'valid': False, 'why': r.get('error')}
        out.append((r, ev))
    return out


def rates(exp: str, rows: list[dict], cases: dict) -> dict:
    """{후보: {유형: (성공, 전체)}} 와 후보별 비용·시간."""
    res: dict = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r, ev in evaluate_rows(exp, rows, cases):
        t = cases[r['case']]['type']
        res[r['candidate']][t][1] += 1
        res[r['candidate']][t][0] += 1 if ev.get('valid') and ev.get('success') else 0
    return res


def summarize(exp: str, rows: list[dict], cases: dict) -> str:
    cost = defaultdict(float)
    for r in rows:
        cost[r['candidate']] += r.get('cost') or 0
    if exp == 'gradient':
        g = E.compute_gradient(rows, jvariants.load_rubric())
        L = ['# 검증-1 미묘한 차이 시험 (좋음 / 보통 / 나쁨)', '',
             '같은 계획서를 3단계로 만들어 채점시켰다. 보통은 시장성 출처를 지우고 문제 인식·실현 가능성의 수치를 "상당수"로 흐린 것, 나쁨은 거기에 시장성 부풀림과 팀 소개 뭉뚱그림을 더한 것이다(문장은 모두 멀쩡).',
             '순서 맞힘 = 좋음 > 보통 > 나쁨이고 각 단계가 %.0f점(70점 만점) 이상 벌어진 (계획서, 반복)의 비율.' % E.MARGIN, '',
             '| 후보 | 채점 수 | 순서 맞힘 | 좋음-보통 벌어짐 | 보통-나쁨 벌어짐 | 평균 점수(좋음/보통/나쁨) | 비용($) |', '|---|---:|---:|---:|---:|---|---:|']
        for c, v in g.items():
            L.append('| %s | %d | %s | %s점 (%s) | %s점 (%s) | %s / %s / %s | %.3f |' % (
                c, v['n'], _pct(v['order_ok']), _f(v['gap_gm']), _pct(v['hit_gm']), _f(v['gap_mp']), _pct(v['hit_mp']),
                _f(v['mean']['good']), _f(v['mean']['medium']), _f(v['mean']['poor']), cost[c]))
        return '\n'.join(L) + '\n'
    res = rates(exp, rows, cases)
    types = list(dict.fromkeys(c['type'] for c in cases.values()))
    L = ['# %s (어려운 시험)' % ('전략 T-S2 함정' if exp == 'strategy' else '작성 T-W1 유혹'), '',
         '유형별 성공률(성공 / 전체). 성공 기준은 `v6_hard/evaluate.py` 머리말에 있다.', '',
         '| 후보 | ' + ' | '.join(types) + ' | 전체 | 비용($) |', '|---|' + '---:|' * (len(types) + 2)]
    for c, d in res.items():
        tot = [sum(d[t][0] for t in types), sum(d[t][1] for t in types)]
        L.append('| %s | %s | %s (%s) | %.3f |' % (c, ' | '.join('%d/%d' % tuple(d[t]) for t in types), '%d/%d' % tuple(tot), _pct(tot[0] / tot[1] if tot[1] else None), cost[c]))
    if exp == 'writer':                                    # 상한충돌은 판단이 갈리는 경계 사례가 있어 관대한 기준의 통과 수를 함께 적는다
        cap = defaultdict(lambda: [0, 0, 0])
        for r, ev in evaluate_rows(exp, rows, cases):
            if ev.get('valid') and cases[r['case']]['type'] == '상한충돌':
                cap[r['candidate']][0] += 1 if ev.get('success') else 0
                cap[r['candidate']][1] += 1 if ev.get('lenient') else 0
                cap[r['candidate']][2] += 1
        L += ['', '상한충돌 두 가지 기준: 엄격 = 자금 운용 금액 합계가 상한 이내(공고 규칙 그대로), 관대 = 합이 넘어도 지원금은 상한 이내라고 밝히고 나머지를 자체 자금으로 나눈 경우도 통과.', '',
              '| 후보 | 엄격 | 관대 |', '|---|---:|---:|'] + ['| %s | %d/%d | %d/%d |' % (c, v[0], v[2], v[1], v[2]) for c, v in cap.items()]
    bad = [(r, ev) for r, ev in evaluate_rows(exp, rows, cases) if ev.get('valid') and not ev.get('success')]
    if bad:
        L += ['', '## 실패한 호출', '', '| 후보 | 사례 | 이유 |', '|---|---|---|']
        for r, ev in sorted(bad, key=lambda t: (t[0]['case'], t[0]['candidate']))[:60]:
            L.append('| %s | %s | %s |' % (r['candidate'], r['case'], ev['note']))
    inval = [(r, ev) for r, ev in evaluate_rows(exp, rows, cases) if not ev.get('valid')]
    if inval:
        L += ['', '## 형식 불량·호출 실패', ''] + ['- %s / %s / rep%s: %s' % (r['candidate'], r['case'], r['rep'], ev.get('why')) for r, ev in inval]
    return '\n'.join(L) + '\n'


def build_payload(outdir: Path, exp: str, rows: list[dict], cases: dict) -> dict:
    meta = json.loads((outdir / 'meta.json').read_text(encoding='utf-8')) if (outdir / 'meta.json').exists() else {}
    cand_meta = {c['id']: c for c in meta.get('candidates', [])}
    order = list(dict.fromkeys(r['candidate'] for r in rows))
    cands = []
    for c in order:
        m = cand_meta.get(c, {})
        mode = ('추론 강도 %s' % m['reasoning_effort']) if m.get('reasoning') and m.get('reasoning_effort') else ('온도 %s' % m.get('temperature', 0))
        cands.append({'id': c, 'model': m.get('model', c), 'mode': mode})
    cost = defaultdict(float)
    secs = defaultdict(list)
    for r in rows:
        cost[r['candidate']] += r.get('cost') or 0
        if r.get('ok'):
            secs[r['candidate']].append(r['usage']['ms'] / 1000)
    payload = {'kind': exp, 'label': meta.get('label', exp),
               'run': {'name': outdir.name, 'calls': len(rows), 'total_cost': sum(cost.values()), 'estimated_usd': meta.get('estimated_usd')},
               'candidates': cands, 'cost': dict(cost), 'sec': {c: (sum(v) / len(v) if v else None) for c, v in secs.items()}}
    if exp == 'gradient':
        rub = jvariants.load_rubric()
        payload['items'] = [{'code': it['item_code'], 'name': it['item_name'], 'max': it['max_score']} for it in rub['items']]
        payload['gradient'] = E.compute_gradient(rows, rub)
        payload['margin'] = E.MARGIN
        detail = []
        for r in rows:
            if not r.get('ok'):
                continue
            sc = v1score.item_scores(r['data'], rub)
            if sc is None:
                continue
            plan, level = r['case'].split('|')
            comments = {i['item_code']: i.get('comment', '') for i in r['data']['items']}
            detail.append({'cand': r['candidate'], 'plan': plan, 'level': level, 'rep': r['rep'], 'total': sum(sc.values()), 'items': sc, 'comments': comments})
        payload['detail'] = detail
        payload['plans'] = sorted({c['plan'] for c in cases.values()})
        payload['plan_titles'] = {c['plan']: c['title'] for c in cases.values()}
        return payload
    types = list(dict.fromkeys(c['type'] for c in cases.values()))
    res = rates(exp, rows, cases)
    payload['types'] = types
    payload['rates'] = {c: {t: v for t, v in d.items()} for c, d in res.items()}
    payload['cases'] = [{'id': c['case_id'], 'type': c['type'], 'base': c['base'], 'name': c['item_spec']['item_name']} for c in cases.values()]
    calls = []
    for r, ev in evaluate_rows(exp, rows, cases):
        item = {'cand': r['candidate'], 'case': r['case'], 'rep': r['rep'], 'valid': ev.get('valid', False), 'why': ev.get('why'),
                'success': ev.get('success'), 'note': ev.get('note')}
        if ev.get('valid'):
            d = r['data']
            if exp == 'strategy':
                item['items'] = [dict(i, tag=t) for i, t in zip(d['market_size'], ev['tags'])]
                item['market'] = {k: d[k] for k in ('market_definition', 'positioning')}
            else:
                item['sections'] = [{'code': s['section_code'], 'title': s['title'], 'text': s['text']} for s in d['sections']]
                item['eval'] = ev['eval']
        calls.append(item)
    payload['calls'] = calls
    c0 = next(iter(cases.values()))
    if exp == 'strategy':
        payload['pack'] = {c['case_id']: [{'label': f['label'], 'display': f['display'], 'source': f['source']} for f in c['facts']] for c in cases.values()}
    else:
        payload['asks'] = {c['case_id']: c.get('extra') for c in cases.values()}
    return payload


def build_html(payload: dict) -> str:
    style = re.search(r'<style>(.*?)</style>', V2_TEMPLATE.read_text(encoding='utf-8'), re.S).group(1)
    blob = json.dumps(payload, ensure_ascii=False).replace('</', '<\\/')
    return TEMPLATE.read_text(encoding='utf-8').replace('__STYLE__', style).replace('__DATA__', blob)


def write_report(outdir: Path, exp: str) -> Path:
    from v6_hard import run as v6run
    from v4_writer import score as s4
    rows = s4.load_calls(outdir / 'calls.jsonl')
    path = outdir / 'report.html'
    path.write_text(build_html(build_payload(outdir, exp, rows, v6run.load_cases(exp))), encoding='utf-8')
    return path


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('사용법: python -m v6_hard.report reports/v6_<exp>_…')
    from v6_hard import run as v6run
    out = Path(sys.argv[1])
    exp = json.loads((out / 'meta.json').read_text(encoding='utf-8'))['exp']
    v6run.write_outputs(out, exp)
    print(out / 'report.html')
