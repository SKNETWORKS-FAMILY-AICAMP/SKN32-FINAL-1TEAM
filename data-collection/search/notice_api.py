# -*- coding: utf-8 -*-
"""조율 에이전트(Orchestrator)가 부르는 공고 서버 창구 (2026-10-06~).

요청서: SB-87 브랜치 agent-orchestration/docs/공고서버_API요청_공고팀전달.md
작업 기록: docs/notice_api/ (작업별 폴더)

  GET  /api/collection_status                  수집 상태 — 01
  POST /api/match                              공고 추천 — search/app.py 에 있다(결과 키는 01 에서 더함)
  GET  /api/notices/{notice_id}                공고 상세 — 02
  POST /api/notices/{notice_id}/eligibility    자격 판정 — 02

서버는 `python -m search.app` 으로 켜서 app.py 가 __main__ 모듈이다. 여기서 app.py 를 import 하면
STATE 가 빈 두 번째 사본이 생긴다. 그래서 app.py 가 build_router(STATE, connect) 로 상태와 DB 연결 함수를 넘긴다.

공고 ID 는 경로에 퍼센트 인코딩으로 온다(`kstartup%3A179323`). 서버가 풀어서 넘겨준다. `/` 가 든 ID 도 받도록
경로 칸을 {notice_id:path} 로 둔다. 공고가 없으면 404 + 본문 최상위 {"code": "NOTICE_NOT_FOUND"} —
본문 코드가 없는 404(경로가 없을 때)와 조율 쪽이 구분한다(요청서 2.1).
"""
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from search import collection_status, gate
from search import eligibility as eligibility_mod

NOT_FOUND = {'code': 'NOTICE_NOT_FOUND'}
APPLICANT_TYPES = ('예비창업자', '개인사업자', '법인')
PRE_FOUNDER = APPLICANT_TYPES[0]
# 조율 창구가 쓰는 조건 이름은 둘뿐이다(요청서 2.5). 접수기간·모집 상태는 판정하지 않는다
CONDITIONS = (eligibility_mod.TYPE, eligibility_mod.AGE)
RECRUITMENT = ('open', 'closed', 'unknown')


def _day(value):
    """DB 날짜(date) 또는 문자열 → 'YYYY-MM-DD'. 없으면 None."""
    if not value:
        return None
    return value.isoformat() if hasattr(value, 'isoformat') else str(value)


def _types_table(state):
    """추천의 정형 필터와 같은 조건으로 신청자 유형 판정표를 쓴다 — 표가 켜져 있을 때만(app.match 의 use_types)."""
    table = state.get('applicant_types') or {}
    return table if table.get('active') else None


# ── 공고 상세 ────────────────────────────────────────────────
def allowed_types(row, notice_id, types_table):
    """허용 지원대상 유형 목록 — 세 유형 중 **유형만으로 확실히 안 되는 것**을 뺀다. 자격 판정과 같은 규칙이다.

      예비창업자   지원대상 유형·업력 판정에 확실한 미달(False)이 있으면 뺀다(본문 '불가', 업력 칸이 사업자 전용 …)
      개인사업자·법인  업력 칸이 '예비창업자'만이면 뺀다. 업력 상한(N년 미만)은 설립일에 달린 것이라 빼지 않는다
    조율 쪽은 이 값을 선택 공고에 담아 두기만 한다(판정은 자격 판정 창구가 한다).
    """
    out = []
    checks, _ = eligibility_mod.conditions(row, notice_id, PRE_FOUNDER, '', types_table=types_table)
    if not any(c['판정'] is False for c in checks if c['조건'] in CONDITIONS):
        out.append(PRE_FOUNDER)
    raw = row.get('age_condition_raw')
    pre_only = gate.understood(raw) and gate.parse_enyy(raw)[1] is None
    if not pre_only:
        out.extend(APPLICANT_TYPES[1:])
    return out


