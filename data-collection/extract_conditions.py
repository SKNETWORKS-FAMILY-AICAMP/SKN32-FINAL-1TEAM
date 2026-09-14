# -*- coding: utf-8 -*-
"""첨부 본문에서 자격요건을 뽑는다 — 1단계는 표본 검사다.

  python extract_conditions.py --sample 30          표본만. DB 에 쓰지 않는다
  python extract_conditions.py --sample 30 --save   결과를 파일로 남긴다
  python extract_conditions.py --notice <id>        특정 공고 하나만

왜 표본부터 하나. 업력 조건을 못 찾은 공고가 1,640건인데, 그 중 **문서에는
있는데 우리가 못 뽑은 것**과 **애초에 업력 제한이 없는 것**이 섞여 있다.
비율을 모르는 상태에서 1,701건을 전량 돌리면 돈만 쓰고 판정률이 거의
안 올라갈 수 있다. 30건으로 먼저 확인한다.

토큰을 줄이는 방법. 공고문 전체는 최대 27,000자다. 그대로 넣으면 비싸고
관계 없는 내용이 판단을 흐린다. **자격요건이 적힌 구간만 잘라서** 넣는다.

  "지원대상" · "신청자격" · "지원제외" · "지원금액" 같은 제목 주변만

절대 하지 않는 것
  · 못 찾은 것을 "제한 없음" 으로 바꾸지 않는다. 둘은 다르다.
    gate.py 주석의 경고와 같다 — 못 찾았다고 제한 없음으로 쓰면 사용자가
    자격을 확인받은 것으로 읽는다.
  · 근거 문장(source_quote) 없이 숫자만 저장하지 않는다. 틀렸는지 알 수 없다.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import config
import store_mysql

MODEL = 'gpt-4o-mini'
EXTRACTOR_VERSION = 'extract_conditions/1.0 ' + MODEL

# 자격요건이 적힌 구간을 찾는 제목들. 표본에서 실제로 쓰인 표현을 모았다.
HEADINGS = ('지원대상', '지원 대상', '신청자격', '신청 자격', '지원자격', '신청대상',
            '지원제외', '지원 제외', '제외대상', '지원금액', '지원 금액', '지원규모',
            '지원내용', '융자한도', '지원한도', '신청자 자격')

WINDOW_BEFORE = 80
WINDOW_AFTER = 900
MAX_CHARS = 6000

SCHEMA = {
    'name': 'notice_conditions',
    'schema': {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'age_years_max': {
                'type': ['integer', 'null'],
                'description': '업력(사업을 한 기간) 상한(년). "업력 7년 이하"면 7. '
                               '사람 나이·근속연수·지원기간은 업력이 아니다. 없으면 null',
            },
            'age_years_min': {
                'type': ['integer', 'null'],
                'description': '업력 하한(년). "업력 1년 이상"이면 1. '
                               '"3개월 이상 영업"은 1년 미만이므로 0. 없으면 null',
            },
            'age_source_quote': {
                'type': ['string', 'null'],
                'description': '업력 값의 근거가 된 문장을 원문 그대로. '
                               '업력을 못 찾았으면 null. 다른 조건 문장을 넣지 않는다',
            },
            'pre_startup_allowed': {
                'type': ['boolean', 'null'],
                'description': '예비창업자(사업자등록 전)가 신청 가능한가. 알 수 없으면 null',
            },
            'business_type': {
                'type': 'array',
                'items': {'type': 'string',
                          'enum': ['개인사업자', '법인', '예비창업자', '비영리', '기타']},
                'description': '신청 가능한 사업자 형태. 문서가 형태를 특정하지 않으면 빈 배열',
            },
            'amount_max_won': {
                'type': ['integer', 'null'],
                'description': '기업 1곳(또는 과제 1건)이 받을 수 있는 최대 지원금(원). '
                               '사업 전체 예산·매출 기준·융자 총 규모는 여기에 넣지 않는다. '
                               '구분이 안 되면 null',
            },
            'source_quote': {
                'type': ['string', 'null'],
                'description': '위 값들의 근거가 된 원문 문장을 그대로. 없으면 null',
            },
            'no_age_limit': {
                'type': 'boolean',
                'description': '문서를 읽어보니 업력 제한이 명시적으로 없다고 판단되면 true. '
                               '단순히 못 찾은 경우는 false',
            },
            'uncertain': {
                'type': 'array',
                'items': {'type': 'string'},
                'description': '판단하지 못한 이유. 예: "세부사업별로 조건이 다름"',
            },
        },
        'required': ['age_years_max', 'age_years_min', 'age_source_quote',
                     'pre_startup_allowed', 'business_type', 'amount_max_won',
                     'source_quote', 'no_age_limit', 'uncertain'],
    },
    'strict': True,
}

SYSTEM = """너는 정부 지원사업 공고문에서 신청 자격요건만 뽑아내는 도구다.

