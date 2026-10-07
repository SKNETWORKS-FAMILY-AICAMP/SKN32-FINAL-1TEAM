# -*- coding: utf-8 -*-
"""공고문에서 가점(가산점) 조건을 뽑는다 — 조율 요청서 3.2, docs/notice_api/03_bonus (2026-10-06~).

  python -m collect.extract_bonus --sample 30            표본 30건. DB 에 쓰지 않고 reports/ 에 결과를 남긴다
  python -m collect.extract_bonus --notice <공고 ID>      공고 하나만(화면에 출력)
  python -m collect.extract_bonus --sample 30 --plan     부르지 않고 대상·예상 비용만 센다
  python -m collect.extract_bonus --ids A,B,C            지정한 공고만. DB 에 쓰지 않고 reports/ 에 남긴다
  python -m collect.extract_bonus --all [--plan]         열린 공고 전량 → 공용 DB notice_bonus (같은 문서·버전은 건너뜀)

무엇을 뽑나
  신청 기업이 **선정 평가에서 더 받는 점수**(가점·가산점)와 그 조건. 항목마다 이름·점수·종류·조건·근거 원문.
  감점·배점(평가 항목 자체)·지원 금액 우대·융자 금리 우대는 가점이 아니다.
  종류(kind)는 웹 입력으로 판단할 수 있는지에 맞춰 나눴다 — 3-3 단계가 신청자 정보와 맞춰 본다.

절대 하지 않는 것(extract_conditions 와 같은 원칙)
  · 문서에 없는 점수를 지어내지 않는다. 점수가 적혀 있지 않으면 null 이다.
  · 근거(quote)가 LLM 에 보낸 문서에 실제로 없으면 그 항목을 버린다(verify).
  · 점수가 근거 문장에 숫자로 없으면 점수를 null 로 낮춘다 — 표를 읽고 계산한 값은 믿지 않는다.

토큰을 줄이는 방법: 공고문 전체(최대 수만 자) 대신 '가점·가산점·우대' 주변만 잘라 보낸다(최대 MAX_CHARS).
"""
import argparse
import hashlib
import io
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone

from shared import config
from shared import store_mysql

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODEL, EFFORT = 'gpt-5.6-luna', 'medium'
# v2(2026-10-06): 선정 뒤 혜택 제외 규칙, 점수 검사 완화, 지역 상한, status · v3: 청년(대표자 나이) ↔ 청년 고용 구분
# v4(2026-10-06 Codex 검수 반영): group(한 점수를 나눠 가지는 선택 조건)·program(세부사업)·extra_conditions(추가 조건)
#   ·points_source(떨어진 배점 칸), 대상을 '우대·우선 선정'까지, 발췌 12,000자·가점 구간 먼저, 근거 위치 검사 강화
PROMPT_VERSION = 'v4'
EXTRACTOR_VERSION = 'extract_bonus/%s %s %s' % (PROMPT_VERSION, MODEL, EFFORT)
PRICES = {'gpt-5.6-luna': (0.20, 1.20)}        # 2026-09-22 OpenAI 요금 페이지 표준 단가($/100만 토큰) — 추정용
SEED = 20261006

# 가점 구간을 찾는 말. 자르기는 '가점·가산점' 주변을 먼저(PRIMARY_RE) 담고 남은 자리에 '우대·우선 선정' 주변을 담는다.
# 대상 고르기도 '우대·우선 선정'까지 본다 — "여성기업 우대: 평가 시 2점"만 적힌 공고를 0점으로 두지 않는다
# (2026-10-06 Codex 검수 P2-3). 발췌가 가점 구간을 다 담지 못하면 '가점 없음'을 확정하지 않는다(P2-2)
PRIMARY_RE = re.compile(r'가\s*점|가\s*산\s*점')
SLICE_RE = re.compile(r'가\s*점|가\s*산\s*점|우대|우선\s*(?:선정|지원|선발)')
TARGET_RE = SLICE_RE
WINDOW_BEFORE, WINDOW_AFTER, MAX_CHARS = 200, 700, 12000

KINDS = ('여성', '장애인', '청년', '지역', '인증', '고용', '수출', '특허', '이전실적', '재창업', '업종', '기타')
CERTS = ('여성기업', '장애인기업', '사회적기업', '예비사회적기업', '협동조합', '소셜벤처', '벤처기업', '이노비즈',
         '메인비즈', '연구소기업', '기업부설연구소', '수출기업', '가족친화기업', '청년친화강소기업')
REGIONS = ('서울', '부산', '대구', '인천', '대전', '울산', '세종', '경기', '강원', '충북', '충남', '전북',
           '전남', '광주', '경북', '경남', '제주')