def notice_detail(row, notice_id, amount, types_table, bonus=None):
    """공고 한 건 → 요청서 2.4 의 응답. amount 는 {'won', 'quote'} 또는 None, bonus 는 search.bonus.load() 의 한 건."""
    raw = row.get('age_condition_raw')
    status = row.get('recruitment_status')
    won = (amount or {}).get('won')
    return {
        'notice_id': notice_id,
        'title': row.get('title') or '',
        'organizer': row.get('organizer') or None,
        'supervising_org': row.get('supervising_org') or None,
        'executing_org': row.get('executing_org') or None,
        'source': row.get('source'),
        'url': row.get('url') or None,
        'apply_url': row.get('apply_url') or None,
        'category': row.get('category') or None,
        'apply_start': _day(row.get('apply_start')),
        'apply_end': _day(row.get('apply_end')),
        'apply_period_type': row.get('apply_period_type'),
        'recruitment_status': status if status in RECRUITMENT else 'unknown',
        # 지원 금액 상한(원) — 첨부 공고문에서 LLM 이 뽑고 근거 문장과 대조한 값(notice_conditions). 버린 값·0 은 null
        'support_amount_max_won': won if isinstance(won, int) and won > 0 else None,
        # 공고 원문의 금액 표기는 따로 저장하지 않는다 — null. 근거 문장은 참고용 추가 키로 준다(조율 쪽은 쓰지 않는다)
        'support_amount_text': None,
        'support_amount_evidence': (amount or {}).get('quote') if won else None,
        # 가점 원문(03_bonus) — 가점을 찾은 공고만. 가점 없음·읽지 못함은 null
        'bonus_info': (bonus or {}).get('bonus_info') if (bonus or {}).get('status') == 'found' else None,
        'eligibility': {
            'applicant_types': allowed_types(row, notice_id, types_table),
            # 업력 상한·읽었는지 — API 업력 칸(age_condition_raw) 기준. 자격 판정과 같은 칸이다.
            # 칸을 읽지 못했으면 상한 null · parsed false(제한이 없다는 뜻이 아니다)
            'business_age_max_months': gate.parse_enyy(raw)[1] if gate.understood(raw) else None,
            'parsed': gate.understood(raw),
        },
    }