규칙
1. 문서에 적혀 있는 것만 쓴다. 추측하거나 일반 상식으로 채우지 않는다.
2. 값을 찾지 못했으면 null 을 쓴다. 0 이나 빈 문자열로 바꾸지 않는다.
3. "업력 제한이 없다" 와 "업력 제한을 찾지 못했다" 는 다르다.
   문서가 업력을 언급하지 않으면 age_years_max=null, no_age_limit=false 다.
   문서가 "업력 제한 없음", "전 업력" 처럼 명시하면 no_age_limit=true 다.
4. source_quote 에는 판단 근거가 된 문장을 원문 그대로 넣는다. 요약하지 않는다.
5. business_type 은 문서가 사업자 형태를 특정할 때만 채운다.
   "중소기업", "소상공인" 은 규모 분류이지 사업자 형태가 아니므로 빈 배열이다.
   "법인등기부등본 제출" 같은 제출서류 언급은 자격요건이 아니다.
6. 조건이 세부사업별로 다르면 가장 넓은 조건을 쓰고 uncertain 에 그 사실을 적는다.
7. 부정형을 반대로 읽지 않는다. "체납이 없는 기업" 은 신청 가능하다는 뜻이다.
8. amount_max_won 은 **기업 1곳이 받는 최대 금액**만 쓴다. 아래는 모두 null 이다.
   · "지원예산 총 6억원", "지원규모 4,942억원"  → 사업 전체 예산이다
   · "총수입금액 15억원 미만", "매출액 100억 이하" → 자격 기준이지 지원금이 아니다
   · "융자 규모 200억원" → 사업 전체 융자 총액이다
   맞는 예: "1개사당 25만원 한도", "기업당 최대 5천만원", "과제당 3억원 이내"
   금액이 여러 개면 기업 1곳 기준의 가장 큰 값을 쓴다. 헷갈리면 null 을 쓰고
   uncertain 에 이유를 적는다.
9. age_years_max·age_years_min 은 **사업을 한 기간(업력)** 만 쓴다.
   아래는 모두 업력이 아니다. 업력으로 쓰면 안 된다.
   · "만 19세 ~ 만 45세", "만 39세 이하"  → 사람 나이다
   · "장기재직 3년 이상", "근속 5년"      → 근로자 근속연수다
   · "지원기간 3~5년", "유효기간 5년"     → 사업 기간이다
   · "최근 3개년 매출", "최근 5년간 지원금" → 실적 집계 기간이다
   업력은 "업력 N년", "창업 N년", "설립 후 N년", "개업 N년", "영업 N년" 처럼
   사업 시작 시점을 기준으로 적힌 것만이다.
10. age_source_quote 에는 업력 값의 근거 문장만 원문 그대로 넣는다.
    업력을 못 찾았으면 age_years_max=null, age_years_min=null,
    age_source_quote=null 이다. 다른 조건 문장을 억지로 넣지 않는다.
