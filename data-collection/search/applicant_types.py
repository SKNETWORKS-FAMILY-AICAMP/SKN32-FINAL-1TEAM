# -*- coding: utf-8 -*-
"""공고 본문에서 읽은 신청자 유형(예비창업자·개인사업자·법인)을 매칭·자격 확인에 쓴다 (2026-09-28, 기획서 대조 G).

근거: LLM 전량 추출 `reports/applicant_type_llm_full_20260928T023916Z/`(gpt-5.6-luna, 유형마다 원문 근거 + 코드 검사)과
Codex 블라인드 판정 `docs/reviews/applicant_type/APPLICANT_TYPE_INDUSTRY_LABEL_RESULT_20260928.md`(AI 참고 정답).
사용자 결정(2026-09-28): Codex 판정에서 믿을 만했던 것만 연결한다.

  예비창업자 '불가' strong · varies 아님   → 예비창업자 신청자에게서 **뺀다**(정형 필터). Codex 30/30 일치
  예비창업자 '가능'                        → K-Startup API 업력 칸이 예비창업자 불가라도 **본문을 우선해 되살린다**. Codex 9/9
  예비창업자 '불가 추정'                    → 빼지 않고 **뒤로** 보낸다(순위 신호). 추정이라 탈락 근거로 쓰지 않는다
  예비창업자 '불가' weak                   → 쓰지 않는다(Codex 13/17)
  개인사업자·법인                          → 매칭에 쓰지 않는다. 자격 확인 화면에 근거만 참고로 보여 준다(건수가 적고 적용 범위 주의)

등록 사업자 규칙(2026-09-28 사용자 승인 — docs/reviews/applicant_type/APPLICANT_TYPE_AMBIGUOUS_CHECK_20260928.md)
  LLM 이 예비창업자를 '언급 없음'이나 '불가 weak'로 둔 공고라도, 저장된 근거 문장에 **등록 사업자만 충족하는 표현**
  ("사업자등록증명원 상의 소재지", "사업자 미등록 업체" 제외, "정상가동 중", "영업활동을 하고 있는", "등록을 필한", "신고서가 제출 완료된" …)
  이 있으면 '불가 추정'으로 올려 **뒤로** 보낸다. 빼지 않는다. varies 공고와 '가능' 판정은 건드리지 않는다.
  근거에 "예비·없이·무관·예정" 이 있으면 올리지 않는다("사업자등록 없이도 신청 가능" 같은 문장). LLM 재호출·DB 조회 없음.
  2026-09-28 Codex 통합 검수 P2 보완
    · 제출 서류 문장("제출서류: 사업자등록증 보유 확인 서류", "사본")은 신청 자격이 아니므로 올리지 않는다
      (판정 지시서 3절과 같은 원칙). 단 "신청 자격·지원 대상·자격" 이 함께 있으면 자격 문장으로 본다
    · "예비창업자 제외/불가" 는 예비창업자를 받는다는 말이 아니다. 이 부분을 지운 뒤 "예비" 를 찾는다
    · "마감일 내 사업자등록 완료", "협약 전까지 등록" 처럼 신청 뒤에 등록해도 되는 문장은 올리지 않는다
    · 올라간 근거 67건을 Claude 가 한 줄씩 읽었다(AI 참고). 66건은 등록 사업자 요건이 맞고, 1건("공고 마감일 내
      사업자등록 완료한 기업")만 예비창업자도 신청할 수 있어 위 예외로 뺐다 → 66건
  2,476건 중 66건이 올라가고(처음 67건 → 검토 뒤 1건 제외), 원문 대조에서 놓침으로 확인된 6건(P044·P047·P084·P085·P086·P089)이 모두 포함된다.

결과 파일이 없으면(EC2 등) 이 기능은 꺼지고 지금까지와 같다. 파일에 없는 공고(추출 뒤 새로 수집)는 건드리지 않는다.
"""
import io
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_RUN = 'applicant_type_llm_full_20260928T023916Z'
ENV = 'APPLICANT_TYPES_RESULTS'
PRE_FOUNDER = '예비창업자'
_REGISTERED_ONLY = re.compile(
    r'사업자\s*등록\s*증(?:명원)?\s*(?:상의?|의)?\s*(?:소재지|사업장|주소)|사업자\s*등록\S{0,4}\s*(?:보유|완료|필수|된\s|한\s|을\s*한|이\s*되어)'
    r'|사업자\s*등록을?\s*하지\s*않|사업자\s*미등록|미등록\s*(?:업체|사업자)|정상\s*(?:가동|영업)|영업\s*활동을?\s*하고\s*있'
    r'|(?:등록증|허가증|신고증|확인증)을?\s*보유|등록을?\s*(?:필한|해야|완료한)|신고서가?\s*제출\s*완료|현재\s*영업\s*중|영업\s*중인'
    r'|사업자\s*등록일로부터|개업\s*(?:일|후)')