def load_amounts(connection):
    """{notice_id: {'won', 'quote'}} — notice_conditions 의 지원 금액(버린 값 제외). SELECT 만 한다."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT notice_id, amount_max_won, source_quote FROM notice_conditions '
                       'WHERE amount_max_won IS NOT NULL AND amount_rejected IS NULL')
        return {nid: {'won': int(won), 'quote': quote} for nid, won, quote in cursor.fetchall()}


# ── 자격 판정 ────────────────────────────────────────────────
class EligibilityBody(BaseModel):
    """요청서 2.5 보내는 값. 형식이 틀리면 422(조율 쪽은 늘 정해진 형식으로 보낸다)."""
    applicant_type: Literal['예비창업자', '개인사업자', '법인']
    founded_at: str = ''
    today: str

    @field_validator('today')
    @classmethod
    def _today(cls, v):
        if gate.parse_ymd(v) is None or len(v) != 10:
            raise ValueError("today 는 'YYYY-MM-DD'")
        return v

    @field_validator('founded_at')
    @classmethod
    def _founded(cls, v):
        if v and (gate.parse_ymd(v) is None or len(v) != 10):
            raise ValueError("founded_at 은 'YYYY-MM-DD' 또는 빈 값")
        return v


def judge(row, notice_id, body, types_table):
    """공고 한 건 × 신청자 → 요청서 2.5 의 응답. 접수기간·모집 상태 줄은 버린다.

    passed 는 두 조건에 확실한 미달(False)이 없으면 참. 확인할 수 없는 조건(None)은 통과로 보고 unknown_conditions 에 넣는다.
    business_age_months 는 사업자의 업력(today 기준 개월). 예비창업자·설립일을 모르는 사업자는 null.
    """
    checks, age = eligibility_mod.conditions(row, notice_id, body.applicant_type, body.founded_at,
                                             types_table=types_table, today=gate.parse_ymd(body.today))
    used = [c for c in checks if c['조건'] in CONDITIONS]
    failed = [c['조건'] for c in used if c['판정'] is False]
    return {
        'passed': not failed,
        'failed_conditions': failed,
        'unknown_conditions': [c['조건'] for c in used if c['판정'] is None],
        'business_age_months': age if isinstance(age, int) and not isinstance(age, bool) else None,
        # 참고용(조율 쪽은 쓰지 않는다) — 조건마다 요구·설명
        'details': [{'condition': c['조건'], 'verdict': c['판정'], 'need': c['요구'], 'note': c.get('설명') or ''}
                    for c in used],
    }


def served_status(checked, loaded_store_at, now, max_age_hours=collection_status.MAX_AGE_HOURS):
    """DB 기준 수집 상태(checked)에 "서버가 들고 있는 공고가 오래됐는가"를 얹는다. 순수 함수.

    서버는 켤 때 공고를 메모리에 올리고, 매일 배치 뒤 다시 켜야 새 공고가 반영된다(app.py boot 주석).
    DB 가 새것이어도 서버가 사흘 전 공고로 추천하면 기준 문서의 "최종 수집 24시간 초과면 매칭 안 함"을
    어긴다. 그래서 서버가 올린 공고의 저장 시각(loaded_store_at)이 max_age 를 넘으면 '정상'을 '지연'으로 내린다.
    '실패'는 그대로 둔다(더 강한 상태). loaded_store_at 을 모르면 서버 공고가 새것인지 확인할 수 없으므로
    '정상'을 '지연'으로 내린다(2026-10-06 Codex 검수 P2-8 — 전에는 DB 판정만 따라 '정상'이 나올 수 있었다).
    """
    status = checked['status']
    reasons = list(checked.get('reasons') or [])
    if loaded_store_at is None:
        if status == '정상':
            status = '지연'
        reasons.append('서버가 올린 공고의 저장 시각을 모른다 — 서버 공고가 새것인지 확인할 수 없다(서버를 다시 켜야 한다)')
    else:
        age = now - loaded_store_at
        if age > timedelta(hours=max_age_hours):
            if status == '정상':
                status = '지연'
            reasons.append('서버가 들고 있는 공고가 %.1f시간 전 저장분이다(기준 %d시간) — 서버를 다시 켜야 새 공고가 반영된다'
                           % (age.total_seconds() / 3600, max_age_hours))
    return status, reasons


def build_router(state, connect):
    """state 는 app.STATE, connect 는 app._connect (EC2·PC 에 맞는 DB 연결)."""
    router = APIRouter()

    @router.get('/api/collection_status')
    def api_collection_status():
        # 응답 약속: 최상위 status 는 '정상'·'지연'·'실패' 중 하나. 나머지 키는 참고용이다(조율 쪽은 쓰지 않는다).
        # DB 를 읽지 못하면 상태를 지어내지 않고 503 을 준다 — 조율 쪽은 다시 부르다가 "잠시 문제" 안내를 낸다.
        # ('실패'를 주면 "공고 정보를 갱신하는 중" 안내가 나가는데, 그건 수집이 실패했다는 뜻이라 사실이 아니다.)
        now = datetime.now(timezone.utc)
        try:
            connection = connect()
            try:
                checked = collection_status.check(connection=connection, now=now)
            finally:
                connection.close()
        except Exception as exc:
            return JSONResponse({'code': 'COLLECTION_STATUS_UNAVAILABLE',
                                 'error': '%s: 수집 상태를 읽지 못했다' % type(exc).__name__}, status_code=503)
        loaded = state.get('loaded_store_at')
        status, reasons = served_status(checked, loaded, now)
        return {'status': status, 'reasons': reasons,
                'db_status': checked['status'], 'last_run_at': checked.get('last_run_at'),
                'loaded_store_at': loaded.isoformat() if loaded else None,
                'checked_at': checked.get('checked_at')}

    @router.get('/api/notices/{notice_id:path}')
    def api_notice(notice_id: str):
        row = state['rows'].get(notice_id)
        if row is None:
            return JSONResponse(NOT_FOUND, status_code=404)
        return notice_detail(row, notice_id, (state.get('amounts') or {}).get(notice_id), _types_table(state),
                             (state.get('bonus') or {}).get(notice_id))

    @router.post('/api/notices/{notice_id:path}/eligibility')
    def api_notice_eligibility(notice_id: str, body: EligibilityBody):
        row = state['rows'].get(notice_id)
        if row is None:
            return JSONResponse(NOT_FOUND, status_code=404)
        return judge(row, notice_id, body, _types_table(state))

    return router