11. "N년 이상" 은 하한(age_years_min), "N년 이하·미만·이내" 는 상한
    (age_years_max) 이다. 방향을 바꾸지 않는다."""

# 업력 근거로 인정할 표현. 이 말이 근거 문장에 없으면 업력 값을 버린다.
# 실측 오답: "만 19세~만 45세" 를 업력 45년으로, "3개월 이상 영업" 을 5년으로 읽었다.
AGE_EVIDENCE = re.compile(r'업력|창업\s*후|창업\s*\d|설립\s*후|설립\s*\d|개업|영업\s*중|영업\s*\d')
AGE_DECOY = re.compile(r'만\s*\d+\s*세|\d+\s*세\s*(이하|이상|미만)|근속|재직|유효기간')


AGE_MONTH_ONLY = re.compile(r'\d+\s*개월')
AGE_YEAR = re.compile(r'\d+\s*년')


def verify_age(data):
    """LLM 이 준 업력 값을 근거 문장으로 검증한다.

    프롬프트만으로는 재발을 막지 못했다. 근거에 업력 표현이 없거나 사람 나이
    표현이 있으면 값을 버리고 왜 버렸는지 남긴다. 자격요건은 틀리면 사용자가
    헛수고하는 영역이라, 애매하면 버리고 "확인 필요" 로 두는 쪽이 낫다.

    실측 오답
      "만 19세 ~ 만 45세"        → 업력 45년        사람 나이
      "장기재직(3년 이상)"        → 업력 3년         근로자 근속
      "3개월 이상 영업 중"        → 업력 3년         개월을 년으로
    """
    quote = data.get('age_source_quote') or ''
    has_age = data.get('age_years_max') is not None or data.get('age_years_min') is not None
    if not has_age:
        return data, None

    if not quote.strip():
        reason = '근거 문장 없음'
    elif AGE_DECOY.search(quote) and not AGE_EVIDENCE.search(quote):
        reason = '근거가 사람 나이·근속연수로 보임'
    elif not AGE_EVIDENCE.search(quote):
        reason = '근거에 업력 표현이 없음'
    elif AGE_MONTH_ONLY.search(quote) and not AGE_YEAR.search(quote):
        # "3개월 이상 영업" 을 3년으로 읽은 사례가 있었다. 개월만 적힌 근거는 버린다.
        reason = '근거가 개월 단위인데 연 단위로 읽음'
    else:
        return data, None

    data['age_years_max'] = None
    data['age_years_min'] = None
    data['age_rejected'] = reason
    data['uncertain'] = list(data.get('uncertain') or []) + ['업력 추출 버림: ' + reason]
    return data, reason


# 한국어 금액 표기. "3천만원" · "1.5억원" · "1억 5천만원" 을 모두 읽는다.
WON = re.compile(r'([0-9][0-9,.]*)\s*(억|천만|백만|만)?\s*원?')
WON_UNIT = {'억': 10 ** 8, '천만': 10 ** 7, '백만': 10 ** 6, '만': 10 ** 4, '': 1}

# 기업 1곳이 받는 지원금 상한. 이 값 이상은 사업 총예산·매출 기준을
# 잘못 읽은 것으로 본다. /review 로 확인하고 조정한다.
AMOUNT_SANITY_MAX = 10 ** 9      # 10억원


def won_candidates(text):
    """근거 문장에서 금액 후보를 원 단위로 모은다.

    "1억 5천만원" 처럼 큰 단위 뒤에 작은 단위가 붙는 복합 표기는 합친 값도
    후보에 넣는다. 그러지 않으면 1억·5천만 두 개로만 잡혀 실제 1.5억을 놓친다.
    """
    found = []
    for m in WON.finditer(text or ''):
        num, unit = m.group(1), m.group(2) or ''
        if not unit and '원' not in m.group(0):
            continue            # 단위도 '원' 도 없는 숫자는 금액이 아니다
        try:
            value = float(num.replace(',', ''))
        except ValueError:
            continue
        found.append((int(value * WON_UNIT[unit]), m.start(), m.end(), unit))

    values = {v for v, _, _, _ in found}
    # 붙어 있는(사이 간격 4자 이내) 내림차순 단위 두 개는 합친 값도 후보다
    for i in range(len(found) - 1):
        a, _, a_end, a_unit = found[i]
        b, b_start, _, b_unit = found[i + 1]
        if b_start - a_end <= 4 and WON_UNIT[a_unit] > WON_UNIT[b_unit] > 1:
            values.add(a + b)
    return values


def verify_amount(data):
    """금액을 근거 문장과 대조해 교정하거나 버린다.

    실측 오답이 모두 '억' 단위 10배 실수였다.
      "보증한도 1억 원 이내"        → 1,000,000,000 (10배)
      "1억 5천만원 ~ 3억원 한도"    → 3,000,000,000 (10배)

    후보가 하나뿐이면 그 값으로 고친다. 여러 개면 어느 것인지 알 수 없으므로
    버린다. 근거에 금액이 아예 없으면 근거 없는 값이라 버린다.
    """
    amount = data.get('amount_max_won')
    if amount is None:
        return data, None

    # 기업 1곳이 10억 넘게 받는 공고는 드물다. 그 구간은 근거를 봐도 숫자가
    # 맞아서 검산이 통과시키는데, 실제로는 사업 총예산·전체 융자 규모·매출
    # 기준을 지원금으로 읽은 것이 대부분이었다(실측 38건 중 다수).
    # 숫자와 의미가 어긋나는 경우라 정규식으로는 가릴 수 없어 상한으로 막는다.
    if amount >= AMOUNT_SANITY_MAX:
        data['amount_max_won'] = None
        reason = '기업당 지원금으로 보기 어려운 금액(%s 이상)' % '{:,}'.format(AMOUNT_SANITY_MAX)
        data['amount_rejected'] = reason
        data['uncertain'] = list(data.get('uncertain') or []) + ['금액 추출 버림: ' + reason]
        return data, reason

    candidates = won_candidates(data.get('source_quote') or '')
    if not candidates:
        reason = '근거에 금액이 없음'
    elif amount in candidates:
        return data, None
    else:
        # 단위 자리수만 틀린 경우(10배·100배)만 고친다. 값이 아예 다르면 고치지
        # 않고 버린다. 유일 후보라고 무조건 갈아끼우면 "연 매출 300억 미만"
        # 같은 자격 기준을 지원금액으로 바꿔 넣는 사고가 난다.
        slips = [c for c in candidates
                 if amount and c and round(max(c, amount) / min(c, amount)) in (10, 100)]
        if len(set(slips)) == 1:
            fixed = slips[0]
            data['amount_max_won'] = fixed
            data['amount_corrected'] = {'from': amount, 'to': fixed}
            return data, 'corrected'
        reason = '근거의 금액 후보와 불일치(후보 %d개)' % len(candidates)

    data['amount_max_won'] = None
    data['amount_rejected'] = reason
    data['uncertain'] = list(data.get('uncertain') or []) + ['금액 추출 버림: ' + reason]
    return data, reason


def dedupe_types(data):
    """business_type 중복 제거. 순서는 유지한다.

    "(예비)사회적기업, (예비)마을기업" 에서 예비창업자가 두 번 들어온 사례가 있다.
    """
    kinds = data.get('business_type') or []
    if len(kinds) != len(set(kinds)):
        data['business_type'] = list(dict.fromkeys(kinds))
    return data


def slice_conditions(text, max_chars=MAX_CHARS):
    """자격요건이 적힌 구간만 잘라낸다. 못 찾으면 앞부분을 쓴다."""
    if not text:
        return ''
    spans = []
    for head in HEADINGS:
        for m in re.finditer(re.escape(head), text):
            spans.append((max(0, m.start() - WINDOW_BEFORE),
                          min(len(text), m.end() + WINDOW_AFTER)))
    if not spans:
        return text[:max_chars]

    spans.sort()
    merged = [list(spans[0])]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    out = []
    total = 0
    for start, end in merged:
        piece = ' '.join(text[start:end].split())
        if total + len(piece) > max_chars:
            piece = piece[:max_chars - total]
        out.append(piece)
        total += len(piece)
        if total >= max_chars:
            break
    return '\n---\n'.join(out)


def pick_targets(connection, limit, only_missing_age=True, notice_id=None):
    """대상 공고와 그 문서들.

    **GROUP_CONCAT 을 쓰지 않는다.** MySQL 의 group_concat_max_len 기본값이
    1024 바이트라서, 한글 기준 약 340자에서 잘린다. 19,563자 공고문이 앞 340자만
    넘어와 자격요건 구간에 도달조차 못 하는 일이 실제로 있었다. 첨부를 행별로
    받아 파이썬에서 합친다.

    공고 본문(body)·지원대상(target_text)도 함께 넣는다. 업력 조건이 첨부가
    아니라 공고 본문에 적힌 경우가 실측으로 69건 있었다.
    """
    where = ''
    args = []
    if notice_id:
        where = ' AND n.notice_id = %s'
        args.append(notice_id)
    elif only_missing_age:
        where = ' AND n.age_condition_raw IS NULL'

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT n.id, n.notice_id, n.title, n.body, n.target_text,
                   n.age_condition_raw, n.target_category
              FROM notices n
             WHERE EXISTS (SELECT 1 FROM notice_attachments na
                             JOIN attachment_texts at ON at.attachment_fk = na.id
                            WHERE na.notice_fk = n.id AND at.last_status = 'ok'
                              AND at.extracted_text IS NOT NULL)""" + where +
            ' ORDER BY n.notice_id LIMIT %s', tuple(args) + (limit,))
        notices = cursor.fetchall()

        targets = []
        for pk, nid, title, body, target, age_raw, target_cat in notices:
            cursor.execute("""
                SELECT at.extracted_text
                  FROM notice_attachments na
                  JOIN attachment_texts at ON at.attachment_fk = na.id
                 WHERE na.notice_fk = %s AND at.last_status = 'ok'
                   AND at.extracted_text IS NOT NULL
                 ORDER BY at.text_chars DESC""", (pk,))
            attachments = [r[0] for r in cursor.fetchall()]
            targets.append({
                'notice_id': nid, 'title': title or '',
                'body': body or '', 'target_text': target or '',
                'age_condition_raw': age_raw, 'target_category': target_cat,
                'attachments': attachments,
            })
        return targets


