# -*- coding: utf-8 -*-
"""공고의 신청자 유형(예비창업자·개인사업자·법인)을 LLM 으로 뽑는다 — 표본 60건. **DB 에 쓰지 않는다.**

  python -X utf8 -m experiments.sql_semantic.applicant_type_llm --plan      문서·예상 비용만 (호출 없음)
  python -X utf8 -m experiments.sql_semantic.applicant_type_llm             60건 실제 호출 (gpt-5.6-luna@medium)
  python -X utf8 -m experiments.sql_semantic.applicant_type_llm --all      출처 DB 공고 전부(2026-09-28 사용자 승인, 약 $2)
  python -X utf8 -m experiments.sql_semantic.applicant_type_llm --resume reports/applicant_type_llm_<시각>          표본 이어 하기
  python -X utf8 -m experiments.sql_semantic.applicant_type_llm --all --resume reports/applicant_type_llm_full_<시각> 전량 이어 하기

  재개할 때는 처음 실행과 같은 모드(--all 여부)와 같은 대상 공고여야 한다. 폴더의 run_spec.json(없으면 meta.json,
  둘 다 없으면 폴더 이름의 full_)과 대조해 다르면 **결과를 쓰기 전에** 멈춘다(2026-09-28 Codex 통합 검수 P1).

배경 (2026-09-28 사용자 요청 — 기획서 대조 G, "업종 때 방식으로 가져올 수 있나")

  · 게이트(search/gate.py)는 K-Startup API 업력 칸(biz_enyy)으로만 예비창업자 여부를 본다. 기업마당 2,041건은 판정 못 한다.
  · 매일 배치의 조건 추출기(collect/extract_conditions.py, gpt-4o-mini)가 notice_conditions.business_type ·
    pre_startup_allowed 를 이미 채우지만, 근거가 공고당 한 문장(대개 지원 금액 문장)이라 확인할 수 없고
    표본에서 오판이 보였다("중소 제조기업" → 법인만, "법인사업자이어야 함" → 예비창업자 가능). 게이트도 이 값을 쓰지 않는다.
  · 그래서 업종(industry_llm_sample v3)처럼 **유형마다 원문 근거**를 받고 코드로 검사한다. 이 표본은 기존 값과도 나란히 본다.

판정 (유형마다)
  allowed          그 유형이 신청할 수 있다고 적혀 있다("예비창업자 및 창업 7년 이내 기업", "개인·법인사업자")
  not_allowed      명시적으로 안 된다("법인사업자에 한함" → 개인·예비 불가, "사업자등록 필수" → 예비 불가, "개인사업자 제외")
  implied_no       (예비창업자만) 대상이 이미 사업을 하는 기업·업체·사업장으로만 적혀 있어 예비창업자는 해당하지 않아 보인다.
                   명시가 아니라 **추정**이다 — 게이트에서 탈락 근거로 쓰지 않는다. 순위·확인 필요 표시에 쓸지는 나중에 정한다
  not_mentioned    판단할 문장이 없다

코드 검사 (하나라도 걸리면 not_mentioned 로 내리고 이유를 남긴다)
  · 근거가 원문에 없다(느슨한 대조 industry_llm_sample.loose_found)
  · 근거가 제출 서류 설명이다("법인등기부등본(법인에 한함)")
  · 근거가 지원 내용 문맥이다(industry_llm_sample.quote_role == 'support')
  근거가 자격·제외 머리말 아래면 strength=strong, 머리말을 못 찾으면 weak 로 표시한다.
  세부사업마다 다르다고 하면(varies) 게이트는 이 공고를 판정하지 않는다.

읽기 전용: 출처 DB(MySQL) SELECT 만. 결과는 reports/applicant_type_llm_<시각>/ 에만 남긴다.
비용은 API 가 보고한 토큰 × 단가(industry_llm_sample.PRICES)로 계산한 추정이다. 청구액이 아니다.
"""
import argparse
import io
import json
import os
import random
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from collect import extract_conditions as ec  # noqa: E402  (문서 자르기만 재사용)
from experiments.sql_semantic import industry_llm_sample as ils  # noqa: E402  (검사 부품 재사용)
from search import gate  # noqa: E402
from shared import config as pipeline_config  # noqa: E402

