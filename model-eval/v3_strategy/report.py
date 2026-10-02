"""전략 T-S1·T-S2 실험 결과를 눈으로 보는 리포트(report.html)로 만든다. 서버·인터넷 없이 브라우저에서 바로 열린다. API 호출 없음.

  python -m v3_strategy.report reports/v3_20260930T120000
스타일은 v2 리포트 템플릿의 <style> 블록을 그대로 가져와 같은 모양을 유지한다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from v3_strategy import prompt, score  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent / 'report_template.html'
V2_TEMPLATE = ROOT / 'v2_coordinator' / 'report_template.html'


def build_payload(outdir: Path, cases: dict[str, dict], rows: list[dict]) -> dict:
    meta_path = outdir / 'meta.json'
    meta = json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.exists() else {}
    cand_meta = {c['id']: c for c in meta.get('candidates', [])}
    order = list(dict.fromkeys(r['candidate'] for r in rows))
    cands = []
    for c in order:
        m = cand_meta.get(c, {})
        mode = ('추론 강도 %s' % m['reasoning_effort']) if m.get('reasoning') else ('온도 %s' % m.get('temperature', 0))
        cands.append({'id': c, 'model': m.get('model', c), 'mode': mode})
    calls = []
    for r in rows:
        case = cases[r['case']]
        ev = score.evaluate(r, case)
        d = r.get('data') or {}
        item = {'cand': r['candidate'], 'task': r['task'], 'case': r['case'], 'cond': r['cond'], 'rep': r['rep'],
                'valid': ev['valid'], 'why': ev.get('why'), 'ev': {k: v for k, v in ev.items() if k not in ('valid', 'why')}}
        if ev['valid'] and r['task'] == 's1':
            core = case['item_spec']['core_features']
            item['features'] = [{'text': f, 'kind': ('exact' if f.strip() in [c.strip() for c in core] else
                                                     'para' if any(score.same_feature(c, f) for c in core) else 'extra')}
                                for f in d['feature_list']]
            item['analysis'] = {k: d[k] for k in ('problem_statement', 'target_customer', 'differentiator', 'use_cases')}
        if ev['valid'] and r['task'] == 's2':
            cls = score.classify_items(d['market_size'], case) if r['cond'] == 'facts' else [{}] * len(d['market_size'])
            item['items'] = [dict(it, **c) for it, c in zip(d['market_size'], cls)]
            item['market'] = {k: d[k] for k in ('market_definition', 'competitors', 'positioning')}
        calls.append(item)
    return {
        'run': {'name': outdir.name, 'prompt_version': meta.get('prompt_version', ''), 'reps': meta.get('reps'),
                'estimated_usd': meta.get('estimated_usd'), 'calls': len(rows),
                'total_cost': sum(r.get('cost') or 0 for r in rows)},
        'candidates': cands, 'metrics': score.compute(rows, cases),
        'cases': [{'id': c['case_id'], 'name': c['item_spec']['item_name'], 'summary': c['item_spec']['one_line_summary'],
                   'core': c['item_spec']['core_features'], 'facts': c['facts'], 'trap': c['trap']} for c in cases.values()],
        'calls': calls,
    }


def build_html(payload: dict) -> str:
    style = re.search(r'<style>(.*?)</style>', V2_TEMPLATE.read_text(encoding='utf-8'), re.S).group(1)
    blob = json.dumps(payload, ensure_ascii=False).replace('</', '<\\/')
    return TEMPLATE.read_text(encoding='utf-8').replace('__STYLE__', style).replace('__DATA__', blob)


def write_report(outdir: Path) -> Path:
    rows = score.load_calls(outdir / 'calls.jsonl')
    path = outdir / 'report.html'
    path.write_text(build_html(build_payload(outdir, prompt.load_cases(), rows)), encoding='utf-8')
    return path


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('사용법: python -m v3_strategy.report reports/v3_…')
    out = Path(sys.argv[1])
    cases = prompt.load_cases()
    (out / 'summary.md').write_text(score.summarize(score.load_calls(out / 'calls.jsonl'), cases), encoding='utf-8')
    print(write_report(out))