SCHEMA = {
    'name': 'notice_bonus',
    'strict': True,
    'schema': {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'has_bonus': {'type': 'boolean',
                          'description': '신청 기업이 선정 평가에서 더 받는 가점·가산점 제도가 문서에 있으면 true'},
            'max_total_points': {'type': ['number', 'null'],
                                 'description': '가점 합계 한도(예: "가점은 최대 5점" → 5). 없으면 null'},
            'bonus_info': {'type': ['string', 'null'],
                           'description': '가점 조건이 적힌 부분을 원문 그대로(여러 곳이면 이어 붙임, 800자 이내). 없으면 null'},
            'items': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'additionalProperties': False,
                    'properties': {
                        'name': {'type': 'string', 'description': '짧은 항목 이름. 예: "여성기업", "도내 소재 기업", "청년 대표자"'},
                        'points': {'type': ['number', 'null'],
                                   'description': '이 항목의 가점. 문서에 숫자로 적혀 있을 때만. 없으면 null'},
                        'kind': {'type': 'string', 'enum': list(KINDS)},
                        'certs': {'type': 'array', 'items': {'type': 'string', 'enum': list(CERTS)},
                                  'description': 'kind 가 인증일 때 해당 인증(목록에 있는 것만). 아니면 빈 배열'},
                        'regions': {'type': 'array', 'items': {'type': 'string', 'enum': list(REGIONS)},
                                    'description': 'kind 가 지역일 때 시·도. 아니면 빈 배열'},
                        'detail': {'type': ['string', 'null'],
                                   'description': '조건 세부(예: "만 39세 이하 대표자", "강남구 소재"). 없으면 null'},
                        'quote': {'type': 'string', 'description': '이 항목의 근거 문장 원문 그대로'},
                        'points_source': {'type': ['string', 'null'],
                                          'description': '점수가 quote 밖(표의 배점 칸, "각 1점" 같은 공통 배점)에 적혀 있으면 '
                                                         '그 점수가 적힌 원문 조각 그대로. quote 안에 점수가 있으면 null'},
                        'group': {'type': 'string',
                                  'description': '한 점수를 나눠 가지는 항목끼리 같은 이름(예: "g1"). 따로 더해 받는 항목은 다른 이름'},
                        'program': {'type': ['string', 'null'],
                                    'description': '세부사업마다 가점이 다르면 이 항목이 속한 세부사업 이름. 공고 전체 공통이면 null'},
                        'extra_conditions': {'type': ['string', 'null'],
                                             'description': '인증 보유·지역 소재·대표자 성별·나이 말고 함께 갖춰야 하는 조건 원문'
                                                            '(기간·유효기간·역할·제외 대상·"그리고" 조건). 없으면 null'},
                    },
                    'required': ['name', 'points', 'kind', 'certs', 'regions', 'detail', 'quote', 'points_source',
                                 'group', 'program', 'extra_conditions'],
                },
            },
            'uncertain': {'type': 'array', 'items': {'type': 'string'},
                          'description': '판단하지 못한 것. 예: "세부사업별로 가점이 다름"'},
        },
        'required': ['has_bonus', 'max_total_points', 'bonus_info', 'items', 'uncertain'],
    },
}

SYSTEM = """너는 정부 지원사업 공고문에서 **가점(가산점)** 조건만 뽑아내는 도구다.

가점이란: 신청 기업이 선정 평가에서 기본 점수에 **더 받는 점수**다. 예: "여성기업 가점 2점", "도내 소재 기업 1점 가산".

규칙
1. 문서에 적혀 있는 것만 쓴다. 추측하거나 상식으로 채우지 않는다.
2. 가점이 아닌 것은 넣지 않는다.
   · 감점(벌점), 평가 항목과 배점("사업성 30점") — 기본 평가다
   · 지원 금액·보조 비율 우대, 융자 금리 우대, 수수료 감면 — 점수가 아니다
   · 신청 자격 조건 그 자체("○○ 기업만 신청 가능")
   · 이 공고에 **선정된 뒤 받는 혜택**("선정 기업은 다른 사업 평가 시 가점", "인증 기업은 R&D 신청 시 가점 부여")
     — 이 공고의 선정 평가에서 더 받는 점수가 아니다
3. "우대", "우선 선정"처럼 점수 없이 유리하게 본다는 말은 점수 없는 항목(points=null)으로 넣는다.
   단 평가 점수와 관계없는 지원 금액 우대는 넣지 않는다.
4. points 는 그 항목에 대해 문서에 숫자로 적힌 점수만 쓴다. "최대 3점", "1~3점"이면 가장 큰 값.
   표에서 계산하거나 합쳐서 만든 값은 쓰지 않는다. 숫자가 없으면 null. 표의 연번·번호(1, 2, 3 …)는 점수가 아니다.
   **points 에 숫자를 썼는데 그 숫자가 quote 안에 없으면 반드시 points_source 를 채운다.** 점수가 quote 와 떨어진 곳
   (표의 배점 칸, 병합된 칸, "각 1점" 같은 공통 배점)에 있으면 그 점수가 적힌 원문 조각을 points_source 에 그대로 넣는다.
   points_source 가 없으면 코드가 점수를 버린다.
5. 항목은 조건 하나씩 나눈다. "여성기업 또는 장애인기업 2점"은 두 항목(각 2점)이지만 **같은 group** 이다 — 둘 다 해당해도 2점이다.
   같은 group 은 다음 두 경우뿐이다.
   · 한 문장·한 표 행이 조건 여러 개를 "또는"·쉼표로 나열하고 그 행에 점수가 하나다("벤처, 이노비즈, 메인비즈 기업 : 10점").
   · 문서가 그중 **하나만** 인정한다고 적었다("중복 시 1개만 인정", "택1").
   그 밖은 모두 서로 다른 group 이다. 특히 다음은 같은 group 이 아니다.
   · 행마다 따로 적힌 항목이 같은 배점 칸(병합된 칸, "각 1점", "항목당 3점")을 쓰는 경우 — 각 행이 따로 더해진다.
   · "최대 5점", "최대 2개까지 인정"처럼 합계를 제한하는 경우 — 이것은 max_total_points 로 적는다.
   group 이름은 "g1", "g2" 처럼 짧게.
6. kind 는 아래 중 하나다.
   여성(대표자가 여성·여성기업) · 장애인(장애인기업·장애인 고용 대표) · 청년(대표자 나이) · 지역(특정 지역 소재)
   · 인증(벤처기업·이노비즈 등 인증·확인서 보유) · 고용(일자리 창출·고용 증가·고용 우수) · 수출(수출 실적)
   · 특허(특허·지식재산 보유) · 이전실적(수상·이전 지원사업 선정·교육 수료) · 재창업 · 업종(특정 업종·분야) · 기타
   여성기업 인증은 kind=여성, certs=["여성기업"]. 장애인기업 인증은 kind=장애인, certs=["장애인기업"].
   청년은 **대표자(신청자) 본인의 나이**일 때만이다. "청년 고용 인원 30% 이상", "청년 채용"은 고용이다.
7. quote 에는 근거 문장을 원문 그대로 넣는다. 요약하거나 고치지 않는다. "제외"·"아닌" 같은 말을 빼고 이어 붙이지 않는다.
8. 세부사업마다 가점이 다르면 모두 넣고 program 에 세부사업 이름을 적는다. 공고 전체에 공통이면 program=null.
   detail 에는 조건 세부를 적는다.
9. 가점 제도가 없으면 has_bonus=false, items=[], bonus_info=null 이다.
10. extra_conditions: 인증 보유·지역 소재·대표자 성별·나이 말고 함께 갖춰야 하는 조건이 있으면 원문 그대로 짧게 적는다.
    예: "최근 3년 이내 취득", "마감일 기준 유효한 인증", "주관연구개발기관인 경우", "개인사업자 제외", "본사 및 공장 모두 도내".
    없으면 null.
11. max_total_points 는 "가점은 최대 5점", "가점 합계 10점 이내"처럼 가점 합계 한도가 문서에 적혀 있을 때만 쓴다."""


