# -*- coding: utf-8 -*-
"""Codex 판정 꾸러미 — 신청자 유형(LLM 전량)과 업종 순위로 밀린 공고를 사람 대신 Codex 가 **블라인드**로 판정한다.

  python -X utf8 -m experiments.sql_semantic.label_pack          reports/label_pack_<시각>/ 을 만든다 (DB 읽기만)

2026-09-28 사용자 요청 — 게이트·순위 연결 전에 독립 판정("AI 참고 정답")을 받는다.
판정지에는 **공고문 발췌만** 넣는다. LLM 답은 answers_hidden.jsonl 에 따로 두고, 판정이 끝난 뒤 label_score 로 대조한다.

묶음 (신청자 유형 — reports/applicant_type_llm_full_20260928T023916Z)
  A  예비창업자 '불가' strong, varies 아님   30 (183 중)  게이트 필터로 써도 되나
  B  K-Startup API 업력 칸은 예비 불가, LLM 은 예비 가능   전부(9)  본문을 API 보다 우선해도 되나
  C  예비창업자 '불가' weak                 15           약한 근거도 쓸 수 있나
  D  개인사업자·법인 '불가' strong           20 (42 중)   개인/법인 게이트를 둘 만한가
  E  예비창업자 '불가 추정'                  20           순위 신호로 써도 되나
  F  세 유형 모두 '언급 없음'                10           놓친 제한이 있나
업종 — 최신 업종 순위 평가(reports/industry_rank_check_*)에서 서비스 조건 상위 10 밖으로 밀린 공고 전부.
  신청자 대분류(밀린 쌍의 업종)마다 "그 업종 신청자는 확실히 신청할 수 없는가"를 묻는다.

발췌는 LLM 이 본 것과 같은 규칙(collect.extract_conditions.build_document, 6,000자)으로 **지금 출처 DB** 에서 다시 만든다.
신청자 유형은 document_sha256 이 같으면 same_document=true 로 표시한다. 업종은 실험 DB 스냅샷(9/18)에서 뽑았으므로 발췌가 조금 다를 수 있다.
"""
import argparse
import io
import json
import os
import random
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from experiments.sql_semantic import applicant_type_llm as atl  # noqa: E402
from experiments.sql_semantic.industry_results import notice_url  # noqa: E402

REPORTS = os.path.join(ROOT, 'reports')
APPLICANT_RUN = 'applicant_type_llm_full_20260928T023916Z'
SEED = 20260929
SIZES = {'A': 30, 'B': None, 'C': 15, 'D': 20, 'E': 20, 'F': 10}      # None = 전부
SECTION_KO = {'A': '농업·임업·어업', 'C': '제조업', 'F': '건설업', 'G': '도매·소매', 'I': '숙박·음식점',
              'J': '정보통신', 'N': '사업시설관리·사업지원·임대(여행 포함)'}


def read_jsonl(path):
    with io.open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def stratum(row):
    """신청자 유형 결과 한 행 → 묶음(A~F) 또는 None. 한 공고는 하나의 묶음에만 든다(앞 묶음 우선)."""
    from search import gate
    m = row['llm']
    pre = m['pre_founder']
    biz = [m[t] for t in ('sole_proprietor', 'corporation')]
    if row.get('source') == 'kstartup' and row.get('age_condition_raw') \
            and gate.parse_enyy(row['age_condition_raw'])[0] is False and pre['status'] == 'allowed':
        return 'B'
    if pre['status'] == 'not_allowed' and pre['strength'] == 'strong' and not m.get('varies'):
        return 'A'
    if any(c['status'] == 'not_allowed' and c['strength'] == 'strong' for c in biz):
        return 'D'
    if pre['status'] == 'not_allowed' and pre['strength'] == 'weak':
        return 'C'
    if pre['status'] == 'implied_no':
        return 'E'
    if pre['status'] == 'not_mentioned' and all(c['status'] == 'not_mentioned' for c in biz):
        return 'F'
    return None


