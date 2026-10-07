# -*- coding: utf-8 -*-
"""신청자별 가산점 — 공고 가점(notice_bonus, collect/extract_bonus.py)을 신청자 정보와 맞춘다 (2026-10-06, 03_bonus 3-3).

조율 요청서 3.2
  bonus_score   이 신청자가 그 공고에서 받을 수 있는 가산점 합계. 해당 가점이 없으면 0, 계산하지 못하면 null
  bonus_items   항목별 근거 [{'name', 'points'}]. **합계와 맞아야 한다**. 계산하지 못하면 []

항목마다 신청자에게 True(해당) · False(해당 아님) · None(모름)을 매긴다(gate 의 3값과 같은 태도 — 모르면 단정하지 않는다).
  여성     '여성기업'을 요구하면 인증과 대조. 글에 '대표'가 있으면 성별과 대조. 그 밖(여성연구자 비율 등)은 None
  장애인   '장애인기업' 인증을 요구하는 항목만 인증과 대조. 그 밖(장애인표준사업장·장애인 대표·고용)은 None
  인증     항목 인증이 우리 인증 목록(applicant.CERTIFICATIONS)에 있으면 신청자 목록과 대조. 목록 밖 인증은 None
  지역     항목 시·도와 신청자 시·도 대조(글에 그 지역·'도내·관내'가 적힌 항목만). 글에 시·군·구 이름이 있으면 시·군·구까지 본다.
           글에 인증·연구소 조건이 함께 있으면("서울 소재 기업부설연구소") 그 조건이 신청자 인증 목록에 없을 때 None
  청년     생년월일과 항목의 "만 N세 이하·미만" 대조. 생년월일·나이 조건이 없으면 None
  재창업   첫 창업 여부(first_startup) — 거짓이면 True, 참이면 False, 없으면 None
  그 밖    고용·수출·특허·이전실적·업종·기타 — 입력이 없어 None
신청자의 인증 목록은 화면에서 고른 것이라 **고르지 않은 인증은 없다**고 본다.
항목에 추가 조건(extra_conditions — "최근 3년 이내", "개인사업자 제외" 등)이 있으면 위에서 '해당'이 나와도 모름(None)이다.
입력으로 그 조건을 확인할 수 없다(2026-10-06 Codex 검수 P2-1). '해당 아님'은 그대로 둔다.

선택 조건 묶음(2026-10-06 Codex 검수 P1-1)
  "벤처·이노비즈·메인비즈 10점"처럼 한 점수를 여러 조건이 나눠 가지면 같은 묶음이다(추출기의 group, 또는 근거 문장이 같음).
  묶음은 한 번만 센다 — 해당 항목 중 가장 큰 점수. 둘 다 해당해도 10점이다.
세부사업(program)
  세부사업마다 가점이 다르면 신청자가 어느 세부사업에 내는지 모른다. 세부사업마다(공통 항목 포함) 따로 계산해
  가장 큰 값을 쓰고 항목 이름에 세부사업을 붙인다. 어느 세부사업이 모름이면 양수가 없을 때 null 이다.

공고 단위 합계
  행 없음(첨부를 못 읽은 공고 — K-Startup 등)            → null
  status none · no_mention(가점 없음·가점 말 없음)        → 0
  status unverified(찾았으나 근거 확인 실패)              → null
  status found
    점수 있는 해당 묶음이 있다      → 그 합(공고 합계 한도 max_total_points 로 자른다)
    해당 묶음이 없고 모두 '해당 아님' → 0
    그 밖(모름이 섞임·해당이지만 점수 없음) → null
  bonus_items 의 points 는 **한도를 적용한 뒤 실제로 더한 점수**다(원문 배점과 다를 수 있다 — 이름에 "합계 한도 N점 적용").
  한도로 자를 때는 점수가 큰 항목부터 남긴다(같으면 이름순) — 추출 순서와 관계없이 같은 결과.

확실한 것만 남기기(2026-10-07 사용자 결정, Codex 재검수 R-P1-1·R-P2-1~5·R-P3-2) — AI 를 다시 부르지 않고 계산만 줄인다
  점수 인정     근거 문장(quote) 안에 그 점수가 "N점"으로 직접 적힌 항목만. 떨어진 배점 칸(points_source)·숫자만 있는 경우는 점수 없음
  묶음         같은 group 이름일 때만 한 묶음. quote 가 같다는 이유로 묶지 않는다(이름·근거가 같은 중복 추출만 하나로)
  앞으로의 조건  이전·유치·예정·희망·신규 채용 같은 말이 있으면 해당이어도 모름(FUTURE_WORDS)
  세부사업      세부사업마다 결과가 모두 같을 때만 그 값, 다르면 null
  합계 한도     해당 점수 합이 한도를 넘으면(전체 한도인지 확인 불가) null
  불확실       none + uncertain 있음 → null. found + uncertain 에 읽기 누락 말(GAP_WORDS) → null.
               found + uncertain 에 '중복' → 점수 있는 해당 묶음이 2개 이상이면 null
  같은 점수     묶음 안에서 점수가 같으면 이름순 첫 항목
  공고 합계는 "점수 있는 해당 묶음의 합"이다(다른 묶음이 모름이어도 확인된 묶음의 합 — 확인된 부분합).

최신성(2026-10-06 Codex 검수 P2-4): 가점 행은 뽑을 때의 공고 내용 지문(content_version)과 추출기 버전을 함께 저장한다.
load() 에 지금 지문·버전을 넘기면 다른 행(공고문이 바뀌었는데 아직 다시 뽑지 않음)은 버린다 → 그 공고는 null(모름).
"""
import re