# ── 문서 만들기 ──────────────────────────────────────────────
def _flat(text):
    return ' '.join(str(text or '').split())


def _windows(text, regex):
    """regex 가 나온 곳 주변(앞 WINDOW_BEFORE · 뒤 WINDOW_AFTER) 구간들을 겹치면 합쳐 돌려준다."""
    spans = sorted((max(0, m.start() - WINDOW_BEFORE), min(len(text), m.end() + WINDOW_AFTER))
                   for m in regex.finditer(text))
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [tuple(x) for x in merged]


def _uncovered(span, chosen):
    """span 중 이미 고른 구간(chosen)에 들어 있지 않은 글자 수."""
    start, end = span
    covered = 0
    for s0, e0 in chosen:
        covered += max(0, min(end, e0) - max(start, s0))
    return (end - start) - covered


def _join(text, spans):
    spans = sorted(spans)
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return '\n---\n'.join(text[s0:e0] for s0, e0 in merged)


def slice_bonus(text, max_chars=MAX_CHARS):
    """가점·우대 주변만 잘라낸다(가점 구간 먼저). 없으면 빈 문자열."""
    return build_parts([('', text)], max_chars)[0][0][1] if SLICE_RE.search(_flat(text)) else ''


def build_parts(sources, max_chars=MAX_CHARS):
    """[(이름, 원문)] → ([(이름, 발췌)], complete).

    '가점·가산점' 주변을 모든 출처에서 먼저 담고, 남은 자리에 '우대·우선 선정' 주변을 담는다(2026-10-06 Codex 검수 P2-2 —
    앞쪽 금리 우대 구간이 자리를 다 써서 뒤쪽 가점 배점표가 빠진 공고가 있었다). 가점 구간을 다 담지 못하면 complete=False.
    """
    flat = [(label, _flat(text)) for label, text in sources]
    chosen = [[] for _ in flat]
    budget, complete = max_chars, True
    for regex in (PRIMARY_RE, SLICE_RE):
        for i, (_label, text) in enumerate(flat):
            for span in _windows(text, regex):
                need = _uncovered(span, chosen[i])
                if need <= 0:
                    continue
                if need > budget:
                    if regex is PRIMARY_RE:
                        complete = False
                    if budget > 0:
                        chosen[i].append((span[0], span[0] + min(span[1] - span[0], budget)))
                        budget = 0
                    continue
                chosen[i].append(span)
                budget -= need
    parts = [(label, _join(text, chosen[i])) for i, (label, text) in enumerate(flat) if chosen[i]]
    return parts, complete


def build(item, max_chars=MAX_CHARS):
    """공고 개요·지원대상 원문·첨부에서 가점 주변을 잘라 붙인다. 첨부는 긴 것부터. → (문서, 가점 구간을 다 담았나)"""
    sources = [('공고 개요·지원대상', ' '.join(x for x in (item.get('body'), item.get('target_text')) if x))] + \
        [('공고문 첨부', t) for t in item.get('attachments') or []]
    parts, complete = build_parts(sources, max_chars)
    return '\n\n'.join('[%s 발췌]\n%s' % (label, piece) for label, piece in parts if piece), complete


def build_document(item, max_chars=MAX_CHARS):
    return build(item, max_chars)[0]


def doc_hash(document):
    return hashlib.sha256(document.encode('utf-8')).hexdigest()


