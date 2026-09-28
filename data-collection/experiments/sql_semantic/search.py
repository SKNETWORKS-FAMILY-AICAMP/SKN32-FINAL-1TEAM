# -*- coding: utf-8 -*-
"""정형 필터(SQL) → 후보 벡터와 직접 비교 → 규칙 정렬 → Top N.

  python -X utf8 -m experiments.sql_semantic.search --idea "..." --region 경기 --top 5
  python -X utf8 -m experiments.sql_semantic.search --no-filter ...   정형 필터 끔(대조군)

원칙 (지시서 5·6절)

  · **확실한 불일치만 SQL 에서 제외한다.** 모르는 조건은 후보로 남긴다(확인 필요).
  · 남겼다는 것이 자격을 보장한다는 뜻이 아니다. 조건별 사유를 응답에 담는다.
  · 전체 벡터 Top-K 를 먼저 자르고 SQL 필터라고 부르지 않는다. SQL 로 거른 **후보 전체**와 비교한다.
  · 값은 파라미터로 넘긴다. 사용자 입력으로 SQL 문자열을 조립하지 않는다.
  · 코사인과 규칙을 섞어 '적합 확률' 같은 하나의 점수로 만들지 않는다.
"""
import argparse
import json
import os
import sys
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from experiments.sql_semantic import config, embedding  # noqa: E402
from search import gate  # noqa: E402
from shared import region as region_mod  # noqa: E402

TOP = 5

# 조건 판정 세 값
OK, NO, CHECK = 'ok', 'no', 'check'


def applicant_age_months(applicant, as_of):
    """신청자 업력(개월). 예비창업자는 None, 설립일을 모르면 UNKNOWN_AGE."""
    if applicant.get('prestartup'):
        return None
    months = gate.business_age_months(applicant.get('founded_at') or '', as_of)
    return gate.UNKNOWN_AGE if months is None else months


def build_filter(applicant, as_of):
    """(SQL, 파라미터). 확실한 불일치만 제외한다.

    SQL 안에서 걸러내는 것은 두 가지뿐이다.
      · 마감이 지난 공고 (마감일이 **있고** 그 날짜가 기준일보다 이른 경우만)
      · 지역이 확인됐고 신청자 지역과 다른 경우 (전국·미확인은 남긴다)

    업력은 경계 처리가 까다로워 SQL 에서 값만 가져오고 파이썬에서 3값으로 판정한다.
    업종·규모·지원 방식은 자격이 아니라 선호라 여기서 거르지 않는다(지시서 5절).
    """
    where = ["(n.apply_end IS NULL OR n.apply_end >= %s)"]

    my_region = region_mod.canonical(applicant.get('region') or '') if applicant.get('region') else None
    if my_region:
        # 지역 조건이 known 이면서 내 지역이 목록에 없을 때만 제외한다.
        # no_limit(전국)·unknown 은 남긴다.
        where.append(
            "(c_region.status IS NULL OR c_region.status <> 'known' "
            " OR FIND_IN_SET(%s, c_region.value_text) > 0)")

    sql = (
        "SELECT n.notice_id, n.title, n.url, n.apply_start, n.apply_end, n.apply_period_type,\n"
        "       c_region.status AS region_status, c_region.value_text AS region_value,\n"
        "       c_age.status AS age_status, c_age.value_max AS age_max,\n"
        "       c_age.bound_note AS age_bound, c_age.value_text AS age_text,\n"
        "       c_size.status AS size_status, c_size.value_text AS size_value,\n"
        "       c_ind.status AS industry_status, c_ind.value_text AS industry_value,\n"
        "       c_type.status AS type_status, c_type.value_text AS type_value,\n"
        # 저장 벡터가 지금 공고 내용으로 만든 것인지 확인하려면 현재 본문이 필요하다
        "       n.body, n.target_text, n.target_category, n.category, n.subcategory,\n"
        "       v.vector, v.dim, v.dtype, v.normalized, v.model, v.model_revision,\n"
        "       v.contract, v.input_sha256\n"
        "  FROM lab_notices n\n"
        "  LEFT JOIN lab_conditions c_region ON c_region.notice_id = n.notice_id"
        " AND c_region.field = 'region'\n"
        "  LEFT JOIN lab_conditions c_age ON c_age.notice_id = n.notice_id"
        " AND c_age.field = 'business_age'\n"
        "  LEFT JOIN lab_conditions c_size ON c_size.notice_id = n.notice_id"
        " AND c_size.field = 'company_size'\n"
        "  LEFT JOIN lab_conditions c_ind ON c_ind.notice_id = n.notice_id"
        " AND c_ind.field = 'industry'\n"
        "  LEFT JOIN lab_conditions c_type ON c_type.notice_id = n.notice_id"
        " AND c_type.field = 'support_type'\n"
        "  LEFT JOIN lab_vectors v ON v.notice_id = n.notice_id AND v.contract = %s\n"
        " WHERE " + "\n   AND ".join(where))
    # **순서가 중요하다.** 물음표는 SQL 에 나온 순서대로 채워진다.
    # 계약(contract)은 LEFT JOIN 안에 있어 WHERE 보다 먼저 나온다.
    # 처음에 날짜를 먼저 넣었다가 실제 DB 에서 "Incorrect DATE value: '경기'" 로 실패했다.
    params = [embedding.CONTRACT, as_of.isoformat()] + ([my_region] if my_region else [])
    return sql, params


