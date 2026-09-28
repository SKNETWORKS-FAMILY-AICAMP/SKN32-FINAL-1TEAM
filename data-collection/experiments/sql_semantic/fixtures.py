# -*- coding: utf-8 -*-
"""검증 화면용 **가짜 데이터**. 실제 DB·모델을 부르지 않는다.

왜 만드나. 저장된 실행 결과(`reports/sql_semantic_*`)에는 사람이 봐야 할 상태가 전부
들어 있지 않다. 예를 들어 아래는 실제 10개 입력에서 한 번도 나오지 않았다.

  · 조건 불충족(no)으로 후보에서 빠지는 공고
  · 벡터가 없거나 깨진 공고
  · 후보가 0건인 화면
  · 자격 문구를 잘못 읽는 사례 (리뷰 F1)

그래서 **조건 추출과 검색 로직은 진짜 코드를 그대로 부르고**, 입력만 가짜로 만든다.
화면에서 진짜 동작(문제 포함)을 눈으로 볼 수 있어야 하기 때문이다.

여기서 나오는 수치는 어떤 실제 데이터도 나타내지 않는다. 화면에는 항상
`DEMO/FIXTURE — 실제 검색 결과 아님` 을 붙인다.
"""
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from experiments.sql_semantic import conditions, embedding, search  # noqa: E402

BANNER = 'DEMO/FIXTURE — 실제 검색 결과 아님'
AS_OF = date(2026, 9, 18)          # 고정한다. 새로고침해도 같은 화면이 나와야 한다


# ---------------------------------------------------------------- 가짜 연결·모델

class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.description = [(k,) for k in (rows[0] if rows else {})]

    def execute(self, sql, params=None):
        return None

    def fetchall(self):
        return [tuple(r.values()) for r in self.rows]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConnection:
    """SQL 을 실제로 돌리지 않는다. 미리 만든 줄을 그대로 돌려준다.

    주의: 진짜 DB 라면 SQL 의 WHERE 가 걸러 냈을 줄도 여기서는 그대로 나온다.
    그래서 화면의 `SQL 후보` 숫자는 fixture 에서 '입력으로 넣은 줄 수'다.
    """

    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return _Cursor(self.rows)

    def close(self):
        return None


def _fake_encode(_model, texts, **_kw):
    """질의를 항상 같은 2차원 벡터로 만든다. 모델을 부르지 않는다."""
    import numpy as np
    return np.array([[1.0, 0.0]] * len(texts), dtype='float32')


def _notice(notice_id, title, **kw):
    """공고 원문 한 줄 (조건 추출에 넣는 형태)."""
    row = {'notice_id': notice_id, 'source': 'fixture', 'title': title, 'body': '',
           'target_text': '', 'target_category': '', 'category': '', 'subcategory': '',
           'organizer': '가상기관', 'region': '전국', 'age_condition_raw': '',
           'apply_start': '2026-01-01', 'apply_end': '2026-12-31',
           'apply_period_type': 'fixed', 'recruitment_status': 'open',
           'url': 'https://example.invalid/notice/' + notice_id}
    row.update(kw)
    return row


def _search_row(notice, vector, **kw):
    """조건 추출 결과를 검색이 읽는 한 줄로 바꾼다 (진짜 SQL 이 주는 모양)."""
    import numpy as np
    extracted = {c['field']: c for c in conditions.build(notice)}

    def cell(field, key, default=None):
        return (extracted.get(field) or {}).get(key, default)

    meta = embedding.meta()
    row = {
        'notice_id': notice['notice_id'], 'title': notice['title'], 'url': notice['url'],
        'apply_start': notice['apply_start'], 'apply_end': notice['apply_end'],
        'apply_period_type': notice['apply_period_type'],
        'region_status': cell('region', 'status'), 'region_value': cell('region', 'value_text'),
        'age_status': cell('business_age', 'status'), 'age_max': cell('business_age', 'value_max'),
        'age_bound': cell('business_age', 'bound_note'), 'age_text': cell('business_age', 'value_text'),
        'size_status': cell('company_size', 'status'), 'size_value': cell('company_size', 'value_text'),
        'industry_status': cell('industry', 'status'), 'industry_value': cell('industry', 'value_text'),
        'type_status': cell('support_type', 'status'), 'type_value': cell('support_type', 'value_text'),
        'body': notice['body'], 'target_text': notice['target_text'],
        'target_category': notice['target_category'], 'category': notice['category'],
        'subcategory': notice['subcategory'],
        'vector': embedding.pack(np.asarray(vector, dtype='float32')),
        'dim': len(vector), 'dtype': meta['dtype'], 'normalized': 1,
        'model': meta['model'], 'model_revision': meta['model_revision'],
        'contract': meta['contract'],
    }
    text, _sources = embedding.build_input(row)
    row['input_sha256'] = embedding.input_sha256(text)
    row['_evidence'] = {field: extracted[field].get('evidence') for field in extracted}
    row['_conditions'] = extracted
    row.update(kw)
    return row


