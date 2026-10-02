"""조율 T-C1 실험 결과를 눈으로 보는 리포트(report.html)로 만든다. 서버·인터넷 없이 브라우저에서 바로 열린다. API 호출 없음.

  python -m v2_coordinator.report reports/v2_20260930T120000
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from v2_coordinator import score  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent / 'report_template.html'
CASES_PATH = ROOT / 'fixtures' / 'tc1_cases.json'


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
        ev = score.evaluate(r, cases[r['case']])
        d = r.get('data') or {}
        calls.append({
            'cand': r['candidate'], 'case': r['case'], 'rep': r['rep'], 'ok': bool(r.get('ok')), 'valid': ev['valid'],
            'category': ev['category'], 'correct': ev['correct'], 'confidence': ev['confidence'], 'invented': ev['invented'],
            'why': ev['why'], 'item_name': d.get('item_name'), 'summary': d.get('one_line_summary'),
            'target': d.get('target_customer'), 'features': d.get('core_features'), 'keywords': d.get('keywords'),
            'reason': d.get('category_reason'),
        })
    order_cases = sorted(cases.values(), key=lambda c: (['원페이지', '웹개발', 'AI_API'].index(c['expected']),
                                                        ['clear', 'boundary', 'injection'].index(c['kind']), c['case_id']))
    return {
        'run': {'name': outdir.name, 'prompt_version': meta.get('prompt_version', ''), 'reps': meta.get('reps'),
                'estimated_usd': meta.get('estimated_usd'), 'calls': len(rows),
                'total_cost': sum(r.get('cost') or 0 for r in rows)},
        'candidates': cands, 'metrics': score.compute(rows, cases),
        'cases': [{'id': c['case_id'], 'kind': c['kind'], 'expected': c['expected'], 'accept': c['accept'], 'note': c['note'],
                   'idea': c['form']['idea_text']} for c in order_cases],
        'calls': calls,
    }


def write_report(outdir: Path) -> Path:
    from v2_coordinator import run as v2run
    cases = v2run.load_cases()
    rows = v2run.load_rows(outdir)
    blob = json.dumps(build_payload(outdir, cases, rows), ensure_ascii=False).replace('</', '<\\/')
    path = outdir / 'report.html'
    path.write_text(TEMPLATE.read_text(encoding='utf-8').replace('__DATA__', blob), encoding='utf-8')
    return path


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('사용법: python -m v2_coordinator.report reports/v2_…')
    from v2_coordinator import run as v2run
    out = Path(sys.argv[1])
    (out / 'summary.md').write_text(score.summarize(v2run.load_rows(out), v2run.load_cases()), encoding='utf-8')
    print(write_report(out))
