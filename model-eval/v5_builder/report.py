"""구현 T-B1·T-B2 실험 결과를 눈으로 보는 리포트(report.html)로 만든다. 서버·인터넷 없이 브라우저에서 바로 열린다. API 호출 없음.

모델이 만든 HTML·SVG를 리포트 안의 미리보기(갤러리)로 그대로 보여 준다. HTML은 격리된 iframe(sandbox)에서 실행되고 밖으로 나가지 못한다.
  python -m v5_builder.report reports/v5_20260930T120000
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from v5_builder import checks, prompt, score  # noqa: E402

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
        mode = ('추론 강도 %s' % m['reasoning_effort']) if m.get('reasoning') and m.get('reasoning_effort') else ('온도 %s' % m.get('temperature', 0))
        cands.append({'id': c, 'model': m.get('model', c), 'mode': mode, 'api': m.get('api', 'chat')})
    calls = []
    for r in rows:
        case = cases[r['case']]
        ev = score.evaluate(r, case)
        item = {'cand': r['candidate'], 'task': r['task'], 'case': r['case'], 'rep': r['rep'], 'valid': ev['valid'], 'why': ev.get('why'),
                'sec': (r.get('usage') or {}).get('ms', 0) / 1000 if r.get('ok') else None, 'cost': r.get('cost')}
        if ev['valid']:
            item.update(src=ev['src'], code=ev['code'], match=ev['match'], total=ev['total'], checks=ev['checks'], missing=ev['missing'],
                        external=ev['external'], info=ev.get('info', []), chars=ev['chars'])
        calls.append(item)
    return {
        'run': {'name': outdir.name, 'prompt_version': meta.get('prompt_version', ''), 'reps': meta.get('reps'),
                'estimated_usd': meta.get('estimated_usd'), 'calls': len(rows), 'total_cost': sum(r.get('cost') or 0 for r in rows)},
        'candidates': cands, 'metrics': score.compute(rows, cases),
        'html_names': checks.HTML_NAMES, 'svg_names': checks.SVG_NAMES, 'html_weights': checks.HTML_WEIGHTS, 'svg_weights': checks.SVG_WEIGHTS,
        'cases': [{'id': c['case_id'], 'name': c['item_spec']['item_name'], 'summary': c['item_spec']['one_line_summary'],
                   'category': c['item_spec']['category'], 'features': c['item_spec']['core_features']} for c in cases.values()],
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
        raise SystemExit('사용법: python -m v5_builder.report reports/v5_…')
    from v5_builder import run as v5run
    out = Path(sys.argv[1])
    v5run.write_outputs(out)
    print(out / 'report.html')
