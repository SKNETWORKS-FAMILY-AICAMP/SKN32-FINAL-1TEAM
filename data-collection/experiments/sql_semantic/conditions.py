# -*- coding: utf-8 -*-
"""공고 원문 → 정형 조건. **DB 없이 도는 순수 함수**라 테스트가 쉽다.

세 가지 상태로만 말한다.

  known      공고에서 값을 확인했다
  no_limit   제한이 없다고 공고가 밝혔다 (예: 지역 '전국')
  unknown    확인할 수 없다  ← 값이 없는 것과 제한이 없는 것을 뭉개지 않는다

원문에 없는 값을 만들어 내지 않는다. 애매하면 unknown 이다. 그래서 확보율이 낮게 나오는데,
그 숫자를 그대로 보고하는 것이 이번 실험의 목적 중 하나다(지시서 4절).

기존 `notice_conditions.age_years_*` 는 **근거로만** 쓰고 신뢰된 필터로 승격하지 않는다(지시서 4절).
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from search import gate  # noqa: E402  (업력 문구 해석은 서비스와 같은 규칙을 쓴다)
from shared import region as region_mod  # noqa: E402

# 추출 규칙이 바뀌면 올린다. DB 의 lab_conditions.extractor 만 보고 어느 규칙으로 만든 값인지 알 수 있어야 한다.
#   sql_lab_v1  2026-09-18 최초 적재 (F1 오해석 포함)
#   sql_lab_v2  2026-09-21 F1 수정 — 지원대상 칸만, 제외·거래상대 문장 제외, 필드별 제한 없음
EXTRACTOR = 'sql_lab_v2'

KNOWN, NO_LIMIT, UNKNOWN = 'known', 'no_limit', 'unknown'

# 기업 규모 — 지원대상 문구에 그대로 나오는 말만 인정한다
SIZE_WORDS = (('중소기업', '중소기업'), ('소상공인', '소상공인'), ('중견기업', '중견기업'),
              ('대기업', '대기업'), ('스타트업', '스타트업'), ('1인 기업', '1인기업'),
              ('1인기업', '1인기업'), ('사회적기업', '사회적기업'))

# 지원 방식 — 자격이 아니라 **선호**로 쓴다
SUPPORT_TYPES = (('보조금', '보조금'), ('출연', '보조금'), ('융자', '융자'), ('대출', '융자'),
                 ('보증', '보증'), ('투자', '투자'), ('바우처', '바우처'),
                 ('컨설팅', '컨설팅'), ('교육', '교육'), ('멘토링', '컨설팅'),
                 ('공간', '공간'), ('입주', '공간'))

# 기업당 최대 지원금. '총 사업비', '예산 규모' 같은 총액 표현은 일부러 제외한다
AMOUNT_RE = re.compile(r'(?:기업당|업체당|사당|최대|최고)\s*([0-9][0-9,\.]*)\s*(억|천만|백만|만)?\s*원')
TOTAL_HINTS = ('총사업비', '총 사업비', '총예산', '총 예산', '사업비 총', '예산 규모', '지원 규모 총')
UNIT = {'억': 100_000_000, '천만': 10_000_000, '백만': 1_000_000, '만': 10_000, None: 1}


def _cond(field, status, **kw):
    row = {'field': field, 'status': status, 'value_text': None, 'value_min': None,
           'value_max': None, 'bound_note': None, 'evidence': None, 'extractor': EXTRACTOR}
    row.update(kw)
    return row


def region_condition(notice):
    """지역. '전국' 은 제한 없음이지 값 없음이 아니다."""
    value = (notice.get('region') or '').strip()
    if not value:
        return _cond('region', UNKNOWN, evidence=None)
    if value == region_mod.NATIONWIDE:
        return _cond('region', NO_LIMIT, value_text=region_mod.NATIONWIDE, evidence='region=전국')
    names = [region_mod.canonical(v) for v in value.split(',')]
    names = [n for n in names if n]
    if not names:
        return _cond('region', UNKNOWN, evidence='region=%s (해석 불가)' % value[:40])
    return _cond('region', KNOWN, value_text=','.join(names), evidence='region=%s' % value[:60])


def business_age_condition(notice):
    """업력. 개월 단위 최소/최대와 경계 포함 여부까지 남긴다.

    `gate.parse_enyy` 는 서비스가 쓰는 해석기다. 여기서 다시 만들지 않는다.
    'N년 미만' 은 **미만**이므로 상한을 포함하지 않는다(bound_note).
    """
    raw = (notice.get('age_condition_raw') or '').strip()
    if not raw:
        return _cond('business_age', UNKNOWN)
    if not gate.understood(raw):
        return _cond('business_age', UNKNOWN, evidence=raw[:120])
    pre_ok, cap = gate.parse_enyy(raw)
    if cap is None:
        # 예비창업자만 신청 가능한 공고
        return _cond('business_age', KNOWN, value_text='예비창업자만', value_min=None,
                     value_max=0, bound_note='prestartup_only', evidence=raw[:120])
    return _cond('business_age', KNOWN,
                 value_text='예비창업자 가능' if pre_ok else '사업자만',
                 value_min=None, value_max=int(cap),
                 bound_note='max_exclusive_months' + ('' if pre_ok else '_no_prestartup'),
                 evidence=raw[:120])


def period_condition(notice):
    """접수기간. 마감일이 없는 것이 정상인 형태(상시·예산 소진)를 unknown 과 구분한다."""
    end = notice.get('apply_end')
    kind = (notice.get('apply_period_type') or 'unknown').strip()
    if end:
        return _cond('application_period', KNOWN, value_text=str(end), bound_note=kind,
                     evidence='apply_start=%s apply_end=%s' % (notice.get('apply_start'), end))
    if kind in ('rolling', 'budget_exhaustion', 'until_filled'):
        return _cond('application_period', NO_LIMIT, value_text=kind, bound_note=kind,
                     evidence='apply_period_type=%s' % kind)
    return _cond('application_period', UNKNOWN, bound_note=kind)


def _words(notice):
    return ' '.join(str(notice.get(k) or '') for k in
                    ('target_category', 'target_text', 'title', 'category', 'subcategory'))


# ---------------------------------------------------------------- 자격 문구 읽기 (F1 수정)
#
# 2026-09-18 Codex 리뷰 F1. 예전에는 제목·분류까지 뒤져 단어가 보이면 제한으로 단정했다.
# 그래서 이런 일이 있었다.
#
#   "대기업과 함께하는 기술교류" + "기업 규모 제한 없이 모든 기업 신청 가능"  → 대기업 전용
#   "제조업을 영위하는 기업은 제외하며 그 외 업종은 모두 신청 가능"          → 제조업만 가능
#
# 둘 다 신청할 수 있는 사람을 떨어뜨린다. 그래서 세 가지를 지킨다.
#
#   ① **지원대상 칸만 본다.** 제목·사업 분류는 자격 문구가 아니다.
#   ② **부정·제외 문장에 나온 단어는 허용 목록에 넣지 않는다.** 남은 업종을 셀 수 없으면 unknown 이다.
#   ③ **제한 없음이 명시되면 no_limit 이다.** 값 없음(unknown)과 구분한다.
#
# 애매하면 unknown 으로 남긴다. 남기면 '확인 필요'가 되어 후보로 살아 있고, 사람이 확인하면 된다.
# 잘못 탈락시키는 것보다 낫다.

# 자격을 밝힌 칸. 제목·category 는 일부러 뺀다.
ELIGIBILITY_FIELDS = ('target_text', 'target_category')

# 이 말이 있으면 앞에 나온 단어는 **허용**이 아니다
NEGATION_HINTS = ('제외', '불가', '해당하지 않', '아닌 ', '아닙니다', '없는 기업', '미해당')

# 제한이 없다고 밝힌 문구. **어느 조건의 제한 없음인지 필드별로 따로 본다.**
#
# 처음에는 '제한 없'·'무관'·'누구나' 를 지원대상 어디서든 찾아 규모·업종 모두에 썼다.
# 그랬더니 "지역 제한 없음", "업력 무관", "연령제한 없음" 이 규모·업종의 제한 없음으로 새어 들어가
# "업종 제한 없이 중소기업만 신청 가능" 의 대기업 신청자까지 **충족**이 됐다
# (2026-09-21 Codex F1 리뷰 P1. 실제 공고 업종 no_limit 28건 대부분이 이 경우였다).
#
# 그래서 '제한 없음' 표현 바로 앞에 **그 필드의 이름**이 있을 때만 인정한다.
# '누구나'·'모든 기업' 처럼 어느 조건인지 모르는 말은 쓰지 않는다 → unknown 으로 남는다.
_FREE = r'(?:제한\s*(?:이\s*)?없|무관|관계\s*없|상관\s*없)'
# 맨 '규모' 는 '지원 규모 무관' 같은 금액 표현과 겹친다 → 기업 규모/형태만 인정한다
SIZE_NO_LIMIT_RE = re.compile(r'(?:기업\s*규모|기업\s*형태)[^\n.,;]{0,6}?' + _FREE)
INDUSTRY_NO_LIMIT_RE = re.compile(
    r'(?:업종|업태|산업군|산업\s*분야)[^\n.,;]{0,6}?' + _FREE + r'|전\s*업종')

# 문장을 자르는 기준. "A는 제외하며 B는 가능" 처럼 이어진 문장도 나눠서 본다.
# **가운뎃점(·)으로는 자르지 않는다.** "대기업·중견기업과 계약 실적" 을 쪼개면 뒤의 '계약' 을
# 놓쳐 대기업을 신청 자격으로 읽는다(실제 공고 kstartup:179258 에서 그랬다).
CLAUSE_SPLIT = re.compile(r'[.\n,;]|(?:하며|하고|이며)\s')

# 신청자가 아니라 **거래 상대**를 말하는 문장. 여기 나온 규모는 자격이 아니다.
PARTNER_HINTS = ('계약', '협력', '공동', '동반', '거래', '납품', '수요', '파트너', '연계',
                 '판로', '고객', '판매처', '거래처', '진출한')


def _eligibility_text(notice):
    return ' '.join(str(notice.get(k) or '') for k in ELIGIBILITY_FIELDS).strip()


def _no_limit_quote(text, pattern):
    """그 필드의 '제한 없음' 문구를 찾아 근거로 돌려준다. 없으면 None."""
    match = pattern.search(text)
    return match.group(0) if match else None


def _allowed_words(text, word_table, require_hints=None):
    """지원대상 문구에서 **허용 목록**만 고른다.

    반환은 (허용 집합, 허용으로 쓰지 못한 집합). 부정 문장이나 거래 상대를 말하는 문장에
    걸린 단어는 허용에 넣지 않는다. `require_hints` 를 주면 그 문장에 제한 표현이 있어야
    허용으로 인정한다(업종용).
    """
    allowed, negated, ambiguous = set(), set(), set()
    for clause in CLAUSE_SPLIT.split(text):
        clause = clause.strip()
        if not clause:
            continue
        found = {norm for word, norm in word_table if word in clause}
        if not found:
            continue
        if any(hint in clause for hint in NEGATION_HINTS):
            negated |= found          # "제조업은 제외" — 남은 업종을 셀 수 없다
            continue
        if any(hint in clause for hint in PARTNER_HINTS):
            ambiguous |= found        # "대기업과 계약 실적" — 신청자가 대기업이라는 뜻이 아니다
            continue
        if require_hints and not any(hint in clause for hint in require_hints):
            continue                  # 업종 이름만 스쳤을 뿐 제한 표현이 없다
        allowed |= found
    return allowed, (negated | ambiguous) - allowed


def company_size_condition(notice):
    """신청 가능한 기업 규모. **지원대상 칸에 분명히 적힌 것만** 인정한다(리뷰 F1)."""
    text = _eligibility_text(notice)
    if not text:
        return _cond('company_size', UNKNOWN)
    free = _no_limit_quote(text, SIZE_NO_LIMIT_RE)
    allowed, negated = _allowed_words(text, SIZE_WORDS)
    if free and allowed:
        # "기업 규모 제한 없음" 과 "중소기업만" 이 함께 있다 — 어느 쪽인지 단정하지 않는다
        return _cond('company_size', UNKNOWN,
                     evidence='제한 없음(%s)과 %s 이 함께 있음' % (free, ','.join(sorted(allowed))))
    if free:
        return _cond('company_size', NO_LIMIT, value_text='제한 없음', evidence=free)
    if not allowed:
        # 제외 문구만 있으면 '나머지 전부'를 목록으로 만들 수 없다 → 확인 필요로 남긴다
        return _cond('company_size', UNKNOWN, evidence=text[:120] if negated else None)

    # 지원대상 칸을 좁게 믿는 것도 위험하다. 실제 공고에 이런 것이 있었다.
    #   제목 "소상공인 경영안정자금" · target_category "중소기업"
    # 지원대상만 보면 중소기업 전용이 되어 **소상공인을 떨어뜨린다**. 제목이 다른 규모를 말하면
    # 그 목록이 전부라고 단정할 수 없으므로 unknown(확인 필요)으로 남긴다.
    # 지원대상에서 "대기업은 제외" 처럼 이미 정리된 말은 충돌이 아니다.
    elsewhere = ({norm for word, norm in SIZE_WORDS if word in _words(notice)}
                 - allowed - negated)
    if elsewhere:
        return _cond('company_size', UNKNOWN,
                     evidence='지원대상 %s · 다른 칸에 %s 언급'
                              % (text[:80], ','.join(sorted(elsewhere))))
    return _cond('company_size', KNOWN, value_text=','.join(sorted(allowed)),
                 evidence=text[:120])


def purpose_condition(notice):
    """지원 분야·목적. `category/subcategory` 는 **지원사업 분류**이지 신청 가능 업종이 아니다.

    처음에는 이 값을 업종으로 저장해 '업종 확보율 100%' 라고 보고했는데 잘못이었다
    (2026-09-18 Codex 리뷰 1번). 분야는 분야로 남기고, 업종은 따로 본다.
    """
    parts = [str(notice.get('category') or '').strip(), str(notice.get('subcategory') or '').strip()]
    parts = [p for p in parts if p]
    if not parts:
        return _cond('purpose', UNKNOWN)
    return _cond('purpose', KNOWN, value_text=' · '.join(parts), evidence='category/subcategory')


# 신청 가능 업종. **지원대상 문구에 업종이 못 박힌 경우만** 인정한다.
# '제조' 라는 말이 지나가듯 나온 것으로 업종 제한이라고 단정하지 않는다(리뷰 1번).
INDUSTRY_WORDS = (('제조업', '제조업'), ('서비스업', '서비스업'), ('도소매업', '도소매업'),
                  ('음식점업', '음식점업'), ('숙박업', '숙박업'), ('건설업', '건설업'),
                  ('농업', '농업'), ('어업', '어업'), ('축산업', '축산업'),
                  ('정보통신업', '정보통신업'), ('물류업', '물류업'), ('운수업', '운수업'))
INDUSTRY_LIMIT = ('만 신청', '에 한함', '한정', '영위하는', '업종만', '해당 업종')


def industry_condition(notice):
    """신청 가능 업종. 지원대상 문구에 업종 제한이 분명할 때만 known 이다.

    제한 표현이 있어도 그것이 **제외** 문장이면 허용 목록으로 쓰지 않는다(리뷰 F1).
    "제조업을 영위하는 기업은 제외" 를 "제조업만 가능" 으로 뒤집던 문제를 막는다.
    """
    text = _eligibility_text(notice)
    if not text:
        return _cond('industry', UNKNOWN)
    free = _no_limit_quote(text, INDUSTRY_NO_LIMIT_RE)
    allowed, negated = _allowed_words(text, INDUSTRY_WORDS, require_hints=INDUSTRY_LIMIT)
    if free and allowed:
        return _cond('industry', UNKNOWN,
                     evidence='제한 없음(%s)과 %s 이 함께 있음' % (free, ','.join(sorted(allowed))))
    if free:
        return _cond('industry', NO_LIMIT, value_text='제한 없음', evidence=free)
    if not allowed:
        # 업종 이름만 스쳤거나, 제외 문장뿐이다 → 단정하지 않는다
        has_word = any(word in text for word, _norm in INDUSTRY_WORDS)
        return _cond('industry', UNKNOWN,
                     evidence=text[:120] if (has_word or negated) else None)
    return _cond('industry', KNOWN, value_text=','.join(sorted(allowed)), evidence=text[:120])


def target_condition(notice):
    """대상 설명. 문자열이 다르다고 SQL 에서 떨어뜨리지 않는다 — 참고용 텍스트다."""
    text = (notice.get('target_text') or notice.get('target_category') or '').strip()
    if not text:
        return _cond('target', UNKNOWN)
    return _cond('target', KNOWN, value_text=text[:300], evidence='target_text/target_category')


def support_amount_condition(notice):
    """기업당 최대 지원금. 총사업비·예산 규모 표현이 섞인 문장은 쓰지 않는다."""
    body = str(notice.get('body') or '')
    for match in AMOUNT_RE.finditer(body):
        # 총액 표현인지 **앞쪽만** 본다. 뒤까지 보면 "기업당 최대 5천만원 … 총사업비 30억" 처럼
        # 뒤 문장의 총액 때문에 멀쩡한 값을 버린다(첫 시험에서 실제로 그랬다).
        start = max(0, match.start() - 30)
        before = body[start:match.start()]
        if any(hint in before for hint in TOTAL_HINTS):
            continue
        number = match.group(1).replace(',', '')
        try:
            value = float(number) * UNIT[match.group(2)]
        except (ValueError, KeyError):
            continue
        evidence = body[start:match.end()].strip()
        return _cond('support_amount', KNOWN, value_max=int(value), bound_note='krw_per_company',
                     value_text='%d원' % int(value), evidence=evidence[:120])
    return _cond('support_amount', UNKNOWN)


def support_type_condition(notice):
    text = _words(notice) + ' ' + str(notice.get('body') or '')[:2000]
    found = sorted({norm for word, norm in SUPPORT_TYPES if word in text})
    if not found:
        return _cond('support_type', UNKNOWN)
    return _cond('support_type', KNOWN, value_text=','.join(found), evidence='제목·분류·본문 앞부분')


def build(notice):
    """공고 하나 → 조건 목록."""
    return [region_condition(notice), business_age_condition(notice), period_condition(notice),
            company_size_condition(notice), purpose_condition(notice), industry_condition(notice),
            target_condition(notice), support_amount_condition(notice),
            support_type_condition(notice)]


FIELDS = ('region', 'business_age', 'application_period', 'company_size',
          'purpose', 'industry', 'target', 'support_amount', 'support_type')


def coverage(rows):
    """필드별 known/no_limit/unknown 비율. 확보율을 그대로 보고하기 위한 집계."""
    out = {}
    for field in FIELDS:
        counts = {KNOWN: 0, NO_LIMIT: 0, UNKNOWN: 0}
        for row in rows:
            if row['field'] == field:
                counts[row['status']] = counts.get(row['status'], 0) + 1
        total = sum(counts.values()) or 1
        out[field] = dict(counts, total=sum(counts.values()),
                          known_ratio=round((counts[KNOWN] + counts[NO_LIMIT]) / total, 3))
    return out