def judge_age(row, applicant_months):
    """업력 3값 판정. (판정, 사유)"""
    status = row.get('age_status')
    if status != 'known':
        return CHECK, '공고에 업력 조건이 없거나 확인 불가'
    if applicant_months is gate.UNKNOWN_AGE:
        return CHECK, '신청자 설립일을 알 수 없음'
    bound = row.get('age_bound') or ''
    if bound.startswith('prestartup_only'):
        return (OK, '예비창업자 전용 공고') if applicant_months is None \
            else (NO, '예비창업자만 신청 가능')
    cap = row.get('age_max')
    if cap is None:
        return CHECK, '업력 상한을 읽지 못함'
    if applicant_months is None:      # 예비창업자
        return (OK, '예비창업자 신청 가능') if 'no_prestartup' not in bound \
            else (NO, '예비창업자는 신청 불가')
    return (OK, '업력 %d개월 < 상한 %d개월' % (applicant_months, cap)) if applicant_months < cap \
        else (NO, '업력 %d개월 ≥ 상한 %d개월' % (applicant_months, cap))


def judge_region(row, applicant):
    my = region_mod.canonical(applicant.get('region') or '') if applicant.get('region') else None
    status = row.get('region_status')
    if not my:
        return CHECK, '신청자 소재지 미입력'
    if status == 'no_limit':
        return OK, '전국 대상'
    if status != 'known':
        return CHECK, '공고 지역 확인 불가'
    targets = {v.strip() for v in (row.get('region_value') or '').split(',') if v.strip()}
    return (OK, '대상 지역 %s' % row.get('region_value')) if my in targets \
        else (NO, '대상 지역 %s' % row.get('region_value'))


def judge_period(row, as_of):
    """접수기간. **시작 전 공고를 '충족' 이라고 말하지 않는다**(2026-09-18 Codex 리뷰 4번).

    시작일이 아직 안 왔으면 지금은 신청할 수 없다. 후보에서 빼지는 않고 '확인 필요(예정)' 로 남긴다.
    """
    start, end = row.get('apply_start'), row.get('apply_end')
    today = as_of.isoformat()
    if start and str(start) > today:
        return CHECK, '접수 시작 예정 %s' % start
    if end:
        end = str(end)
        return (OK, '마감 %s' % end) if end >= today else (NO, '마감 %s' % end)
    kind = row.get('apply_period_type') or 'unknown'
    if kind in ('rolling', 'budget_exhaustion', 'until_filled'):
        return OK, {'rolling': '상시·수시 접수', 'budget_exhaustion': '예산 소진 시까지',
                    'until_filled': '선착순'}[kind]
    return CHECK, '접수기간 정보 없음'


def judge_list(row, applicant, status_key, value_key, mine_key, label):
    """공고가 목록으로 못 박은 자격(업종·기업 규모)과 맞춰 본다.

    known 이면서 내 값이 목록에 없을 때만 불충족이다. 공고가 모르거나 내가 안 적었으면
    '확인 필요' 로 남긴다. 단어가 스쳐 지나간 것을 제한으로 승격하는 일은 conditions.py 에서
    이미 막아 둔다(2026-09-18 Codex 리뷰 1번).
    """
    status = row.get(status_key)
    # 공고가 "규모 제한 없이 모든 기업" 이라고 밝혔으면 신청자 값을 몰라도 충족이다.
    # 지역과 같은 처리다. 값 없음(unknown)과 구분한다(2026-09-21 F1 수정).
    if status == 'no_limit':
        return OK, '%s 제한 없음' % label
    mine = (applicant.get(mine_key) or '').strip()
    if not mine:
        return CHECK, '신청자 %s 미입력' % label
    if status != 'known':
        return CHECK, '공고 %s 조건 확인 불가' % label
    allowed = {v.strip() for v in (row.get(value_key) or '').split(',') if v.strip()}
    return (OK, '%s %s' % (label, row.get(value_key))) if mine in allowed \
        else (NO, '%s %s 만 해당' % (label, row.get(value_key)))


