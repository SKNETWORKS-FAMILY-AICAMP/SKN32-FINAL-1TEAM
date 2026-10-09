# -*- coding: utf-8 -*-
"""배치 AI 4단계를 gpt-6-luna 로 바꾸기 전 표본 비교 (2026-10-07, .dryforge spec 2부).

  .\\.venv\\Scripts\\python.exe -X utf8 -m eval.model_switch_compare --plan     부르지 않고 대상·예상 비용만
  .\\.venv\\Scripts\\python.exe -X utf8 -m eval.model_switch_compare           실제 표본 실행

단계마다 지금 공용 DB 에 결과가 있는 공고를 고정 시드로 골라, **같은 문서(같은 길이·같은 지문)** 를 새 모델로 다시 뽑아
지금 결과와 비교한다. 프롬프트·검사 규칙은 그대로이고 모델·생각 강도만 바꾼다.
공용 DB 는 읽기만 한다(SELECT). 결과는 reports/model_switch_6luna_<UTC 시각>Z/ 에만 쓴다.

비교:
  자격요건  지원 금액 상한(버린 값은 '없음'으로), 업력 상한, 사업자 유형, 예비창업자 가능 여부
  신청자 유형  예비창업자·개인사업자·법인 판정 상태
  업종      판정 상태, 허용 업종 대분류
  가점      가점 상태, 항목 수, 서버 규칙(search/bonus.py)을 그대로 통과한 최종 가산점(가상 신청자 4명)
전량 비용: 단계별 대상 수 × 표본의 건당 실제 토큰 × 새 단가. 지금 모델 비용은 DB 에 남은 토큰 기록으로 계산한다.
"""
import argparse
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

NEW_MODEL, NEW_EFFORT = 'gpt-6-luna', 'medium'
SEED = 20261007
SAMPLE = 40
BALANCE_USD = 7.86          # 배치 서버 키 잔액(사용자 기록 기준, 2026-10-06) — 비교용 표시만
APPLICANTS = {
    '속성 없음': {},
    '여성 · 서울': {'gender': '여성', 'region': '서울'},
    '여성기업 · 벤처기업 · 경기 성남시': {'certifications': ['여성기업', '벤처기업'], 'region': '경기', 'district': '성남시'},
    '남성 · 장애인기업 · 이노비즈 · 전남광주': {'gender': '남성', 'certifications': ['장애인기업', '이노비즈'],
                                       'region': '전남광주'},
}


def _cost(tok_in, tok_out, model):
    from experiments.sql_semantic import industry_llm_sample as ils
    price_in, price_out = ils.PRICES[model]
    return tok_in / 1e6 * price_in + tok_out / 1e6 * price_out


def _pick(rows, n, seed=SEED):
    rows = sorted(rows, key=lambda r: r['notice_id'])
    random.Random(seed).shuffle(rows)
    return rows[:n]


def _json(value):
    if isinstance(value, (bytes, str)):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _old_tokens(conn, table, version):
    with conn.cursor() as cur:
        cur.execute('SELECT COUNT(*), SUM(prompt_tokens), SUM(completion_tokens) FROM %s WHERE extractor_version = %%s'
                    % table, (version,))
        n, tin, tout = cur.fetchone()
    return int(n or 0), int(tin or 0), int(tout or 0)


# ── 단계별 표본 준비 ────────────────────────────────────────
def prep_conditions(conn, n):
    from collect import extract_conditions as ec
    with conn.cursor() as cur:
        cur.execute('SELECT notice_id, input_sha256, amount_max_won, amount_rejected, age_years_max, age_rejected, '
                    'business_type, pre_startup_allowed, no_age_limit FROM notice_conditions WHERE extractor_version = %s',
                    (ec.EXTRACTOR_VERSION,))
        cols = [d[0] for d in cur.description]
        old = {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}
    targets = ec.pick_targets(conn, 100000, only_missing_age=False)
    same = []
    for t in targets:
        o = old.get(t['notice_id'])
        if not o:
            continue
        document = ec.build_document(t)
        if ec.doc_hash(document) == o['input_sha256']:
            same.append({'notice_id': t['notice_id'], 'title': t['title'], 'document': document, 'old': o})
    return {'population': len(targets), 'comparable': len(same), 'sample': _pick(same, n)}


def run_conditions(client, it):
    from collect import extract_conditions as ec
    data, usage = ec.ask(client, it['title'], it['document'], NEW_MODEL, NEW_EFFORT)
    data, _ = ec.verify_age(data)
    data, _ = ec.verify_amount(data)
    data = ec.dedupe_types(data)
    return data, usage