from search import applicant as applicant_mod
from shared import region as region_mod

KNOWN_CERTS = set(applicant_mod.CERTIFICATIONS)
_AGE_LIMIT = re.compile(r'만\s*(\d{2})\s*세\s*(이하|미만)')
# 확실한 것만 남기기(2026-10-07) — 조정 가능한 판단 단어
FUTURE_WORDS = re.compile(r'이전|이주|유치|예정|희망|신규\s*채용|신규\s*고용')
GAP_WORDS = re.compile(r'누락|빠짐|빠져|빠진|발췌|일부|잘림|잘려|확인\s*불가|확인할\s*수\s*없|불명확|표\s*전체')
DUP_WORDS = re.compile(r'중복')


def load(connection, versions=None, extractor_version=None, stale=None):
    """{notice_id: {'status','max_total_points','bonus_info','items'}} — 공용 DB notice_bonus. SELECT 만 한다.

    versions({notice_id: 지금 공고 내용 지문})를 주면 지문이 다른 행을, extractor_version 을 주면 버전이 다른 행을 버린다.
    stale 에 dict 를 넘기면 버린 이유별 건수를 적는다.
    """
    import json
    with connection.cursor() as cursor:
        cursor.execute('SELECT notice_id, status, max_total_points, bonus_info, items, content_version, '
                       'extractor_version, uncertain FROM notice_bonus')
        out = {}
        for nid, status, total, info, items, cv, ver, uncertain in cursor.fetchall():
            if extractor_version is not None and ver != extractor_version:
                if stale is not None:
                    stale['version'] = stale.get('version', 0) + 1
                continue
            if versions is not None and (cv is None or versions.get(nid) != cv):
                if stale is not None:
                    stale['content'] = stale.get('content', 0) + 1
                continue
            if isinstance(items, (bytes, str)):
                items = json.loads(items)
            if isinstance(uncertain, (bytes, str)):
                uncertain = json.loads(uncertain)
            out[nid] = {'status': status, 'max_total_points': None if total is None else float(total),
                        'bonus_info': info, 'items': items or [], 'uncertain': uncertain or []}
        return out


def _text(item):
    return ' '.join(str(item.get(k) or '') for k in ('name', 'detail', 'quote'))


def _extra_requirements(item):
    """지역 항목 글에 함께 적힌 인증·연구소 조건("서울 소재 기업부설연구소 보유 기업") — 지역만 맞아서는 받지 못한다."""
    text = _text(item)
    need = {c for c in KNOWN_CERTS if c in text}
    if '연구소' in text:
        need.add('기업부설연구소')
    return need


_LOCAL_WORDS = re.compile(r'도내|관내|시내|군내|구내|역내|지역\s*내')


def _mentions_region(item, sido):
    """항목 글에 그 시·도(또는 그 안 시·군·구, '도내·관내')가 실제로 적혀 있나.

    LLM 이 지역을 공고 소재지에서 끌어와 붙인 항목("도시철도2호선 공사현장 반경 300m 상가")은 시·도만 맞아서는
    받지 못한다(2026-10-06 전량 점검). 글에 지역이 적힌 항목만 시·도로 맞춘다.
    """
    text = _text(item)
    names = {s for s, c in region_mod.ALIASES.items() if c == sido} | {sido, sido + '시', sido + '도'}
    if sido == '전남광주':
        names |= {'전남', '광주', '전라남도', '광주시'}
    return (any(n in text for n in names) or bool(region_mod.districts_in_title(text, sido))
            or bool(_LOCAL_WORDS.search(text)))


_GWANGJU_GU = ('동구', '서구', '남구', '북구', '광산구')