MODEL = 'gpt-5.6-luna'
EFFORT = 'medium'
SEED = 20260928
N_BIZINFO, N_KSTARTUP = 40, 20
REPORTS = os.path.join(ROOT, 'reports')
TYPES = ('pre_founder', 'sole_proprietor', 'corporation')
TYPE_KO = {'pre_founder': '예비창업자', 'sole_proprietor': '개인사업자', 'corporation': '법인'}
STATUSES = ('allowed', 'not_allowed', 'implied_no', 'not_mentioned')
STATUS_KO = {'allowed': '가능', 'not_allowed': '불가', 'implied_no': '불가 추정', 'not_mentioned': '언급 없음'}

SYSTEM = """너는 정부·지자체 지원사업 공고에서 **신청할 수 있는 사람·사업자의 형태**만 찾는다.
세 가지 유형을 따로 본다: 예비창업자(아직 사업자등록 전), 개인사업자, 법인(법인사업자).

유형마다 status 와 evidence 를 채운다.
- allowed: 그 유형이 신청할 수 있다고 문서에 적혀 있다.
  예) "예비창업자 및 창업 7년 이내 기업" → 예비창업자 allowed. "개인사업자 또는 법인사업자" → 둘 다 allowed.
  "(예비)창업자" → 예비창업자 allowed.
- not_allowed: 그 유형은 안 된다고 **명시**돼 있다.
  예) "법인사업자에 한함", "법인사업자이어야 함" → 개인사업자·예비창업자 not_allowed, 법인 allowed.
  "공고일 기준 사업자등록이 되어 있어야 함", "사업자등록증을 보유한 자" → 예비창업자 not_allowed.
  "개인사업자 제외" → 개인사업자 not_allowed. "예비창업자는 신청 불가" → 예비창업자 not_allowed.
- implied_no: **예비창업자에만** 쓴다. 신청 대상이 이미 사업을 하는 기업·업체·사업장·사업자로만 적혀 있고
  예비창업자나 창업 예정자를 받는다는 말이 없을 때. 예) "도내 소재 중소 제조기업", "관내 음식점 영업자".
- not_mentioned: 판단할 문장이 없다.

지켜야 할 것
1. 신청 자격(지원대상·신청자격·참여대상·지원제외 등) 문장만 본다. 지원 내용·사업 목적·선정 우대에서 판단하지 않는다.
2. 제출서류 설명은 자격이 아니다. "법인등기부등본(법인에 한함)", "사업자등록증 사본 제출"로 판단하지 않는다.
3. "중소기업", "소상공인", "기업" 은 규모 분류이지 개인/법인 구분이 아니다. 이것만으로 개인사업자·법인을 판단하지 않는다(not_mentioned).
4. 추측하지 않는다. 명시가 아니면 allowed·not_allowed 로 쓰지 않는다.
5. evidence 는 판단 근거 문장을 **원문 그대로** 짧게(한 문장) 복사한다. not_mentioned 면 null.
6. 세부사업·유형별로 자격이 다르면 varies=true 로 하고, 가장 넓게 허용되는 쪽으로 쓴다.
7. reason 에 판단 이유를 한두 문장으로 적는다."""


def _type_schema(statuses):
    return {'type': 'object', 'additionalProperties': False,
            'properties': {'status': {'type': 'string', 'enum': list(statuses)},
                           'evidence': {'type': ['string', 'null']}},
            'required': ['status', 'evidence']}


SCHEMA = {
    'name': 'applicant_types', 'strict': True,
    'schema': {'type': 'object', 'additionalProperties': False,
               'properties': {'pre_founder': _type_schema(STATUSES),
                              'sole_proprietor': _type_schema(('allowed', 'not_allowed', 'not_mentioned')),
                              'corporation': _type_schema(('allowed', 'not_allowed', 'not_mentioned')),
                              'varies': {'type': 'boolean'},
                              'reason': {'type': 'string'}},
               'required': ['pre_founder', 'sole_proprietor', 'corporation', 'varies', 'reason']},
}