# "마감일 내 등록 완료"·"협약 전까지 등록" 은 지금 예비창업자여도 신청할 수 있다(67건 검토에서 1건, 2026-09-28)
_NOT_REGISTERED_ONLY = re.compile(r'예비|없이|무관|예정|관계없|불문|마감일?\s*(?:내|까지|이전)|협약\s*(?:체결\s*)?(?:전|시)|선정\s*후')
# 예비창업자를 빼는 말 — 받는다는 뜻이 아니므로 _NOT_REGISTERED_ONLY 검사 전에 지운다
_PRE_EXCLUDED = re.compile(r'예비\s*창업\S{0,3}\s*(?:\S{1,3}\s*)?(?:제외|불가|신청\s*불가|지원\s*불가|신청\s*제한|참여\s*불가)')
# 제출 서류 설명(신청 자격이 아니다). "증명원" 은 넣지 않는다 — "사업자등록증명원 상의 소재지" 는 자격 문장이다
_DOC_ONLY = re.compile(r'(?:제출|구비|증빙|첨부|확인)\s*서류|서류\s*[:：]|사본|첨부')
_QUALIFICATION = re.compile(r'신청\s*자격|지원\s*대상|자격')


def registered_only(text):
    """근거 문장이 등록 사업자만 충족하는 표현이면 그 표현, 아니면 None."""
    if not text:
        return None
    if _DOC_ONLY.search(text) and not _QUALIFICATION.search(text):
        return None
    if _NOT_REGISTERED_ONLY.search(_PRE_EXCLUDED.sub(' ', text)):
        return None
    m = _REGISTERED_ONLY.search(text)
    return m.group(0) if m else None


DAILY_RESULTS = os.path.join(ROOT, 'data', 'applicant_types', 'results.jsonl')   # 매일 배치 11단계 누적(collect/applicant_type_daily.py)


def default_path():
    """환경 변수 → 매일 배치 누적 파일(있으면) → 2026-09-28 전량 실행 결과 순서."""
    if os.environ.get(ENV):
        return os.environ[ENV]
    if os.path.exists(DAILY_RESULTS):
        return DAILY_RESULTS
    return os.path.join(ROOT, 'reports', DEFAULT_RUN, 'results.jsonl')


def _cell(llm, key):
    c = llm.get(key) or {}
    return {'status': c.get('status') or 'not_mentioned', 'strength': c.get('strength'),
            'evidence': c.get('evidence')}