def compare_conditions(it, data):
    o = it['old']
    old_amount = None if o['amount_rejected'] else o['amount_max_won']
    new_amount = None if data.get('amount_rejected') else data.get('amount_max_won')
    old_age = None if o['age_rejected'] else o['age_years_max']
    new_age = None if data.get('age_rejected') else data.get('age_years_max')
    old_types = sorted(_json(o['business_type']) or [])
    new_types = sorted(data.get('business_type') or [])
    old_pre = None if o['pre_startup_allowed'] is None else bool(o['pre_startup_allowed'])
    return {
        'amount': {'old': None if old_amount is None else int(old_amount), 'new': new_amount,
                   'same': (old_amount is None and new_amount is None) or (old_amount is not None and new_amount is not None
                                                                          and int(old_amount) == int(new_amount))},
        'age_max': {'old': None if old_age is None else float(old_age), 'new': new_age,
                    'same': (old_age is None and new_age is None) or (old_age is not None and new_age is not None
                                                                     and float(old_age) == float(new_age))},
        'business_type': {'old': old_types, 'new': new_types, 'same': old_types == new_types},
        'pre_startup_allowed': {'old': old_pre, 'new': data.get('pre_startup_allowed'),
                                'same': old_pre == data.get('pre_startup_allowed')},
        'rejected_new': [k for k in ('amount_rejected', 'age_rejected') if data.get(k)],
    }


def prep_applicant(conn, n):
    from experiments.sql_semantic import applicant_type_llm as atl
    with conn.cursor() as cur:
        cur.execute('SELECT notice_id, document_sha256, pre_founder_status, sole_proprietor_status, corporation_status '
                    'FROM notice_applicant_types')
        old = {r[0]: {'sha': r[1], 'pre_founder': r[2], 'sole_proprietor': r[3], 'corporation': r[4]}
               for r in cur.fetchall()}
    population = atl.load_population(conn)
    same = [dict(it, old=old[it['notice_id']]) for it in population
            if it['notice_id'] in old and old[it['notice_id']]['sha'] == it['document_sha256']]
    return {'population': len(population), 'comparable': len(same), 'sample': _pick(same, n)}


def run_applicant(client, it):
    from experiments.sql_semantic import applicant_type_llm as atl
    data, usage = atl.ask(client, it, NEW_MODEL, NEW_EFFORT)
    return atl.verify(data, it['document']), usage


def compare_applicant(it, llm):
    out = {}
    for key in ('pre_founder', 'sole_proprietor', 'corporation'):
        new = ((llm or {}).get(key) or {}).get('status') or 'not_mentioned'
        out[key] = {'old': it['old'][key], 'new': new, 'same': it['old'][key] == new}
    return out


def prep_industry(conn, n):
    from experiments.sql_semantic import industry_llm_sample as ils
    with conn.cursor() as cur:
        cur.execute('SELECT notice_id, document_sha256, status, allowed_sections, allowed, excerpt_chars FROM notice_industries')
        old = {r[0]: {'sha': r[1], 'status': r[2], 'allowed_sections': _json(r[3]), 'allowed': _json(r[4]),
                      'cap': r[5]} for r in cur.fetchall()}
    ids = ils.pick_shared(conn)
    picked = _pick([{'notice_id': nid} for nid in ids if nid in old], n * 2)
    by_cap = {}
    for p in picked:
        by_cap.setdefault(old[p['notice_id']]['cap'] or ils.ec.MAX_CHARS, []).append(p['notice_id'])
    items = []
    for cap, cap_ids in by_cap.items():
        # 기존 결과와 같은 길이로 읽는다(9/28 에 18,000자로 다시 읽은 공고 포함)
        for it in ils.load_items_shared(conn, cap_ids, max_chars=cap):
            if it['document_sha256'] == old[it['notice_id']]['sha']:
                it['old'], it['cap'] = old[it['notice_id']], cap
                items.append(it)
    items = _pick(items, n)
    return {'population': len(ids), 'comparable': f'표본 후보 {len(picked)}건 중 같은 문서 {len(items)}건', 'sample': items}


def run_industry(client, it):
    from experiments.sql_semantic import industry_llm_sample as ils
    data, usage = ils.ask(client, it, 'v3', NEW_MODEL, NEW_EFFORT)
    return ils.verify_for('v3', data, it['document'], 'rough', it['cap'], it.get('title') or ''), usage


def compare_industry(it, llm):
    from experiments.sql_semantic import industry_groups
    status = (llm or {}).get('industry_status') or (llm or {}).get('status') or 'unknown'
    allowed = [a.get('text') for a in (llm or {}).get('allowed') or []]
    found = industry_groups.allowed_sections(allowed) if status == 'known' and allowed else None
    sections = sorted(found) if found else None
    old_sections = sorted(it['old']['allowed_sections']) if it['old']['allowed_sections'] else None
    return {'status': {'old': it['old']['status'], 'new': status, 'same': it['old']['status'] == status},
            'sections': {'old': old_sections, 'new': sections, 'same': old_sections == sections}}


