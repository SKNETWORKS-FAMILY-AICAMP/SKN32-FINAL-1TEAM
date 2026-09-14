# -*- coding: utf-8 -*-
"""자격요건 게이트 — 구조화 필드 비교로 통과 / 불통과 / 판단 불가를 판정한다.

LLM 을 쓰지 않는다. 같은 입력이면 항상 같은 결과가 나온다.

판정은 세 값이다 (decisions.md D4).

    True   조건을 충족한다            → 통과
    False  조건에 미달한다            → 탈락
    None   조건을 확인할 수 없다        → 후보로 남기되 "확인 필요" 로 표기한다

`None` 의 통과는 **추천 후보를 유지한다는 뜻이지 자격을 충족했다는 뜻이 아니다.**
조건을 못 찾은 것과 조건이 없는 것은 다르다. 못 찾았다고 "제한 없음" 으로 쓰면
사용자가 자격을 확인받은 것으로 읽는다.

`None` 을 `False` 로 뭉개면 **조건이 아예 없는 공고를 미달로 탈락시킨다.**
기업마당 1,520건은 업력 필드가 없고 접수 마감일도 60%가 없어서, 뭉개면
전건 탈락한다. 반대로 `None` 을 조용히 통과로만 처리하면 자격 없는 기업을
통과로 보여주게 되므로, 표기가 반드시 따라와야 한다.

입력은 두 형태를 모두 받는다.

    정규화 레코드   normalize.py 산출물 (`notice_id`/`schema_version` 보유)
    K-Startup 원본  기존 `data/notices.json` 의 행

판정에 쓰는 값
    업력 조건    age_condition_raw   / biz_enyy
    접수 기간    apply_start·end     / pbanc_rcpt_bgng_dt·end_dt
    기간 성격    apply_period_type   (fixed·budget_exhaustion·rolling·until_filled·unknown)
    모집 상태    recruitment_status  / rcrt_prgs_yn
"""
import re
from datetime import date

PRE_FOUNDER = '예비창업자'
YEAR_RE = re.compile(r'(\d+)\s*년\s*미만')

# 마감일이 "없는" 것이 정상인 접수 형태. 판단 불가가 아니라 조건 없음이다.
OPEN_ENDED = ('budget_exhaustion', 'rolling', 'until_filled')

PERIOD_LABEL = {
    'budget_exhaustion': '예산 소진 시까지',
    'rolling': '상시·수시 접수',
    'until_filled': '선착순·모집 완료 시까지',
    'unknown': '접수기간 정보 없음',
}


def parse_enyy(raw):
    """biz_enyy 문자열 → (예비창업자 허용 여부, 업력 상한 개월수 또는 None)

    "7년미만"              → (False, 84)
    "예비창업자,1년미만"      → (True, 12)
    "예비창업자"            → (True, None)   업력 있는 기업은 신청 불가
    ""                    → (False, None)  조건 없음. 아래 understood() 로 구분한다
    """
    tokens = [t.strip() for t in str(raw or '').split(',') if t.strip()]
    pre_ok = PRE_FOUNDER in tokens

    years = [int(m.group(1)) for t in tokens for m in [YEAR_RE.search(t)] if m]
    cap_months = max(years) * 12 if years else None
    return pre_ok, cap_months


def understood(raw):
    """업력 문자열에서 판정에 쓸 정보를 실제로 뽑아냈는지.

    빈 값과 "해석 못 한 값" 을 모두 판단 불가로 보낸다. 값이 있는데 못 읽었다면
    조건이 없는 것이 아니므로 통과시켜서는 안 되고, 미달도 아니므로 탈락시켜서도
    안 된다.
    """
    pre_ok, cap = parse_enyy(raw)
    return pre_ok or cap is not None


def business_age_months(founded, today=None):
    """설립일 → 업력(개월). 미설립이면 None."""
    if not founded:
        return None
    today = today or date.today()
    if isinstance(founded, str):
        founded = date.fromisoformat(founded)
    months = (today.year - founded.year) * 12 + (today.month - founded.month)
    if today.day < founded.day:
        months -= 1
    return max(months, 0)


def parse_ymd(s):
    """YYYYMMDD 또는 YYYY-MM-DD → date. 못 읽으면 None."""
    s = str(s or '').strip()
    if re.fullmatch(r'\d{8}', s):
        return date(int(s[:4]), int(s[4:6]), int(s[6:]))
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', s):
        return date.fromisoformat(s)
    return None