def _gwangju_side(item, req):
    """'전남광주'로 묶인 신청자가 '전남'만·'광주'만 요구하는 항목에 맞나 — True·False·None(시·군·구가 없어 모름).
    통합 표기는 일반 순위에는 쓰지만, 한쪽만 주는 가점의 소재지 증명에는 부족하다(2026-10-06 Codex 검수 P2-1)."""
    raw = set(item.get('regions') or [])
    if not raw or raw >= {'전남', '광주'} or not raw & {'전남', '광주'}:
        return True
    district = ' '.join(str(req.district or '').split())
    if not district:
        return None
    in_gwangju = district.startswith('광주') or district.split()[0] in _GWANGJU_GU
    return in_gwangju if '광주' in raw else not in_gwangju


def _region_hit(item, req):
    regions = {region_mod.canonical(r) for r in item.get('regions') or []} - {None}
    if not regions or not req.region:
        return None
    mine = region_mod.canonical(req.region)
    if mine not in regions:
        return False
    if mine == '전남광주':
        side = _gwangju_side(item, req)
        if side is not True:
            return side
    if not _mentions_region(item, mine):
        return None
    need = _extra_requirements(item)
    if need and not (need <= set(req.certifications or []) | ({'기업부설연구소'} if '연구소기업' in (req.certifications or []) else set())):
        return None                                        # 지역은 맞지만 추가 조건을 확인하지 못했다(2026-10-06 전량 점검)
    named = region_mod.districts_in_title(_text(item), mine)     # 항목이 시·군·구까지 정했나
    if not named:
        return True
    district = ' '.join(str(req.district or '').split())
    if not district:
        return None
    # 시·군·구는 자유 입력이다("창원시 성산구", "창원") — 항목의 이름이 입력에 들어 있거나 '시·군·구' 를 뗀 이름이 같으면 같다
    return any(n in district or n[:-1] == district.split()[0].rstrip('시군구') for n in named)


def _youth_hit(item, req):
    m = _AGE_LIMIT.search(_text(item))
    age = applicant_mod.age(getattr(req, 'birth_date', ''))
    if not m or age is None:
        return None
    limit = int(m.group(1))
    return age <= limit if m.group(2) == '이하' else age < limit


def item_hit(item, req):
    """항목 하나 × 신청자 → True · False · None. 추가 조건이나 앞으로의 조건(이전·유치·예정 …)이 있으면 True 를 None 으로 낮춘다
    (P2-1, 2026-10-07 R-P2-2 — extra_conditions 를 AI 가 비워도 글에 남은 이전 조건을 본다)."""
    hit = _base_hit(item, req)
    if hit is True and (item.get('extra_conditions') or FUTURE_WORDS.search(_text(item))):
        return None
    return hit


def _num(points):
    value = float(points)
    return ('%d' % value) if value == int(value) else ('%g' % value)


def points_supported(item):
    """항목 점수를 믿을 수 있나 — 떨어진 배점 칸(points_source)에서 가져오지 않았고, 근거 문장에 "N점"이 직접 있다(R-P1-1).
    "1 여성기업 가점 2점"처럼 연번이 점수로 읽힌 경우(근거에 1점이 없음)도 믿지 않는다."""
    if item.get('points') is None or item.get('points_source'):
        return False
    pattern = r'(?<![\d.])%s\s*점' % re.escape(_num(item['points']))
    return bool(re.search(pattern, str(item.get('quote') or '')))


def _base_hit(item, req):
    kind = item.get('kind')
    certs = set(item.get('certs') or [])
    mine = set(req.certifications or [])
    if kind == '여성':
        # 여성기업(인증)을 요구하면 인증과, '대표(자)'가 적혀 있으면 성별과 대조한다. 그 밖("여성연구자 10% 이상",
        # LLM 이 여성으로 분류한 가족친화인증 등)은 신청자 성별로 알 수 없어 모름(2026-10-06 전량 점검)
        # '대표이사가 여성인 기업'은 인증이 아니라 대표 성별 조건이다 — LLM 이 이름을 '여성기업'으로 붙여도 성별을 먼저 본다
        text = _text(item)
        if '대표' in str(item.get('quote') or '') + str(item.get('detail') or '') + str(item.get('name') or ''):
            if '여성기업' in mine or req.gender == '여성':
                return True
            return False if req.gender == '남성' else None
        if '여성기업' in certs or re.search(r'여성\s*기업', text):
            return '여성기업' in mine
        return None
    if kind == '장애인':
        # '장애인기업' 인증을 요구하는 항목만 인증과 대조한다. 장애인표준사업장·장애인 고용 등은 다른 제도라 모름(2026-10-06 전량 점검)
        if '장애인기업' in certs or '장애인기업' in (item.get('name') or ''):
            return '장애인기업' in mine
        return None
    if kind == '인증':
        known = certs & KNOWN_CERTS
        if not known:
            return None
        return bool(known & mine)
    if kind == '지역':
        return _region_hit(item, req)
    if kind == '청년':
        return _youth_hit(item, req)
    if kind == '재창업':
        return None if req.first_startup is None else (req.first_startup is False)
    return None