def prep_bonus(conn, n):
    from collect import extract_bonus as eb
    from search import content_version
    versions = content_version.load(conn)
    with conn.cursor() as cur:
        cur.execute('SELECT notice_id, status, document_sha256 FROM notice_bonus WHERE extractor_version = %s',
                    (eb.EXTRACTOR_VERSION,))
        old = {r[0]: {'status': r[1], 'sha': r[2]} for r in cur.fetchall()}
    targets = eb.pick_targets(conn)
    same = []
    for t in targets:
        o = old.get(t['notice_id'])
        if o and eb.doc_hash(eb.build_document(t)) == o['sha']:
            same.append(dict(t, old_status=o['status']))
    # 가점을 찾은 공고가 비교에 의미가 크다 — 찾음 30 + 그 밖 10 (조정 가능)
    found = [s for s in same if s['old_status'] == 'found']
    other = [s for s in same if s['old_status'] != 'found']
    n_found = min(len(found), max(n - 10, 0))
    sample = _pick(found, n_found) + _pick(other, n - n_found)
    return {'population': len(targets), 'comparable': len(same), 'sample': sample, 'versions': versions}


def run_bonus(client, it):
    from collect import extract_bonus as eb
    row = eb.run_one(client, it, NEW_MODEL, NEW_EFFORT)
    return row['result'], row['usage']


def compare_bonus(conn, sample, results, versions):
    from types import SimpleNamespace
    from collect import extract_bonus as eb
    from search import bonus
    ids = {it['notice_id'] for it in sample}
    old_table = {k: v for k, v in bonus.load(conn, versions=versions, extractor_version=eb.EXTRACTOR_VERSION).items()
                 if k in ids}
    new_table = {}
    for it in sample:
        res = results.get(it['notice_id'])
        if res is None:
            continue
        new_table[it['notice_id']] = {'status': res['status'], 'max_total_points': res.get('max_total_points'),
                                      'bonus_info': res.get('bonus_info'), 'items': res.get('items') or [],
                                      'uncertain': res.get('uncertain') or []}
    bonus._check_documents(conn, new_table)
    rows = []
    for it in sample:
        nid = it['notice_id']
        if nid not in new_table:
            continue
        o, nw = old_table.get(nid), new_table[nid]
        scores = {}
        for label, kw in APPLICANTS.items():
            base = {'gender': '', 'certifications': [], 'region': '', 'district': '', 'birth_date': '', 'first_startup': None}
            base.update(kw)
            req = SimpleNamespace(**base)
            so, sn = bonus.score(o, req)[0], bonus.score(nw, req)[0]
            scores[label] = {'old': so, 'new': sn, 'same': so == sn}
        rows.append({'notice_id': nid, 'title': it['title'],
                     'status': {'old': (o or {}).get('status'), 'new': nw['status'], 'same': (o or {}).get('status') == nw['status']},
                     'items': {'old': len((o or {}).get('items') or []), 'new': len(nw['items'])},
                     'scores': scores})
    return rows


# ── 실행 ─────────────────────────────────────────────────
STAGES = {
    'conditions': ('자격요건', prep_conditions, run_conditions, 'notice_conditions', 'collect.extract_conditions', 'gpt-4o-mini'),
    'applicant': ('신청자 유형', prep_applicant, run_applicant, 'notice_applicant_types', None, 'gpt-5.6-luna'),
    'industry': ('업종', prep_industry, run_industry, 'notice_industries', None, 'gpt-5.6-luna'),
    'bonus': ('가점', prep_bonus, run_bonus, 'notice_bonus', 'collect.extract_bonus', 'gpt-5.6-luna'),
}


