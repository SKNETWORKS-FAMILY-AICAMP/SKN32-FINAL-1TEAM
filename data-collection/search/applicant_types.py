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

어디서 읽나(2026-09-28 → 2026-09-29 지문 확인): 공용 DB notice_applicant_types(13단계) → 배치 PC 결과 파일(11단계) 순서로,
공고마다 **지금 공고문의 지문(document_sha256)과 같은 판정만** 쓴다(load_auto · fresh_only). 판정이 없거나 지문이 다른
공고(공고문이 바뀐 뒤 아직 다시 판정하지 못한 공고)는 '모름'이라 빼지도 되살리지도 않는다. 지문을 확인할 수 없으면
기능 전체가 꺼지고 이 기능이 생기기 전과 같다. 프롬프트 버전은 대조하지 않는다(2026-09-29 사용자 결정).

발췌 밖 원문 확인(2026-09-29 Codex 재검수 P1-2, 사용자 결정 A안): LLM 은 공고 원문 전체가 아니라 build_document() 의
발췌(최대 6,000자)만 읽고, 지문도 그 발췌의 해시다. 그래서 발췌 밖에 "예비창업자도 가능" 이 있거나 나중에 생겨도
판정·지문이 그대로다. 예비창업자 '불가' strong 판정인데 **발췌 밖 원문에 '예비창업' 이 나오면** 빼지 않고
'확인 필요'(pre_founder() 가 None)로 낮춘다(mark_unread). 전체 원문 지문으로 바꿔도 다시 판정할 때 같은 발췌를 읽어
결론이 같으므로, 옛 판정 감지보다 "안 읽은 곳에 해당 말이 있나" 를 본다. 9/29 공용 DB: strong 불가 187건 중 2건.
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
    """결과 파일 → {'active', 'source', 'rows', 'notices': {공고 ID: {...}}, 'error', 'bad_lines'}.

    **예외를 내지 않는다**(2026-09-29 Codex 재검수 P1). 깨진 줄은 건너뛰고 bad_lines 로 센다 — 파일 한 줄 때문에
    서버 시작(app.boot)이 멈추면 조율 에이전트처럼 공고팀 코드를 직접 부르는 쪽까지 멈춘다. 파일을 아예 못 읽으면 error.
    """
    path = path or default_path()
    out = {'active': False, 'source': os.path.basename(os.path.dirname(path)), 'rows': 0, 'notices': {},
           'error': None, 'bad_lines': 0}
    if not os.path.exists(path):
        out['error'] = '신청자 유형 결과 파일이 없다: %s' % path
        return out
    try:
        with io.open(path, encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    llm = row.get('llm')
                    if not llm:
                        continue
                    info = dict(_info(llm), document_sha256=row.get('document_sha256'))
                    notice_id = row['notice_id']
                    # 공고 ID 가 목록·객체면 사전 키가 되지 못해 여기서 터진다 — 줄 단위로 걸러 낸다(Codex 재검수 P1-4)
                    if not isinstance(notice_id, str) or not notice_id:
                        raise TypeError('notice_id 는 문자열이어야 한다')
                    out['notices'][notice_id] = info
                except (ValueError, KeyError, TypeError, AttributeError):
                    out['bad_lines'] += 1
                    continue
                out['rows'] += 1
    except (OSError, UnicodeDecodeError) as exc:
        out['notices'], out['rows'] = {}, 0
        out['error'] = '신청자 유형 결과 파일을 읽지 못했다(%s): %s' % (type(exc).__name__, path)
        return out
    if out['bad_lines']:
        out['error'] = '결과 파일에서 읽지 못한 줄 %d개를 건너뛰었다: %s' % (out['bad_lines'], path)
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


def current_document_hashes(connection):
    """지금 공고문의 지문 {공고 ID: document_sha256}. 11단계가 판정할 때 쓰는 **같은 함수**로 만든다(2026-09-29).

    applicant_type_llm.load_population 이 공고 본문·지원대상·첨부 본문으로 LLM 에 보낼 문서를 만들고 그 해시를
    붙인다. 판정 행의 document_sha256 과 같으면 "지금 공고문을 보고 내린 판정"이다. 공고 2,525건 약 1.7초(9/29).
    문서가 비어 판정 대상이 아닌 공고는 없다(그 공고의 판정은 쓰지 않는다). DB 조회만 한다.
    """
    return {nid: item['document_sha256'] for nid, item in current_documents(connection).items()}


def current_documents(connection):
    """지금 공고문 {공고 ID: load_population 항목} — 발췌(document)·지문과 원문(target_text·body·attachments)이 함께 있다."""
    from experiments.sql_semantic import applicant_type_llm as atl
    return {item['notice_id']: item for item in atl.load_population(connection)}


_PRE_WORD = '예비창업'
_PRE_MENTION = re.compile(r'예\s*비\s*창\s*업')    # 글자 사이 공백·줄바꿈 허용("예비창\n업자"도 같은 말)
_MENTION_WINDOW = 10          # 보여 줄 문장을 고를 때 언급 앞뒤 몇 글자를 발췌와 대조하나


def _flat(text):
    return re.sub(r'\s+', '', text or '')


def _strong_no(info):
    c = info['pre_founder']
    return c['status'] == 'not_allowed' and c['strength'] == 'strong' and not info['varies']


def unread_pre_founder(item):
    """발췌(item['document']) 밖 원문에 '예비창업' 이 있으면 보여 줄 문장 조각, 없으면 None.

    **횟수로 판단한다**(2026-09-29 Codex 재재검수 P1). 공백·줄바꿈을 모두 지운 원문(지원대상·본문·첨부 전체)과
    발췌에서 '예비창업' 을 센다. 발췌는 원문 조각을 구분 표시와 함께 이어 붙인 것이라 원문보다 많을 수 없으므로,
    원문이 더 많으면 안 읽은 언급이 적어도 하나 있다. 예전에는 언급 앞뒤 10자가 발췌 **어딘가에** 있는지만 봐서,
    같은 문구가 읽은 곳·안 읽은 곳에 반복되면 읽은 것으로 착각했고 "예비창\\n업" 은 찾지 못했다.
    발췌 경계에 잘린 언급은 안 읽은 쪽으로 센다(낮추는 쪽이 안전).

    발췌는 **빈 줄(\\n\\n)로 나눈 조각마다** 따로 센다(2026-09-29 Codex 3차 재검수 P1). build_document() 는 첨부별
    조각을 빈 줄로 잇는데, 발췌 전체의 공백을 지우면 앞 첨부 끝 "예비" 와 다음 첨부 시작 "창업" 이 붙어 원문에 없는
    언급이 생기고, 그 가짜 1회가 안 읽은 진짜 1회를 가렸다. 한 조각 안에는 빈 줄이 없다(공백을 합쳐 만든다). 머리
    (지원대상·공고 개요)와 첨부 발췌 사이·한 첨부의 구간 사이에는 글자 표시("[공고 개요]"·"---")가 있어 붙지 않는다.
    나누기가 원문 한 곳을 둘로 쪼개는 경우(자격 구간을 못 찾아 원문 앞부분을 그대로 쓴 첨부)는 발췌 횟수가 줄어드는
    쪽이라 안전하다. 발췌를 만드는 함수는 바꾸지 않는다(지문이 바뀌면 전량 재판정이 된다).
    """
    texts = [item.get('target_text') or '', item.get('body') or ''] + list(item.get('attachments') or [])
    chunks = [_flat(c) for c in (item.get('document') or '').split('\n\n')]
    read = '|'.join(chunks)                      # 조각 사이에 글자를 넣어 문장 고르기에서도 붙지 않게
    if sum(_flat(t).count(_PRE_WORD) for t in texts) <= sum(c.count(_PRE_WORD) for c in chunks):
        return None
    last = None
    for text in texts:
        for m in _PRE_MENTION.finditer(text):
            snippet = ' '.join(text[max(0, m.start() - 40):m.end() + 40].split())
            if _flat(text[max(0, m.start() - _MENTION_WINDOW):m.end() + _MENTION_WINDOW]) not in read:
                return snippet                   # 앞뒤까지 발췌에 없는 언급 — 안 읽은 곳이 분명하다
            last = snippet
    return last                                  # 반복 문구라 어느 것인지 못 가리면 마지막 언급을 보여 준다


def mark_unread(notices, documents):
    """strong 불가 판정에 발췌 밖 확인 결과를 붙인 새 dict. documents 는 current_documents() 값. 원래 표는 바꾸지 않는다.

      unread_pre_founder   발췌 밖 원문에 '예비창업' 이 있다(보여 줄 문장)
      unverified_pre_founder  원문이 없거나(documents 없음·그 공고 없음) 판정 지문이 지금 공고문과 달라 확인하지 못했다
    둘 다 pre_founder() 가 'blocked' 대신 None(확인 필요)을 돌려준다 — 확인 못 한 불가로 빼지 않는다(Codex 재재검수 P2).
    """
    out = {}
    for nid, info in notices.items():
        if _strong_no(info):
            item = (documents or {}).get(nid)
            if item is None or info.get('document_sha256') != item.get('document_sha256'):
                info = dict(info, unverified_pre_founder=True)
            else:
                snippet = unread_pre_founder(item)
                if snippet:
                    info = dict(info, unread_pre_founder=snippet)
        out[nid] = info
    return out


def fresh_only(sources, current):
    """공고마다 **지금 공고문과 지문이 같은** 판정만 고른다. sources 는 우선순위 순서의 [(이름, 표)].

    (2026-09-29 Codex 재검수 P1 — 지문이 다르다는 것만으로는 어느 쪽이 새것인지 모른다. 지금 공고문과 대조해야 방향이 정해진다)
      · 지금 공고문과 같은 쪽을 쓴다. 둘 다 같으면 앞의 것(DB)
      · 어느 쪽도 같지 않으면 쓰지 않는다 → 그 공고는 '모름'(pre_founder() 가 None — 빼지도 되살리지도 않는다)
        공고문이 바뀐 뒤 11단계가 아직 다시 판정하지 못했거나(하루 상한·실패), 13단계가 못 올렸거나, 옛 파일인 경우다
      · 지금 공고문이 없는 공고(문서가 비었거나 notices 에서 사라짐)도 쓰지 않는다
    돌려주는 것: (notices, {'fresh': {이름: 건수}, 'stale': 건수, 'no_document': 건수})
    """
    notices, fresh, stale, no_document = {}, {name: 0 for name, _ in sources}, 0, 0
    ids = set()
    for _, table in sources:
        ids.update((table or {}).get('notices') or {})
    for nid in ids:
        now = current.get(nid)
        if now is None:
            no_document += 1
            continue
        for name, table in sources:
            info = ((table or {}).get('notices') or {}).get(nid)
            if info is not None and info.get('document_sha256') == now:
                notices[nid] = info
                fresh[name] += 1
                break
        else:
            stale += 1
    return notices, {'fresh': fresh, 'stale': stale, 'no_document': no_document}


def load_auto(connection=None, path=None, expected=None, current=None, documents=None):
    """서비스가 부르는 진입점(2026-09-28, 2026-09-29 지문 확인으로 다시 씀). 예외를 내지 않는다.

    판정은 공용 DB(배치 13단계가 올린 표)와 배치 PC 의 결과 파일(11단계 누적) 두 곳에 있다. 어느 쪽이든
    **지금 공고문의 지문과 같은 판정만** 쓴다(fresh_only). 이 판정은 '불가' 공고를 추천에서 빼는 데 쓰이므로,
    옛 판정을 쓰면 신청 가능한 공고가 잘못 빠진다(Codex 재검수 P1).
      auto(기본)  DB → 파일 순서로 공고마다 신선한 쪽. 파일이 없는 곳(EC2·조율 에이전트)은 DB 만으로 같은 확인을 한다
      db          DB 만. 연결이 없거나 읽기가 실패하면 error(기능이 꺼진다)
      file        파일만(개발용). 이 모드도 지문을 확인한다 — 지문을 구할 수 없으면 기능이 꺼진다(Codex 재검수 P1-3)
    current: {공고 ID: 지금 문서 지문}. 주지 않으면 connection 으로 계산한다(current_documents).
    documents: current_documents() 값(지금 공고문 원문). strong 불가 판정의 발췌 밖 언급을 이것으로 확인한다(mark_unread).
      connection 으로 지문을 계산할 때는 함께 얻는다. current 만 넘기고 documents 를 안 넘기면 확인할 수 없어
      strong 불가를 쓰지 않는다(확인 필요, Codex 재재검수 P2).
    **지문을 알 수 없으면 판정을 하나도 쓰지 않는다**(active False + error). 쓸 판정이 0건이어도 error 에 이유를 남긴다 — 판정을 안 쓰면 이 기능이 생기기 전과
    같은 결과이고(예비창업자 본문 판정으로 빼거나 되살리지 않음), 옛 판정으로 잘못 빼는 것보다 안전하다.
    expected: 서비스 공고 수. 요약 문구(note)에만 쓴다. 예전 95% 완전성 기준은 지문 확인으로 대신한다.
    """
    mode = (os.environ.get(SOURCE_ENV) or 'auto').lower()
    off = {'active': False, 'source': 'db:' + DB_TABLE, 'rows': 0, 'notices': {}, 'refreshed_from_file': 0,
           'stale': 0, 'bad_lines': 0, 'unread_pre_founder': 0, 'unverified_pre_founder': 0}
    if mode == 'db' and connection is None:
        return dict(off, error='DB 연결 없음 — 지금 공고문의 지문을 확인할 수 없어 판정을 쓰지 않는다')
    # 1) 지금 공고문의 지문 — **모든 모드에서** 먼저 구한다. 예전 file 모드는 지문 없이 파일 판정을 그대로 써서
    #    옛 '불가'로 공고를 뺄 수 있었다(2026-09-29 Codex 재검수 P1-3)
    if current is None and documents is not None:
        current = {nid: item['document_sha256'] for nid, item in documents.items()}
    if current is None:
        if connection is None:
            return dict(off, error='DB 연결 없음 — 지금 공고문의 지문을 확인할 수 없어 판정을 쓰지 않는다')
        try:
            documents = current_documents(connection)
            current = {nid: item['document_sha256'] for nid, item in documents.items()}
        except Exception as exc:
            return dict(off, error='지금 공고문의 지문을 계산하지 못해 판정을 쓰지 않는다(%s)' % type(exc).__name__)
    # 2) 판정 — auto 는 DB → 파일, db 는 DB 만, file 은 파일만(개발용). 어느 쪽이든 지문이 같은 것만 쓴다
    db = None
    if mode != 'file' and connection is not None:
        try:
            db = load_db(connection)
        except Exception as exc:
            if mode == 'db':
                return dict(off, error='DB 읽기 실패: %s' % type(exc).__name__)
            db = dict(off, error='DB 읽기 실패: %s' % type(exc).__name__)
    sources = [] if mode == 'file' else [('db', db)]
    file_table = None
    if mode != 'db':
        file_path = path or default_path()
        if mode == 'file' or os.path.exists(file_path):
            file_table = load(file_path)                  # 예외 없음 — 깨진 줄은 bad_lines, 파일이 없으면 error
            sources.append(('file', file_table))
    notices, stats = fresh_only(sources, current)
    notices = mark_unread(notices, documents)            # 원문이 없으면 strong 불가는 확인 못 함으로 둔다
    db_ok = bool(db and not db.get('error'))
    out = {'active': bool(notices), 'source': 'db:' + DB_TABLE if db_ok else (file_table or {}).get('source', 'file'),
           'rows': (db or {}).get('rows', 0), 'notices': notices, 'error': None,
           'refreshed_from_file': stats['fresh'].get('file', 0), 'stale': stats['stale'],
           'no_document': stats['no_document'], 'bad_lines': (file_table or {}).get('bad_lines', 0),
           'fresh_from_db': stats['fresh'].get('db', 0),
           'unread_pre_founder': sum(1 for i in notices.values() if i.get('unread_pre_founder')),
           'unverified_pre_founder': sum(1 for i in notices.values() if i.get('unverified_pre_founder'))}
    problems = [t['error'] for t in (db, file_table) if t and t.get('error')]
    if problems and not notices:
        out['error'] = '; '.join(problems)
    elif not notices:
        # 표가 비었거나 모두 지문이 달라 쓸 판정이 없다 — 기능이 꺼진 이유를 남긴다(boot_errors, Codex 재검수 P2-3)
        out['error'] = '쓸 수 있는 판정이 0건이다(DB %d행 · 파일 %d행 · 지문 다름 %d · 공고문 없음 %d)' % (
            out['rows'], (file_table or {}).get('rows', 0), stats['stale'], stats['no_document'])
    parts = ['지금 공고문과 지문이 같은 판정 %d건(DB %d · 파일 %d)' % (len(notices), out['fresh_from_db'],
                                                            out['refreshed_from_file'])]
    if mode == 'file':
        parts.insert(0, '파일만 쓴다(APPLICANT_TYPES_SOURCE=file, 개발용)')
    if expected:
        parts.append('공고 %d건 중' % expected)
    if stats['stale']:
        parts.append('지문이 달라 쓰지 않음 %d건' % stats['stale'])
    if out['unread_pre_founder']:
        parts.append('발췌 밖 예비창업 언급으로 불가 → 확인 필요 %d건' % out['unread_pre_founder'])
    if out['unverified_pre_founder']:
        parts.append('원문이 없어 발췌 밖을 확인 못 한 불가 → 확인 필요 %d건' % out['unverified_pre_founder'])
    if problems and notices:
        parts.append('참고: ' + '; '.join(problems))
    out['note'] = ' · '.join(parts)
    return out


def pre_founder(table, notice_id):
    """예비창업자에 대한 판정: 'blocked' | 'allowed' | 'implied_no' | None(모름·쓰지 않음)."""
    info = ((table or {}).get('notices') or {}).get(notice_id)
    if not info:
        return None
    c = info['pre_founder']
    if _strong_no(info):
        # 발췌 밖 원문에도 예비창업자 언급이 있으면 빼지 않는다 — 확인 필요(Codex 재검수 P1-2, A안)
        return None if info.get('unread_pre_founder') or info.get('unverified_pre_founder') else 'blocked'
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
        if info.get('unread_pre_founder') and _strong_no(info):
            return None, '예비창업자 불가로 읽었으나 확인 필요(공고 본문)', \
                ('판정에 쓴 발췌의 근거: "%s". 그런데 판정에 쓰지 않은 원문에도 예비창업자 언급이 있습니다: "%s". '
                 '원문을 확인하세요.' % (ev, info['unread_pre_founder']))
        if info.get('unverified_pre_founder') and _strong_no(info):
            return None, '예비창업자 불가로 읽었으나 확인 필요(공고 본문)', \
                ('판정에 쓴 발췌의 근거: "%s". 발췌 밖 원문을 확인하지 못했습니다. 원문을 확인하세요.' % ev)
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