# 제출 서류 문맥 — 근거가 이 말을 담으면 자격 문장이 아니다
DOC_WORDS = re.compile(r'등본|등기사항|증명서|증명원|사본|제출|구비\s*서류|제출\s*서류|서류')
TYPE_WORDS = re.compile(r'예비|창업|개인|법인|사업자|기업|업체|영업|소상공인|사업장|자영업')


def sha(text):
    return ils.sha256_text(text)


def prompt_sha():
    return sha(SYSTEM + json.dumps(SCHEMA, ensure_ascii=False, sort_keys=True))


# ─────────────────────────────────────────────────────────── 데이터

def load_population(connection):
    """출처 DB 의 공고 + 첨부 본문 + 기존 4o-mini 값. 문서가 빈 공고는 뺀다."""
    with connection.cursor() as cur:
        cur.execute('SELECT notice_id, source, title, body, target_text, target_category, age_condition_raw '
                    'FROM notices ORDER BY notice_id')
        rows = {r[0]: dict(zip(('notice_id', 'source', 'title', 'body', 'target_text', 'target_category',
                                'age_condition_raw'), r)) for r in cur.fetchall()}
        cur.execute("""SELECT n.notice_id, at.extracted_text FROM notices n
                         JOIN notice_attachments na ON na.notice_fk = n.id
                         JOIN attachment_texts at ON at.attachment_fk = na.id
                        WHERE at.last_status = 'ok' AND at.extracted_text IS NOT NULL
                        ORDER BY n.notice_id, at.text_chars DESC""")
        for nid, text in cur.fetchall():
            if nid in rows:
                rows[nid].setdefault('attachments', []).append(text)
        cur.execute('SELECT notice_id, business_type, pre_startup_allowed FROM notice_conditions')
        for nid, bt, pre in cur.fetchall():
            if nid in rows:
                rows[nid]['legacy'] = {'business_type': json.loads(bt) if bt else [],
                                       'pre_startup_allowed': None if pre is None else bool(pre)}
    items = []
    for row in rows.values():
        prepare(row)
        if row['document'].strip():
            items.append(row)
    return items


def prepare(item):
    item['body'] = item.get('body') or ''
    item['target_text'] = item.get('target_text') or ''
    item['attachments'] = item.get('attachments') or []
    item['document'] = ec.build_document(item, max_chars=ec.MAX_CHARS)
    item['document_sha256'] = sha(item['document'])
    return item


def pick_sample(items):
    """출처별 고정 seed 표본. 기업마당 40 · K-Startup 20 (K-Startup 은 API 업력 칸과 대조할 수 있다)."""
    rng = random.Random(SEED)
    out = []
    for source, n in (('bizinfo', N_BIZINFO), ('kstartup', N_KSTARTUP)):
        pool = sorted((it for it in items if it['source'] == source), key=lambda it: it['notice_id'])
        out += rng.sample(pool, min(n, len(pool)))
    return sorted(out, key=lambda it: it['notice_id'])


# ─────────────────────────────────────────────────────────── 검사

def verify(data, document):
    """LLM 원답 → 검사한 판정. 유형마다 {'status', 'evidence', 'strength', 'raw_status', 'dropped'}."""
    out = {'varies': bool(data.get('varies')), 'reason': data.get('reason') or ''}
    for t in TYPES:
        cell = data.get(t) or {}
        status, ev = cell.get('status') or 'not_mentioned', (cell.get('evidence') or '').strip()
        res = {'status': status, 'evidence': ev or None, 'strength': None, 'raw_status': status, 'dropped': None}
        if status != 'not_mentioned':
            problem, strength = None, None
            if not ev:
                problem = '근거 없음'
            elif not ils.loose_found(ev, document):
                problem = '근거가 원문에 없음'
            elif DOC_WORDS.search(ev) and not re.search(r'신청\s*자격|지원\s*대상|자격', ev):
                problem = '제출 서류 설명'
            elif not TYPE_WORDS.search(ev):
                problem = '근거에 사업자·창업 관련 말이 없음'
            else:
                role, _why = ils.quote_role(ev, document)
                if role == 'support':
                    problem = '지원 내용 문맥'
                strength = 'strong' if role in ('eligibility', 'exclusion') else 'weak'
            if problem:
                res.update(status='not_mentioned', dropped=problem)
            else:
                res['strength'] = strength
        out[t] = res
    return out