def _groups(items):
    """선택 조건 묶음 — 같은 group 이름이면 한 묶음(세부사업이 같을 때만). 순서는 처음 나온 순.
    같은 근거 문장(quote)이라는 이유로 묶지 않는다 — 한 문장에 독립 가점이 함께 적힌다(2026-10-07 R-P2-1).
    이름·근거가 같은 중복 추출만 하나로 친다."""
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    seen = {}
    for i, it in enumerate(items):
        for key in (('g', it.get('program'), it.get('group')) if it.get('group') else None,
                    ('same', it.get('program'), it.get('name'), it.get('quote'))):       # 똑같은 항목이 두 번 뽑힘
            if key is None:
                continue
            if key in seen:
                parent[find(i)] = find(seen[key])
            else:
                seen[key] = i
    out = {}
    for i, it in enumerate(items):
        out.setdefault(find(i), []).append(it)
    return list(out.values())


def _score_scope(items, req, cap, label=None, dup_unsure=False):
    """한 세부사업(또는 공통) 범위 → (점수 또는 None, 항목).
    dup_unsure: AI 가 중복 인정 여부를 모른다고 남김 — 점수 있는 해당 묶음이 2개 이상이면 합을 믿을 수 없어 None."""
    states, picked = [], []
    for group in _groups(items):
        hits = [(it, item_hit(it, req)) for it in group]
        scored = [it for it, hit in hits if hit is True and points_supported(it)]
        if scored:
            best = min(scored, key=lambda it: (-float(it['points']), it.get('name') or ''))     # 같은 점수면 이름순(R-P3-2)
            picked.append({'name': best.get('name') or '', 'points': float(best['points'])})
            states.append('scored')
        elif all(hit is False for _it, hit in hits):
            states.append('false')
        else:
            states.append('unknown')
    if not picked:
        return (0, []) if states and all(x == 'false' for x in states) else (None, [])
    if dup_unsure and len(picked) >= 2:
        return None, []
    picked.sort(key=lambda i: (-i['points'], i['name']))
    total = sum(i['points'] for i in picked)
    if cap is not None and total > cap:
        # 한도가 공고 전체 한도인지 항목 한도인지 확인할 수 없다 — 깎아서 내지 않고 모름(2026-10-07 R-P2-5)
        return None, []
    if label:
        for i in picked:
            i['name'] = '%s [%s]' % (i['name'], label)
    return round(total, 2), [dict(i, points=round(i['points'], 2)) for i in picked]


def score(entry, req):
    """공고 한 건의 가점(entry, load() 값 또는 None) × 신청자 → (bonus_score, bonus_items)."""
    if not entry or entry.get('status') == 'unverified':
        return None, []
    notes = ' '.join(str(x) for x in entry.get('uncertain') or [])
    if entry.get('status') == 'none' and notes.strip():
        return None, []                       # '가점 없음'을 확정하지 못했다(2026-10-07 R-P2-3)
    if entry.get('status') in ('none', 'no_mention'):
        return 0, []
    if GAP_WORDS.search(notes):
        return None, []                       # 표·우대 구간 일부를 읽지 못했다고 남겼다(R-P2-3)
    dup = bool(DUP_WORDS.search(notes))
    items = entry.get('items') or []
    cap = entry.get('max_total_points')
    programs = sorted({it.get('program') for it in items if it.get('program')})
    if len(programs) <= 1:
        return _score_scope(items, req, cap, dup_unsure=dup)
    # 세부사업이 나뉜 공고 — 신청자가 어느 세부사업에 내는지 모른다. 결과가 모두 같을 때만 쓴다(2026-10-07 R-P2-4)
    results = [_score_scope([it for it in items if not it.get('program') or it.get('program') == p], req, cap, p, dup)
               for p in programs]
    if len({r[0] for r in results}) == 1 and results[0][0] is not None:
        if results[0][0] == 0:
            return 0, []
        common = _score_scope([it for it in items if not it.get('program')], req, cap, None, dup)
        if common[0] == results[0][0]:
            return common                     # 공통 항목만으로 같은 점수 — 세부사업 꼬리표 없이 낸다
    return None, []
