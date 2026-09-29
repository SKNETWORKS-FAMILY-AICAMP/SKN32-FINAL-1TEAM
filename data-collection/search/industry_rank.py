# -*- coding: utf-8 -*-
"""업종 순위 신호 — 신청자 주 업종이 공고의 허용 업종 목록 **밖**이면 뒤로 보낸다. 빼지는 않는다.

2026-09-28 사용자 결정(docs/PLAN_ALIGNMENT_20260928.md 2절)
  · 업종은 정형 필터·자격 게이트에 쓰지 않고 순위에만 쓴다(기획서 4-2·5-3, 기능정의서 R-3 preference.industryCode)
  · 확실한 불일치만 뒤로 보낸다. 모르면 건드리지 않는다(지역 규칙과 같은 원칙)
  · 허용 목록만 쓴다. 제외 목록은 세부 업종(유흥주점·담배 중개 …)이라 대분류로 비교하면 틀린다(A안)

공고 업종은 DB 에 없다. LLM 업종 추출 결과 파일(reports/industry_llm_*/results.jsonl)을 서버를 켤 때 읽는다.
파일이 없으면(EC2 등) 규칙은 조용히 꺼지고 응답의 industry.active 가 False 가 된다.

순위에 쓰는 공고 — 아래를 **모두** 만족할 때만(하나라도 아니면 그 공고는 업종으로 건드리지 않는다)
  industry_status == 'known'     업종 제한이 있다고 검사까지 통과한 공고
  list_complete                  허용 목록이 완전하다("등"으로 끝나거나 일부만 뽑힌 목록이 아니다)
  not truncated                  공고문 발췌가 상한에서 잘리지 않았다
  not scope_unresolved           통합공고처럼 세부사업마다 조건이 다를 수 있는 공고가 아니다
  allowed_sections(...) 가 있음  허용값이 **전부** KSIC 대분류로 바뀐다(바이오·AI 같은 분야값이 섞이면 비교 불가)

신청자 쪽은 industry_groups.applicant_section — 대분류 하나로 정해질 때만 쓴다.
정확도는 사람 정답으로 재지 않았다(LLM 추출 + 규칙 묶음). 그래서 규칙 우선순위는 지역보다 약하게 둔다(app.match).

**2026-09-28 기본 꺼짐**(MatchRequest.demote_industry=False). Codex 블라인드 판정에서 밀린 공고 34건 중 11건(업종 쌍 32개)이
부당하게 밀렸다 — 허가("발전사업자"), 상품 조건(입점 품목), 창업 예정 업종(외식업 창업 교육), 역할 갈래(공급기업)를
신청자 업종 제한으로 읽었다(docs/reviews/applicant_type/APPLICANT_TYPE_INDUSTRY_LABEL_RESULT_20260928.md). 추출을 고친 뒤 다시 켠다.
"""
import io
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_RUN = 'industry_llm_full_luna_20260928_final5'
ENV = 'INDUSTRY_RESULTS'          # 다른 결과 파일을 쓰려면 이 환경 변수에 results.jsonl 경로를 준다


def default_path():
    return os.environ.get(ENV) or os.path.join(ROOT, 'reports', DEFAULT_RUN, 'results.jsonl')


# ── 근거 문장에 다른 갈래가 남았는가 (2026-09-28 Codex 통합 재검수 P1) ──
# LLM 의 list_complete 를 그대로 믿지 않는다. 허용값을 근거 문장에서 지우고 **남은 부분**에
#   · 갈래를 여는 말(또는·혹은·~거나·판단되는·~의 경우·①② 번호 갈래·중 하나)이나
#   · 허용값에 없는 다른 대상(농업인·단체·소상공인·수출·무역·예비창업자 …)이 있으면
# 목록이 완전하지 않다고 보고 순위에 쓰지 않는다. 예: "제조 또는 수출 기업"(허용값 '제조'), "무역업의 경우 …",
# "농업인과 농업법인, 생산자 단체 및 농식품 제조ㆍ가공업체"(허용값 '농식품 제조ㆍ가공업체').
# "본사 또는 공장" 같은 소재지 표현의 '또는'은 갈래가 아니라 먼저 지운다. 규칙은 보수적이다 — 쓸 수 있는 공고를 버리는 쪽으로만 틀린다.
_NOISE = re.compile(r'[\s·ㆍ・‧∙\-_/\'‘’"“”,，、()（）\[\]〈〉<>:：☞◦❍○●□■▶※*]')
_PLACE_PAIR = re.compile(r'(본사|공장|사업장|사무소|주사무소|주소지|연구소|지사|소재지)(및|또는|혹은)'
                         r'(본사|공장|사업장|사무소|주사무소|주소지|연구소|지사|소재지)')
_BRANCH_CUE = re.compile(r'또는|혹은|이거나|거나|판단되|의경우|인경우|①|②|중하나|어느하나')
_OTHER_TARGET = re.compile(r'소상공인|농업인|농업법인|생산자|단체|명인|수출|무역|협동조합|예비창업|스타트업|연구기관|대학|개인')


