# -*- coding: utf-8 -*-
"""지역 정규화 — 두 출처의 지역 표기를 하나의 어휘로 맞춘다.

  K-Startup   supt_regin 칸에 이미 들어온다 ('전국', '서울', '전남광주' ...)
  기업마당     지역 칸이 없다. hashtags 에 업종·키워드와 섞여 들어온다
              예) "경영,기타,서울,부산,...,제주,납부지연가산세,영세개인사업자"

어휘는 K-Startup 이 쓰는 값을 그대로 따른다(16개 + 전국). 광주와 전남은 통합되어
`전남광주` 하나다 — 두 출처 모두 이 표기를 쓴다. 기업마당의 옛 공고에는 '광주',
'전남' 이 따로 남아 있어 둘 다 `전남광주` 로 모은다.

**임베딩 입력(embed.FIELDS)에는 넣지 않는다.** 지역은 "비슷한가"가 아니라
"맞나 아닌가"로 잘라야 하는 조건이라 거르는 데만 쓴다. 넣으면 공고 2,198건을
다시 임베딩해야 하고 평가 수치도 전부 다시 계산된다.

여러 지역을 대상으로 하는 공고가 있다(예: "[경북ㆍ대구]"). 쉼표로 이어 둔다.
"""
import re

# 표준 어휘. 순서는 이 목록을 따른다
REGIONS = ('서울', '부산', '대구', '인천', '대전', '울산', '세종', '경기',
           '강원', '충북', '충남', '전북', '전남광주', '경북', '경남', '제주')
NATIONWIDE = '전국'

# 표기 흔들림 → 표준 어휘
ALIASES = {
    '서울특별시': '서울', '부산광역시': '부산', '대구광역시': '대구',
    '인천광역시': '인천', '대전광역시': '대전', '울산광역시': '울산',
    '세종특별자치시': '세종', '세종특별시': '세종',
    '경기도': '경기', '강원특별자치도': '강원', '강원도': '강원',
    '충청북도': '충북', '충청남도': '충남',
    '전북특별자치도': '전북', '전라북도': '전북',
    '전남광주통합특별시': '전남광주', '전라남도': '전남광주',
    '광주': '전남광주', '광주광역시': '전남광주', '전남': '전남광주',
    '경상북도': '경북', '경상남도': '경남',
    '제주특별자치도': '제주', '제주도': '제주',
}


def canonical(word):
    """태그 한 개 → 표준 어휘. 지역이 아니면 None."""
    w = (word or '').strip()
    if not w:
        return None
    if w == NATIONWIDE:
        return NATIONWIDE
    w = ALIASES.get(w, w)
    return w if w in REGIONS else None


def join(found):
    """지역 집합 → 저장 문자열. 16개를 모두 나열한 공고는 '전국' 으로 줄인다."""
    found = {r for r in found if r}
    if not found:
        return None
    if NATIONWIDE in found or len(found - {NATIONWIDE}) >= len(REGIONS):
        return NATIONWIDE
    return ','.join(r for r in REGIONS if r in found)


def from_tags(hashtags):
    """기업마당 hashtags 문자열 → 지역 문자열. 지역 태그가 없으면 None."""
    words = (hashtags or '').split(',')
    return join(canonical(w) for w in words)


# 제목 맨 앞 대괄호. 예) "[경북] ...", "[부산ㆍ울산ㆍ경남] ..."
_HEAD = re.compile(r'^\s*[\[(]([^\]\)]{1,30})[\])]')


def from_title(title):
    """제목 앞머리의 지역 표기 → 지역 문자열. 없으면 None.

    기업마당 태그가 빠뜨린 지역을 메운다(실측 1,272건 중 1건). 지역이 아닌
    말머리("[국비지원]", "[비수도권]")는 canonical 이 걸러낸다.
    """
    m = _HEAD.match(title or '')
    if not m:
        return None
    return join(canonical(w) for w in re.split(r'[ㆍ,·/]|\s+', m.group(1)))


def merge(*values):
    """여러 출처의 지역 문자열을 합친다. 하나라도 '전국' 이면 전국이다."""
    found = set()
    for v in values:
        for w in (v or '').split(','):
            c = canonical(w)
            if c:
                found.add(c)
    return join(found)


def normalize(value):
    """K-Startup supt_regin 등 이미 지역인 값 → 표준 표기. 쉼표 여러 개도 받는다."""
    if not value:
        return None
    return join(canonical(w) for w in str(value).split(','))


def matches(notice_region, applicant_region):
    """신청자 지역이 이 공고의 대상에 드는가.

    True   대상 지역이다 (전국 포함)
    False  다른 지역 전용이다
    None   공고에 지역 정보가 없거나 신청자가 지역을 고르지 않았다 — 판단하지 않는다

    `None` 을 False 로 바꾸지 않는다. 모른다고 뒤로 보내면 지역을 못 뽑은 공고가
    통째로 밀린다. gate.py 의 3값 판정과 같은 태도다.
    """
    if not notice_region or not applicant_region:
        return None
    mine = canonical(applicant_region)
    if mine is None:
        return None
    targets = {w.strip() for w in notice_region.split(',')}
    if NATIONWIDE in targets:
        return True
    return mine in targets


def demote(items, applicant_region, key=lambda x: x):
    """(앞으로 둘 것, 뒤로 보낸 것). 다른 지역 전용 공고만 뒤로 보낸다.

    key(item) 는 공고의 지역 문자열을 돌려줘야 한다. 각 묶음 안의 순서는 유지한다.
    판단 불가(None)는 뒤로 보내지 않는다. 서비스(app.py)와 평가(eval/region_eval.py)가
    이 함수를 같이 쓴다.
    """
    keep, moved = [], []
    for item in items:
        (moved if matches(key(item), applicant_region) is False else keep).append(item)
    return keep, moved