def pick_targets(connection, notice_ids=None, open_only=True, with_no_mention=False):
    """가점·가산점이 나오는 공고와 그 문서. 첨부는 지금 공고에 달린 것(na.active)·추출 성공분만.

    with_no_mention=True 면 **첨부 본문이 있는데 가점·가산점 말이 없는 공고**도 item['mention']=False 로 함께 돌려준다
    (LLM 을 부르지 않고 no_mention 으로 저장한다). 첨부 본문이 없는 공고(K-Startup 등)는 어느 쪽에도 넣지 않는다 — 모름.
    """
    where, args = [], []
    if notice_ids:
        where.append('n.notice_id IN (%s)' % ','.join(['%s'] * len(notice_ids)))
        args.extend(notice_ids)
    elif open_only:
        where.append("n.recruitment_status <> 'closed'")
    with connection.cursor() as cursor:
        cursor.execute('SELECT n.id, n.notice_id, n.title, n.body, n.target_text FROM notices n'
                       + (' WHERE ' + ' AND '.join(where) if where else '') + ' ORDER BY n.notice_id', tuple(args))
        notices = cursor.fetchall()
        cursor.execute("""SELECT na.notice_fk, at.extracted_text FROM notice_attachments na
                            JOIN attachment_texts at ON at.attachment_fk = na.id
                           WHERE na.active AND at.last_status = 'ok' AND at.extracted_text IS NOT NULL
                           ORDER BY na.notice_fk, at.text_chars DESC, na.id""")
        files = {}
        for fk, text in cursor.fetchall():
            files.setdefault(fk, []).append(text)
    from search import content_version
    versions = content_version.load(connection)
    out = []
    for pk, nid, title, body, target in notices:
        item = {'notice_id': nid, 'title': title or '', 'body': body or '', 'target_text': target or '',
                'attachments': files.get(pk, []), 'content_version': versions.get(nid)}
        item['mention'] = bool(TARGET_RE.search(' '.join([item['body'], item['target_text']] + item['attachments'])))
        if item['mention'] or (with_no_mention and item['attachments']):
            out.append(item)
    return out


# ── 부르기 · 검사 ────────────────────────────────────────────
def ask(client, title, document):
    started = time.time()
    response = client.chat.completions.create(
        model=MODEL, reasoning_effort=EFFORT,
        messages=[{'role': 'system', 'content': SYSTEM},
                  {'role': 'user', 'content': '공고 제목: %s\n\n공고문 발췌:\n%s' % (title, document)}],
        response_format={'type': 'json_schema', 'json_schema': SCHEMA})
    data = json.loads(response.choices[0].message.content)
    usage = response.usage
    return data, {'in': usage.prompt_tokens, 'out': usage.completion_tokens,
                  'ms': round((time.time() - started) * 1000), 'model': getattr(response, 'model', None)}


# 근거 문장 속 숫자 중 점수로 볼 수 있는 것 — 'N점' 또는 단위 없이 홀로 선 숫자(표: "여성기업 해당 10", "(1)").
# 기간·비율·금액·개수처럼 단위가 붙은 숫자("3년", "30%", "5개", "1억")는 점수가 아니다(v1 표본 30건, 2026-10-06)
# 단위는 숫자 바로 뒤에 붙은 것만 본다("2 기업"의 '기'는 단위가 아니다). '점'만 띄어 써도 인정한다
_NUMBER_RE = re.compile(r'(?<![\d.])(\d+(?:\.\d+)?)(?![\d.])(\s*점|[년개월일세%명회차억만천원배위등호기건종인평㎡]?)')
_NEG_RE = re.compile(r'제외|미해당|해당\s*없|불가|아닌|않는|않은|미포함')
NEAR_CHARS = 600            # 떨어진 배점 칸(points_source)은 근거에서 이만큼 안에 있어야 한다
_TOTAL_WORDS = re.compile(r'최대|한도|이내|까지|상한|합계|합산|총|초과')


def _points_in(text, leading=False):
    """점수로 볼 수 있는 숫자들(2026-10-06 Codex 검수 P1-2).

    'N점'과 괄호 속 숫자("지역화폐 가맹점(1)")는 늘 본다. 그 밖의 단위 없는 숫자는 'N점'이 없을 때만 보고,
    맨 앞의 숫자는 표 연번("1 여성기업 가점")으로 보고 뺀다. leading=True 면 맨 앞 숫자도 본다 — 떨어진 배점 칸
    (points_source, "5 (우대한도 적용)")은 맨 앞이 점수다.
    """
    flat = _flat(text)
    with_unit, paren, bare = set(), set(), set()
    for m in _NUMBER_RE.finditer(flat):
        unit, value = m.group(2).strip(), float(m.group(1))
        if unit == '점':
            with_unit.add(value)
        elif unit == '':
            if flat[m.start() - 1:m.start()] == '(' and flat[m.end():m.end() + 1] == ')' and m.start() > 1:
                paren.add(value)
            elif leading or flat[:m.start()].strip(' (|·ㆍ-') != '':
                bare.add(value)
    return with_unit | paren if (with_unit or paren) else bare


def _gap(a, b):
    return max(0, max(a[0], b[0]) - min(a[1], b[1]))


def locate(quote, document, near=None):
    """근거가 문서(_flat 기준)에 있으면 (시작, 끝), 없으면 None. near=(시작, 끝)이면 그 구간에서 가장 가까운 곳."""
    found = locate_all(quote, document)
    if not found:
        return None
    if near is None:
        return found[0]
    return min(found, key=lambda span: _gap(span, near))