# ---------------------------------------------------------------- 조건 판정 반례
#
# 지시서 3-B 의 네 가지를 각각 한 건씩 만든다. `expect` 는 '이렇게 읽어야 맞다',
# `guards` 는 이 검사가 지키는 리뷰 항목이다. 실제 추출 결과가 expect 와 다르면
# 화면에 **문제 재현됨**으로 표시한다. 통과처럼 꾸미지 않는다.
#
# 2026-09-21: F1 을 수정해 반례가 모두 `기대대로` 가 됐다. 검사는 지우지 않는다 —
# 같은 오해석이 다시 들어오면 여기서 바로 빨갛게 드러나야 한다.
# 같은 날 Codex 재리뷰에서 '다른 조건의 제한 없음이 새는' 문제가 나와 두 건을 더했다.

CONDITION_CASES = (
    {
        'id': 'fx-size-nolimit',
        'label': '제한 없다는 문구를 규모 제한으로 읽지 않는가',
        'field': 'company_size',
        'expect': ('no_limit', 'unknown'),
        'guards': 'F1',
        'why': '제목에 대기업이 들어갔을 뿐 신청 자격은 제한이 없다. '
               '제한 없음(no_limit)이거나 최소한 단정하지 않아야(unknown) 한다.',
        'notice': _notice('fx-size-nolimit', '대기업과 함께하는 기술교류 프로그램',
                          target_text='기업 규모 제한 없이 모든 기업 신청 가능',
                          category='기술'),
    },
    {
        'id': 'fx-industry-exclude',
        'label': '제외 문구를 허용 목록으로 뒤집지 않는가',
        'field': 'industry',
        'expect': ('unknown', 'no_limit'),
        'guards': 'F1',
        'why': '제조업을 **제외**한다는 문장이다. 제조업만 가능으로 읽으면 판정이 정반대가 된다.',
        'notice': _notice('fx-industry-exclude', '지역 소상공인 성장지원',
                          target_text='제조업을 영위하는 기업은 제외하며 그 외 업종은 모두 신청 가능',
                          category='경영'),
    },
    {
        'id': 'fx-region-free-not-industry-free',
        'label': '지역 제한 없음이 업종 제한 없음으로 새지 않는가',
        'field': 'industry',
        'expect': ('unknown',),
        'guards': 'F1',
        'why': '"지역 제한 없음" 은 지역 이야기다. 업종까지 제한 없음으로 바꾸면 '
               '업종 제한이 있는 공고도 아무나 통과시킨다 (Codex F1 리뷰 P1, 실제 공고에서 발견).',
        'notice': _notice('fx-region-free-not-industry-free', '창업기업 사업화 지원',
                          target_text='창업기업 지역 제한 없음', category='사업화'),
    },
    {
        'id': 'fx-industry-free-keeps-size',
        'label': '업종 제한 없음이 규모 제한을 지우지 않는가',
        'field': 'company_size',
        'expect': ('known',),
        'guards': 'F1',
        'why': '"업종 제한 없이 중소기업만" 이면 규모는 중소기업이다. '
               '규모까지 제한 없음이 되면 대기업도 통과한다.',
        'notice': _notice('fx-industry-free-keeps-size', '중소기업 기술개발 지원',
                          target_text='업종 제한 없이 중소기업만 신청 가능', category='기술'),
    },
    {
        'id': 'fx-purpose-not-industry',
        'label': '지원 분야 분류를 업종 자격으로 오인하지 않는가',
        'field': 'industry',
        'expect': ('unknown',),
        'guards': None,
        'why': 'category 의 제조는 사업 분류다. 신청 가능 업종이 아니다 (리뷰 1번에서 고친 부분).',
        'notice': _notice('fx-purpose-not-industry', '스마트 제조 혁신 바우처',
                          category='제조', target_text='중소기업 및 소상공인'),
    },
    {
        'id': 'fx-age-unknown',
        'label': '업력 문구가 없을 때 값을 지어내지 않는가',
        'field': 'business_age',
        'expect': ('unknown',),
        'guards': None,
        'why': '공고에 업력 문구가 없으면 unknown 이다. 0개월이나 제한 없음으로 바꾸지 않는다.',
        'notice': _notice('fx-age-unknown', '창업기업 판로개척 지원',
                          target_text='창업기업', category='판로'),
    },
)