# ── 시·군·구 ────────────────────────────────────────────────
# 공고 지역 칸은 시·도 까지만 있다. 그런데 제목에는 "[전북] 무주군 ..." 처럼 시·군·구가
# 적힌 경우가 많다(실측 2,285건 중 601건, 26%). 그래서 시·군·구는 **제목에서 찾는다.**
# '연구', '특구' 같은 오탐을 막으려고 표준 행정구역 이름만 인정한다.
DISTRICTS = {
    '서울': ('종로구', '중구', '용산구', '성동구', '광진구', '동대문구', '중랑구', '성북구',
             '강북구', '도봉구', '노원구', '은평구', '서대문구', '마포구', '양천구', '강서구',
             '구로구', '금천구', '영등포구', '동작구', '관악구', '서초구', '강남구', '송파구', '강동구'),
    '부산': ('중구', '서구', '동구', '영도구', '부산진구', '동래구', '남구', '북구', '해운대구',
             '사하구', '금정구', '강서구', '연제구', '수영구', '사상구', '기장군'),
    '대구': ('중구', '동구', '서구', '남구', '북구', '수성구', '달서구', '달성군', '군위군'),
    '인천': ('중구', '동구', '미추홀구', '연수구', '남동구', '부평구', '계양구', '서구', '강화군', '옹진군'),
    '대전': ('동구', '중구', '서구', '유성구', '대덕구'),
    '울산': ('중구', '남구', '동구', '북구', '울주군'),
    '세종': (),
    '경기': ('수원시', '성남시', '의정부시', '안양시', '부천시', '광명시', '평택시', '동두천시',
             '안산시', '고양시', '과천시', '구리시', '남양주시', '오산시', '시흥시', '군포시',
             '의왕시', '하남시', '용인시', '파주시', '이천시', '안성시', '김포시', '화성시',
             '광주시', '양주시', '포천시', '여주시', '연천군', '가평군', '양평군'),
    '강원': ('춘천시', '원주시', '강릉시', '동해시', '태백시', '속초시', '삼척시', '홍천군',
             '횡성군', '영월군', '평창군', '정선군', '철원군', '화천군', '양구군', '인제군',
             '고성군', '양양군'),
    '충북': ('청주시', '충주시', '제천시', '보은군', '옥천군', '영동군', '증평군', '진천군',
             '괴산군', '음성군', '단양군'),
    '충남': ('천안시', '공주시', '보령시', '아산시', '서산시', '논산시', '계룡시', '당진시',
             '금산군', '부여군', '서천군', '청양군', '홍성군', '예산군', '태안군'),
    '전북': ('전주시', '군산시', '익산시', '정읍시', '남원시', '김제시', '완주군', '진안군',
             '무주군', '장수군', '임실군', '순창군', '고창군', '부안군'),
    # 광주와 전남이 통합되어 자치구와 시·군이 한 목록이다
    '전남광주': ('동구', '서구', '남구', '북구', '광산구',
                 '목포시', '여수시', '순천시', '나주시', '광양시', '담양군', '곡성군', '구례군',
                 '고흥군', '보성군', '화순군', '장흥군', '강진군', '해남군', '영암군', '무안군',
                 '함평군', '영광군', '장성군', '완도군', '진도군', '신안군'),
    '경북': ('포항시', '경주시', '김천시', '안동시', '구미시', '영주시', '영천시', '상주시',
             '문경시', '경산시', '의성군', '청송군', '영양군', '영덕군', '청도군', '고령군',
             '성주군', '칠곡군', '예천군', '봉화군', '울진군', '울릉군'),
    '경남': ('창원시', '진주시', '통영시', '사천시', '김해시', '밀양시', '거제시', '양산시',
             '의령군', '함안군', '창녕군', '고성군', '남해군', '하동군', '산청군', '함양군',
             '거창군', '합천군'),
    '제주': ('제주시', '서귀포시'),
}


def districts_of(sido):
    """그 시·도의 시·군·구 목록. 화면 선택 상자를 채우는 데 쓴다."""
    return DISTRICTS.get(canonical(sido) or '', ())


def districts_in_title(title, sido=None):
    """공고 제목에 적힌 시·군·구. 시·도를 주면 그 안의 이름만 본다.

    '특례시'(용인특례시)처럼 뒤에 말이 붙는 경우가 있어 '용인시' 를 '용인특례시' 에서도
    찾도록 시·군 이름의 앞부분으로 맞춘다.
    """
    text = title or ''
    names = DISTRICTS.get(canonical(sido) or '', ()) if sido else \
        tuple({d for ds in DISTRICTS.values() for d in ds})
    found = set()
    for name in names:
        if name in text or (name[-1] == '시' and (name[:-1] + '특례시') in text):
            found.add(name)
    return found


def district_matches(title, notice_region, my_sido, my_district):
    """제목에 특정 시·군·구가 적힌 공고인가, 그게 내 시·군·구인가.

    True   내 시·군·구가 적혀 있다
    False  다른 시·군·구만 적혀 있다 (같은 시·도 안에서)
    None   제목에 시·군·구가 없거나, 내가 고르지 않았거나, 시·도부터 다르다
    """
    if not my_district or not my_sido:
        return None
    if matches(notice_region, my_sido) is not True:
        return None                     # 시·도 판단이 먼저다
    found = districts_in_title(title, my_sido)
    if not found:
        return None
    return my_district in found
