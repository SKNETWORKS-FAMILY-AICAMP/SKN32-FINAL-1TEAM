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
