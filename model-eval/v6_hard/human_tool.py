"""사람 채점 도구와 일치도 계산. API 호출 없음.

  python -m v6_hard.human_tool build                    # human/rating_tool.html 과 human/key.json 을 만든다
  python -m v6_hard.human_tool check human/codex_pack/ratings.json              # 채점 파일 형식 검사(정답 열쇠는 안 읽는다)
  python -m v6_hard.human_tool score human/ratings.json reports/v6_gradient_…   # 사람(또는 Codex) 점수와 모델 점수를 비교한다

도구는 계획서 12편(계획서 4편 × 좋음/보통/나쁨)을 섞어 번호(D01~D12)만 보여 준다 — 어느 단계인지 모르는 채로 평가항목별 점수를 매긴다.
채점 기준은 모델이 받은 것과 같은 평가항목·배점(70점 만점)이다. 정답 열쇠(human/key.json)는 채점이 끝나기 전에 열지 않는다.
결과는 브라우저에서 JSON 파일로 내려받는다(서버·업로드 없음, 이 PC에만 저장).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from v1_verifier import variants as jv  # noqa: E402
from v6_hard import cases as C, evaluate as E  # noqa: E402

HUMAN = ROOT / 'human'

PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>사업계획서 사람 채점</title>
<style>
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;--grid:#e1e0d9;--ring:rgba(11,11,11,.10);--accent:#2a78d6;--ok:#0c7a0c}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink-2:#c3c2b7;--grid:#2c2c2a;--ring:rgba(255,255,255,.10);--accent:#3987e5;--ok:#3fbf3f}}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);font:15px/1.6 system-ui,-apple-system,"Segoe UI","Malgun Gothic",sans-serif}
main{max-width:920px;margin:0 auto;padding:22px 16px 64px}h1{font-size:22px;margin:0 0 4px}.sub{color:var(--ink-2);margin:0 0 10px}.note{font-size:13px;color:var(--muted)}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:16px;margin-top:12px}
.bar{height:8px;background:var(--grid);border-radius:4px;overflow:hidden;margin:8px 0}.bar i{display:block;height:100%;background:var(--accent);width:0}
.doc{white-space:pre-wrap;font-size:15px;line-height:1.75}.doc b{display:block;margin-top:10px}
.item{display:grid;grid-template-columns:1fr 110px;gap:4px 12px;align-items:center;padding:8px 0;border-top:1px solid var(--grid)}.item small{color:var(--muted);display:block}
input[type=number]{width:100%;padding:6px 8px;font:inherit;border:1px solid var(--ring);border-radius:8px;background:var(--surface);color:var(--ink)}
button{font:inherit;padding:8px 14px;border-radius:8px;border:1px solid var(--ring);background:var(--surface);color:var(--ink);cursor:pointer}button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.nav{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.pill{padding:2px 10px;border-radius:999px;border:1px solid var(--ring);font-size:13px;cursor:pointer;background:var(--surface)}.pill.done{border-color:var(--ok);color:var(--ok)}.pill.cur{background:var(--ink);color:var(--surface)}
.total{font-size:20px;font-weight:700}
</style></head><body><main>
<h1>사업계획서 사람 채점</h1>
<p class="sub">계획서 __N__편을 읽고 <b>평가항목별 점수</b>를 매겨 주세요. 어떤 계획서가 좋고 나쁜지는 알려 드리지 않습니다. 눈에 보이는 대로 채점하시면 됩니다.</p>
<p class="note">공고(가상): __ANN__ · 점수는 이 브라우저에만 자동 저장됩니다. 다 끝나면 맨 아래에서 결과 파일을 내려받으세요. 약 __MIN__분 걸립니다.</p>
<div class="card"><div class="bar"><i id="prog"></i></div><div id="count" class="note"></div><div class="nav" id="nav"></div></div>
<div class="card"><h2 id="dtitle" style="margin:0 0 8px;font-size:17px"></h2><div class="doc" id="doc"></div></div>
<div class="card"><h3 style="margin:0 0 4px;font-size:15px">평가항목별 점수</h3><div id="items"></div>
<div style="margin-top:10px">합계 <span class="total" id="tot">0</span> / __TOTAL__점</div>
<div class="nav"><button id="prev">이전</button><button class="primary" id="next">다음</button></div></div>
<div class="card"><button class="primary" id="dl">결과 파일 내려받기 (ratings.json)</button> <span class="note" id="dlnote"></span></div>
<script>
const DOCS=__DOCS__, ITEMS=__ITEMS__, KEY='s-brain-human-rating-v1';
let store={}; try{store=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}
let cur=0;
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(store))}catch(e){}};
const done=(id)=>store[id]&&ITEMS.every(it=>store[id][it.code]!==undefined&&store[id][it.code]!=='');
function render(){
  const d=DOCS[cur]; document.getElementById('dtitle').textContent=d.id+' · '+(cur+1)+' / '+DOCS.length;
  document.getElementById('doc').innerHTML=d.text.split('\\n\\n').map(p=>{const i=p.indexOf('\\n');return '<b>'+p.slice(0,i).replace(/</g,'&lt;')+'</b>'+p.slice(i+1).replace(/</g,'&lt;')}).join('\\n');
  document.getElementById('items').innerHTML=ITEMS.map(it=>'<div class="item"><div><b>'+it.name+'</b> <span class="note">(0~'+it.max+'점)</span><small>'+it.description+'</small></div><input type="number" min="0" max="'+it.max+'" step="0.5" data-c="'+it.code+'" value="'+((store[d.id]||{})[it.code]??'')+'" aria-label="'+it.name+' 점수"></div>').join('');
  document.querySelectorAll('#items input').forEach(inp=>inp.addEventListener('input',()=>{const v=inp.value===''?'':Math.max(0,Math.min(+inp.dataset.max||ITEMS.find(x=>x.code===inp.dataset.c).max,+inp.value));(store[d.id]=store[d.id]||{})[inp.dataset.c]=v;save();totals();nav();}));
  totals();nav();
}
function totals(){const d=DOCS[cur];document.getElementById('tot').textContent=ITEMS.reduce((a,it)=>a+(+((store[d.id]||{})[it.code])||0),0).toFixed(1);}
function nav(){
  const n=DOCS.filter(d=>done(d.id)).length;
  document.getElementById('prog').style.width=(100*n/DOCS.length)+'%';document.getElementById('count').textContent='채점 완료 '+n+' / '+DOCS.length;
  document.getElementById('nav').innerHTML=DOCS.map((d,i)=>'<span class="pill'+(done(d.id)?' done':'')+(i===cur?' cur':'')+'" data-i="'+i+'">'+d.id+'</span>').join('');
  document.querySelectorAll('.pill').forEach(p=>p.addEventListener('click',()=>{cur=+p.dataset.i;render();scrollTo(0,0)}));
}
document.getElementById('prev').onclick=()=>{cur=Math.max(0,cur-1);render();scrollTo(0,0)};
document.getElementById('next').onclick=()=>{cur=Math.min(DOCS.length-1,cur+1);render();scrollTo(0,0)};
document.getElementById('dl').onclick=()=>{
  const n=DOCS.filter(d=>done(d.id)).length;
  const out={rated_at:new Date().toISOString(),items:ITEMS.map(i=>i.code),ratings:store};
  const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(out,null,1)],{type:'application/json'}));a.download='ratings.json';a.click();
  document.getElementById('dlnote').textContent=n<DOCS.length?'(아직 '+(DOCS.length-n)+'편이 비어 있습니다 — 그대로 내려받았습니다)':'완료! 파일을 model-eval/human/ratings.json 으로 저장해 주세요.';
};
render();
</script></main></body></html>
"""


