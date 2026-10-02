"""reports/ 폴더의 실험 결과를 한눈에 보는 목록 페이지(reports/index.html)를 만든다. API 호출 없음.

  python build_index.py
브라우저에서 결과 폴더를 열면(예: 로컬 서버 eval-reports) 기본 파일 목록 대신 이 페이지가 나온다.
각 run.py 는 실제 실행이 끝날 때 이 목록을 자동으로 다시 만든다.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / 'reports'

KINDS = {
    'v1': ('검증-1', '계획서 채점', '망가뜨린 계획서를 알아채는지, 같은 입력에 점수가 흔들리는지'),
    'v2': ('조율 T-C1', '카테고리 판정', '아이템을 원페이지 / 웹개발 / AI API로 맞게 분류하는지'),
    'v3': ('전략 T-S1·T-S2', '요구사항·시장 분석', '기능 목록을 그대로 이어받는지, 시장 수치를 지어내지 않는지'),
    'v4': ('작성 T-W1·T-W2·T-W3', '본문·그래프·표', '규칙을 지키며 쓰는지, 수치를 지어내지 않는지, 글 품질이 어떤지'),
    'v5': ('구현 T-B1·T-B2', 'HTML 프로토타입·SVG 인포그래픽', '접근성 검사를 통과하는지, 기능을 빠뜨리지 않는지, 화면이 어떻게 생겼는지'),
    'v6': ('어려운 시험', '검증-1 3단계 · 전략 함정 · 작성 유혹', '미묘한 품질 차이를 구분하는지, 함정 자료와 규칙을 어기고 싶어지는 요청에 옳게 대응하는지'),
}

PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>모델 비교 실험 결과</title>
<style>
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;--grid:#e1e0d9;--ring:rgba(11,11,11,.10);
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--accent:#2a78d6}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink-2:#c3c2b7;--grid:#2c2c2a;--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--accent:#3987e5}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink-2:#c3c2b7;--grid:#2c2c2a;--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--accent:#3987e5}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI","Malgun Gothic",sans-serif}
main{max-width:980px;margin:0 auto;padding:28px 16px 64px}
.top{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap}
h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:32px 0 2px}.sub{color:var(--ink-2);margin:0 0 12px}.note{font-size:13px;color:var(--muted)}
button.theme{background:var(--surface);color:var(--ink-2);border:1px solid var(--ring);border-radius:8px;padding:6px 12px;cursor:pointer;font:inherit;font-size:13px}
.sum{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0 0}.sum div{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:10px 16px}
.sum b{display:block;font-size:22px}.sum span{font-size:12px;color:var(--ink-2)}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:14px 16px;margin-top:10px;display:grid;grid-template-columns:1fr auto;gap:8px 16px;align-items:center;border-left:4px solid var(--kc)}
.card h3{margin:0;font-size:15px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.card .meta{font-size:13px;color:var(--ink-2);margin-top:2px}
.chip{font-size:12px;padding:0 8px;border:1px solid var(--grid);border-radius:999px;color:var(--ink-2);white-space:nowrap}
.chip.trial{border-style:dashed}
.chips{margin-top:6px;display:flex;gap:4px;flex-wrap:wrap}
.acts{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
a.btn{text-decoration:none;font-size:13px;padding:6px 12px;border-radius:8px;border:1px solid var(--ring);color:var(--ink-2);background:var(--surface)}
a.btn.main{background:var(--accent);color:#fff;border-color:var(--accent)}a.btn:hover{filter:brightness(.95)}a.btn:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.k1{--kc:var(--s1)}.k2{--kc:var(--s2)}.k3{--kc:var(--s3)}.k4{--kc:#eda100}.k5{--kc:#e87ba4}.k6{--kc:#7a5cd6}
@media(max-width:640px){.card{grid-template-columns:1fr}.acts{justify-content:flex-start}}
</style></head><body><main>
<div class="top"><div><h1>모델 비교 실험 결과</h1>
<p class="sub">S-Brain Agent별로 어떤 모델이 맞는지 하나씩 시험한 결과 모음입니다. 카드의 <b>리포트 열기</b>를 누르면 그래프와 표로 볼 수 있습니다.</p></div>
<button class="theme" id="tb" type="button">화면 밝기 바꾸기</button></div>
__SUMMARY__
__SECTIONS__
<p class="note" style="margin-top:32px">이 페이지는 <code>model-eval/build_index.py</code>가 만듭니다. 새 실험이 끝나면 자동으로 다시 만들어집니다.</p>
</main><script>
document.getElementById('tb').addEventListener('click',()=>{const r=document.documentElement;const d=r.dataset.theme?r.dataset.theme==='dark':matchMedia('(prefers-color-scheme: dark)').matches;r.dataset.theme=d?'light':'dark'})
</script></body></html>
"""