def condition_cases():
    """반례를 **실제 추출기**에 넣고 결과를 그대로 돌려준다."""
    out = []
    for case in CONDITION_CASES:
        extracted = {c['field']: c for c in conditions.build(case['notice'])}
        got = extracted.get(case['field']) or {'status': '(없음)'}
        passed = got.get('status') in case['expect']
        out.append({
            'id': case['id'], 'label': case['label'], 'field': case['field'],
            'why': case['why'], 'guards': case['guards'],
            'notice': {k: v for k, v in case['notice'].items() if k != 'notice_id'},
            'notice_id': case['notice']['notice_id'],
            'expected_status': '/'.join(case['expect']),
            'actual_status': got.get('status'),
            'actual_value': got.get('value_text'),
            'evidence': got.get('evidence'),
            'result': '기대대로' if passed else '문제 재현됨',
            'passed': passed,
            'all_fields': [extracted[f] for f in sorted(extracted)],
        })
    return out


# ---------------------------------------------------------------- 검색 화면 fixture

def _demo_rows():
    """검색 fixture 의 공고 6건. 화면에서 봐야 할 상태를 하나씩 담았다."""
    import numpy as np
    rows = []
    # 1. 평범하게 통과하는 공고 (유사도 가장 높음)
    rows.append(_search_row(_notice(
        'fx-001', '중소 제조기업 비전 AI 검사 장비 도입 지원',
        body='불량 검출 자동화 설비 도입비를 기업당 최대 5,000만원 지원한다.',
        target_text='경기도 소재 중소기업', region='경기', category='기술',
        age_condition_raw='업력 7년 미만'), [1.0, 0.0]))
    # 2. 지역이 달라 SQL 단계에서 빠지는 공고
    rows.append(_search_row(_notice(
        'fx-002', '부산 스마트공장 구축 지원',
        body='스마트공장 고도화를 지원한다.', target_text='부산 소재 중소기업',
        region='부산', category='기술'), [0.9, 0.1]))
    # 3. 업력 상한을 넘겨 파이썬 조건에서 빠지는 공고
    rows.append(_search_row(_notice(
        'fx-003', '초기창업 패키지',
        body='창업 3년 미만 기업의 사업화 자금을 지원한다.',
        target_text='업력 3년 미만 창업기업', region='전국',
        age_condition_raw='3년미만', category='창업'), [0.8, 0.2]))
    # 4. 벡터가 아예 없는 공고 (조용히 버리지 않고 센다)
    rows.append(dict(_search_row(_notice(
        'fx-004', '제조 공정 데이터 분석 컨설팅',
        body='공정 데이터 분석 컨설팅을 제공한다.', target_text='중소기업',
        region='전국', category='기술'), [0.7, 0.3]), vector=None))
    # 5. 저장 길이와 dim 이 어긋난 손상 벡터 (한 건 깨져도 나머지는 나와야 한다)
    rows.append(dict(_search_row(_notice(
        'fx-005', '뿌리기업 자동화 설비 지원',
        body='자동화 설비 도입을 지원한다.', target_text='중소기업',
        region='전국', category='기술'), [0.6, 0.4]), dim=1024))
    # 6. 공고 내용이 바뀐 뒤 벡터를 다시 만들지 않은 경우 (낡은 벡터)
    rows.append(dict(_search_row(_notice(
        'fx-006', '중소기업 기술개발 지원',
        body='기술개발 과제를 지원한다.', target_text='중소기업',
        region='전국', category='기술'), [0.5, 0.5]),
        input_sha256='0' * 64))
    # 7. 같은 모델 이름이지만 **다른 리비전**으로 만든 벡터 (리뷰 F2 — 예전에는 그대로 통과했다)
    rows.append(dict(_search_row(_notice(
        'fx-007', '스마트공장 고도화 컨설팅',
        body='스마트공장 고도화 컨설팅을 제공한다.', target_text='중소기업',
        region='전국', category='기술'), [0.95, 0.05]),
        model_revision='old-revision-0000'))
    return rows


APPLICANT = {
    'idea': '금형·사출 공장의 불량을 카메라로 자동 검출하는 비전 AI 검사 장비',
    'region': '경기', 'district': '수원시', 'founded_at': '2021-04-01',
    'prestartup': False, 'preferred_support_type': '',
}

# 신청자 정보를 비운 경우 — 후보를 떨어뜨리지 않고 '확인 필요'로 남기는지 본다
APPLICANT_SPARSE = {
    'idea': '금형·사출 공장의 불량을 카메라로 자동 검출하는 비전 AI 검사 장비',
    'region': '', 'district': '', 'founded_at': '', 'prestartup': False,
    'preferred_support_type': '',
}


