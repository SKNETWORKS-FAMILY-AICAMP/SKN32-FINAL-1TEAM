# -*- coding: utf-8 -*-
"""신청자 정보를 검색에 쓰는 방법.

입력 항목이 늘었다(성별·업종·인증·채용계획·자기부담금 …). 그런데 **항목마다 쓰임이 다르다.**
아무 데나 다 넣으면 검색이 나빠지므로 세 갈래로 나눈다.

  1) 질의 문장에 넣는다     공고 본문에 대응하는 말이 있는 것 (업종·인증·채용계획)
                            → 의미 검색·단어 검색이 함께 본다
  2) 규칙에만 쓴다          공고가 한정한 집단과 맞춰 보는 것 (성별·재창업·인증)
                            → rank_rules 가 쓴다. 질의 문장은 건드리지 않는다
  3) 지금은 받아만 둔다     공고 데이터에 대응하는 칸이 없는 것
                            (이름·생년월일·사업자번호·자기부담금·예산 규모·장비)

3)을 "쓰지 않는다" 고 적어 두는 이유 — 화면에 입력칸이 있으면 반영되는 줄 알기 때문이다.
공고 쪽에 그 정보가 생기면 그때 1)이나 2)로 옮긴다.
"""
from datetime import date

# 공고 대상 조건에 자주 나오는 인증·확인서. 화면 선택지와 같다.
CERTIFICATIONS = ('여성기업', '장애인기업', '사회적기업', '예비사회적기업', '협동조합',
                  '소셜벤처', '벤처기업', '이노비즈', '메인비즈', '연구소기업', '기업부설연구소',
                  '수출기업', '가족친화기업', '청년친화강소기업')


def age(birth_date, today=None):
    """만 나이. 형식이 이상하면 None."""
    if not birth_date:
        return None
    try:
        born = date.fromisoformat(str(birth_date)[:10])
    except ValueError:
        return None
    today = today or date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def rule_words(req):
    """rank_rules 가 볼 신청자 근거 단어들.

    공고가 "여성기업 대상" 이면 지금까지는 신청자 입력에 '여성' 이라는 말이 없어서
    뒤로 밀렸다. 성별을 받으면 그 공고가 제자리를 지킨다.
    """
    words = []
    if (req.gender or '').strip() == '여성':
        words.append('여성')
    if req.first_startup is False:
        words.append('재창업 재도전')
    words.extend(c.strip() for c in (req.certifications or []) if c and c.strip())
    if (req.main_industry or '').strip():
        words.append(req.main_industry.strip())
    words.extend(p.strip() for p in (req.partners or []) if p and p.strip())
    return [w for w in words if w]


def query_extras(req):
    """질의 문장 뒤에 붙일 조각. 비어 있으면 예전과 완전히 같은 문장이 된다."""
    parts = []
    if (req.main_industry or '').strip():
        parts.append('업종: ' + req.main_industry.strip())
    certs = [c.strip() for c in (req.certifications or []) if c and c.strip()]
    if certs:
        parts.append('보유 인증: ' + ', '.join(certs))
    if req.hiring_plan:
        parts.append('고용 계획 있음')
    return parts


def stored_only(req):
    """받아는 두지만 지금 매칭에 쓰지 않는 항목. 화면에 그대로 보여 준다."""
    out = {}
    if (req.name or '').strip():
        out['이름'] = req.name.strip()
    years = age(req.birth_date)
    if years is not None:
        out['만 나이'] = '%d세' % years
    if (req.business_no or '').strip():
        out['사업자등록번호'] = '입력함'          # 값은 돌려주지 않는다
    if req.budget_scale:
        out['예산 규모'] = '%s만원' % req.budget_scale
    if req.self_funding is not None:
        out['자기부담금'] = ('가능 %s만원' % req.self_funding_budget) if req.self_funding_budget \
            else ('가능' if req.self_funding else '어려움')
    equipment = [e.strip() for e in (req.equipment or []) if e and e.strip()]
    if equipment:
        out['보유 장비'] = ', '.join(equipment)
    return out


def why_not_used():
    """왜 못 쓰는지 한 줄씩. 화면에서 그대로 보여 준다."""
    return {
        '이름': '공고 데이터에 대응하는 칸이 없다',
        '만 나이': '공고의 나이 조건(청년·중장년)이 칸으로 정리돼 있지 않다',
        '사업자등록번호': '국세청 API 를 붙이면 설립일 검증·폐업 확인에 쓴다',
        '예산 규모': '공고에 지원금액 칸이 없다',
        '자기부담금': '공고에 자기부담 비율 칸이 없다',
        '보유 장비': '공고 본문에만 있어 아직 칸으로 뽑지 않았다',
    }
