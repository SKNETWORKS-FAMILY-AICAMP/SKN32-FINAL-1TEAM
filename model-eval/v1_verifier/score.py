"""검증-1 실험 채점 — calls.jsonl 을 읽어 후보별 지표를 계산한다. API 호출 없음.

총점은 모델이 낸 항목 점수를 코드가 합산한다(항목 상한으로 잘라서). 모델이 말한 총점은 믿지 않는다.
summarize() 는 표(summary.md), report.py 는 시각 리포트(report.html)를 만든다. 둘 다 compute() 의 같은 숫자를 쓴다.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path


def load_calls(path: Path) -> list[dict]:
    """같은 key 가 여러 줄이면(실패 뒤 재개) 마지막 줄만 쓴다."""
    latest: dict[str, dict] = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            row = json.loads(line)
            latest[row['key']] = row
    return list(latest.values())


def item_scores(data: dict, rubric: dict) -> dict[str, float] | None:
    """항목 점수 {코드: 점수}. 항목이 빠졌거나 중복이면 None(형식 불량)."""
    maxes = {it['item_code']: float(it['max_score']) for it in rubric['items']}
    got: dict[str, float] = {}
    for it in data.get('items', []):
        code = it.get('item_code')
        if code not in maxes or code in got:
            return None
        got[code] = min(max(float(it['score']), 0.0), maxes[code])
    return got if set(got) == set(maxes) else None


# '깎였다'로 세는 최소 폭. 반복 오차 수준의 차이(0.8점 등)를 성공으로 세지 않기 위한 값이다(잠정).
MARGIN_ITEM = 0.10     # 항목 만점의 10% 이상 낮아져야 함
MARGIN_TOTAL = 0.05    # 총점 만점의 5% 이상 낮아져야 함


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _fmt(x, nd=1):
    return '-' if x is None else ('%.*f' % (nd, x))


def compute(rows: list[dict], rubric: dict, expects: dict[tuple[str, str], list[str]]) -> dict[str, dict]:
    """후보별 지표. expects[(plan, variant)] = 원본보다 깎여야 할 항목 목록."""
    by_cand: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_cand[r['candidate']].append(r)
    maxes = {it['item_code']: float(it['max_score']) for it in rubric['items']}
    total_max = sum(maxes.values())

    out: dict[str, dict] = {}
    for cand, rs in by_cand.items():
        ok = [r for r in rs if r.get('ok')]
        parsed = []
        for r in ok:
            sc = item_scores(r['data'], rubric)
            if sc is not None:
                parsed.append((r, sc, sum(sc.values())))
        totals = defaultdict(list)       # (plan, variant) -> [총점]
        per_item = defaultdict(list)     # (plan, variant, item) -> [점수]
        for r, sc, total in parsed:
            totals[(r['plan'], r['variant'])].append(total)
            for code, v in sc.items():
                per_item[(r['plan'], r['variant'], code)].append(v)
        plans = sorted({p for p, _ in totals})
        order_hit = order_n = cause_hit = cause_n = 0
        orig_means, jitter, depths = [], [], []
        for p in plans:
            base_total = _mean(totals.get((p, 'original'), []))
            if base_total is not None:
                orig_means.append(base_total)
            for (pp, v), ts in totals.items():
                if pp != p:
                    continue
                if len(ts) > 1:
                    jitter.append(statistics.pstdev(ts))
                if v == 'original' or base_total is None:
                    continue
                order_n += 1
                order_hit += _mean(ts) < base_total - MARGIN_TOTAL * total_max
                for code in expects.get((p, v), []):
                    base_item = _mean(per_item.get((p, 'original', code), []))
                    cur = _mean(per_item.get((p, v, code), []))
                    if base_item is None or cur is None:
                        continue
                    cause_n += 1
                    cause_hit += cur < base_item - MARGIN_ITEM * maxes[code]
                    depths.append((base_item - cur) / maxes[code])
        ms_list = [r['usage']['ms'] for r in ok]
        rt = [r['usage'].get('reasoning') for r in ok if r['usage'].get('reasoning') is not None]
        out[cand] = {
            'calls': len(rs), 'ok': len(ok), 'parsed': len(parsed),
            'orig_mean': _mean(orig_means), 'order_hit': int(order_hit), 'order_n': order_n,
            'cause_hit': int(cause_hit), 'cause_n': cause_n, 'cause_depth': _mean(depths), 'jitter': _mean(jitter),
            'sec': (_mean(ms_list) / 1000) if ms_list else None, 'reasoning': _mean(rt),
            'cost': sum(r.get('cost', 0) or 0 for r in rs), 'totals': dict(totals),
        }
    return out


def summarize(rows: list[dict], rubric: dict, expects: dict[tuple[str, str], list[str]]) -> str:
    metrics = compute(rows, rubric, expects)
    lines = ['# 검증-1 모델 비교 결과', '',
             '- 총점은 항목 점수 합(코드 계산, 만점 %g). 반복은 같은 입력 재호출이다.' % sum(it['max_score'] for it in rubric['items']),
             '- 순서 맞힘: 변형 평균 총점이 원본보다 뚜렷하게(총점 만점의 5% 이상) 낮은 변형의 비율.',
             '- 원인 짚기: 깎여야 할 항목의 평균 점수가 원본보다 뚜렷하게(항목 만점의 10% 이상) 낮아진 (변형, 항목) 비율.',
             '- 깎은 폭: 깎여야 할 항목이 원본보다 항목 만점의 몇 %나 내려갔나(평균, 클수록 정확). 없는 섹션에 점수를 그대로 주면 낮게 나온다.',
             '- 흔들림: 같은 입력 반복 총점의 표준편차 평균(작을수록 안정). 추론 모델은 온도 0을 쓸 수 없다.', '',
             '| 후보 | 호출 | 성공 | 형식 통과 | 원본 평균 | 순서 맞힘 | 원인 짚기 | 깎은 폭 | 흔들림 | 평균 시간(s) | 평균 추론 토큰 | 비용($) |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    details = []
    for cand, m in metrics.items():
        lines.append('| %s | %d | %d | %d | %s | %s | %s | %s | %s | %s | %s | %.3f |' % (
            cand, m['calls'], m['ok'], m['parsed'], _fmt(m['orig_mean']),
            '%d/%d' % (m['order_hit'], m['order_n']) if m['order_n'] else '-',
            '%d/%d' % (m['cause_hit'], m['cause_n']) if m['cause_n'] else '-',
            ('%.0f%%' % (100 * m['cause_depth'])) if m['cause_depth'] is not None else '-',
            _fmt(m['jitter'], 2), _fmt(m['sec'], 1), _fmt(m['reasoning'], 0), m['cost']))
        for (p, v), ts in sorted(m['totals'].items()):
            details.append('| %s | %s | %s | %s | %s |' % (cand, p, v, _fmt(_mean(ts)), ', '.join('%.1f' % t for t in ts)))
    lines += ['', '## 변형별 총점', '', '| 후보 | 계획서 | 변형 | 평균 | 반복별 |', '|---|---|---|---:|---|'] + details
    failed = [r for r in rows if not r.get('ok')]
    if failed:
        lines += ['', '## 실패한 호출', ''] + ['- %s / %s / %s / rep%s: %s' % (
            r['candidate'], r['plan'], r['variant'], r['rep'], r.get('error')) for r in failed]
    return '\n'.join(lines) + '\n'