def evaluate(row, applicant, applicant_months, as_of):
    """조건별 판정 묶음. NO 가 하나라도 있으면 후보에서 뺀다(사유를 남긴다)."""
    checks = {
        'region': judge_region(row, applicant),
        'business_age': judge_age(row, applicant_months),
        'application_period': judge_period(row, as_of),
        'company_size': judge_list(row, applicant, 'size_status', 'size_value',
                                   'company_size', '기업 규모'),
        'industry': judge_list(row, applicant, 'industry_status', 'industry_value',
                               'industry', '업종'),
    }
    excluded = [k for k, (verdict, _why) in checks.items() if verdict == NO]
    unsure = [k for k, (verdict, _why) in checks.items() if verdict == CHECK]
    return checks, excluded, unsure


def rank(candidates, similarity, applicant):
    """고정된 정렬 규칙.

      1) 신청자가 원하는 지원 방식이 공고에 있으면 먼저 (선호를 밝혔을 때만)
      2) 유사도 높은 순
      3) 동점이면 공고 ID 순

    가중치를 곱해 하나의 점수로 만들지 않는다. 왜 올라갔는지 말할 수 있어야 한다.
    """
    want = (applicant.get('preferred_support_type') or '').strip()
    ordered = []
    for row, score in zip(candidates, similarity):
        types = {v.strip() for v in (row.get('type_value') or '').split(',') if v.strip()}
        matched = bool(want) and want in types
        ordered.append({'row': row, 'similarity': float(score), 'preference_match': matched})
    ordered.sort(key=lambda x: (0 if x['preference_match'] else 1,
                                -x['similarity'], x['row']['notice_id']))
    for i, item in enumerate(ordered, 1):
        item['rank'] = i
        item['rank_reason'] = ('선호한 지원 방식(%s) 일치 → 앞으로' % want) if item['preference_match'] \
            else '유사도 순'
    return ordered