def build_document(item, max_chars=MAX_CHARS):
    """LLM 에 보낼 문서를 만든다.

    공고 본문과 지원대상 원문을 먼저 넣고, 그 다음 첨부 본문에서 자격요건
    구간을 잘라 붙인다. 첨부는 긴 것부터 본다(공고문이 서식보다 길다).
    """
    head = []
    if item['target_text']:
        head.append('[지원대상 원문]\n' + ' '.join(item['target_text'].split()))
    if item['body']:
        head.append('[공고 개요]\n' + ' '.join(item['body'].split()))
    head_text = '\n\n'.join(head)[:max_chars // 3]

    budget = max_chars - len(head_text)
    pieces = []
    for text in item['attachments']:
        if budget <= 0:
            break
        piece = slice_conditions(text, max_chars=budget)
        if piece:
            pieces.append(piece)
            budget -= len(piece)

    parts = [p for p in (head_text, '\n\n'.join(pieces)) if p]
    return '\n\n[공고문 첨부 발췌]\n'.join(parts) if len(parts) == 2 else (parts[0] if parts else '')


def doc_hash(document):
    """LLM 에 보낸 문서의 해시. 문서가 그대로면 다시 부르지 않는 기준이다."""
    return hashlib.sha256((document or '').encode('utf-8')).hexdigest()


def save_condition(connection, notice_id, data, doc_sha, usage):
    """추출 결과를 notice_conditions 에 저장한다. 같은 공고면 덮어쓴다.

    한 건마다 커밋한다. 1,542건에 한 시간 걸리는 작업이라 중간에 끊겨도
    거기까지는 남아야 하고, 다시 실행하면 이어서 해야 한다.
    """
    with connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO notice_conditions
              (notice_id, amount_max_won, business_type, pre_startup_allowed,
               age_years_max, age_years_min, age_source_quote, no_age_limit,
               source_quote, uncertain, amount_corrected, amount_rejected,
               age_rejected, input_sha256, extractor_version,
               prompt_tokens, completion_tokens)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              amount_max_won=VALUES(amount_max_won),
              business_type=VALUES(business_type),
              pre_startup_allowed=VALUES(pre_startup_allowed),
              age_years_max=VALUES(age_years_max),
              age_years_min=VALUES(age_years_min),
              age_source_quote=VALUES(age_source_quote),
              no_age_limit=VALUES(no_age_limit),
              source_quote=VALUES(source_quote),
              uncertain=VALUES(uncertain),
              amount_corrected=VALUES(amount_corrected),
              amount_rejected=VALUES(amount_rejected),
              age_rejected=VALUES(age_rejected),
              input_sha256=VALUES(input_sha256),
              extractor_version=VALUES(extractor_version),
              prompt_tokens=VALUES(prompt_tokens),
              completion_tokens=VALUES(completion_tokens)""",
            (notice_id, data.get('amount_max_won'),
             json.dumps(data.get('business_type') or [], ensure_ascii=False),
             data.get('pre_startup_allowed'),
             data.get('age_years_max'), data.get('age_years_min'),
             data.get('age_source_quote'), bool(data.get('no_age_limit')),
             data.get('source_quote'),
             json.dumps(data.get('uncertain') or [], ensure_ascii=False),
             json.dumps(data['amount_corrected'], ensure_ascii=False)
             if data.get('amount_corrected') else None,
             data.get('amount_rejected'),
             data.get('age_rejected'), doc_sha, EXTRACTOR_VERSION,
             usage.get('in'), usage.get('out')))
    connection.commit()


def already_done(connection, version=EXTRACTOR_VERSION):
    """이미 추출한 공고. {notice_id: input_sha256}.

    같은 추출기 버전에서 문서가 안 바뀐 것은 다시 부르지 않는다. 벡터를
    embedding_input_sha256 으로 관리하는 방식과 같다.
    """
    with connection.cursor() as cursor:
        cursor.execute('SELECT notice_id, input_sha256 FROM notice_conditions '
                       'WHERE extractor_version = %s', (version,))
        return dict(cursor.fetchall())


def ask(client, title, body):
    started = time.time()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{'role': 'system', 'content': SYSTEM},
                  {'role': 'user',
                   'content': '공고 제목: %s\n\n공고문 발췌:\n%s' % (title, body)}],
        response_format={'type': 'json_schema', 'json_schema': SCHEMA},
        temperature=0)
    data = json.loads(response.choices[0].message.content)
    usage = response.usage
    return data, {'in': usage.prompt_tokens, 'out': usage.completion_tokens,
                  'ms': (time.time() - started) * 1000}


def run_batch(limit=None, connection=None, say=print):
    """배치(daily_pipeline 10단계)에서 부르는 진입점.

    바뀐 것만 부른다. 문서 해시가 같으면 건너뛰므로 하루 비용은 신규 공고
    수십 건 분량이다. 한 건마다 커밋해서 중단돼도 거기까지는 남는다.

    한 건이 실패해도 멈추지 않는다. 실패 건수를 세어 돌려주고, 다음 실행이
    다시 고른다. 1,542건을 돌리다 한 건 때문에 전체가 죽으면 안 된다.
    """
    import openai

    key = config.get('OPENAI_API_KEY')
    if not key:
        say('OPENAI_API_KEY 가 없다. 자격요건 추출을 건너뛴다')
        return {'error': 'no_api_key', 'extracted': 0}
    client = openai.OpenAI(api_key=key)

    own = connection is None
    if own:
        connection = store_mysql.connect()
    try:
        targets = pick_targets(connection, limit or 100000, only_missing_age=False)
        done = already_done(connection)
        todo = [t for t in targets
                if done.get(t['notice_id']) != doc_hash(build_document(t))]
        say('대상 %d건 중 새로 추출할 것 %d건' % (len(targets), len(todo)))
        if not todo:
            return {'extracted': 0, 'amount': 0, 'types': 0, 'failed': 0,
                    'tokens_in': 0, 'tokens_out': 0}

        extracted = amount = types = failed = 0
        tokens_in = tokens_out = 0
        for i, item in enumerate(todo, 1):
            document = build_document(item)
            try:
                data, usage = ask(client, item['title'], document)
            except Exception as exc:
                failed += 1
                say('  실패 %s — %s' % (item['notice_id'], type(exc).__name__))
                continue

            data, _ = verify_age(data)
            data, _ = verify_amount(data)
            data = dedupe_types(data)
            save_condition(connection, item['notice_id'], data,
                           doc_hash(document), usage)

            extracted += 1
            tokens_in += usage['in']
            tokens_out += usage['out']
            amount += data.get('amount_max_won') is not None
            types += bool(data.get('business_type'))
            if len(todo) > 50 and i % 50 == 0:
                say('  %d/%d' % (i, len(todo)))

        say('추출 %d건 · 금액 %d · 형태 %d%s'
            % (extracted, amount, types, ' · 실패 %d' % failed if failed else ''))
        say('  토큰 입력 {:,} · 출력 {:,}'.format(tokens_in, tokens_out))
        return {'extracted': extracted, 'amount': amount, 'types': types,
                'failed': failed, 'tokens_in': tokens_in, 'tokens_out': tokens_out}
    finally:
        if own:
            connection.close()


def main():
    ap = argparse.ArgumentParser(description='첨부 본문에서 자격요건 추출 (표본 검사)')
    ap.add_argument('--sample', type=int, default=30, help='표본 건수')
    ap.add_argument('--notice', help='특정 공고 하나만')
    ap.add_argument('--all-notices', action='store_true',
                    help='업력을 이미 아는 공고도 포함한다(정확도 대조용)')
    ap.add_argument('--save', action='store_true', help='결과를 파일로 남긴다')
    ap.add_argument('--save-db', action='store_true',
                    help='notice_conditions 에 저장한다. 중단되면 이어서 한다')
    ap.add_argument('--redo', action='store_true',
                    help='이미 추출한 것도 다시 부른다')
    args = ap.parse_args()

    import openai
    key = config.get('OPENAI_API_KEY')
    if not key:
        print('OPENAI_API_KEY 가 .env 에 없다')
        return 1
    client = openai.OpenAI(api_key=key)

    connection = store_mysql.connect()
    rows = pick_targets(connection, 1 if args.notice else args.sample,
                        only_missing_age=not args.all_notices,
                        notice_id=args.notice)

    done = {}
    if args.save_db and not args.redo:
        done = already_done(connection)
        before = len(rows)
        rows = [r for r in rows
                if done.get(r['notice_id']) != doc_hash(build_document(r))]
        if before != len(rows):
            print('이미 추출한 %d건은 건너뛴다 (문서가 그대로다)' % (before - len(rows)))

    if not args.save_db:
        connection.close()
        connection = None

    if not rows:
        print('대상이 없다 — 모두 추출돼 있다')
        if connection:
            connection.close()
        return 0

    print('대상 %d건 · 모델 %s' % (len(rows), MODEL))
    print('=' * 76)

    results = []
    tokens_in = tokens_out = 0
    found_age = found_type = found_amount = no_limit = failed = age_rejected = 0
    amt_corrected = amt_rejected = 0

    for i, item in enumerate(rows, 1):
        nid, title = item['notice_id'], item['title']
        age_raw, target_cat = item['age_condition_raw'], item['target_category']
        body = build_document(item)
        try:
            data, usage = ask(client, title, body)
        except Exception as exc:
            failed += 1
            print('%2d. %-44s 실패 %s' % (i, title[:44], type(exc).__name__))
            continue

        data, rejected = verify_age(data)
        if rejected:
            age_rejected += 1
        data, amt_note = verify_amount(data)
        if amt_note == 'corrected':
            amt_corrected += 1
        elif amt_note:
            amt_rejected += 1
        data = dedupe_types(data)

        tokens_in += usage['in']
        tokens_out += usage['out']
        if data['age_years_max'] is not None or data['age_years_min'] is not None:
            found_age += 1
        if data['business_type']:
            found_type += 1
        if data['amount_max_won'] is not None:
            found_amount += 1
        if data['no_age_limit']:
            no_limit += 1

        if args.save_db:
            save_condition(connection, nid, data, doc_hash(body), usage)

        results.append({'notice_id': nid, 'title': title,
                        'age_condition_raw': age_raw, 'target_category': target_cat,
                        'sliced_chars': len(body), 'usage': usage, **data})

        age = ('%s년 이하' % data['age_years_max'] if data['age_years_max'] is not None
               else ('제한 없음(명시)' if data['no_age_limit'] else '—'))
        print('%2d. %s' % (i, (title or '')[:56]))
        print('    업력 %-14s 형태 %-22s 금액 %s'
              % (age, ','.join(data['business_type']) or '—',
                 '{:,}원'.format(data['amount_max_won'])
                 if data['amount_max_won'] else '—'))
        if data.get('age_source_quote'):
            print('    업력근거 "%s"' % ' '.join(data['age_source_quote'].split())[:82])
        if data.get('age_rejected'):
            print('    업력버림 %s' % data['age_rejected'])
        if data['source_quote']:
            print('    근거 "%s"' % ' '.join(data['source_quote'].split())[:88])
        if data['uncertain']:
            print('    미확정 %s' % '; '.join(data['uncertain'])[:88])

    n = len(results)
    print('=' * 76)
    print('표본 %d건 (실패 %d건)' % (n, failed))
    if n:
        print('  업력 조건 찾음        %2d건  %4.0f%%' % (found_age, found_age / n * 100))
        print('  업력 검증에서 버림     %2d건  %4.0f%%' % (age_rejected, age_rejected / n * 100))
        print('  업력 제한 없음 명시    %2d건  %4.0f%%' % (no_limit, no_limit / n * 100))
        print('  둘 다 아님(판단 못함)  %2d건  %4.0f%%'
              % (n - found_age - no_limit, (n - found_age - no_limit) / n * 100))
        print('  사업자 형태 찾음      %2d건  %4.0f%%' % (found_type, found_type / n * 100))
        print('  지원금액 찾음         %2d건  %4.0f%%' % (found_amount, found_amount / n * 100))
        print('  금액 근거로 교정       %2d건' % amt_corrected)
        print('  금액 검증에서 버림     %2d건' % amt_rejected)
    print()
    print('토큰  입력 {:,} · 출력 {:,}'.format(tokens_in, tokens_out))
    if n:
        print('건당  입력 %.0f · 출력 %.0f' % (tokens_in / n, tokens_out / n))
        print('1,701건 환산 입력 %.1fM · 출력 %.1fM 토큰'
              % (tokens_in / n * 1701 / 1e6, tokens_out / n * 1701 / 1e6))
        print('  ※ 실제 단가는 OpenAI 요금표를 확인하세요')

    if connection:
        connection.close()

    if args.save and results:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        path = os.path.join('data', 'conditions_sample_%s.json' % stamp)
        os.makedirs('data', exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print('\n저장 %s' % path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