def branch_problem(llm):
    """근거 문장에 허용값 밖 갈래가 남았으면 그 단서(문자열), 아니면 None."""
    allowed = llm.get('allowed') or []
    evidences = [a.get('evidence') or '' for a in allowed]
    text = ' '.join(dict.fromkeys(e for e in evidences if e)) or (llm.get('quote') or '')
    rest = _PLACE_PAIR.sub('', _NOISE.sub('', text))
    for value in sorted((_NOISE.sub('', a.get('text') or '') for a in allowed), key=len, reverse=True):
        if value:
            rest = rest.replace(value, '')
    for rx in (_BRANCH_CUE, _OTHER_TARGET):
        m = rx.search(rest)
        if m:
            return m.group(0)
    return None


def usable_sections(llm):
    """결과 한 행의 llm 칸 → 순위에 쓸 대분류 집합. 쓸 수 없으면 None."""
    from experiments.sql_semantic import industry_groups
    if (llm.get('industry_status') != 'known' or not llm.get('list_complete')
            or llm.get('truncated') or llm.get('scope_unresolved')):
        return None
    if branch_problem(llm):
        return None
    return industry_groups.allowed_sections([a.get('text') for a in llm.get('allowed') or []])


def load(path=None):
    """결과 파일 → {'active', 'source', 'rows', 'notices': {공고 ID: {'sections', 'allowed'}}, 'error'}."""
    path = path or default_path()
    out = {'active': False, 'source': os.path.basename(os.path.dirname(path)), 'rows': 0, 'notices': {},
           'error': None}
    if not os.path.exists(path):
        out['error'] = '업종 결과 파일이 없다: %s' % path
        return out
    with io.open(path, encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            out['rows'] += 1
            llm = row.get('llm') or {}
            sections = usable_sections(llm)
            if sections:
                out['notices'][row['notice_id']] = {
                    'sections': sorted(sections), 'allowed': [a.get('text') for a in llm.get('allowed') or []]}
    out['active'] = bool(out['notices'])
    return out


DB_TABLE = 'notice_industries'
SOURCE_ENV = 'INDUSTRY_SOURCE'      # file(기본, 2026-09-28 결정 — Codex 재검수 뒤 final6·DB 로 바꾼다) · auto · db


def load_db(connection):
    """공용 DB notice_industries → load() 와 같은 모양. usable_for_rank 행만 순위 신호로 쓴다(올릴 때의 규칙으로 계산)."""
    out = {'active': False, 'source': 'db:' + DB_TABLE, 'rows': 0, 'notices': {}, 'error': None}
    with connection.cursor() as cur:
        cur.execute('SELECT COUNT(*) FROM %s' % DB_TABLE)
        out['rows'] = cur.fetchone()[0]
        cur.execute('SELECT notice_id, allowed_sections, allowed FROM %s WHERE usable_for_rank' % DB_TABLE)
        for nid, sections, allowed in cur.fetchall():
            sections = json.loads(sections) if isinstance(sections, (str, bytes)) else sections
            allowed = json.loads(allowed) if isinstance(allowed, (str, bytes)) else allowed
            if sections:
                out['notices'][nid] = {'sections': sorted(sections), 'allowed': [a.get('text') for a in allowed or []]}
    out['active'] = bool(out['notices'])
    return out


def load_auto(connection=None, path=None, expected=None):
    """서비스가 부르는 진입점. 기본은 파일(final5). INDUSTRY_SOURCE=auto 면 DB 먼저, 비었거나 실패하면 파일.

    auto 에서 DB 행이 expected(공고 수)의 95% 미만이면 덜 올라간 것으로 보고 파일을 쓴다. db 강제에서 연결이
    없으면 파일로 넘어가지 않고 error(2026-09-28 Codex 검수).
    """
    mode = (os.environ.get(SOURCE_ENV) or 'file').lower()
    if mode == 'file':
        return load(path)
    if connection is None:
        if mode == 'db':
            return {'active': False, 'source': 'db:' + DB_TABLE, 'rows': 0, 'notices': {},
                    'error': 'DB 연결 없음(INDUSTRY_SOURCE=db)'}
        return load(path)
    try:
        table = load_db(connection)
    except Exception as exc:
        if mode == 'db':
            return {'active': False, 'source': 'db:' + DB_TABLE, 'rows': 0, 'notices': {},
                    'error': 'DB 읽기 실패: %s' % type(exc).__name__}
        why = 'DB 읽기 실패(%s)' % type(exc).__name__
    else:
        if mode == 'db':
            return table
        if not table['active']:
            why = 'DB 표가 비어 있음'
        elif expected and table['rows'] < 0.95 * expected:
            why = 'DB 행이 공고 수의 95%% 미만(%d/%d)' % (table['rows'], expected)
        else:
            return table
    fallback = load(path)
    fallback['note'] = '%s — 파일을 쓴다' % why
    return fallback


def applicant_section(main_industry):
    from experiments.sql_semantic import industry_groups
    return industry_groups.applicant_section(main_industry)


def off_industry(table, notice_id, section):
    """신청자 대분류 section 이 공고 허용 목록 밖이면 True. 모르면(표에 없음·신청자 업종 없음) False."""
    if not section or not table:
        return False
    info = (table.get('notices') or {}).get(notice_id)
    return bool(info) and section not in info['sections']