def _e(s) -> str:
    return html.escape(str(s))


def describe(folder: Path) -> dict | None:
    calls = folder / 'calls.jsonl'
    if not calls.exists():
        return None
    meta_path = folder / 'meta.json'
    meta = json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.exists() else {}
    n = cost = 0
    ok = 0
    latest = {}
    for line in calls.read_text(encoding='utf-8').splitlines():
        if line.strip():
            r = json.loads(line)
            latest[r['key']] = r
    for r in latest.values():
        n += 1
        ok += 1 if r.get('ok') else 0
        cost += r.get('cost') or 0
    judge_cost = judge_n = 0
    judge_path = folder / 'judge.jsonl'                       # 작성 실험의 글 품질 채점자 호출(별도 파일)
    if judge_path.exists():
        jl = {}
        for line in judge_path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                r = json.loads(line)
                jl[r['key']] = r
        judge_n = len(jl)
        judge_cost = sum(r.get('cost') or 0 for r in jl.values())
    m = re.search(r'(\d{8})T(\d{6})', folder.name)
    stamp = (m.group(1) + 'T' + m.group(2)) if m else ''
    date = '%s-%s-%s %s:%s' % (stamp[0:4], stamp[4:6], stamp[6:8], stamp[9:11], stamp[11:13]) if len(stamp) >= 13 else folder.name
    return {'name': folder.name, 'kind': folder.name.split('_')[0], 'date': date, 'calls': n + judge_n, 'gen_calls': n, 'judge_calls': judge_n, 'ok': ok + judge_n, 'cost': cost + judge_cost, 'judge_cost': judge_cost,
            'cands': [c['id'] for c in meta.get('candidates', [])], 'prompt': meta.get('prompt_version') or meta.get('label', ''),
            'reps': meta.get('reps'), 'trial': 'trial' in folder.name,
            'report': (folder / 'report.html').exists(), 'summary': (folder / 'summary.md').exists()}


def build(reports: Path = REPORTS) -> Path:
    runs = [d for d in (describe(p) for p in sorted(reports.iterdir(), reverse=True) if p.is_dir()) if d]
    total_cost = sum(r['cost'] for r in runs)
    summary = '<div class="sum"><div><b>%d</b><span>실험 실행</span></div><div><b>%d</b><span>API 호출</span></div><div><b>$%.2f</b><span>누적 비용</span></div></div>' % (
        len(runs), sum(r['calls'] for r in runs), total_cost)
    sections = []
    for kind, (title, what, question) in KINDS.items():
        rs = [r for r in runs if r['kind'] == kind]
        if not rs:
            continue
        cards = []
        for r in rs:
            chips = ''.join('<span class="chip">%s</span>' % _e(c) for c in r['cands'])
            tag = '<span class="chip trial">시험 실행</span>' if r['trial'] else ''
            acts = ''
            if r['report']:
                acts += '<a class="btn main" href="%s/report.html">리포트 열기</a>' % _e(r['name'])
            if r['summary']:
                acts += '<a class="btn" href="%s/summary.md">표(md)</a>' % _e(r['name'])
            acts += '<a class="btn" href="%s/calls.jsonl">원본 응답</a>' % _e(r['name'])
            fail = '' if r['ok'] == r['calls'] else ' · <span style="color:#d03b3b">실패 %d</span>' % (r['calls'] - r['ok'])
            cards.append('<div class="card k%s"><div><h3>%s %s</h3><div class="meta">호출 %d건%s · 비용 $%.3f%s%s · %s</div><div class="chips">%s</div></div><div class="acts">%s</div></div>' % (
                kind[1], _e(r['date']), tag, r['calls'], fail, r['cost'],
                (' (채점자 %d건 $%.3f 포함)' % (r['judge_calls'], r['judge_cost'])) if r['judge_calls'] else '',
                (' · 반복 %s회' % r['reps']) if r['reps'] else '', _e(r['prompt']), chips, acts))
        sections.append('<h2>%s · %s</h2><p class="sub">%s</p>%s' % (_e(title), _e(what), _e(question), ''.join(cards)))
    if not sections:
        sections.append('<p class="sub">아직 실행한 실험이 없습니다.</p>')
    out = reports / 'index.html'
    out.write_text(PAGE.replace('__SUMMARY__', summary).replace('__SECTIONS__', ''.join(sections)), encoding='utf-8')
    return out


if __name__ == '__main__':
    print(build())