def locate_all(quote, document):
    """근거가 문서(_flat 기준)에 나오는 모든 자리 [(시작, 끝)].

    ① 공백만 다르고 한 줄로 이어져 있으면 **실제로 일치한 자리**를 돌려준다(2026-10-06 Codex 검수 P1-2 — 전에는 첫 단어가
       처음 나온 자리에서 잘라, 다른 줄의 점수로 검사했다).
    ② 표가 글자로 바뀌면 칸 내용이 뒤섞인다("…인증수출자 인증서 4 1 제12조에 따른…"). LLM 은 표를 읽고 칸을 다시 이어
       붙이므로, 근거의 단어들이 **같은 순서로** 모두 나오고 그 구간이 근거 길이의 2배 + 60자 안이면 인정한다(v1 표본 7건).
       단 근거에 없는 '제외·아닌' 같은 말이 그 구간에 끼어 있으면 인정하지 않는다(뜻이 뒤집힌 재구성).
    """
    words = _flat(quote).split()
    doc = _flat(document)
    if not words:
        return []
    joined = ''.join(words)
    index = [i for i, ch in enumerate(doc) if ch != ' ']
    compact = ''.join(doc[i] for i in index)
    found = []
    k = compact.find(joined)
    while k >= 0:
        found.append((index[k], index[k + len(joined) - 1] + 1))
        k = compact.find(joined, k + 1)
    if not found:
        limit = 2 * len(_flat(quote)) + 60
        quote_negated = bool(_NEG_RE.search(_flat(quote)))
        pos = doc.find(words[0])
        while pos >= 0:
            cur, ok = pos + len(words[0]), True
            for w in words[1:]:
                nxt = doc.find(w, cur)
                if nxt < 0 or nxt - pos > limit:
                    ok = False
                    break
                cur = nxt + len(w)
            if ok and (quote_negated or not _NEG_RE.search(doc[pos:cur])):
                found.append((pos, cur))
            pos = doc.find(words[0], pos + 1)
    return found


def find_quote(quote, document):
    """근거가 문서에 있으면 그 원문 구간 글자, 없으면 None."""
    span = locate(quote, document)
    return None if span is None else _flat(document)[span[0]:span[1]]


def _total_supported(total, doc):
    """가점 합계 한도(N점)가 문서에 '최대·한도·이내…'와 '가점' 가까이 적혀 있나(Codex 검수 P1-2 — 한도도 근거를 본다)."""
    for m in re.finditer(r'(?<![\d.])(\d+(?:\.\d+)?)\s*점', doc):
        if float(m.group(1)) != float(total):
            continue
        around = doc[max(0, m.start() - 60):m.end() + 30]
        if _TOTAL_WORDS.search(around) and PRIMARY_RE.search(around):
            return True
    return False


def verify(data, document, complete=True):
    """LLM 결과를 문서와 대조한다. (고친 결과, 버린 이유 목록).

    · 근거(quote)가 문서에 없으면 항목을 버린다(공백 차이는 무시). 위치는 실제로 일치한 자리(locate).
    · 점수는 근거 구간에, 아니면 근거 가까이(NEAR_CHARS) 있는 points_source 구간에 점수로 있어야 한다. 아니면 null.
    · 점수가 0 이하·100 초과·유한하지 않으면 null.
    · 지역이 4곳 이상이면 비운다(전국을 다 적은 것은 지역 가점이 아니다).
    · 가점 합계 한도는 문서에 한도로 적혀 있을 때만 남긴다.
    · status: 'none'(LLM 이 가점 없다고 봄) · 'found'(검사를 통과한 항목이 있음)
              · 'unverified'(근거가 문서와 맞지 않아 모두 버림, 또는 발췌가 가점 구간을 다 담지 못했는데 '없음'이라 함 — 모름)
    """
    doc = _flat(document)
    problems, items = [], []
    for it in data.get('items') or []:
        quote = _flat(it.get('quote'))
        span = locate(quote, doc) if quote else None
        if span is None:
            problems.append('근거가 문서에 없어 버림: %s' % (it.get('name') or '')[:40])
            continue
        pts = it.get('points')
        source = _flat(it.get('points_source')) or None
        if pts is not None:
            if not isinstance(pts, (int, float)) or not (0 < pts <= 100):
                problems.append('점수 범위 밖이라 null: %s' % it.get('name'))
                pts = None
            else:
                ok = float(pts) in _points_in(doc[span[0]:span[1]])
                if not ok and source:
                    # 근거·배점 칸이 문서에 여러 번 나오면 서로 가장 가까운 짝을 본다(표본 F06 — 같은 문구가 앞쪽 설명에도 있었다)
                    pairs = [(_gap(q, s0), q, s0) for q in locate_all(quote, doc) for s0 in locate_all(source, doc)
                             if float(pts) in _points_in(doc[s0[0]:s0[1]], leading=True)]
                    if pairs:
                        gap, span, _src = min(pairs)
                        ok = gap <= NEAR_CHARS
                if not ok:
                    problems.append('점수가 근거에 없어 null: %s(%s)' % (it.get('name'), pts))
                    pts = None
        kind = it.get('kind') if it.get('kind') in KINDS else '기타'
        regions = [r for r in it.get('regions') or [] if r in REGIONS]
        if len(regions) > 3:
            problems.append('지역이 %d곳이라 비움: %s' % (len(regions), it.get('name')))
            regions = []
        items.append(dict(it, quote=quote, points=pts, kind=kind, points_source=source,
                          group=_flat(it.get('group')) or None, program=_flat(it.get('program')) or None,
                          extra_conditions=_flat(it.get('extra_conditions')) or None,
                          certs=[c for c in it.get('certs') or [] if c in CERTS], regions=regions))
    has_bonus = bool(data.get('has_bonus')) and bool(items)
    raw_found = bool(data.get('has_bonus')) or bool(data.get('items'))
    status = 'found' if has_bonus else ('unverified' if raw_found else 'none')
    if status == 'none' and not complete:
        problems.append('발췌가 가점 구간을 다 담지 못해 가점 없음을 확정하지 않음')
        status = 'unverified'
    total = data.get('max_total_points')
    if total is not None and not (isinstance(total, (int, float)) and 0 < total <= 100):
        total = None
    if total is not None and not _total_supported(total, doc):
        problems.append('가점 합계 한도(%s)가 문서에 한도로 없어 null' % total)
        total = None
    # 가점 원문(bonus_info)도 문서와 대조한다. 맞지 않으면 항목 근거를 이어 붙인 것으로 바꾼다(공고 상세 창구에 나간다)
    info = _flat(data.get('bonus_info')) or None
    if info and locate(info, doc) is None:
        problems.append('가점 원문이 문서와 맞지 않아 항목 근거로 바꿈')
        info = None
    if has_bonus and not info:
        info = ' / '.join(dict.fromkeys(i['quote'] for i in items))[:800]
    return dict(data, has_bonus=has_bonus, status=status, items=items if has_bonus else [],
                max_total_points=total, bonus_info=info if has_bonus else None), problems