def _fields(notice):
    """원본 형태와 무관하게 판정에 필요한 값만 뽑아 통일한다."""
    if 'schema_version' in notice or 'notice_id' in notice:
        start, end = parse_ymd(notice.get('apply_start')), parse_ymd(notice.get('apply_end'))
        return {
            'age_raw': notice.get('age_condition_raw'),
            'start': start,
            'end': end,
            'period_type': notice.get('apply_period_type') or 'unknown',
            'status': notice.get('recruitment_status') or 'unknown',
        }

    # K-Startup 원본. 정규화 이전 경로를 그대로 지원한다.
    start, end = (parse_ymd(notice.get('pbanc_rcpt_bgng_dt')),
                  parse_ymd(notice.get('pbanc_rcpt_end_dt')))
    return {
        'age_raw': notice.get('biz_enyy'),
        'start': start,
        'end': end,
        'period_type': 'fixed' if (start and end) else 'unknown',
        'status': {'Y': 'open', 'N': 'closed'}.get(
            str(notice.get('rcrt_prgs_yn') or '').strip(), 'unknown'),
    }


def _check_age(age_raw, age_months):
    """업력. (판정, 요구, 내 값) 을 돌려준다."""
    mine = ('예비창업자 (미설립)' if age_months is None
            else '%d년 %d개월' % (age_months // 12, age_months % 12))

    if not understood(age_raw):
        # 조건이 없거나 해석하지 못했다. 미달로 볼 근거가 없다.
        # 조건을 못 찾은 것과 조건이 없는 것은 다르다. 못 찾았다고 "제한 없음" 으로
        # 쓰면 자격을 충족했다는 뜻으로 읽힌다. 확인할 수 없다고만 말한다.
        need = ('업력 조건 알 수 없음' if not str(age_raw or '').strip()
                else '업력 조건 해석 불가')
        return None, need, mine

    pre_ok, cap = parse_enyy(age_raw)
    if age_months is None:
        return pre_ok, ('예비창업자 신청 가능' if pre_ok else '예비창업자 신청 불가'), mine
    if cap is None:
        return False, '예비창업자만 신청 가능', mine
    return age_months < cap, '업력 %d년 미만' % (cap // 12), mine


def _check_period(f, today):
    """접수기간. 마감일이 없는 것이 정상인 형태를 미달로 보지 않는다."""
    start, end, kind = f['start'], f['end'], f['period_type']
    mine = '%s 신청' % today

    if end:
        ok = (start is None or start <= today) and today <= end
        need = '%s ~ %s' % (start or '(시작일 없음)', end)
        return ok, need, mine
    if kind in OPEN_ENDED:
        # 마감일이라는 조건 자체가 없는 공고다. 통과시키되 표기한다.
        return None, PERIOD_LABEL[kind], mine
    return None, PERIOD_LABEL['unknown'], mine


def _check_status(status):
    if status == 'open':
        return True, '모집 중', '모집 중'
    if status == 'closed':
        return False, '모집 중', '모집 마감'
    return None, '모집 상태 정보 없음', '알 수 없음'


def judge(notice, age_months, today=None):
    """공고 1건에 대한 자격 판정.

    age_months = None 이면 예비창업자(미설립)로 본다.

    반환
        passed   미달(False)이 하나도 없으면 True. 판단 불가는 탈락시키지 않는다.
                 **추천 후보로 남긴다는 뜻이지 자격을 충족했다는 뜻이 아니다**
        unknown  판단 불가인 조건 수. 0보다 크면 화면에 "확인 필요" 를 띄운다
        checks   [{'조건','요구','내 값','판정'}] — 판정은 True/False/None
    """
    today = today or date.today()
    f = _fields(notice)

    checks = []
    for name, (verdict, need, mine) in (
            ('업력', _check_age(f['age_raw'], age_months)),
            ('접수기간', _check_period(f, today)),
            ('모집 상태', _check_status(f['status']))):
        checks.append({'조건': name, '요구': need, '내 값': mine, '판정': verdict})

    return {
        'passed': all(c['판정'] is not False for c in checks),
        'unknown': sum(1 for c in checks if c['판정'] is None),
        'checks': checks,
    }


def mark(verdict):
    """판정 값 → 표시 기호. None 을 X 로 뭉개지 않기 위한 공용 함수."""
    return {True: 'O', False: 'X'}.get(verdict, '?')


def deadline_days(notice, today=None):
    """마감까지 남은 일수. 마감일이 없으면 None."""
    f = _fields(notice)
    if not f['end']:
        return None
    return (f['end'] - (today or date.today())).days
