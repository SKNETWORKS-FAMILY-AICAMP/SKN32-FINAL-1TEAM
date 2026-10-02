"""작성 T-W1·T-W2·T-W3 실험 결과를 눈으로 보는 리포트(report.html)로 만든다. 서버·인터넷 없이 브라우저에서 바로 열린다. API 호출 없음.

  python -m v4_writer.report reports/v4_20260930T120000
스타일은 v2 리포트 템플릿의 <style> 블록을 그대로 가져와 같은 모양을 유지한다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from v4_writer import prompt, score  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent / 'report_template.html'
V2_TEMPLATE = ROOT / 'v2_coordinator' / 'report_template.html'


def _w1_detail(data: dict, case: dict) -> list[dict]:
    allowed = score.allowed_values(case)
    mx = case['form']['max_chars_per_section']
    banned = case['form']['format']['banned_expressions']
    out = []
    for s in data['sections']:
        inv, car = score.section_numbers(s['section_code'], s['text'], case, allowed)
        sents = score.sentences(s['text'])
        out.append({'code': s['section_code'], 'title': s['title'], 'text': s['text'], 'chars': len(s['text']),
                    'short': len(s['text']) < score.MIN_CHARS, 'over': bool(mx and len(s['text']) > mx),
                    'banned': [b for b in banned if b in s['text']], 'bad_end': sum(1 for x in sents if score._END_BAD.search(x)),
                    'n_sent': len(sents), 'invented': inv, 'career': car})
    return out


def build_payload(outdir: Path, cases: dict[str, dict], rows: list[dict], judge: dict[str, dict]) -> dict:
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
        item = {'cand': r['candidate'], 'task': r['task'], 'case': r['case'], 'rep': r['rep'], 'valid': ev['valid'], 'why': ev.get('why'),
                'ev': {k: v for k, v in ev.items() if k not in ('valid', 'why')}}
        if ev['valid'] and r['task'] == 'w1':
            item['sections'] = _w1_detail(d, case)
            item['feature_list'] = d['feature_list']
            j = judge.get(r['key'])
            item['judge'] = j
        elif ev['valid'] and r['task'] == 'w2':
            vals = score.chart_values(case)
            item['charts'] = [dict(ch, series=[dict(p, ok=any(score._close(float(p['value']), v) for v in vals)) for p in ch.get('series', [])])
                              for ch in d['charts']]
        elif ev['valid'] and r['task'] == 'w3':
            item['tables'] = d['tables']
        calls.append(item)
    m = score.compute(rows, cases, judge)
    return {
        'run': {'name': outdir.name, 'prompt_version': meta.get('prompt_version', ''), 'judge': meta.get('judge', ''), 'reps': meta.get('reps'),
                'estimated_usd': meta.get('estimated_usd'), 'calls': len(rows), 'total_cost': sum(r.get('cost') or 0 for r in rows)},
        'candidates': cands, 'metrics': m, 'min_chars': score.MIN_CHARS,
        'cases': [{'id': c['case_id'], 'name': c['item_spec']['item_name'], 'summary': c['item_spec']['one_line_summary'],
                   'core': c['item_spec']['core_features'], 'max_chars': c['form']['max_chars_per_section'],
                   'max_amount': c['announcement']['support_amount_max'], 'funds': c['funds']} for c in cases.values()],
        'calls': calls,
    }


def build_html(payload: dict) -> str:
    style = re.search(r'<style>(.*?)</style>', V2_TEMPLATE.read_text(encoding='utf-8'), re.S).group(1)
    blob = json.dumps(payload, ensure_ascii=False).replace('</', '<\\/')
    return TEMPLATE.read_text(encoding='utf-8').replace('__STYLE__', style).replace('__DATA__', blob)


def write_report(outdir: Path) -> Path:
    rows = score.load_calls(outdir / 'calls.jsonl')
    from v1_verifier import variants as jv
    judge = score.judge_scores(score.load_calls(outdir / 'judge.jsonl'), jv.load_rubric())
    path = outdir / 'report.html'
    path.write_text(build_html(build_payload(outdir, prompt.load_cases(), rows, judge)), encoding='utf-8')
    return path


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('사용법: python -m v4_writer.report reports/v4_…')
    from v4_writer import run as v4run
    out = Path(sys.argv[1])
    v4run.write_outputs(out)
    print(out / 'report.html')