def build() -> None:
    HUMAN.mkdir(exist_ok=True)
    docs, key = C.human_set()
    rub = jv.load_rubric()
    items = [{'code': it['item_code'], 'name': it['item_name'], 'max': it['max_score'], 'description': it['description']} for it in rub['items']]
    ann = rub['announcement']
    html = (PAGE.replace('__DOCS__', json.dumps(docs, ensure_ascii=False)).replace('__ITEMS__', json.dumps(items, ensure_ascii=False))
            .replace('__N__', str(len(docs))).replace('__TOTAL__', '%g' % sum(i['max'] for i in items))
            .replace('__ANN__', '%s — %s' % (ann['title'], ann['summary'])).replace('__MIN__', '%d~%d' % (len(docs) * 2, len(docs) * 3)))
    (HUMAN / 'rating_tool.html').write_text(html, encoding='utf-8')
    (HUMAN / 'key.json').write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding='utf-8')
    pack = HUMAN / 'codex_pack'                                              # Codex에게 맡기는 꾸러미: 12편 본문과 평가 기준만(단계·정답 없음)
    pack.mkdir(exist_ok=True)
    (pack / 'docs.jsonl').write_text('\n'.join(json.dumps(d, ensure_ascii=False) for d in docs) + '\n', encoding='utf-8')
    (pack / 'rubric.json').write_text(json.dumps({'announcement': ann, 'total': sum(i['max'] for i in items), 'items': items}, ensure_ascii=False, indent=1), encoding='utf-8')
    (pack / 'meta.json').write_text(json.dumps({'n_docs': len(docs), 'item_codes': [i['code'] for i in items], 'output': 'human/codex_pack/ratings.json', 'step': 0.5}, ensure_ascii=False, indent=1), encoding='utf-8')
    (HUMAN / 'README.md').write_text(
        '# 사람 채점\n\n1. `rating_tool.html`을 브라우저로 열어 12편을 채점한다(약 25~35분). 정답 열쇠 `key.json`은 채점이 끝나기 전에 열지 않는다.\n'
        '2. 맨 아래 버튼으로 `ratings.json`을 내려받아 이 폴더에 둔다.\n'
        '3. `python -m v6_hard.human_tool score human/ratings.json reports/v6_gradient_…` 로 모델 점수와의 일치도를 계산한다.\n\n'
        '## Codex에게 맡기는 경우\n\n'
        '도메인 지식이 부족해 사람이 채점하기 어려우면 `codex_pack/`(12편 본문과 평가 기준만 있음)과 `docs/CODEX_RATING_TASK_20260930.md`를 Codex에게 준다. '
        'Codex는 `codex_pack/ratings.json`을 쓰고 `python -m v6_hard.human_tool check human/codex_pack/ratings.json`으로 형식을 검사한다. '
        '채점이 끝난 뒤 `score human/codex_pack/ratings.json reports/v6_gradient_…`로 비교한다. 결과는 사람 정답이 아니라 AI 참고 점수다.\n', encoding='utf-8')
    print('만들었다:', HUMAN / 'rating_tool.html', '·', len(docs), '편')


