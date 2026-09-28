# -*- coding: utf-8 -*-
"""/compare 신청자 입력 계약 — 검증, 방식별 변환, 사용 여부 표.

지시서: docs/COMPARE_INPUT_EXPANSION_TASK_20260921.md

세 가지를 한곳에서 정한다.

  1) 무엇이 필수·선택·조건부 필수인가 (validate)
  2) 각 검색 방식에 **무엇을 넘기는가** (service_payload · lab_applicant)
  3) 넘긴 값이 그 방식에서 **실제로 쓰이는가** (field_usage) — 받았다고 쓰는 척하지 않는다

사용자 결정(2026-09-21)
  · 설립일은 개인사업자·법인만 필수. 예비창업자는 받지 않는다(업력 판정에 쓰므로 뺄 수 없다).
  · 성별은 여성 / 남성 / 응답 안 함 중 하나를 반드시 고른다. '응답 안 함' 은 성별 규칙을 적용하지 않는다.

개인정보(이름·생년월일·사업자등록번호)
  · 오류 메시지에 **값을 넣지 않는다.** 칸 이름과 이유만 돌려준다.
  · 응답에 되돌려주지 않는다(input_summary 에는 개인정보가 없다).
  · 기존 서비스(8000)에는 같은 요청을 보낸다 — 서비스는 이 값을 검색에 쓰지 않고 저장하지 않는다.
    다만 서비스가 돌려주는 stored_only(이름 포함)는 /compare 응답으로 넘기지 않는다.
"""
import os
import re
import sys
from datetime import date
from typing import Any, Optional, Union

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from pydantic import BaseModel, ConfigDict, ValidationError  # noqa: E402

from experiments.sql_semantic import conditions  # noqa: E402
from search import applicant as applicant_mod  # noqa: E402
from shared import region as region_mod  # noqa: E402

APPLICANT_TYPES = ('예비창업자', '개인사업자', '법인')
BUSINESS_TYPES = ('개인사업자', '법인')
GENDERS = ('여성', '남성', '응답 안 함')
CERTIFICATIONS = tuple(applicant_mod.CERTIFICATIONS)

# 한 칸의 최대 길이. 너무 긴 입력을 서비스로 그대로 넘기지 않는다
MAX_LEN = {'owner_name': 50, 'main_industry': 50, 'owner_career': 1000, 'idea': 2000,
           'district': 30, 'item': 100, 'team_text': 500, 'list_item': 100}
MAX_LIST = 20
MAX_AMOUNT = 10 ** 12        # 금액 상한(원·만원 공통) — 자릿수 실수 방지

# 필드 이름 → 화면 이름. 오류 메시지와 사용 여부 표에서 같은 이름을 쓴다
LABEL = {
    'applicant_type': '신청자 유형', 'owner_name': '이름', 'birth_date': '생년월일',
    'gender': '성별', 'region': '지역(시·도)', 'district': '시·군·구', 'main_industry': '주 업종',
    'business_no': '사업자등록번호', 'founded_at': '설립일', 'owner_career': '대표자 이력',
    'revenue': '수익모델 단가', 'idea': '아이디어 설명', 'certifications': '보유 인증·확인서',
    'budget_scale': '희망 사업 규모', 'self_funding': '자기부담금', 'team': '팀 구성원',
    'hiring_plan': '채용 계획', 'equipment': '보유 장비', 'partners': '협력기관', 'top': '몇 개씩',
}


class TeamRow(BaseModel):
    model_config = ConfigDict(extra='ignore')
    name: str = ''
    role: str = ''
    career: str = ''


class RevenueRow(BaseModel):
    model_config = ConfigDict(extra='ignore')
    item: str = ''
    price: Union[str, int, float, None] = None


class CompareInput(BaseModel):
    """/api/compare 요청 모양. 타입만 여기서 맞추고, 필수·조건 검사는 validate() 가 한다.

    Pydantic 의 기본 오류는 입력값을 되돌려주므로(개인정보가 섞일 수 있다) 그대로 쓰지 않는다.
    """
    model_config = ConfigDict(extra='ignore')
    applicant_type: str = ''
    owner_name: str = ''
    birth_date: str = ''
    gender: str = ''
    region: str = ''
    district: str = ''
    main_industry: str = ''
    business_no: str = ''
    founded_at: str = ''
    owner_career: str = ''
    revenue: list[RevenueRow] = []
    idea: str = ''
    certifications: list[str] = []
    budget_scale: Union[int, str, None] = None
    self_funding: Optional[bool] = None
    self_funding_budget: Union[int, str, None] = None
    team: list[TeamRow] = []
    hiring_plan: bool = False
    equipment: list[str] = []
    partners: list[str] = []
    top: Any = None