def gate_view(v):
    """게이트가 쓸 수 있는 값: 확실한 불가만. varies 면 판정하지 않는다."""
    if v.get('varies'):
        return {}
    return {t: v[t]['status'] for t in TYPES if v[t]['status'] == 'not_allowed' and v[t]['strength'] == 'strong'}


# ─────────────────────────────────────────────────────────── 호출

def ask(client, item, model=MODEL, effort=EFFORT):
    started = time.time()
    response = client.chat.completions.create(
        model=model, **ils.request_options(model, effort),
        messages=[{'role': 'system', 'content': SYSTEM},
                  {'role': 'user', 'content': '공고 제목: %s\n\n공고문 발췌:\n%s' % (item['title'], item['document'])}],
        response_format={'type': 'json_schema', 'json_schema': SCHEMA})
    data = json.loads(response.choices[0].message.content)
    usage = response.usage
    details = getattr(usage, 'completion_tokens_details', None)
    return data, {'in': usage.prompt_tokens, 'out': usage.completion_tokens,
                  'reasoning': getattr(details, 'reasoning_tokens', None) if details is not None else None,
                  'ms': round((time.time() - started) * 1000), 'model': getattr(response, 'model', None)}


def run_calls(items, outdir, call, workers=6):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    ck = os.path.join(outdir, 'checkpoint.jsonl')
    done = {}
    if os.path.exists(ck):
        for row in ils.read_jsonl(ck):
            done[row['key']] = row
    key = lambda it: '%s|%s|%s' % (it['notice_id'], it['document_sha256'], prompt_sha())
    todo = [it for it in items if key(it) not in done]
    failures = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(call, it): it for it in todo}
        for fut in as_completed(futures):
            it = futures[fut]
            try:
                data, usage = fut.result()
            except Exception as exc:
                failures.append({'notice_id': it['notice_id'], 'error': '%s: %s' % (type(exc).__name__, exc)})
                continue
            row = {'key': key(it), 'notice_id': it['notice_id'], 'data': data, 'usage': usage}
            done[row['key']] = row
            ils.append_jsonl(ck, row)
    return {k.split('|')[0]: v for k, v in done.items()}, failures, len(todo)


# ─────────────────────────────────────────────────────────── 보고서

def legacy_cell(item):
    lg = item.get('legacy')
    if not lg:
        return '-'
    pre = {True: '예비 가능', False: '예비 불가', None: '예비 ?'}[lg['pre_startup_allowed']]
    return '%s · %s' % ('/'.join(lg['business_type']) or '형태 []', pre)


def kstartup_cell(item):
    raw = item.get('age_condition_raw')
    if item['source'] != 'kstartup' or not raw:
        return '-'
    pre_ok, _cap = gate.parse_enyy(raw)
    return '%s → 예비 %s' % (raw, '가능' if pre_ok else '불가')