def pick(rows, rng):
    by = {}
    for r in rows:
        s = stratum(r)
        if s:
            by.setdefault(s, []).append(r)
    out = []
    for s in sorted(SIZES):
        pool = sorted(by.get(s, []), key=lambda r: r['notice_id'])
        n = SIZES[s]
        chosen = pool if n is None or n >= len(pool) else rng.sample(pool, n)
        out += [(s, r) for r in sorted(chosen, key=lambda r: r['notice_id'])]
    return out, {s: len(v) for s, v in by.items()}


def latest_industry_check():
    names = sorted(n for n in os.listdir(REPORTS) if n.startswith('industry_rank_check_'))
    return names[-1] if names else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', help='결과 폴더 (기본 reports/label_pack_<시각>)')
    args = ap.parse_args(argv)
    started = datetime.now(timezone.utc)

    from shared import store_mysql
    conn = store_mysql.connect()
    try:
        docs = {it['notice_id']: it for it in atl.load_population(conn)}
    finally:
        conn.close()

    rows = read_jsonl(os.path.join(REPORTS, APPLICANT_RUN, 'results.jsonl'))
    chosen, pools = pick(rows, random.Random(SEED))
    items, hidden = [], []
    for i, (s, r) in enumerate(chosen, 1):
        doc = docs.get(r['notice_id'])
        item_id = 'P%03d' % i
        items.append({'item_id': item_id, 'group': s, 'notice_id': r['notice_id'], 'title': r['title'],
                      'url': notice_url(r['notice_id']), 'source': r['source'],
                      'api_age_condition': r.get('age_condition_raw') if s == 'B' else None,
                      'same_document': bool(doc) and doc['document_sha256'] == r.get('document_sha256'),
                      'document': doc['document'] if doc else ''})
        hidden.append({'item_id': item_id, 'group': s, 'notice_id': r['notice_id'],
                       'llm': {t: {k: r['llm'][t].get(k) for k in ('status', 'strength', 'evidence')}
                               for t in atl.TYPES}, 'varies': r['llm'].get('varies')})

    check = latest_industry_check()
    ind_items = []
    if check:
        with io.open(os.path.join(REPORTS, check, 'results.json'), encoding='utf-8') as f:
            res = json.load(f)
        for j, n in enumerate(res['demoted_notices'], 1):
            doc = docs.get(n['notice_id'])
            item_id = 'I%03d' % j
            asked = sorted(n.get('asked') or {})
            ind_items.append({'item_id': item_id, 'notice_id': n['notice_id'], 'title': n['title'],
                              'url': notice_url(n['notice_id']),
                              'asked_sections': [{'code': c, 'name': SECTION_KO.get(c, c)} for c in asked],
                              'document': doc['document'] if doc else ''})
            hidden.append({'item_id': item_id, 'group': 'industry', 'notice_id': n['notice_id'],
                           'llm_allowed': n['allowed'], 'llm_sections': n['sections'], 'asked': asked,
                           'pairs': n['pairs'], 'rel2_pairs': n['rel2_pairs']})

    out = args.out or os.path.join(REPORTS, 'label_pack_%s' % started.strftime('%Y%m%dT%H%M%SZ'))
    os.makedirs(out, exist_ok=False)

    def dump(name, rows_):
        with io.open(os.path.join(out, name), 'w', encoding='utf-8', newline='\n') as f:
            for row in rows_:
                f.write(json.dumps(row, ensure_ascii=False) + '\n')
    dump('applicant_items.jsonl', items)
    dump('industry_items.jsonl', ind_items)
    dump('answers_hidden.jsonl', hidden)
    meta = {'created_at': started.isoformat(), 'applicant_run': APPLICANT_RUN, 'industry_check': check,
            'seed': SEED, 'sizes': SIZES, 'pools': pools,
            'applicant_items': len(items), 'industry_items': len(ind_items),
            'groups': {g: sum(1 for it in items if it['group'] == g) for g in sorted(SIZES)},
            'same_document': sum(1 for it in items if it['same_document']), 'db_writes': 0}
    with io.open(os.path.join(out, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(json.dumps(meta, ensure_ascii=False, indent=1))
    print('→', out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