# ─────────────────────────────────────────────────────────── 작은 도우미

DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def _date(text):
    """정확히 YYYY-MM-DD 만 받는다. 뒤에 글자가 붙으면 거부한다.

    처음에는 앞 10자만 잘라 읽어 '1980-01-01garbage' 도 통과했다(2026-09-21 Codex 리뷰 P2).
    """
    text = str(text or '').strip()
    if not DATE_RE.match(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _amount(value):
    """'12,000' · 12000 → 12000. 음수·소수·문자는 None."""
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value >= 0 else None
    if isinstance(value, int):
        return value if value >= 0 else None
    text = str(value).replace(',', '').strip()
    return int(text) if text.isdigit() else None


def _clean_list(values):
    return [v.strip() for v in (values or []) if isinstance(v, str) and v.strip()]


def normalize_industry(text):
    """자유 입력 업종 → 새 방식의 업종 어휘(conditions.INDUSTRY_WORDS). 못 바꾸면 ''.

    '제조업' 은 그대로, '제조' 처럼 '업' 이 빠진 말은 붙여 본다. 그래도 어휘에 없으면 새 방식에는
    넘기지 않는다 — 어휘에 없는 값을 넘기면 공고의 업종 목록과 글자가 달라 잘못 '불충족' 이 날 수 있다.
    """
    text = (text or '').strip()
    if not text:
        return ''
    for word, norm in conditions.INDUSTRY_WORDS:
        if word in text or (text + '업') == word:
            return norm
    return ''


# ─────────────────────────────────────────────────────────── 검증

def validate(body, today=None):
    """(정리된 입력 dict, 오류 목록). 오류가 하나라도 있으면 검색하지 않는다.

    오류는 {'field': 칸, 'message': 이유} 이며 **입력값을 담지 않는다.**
    조건부 칸은 신청자 유형에 맞게 지운다 — 숨긴 칸의 이전 값이 남지 않게.
    """
    today = today or date.today()
    errors = []

    def err(field, message):
        errors.append({'field': field, 'label': LABEL.get(field.split('[')[0], field),
                       'message': message})

    try:
        raw = CompareInput.model_validate(body if isinstance(body, dict) else {})
    except ValidationError as exc:
        # 타입이 틀린 칸만 알린다. exc.errors() 의 'input' 은 버린다
        for e in exc.errors():
            loc = '.'.join(str(x) for x in e.get('loc', ()))
            err(loc or 'body', '형식이 맞지 않는다')
        return None, errors

    clean = {}

    # 신청자 유형
    kind = raw.applicant_type.strip()
    if kind not in APPLICANT_TYPES:
        err('applicant_type', '예비창업자·개인사업자·법인 중 하나를 고른다')
    clean['applicant_type'] = kind
    is_business = kind in BUSINESS_TYPES

    # 대표자 기본 정보
    name = raw.owner_name.strip()
    if not name:
        err('owner_name', '이름을 입력한다')
    elif len(name) > MAX_LEN['owner_name']:
        err('owner_name', '%d자 이내로 입력한다' % MAX_LEN['owner_name'])
    clean['owner_name'] = name

    birth = _date(raw.birth_date) if raw.birth_date.strip() else None
    if not raw.birth_date.strip():
        err('birth_date', '생년월일을 입력한다')
    elif birth is None:
        err('birth_date', '날짜 형식(YYYY-MM-DD)이 아니다')
    elif birth > today:
        err('birth_date', '미래 날짜는 입력할 수 없다')
    elif birth.year < 1900:
        err('birth_date', '1900년 이후 날짜를 입력한다')
    clean['birth_date'] = birth.isoformat() if birth else ''

    gender = raw.gender.strip()
    if gender not in GENDERS:
        err('gender', '여성·남성·응답 안 함 중 하나를 고른다')
    clean['gender'] = gender

    # 사업 정보
    region = raw.region.strip()
    if not region:
        err('region', '시·도를 고른다')
    elif region not in region_mod.REGIONS:
        err('region', '목록에 있는 시·도를 고른다')
    clean['region'] = region
    district = raw.district.strip()
    if district and region in region_mod.REGIONS and district not in region_mod.districts_of(region):
        err('district', '고른 시·도의 시·군·구가 아니다')
    clean['district'] = district

    industry = raw.main_industry.strip()
    if not industry:
        err('main_industry', '주 업종을 입력한다')
    elif len(industry) > MAX_LEN['main_industry']:
        err('main_industry', '%d자 이내로 입력한다' % MAX_LEN['main_industry'])
    clean['main_industry'] = industry

    dropped = []                         # 유형 때문에 지운 칸 (이름만 남긴다)
    if is_business:
        digits = re.sub(r'[\s-]', '', raw.business_no or '')
        if not digits:
            err('business_no', '개인사업자·법인은 사업자등록번호를 입력한다')
        elif not (digits.isdigit() and len(digits) == 10):
            err('business_no', '숫자 10자리로 입력한다')
        clean['business_no'] = digits if (digits.isdigit() and len(digits) == 10) else ''

        founded = _date(raw.founded_at) if raw.founded_at.strip() else None
        if not raw.founded_at.strip():
            err('founded_at', '개인사업자·법인은 설립일을 입력한다')
        elif founded is None:
            err('founded_at', '날짜 형식(YYYY-MM-DD)이 아니다')
        elif founded > today:
            err('founded_at', '미래 날짜는 입력할 수 없다')
        elif founded.year < 1900:
            err('founded_at', '1900년 이후 날짜를 입력한다')
        clean['founded_at'] = founded.isoformat() if founded else ''
    else:
        # 예비창업자 — 사업자 칸은 받지 않는다. 이전 값이 와도 지운다
        for field in ('business_no', 'founded_at'):
            if (getattr(raw, field) or '').strip():
                dropped.append(field)
        clean['business_no'] = ''
        clean['founded_at'] = ''

    # 대표자 이력
    career = raw.owner_career.strip()
    if not career:
        err('owner_career', '대표자 이력을 입력한다')
    elif len(career) > MAX_LEN['owner_career']:
        err('owner_career', '%d자 이내로 입력한다' % MAX_LEN['owner_career'])
    clean['owner_career'] = career

    # 수익모델 — 완성된 행 1개 이상. 반쯤 채운 행은 오류
    # 행 수 상한을 **자르기 전에** 검사한다. 처음에는 21번째부터 조용히 버렸다(Codex 리뷰 P2)
    if len(raw.revenue) > MAX_LIST:
        err('revenue', '수익모델은 %d개까지 입력한다' % MAX_LIST)
    if len(raw.team) > MAX_LIST:
        err('team', '팀 구성원은 %d명까지 입력한다' % MAX_LIST)

    revenue = []
    for i, row in enumerate(raw.revenue[:MAX_LIST]):
        item = (row.item or '').strip()
        price_given = row.price not in (None, '')
        if not item and not price_given:
            continue                                  # 완전히 빈 행은 버린다
        if not item:
            err('revenue[%d].item' % i, '항목 이름을 입력한다')
            continue
        if len(item) > MAX_LEN['item']:
            err('revenue[%d].item' % i, '%d자 이내로 입력한다' % MAX_LEN['item'])
            continue
        price = _amount(row.price)
        if not price_given:
            err('revenue[%d].price' % i, '단가를 입력한다')
            continue
        if price is None or price > MAX_AMOUNT:
            err('revenue[%d].price' % i, '0 이상의 정수 금액으로 입력한다')
            continue
        revenue.append({'item': item, 'price': price})
    if not revenue and not any(e['field'].startswith('revenue') for e in errors):
        err('revenue', '수익모델 항목과 단가를 1개 이상 입력한다')
    clean['revenue'] = revenue

    idea = raw.idea.strip()
    if not idea:
        err('idea', '아이디어 설명을 입력한다')
    elif len(idea) > MAX_LEN['idea']:
        err('idea', '%d자 이내로 입력한다' % MAX_LEN['idea'])
    clean['idea'] = idea

    # 선택 항목
    certs = _clean_list(raw.certifications)
    unknown = [c for c in certs if c not in CERTIFICATIONS]
    if unknown:
        err('certifications', '목록에 있는 인증만 고른다')
    clean['certifications'] = [c for c in certs if c in CERTIFICATIONS]

    if kind == '예비창업자':
        budget = _amount(raw.budget_scale)
        if raw.budget_scale not in (None, '') and (budget is None or budget > MAX_AMOUNT):
            err('budget_scale', '0 이상의 정수 금액(만원)으로 입력한다')
        clean['budget_scale'] = budget
        for field in ('self_funding', 'self_funding_budget'):
            if getattr(raw, field) not in (None, ''):
                dropped.append(field)
        clean['self_funding'] = None
        clean['self_funding_budget'] = None
    else:
        if raw.budget_scale not in (None, ''):
            dropped.append('budget_scale')
        clean['budget_scale'] = None
        clean['self_funding'] = raw.self_funding
        fund = _amount(raw.self_funding_budget)
        if raw.self_funding_budget not in (None, ''):
            if raw.self_funding is not True:
                dropped.append('self_funding_budget')    # '가능'이 아니면 가능액은 의미가 없다
                fund = None
            elif fund is None or fund > MAX_AMOUNT:
                err('self_funding_budget', '0 이상의 정수 금액(만원)으로 입력한다')
        clean['self_funding_budget'] = fund if raw.self_funding is True else None

    team = []
    for i, row in enumerate(raw.team[:MAX_LIST]):
        name_, role_, career_ = (row.name or '').strip(), (row.role or '').strip(), (row.career or '').strip()
        if not (name_ or role_ or career_):
            continue
        if not career_:
            err('team[%d].career' % i, '팀원 이력을 입력하거나 행을 지운다')
            continue
        if max(len(name_), len(role_), len(career_)) > MAX_LEN['team_text']:
            err('team[%d]' % i, '%d자 이내로 입력한다' % MAX_LEN['team_text'])
            continue
        team.append({'name': name_, 'role': role_, 'career': career_})
    clean['team'] = team

    clean['hiring_plan'] = bool(raw.hiring_plan)
    for field in ('equipment', 'partners'):
        values = _clean_list(getattr(raw, field))
        if len(values) > MAX_LIST or any(len(v) > MAX_LEN['list_item'] for v in values):
            err(field, '%d개 이내, 항목마다 %d자 이내로 입력한다' % (MAX_LIST, MAX_LEN['list_item']))
        clean[field] = values[:MAX_LIST]

    clean['dropped_for_type'] = sorted(set(dropped))
    return (None if errors else clean), errors


# ─────────────────────────────────────────────────────────── 방식별 변환

def service_payload(clean, top):
    """기존 서비스(8000) /api/match 요청. hybrid·dense 에 **똑같이** 보낸다(search 만 다르다).

    대표자 이력은 서비스에 칸이 없어 **팀 첫 행(대표)** 으로 넣는다 — 서비스는 팀 경력을 검색어에 붙인다.
    대표 행에는 이름을 넣지 않는다(검색에 쓰이지 않는 개인정보를 여러 칸에 퍼뜨리지 않는다).
    선택 팀원 중 대표 이력과 글자가 같은 행은 한 번만 넣는다.
    """
    rep = {'name': '', 'role': '대표', 'career': clean['owner_career']}
    team = [rep] + [m for m in clean['team'] if m['career'] != clean['owner_career']]
    return {
        'applicant_type': clean['applicant_type'],
        'owner_name': clean['owner_name'], 'name': clean['owner_name'],
        'birth_date': clean['birth_date'],
        # 서비스 규칙은 '여성' 일 때만 쓴다. '응답 안 함' 은 빈 값으로 보내 규칙을 적용하지 않는다
        'gender': '' if clean['gender'] == '응답 안 함' else clean['gender'],
        'region': clean['region'], 'district': clean['district'],
        'main_industry': clean['main_industry'],
        'business_no': clean['business_no'], 'founded_at': clean['founded_at'],
        'team': team,
        'revenue': [{'item': r['item'], 'price': str(r['price'])} for r in clean['revenue']],
        'idea': clean['idea'],
        'certifications': list(clean['certifications']),
        'hiring_plan': clean['hiring_plan'],
        'equipment': list(clean['equipment']), 'partners': list(clean['partners']),
        'budget_scale': clean['budget_scale'],
        'self_funding': clean['self_funding'],
        'self_funding_budget': clean['self_funding_budget'],
        'top': top,
    }


def lab_applicant(clean):
    """새 방식(search.run)이 **실제로 읽는 칸만** 넘긴다. (applicant, 업종 변환 결과)."""
    industry = normalize_industry(clean['main_industry'])
    # 시·군·구는 새 방식이 판정에 쓰지 않아 넘기지 않는다(Codex 리뷰 P3 — '실제로 읽는 칸만')
    return ({
        'idea': clean['idea'],
        'region': clean['region'],
        'founded_at': clean['founded_at'],
        'prestartup': clean['applicant_type'] == '예비창업자',
        'industry': industry,
        'preferred_support_type': '',
    }, industry)


def input_summary(clean):
    """응답에 되돌려줄 입력 요약. **개인정보(이름·생년월일·사업자번호)는 넣지 않는다.**"""
    return {'applicant_type': clean['applicant_type'], 'region': clean['region'],
            'district': clean['district'], 'main_industry': clean['main_industry'],
            'dropped_for_type': list(clean['dropped_for_type'])}


# ─────────────────────────────────────────────────────────── 사용 여부 표

SEARCH, RULE, JUDGE, ONLY, UNUSED, EMPTY = '검색어', '규칙', '조건 판정', '입력만 받음', '미사용', '입력 없음'


def field_usage(clean, lab_industry):
    """칸마다 '기존 서비스에서 / 새 방식에서' 어떻게 쓰였는지. 받았다고 쓰는 척하지 않는다.

    근거: 서비스는 search/app.py build_query·rank_rules·search/applicant.py,
          새 방식은 experiments/sql_semantic/search.py (지역·업력·접수기간·규모·업종 판정, 검색어는 아이디어만).
    """
    has = {
        'applicant_type': True, 'owner_name': True, 'birth_date': True, 'gender': True,
        'region': True, 'main_industry': True, 'owner_career': True, 'idea': True, 'revenue': True,
        'district': bool(clean['district']), 'business_no': bool(clean['business_no']),
        'founded_at': bool(clean['founded_at']), 'certifications': bool(clean['certifications']),
        'budget_scale': clean['budget_scale'] is not None,
        'self_funding': clean['self_funding'] is not None, 'team': bool(clean['team']),
        'hiring_plan': True, 'equipment': bool(clean['equipment']),
        'partners': bool(clean['partners']),
    }
    women = clean['gender'] == '여성'
    rows = [
        ('applicant_type', SEARCH + ' (예비창업자 / 창업 N년차)', JUDGE + ' (예비창업 여부)'),
        ('owner_name', ONLY, UNUSED),
        ('birth_date', ONLY, UNUSED),
        ('gender', (RULE + ' (여성 대상 공고 유지)') if women else (RULE + ' 해당 없음 (여성일 때만 씀)'),
         UNUSED),
        ('region', RULE + ' (다른 지역 전용 공고 뒤로)', JUDGE + ' (SQL 제외 + 지역 판정)'),
        ('district', RULE + ' (다른 시·군·구 공고 뒤로)', UNUSED),
        ('main_industry', SEARCH + ' + ' + RULE,
         (JUDGE + ' (업종 "%s")' % lab_industry) if lab_industry
         else UNUSED + ' (새 방식 업종 어휘로 바꾸지 못함)'),
        ('business_no', ONLY, UNUSED),
        ('founded_at', SEARCH + ' (창업 N년차)', JUDGE + ' (업력)'),
        ('owner_career', SEARCH + ' (팀 경력의 대표 행)', UNUSED),
        ('revenue', SEARCH + ' (항목 이름) · 단가는 ' + ONLY, UNUSED),
        ('idea', SEARCH, SEARCH),
        ('certifications', SEARCH + ' + ' + RULE, UNUSED),
        ('budget_scale', ONLY, UNUSED),
        ('self_funding', ONLY, UNUSED),
        ('team', SEARCH + ' (팀 경력)', UNUSED),
        ('hiring_plan', (SEARCH + ' (고용 계획 있음)') if clean['hiring_plan'] else (SEARCH + ' 해당 없음 (있을 때만 씀)'),
         UNUSED),
        ('equipment', ONLY, UNUSED),
        ('partners', RULE, UNUSED),
    ]
    out = []
    for field, service, lab in rows:
        given = has[field]
        out.append({'field': field, 'label': LABEL[field], 'given': given,
                    'service': service if given else EMPTY, 'lab': lab if given else EMPTY})
    return out