def load(path=None):
    """결과 파일 → {'active', 'source', 'rows', 'notices': {공고 ID: {...}}, 'error'}."""
    path = path or default_path()
    out = {'active': False, 'source': os.path.basename(os.path.dirname(path)), 'rows': 0, 'notices': {},
           'error': None}
    if not os.path.exists(path):
        out['error'] = '신청자 유형 결과 파일이 없다: %s' % path
        return out
    with io.open(path, encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            llm = row.get('llm')
            if not llm:
                continue
            out['rows'] += 1
            out['notices'][row['notice_id']] = dict(_info(llm), document_sha256=row.get('document_sha256'))
    out['active'] = bool(out['notices'])
    return out


def _info(llm):
    """LLM 값(파일의 llm 칸 또는 DB 행을 같은 모양으로 만든 것) → 서비스가 쓰는 공고 정보."""
    info = {
        'varies': bool(llm.get('varies')),
        'pre_founder': _cell(llm, 'pre_founder'),
        'sole_proprietor': _cell(llm, 'sole_proprietor'),
        'corporation': _cell(llm, 'corporation'),
        'registered_only': None,
    }
    pre = info['pre_founder']
    if not info['varies'] and (pre['status'] == 'not_mentioned'
                               or (pre['status'] == 'not_allowed' and pre['strength'] != 'strong')):
        for key in ('pre_founder', 'sole_proprietor', 'corporation'):
            hit = registered_only(info[key]['evidence'])
            if hit:
                info['registered_only'] = {'phrase': hit, 'evidence': info[key]['evidence']}
                break
    return info


DB_TABLE = 'notice_applicant_types'
SOURCE_ENV = 'APPLICANT_TYPES_SOURCE'      # auto(기본) · db · file


def load_db(connection):
    """공용 DB notice_applicant_types → load() 와 같은 모양(2026-09-28). 등록 사업자 규칙은 지금 코드로 다시 계산한다."""
    out = {'active': False, 'source': 'db:' + DB_TABLE, 'rows': 0, 'notices': {}, 'error': None}
    keys = ('pre_founder', 'sole_proprietor', 'corporation')
    cols = ['notice_id', 'varies', 'document_sha256'] + ['%s_%s' % (k, f) for k in keys
                                                         for f in ('status', 'strength', 'evidence')]
    with connection.cursor() as cur:
        cur.execute('SELECT %s FROM %s' % (', '.join(cols), DB_TABLE))
        for r in cur.fetchall():
            row = dict(zip(cols, r))
            llm = {'varies': bool(row['varies'])}
            for k in keys:
                llm[k] = {'status': row[k + '_status'], 'strength': row[k + '_strength'], 'evidence': row[k + '_evidence']}
            out['rows'] += 1
            out['notices'][row['notice_id']] = dict(_info(llm), document_sha256=row['document_sha256'])
    out['active'] = bool(out['notices'])
    return out


COMPLETE_RATIO = 0.95      # DB 행이 서비스 공고 수의 이만큼은 돼야 "다 올라간" 표로 본다


def load_auto(connection=None, path=None, expected=None):
    """서비스가 부르는 진입점. APPLICANT_TYPES_SOURCE=auto 면 공용 DB 를 먼저, 비었거나 실패하면 파일(2026-09-28).

    EC2·팀원 PC 처럼 결과 파일이 없는 곳에서도 같은 판정으로 매칭하려고 DB 를 먼저 읽는다.
    배치 13단계가 파일과 같은 값을 올리므로 두 경로의 결과는 같다(올린 뒤 바뀐 행은 다음 배치까지 차이날 수 있다).
    2026-09-28 Codex 검수 P1·P2 — DB 가 덜 올라갔거나 옛 값일 때 믿지 않는다.
      · 완전성: DB 행이 expected(서비스 공고 수)의 95% 미만이면 업로드가 덜 끝난 것으로 보고 파일을 쓴다
        (파일이 없으면 DB 를 쓰되 note 에 적는다 — DB 에 없는 공고는 '모름'이라 빼지 않는다)
      · 신선도: 파일이 있으면(배치 PC) 공고마다 문서 해시를 비교해 다른 공고는 파일 값을 쓴다
        (11단계는 됐는데 13단계가 실패한 날, 옛 'blocked' 로 신청 가능한 공고를 빼지 않게)
      · db 강제: 연결이 없거나 읽기가 실패하면 파일로 넘어가지 않고 error 로 끝낸다(기능이 꺼진다)
    """
    mode = (os.environ.get(SOURCE_ENV) or 'auto').lower()
    if mode == 'file':
        return load(path)
    empty = {'active': False, 'source': 'db:' + DB_TABLE, 'rows': 0, 'notices': {}}
    if connection is None:
        if mode == 'db':
            return dict(empty, error='DB 연결 없음(APPLICANT_TYPES_SOURCE=db)')
        fallback = load(path)
        fallback['note'] = 'DB 연결 없음 — 파일을 쓴다'
        return fallback
    try:
        table = load_db(connection)
    except Exception as exc:
        if mode == 'db':
            return dict(empty, error='DB 읽기 실패: %s' % type(exc).__name__)
        why = 'DB 읽기 실패(%s)' % type(exc).__name__
    else:
        if mode == 'db':
            return table
        file_path = path or default_path()
        has_file = os.path.exists(file_path)
        if not table['active']:
            why = 'DB 표가 비어 있음'
        elif expected and table['rows'] < COMPLETE_RATIO * expected:
            why = 'DB 행이 공고 수의 %d%% 미만(%d/%d) — 업로드가 덜 끝났을 수 있음' % (
                COMPLETE_RATIO * 100, table['rows'], expected)
            if not has_file:
                table['note'] = why + ' — 파일이 없어 DB 를 쓴다'
                return table
        else:
            if has_file:
                fresh = load(file_path)
                stale = [nid for nid, info in fresh['notices'].items()
                         if (table['notices'].get(nid) or {}).get('document_sha256') != info.get('document_sha256')]
                for nid in stale:
                    table['notices'][nid] = fresh['notices'][nid]
                if stale:
                    table['note'] = '문서가 바뀌었거나 DB 에 없는 %d건은 파일 값을 쓴다(13단계가 아직 못 올림)' % len(stale)
                table['refreshed_from_file'] = len(stale)
            return table
    fallback = load(path)
    fallback['note'] = '%s — 파일을 쓴다' % why
    return fallback


def pre_founder(table, notice_id):
    """예비창업자에 대한 판정: 'blocked' | 'allowed' | 'implied_no' | None(모름·쓰지 않음)."""
    info = ((table or {}).get('notices') or {}).get(notice_id)
    if not info:
        return None
    c = info['pre_founder']
    if c['status'] == 'not_allowed' and c['strength'] == 'strong' and not info['varies']:
        return 'blocked'
    if c['status'] == 'allowed':
        return 'allowed'
    if c['status'] == 'implied_no' or info.get('registered_only'):
        return 'implied_no'
    return None


def varies(table, notice_id):
    """세부사업별로 신청자 유형이 다른 공고인가. 모르면 False."""
    info = ((table or {}).get('notices') or {}).get(notice_id)
    return bool(info and info.get('varies'))


def evidence(table, notice_id, key='pre_founder'):
    info = ((table or {}).get('notices') or {}).get(notice_id)
    return (info or {}).get(key, {}).get('evidence') if info else None


def type_check(table, notice_id, applicant_type):
    """자격 확인 화면의 '지원대상 유형' 한 줄. (판정 True/False/None, 요구, 설명). 표가 없으면 None."""
    info = ((table or {}).get('notices') or {}).get(notice_id)
    if not info:
        return None
    if applicant_type == PRE_FOUNDER:
        verdict = pre_founder(table, notice_id)
        ev = info['pre_founder']['evidence'] or ''
        if verdict == 'blocked':
            return False, '예비창업자 신청 불가(공고 본문)', '근거: "%s"' % ev
        if verdict == 'allowed' and info['varies']:
            # 세부사업마다 대상이 다른 공고(예: "예비창업자(장인대학 운영사업에 한함)")는 공고 전체를 통과로 두지 않는다
            # (2026-09-28 Codex 검수 P2 — varies·allowed 23건). 매칭은 빼지 않고 그대로 둔다(pre_founder 는 그대로)
            return None, '일부 세부사업에서 예비창업자 신청 가능(공고 본문)',                 '세부사업에 따라 대상이 다릅니다. 신청할 세부사업이 예비창업자를 받는지 원문을 확인하세요. 근거: "%s"' % ev
        if verdict == 'allowed':
            return True, '예비창업자 신청 가능(공고 본문)', '근거: "%s"' % ev
        if verdict == 'implied_no':
            reg = info.get('registered_only')
            if reg and info['pre_founder']['status'] != 'implied_no':
                return None, '등록 사업자 대상으로 보임(추정 · "%s")' % reg['phrase'], \
                    '사업자 등록이 필요한 표현이 있습니다. 원문을 확인하세요. 근거: "%s"' % reg['evidence']
            return None, '대상이 이미 사업 중인 기업으로 보임(추정)', \
                '예비창업자를 받는다는 말이 없습니다. 원문을 확인하세요. 근거: "%s"' % ev
        return None, '예비창업자 관련 문장 없음', '공고 본문에서 예비창업자 신청 가능 여부를 찾지 못했습니다.'
    key = 'corporation' if '법인' in (applicant_type or '') else 'sole_proprietor'
    c = info[key]
    label = '법인' if key == 'corporation' else '개인사업자'
    if c['status'] == 'not_mentioned':
        return None, '%s 관련 문장 없음' % label, '개인·법인 구분을 공고 본문에서 찾지 못했습니다. 원문을 확인하세요.'
    word = {'allowed': '가능', 'not_allowed': '불가'}.get(c['status'], c['status'])
    # 개인/법인은 자동 판정하지 않는다(적용 범위 주의 — Codex 판정 결과 3절). 근거만 보여 준다
    return None, '공고 본문: %s %s(참고)' % (label, word), '자동 판정하지 않습니다. 근거: "%s"' % (c['evidence'] or '')