def _run(rows, applicant, use_filter):
    """진짜 `search.run` 을 가짜 연결·가짜 인코더로 돌린다."""
    from unittest.mock import patch
    with patch.object(embedding, 'encode', _fake_encode):
        return search.run(applicant, as_of=AS_OF, top=5, use_filter=use_filter,
                          connection=FakeConnection(rows), model=object())


FIXTURE_CASES = (
    {'case_id': 'fx-case01', 'label': '일반 사례 — 지역·업력·벡터 상태가 섞여 있다',
     'note': '조건 불충족·벡터 없음·손상·낡음이 한 화면에 나온다.',
     'applicant_key': 'full'},
    {'case_id': 'fx-case02', 'label': '신청자 정보 없음 — 후보를 떨어뜨리지 않는다',
     'note': '소재지·설립일을 비웠다. 조건은 모두 확인 필요로 남고 후보는 유지돼야 한다.',
     'applicant_key': 'sparse'},
    {'case_id': 'fx-case03', 'label': '후보 0건 — 빈 화면이 깨지지 않는다',
     'note': '조건에 맞는 공고가 하나도 없는 경우다.',
     'applicant_key': 'none'},
)


# fixture 는 **고정된 가짜 리비전**을 쓴다. 이 PC 의 모델 캐시 유무에 따라 화면·테스트가 달라지면
# 안 된다(캐시가 없는 PC 에서는 리비전이 없어 모든 벡터가 '확인 불가'로 빠진다).
FIXTURE_REVISION = 'fixture-revision'


def fixture_run():
    """화면이 읽는 fixture 실행 결과. 매번 같은 값이 나온다."""
    from unittest.mock import patch
    with patch.object(embedding, 'model_revision', lambda: FIXTURE_REVISION):
        return _fixture_run()


def _fixture_run():
    rows = _demo_rows()
    responses = []
    for case in FIXTURE_CASES:
        if case['applicant_key'] == 'full':
            applicant, case_rows = APPLICANT, rows
        elif case['applicant_key'] == 'sparse':
            applicant, case_rows = APPLICANT_SPARSE, rows
        else:
            # 지역이 모두 다른 공고만 남겨 후보 0건을 만든다
            applicant = dict(APPLICANT, region='제주')
            case_rows = [r for r in rows if r['notice_id'] == 'fx-002']
        for mode, use_filter in (('filter_on', True), ('filter_off', False)):
            responses.append({'case_id': case['case_id'], 'qid': case['case_id'],
                              'mode': mode, 'at': '(fixture — 실행 시각 없음)',
                              'response': _run(case_rows, applicant, use_filter)})
    evidence = {}
    titles = {}
    for row in rows:
        evidence[row['notice_id']] = row.get('_evidence') or {}
        titles[row['notice_id']] = row['title']
    meta = embedding.meta()
    manifest = {
        'run_id': 'fixture',
        'kind': 'fixture',
        'banner': BANNER,
        'task': 'docs/CLAUDE_UI_VERIFICATION_TASK_20260921.md',
        'run_at': '(fixture — 실행 시각 없음)',
        'as_of_date': AS_OF.isoformat(),
        'comparable': '아니오 — 가짜 입력이다. 실제 공고·실제 검색 결과가 아니다.',
        'lab': {'lab': '(fixture — DB 를 부르지 않았다)', 'separated': True},
        'embedding': dict(meta, note='모델을 부르지 않고 고정 벡터를 썼다'),
        'model_revision': meta.get('model_revision'),
        'condition_extractor': conditions.EXTRACTOR,
        'top': 5,
        'data_quality': {
            'notices': len(rows),
            'vectors': {'count': sum(1 for r in rows if r.get('vector')),
                        'dim_min': 2, 'dim_max': 2, 'contract': meta['contract'],
                        'without_vector': sum(1 for r in rows if not r.get('vector'))},
            'conditions': conditions.coverage(
                [c for row in rows for c in (row.get('_conditions') or {}).values()]),
        },
        'counts': {'cases': len(FIXTURE_CASES), 'responses': len(responses)},
    }
    cases = [{'case_id': c['case_id'], 'qid': c['case_id'], 'kind': 'fixture',
              'category': '(fixture)', 'as_of_date': AS_OF.isoformat(),
              'reason': c['label'], 'supplement_note': c['note'],
              'payload': {'idea': APPLICANT['idea']}} for c in FIXTURE_CASES]
    return {'manifest': manifest, 'cases': cases, 'responses': responses,
            'evidence': evidence, 'titles': titles,
            'condition_cases': condition_cases()}