def run(applicant, as_of=None, top=TOP, use_filter=True, connection=None, model=None):
    """실제 실행. connection·model 을 주면 그대로 쓴다(테스트에서 가짜를 넣는다)."""
    import numpy as np
    as_of = as_of or date.today()
    started = time.time()
    own_connection = connection is None
    connection = connection or config.connect()
    applicant_months = applicant_age_months(applicant, as_of)

    try:
        if use_filter:
            sql, params = build_filter(applicant, as_of)
        else:
            # 대조군 — 정형 필터를 끄고 모든 공고를 후보로 둔다(같은 임베딩·같은 정렬 규칙)
            sql, params = build_filter({'region': None, 'founded_at': None,
                                        'prestartup': False}, date(1900, 1, 1))
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            columns = [d[0] for d in cursor.description]
            rows = [dict(zip(columns, r)) for r in cursor.fetchall()]
        sql_ms = (time.time() - started) * 1000

        kept, dropped, missing_vector = [], [], []
        reasons = {}
        for row in rows:
            if use_filter:
                checks, excluded, unsure = evaluate(row, applicant, applicant_months, as_of)
            else:
                checks, excluded, unsure = {}, [], []
            reasons[row['notice_id']] = {'checks': {k: {'verdict': v, 'why': w}
                                                    for k, (v, w) in checks.items()},
                                         'unsure': unsure}
            if excluded:
                dropped.append({'notice_id': row['notice_id'], 'fields': excluded})
                continue
            if not row.get('vector'):
                missing_vector.append(row['notice_id'])   # 조용히 버리지 않는다
                continue
            kept.append(row)

        query_text = applicant.get('idea') or ''
        model = model or embedding.load_model()
        t0 = time.time()
        query_vec = embedding.encode(model, [query_text])[0]
        encode_ms = (time.time() - t0) * 1000

        # 저장 벡터를 쓰기 전에 세 가지를 본다 (2026-09-18 Codex 리뷰 2·3번)
        #   ② 지금 공고 내용으로 만든 벡터인가  — 입력 해시를 다시 계산해 맞춘다
        #   ② 같은 계약·모델로 만든 벡터인가
        #   ③ 지금 질의와 **같은 차원**인가   — 한 건이 이상해도 검색 전체가 죽지 않게 개별 검사
        expected_dim = int(len(query_vec))
        meta = embedding.meta()
        vectors, valid, broken, stale = [], [], [], []
        for row in kept:
            text, _sources = embedding.build_input(row)
            digest = embedding.input_sha256(text)
            if row.get('input_sha256') != digest:
                stale.append({'notice_id': row['notice_id'], 'reason': '공고 내용이 바뀐 뒤 벡터 미갱신'})
                continue
            if row.get('contract') != meta['contract'] or row.get('model') != meta['model']:
                stale.append({'notice_id': row['notice_id'],
                              'reason': '다른 계약/모델의 벡터 (%s / %s)'
                                        % (row.get('contract'), row.get('model'))})
                continue
            # 모델 **리비전**까지 같아야 같은 벡터 공간이다(2026-09-18 Codex 리뷰 F2).
            # 이름이 같아도 캐시가 갱신되면 내용이 다른 모델이다. 입력 해시가 같다는 것만으로
            # 호환된다고 보지 않는다. 어느 쪽이든 리비전을 모르면 확인할 수 없으므로 쓰지 않는다.
            stored_rev, current_rev = row.get('model_revision') or None, meta['model_revision'] or None
            if stored_rev is None or current_rev is None:
                stale.append({'notice_id': row['notice_id'],
                              'reason': '모델 리비전 확인 불가 (저장 %s / 현재 %s)'
                                        % (stored_rev or '없음', current_rev or '없음')})
                continue
            if stored_rev != current_rev:
                stale.append({'notice_id': row['notice_id'],
                              'reason': '다른 모델 리비전 (저장 %s / 현재 %s)'
                                        % (stored_rev[:12], current_rev[:12])})
                continue
            try:
                vector = embedding.unpack(row['vector'], int(row['dim']))
                if int(row['dim']) != expected_dim:
                    raise ValueError('질의 차원 %d 과 다르다 (저장 %d)'
                                     % (expected_dim, int(row['dim'])))
                if (row.get('dtype') or embedding.DTYPE) != embedding.DTYPE:
                    raise ValueError('dtype 이 다르다: %s' % row.get('dtype'))
            except ValueError as exc:
                broken.append({'notice_id': row['notice_id'], 'error': str(exc)})
                continue
            vectors.append(vector)
            valid.append(row)
        t0 = time.time()
        scores = embedding.cosine(query_vec, np.vstack(vectors)) if vectors else []
        compare_ms = (time.time() - t0) * 1000

        ordered = rank(valid, scores, applicant)[:top]
        results = []
        for item in ordered:
            row = item['row']
            results.append({
                'notice_id': row['notice_id'], 'title': row['title'], 'url': row['url'],
                'rank': item['rank'], 'similarity': round(item['similarity'], 4),
                'rank_reason': item['rank_reason'],
                'apply_end': str(row.get('apply_end') or ''),
                'apply_period_type': row.get('apply_period_type'),
                'region': row.get('region_value'), 'region_status': row.get('region_status'),
                'conditions': reasons[row['notice_id']]['checks'],
                'needs_check': reasons[row['notice_id']]['unsure'],
            })
        return {
            'as_of_date': as_of.isoformat(),
            'use_filter': use_filter,
            'applicant': {k: v for k, v in applicant.items() if k != 'idea'},
            'query_text': query_text,
            # 질의를 만든 인코더. 저장 벡터와 같은 리비전이어야 비교가 성립한다(F2)
            'encoder': {'model': meta['model'], 'model_revision': meta['model_revision'],
                        'contract': meta['contract']},
            'counts': {'rows_from_sql': len(rows), 'after_conditions': len(kept),
                       'compared': len(valid), 'returned': len(results),
                       'dropped': len(dropped), 'missing_vector': len(missing_vector),
                       'broken_vector': len(broken), 'stale_vector': len(stale)},
            'dropped_examples': dropped[:10],
            'missing_vector_examples': missing_vector[:10],
            'broken_vector_examples': broken[:10],
            'stale_vector_examples': stale[:10],
            'timing_ms': {'sql': round(sql_ms, 1), 'encode': round(encode_ms, 1),
                          'compare': round(compare_ms, 1),
                          'total': round((time.time() - started) * 1000, 1)},
            'results': results,
        }
    finally:
        if own_connection:
            connection.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--idea', required=True)
    ap.add_argument('--region', default='')
    ap.add_argument('--district', default='')
    ap.add_argument('--founded-at', dest='founded_at', default='')
    ap.add_argument('--prestartup', action='store_true')
    ap.add_argument('--industry', default='', help='신청자 업종 (제조업·서비스업 …)')
    ap.add_argument('--company-size', dest='company_size', default='',
                    help='기업 규모 (중소기업·소상공인·중견기업 …)')
    ap.add_argument('--prefer', default='', help='선호 지원 방식 (보조금·융자·교육 …)')
    ap.add_argument('--as-of', dest='as_of', default='')
    ap.add_argument('--top', type=int, default=TOP)
    ap.add_argument('--no-filter', dest='use_filter', action='store_false',
                    help='정형 필터를 끄고 같은 임베딩·정렬로만 검색한다(대조군)')
    args = ap.parse_args()

    applicant = {'idea': args.idea, 'region': args.region, 'district': args.district,
                 'founded_at': args.founded_at, 'prestartup': args.prestartup,
                 'industry': args.industry, 'company_size': args.company_size,
                 'preferred_support_type': args.prefer}
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    out = run(applicant, as_of=as_of, top=args.top, use_filter=args.use_filter)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
