"""검증-1 실험 결과를 눈으로 보는 리포트(report.html)로 만든다. 서버·인터넷 없이 브라우저에서 바로 열린다. API 호출 없음.

  python -m v1_verifier.report reports/v1_20260930T120000      # 그 폴더의 calls.jsonl → report.html
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from v1_verifier import score, variants  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent / 'report_template.html'


def candidate_label(c: dict) -> dict:
    mode = ('추론 강도 %s' % c['reasoning_effort']) if c.get('reasoning') else ('온도 %s' % c.get('temperature', 0))
    return {'id': c['id'], 'model': c['model'], 'mode': mode, 'reasoning': bool(c.get('reasoning'))}


def build_payload(outdir: Path) -> dict:
    rubric = variants.load_rubric()
    rows = score.load_calls(outdir / 'calls.jsonl')
    meta_path = outdir / 'meta.json'
    meta = json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.exists() else {}

    plan_ids = sorted({r['plan'] for r in rows})
    var_list, expects, plan_list = [], {}, []
    for pid in plan_ids:
        plan_list.append({'id': pid, 'title': variants.load_plan(pid).get('title', pid)})
        for v in variants.build_variants(variants.load_plan(pid)):
            var_list.append({'plan': pid, 'id': v['variant_id'], 'note': v['note'], 'short': v['short'], 'expect': v['expect_lower']})
            expects[(pid, v['variant_id'])] = v['expect_lower']

    metrics = score.compute(rows, rubric, expects)
    for m in metrics.values():
        m.pop('totals', None)                                  # 튜플 키라 JSON 불가. 화면에서 rows 로 다시 만든다

    cand_meta = {c['id']: c for c in meta.get('candidates', [])}
    order = list(dict.fromkeys(r['candidate'] for r in rows))
    cands = [candidate_label(cand_meta[c]) if c in cand_meta else {'id': c, 'model': c, 'mode': '', 'reasoning': False}
             for c in order]

    slim = []
    for r in rows:
        sc = score.item_scores(r['data'], rubric) if r.get('ok') else None
        detail = {}
        if sc is not None:
            for it in r['data']['items']:
                detail[it['item_code']] = {'score': sc[it['item_code']], 'comment': it.get('comment', ''),
                                           'evidence': it.get('evidence_locator', '')}
        slim.append({'cand': r['candidate'], 'plan': r['plan'], 'variant': r['variant'], 'rep': r['rep'],
                     'ok': bool(r.get('ok')), 'valid': sc is not None, 'total': sum(sc.values()) if sc else None,
                     'scores': detail, 'sec': r['usage']['ms'] / 1000 if r.get('ok') else None,
                     'reasoning': r['usage'].get('reasoning') if r.get('ok') else None,
                     'cost': r.get('cost'), 'error': r.get('error')})
    return {
        'run': {'name': outdir.name, 'started_at': meta.get('started_at', ''), 'prompt_version': meta.get('prompt_version', ''),
                'estimated_usd': meta.get('estimated_usd'), 'reps': meta.get('reps'),
                'total_cost': sum(r.get('cost') or 0 for r in rows), 'calls': len(rows)},
        'items': [{'code': it['item_code'], 'name': it['item_name'], 'max': it['max_score']} for it in rubric['items']],
        'total_max': sum(it['max_score'] for it in rubric['items']),
        'margin_item': score.MARGIN_ITEM, 'margin_total': score.MARGIN_TOTAL,
        'plans': plan_list, 'variants': var_list, 'candidates': cands, 'metrics': metrics, 'rows': slim,
    }


def write_report(outdir: Path) -> Path:
    payload = build_payload(outdir)
    blob = json.dumps(payload, ensure_ascii=False).replace('</', '<\\/')
    html = TEMPLATE.read_text(encoding='utf-8').replace('__DATA__', blob)
    path = outdir / 'report.html'
    path.write_text(html, encoding='utf-8')
    return path


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('사용법: python -m v1_verifier.report reports/v1_…')
    out = Path(sys.argv[1])
    rubric = variants.load_rubric()
    rows = score.load_calls(out / 'calls.jsonl')
    expects = {(p, v['variant_id']): v['expect_lower'] for p in sorted({r['plan'] for r in rows})
               for v in variants.build_variants(variants.load_plan(p))}
    (out / 'summary.md').write_text(score.summarize(rows, rubric, expects), encoding='utf-8')   # 채점 기준이 바뀌었을 때도 표를 다시 만든다
    print(write_report(out))