def check(path: Path) -> list[str]:
    """채점 파일(사람이든 Codex든)의 형식 검사. 문제 목록을 돌려준다(비어 있으면 통과). 정답 열쇠는 읽지 않는다."""
    pack = json.loads((HUMAN / 'codex_pack' / 'rubric.json').read_text(encoding='utf-8'))
    items = {i['code']: i['max'] for i in pack['items']}
    ids = [json.loads(ln)['id'] for ln in (HUMAN / 'codex_pack' / 'docs.jsonl').read_text(encoding='utf-8').splitlines() if ln.strip()]
    try:
        ratings = json.loads(Path(path).read_text(encoding='utf-8'))['ratings']
    except (OSError, ValueError, KeyError) as e:
        return ['파일을 읽을 수 없거나 "ratings" 키가 없다: %s' % e]
    problems = []
    for d in ids:
        r = ratings.get(d)
        if r is None:
            problems.append('%s: 채점이 없다' % d)
            continue
        for code, mx in items.items():
            v = r.get(code)
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                problems.append('%s %s: 숫자가 아니다(%r)' % (d, code, v))
            elif not 0 <= v <= mx:
                problems.append('%s %s: 범위(0~%g) 밖이다(%g)' % (d, code, mx, v))
            elif (v * 2) % 1:
                problems.append('%s %s: 0.5 단위가 아니다(%g)' % (d, code, v))
    problems += ['%s: 편 번호가 아니다' % d for d in ratings if d not in ids]
    return problems


