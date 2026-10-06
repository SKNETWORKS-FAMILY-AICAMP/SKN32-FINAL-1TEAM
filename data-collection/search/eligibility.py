# -*- coding: utf-8 -*-
"""자격 확인 판정 한 곳 — 화면용 `/api/eligibility`와 조율용 `/api/notices/{id}/eligibility`가 함께 쓴다 (2026-10-06).

2026-10-06 전에는 이 판정이 app.py 의 eligibility() 안에 있었다. 조율 요청서 2.5 가 "추천의 정형 필터와 같은 규칙"을
요구해서, 두 창구가 규칙을 복사하지 않도록 **그대로 옮겼다**(판정 내용은 바꾸지 않았다). 추천의 정형 필터
(app.eligible_with_types → gate.prefilter)와 같은 함수(gate._check_age·applicant_types.pre_founder)를 쓴다.

조건 네 줄
  지원대상 유형  공고 본문에서 읽은 신청자 유형(applicant_types). 예비창업자만 자동 판정, 개인사업자·법인은 근거만(None)
  업력          API 업력 칸(gate). 본문에 예비창업자 가능이 명시되면 본문을 따른다
  접수기간      gate — 조율 창구는 쓰지 않는다
  모집 상태     gate — 조율 창구는 쓰지 않는다
판정 값은 True(충족)·False(확실한 미달)·None(확인할 수 없음 — 통과로 본다).
"""
from search import gate

TYPE, AGE, PERIOD, STATUS = '지원대상 유형', '업력', '접수기간', '모집 상태'


def conditions(row, notice_id, applicant_type, founded_at, types_table=None, age_table=None, today=None):
    """공고 한 건 × 신청자 → (checks, age_months).

    checks      [{'조건','요구','내 값','판정','설명'?}] — 지원대상 유형 · 업력 · 접수기간 · 모집 상태 순
    age_months  gate.applicant_age 값(예비창업자 None, 설립일을 모르는 사업자 gate.UNKNOWN_AGE, 그 밖에는 개월 수)
    today       업력·접수기간 기준일(date). None 이면 오늘(서버 날짜)
    types_table 신청자 유형 판정표(app.STATE['applicant_types']). None 이면 공고 본문 유형을 쓰지 않는다
    age_table   업력 근거표(app.STATE['age_evidence']). 화면 설명에만 쓴다(판정에 쓰지 않는다)
    """
    # 예비창업자는 미설립(None), 설립일이 없거나 형식이 이상한 사업자는 '모른다'(UNKNOWN_AGE).
    # 매칭의 정형 필터와 같은 함수를 쓴다
    age_months = gate.applicant_age(applicant_type, founded_at, today)
    verdict = gate.judge(row, age_months, today)

    # '지원대상 유형'은 공고 본문에서 읽은 신청자 유형으로 판정한다(2026-09-28 G, search/applicant_types.py).
    # 예비창업자는 본문 '불가'(강한 근거)면 미달, '가능'이면 통과, 추정·모름은 확인 필요.
    # 개인사업자·법인은 자동 판정하지 않고 근거만 보여 준다. 결과 파일에 없는 공고는 예전처럼 확인 필요다.
    from search import applicant_types as types_mod
    typed = types_mod.type_check(types_table, notice_id, applicant_type) if types_table is not None else None
    if typed:
        type_verdict, type_need, type_why = typed
    else:
        type_verdict, type_need = None, row.get('target_category') or '지원대상 정보 없음'
        type_why = '개인사업자·법인 구분 정보가 공고 데이터에 없습니다. 원문을 확인하세요.'
    checks = [{'조건': TYPE, '요구': type_need, '내 값': applicant_type,
               '판정': type_verdict, '설명': type_why}] + verdict['checks']
    # 본문에 예비창업자 가능이 명시됐으면 업력 줄도 본문을 따른다.
    #   API 업력 칸이 예비 불가라 미달로 나온 경우 — 본문 우선
    #   업력 칸이 없어(기업마당) 모름으로 나온 경우 — "예비창업자 또는 창업 N년 미만 기업" 처럼 업력은 기존 사업자 쪽
    #   조건이다. 예비창업자에게는 해당하지 않으므로 통과로 둔다(2026-09-28 A, 반려동물 창업 경진대회 공고)
    pre_allowed = applicant_type == types_mod.PRE_FOUNDER and type_verdict is True
    # 세부사업별로 예비창업자 허용이 갈리는 공고 — 업력을 통과로도 미달로도 두지 않는다(Codex 검수 P2)
    pre_partial = (applicant_type == types_mod.PRE_FOUNDER and types_mod.varies(types_table, notice_id)
                   and types_mod.pre_founder(types_table, notice_id) == 'allowed')
    for c in checks:
        if c['조건'] != AGE:
            continue
        # 세부사업별 예비 허용은 업력이 이미 통과여도 확인 필요로 둔다(Codex 재검수 P2 — K-Startup 5건은
        # API 업력 칸이 "예비창업자, …년미만" 이라 True 였고, 먼저 건너뛰어 통과로 남았다)
        if not pre_partial and c['판정'] is True:
            continue
        if pre_partial:
            c['판정'] = None
            c['요구'] = '세부사업에 따라 예비창업자 신청 가능(공고 본문) — 업력 조건은 세부사업별로 확인 · 업력 칸: %s' % c['요구']
            c['설명'] = type_why or ''
        elif pre_allowed and c['판정'] is False:
            c['판정'] = True
            c['요구'] = '예비창업자 신청 가능(공고 본문 우선 · API 업력 칸: %s)' % c['요구']
            c['설명'] = '업력 칸(API)은 예비창업자 불가지만, 공고 본문에 예비창업자 신청 가능이 명시돼 본문을 따릅니다.'
        elif pre_allowed:
            c['판정'] = True
            c['요구'] = '예비창업자 신청 가능(공고 본문) — 업력 조건은 이미 창업한 기업에 붙는 조건'
            c['설명'] = ('공고 본문에 예비창업자 신청 가능이 명시돼 있습니다. %s' % (type_why or '')).strip()
        else:
            # 업력 칸이 없거나 못 읽었다 — 공고문 추출 값을 근거로만 보여 준다(판정은 확인 필요 그대로, B)
            from search import age_evidence
            shown = age_evidence.evidence_check(age_table, notice_id, age_months)
            if shown:
                c['요구'], c['설명'] = shown
                if age_months is gate.UNKNOWN_AGE:
                    c['설명'] = '설립일이 없어 비교하지 못했습니다. ' + c['설명']
    return checks, age_months