# ── 실행 ────────────────────────────────────────────────────
def _client():
    import openai
    return openai.OpenAI(api_key=config.require('OPENAI_API_KEY'))


def estimate(items):
    """부르기 전 예상 비용(추정). 입력은 글자 수 ÷ 1.6(한글 토큰 근사), 출력은 추론 포함 2,000토큰 가정."""
    price_in, price_out = PRICES[MODEL]
    tok_in = sum(len(build_document(i)) / 1.6 + 900 for i in items)
    return tok_in / 1e6 * price_in + len(items) * 2000 / 1e6 * price_out


def run_one(client, item):
    document, complete = build(item)
    data, usage = ask(client, item['title'], document)
    fixed, problems = verify(data, document, complete)
    price_in, price_out = PRICES[MODEL]
    return {'notice_id': item['notice_id'], 'title': item['title'], 'document_sha256': doc_hash(document),
            'content_version': item.get('content_version'), 'document_complete': complete,
            'document_chars': len(document), 'extractor_version': EXTRACTOR_VERSION, 'llm_raw': data,
            'result': fixed, 'problems': problems, 'usage': usage,
            'cost_usd': round(usage['in'] / 1e6 * price_in + usage['out'] / 1e6 * price_out, 6)}


def run_sample(n, plan=False, workers=4, seed=SEED, ids=None):
    """표본 n건(seed 로 섞음) 또는 지정한 공고(ids)를 뽑아 reports/ 에만 남긴다. DB 에 쓰지 않는다."""
    conn = store_mysql.connect()
    try:
        pool = pick_targets(conn, notice_ids=ids) if ids else pick_targets(conn)
    finally:
        conn.close()
    if ids:
        items = pool
    else:
        random.Random(seed).shuffle(pool)
        items = pool[:n]
    print('가점·가산점이 나오는 열린 공고 %d건 중 표본 %d건 · 예상 비용 약 $%.3f(추정)' % (len(pool), len(items), estimate(items)))
    if plan:
        return None
    from concurrent.futures import ThreadPoolExecutor
    client = _client()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    outdir = os.path.join(ROOT, 'reports', 'bonus_sample_%s' % stamp)
    os.makedirs(outdir)
    rows, failures = [], []
    with ThreadPoolExecutor(max_workers=workers) as pool_ex:
        futures = {pool_ex.submit(run_one, client, it): it for it in items}
        for fut in futures:
            it = futures[fut]
            try:
                rows.append(fut.result())
            except Exception as exc:                    # 실패는 기록만 하고 계속한다(키·주소를 남기지 않는다)
                failures.append({'notice_id': it['notice_id'], 'error': type(exc).__name__})
    rows.sort(key=lambda r: r['notice_id'])
    with io.open(os.path.join(outdir, 'results.jsonl'), 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    meta = {'run_at': stamp, 'model': MODEL, 'effort': EFFORT, 'extractor_version': EXTRACTOR_VERSION, 'seed': seed,
            'pool': len(pool), 'sample': len(items), 'done': len(rows), 'failures': failures,
            'tokens_in': sum(r['usage']['in'] for r in rows), 'tokens_out': sum(r['usage']['out'] for r in rows),
            'cost_usd': round(sum(r['cost_usd'] for r in rows), 4), 'price_basis': '2026-09-22 OpenAI 표준 단가(추정)'}
    with io.open(os.path.join(outdir, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print('완료 %d건 · 실패 %d건 · 비용 약 $%.4f(추정) → %s' % (len(rows), len(failures), meta['cost_usd'], outdir))
    return outdir


# ── 전량 추출 · 저장 (3-2) ───────────────────────────────────
NO_MENTION_HASH = doc_hash('')        # 가점 말이 없는 공고 — 보낸 문서가 없다


def no_mention_row(item):
    """첨부를 읽었으나 가점·가산점 말이 없는 공고 — LLM 을 부르지 않는다."""
    return {'notice_id': item['notice_id'], 'title': item['title'], 'document_sha256': NO_MENTION_HASH,
            'content_version': item.get('content_version'), 'document_chars': 0, 'extractor_version': EXTRACTOR_VERSION, 'llm_raw': None,
            'result': {'status': 'no_mention', 'has_bonus': False, 'max_total_points': None, 'bonus_info': None,
                       'items': [], 'uncertain': []},
            'problems': [], 'usage': {'in': 0, 'out': 0, 'ms': 0, 'model': None}, 'cost_usd': 0.0}


def save(connection, row):
    """notice_bonus 에 한 건 넣거나 바꾼다. 커밋은 부르는 쪽이 한다."""
    res = row['result']
    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO notice_bonus (notice_id, status, max_total_points, bonus_info, items, uncertain, problems,
                                         document_sha256, content_version, extractor_version,
                                         prompt_tokens, completion_tokens)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE status = VALUES(status), max_total_points = VALUES(max_total_points),
                   bonus_info = VALUES(bonus_info), items = VALUES(items), uncertain = VALUES(uncertain),
                   problems = VALUES(problems), document_sha256 = VALUES(document_sha256),
                   content_version = VALUES(content_version), extractor_version = VALUES(extractor_version), prompt_tokens = VALUES(prompt_tokens),
                   completion_tokens = VALUES(completion_tokens), extracted_at = CURRENT_TIMESTAMP(6)""",
            (row['notice_id'], res['status'], res.get('max_total_points'), res.get('bonus_info'),
             json.dumps(res.get('items') or [], ensure_ascii=False),
             json.dumps(res.get('uncertain') or [], ensure_ascii=False),
             json.dumps(row.get('problems') or [], ensure_ascii=False),
             row['document_sha256'], row.get('content_version'), row['extractor_version'], row['usage']['in'] or None, row['usage']['out'] or None))


def stored(connection):
    """{notice_id: (document_sha256, extractor_version, content_version)} — 이미 저장된 것."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT notice_id, document_sha256, extractor_version, content_version FROM notice_bonus')
        return {nid: (sha, ver, cv) for nid, sha, ver, cv in cursor.fetchall()}


def plan_work(items, done):
    """(부를 것, 가점 말 없는 것, 그대로 둘 것) — 발췌 지문·추출기 버전·공고 내용 지문이 모두 같으면 다시 하지 않는다.

    공고 내용 지문(search/content_version)까지 보는 것은 발췌 밖이 바뀐 경우("추가조건" → "제외조건")와
    가점 말이 없는 공고의 원문이 바뀐 경우도 다시 보기 위해서다(2026-10-06 Codex 검수 P2-4)."""
    call, quiet, keep = [], [], []
    for it in items:
        sha = doc_hash(build_document(it)) if it['mention'] else NO_MENTION_HASH
        if done.get(it['notice_id']) == (sha, EXTRACTOR_VERSION, it.get('content_version')):
            keep.append(it)
        elif it['mention']:
            call.append(it)
        else:
            quiet.append(it)
    return call, quiet, keep


DAILY_LIMIT = 300          # 매일 배치 14단계의 **한국 날짜 하루** 상한
DAILY_FILE = os.path.join(ROOT, 'data', 'bonus_daily_calls.json')


def _today_kst():
    from datetime import timedelta
    return (datetime.now(timezone.utc) + timedelta(hours=9)).date().isoformat()


class DailyRecordError(RuntimeError):
    """하루 호출 기록 파일이 있는데 읽지 못함 — 이미 쓴 호출 수를 모르므로 그날은 부르지 않는다(2026-10-07 R-P2-6)."""


def _read_daily(path):
    """기록 파일 → dict. 없으면 {}(처음). 있는데 읽지 못하거나 모양이 틀리면 DailyRecordError."""
    if not os.path.exists(path):
        return {}
    try:
        with io.open(path, encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError('dict 가 아니다')
        {k: int(v) for k, v in data.items()}
        return data
    except (OSError, ValueError, TypeError) as exc:
        raise DailyRecordError('하루 호출 기록 %s 를 읽지 못했다(%s: %s)' % (path, type(exc).__name__, exc))


def _daily_used(day, path=None):
    """오늘 이미 부른 수. 기록이 없으면 0, 있는데 깨졌으면 DailyRecordError."""
    return int(_read_daily(path or DAILY_FILE).get(day, 0))


def _daily_add(day, n, path=None):
    """오늘 부른 수에 n 을 더한다. 임시 파일에 쓴 뒤 바꿔치기한다 — 쓰다 끊겨도 이전 기록이 남는다."""
    path = path or DAILY_FILE
    data = _read_daily(path)
    data = {k: v for k, v in data.items() if k[:7] == day[:7]}     # 이번 달 것만 남긴다
    data[day] = int(data.get(day, 0)) + n
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def run_batch(limit=DAILY_LIMIT, say=print, daily_file=None):
    """매일 배치(daily_pipeline 14단계) 진입점 — 새·바뀐 공고만 부르고 DB 에만 쓴다(reports/ 파일 없음).

    API 키가 없으면 부르지 않고 {'error': 'no_api_key'}. 실패한 공고는 failed 로 세고 다음 실행이 다시 고른다.
    상한은 **한국 날짜 하루**에 부른 횟수(실패·같은 날 다시 돌린 것 포함)다. 부르기 전에 횟수를 먼저 적는다
    (2026-10-06 Codex 검수 P2-6 — 전에는 실행마다 300건이라 같은 날 다시 돌리면 또 300건을 불렀다).
    손으로 돌리는 `--all --limit N` 은 관리자용이라 이 상한을 쓰지 않는다(실행당 N건).
    """
    if not config.get('OPENAI_API_KEY'):
        say('OPENAI_API_KEY 가 없다. 가점 추출을 건너뛴다')
        return {'error': 'no_api_key', 'saved': 0}
    # 잔여량 읽기 → 호출 수 예약 → 기록을 한 잠금 안에서 한다(2026-10-07 Codex 재검수 B-P2-3 — 원자적 교체만으로는 두 실행이
    # 같은 잔여량을 읽고 둘 다 예약할 수 있었다). 이미 잡혀 있으면 부르지 않는다
    from collect import job_lock
    try:
        with job_lock.acquire((daily_file or DAILY_FILE) + '.lock'):
            return _run_batch_locked(limit, say, daily_file)
    except job_lock.JobBusy as exc:
        say('  다른 가점 추출이 실행 중이다 — 이번에는 부르지 않는다')
        return {'error': 'bonus_busy: %s' % exc, 'saved': 0}


def _run_batch_locked(limit, say, daily_file):
    day = _today_kst()
    try:
        used = _daily_used(day, daily_file)
    except DailyRecordError as exc:
        # 이미 쓴 호출 수를 모르면 상한을 지킬 수 없다 — 그날은 부르지 않는다(종료 코드 4 로 알린다)
        say('  %s — 오늘은 가점 추출을 부르지 않는다' % exc)
        return {'error': 'daily_record_unreadable: %s' % exc, 'saved': 0}
    room = max(0, limit - used)
    if used:
        say('오늘(%s) 이미 %d건 불렀다 — 이번 상한 %d건' % (day, used, room))
    meta = run_full(limit=room, say=say, report=False,
                    on_calls=lambda n: _daily_add(day, n, daily_file) if n else None)
    return {'called': meta['called'], 'no_mention': meta['no_mention'], 'saved': meta['saved'],
            'failed': len(meta['failures']), 'cost_usd': meta['cost_usd'], 'left': meta['left']}


def run_full(plan=False, workers=6, limit=None, say=print, report=True, on_calls=None):
    """열린 공고 전량 → notice_bonus. 이미 같은 문서·버전으로 저장된 공고는 건너뛴다.

    report=True 면 결과 파일도 reports/bonus_full_<시각>/ 에 남긴다(손으로 돌릴 때). 매일 배치는 report=False.
    """
    conn = store_mysql.connect()
    try:
        items = pick_targets(conn, with_no_mention=True)
        done = stored(conn)
    finally:
        conn.close()
    call, quiet, keep = plan_work(items, done)
    left = 0
    if limit is not None and len(call) > limit:
        left = len(call) - limit
        call = call[:limit]
    say('열린 공고 중 첨부·가점 말 있는 %d건 · 부를 것 %d · 가점 말 없음 %d · 그대로 %d · 다음으로 미룸 %d · 예상 약 $%.2f(추정)'
        % (len(items), len(call), len(quiet), len(keep), left, estimate(call)))
    if plan:
        return None
    from concurrent.futures import ThreadPoolExecutor, as_completed
    if on_calls:
        on_calls(len(call))                       # 부르기 전에 센다 — 도중에 실패해도 오늘 횟수에 들어간다
    client = _client() if call else None
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    outdir = os.path.join(ROOT, 'reports', 'bonus_full_%s' % stamp) if report else None
    if outdir:
        os.makedirs(outdir)
    conn = store_mysql.connect()
    rows, failures, cost = [], [], 0.0
    try:
        for it in quiet:
            row = no_mention_row(it)
            save(conn, row)
            rows.append(row)
        conn.commit()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(run_one, client, it): it for it in call}
            for n, fut in enumerate(as_completed(futures), 1):
                it = futures[fut]
                try:
                    row = fut.result()
                except Exception as exc:              # 기록만 하고 계속한다. 다음 실행이 다시 부른다
                    failures.append({'notice_id': it['notice_id'], 'error': type(exc).__name__})
                    continue
                save(conn, row)                       # DB 연결은 이 스레드에서만 쓴다
                conn.commit()
                rows.append(row)
                cost += row['cost_usd']
                if n % 50 == 0:
                    say('  %d/%d · 실패 %d · 약 $%.3f' % (n, len(call), len(failures), cost))
    finally:
        conn.close()
        rows.sort(key=lambda r: r['notice_id'])
        meta = {'run_at': stamp, 'extractor_version': EXTRACTOR_VERSION, 'targets': len(items), 'called': len(call),
                'no_mention': len(quiet), 'kept': len(keep), 'left': left, 'saved': len(rows), 'failures': failures,
                'cost_usd': round(cost, 4), 'price_basis': '2026-09-22 OpenAI 표준 단가(추정)'}
        if outdir:
            with io.open(os.path.join(outdir, 'results.jsonl'), 'w', encoding='utf-8') as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + '\n')
            with io.open(os.path.join(outdir, 'meta.json'), 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=1)
    say('저장 %d건(LLM %d · 가점 말 없음 %d) · 실패 %d · 약 $%.3f(추정)%s'
        % (len(rows), len(rows) - len(quiet), len(quiet), len(failures), cost, (' → %s' % outdir) if outdir else ''))
    return meta


def main(argv=None):
    parser = argparse.ArgumentParser(description='공고 가점 추출 (표본은 DB 에 쓰지 않는다)')
    parser.add_argument('--sample', type=int, help='열린 공고 중 가점이 나오는 공고 표본 수')
    parser.add_argument('--notice', help='공고 하나만 추출해 화면에 출력')
    parser.add_argument('--plan', action='store_true', help='부르지 않고 대상·예상 비용만')
    parser.add_argument('--all', action='store_true', help='열린 공고 전량 → 공용 DB notice_bonus 에 저장(유료·DB 쓰기)')
    parser.add_argument('--limit', type=int, help='--all 에서 이번에 부를 최대 건수')
    parser.add_argument('--ids', help='쉼표로 나눈 공고 ID 들만 뽑아 reports/ 에 남긴다(DB 에 쓰지 않음)')
    args = parser.parse_args(argv)
    if args.all:
        run_full(plan=args.plan, limit=args.limit)
        return 0
    if args.notice:
        conn = store_mysql.connect()
        try:
            items = pick_targets(conn, notice_ids=[args.notice])
        finally:
            conn.close()
        if not items:
            print('가점·가산점이 나오지 않는 공고이거나 없는 공고다')
            return 1
        if args.plan:
            print(build_document(items[0]))
            return 0
        print(json.dumps(run_one(_client(), items[0]), ensure_ascii=False, indent=1))
        return 0
    if args.ids:
        run_sample(0, plan=args.plan, ids=[x.strip() for x in args.ids.split(',') if x.strip()])
        return 0
    if args.sample:
        run_sample(args.sample, plan=args.plan)
        return 0
    parser.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