def spearman(a: list[float], b: list[float]) -> float | None:
    def ranks(x):
        order = sorted(range(len(x)), key=lambda i: x[i])
        r = [0.0] * len(x)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    if len(a) < 3:
        return None
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else None


def compare(ratings: dict, key: dict, rows: list[dict]) -> dict:
    """사람 점수(문서별 합계)와 후보별 모델 점수(문서별 반복 평균)의 순위 상관, 그리고 사람이 좋음>보통>나쁨 순서로 봤는지."""
    rub = jv.load_rubric()
    human = {d: sum(float(v) for v in r.values() if v != '') for d, r in ratings.items() if all(r.get(c) not in (None, '') for c in [i['item_code'] for i in rub['items']])}
    by_case = {v['case_id']: d for d, v in key.items()}
    tot = E.totals_by_level(rows, rub)
    out = {'n_docs': len(human), 'human_ladder': None, 'models': {}}
    lv_scores = {}
    for d, sc in human.items():
        k = key[d]
        lv_scores.setdefault(k['plan'], {})[k['level']] = sc
    full = [p for p, d in lv_scores.items() if len(d) == 3]
    if full:
        out['human_ladder'] = {'plans': len(full), 'gm': sum(1 for p in full if lv_scores[p]['good'] > lv_scores[p]['medium']) / len(full),
                               'mp': sum(1 for p in full if lv_scores[p]['medium'] > lv_scores[p]['poor']) / len(full),
                               'mean': {lv: sum(lv_scores[p][lv] for p in full) / len(full) for lv in ('good', 'medium', 'poor')}}
    cands = sorted({c for (c, _, _) in tot})
    for cand in cands:
        m = {}
        for (c, plan, rep), d in tot.items():
            if c != cand:
                continue
            for lv in ('good', 'medium', 'poor'):
                if lv in d:
                    m.setdefault('%s|%s' % (plan, lv), []).append(d[lv])
        docs = [d for d in human if by_case.get(key[d]['case_id']) and '%s|%s' % (key[d]['plan'], key[d]['level']) in m]
        hs = [human[d] for d in docs]
        ms = [sum(m['%s|%s' % (key[d]['plan'], key[d]['level'])]) / len(m['%s|%s' % (key[d]['plan'], key[d]['level'])]) for d in docs]
        exact = sum(abs(h - x) for h, x in zip(hs, ms)) / len(hs) if hs else None
        out['models'][cand] = {'n': len(docs), 'spearman': spearman(hs, ms), 'mean_abs_diff': exact,
                               'human_mean': sum(hs) / len(hs) if hs else None, 'model_mean': sum(ms) / len(ms) if ms else None}
    return out


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == 'build':
        build()
    elif len(sys.argv) == 3 and sys.argv[1] == 'check':
        problems = check(Path(sys.argv[2]))
        print('\n'.join(problems) if problems else '통과: 12편 × 5항목이 모두 형식에 맞다.')
        raise SystemExit(1 if problems else 0)
    elif len(sys.argv) == 4 and sys.argv[1] == 'score':
        from v4_writer import score as s4
        raw = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
        key = json.loads((HUMAN / 'key.json').read_text(encoding='utf-8'))
        res = compare(raw['ratings'], key, s4.load_calls(Path(sys.argv[3]) / 'calls.jsonl'))
        res = {'rater': raw.get('rater', '사람'), **res}                    # 누가 채점했는지 결과에 남긴다(Codex면 "AI 참고", 사람 정답이 아니다)
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        raise SystemExit(__doc__)