def _calls(client, fn, sample, workers):
    out, fails = {}, []

    def one(it):
        for attempt in range(2):
            try:
                return it['notice_id'], fn(client, it), None
            except Exception as exc:          # noqa: BLE001 — 실패는 세어서 보고한다
                err = '%s: %s' % (type(exc).__name__, str(exc)[:200])
                time.sleep(2)
        return it['notice_id'], None, err

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for nid, res, err in pool.map(one, sample):
            if err:
                fails.append({'notice_id': nid, 'error': err})
            else:
                out[nid] = res
    return out, fails


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plan', action='store_true', help='부르지 않고 대상·예상 비용만')
    ap.add_argument('--n', type=int, default=SAMPLE, help='단계별 표본 수(기본 %d)' % SAMPLE)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--stages', default='conditions,applicant,industry,bonus')
    args = ap.parse_args(argv)

    from collect import extract_bonus as eb, extract_conditions as ec
    from experiments.sql_semantic import applicant_type_llm as atl
    from shared import config, store_mysql
    versions_now = {'conditions': ec.EXTRACTOR_VERSION, 'applicant': 'applicant_type_llm gpt-5.6-luna@medium',
                    'industry': 'industry_llm v3 gpt-5.6-luna@medium', 'bonus': eb.EXTRACTOR_VERSION}
    stages = [s.strip() for s in args.stages.split(',') if s.strip()]
    conn = store_mysql.connect()
    prepared = {}
    try:
        for key in stages:
            label, prep = STAGES[key][0], STAGES[key][1]
            prepared[key] = prep(conn, args.n)
            p = prepared[key]
            chars = sum(len(it['document']) if 'document' in it else len(eb.build_document(it)) for it in p['sample'])
            guess = _cost(chars / 1.6 + 900 * len(p['sample']), 2500 * len(p['sample']), NEW_MODEL)
            print('%s: 전체 대상 %s · 비교 가능 %s · 표본 %d건 · 예상 약 $%.3f'
                  % (label, p['population'], p['comparable'], len(p['sample']), guess))
        if args.plan:
            return 0

        import openai
        client = openai.OpenAI(api_key=config.require('OPENAI_API_KEY'))
        started = datetime.now(timezone.utc)
        out_dir = os.path.join(ROOT, 'reports', 'model_switch_6luna_%s' % started.strftime('%Y%m%dT%H%M%SZ'))
        os.makedirs(out_dir, exist_ok=True)
        summary = {'run_at': started.isoformat(), 'model': NEW_MODEL, 'effort': NEW_EFFORT, 'seed': SEED,
                   'balance_usd_reference': BALANCE_USD, 'db_writes': 0, 'stages': {}}
        for key in stages:
            label, _prep, run, table, _mod, old_model = STAGES[key]
            p = prepared[key]
            t0 = time.time()
            results, fails = _calls(client, run, p['sample'], args.workers)
            secs = time.time() - t0
            usages = [u for _d, u in results.values()]
            tin = sum(u.get('in') or 0 for u in usages)
            tout = sum(u.get('out') or 0 for u in usages)
            reasoning = sum(u.get('reasoning') or 0 for u in usages if u.get('reasoning'))
            if key == 'bonus':
                rows = compare_bonus(conn, p['sample'], {k: d for k, (d, _u) in results.items()}, p['versions'])
            else:
                cmp_fn = {'conditions': compare_conditions, 'applicant': compare_applicant,
                          'industry': compare_industry}[key]
                rows = [dict(notice_id=it['notice_id'], title=it.get('title'), **cmp_fn(it, results[it['notice_id']][0]))
                        for it in p['sample'] if it['notice_id'] in results]
            n_ok = len(usages)
            old_n, old_in, old_out = _old_tokens(conn, table, versions_now[key])
            per_in = tin / n_ok if n_ok else 0
            per_out = tout / n_ok if n_ok else 0
            population = p['population']
            stage = {
                'label': label, 'old_model': old_model, 'population': population, 'comparable': p['comparable'],
                'sample': len(p['sample']), 'ok': n_ok, 'failed': fails, 'seconds': round(secs, 1),
                'tokens': {'in': tin, 'out': tout, 'reasoning': reasoning,
                           'per_call_in': round(per_in), 'per_call_out': round(per_out)},
                'sample_cost_usd': round(_cost(tin, tout, NEW_MODEL), 4),
                'old_rows': old_n,
                'old_per_call': {'in': round(old_in / old_n) if old_n else None, 'out': round(old_out / old_n) if old_n else None},
                'old_full_cost_usd': round(_cost(old_in, old_out, old_model), 3),
                'new_full_estimate_usd': round(population * _cost(per_in, per_out, NEW_MODEL), 3),
                'rows': rows,
            }
            summary['stages'][key] = stage
            with open(os.path.join(out_dir, '%s.json' % key), 'w', encoding='utf-8') as f:
                json.dump(stage, f, ensure_ascii=False, indent=1, default=str)
            print('%s: 성공 %d · 실패 %d · %.0f초 · 표본 $%.4f' % (label, n_ok, len(fails), secs, stage['sample_cost_usd']))
        summary['sample_cost_usd'] = round(sum(s['sample_cost_usd'] for s in summary['stages'].values()), 4)
        summary['new_full_estimate_usd'] = round(sum(s['new_full_estimate_usd'] for s in summary['stages'].values()), 3)
        with open(os.path.join(out_dir, 'summary.json'), 'w', encoding='utf-8') as f:
            json.dump({k: v for k, v in summary.items() if k != 'stages'} |
                      {'stages': {k: {kk: vv for kk, vv in v.items() if kk != 'rows'} for k, v in summary['stages'].items()}},
                      f, ensure_ascii=False, indent=1, default=str)
        print('→', out_dir)
    finally:
        conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