def write_report(outdir, items, meta):
    keep = ('notice_id', 'source', 'title', 'target_category', 'age_condition_raw', 'legacy', 'llm', 'raw',
            'usage', 'document_sha256')
    with io.open(os.path.join(outdir, 'results.jsonl'), 'w', encoding='utf-8', newline='\n') as f:
        for it in items:
            f.write(json.dumps({k: it.get(k) for k in keep}, ensure_ascii=False) + '\n')
    with io.open(os.path.join(outdir, 'meta.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    done = [it for it in items if it.get('llm')]
    lines = ['# 신청자 유형 LLM 추출 표본 — %s' % meta['run_at'], '',
             '**사람 정답 없음.** 확보율·오독 유형·기존 4o-mini 값과의 차이를 보는 표본이다. DB 에 쓰지 않았다. 게이트에 연결하지 않았다.', '',
             '- %s · 공고 %d건(기업마당 %d · K-Startup %d) · 성공 %d · 실패 %d' % (
                 meta['engine'], meta['n'], meta['n_bizinfo'], meta['n_kstartup'], len(done), meta['failures']),
             '- 보고 토큰 입력 %d · 출력 %d · 기록 단가 기준 약 $%.4f (청구액 아님)' % (
                 meta['tokens_in'], meta['tokens_out'], meta['cost_usd']), '']
    lines += ['| 유형 | 가능 | 불가 | 불가 추정 | 언급 없음 | 검사로 내림 | 불가 중 strong |', '|---|---:|---:|---:|---:|---:|---:|']
    for t in TYPES:
        c = Counter(it['llm'][t]['status'] for it in done)
        dropped = sum(1 for it in done if it['llm'][t]['dropped'])
        strong = sum(1 for it in done if it['llm'][t]['status'] == 'not_allowed' and it['llm'][t]['strength'] == 'strong')
        lines.append('| %s | %d | %d | %d | %d | %d | %d |' % (TYPE_KO[t], c['allowed'], c['not_allowed'],
                                                             c['implied_no'], c['not_mentioned'], dropped, strong))
    varies = sum(1 for it in done if it['llm']['varies'])
    gated = sum(1 for it in done if gate_view(it['llm']))
    lines += ['', '세부사업별로 다름(varies) %d건 · 게이트가 쓸 수 있는 "확실한 불가"가 있는 공고 %d건' % (varies, gated), '']
    # K-Startup API 업력 칸과 예비창업자 판정 대조
    ks = [it for it in done if it['source'] == 'kstartup' and it.get('age_condition_raw')]
    if ks:
        agree = Counter()
        for it in ks:
            api_ok = gate.parse_enyy(it['age_condition_raw'])[0]
            st = it['llm']['pre_founder']['status']
            llm_ok = {'allowed': True, 'not_allowed': False, 'implied_no': False}.get(st)
            agree['LLM 모름' if llm_ok is None else ('일치' if llm_ok == api_ok else '불일치')] += 1
        lines += ['K-Startup API 업력 칸(예비창업자 가능 여부)과 LLM 예비창업자 판정: ' +
                  ' · '.join('%s %d' % kv for kv in sorted(agree.items())), '']
    lines += ['| 공고 | 제목 | 예비창업자 | 개인사업자 | 법인 | 기존 4o-mini | K-Startup API | 근거(예비 / 개인·법인) |',
              '|---|---|---|---|---|---|---|---|']
    for it in items:
        m = it.get('llm')
        if not m:
            lines.append('| %s | %s | 실패 | | | | | |' % (it['notice_id'], ils._cell(it['title'], 36)))
            continue

        def cell(t):
            c = m[t]
            s = STATUS_KO[c['status']] + ('' if c['strength'] != 'weak' else '(약)')
            return s + (' ⟵%s:%s' % (STATUS_KO[c['raw_status']], c['dropped']) if c['dropped'] else '')
        ev_pre = m['pre_founder']['evidence'] or ''
        ev_biz = m['corporation']['evidence'] or m['sole_proprietor']['evidence'] or ''
        lines.append('| %s | %s | %s | %s | %s | %s | %s | %s / %s |' % (
            it['notice_id'], ils._cell(it['title'], 36) + (' **(세부별)**' if m['varies'] else ''),
            cell('pre_founder'), cell('sole_proprietor'), cell('corporation'), legacy_cell(it), kstartup_cell(it),
            ils._cell(ev_pre, 70), ils._cell(ev_biz, 70)))
    with io.open(os.path.join(outdir, 'summary.md'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    return lines


def resume_spec(outdir):
    """재개 폴더의 처음 실행 모드와 대상. {'take_all': bool, 'notice_ids': list|None}."""
    for name in ('run_spec.json', 'meta.json'):
        path = os.path.join(outdir, name)
        if os.path.exists(path):
            with io.open(path, encoding='utf-8') as f:
                m = json.load(f)
            return {'take_all': bool(m.get('take_all')), 'notice_ids': m.get('notice_ids')}
    return {'take_all': os.path.basename(os.path.normpath(outdir)).startswith('applicant_type_llm_full_'),
            'notice_ids': None}


def check_resume(outdir, take_all, ids):
    """재개 모드·대상이 처음과 다르면 SystemExit. 결과 파일을 쓰기 전에 부른다."""
    spec = resume_spec(outdir)
    if spec['take_all'] != bool(take_all):
        raise SystemExit('재개 폴더는 %s 실행이었다. %s 로 다시 실행한다(결과를 쓰지 않았다)'
                         % ('전량' if spec['take_all'] else '표본', '--all 을 붙여' if spec['take_all'] else '--all 없이'))
    if spec['notice_ids'] is not None and list(spec['notice_ids']) != list(ids):
        raise SystemExit('재개 폴더의 대상 공고 목록이 지금과 다르다(결과를 쓰지 않았다)')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plan', action='store_true', help='문서·예상 비용만. 호출하지 않는다')
    ap.add_argument('--resume', help='이어 할 결과 폴더')
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--all', dest='take_all', action='store_true', help='표본 대신 문서가 있는 공고 전부')
    args = ap.parse_args(argv)

    from shared import store_mysql
    conn = store_mysql.connect()
    try:
        population = load_population(conn)
    finally:
        conn.close()
    items = sorted(population, key=lambda it: it['notice_id']) if args.take_all else pick_sample(population)
    in_tok = sum(ils.estimate_tokens(SYSTEM + it['document']) for it in items)
    price_in, price_out = ils.PRICES[MODEL]
    guess_out = len(items) * (ils.REASONING_TOKENS_GUESS[EFFORT] + 300)
    guess = in_tok / 1e6 * price_in + guess_out / 1e6 * price_out
    print('표본 %d건 (모집단 %d) · 예상 입력 %d토큰 · 예상 비용 약 $%.3f' % (len(items), len(population), in_tok, guess))
    if args.plan:
        return 0

    started = datetime.now(timezone.utc)
    ids = [it['notice_id'] for it in items]
    if args.resume:
        check_resume(args.resume, args.take_all, ids)
    outdir = args.resume or os.path.join(REPORTS, 'applicant_type_llm_%s%s' % (
        'full_' if args.take_all else '', started.strftime('%Y%m%dT%H%M%SZ')))
    os.makedirs(outdir, exist_ok=True)
    spec_path = os.path.join(outdir, 'run_spec.json')
    if not os.path.exists(spec_path):
        with io.open(spec_path, 'w', encoding='utf-8') as f:
            json.dump({'take_all': bool(args.take_all), 'notice_ids': ids, 'started_at': started.isoformat()}, f,
                      ensure_ascii=False)
    key = pipeline_config.get('OPENAI_API_KEY')
    if not key:
        raise SystemExit('OPENAI_API_KEY 가 없다')
    import openai
    client = openai.OpenAI(api_key=key)
    done, failures, called = run_calls(items, outdir, lambda it: ask(client, it), args.workers)
    t_in = t_out = 0
    for it in items:
        row = done.get(it['notice_id'])
        if row:
            it['raw'], it['usage'] = row['data'], row['usage']
            it['llm'] = verify(row['data'], it['document'])
            t_in += row['usage']['in']
            t_out += row['usage']['out']
    models = sorted({(done[n]['usage'] or {}).get('model') for n in done})
    meta = {'run_at': started.isoformat(), 'engine': '%s@%s' % (MODEL, EFFORT), 'response_models': models,
            'n': len(items), 'n_bizinfo': sum(1 for i in items if i['source'] == 'bizinfo'),
            'n_kstartup': sum(1 for i in items if i['source'] == 'kstartup'), 'population': len(population),
            'seed': SEED, 'take_all': bool(args.take_all), 'called_this_run': called, 'failures': len(failures), 'failure_rows': failures,
            'tokens_in': t_in, 'tokens_out': t_out,
            'cost_usd': round(t_in / 1e6 * price_in + t_out / 1e6 * price_out, 5), 'price_basis': ils.PRICE_BASIS,
            'prompt_sha256': prompt_sha(), 'max_chars': ec.MAX_CHARS, 'notice_ids': [i['notice_id'] for i in items],
            'db_writes': 0}
    lines = write_report(outdir, items, meta)
    print('\n'.join(lines[:16]))
    print('→', outdir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
