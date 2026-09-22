# -*- coding: utf-8 -*-
"""신청 가능 업종을 LLM 으로 뽑으면 정규식보다 나은가 — 30건 표본. **DB 에 쓰지 않는다.**

  python -X utf8 -m experiments.sql_semantic.industry_llm_sample --prompt v3 --plan    문서·예상 비용만 (호출 없음)
  python -X utf8 -m experiments.sql_semantic.industry_llm_sample --prompt v3           30건 실제 호출
  python -X utf8 -m experiments.sql_semantic.industry_llm_sample --prompt v3 --resume reports/industry_llm_sample_<시각>
                                                                                       중간에 멈춘 실행 이어 하기

`--prompt` 는 필수다. v1·v2 는 오독이 확인된 판이라 `--allow-legacy` 를 함께 줘야만 돈다
(2026-09-22 Codex 리뷰 F2 — 옵션 없는 실행이 실패한 v1 에 다시 비용을 쓰던 문제).

배경 (2026-09-22 사용자 요청)

  `conditions.py` 의 업종 판정은 정규식이라 실험 DB 1,852건 중 known 0 · no_limit 1 · unknown 1,851 이다.
  기존 LLM 추출기(`collect/extract_conditions.py`)는 업력만 뽑고 업종은 다루지 않는다.
  전량을 돌리기 전에 30건으로 비용과 결과 모양을 먼저 본다.

판 (같은 파일에 모두 남긴다 — 저장된 결과를 다시 만들 수 있어야 한다)

  v1  첫 실행. known 20 중 절반가량이 규모 표현·기술 분야를 업종으로 과잉 추론
  v2  엄격 프롬프트 + 표면어 검사. known 8. 그러나 검사는 글자 존재만 봐서 가짜 no_limit·넓은 별칭을
      통과시키고, "상시근로자" 한 단어로 실제 복합 조건을 내렸으며, 허용 목록 누락(최소 4건)을 만들었다
  v3  (2026-09-22 Codex 리뷰 F1·후속 리뷰 F1 반영) 업종을 **원문 표현 그대로** 값마다, **값마다 원문 근거(evidence)와 함께** 받는다.
      · 허용 값은 근거가 원문에 있고, 값이 근거 안에 있고, **값이 신청 자격 quote 안에 있어야** 남긴다
        (지원 내용·다른 조항에서 본 업종을 신청 제한으로 옮기지 않게). quote 는 가장 가까운 머리말이
        자격 머리말(지원대상·신청자격 등)이거나, 머리말이 없으면 제한 서술어("기업만"·"영위하는")가 있어야 한다
      · 제외 값은 근거가 원문에 있고, 제외 표현과 **같은 절에서 연결**돼야 남긴다
        ("유흥업 교육 포함, 제조업은 지원 제외" 의 유흥업은 빠진다)
      · 어휘 라벨은 원문에 그 업종명이 있을 때만 `exact`, 뜻으로 옮긴 것(농가 → 농업)은 `alias` 로 따로 둔다
      · no_limit 은 "업종 제한 없음/전 업종/업종 무관" 같은 명시 표현이 원문에 있어야 한다
      · 규모 **정의**(소상공인기본법 등의 업종별 인원 기준)만 내리고, 실제 복합 신청 조건은 남긴다
      · "이 목록이 전부인가(list_complete)" 를 따로 받는다. 별표·"등"·누락이 보이면 코드가 false 로 내린다

**어느 판의 결과도 탈락 필터에 쓰지 않는다.** 사람 정답으로 오판율·목록 완전성을 재기 전까지는 참고/확인 필요용이다.

입력

  · 표본: 실험 DB `lab_notices`(2026-09-18 접수 중 스냅샷) 에서 고정 seed 로 30건.
  · 문서: 지원대상 원문 + 공고 개요 + 첨부 본문의 자격요건 구간 — 기존 추출기의 `build_document()` 를 그대로 쓴다.
    첨부는 출처 DB 에서 **SELECT 만** 한다.

기록 (Codex 리뷰 F2)

  · 공고마다 `document_sha256`·첨부 지문, meta 에 프롬프트·스키마·코드 해시와 API 가 돌려준 실제 모델명.
  · 이전 실행과 비교할 때 문서 해시까지 같아야 정식 전후 비교다. 해시가 없는 옛 실행은 "제한적 비교" 로 표시한다.
  · 성공한 호출은 바로 `checkpoint.jsonl` 에 적는다. 중간에 실패해도 이미 쓴 비용의 결과가 남고 `--resume` 으로 이어 한다.
    재개 키는 (notice_id, document_sha256, prompt_sha256, schema_sha256, model).
    재개는 처음 실행의 이전 실행 비교(previous·등급)를 meta 에서 이어받는다. 다른 --previous 를 주거나
    프롬프트·스키마 해시가 바뀌었으면 거부한다. 응답 모델이 섞이면 보고서에 혼합 실행으로 적는다.
  · 비용은 **API 가 보고한 토큰 × 이 파일에 적은 단가**로 계산한 값이다. 청구액이 아니다(F3).

읽기 전용: 실험 DB·출처 DB 모두 SELECT 만. 결과는 `reports/industry_llm_sample_<시각>/` 에만 남긴다.
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
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from collect import extract_conditions as ec  # noqa: E402  (문서 자르기만 재사용. 이 파일은 고치지 않는다)
from experiments.sql_semantic import conditions, config  # noqa: E402
from shared import config as pipeline_config  # noqa: E402

MODEL = 'gpt-4o-mini'                     # 기본값. 기존 업력 추출기와 같은 모델 (--model 로 바꾼다)
# 1M 토큰당 USD (입력, 출력). 추정용 — 청구액이 아니다.
# 2026-09-22 https://developers.openai.com/api/docs/pricing 표준 단가를 옮겼다(v1~v3 실행의 gpt-4o-mini 기록 단가와 같다).
PRICES = {'gpt-4o-mini': (0.15, 0.60), 'gpt-4.1-mini': (0.40, 1.60),
          'gpt-5.6-luna': (0.20, 1.20), 'gpt-5.6-terra': (2.00, 12.00), 'gpt-5.6-sol': (4.00, 20.00)}
PRICE_IN, PRICE_OUT = PRICES[MODEL]
PRICE_BASIS = '2026-09-22 OpenAI 요금 페이지 표준 단가'
# 추론 모델은 temperature 를 보내지 않고 reasoning_effort 를 고를 수 있다. 추론 토큰은 출력 요금으로 청구된다.
REASONING_PREFIXES = ('gpt-5', 'o1', 'o3', 'o4')
REASONING_EFFORTS = ('none', 'low', 'medium', 'high')
# 비용 **추정**에만 쓰는 호출당 추론 토큰 가정. 실제 값은 응답 usage 로 기록한다
REASONING_TOKENS_GUESS = {None: 1500, 'none': 0, 'low': 600, 'medium': 1500, 'high': 4000}


def is_reasoning(model):
    return model.startswith(REASONING_PREFIXES)


def engine_id(model, effort=None):
    """재개 키·meta 에 쓰는 이름. 추론 강도가 다르면 다른 실행이다."""
    return '%s@%s' % (model, effort) if effort else model
SAMPLE = 30
SEED = 20260922
REPORTS = os.path.join(ROOT, 'reports')
CODE_PATH = os.path.abspath(__file__)

# conditions.py 와 같은 어휘
VOCAB = sorted({norm for _word, norm in conditions.INDUSTRY_WORDS})

SYSTEM = """너는 정부·지자체 지원사업 공고에서 **신청 가능한 업종 제한**만 찾는다.

찾는 것: 공고가 "어떤 업종의 기업만 신청할 수 있다"고 밝힌 자격 조건.
예) "제조업을 영위하는 중소기업" → 제조업 · "음식점업 소상공인에 한함" → 음식점업

업종 제한이 **아닌** 것 — 여기서 업종을 뽑지 않는다
- 지원 분야·사업 주제 (예: "스마트공장 구축 지원", "AI 기술개발") — 무엇을 지원하는지이지 누가 신청하는지가 아니다
- 거래 상대·협력 기업 (예: "대기업과 협력한 실적")
- 지역·업력·기업 규모·매출 요건

상태
- known: 신청 가능 업종이 분명히 적혀 있다. industries 에 넣는다
- no_limit: "업종 제한 없음", "전 업종", "업종 무관" 처럼 **업종**에 제한이 없다고 명시했다
- unknown: 업종 언급이 없거나, 제외 업종만 있거나, 애매하다

규칙
- 제외 업종("유흥업 제외", "제조업은 신청 불가")은 excluded_industries 에만 넣는다. 제외만 있으면 unknown 이다.
- industries 는 주어진 어휘에서만 고른다. 어휘에 없는 업종(예: 바이오, 콘텐츠, 관광업)은 other_industries 에 원문 표현으로 적는다.
- quote 는 판단 근거 문장을 **입력에서 그대로 복사**한다. 고쳐 쓰지 않는다. 근거가 없으면 빈 문자열.
- 추측하지 않는다. 애매하면 unknown 이다."""

# v2 (2026-09-22) — v1 30건에서 본 오독 네 가지를 막으려 했다. 검사는 불충분했다(위 설명·Codex 리뷰 F1).
SYSTEM_V2 = SYSTEM + """

## 추가 규칙 (엄격)
- **근거 문장에 업종 이름이 글자로 있어야** known 이다. 업종을 짐작해서 붙이지 않는다.
  예) "중소기업", "기업부설연구소", "수출입 기업", "노동조합이 있는 사업장" → 업종이 없다 → unknown
- 기업 규모·형태(중소기업·중견기업·소상공인·스타트업·사회적기업·연구소기업·벤처기업)는 업종이 아니다.
- "OO 분야", "신산업", "주력산업", "기술분야"는 기술·사업 분야다. 업종 이름이 함께 적혀 있지 않으면 unknown 이다.
  단, "바이오 분야 기업만"처럼 대상 기업을 그 분야로 **한정**했으면 어휘에 맞추지 말고 other_industries 에 원문 그대로 적는다.
- 어휘의 넓은 분류(서비스업 등)는 원문에 그 말이 **그대로** 있을 때만 고른다. 가장 가까운 것을 고르지 않는다.
- 소상공인·중소기업 **정의**에 나오는 업종별 인원·매출 기준(예: "제조업·건설업은 상시근로자 10인 미만")은
  규모 기준이지 업종 제한이 아니다 → unknown
- 거의 모든 업종을 나열했거나 "기업·농가·소상공인·의료기관 등"처럼 대상을 넓게 열어 둔 문장은 제한이 아니다 → unknown"""

# v3 (2026-09-22 Codex 리뷰 F1) — 어휘에 맞추게 한 것이 목록 누락(무역업·여행사·지식·정보 관련업)을 만들었다.
# 이제 원문 표현을 그대로 받고, 어휘 라벨은 보조로만 쓴다.
SYSTEM_V3 = """너는 정부·지자체 지원사업 공고에서 **신청 가능한 업종 제한**만 찾는다.

찾는 것: 공고가 "어떤 업종의 기업만 신청할 수 있다"고 밝힌 자격 조건.

업종 제한이 **아닌** 것
- 지원 분야·사업 주제 (예: "스마트공장 구축 지원", "AI 기술개발")
- 거래 상대·협력 기업 (예: "대기업과 협력한 실적")
- 지역·업력·매출 요건
- 기업 규모·형태: 중소기업·중견기업·소상공인·스타트업·사회적기업·연구소기업·벤처기업·기업부설연구소
- 기술·사업 분야 표현("OO 분야", "신산업", "주력산업", "기술분야")은 대상 기업을 그 분야로 **한정**할 때만 업종으로 본다
- 소상공인·중소기업 **정의**에 나오는 업종별 인원·매출 기준(예: "제조업·건설업·운수업: 상시근로자 10인 미만")
- "기업·농가·소상공인·의료기관 등"처럼 대상을 넓게 열어 둔 문장

출력
- status: known(허용 업종이 분명함) · no_limit(업종 제한이 없다고 **명시**) · unknown(그 밖의 모든 경우)
- quote: **신청 자격(지원대상·신청대상) 문장**을 입력에서 그대로 복사한다. 허용 업종은 모두 이 문장 안에 있어야 한다.
  "지원대상 :" 같은 머리말이 있으면 **머리말부터 포함해** 복사한다. 짧은 조각만 떼어 오지 않는다.
  지원 내용·사업 목적 문장은 quote 가 될 수 없다. 근거가 없으면 빈 문자열
- allowed: 허용 업종 **하나하나**를 원문 표현 그대로 적는다. 어휘에 맞추려고 바꾸지 않는다.
  - text: 원문에 있는 그대로의 업종 표현 (예: "제조", "무역업", "여행사", "지식·정보 관련업")
  - label: 원문 표현이 아래 어휘의 업종명과 **같은 말**일 때만 그 업종명, 아니면 빈 문자열
  - evidence: text 가 들어 있는 원문 문장을 그대로 복사 (quote 의 일부여야 한다)
- excluded: 제외 업종을 원문 표현 그대로 (예: "유흥업", "금융ㆍ보험업"). 제외만 있으면 status 는 unknown 이다
  - evidence: "제외"·"불가" 같은 제외 표현이 함께 있는 원문 문장을 그대로 복사
- no_limit_text: no_limit 일 때 "업종 제한 없음" 같은 원문 표현. 아니면 빈 문자열
- list_complete: 원문에 적힌 허용 업종을 **빠짐없이** allowed 에 옮겼으면 true.
  원문이 "등"으로 끝나거나 별표·붙임·부록을 가리켜 전체 목록을 이 발췌에서 알 수 없으면 false
- 추측하지 않는다. 애매하면 unknown 이다."""

PROMPTS = {'v1': SYSTEM, 'v2': SYSTEM_V2, 'v3': SYSTEM_V3}
LEGACY_PROMPTS = ('v1', 'v2')

# v2 코드 검사 (옛 결과 재현용으로만 남긴다)
SURFACE = {'제조업': ('제조',), '서비스업': ('서비스업',), '도소매업': ('도매', '소매', '도·소매', '도ㆍ소매'),
           '음식점업': ('음식점', '외식', '음식업'), '숙박업': ('숙박',), '건설업': ('건설',),
           '농업': ('농업', '농가', '농산물', '농식품'), '어업': ('어업', '수산'), '축산업': ('축산',),
           '정보통신업': ('정보통신', '정보·통신', '정보ㆍ통신', 'IT', 'SW', '소프트웨어'),
           '물류업': ('물류',), '운수업': ('운수', '운송')}
SIZE_RULE_HINTS = ('상시근로자', '상시 근로자', '상시종업원')

# v3 검사
# 규모 **정의** 표시. 상시근로자 기준이 이 말들과 함께 있을 때만 정의로 보고 내린다
SIZE_DEFINITION_MARKERS = ('정의', '기본법', '소상공인이란', '에 의한 소상공인', '에 따른 소상공인',
                           '소상공인 기준', '중소기업 기준', '중소기업기본법')
# 전체 목록을 이 발췌에서 알 수 없다는 표시
INCOMPLETE_MARKERS = ('별표', '붙임', '부록', '별첨')
# quote 의 역할 판정 (2026-09-22 Codex 2차 후속 리뷰 F1)
#   처음에는 '대상'·'가능' 같은 단어 하나가 quote 에 있으면 신청 자격으로 봤다. 그랬더니
#   "지원내용: 제조업을 대상으로 디지털 전환 비용 지원" 이 신청 자격으로 통과했다.
#   이제 **가장 가까운 머리말**(quote 안이나 바로 앞 원문)이 자격 머리말인지, 지원 내용 머리말인지로 본다.
#   머리말이 없으면 "기업만"·"영위하는"·"에 한함" 같은 제한 서술어가 quote 안에 있어야 한다.
ELIGIBILITY_HEADERS = ('지원대상', '신청대상', '신청자격', '지원자격', '참여대상', '모집대상', '참가대상', '참가자격',
                       '지원가능업종', '신청가능', '지원가능', '신청요건', '자격요건', '신청자격요건',
                       # 컨소시엄 공고의 참여 주체 표시 — "ㅇ (수요기업) 제조공정의 … 제조기업"
                       '(수요기업)', '(공급기업)', '(주관기관)', '(참여기업)', '(신청기업)')
# 기업마당 요약(`bsnsSumryCn`) 형식: "개요 ☞ 지원대상 ☞ 지원내용 …".
# 실험 DB 기업마당 1,601건 모두 ☞ 가 2개 이상이고, 첫 구간이 신청 주체 명사(기업·업체·소상공인 등)로 끝나는 것 1,428건,
# 둘째 구간에 '지원'이 있는 것 1,548건(2026-09-22 Claude 집계). 그래서 첫 ☞ 를 자격 머리말, 둘째 ☞ 를 지원 내용 머리말로 본다.
# ☞ 가 2개 미만인 문서에는 적용하지 않는다.
BIZINFO_MARK = '☞'
_MARK_ELIGIBILITY, _MARK_SUPPORT = '【지원대상】', '【지원내용】'
SUPPORT_HEADERS = ('지원내용', '사업내용', '사업목적', '지원분야', '지원규모', '사업개요', '추진내용', '교육내용',
                   '지원사항', '사업목표', '지원혜택', '프로그램내용')
RESTRICTION_PHRASES = ('에한함', '에한하', '에한정', '으로한정', '로한정', '만신청', '만지원가능', '기업만', '업체만',
                       '사업자만', '영위하는', '영위중인', '영위기업')
HEADER_WINDOW = 80           # quote 앞에서 머리말을 찾는 거리(공백 뺀 글자 수)

# 제외 표현. excluded 값 **바로 뒤 같은 절**에 있거나, 값 앞에 제외 머리말이 있어야 한다(2차 후속 리뷰 F2)
# ('제한'은 넣지 않는다 — "제조업으로 제한"은 허용 목록을 말한다)
EXCLUSION_CUES = conditions.NEGATION_HINTS + ('금지', '배제')
EXCLUSION_HEADERS = ('지원제외', '제외대상', '제외업종', '신청제외', '참여제외', '불가업종', '제한업종', '제외기업')
# 제외가 아니라 포함·허용을 말하는 표현. 값과 제외 표현 사이에 있으면 둘은 연결되지 않은 것이다
POSITIVE_MARKERS = ('포함', '가능', '우대', '대상으로', '허용', '신청할수', '해당기업')
# 제외 머리말은 **콜론으로 목록을 열 때만** 인정한다. "유흥업은 지원 제외, 제조업…" 의 '지원 제외' 는 머리말이 아니다
_EXCLUSION_HEADER_RE = re.compile('(?:%s)[^:：]{0,6}[:：]' % '|'.join(EXCLUSION_HEADERS))
# 목록 항목 뒤에 붙어도 되는 말. 이 밖의 말("교육", "관련 사업")이 붙으면 목록 항목이 아니다(3차 후속 리뷰 F1)
LIST_TAIL_WORDS = ('', '등', '및', '또는', '등의')
# 절을 나누기 전에 값을 바꿔 둘 자리표시(사용자 영역 문자라 원문에 나오지 않는다)
_VALUE_TOKEN = ''

# 구역 경계 (3차 후속 리뷰 F1) — 등록되지 않은 "OO안내:" 같은 콜론 머리말과 □ 같은 새 구역 표시는 앞 자격 문맥을 끊는다
_GENERIC_HEADER_RE = re.compile(r'[가-힣A-Za-z()]{2,12}[:：]')
# 콜론 머리말의 이름에 이 말이 있으면 자격 머리말로 본다("참여업종:", "신청요건:"). 단어 하나를 본문에서 찾는 것이 아니라
# **콜론으로 끝나는 머리말 이름**에서만 쓴다
ELIGIBILITY_LABEL_WORDS = ('대상', '자격', '요건', '업종')
# 콜론 머리말 이름에 이 말이 있으면 **제외 목록**이다. 자격 판정보다 먼저 본다("제외업종:", "비대상 업종:")
EXCLUSION_LABEL_WORDS = ('제외', '불가', '비대상', '금지', '제한', '배제', '미해당')
SECTION_BULLETS = '□■◆◎▶'
LIST_ITEM_MAX = 20           # 쉼표로 이어진 목록 항목으로 볼 최대 길이(공백 뺀 글자 수)
_TRAILING_ETC = re.compile(r'등\s*[)\]」』]?\s*$|등\s*[,.·]|\s등\s')


def _squash(text):
    return ''.join((text or '').split())


def sha256_text(text):
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()


def read_jsonl(path):
    with io.open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def read_json(path):
    with io.open(path, encoding='utf-8') as f:
        return json.load(f)


def sha256_file(path):
    h = hashlib.sha256()
    with io.open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


# ─────────────────────────────────────────────────────────── 스키마

def schema_legacy():
    return {
        'name': 'industry_condition',
        'strict': True,
        'schema': {
            'type': 'object',
            'additionalProperties': False,
            'required': ['status', 'industries', 'other_industries', 'excluded_industries', 'quote', 'reason'],
            'properties': {
                'status': {'type': 'string', 'enum': ['known', 'no_limit', 'unknown']},
                'industries': {'type': 'array', 'items': {'type': 'string', 'enum': VOCAB}},
                'other_industries': {'type': 'array', 'items': {'type': 'string'}},
                'excluded_industries': {'type': 'array', 'items': {'type': 'string'}},
                'quote': {'type': 'string'},
                'reason': {'type': 'string'},
            },
        },
    }


def schema_v3():
    # 값마다 원문 근거(evidence)를 필수로 받는다 (2026-09-22 Codex 후속 리뷰 F1)
    item = {'type': 'object', 'additionalProperties': False, 'required': ['text', 'label', 'evidence'],
            'properties': {'text': {'type': 'string'},
                           'label': {'type': 'string', 'enum': VOCAB + ['']},
                           'evidence': {'type': 'string'}}}
    excluded = {'type': 'object', 'additionalProperties': False, 'required': ['text', 'evidence'],
                'properties': {'text': {'type': 'string'}, 'evidence': {'type': 'string'}}}
    return {
        'name': 'industry_condition_v3',
        'strict': True,
        'schema': {
            'type': 'object',
            'additionalProperties': False,
            'required': ['status', 'allowed', 'excluded', 'no_limit_text', 'list_complete', 'quote', 'reason'],
            'properties': {
                'status': {'type': 'string', 'enum': ['known', 'no_limit', 'unknown']},
                'allowed': {'type': 'array', 'items': item},
                'excluded': {'type': 'array', 'items': excluded},
                'no_limit_text': {'type': 'string'},
                'list_complete': {'type': 'boolean'},
                'quote': {'type': 'string'},
                'reason': {'type': 'string'},
            },
        },
    }


def schema_for(prompt):
    return schema_v3() if prompt == 'v3' else schema_legacy()


def system_message(prompt):
    """실제로 보내는 system 메시지. 프롬프트 해시는 이 문자열로 만든다."""
    return PROMPTS[prompt] + '\n\n업종 어휘: ' + ', '.join(VOCAB)


def prompt_sha256(prompt):
    return sha256_text(system_message(prompt))


def schema_sha256(prompt):
    return sha256_text(json.dumps(schema_for(prompt), ensure_ascii=False, sort_keys=True))


# ─────────────────────────────────────────────────────────── 검사

def verify_legacy(data, document, prompt='v1'):
    """v1·v2 검사. **옛 결과를 재현하는 용도로만 남긴다.** v2 검사의 약점은 Codex 리뷰 F1 참조."""
    quote = (data.get('quote') or '').strip()
    found = bool(quote) and _squash(quote) in _squash(document)
    out = dict(data, quote_found=found, llm_status=data.get('status'))
    if prompt == 'v2' and data.get('status') == 'known' and found:
        sq = _squash(quote)
        kept = [i for i in data.get('industries') or [] if any(_squash(s) in sq for s in SURFACE.get(i, (i,)))]
        other = [o for o in data.get('other_industries') or [] if _squash(o) in sq]
        dropped = sorted(set(data.get('industries') or []) - set(kept)) + \
            sorted(set(data.get('other_industries') or []) - set(other))
        out.update(industries=kept, other_industries=other, dropped_industries=dropped)
        if any(h in quote for h in SIZE_RULE_HINTS):
            out['status'] = 'unknown'
            out['downgraded'] = '근거가 업종별 인원 기준(규모 정의)'
            return out
    if data.get('status') in ('known', 'no_limit') and not found:
        out['status'] = 'unknown'
        out['downgraded'] = '근거 문장이 입력에 없음'
    if out.get('status') == 'known' and not (out.get('industries') or out.get('other_industries')):
        out['status'] = 'unknown'
        out['downgraded'] = out.get('downgraded') or ('근거 문장에 업종 글자가 없음' if prompt == 'v2'
                                                      else 'known 인데 업종이 비어 있음')
    return out


# 이전 이름. 저장된 v1·v2 결과를 만든 함수와 같은 동작이다
verify = verify_legacy


def label_basis(text, label):
    """원문 표현에 업종명이 그대로 있으면 exact. 뜻으로 옮긴 것(농가 → 농업)은 alias.

    '제조업' 라벨은 원문 '제조'도 exact 로 본다(업 한 글자만 뺀 어간이 두 글자 이상일 때만).
    '농업'의 어간 '농'처럼 한 글자는 다른 말에 너무 쉽게 걸려서 쓰지 않는다.
    """
    if not label:
        return ''
    t = _squash(text)
    if _squash(label) in t:
        return 'exact'
    stem = label[:-1] if label.endswith('업') else ''
    if len(stem) >= 2 and _squash(stem) in t:
        return 'exact'
    return 'alias'


def is_size_definition(quote):
    """소상공인·중소기업 **정의**의 업종별 인원 기준인가. 상시근로자 + 정의 표시가 함께 있어야 한다.

    "제조업을 영위하는 상시근로자 10인 이상 기업만 신청" 같은 실제 복합 신청 조건은 정의가 아니다(리뷰 F1 반례).
    """
    return any(h in quote for h in SIZE_RULE_HINTS) and any(m in quote for m in SIZE_DEFINITION_MARKERS)


def looks_incomplete(quote, texts):
    """이 발췌만으로 전체 허용 목록을 알 수 없다는 표시가 있는가."""
    blob = ' '.join([quote] + list(texts))
    if any(m in blob for m in INCOMPLETE_MARKERS):
        return True
    return bool(_TRAILING_ETC.search(quote or ''))


def _last_pos(text, words):
    return max((text.rfind(_squash(w)) for w in words), default=-1)


def _prepared_doc(document):
    """공백을 뺀 문서. 기업마당 요약 형식이면 첫 ☞ 를 자격 머리말, 둘째 ☞ 를 지원 내용 머리말로 바꾼다."""
    doc = _squash(document)
    if doc.count(BIZINFO_MARK) >= 2:
        doc = doc.replace(BIZINFO_MARK, _MARK_ELIGIBILITY, 1).replace(BIZINFO_MARK, _MARK_SUPPORT, 1)
    return doc.replace(BIZINFO_MARK, '')


def _header_events(window):
    """window 안의 머리말 사건 [(끝 위치, 'E'|'S'|'O')]. O 는 등록되지 않은 구역 머리말 — 앞 문맥을 끊는다.

    · 등록된 자격/지원 머리말은 콜론이 없어도 사건이다
    · "OO안내:"·"OO절차:" 처럼 콜론으로 끝나는 머리말은 등록 여부로 E/S/O 를 정한다
    · □·■·◆·◎·▶ 는 새 구역의 시작이라 O 다(○·❍·ㅇ·- 같은 하위 글머리는 구역을 끊지 않는다)
    """
    events = []
    for words, kind in ((ELIGIBILITY_HEADERS, 'E'), (SUPPORT_HEADERS, 'S')):
        for w in words:
            w = _squash(w)
            start = window.find(w)
            while start >= 0:
                events.append((start + len(w), kind))
                start = window.find(w, start + 1)
    for m in _GENERIC_HEADER_RE.finditer(window):
        label = m.group(0)
        # 제외 머리말을 먼저 본다 — "제외업종:"·"비대상 업종:" 이 '업종'·'대상' 때문에 자격 머리말이 되던 문제(4차 후속 리뷰 F1)
        if any(_squash(w) in label for w in EXCLUSION_HEADERS + EXCLUSION_LABEL_WORDS):
            kind = 'X'
        elif any(_squash(w) in label for w in SUPPORT_HEADERS):
            kind = 'S'
        elif any(_squash(w) in label for w in ELIGIBILITY_HEADERS + ELIGIBILITY_LABEL_WORDS):
            kind = 'E'
        else:
            kind = 'O'
        events.append((m.end(), kind))
    for m in re.finditer('[%s]' % SECTION_BULLETS, window):
        events.append((m.end(), 'O'))
    return sorted(events)


def _role_at(doc, at, q):
    window = doc[max(0, at - HEADER_WINDOW):at] + q
    events = _header_events(window)
    last = events[-1][1] if events else None
    if last == 'X':
        return 'exclusion', '가장 가까운 머리말이 제외 목록'
    if last == 'S':
        return 'support', '가장 가까운 머리말이 지원 내용 문맥'
    if last == 'E':
        return 'eligibility', '자격 머리말'
    if any(p in q for p in RESTRICTION_PHRASES):
        return 'eligibility', '제한 서술어'
    if last == 'O':
        return 'unclear', '가장 가까운 머리말이 등록되지 않은 구역(앞 자격 문맥을 잇지 않음)'
    return 'unclear', '자격 머리말·제한 서술어 없음'


def quote_role(quote, document):
    """quote 가 신청 자격 문장인가. ('eligibility' | 'support' | 'unclear', 설명).

    quote 와 그 바로 앞 원문(HEADER_WINDOW 글자)에서 **가장 가까운 머리말**을 본다(2차·3차 후속 리뷰 F1).
      · 지원 내용 머리말이 더 가까우면 support — "지원내용: 제조업을 대상으로…" 는 자격이 아니다
      · 자격 머리말이 더 가까우면 eligibility
      · 등록되지 않은 구역 머리말("기타 안내:")이나 □ 같은 새 구역 표시가 더 가까우면 앞 자격 문맥을 잇지 않는다
      · 머리말이 없거나 끊겼으면 quote 안의 제한 서술어("기업만"·"영위하는"·"에 한함")로만 eligibility
    같은 문자열이 문서에 여러 번 나오면 모든 위치를 보고, 역할이 갈리면 unclear 다(LLM 이 어느 쪽을 복사했는지 모른다).
    '대상'·'가능' 같은 단어 하나는 증거로 쓰지 않는다. build_document() 가 줄바꿈을 공백으로 합치므로 줄 단위 경계는 쓸 수 없다.
    """
    q = _squash(quote).replace(BIZINFO_MARK, '')
    if not q:
        return 'unclear', 'quote 없음'
    doc = _prepared_doc(document)
    positions, start = [], doc.find(q)
    while start >= 0:
        positions.append(start)
        start = doc.find(q, start + 1)
    if not positions:
        return _role_at('', 0, q)
    roles = {_role_at(doc, at, q) for at in positions}
    if len({r for r, _ in roles}) > 1:
        return 'unclear', '같은 문장이 역할이 다른 여러 구역에 있음'
    return sorted(roles)[0]


def _protect(evidence, text):
    """값 안의 구분기호(금융ㆍ보험업의 ㆍ)로 값이 잘리지 않게, 절을 나누기 전에 값을 자리표시로 바꾼다(3차 후속 리뷰 F2)."""
    t = _squash(text)
    if not t:
        return evidence, None
    pattern = re.compile(r'\s*'.join(re.escape(ch) for ch in t))
    if not pattern.search(evidence or ''):
        return evidence, None
    return pattern.sub(_VALUE_TOKEN, evidence), _VALUE_TOKEN


def _clauses(evidence):
    """제외 관계를 볼 절. 마침표·세미콜론·줄바꿈으로 문장을 나누고, 쉼표·가운뎃점으로 절을 나눈다(원문 공백 유지)."""
    out = []
    for sentence in re.split(r'[.;\n]', evidence or ''):
        parts = [p.strip() for p in re.split(r'[,，·ㆍ、]', sentence)]
        out.append([p for p in parts if p])
    return out


def _new_subject(raw):
    """원문 조각에 새 주어·주제("제조업은", "기업이")가 있는가. 목록 끝의 "등은/등이"는 제외한다."""
    for word in (raw or '').split():
        if word.endswith(('등은', '등는', '등이', '등가')):
            continue
        if word.endswith(('은', '는', '이', '가')) and len(word) >= 2:
            return True
    return False


def excluded_linked(text, evidence):
    """제외 값이 제외 표현과 **같은 절에서 연결**되는가. (True/False, 설명).

    인정하는 경우
      · 값 바로 뒤 같은 절에 제외 표현이 있고, 그 사이에 포함·허용 표현이 없다  ("유흥업은 지원 제외", "금융ㆍ보험업은 지원 제외")
      · 값 앞에 콜론으로 목록을 여는 제외 머리말이 있고, 그 사이가 목록 항목뿐이다 ("지원제외 업종: 유흥업, 도박업")
      · 값이 쉼표 목록의 **항목 그 자체**이고(값 뒤에 다른 말이 없다), 목록이 새 주어 없이 제외 표현으로 끝난다
        ("유흥업, 도박업 등은 지원 제외")
    인정하지 않는 경우 (리뷰 반례)
      · "유흥업 교육 포함, 제조업은 지원 제외" · "유흥업 교육, 제조업은 지원 제외" · "유흥업 관련 사업, 제조업은 지원 제외"
        — 유흥업 뒤에 다른 말이 붙어 목록 항목이 아니거나, 끝 절에 새 주어(제조업은)가 있다
      · "유흥업, 제조업은 지원 제외" 도 새 주어 때문에 유흥업을 인정하지 않는다(보수적으로 놓치는 쪽)
    """
    evidence, token = _protect(evidence, text)
    if token is None:
        return False, '근거에서 값을 찾지 못함'
    cues = [_squash(c) for c in EXCLUSION_CUES]
    positives = [_squash(p) for p in POSITIVE_MARKERS]

    def first_cue(s):
        found = [s.find(c) for c in cues if c and c in s]
        return min(found) if found else -1

    def has_positive(s):
        return any(p in s for p in positives)

    def list_like(raw):
        s = _squash(raw)
        return len(s) <= LIST_ITEM_MAX and not has_positive(s) and first_cue(s) < 0 and not _new_subject(raw)

    def under_header(clauses, i, pos):
        """값 앞에 "지원제외 업종:" 머리말이 있고, 머리말과 값 사이가 목록 항목뿐인가."""
        heads = [_squash(c) for c in clauses[:i]] + [_squash(clauses[i])[:pos]]
        for k in range(len(heads) - 1, -1, -1):
            matches = list(_EXCLUSION_HEADER_RE.finditer(heads[k]))
            if not matches:
                continue
            segs = [heads[k][matches[-1].end():]] + ([] if k == i else heads[k + 1:])
            return all(list_like(s) for s in segs)
        return False

    for clauses in _clauses(evidence):
        for i, raw in enumerate(clauses):
            clause = _squash(raw)
            pos = clause.find(token)
            if pos < 0:
                continue
            if under_header(clauses, i, pos):
                return True, '제외 머리말 뒤의 값'
            after = clause[pos + len(token):]
            c = first_cue(after)
            if c >= 0:
                return (False, '값과 제외 표현 사이에 포함·허용 표현') if has_positive(after[:c]) \
                    else (True, '같은 절의 제외 표현')
            if after not in LIST_TAIL_WORDS:
                return False, '값 뒤에 다른 말이 있어 목록 항목이 아님'
            for nxt_raw in clauses[i + 1:]:              # 쉼표 목록이 이어지는가
                nxt = _squash(nxt_raw)
                c = first_cue(nxt)
                if c >= 0:
                    if has_positive(nxt[:c]):
                        return False, '목록 끝 절에 포함·허용 표현'
                    if _new_subject(_cut_before_cue(nxt_raw, cues)):
                        return False, '목록 끝 절에 새 주어'
                    return True, '목록 끝의 제외 표현'
                if not list_like(nxt_raw):
                    return False, '제외 표현 전에 목록 항목이 아닌 말이 끼어 있음'
            return False, '같은 절에 제외 표현 없음'
    return False, '근거에서 값을 찾지 못함'


def _cut_before_cue(raw, cues):
    """원문 조각에서 첫 제외 표현 앞부분(공백 유지)."""
    best = None
    for c in cues:
        pattern = re.compile(r'\s*'.join(re.escape(ch) for ch in c)) if c else None
        m = pattern.search(raw) if pattern else None
        if m and (best is None or m.start() < best):
            best = m.start()
    return raw if best is None else raw[:best]


# ─────────────────────────────────────────────────────────── 검사 강도 (2026-09-22 사용자 요청 — "러프하게")
#
#   strict  지금까지의 v3 검사. 근거 문장이 원문과 글자 그대로 같아야 하고, quote 가 자격 머리말 아래에 있어야 한다
#   rough   원문 대조에서 공백·글머리표·가운뎃점·괄호·원문자 차이를 무시하고, 근거 문장이 80% 이상 이어서 같으면 인정한다.
#           quote 가 **지원 내용·제외 목록으로 확실히 보일 때만** 떨어뜨린다(애매함 unclear 는 살린다).
#           규모·형태 단어 거르기, 제한 없음 명시 확인, 제외 업종 연결 확인, 규모 정의 하향은 strict 와 같다.
#   Codex 전량 리뷰 F2: luna 가 known 이라 한 692건 중 157건을 strict 가 내렸고 그중 일부는 공백·서식 차이였다.
PROFILES = ('strict', 'rough')
_LOOSE_DROP = re.compile(r'[\s□■◆◇◎▶▷❑❍○●◦•ㅇ\-–—·ㆍ・‧※*:：()（）\[\]【】「」『』<>〈〉"\'“”‘’,.;·①-⑳❶-➓]')
FUZZY_MIN_RATIO = 0.8
# 업종이 아닌 규모·형태 단어. 허용 값이 이 말뿐이면 뺀다(두 강도 모두 — Codex 전량 리뷰 F2 "사회적기업" 오염)
SIZE_FORM_WORDS = {'중소기업', '소상공인', '기업', '중견기업', '중소중견기업', '중소벤처기업', '스타트업', '벤처기업',
                   '사회적기업', '예비사회적기업', '연구소기업', '기업부설연구소', '창업기업', '예비창업자', '법인',
                   '개인사업자', '협동조합', '사회적협동조합'}


def _loose(text):
    return _LOOSE_DROP.sub('', text or '')


def loose_found(part, whole):
    """rough 대조: 느슨한 정규화 뒤 포함되거나, 가장 길게 이어서 같은 부분이 FUZZY_MIN_RATIO 이상이면 True."""
    p, w = _loose(part), _loose(whole)
    if not p:
        return False
    if p in w:
        return True
    if len(p) < 8:
        return False
    from difflib import SequenceMatcher
    m = SequenceMatcher(None, p, w, autojunk=False).find_longest_match(0, len(p), 0, len(w))
    return m.size / len(p) >= FUZZY_MIN_RATIO


def is_size_form_value(text):
    return _loose(text) in {_loose(w) for w in SIZE_FORM_WORDS}


# 제외 목록 머리말 (2026-09-22 사용자 요청 — final2 의 확인 필요 333건 중 248건이 "제외 목록의 한 줄"을 근거로 가져왔는데
# "□ 지원 제외 대상" 머리말은 그 윗줄에 있어 연결 검사를 못 넘었다). rough 검사에서만 쓴다.
EXCLUSION_HEADER_RE = re.compile(
    r'(?:지원|신청|참여|참가|융자|보증|대출|가입|정책자금|사업참여|사업)\s*(?:제외|제한|불가)\s*(?:대상|업종|기업|사업자|분야)?'
    r'|(?:제외|제한)\s*(?:대상|업종)')
EXCLUSION_WINDOW = 600        # 근거 앞에서 제외 머리말을 찾는 거리(공백 뺀 글자 수)


def exclusion_by_header(evidence, document):
    """근거 바로 앞 원문에서 **가장 가까운 머리말이 제외 머리말**인가. (True/False, 설명).

    quote_role() 과 같은 머리말 사건(_header_events)에 제외 머리말(EXCLUSION_HEADER_RE)을 더해 가장 가까운 것을 본다.
    자격·지원 내용·다른 구역 머리말(□ 등)이 더 가까우면 인정하지 않는다. 근거에 포함·허용 표현이 있으면 인정하지 않는다.
    """
    ev = _squash(evidence)
    if not ev or any(_squash(p) in ev for p in POSITIVE_MARKERS):
        return False, '근거에 포함·허용 표현이 있음'
    doc = _prepared_doc(document)
    at = doc.find(ev.replace(BIZINFO_MARK, ''))
    if at < 0 and len(ev) >= 12:
        at = doc.find(ev[:12])
    if at < 0:
        return False, '근거 위치를 원문에서 찾지 못함'
    window = doc[max(0, at - EXCLUSION_WINDOW):at + len(ev)]
    head = window[:len(window) - len(ev)]            # 근거 앞부분만 본다
    events = _header_events(head) + [(m.end(), 'X') for m in EXCLUSION_HEADER_RE.finditer(head)]
    if not events:
        return False, '근거 앞에 머리말이 없음'
    last = max(events)[1]
    return (True, '근거 윗줄의 제외 머리말') if last == 'X' else (False, '가장 가까운 머리말이 제외 머리말이 아님')


def _evidence_problem(text, evidence, doc):
    """값 하나의 원문 근거 검사. 문제가 없으면 None."""
    if not text:
        return '값이 비어 있음'
    if not evidence:
        return '근거(evidence) 없음'
    if _squash(evidence) not in doc:
        return '근거가 원문에 없음'
    if _squash(text) not in _squash(evidence):
        return '값이 근거 문장 안에 없음'
    return None


# 매칭용 판정 (2026-09-22 사용자 결정) — "확인 불가" 1,206건의 90%가 "자격 문장은 있는데 업종 언급이 없음"이었다.
# 정부 지원사업 대부분은 업종을 가리지 않으므로 이를 "업종 제한 없음(언급 없음, 추정)"으로 따로 둔다.
# 명시된 제한 없음(no_limit)과는 **다른 값**으로 남긴다 — 값 없음과 제한 없음을 뭉개지 않는다는 원칙(conditions.py).
INDUSTRY_STATUS = {
    'known': '업종 제한 있음',
    'no_limit': '업종 제한 없음(명시)',
    'not_mentioned': '업종 제한 없음(공고에 언급 없음·추정)',
    'excluded_only': '제외 업종만 있음(나머지 업종은 가능)',
    'conditional': '조건부·세부사업별(확인 필요)',
    'unknown': '확인 필요',
}
TRUNCATION_MARGIN = 50        # 발췌가 상한에서 이만큼 안쪽이면 잘린 것으로 본다
# 통합공고는 여러 세부사업을 한 공고에 담는다 — 한 세부사업의 업종 조건을 공고 전체 조건으로 쓰면 안 된다(Codex 후속 리뷰 F1)
UMBRELLA_TITLE = re.compile(r'통합\s*공고')


def _conditional_all(out):
    """허용 목록에 '전 업종'이 구체 업종과 함께 있으면 조건부 분기다("중점 육성기업이면 전 업종")."""
    from experiments.sql_semantic import industry_groups
    groups = [industry_groups.group_of(a['text']) for a in out.get('allowed') or []]
    return any(g == ['ALL'] for g in groups) and len(groups) > 1


def industry_status(out, document, excerpt_cap, title=''):
    """검사 결과 → 매칭용 판정과 그 이유. (코드, 이유).

    2026-09-22 Codex 후속 리뷰 반영:
      · 제외 업종 **후보**가 하나라도 있었으면(검사에서 빠졌어도) 언급 없음으로 올리지 않는다 → 확인 필요 (F1, 244건)
      · 허용 업종 후보가 검사에서 빠졌어도 마찬가지
      · 통합공고의 known, 전 업종이 구체 업종과 섞인 known 은 조건부(conditional) (F1)
      · 발췌가 상한에서 잘렸으면 판정과 상관없이 out['truncated']=True, list_complete=False (F2)
    """
    truncated = bool(excerpt_cap) and len(document or '') >= excerpt_cap - TRUNCATION_MARGIN
    out['truncated'] = truncated
    if truncated:
        out['list_complete'] = False
    cut = ' (발췌가 %d자에서 잘려 목록이 더 있을 수 있음)' % excerpt_cap if truncated else ''
    if out['status'] == 'known':
        if UMBRELLA_TITLE.search(title or ''):
            return 'conditional', '통합공고 — 세부사업마다 업종 조건이 다를 수 있음' + cut
        if _conditional_all(out):
            return 'conditional', '전 업종과 구체 업종이 함께 있음 — 조건부 분기일 수 있음' + cut
        return 'known', cut.strip()
    if out['status'] == 'no_limit':
        return 'no_limit', cut.strip()
    if out.get('downgraded'):
        return 'unknown', '검사가 내림: ' + out['downgraded']
    if out.get('excluded'):
        return 'excluded_only', cut.strip()
    dropped_kinds = {d.get('kind') for d in out.get('dropped') or []}
    if 'excluded' in dropped_kinds:
        return 'unknown', '제외 업종 후보가 있으나 검사를 통과하지 못함'
    if 'allowed' in dropped_kinds or out.get('raw_allowed'):
        return 'unknown', '허용 업종 후보가 있으나 검사를 통과하지 못함'
    if not (out.get('quote') or '').strip():
        return 'unknown', '자격 문장을 찾지 못함'
    if truncated:
        return 'unknown', '발췌가 %d자 상한에서 잘림 — 업종 조건이 잘린 부분에 있을 수 있음' % excerpt_cap
    return 'not_mentioned', ''


def verify_v3(data, document, profile='strict', excerpt_cap=None, title=''):
    """v3 검사. 값 하나하나를 **그 값의 원문 근거**와 대조한다(Codex 리뷰 F1, 후속 리뷰 F1).

    profile 은 'strict'(기본) 또는 'rough' — 위 PROFILES 설명. 두 강도 모두 끝에서 불변식을 지킨다(Codex 전량 리뷰 F1):
    최종 known 이 아니면 allowed 를 비우고 raw_allowed 에 옮긴다. 최종 no_limit 이 아니면 no_limit_text 를 비운다.

    남기는 것
      allowed   evidence 가 원문에 있고, 값이 evidence 안에 있고, **값이 신청 자격 quote 안에 있을 때**만.
                지원 내용·다른 조항에서 본 업종을 신청 제한으로 옮기지 않게 한다(후속 리뷰 반례).
                라벨은 exact/alias 로 나눠 적는다(alias 는 정확한 업종명 검사를 통과한 게 아니다)
      excluded  evidence 가 원문에 있고, 값이 evidence 안에 있고, evidence 에 제외 표현이 있을 때만
    상태
      known     quote 가 원문에 있고, 신청 자격 문장 표시가 있고, 남은 허용 값이 하나 이상이고, 규모 정의가 아닐 때
      no_limit  no_limit_text 가 원문에 있고 conditions.INDUSTRY_NO_LIMIT_RE 에 맞을 때
      그 밖     unknown (내린 이유를 downgraded 에 적는다)
    """
    if profile not in PROFILES:
        raise ValueError(profile)
    rough = profile == 'rough'
    doc = _squash(document)
    quote = (data.get('quote') or '').strip()
    quote_sq = _squash(quote)
    quote_found = bool(quote) and (loose_found(quote, document) if rough else quote_sq in doc)
    out = {'llm_status': data.get('status'), 'quote': quote, 'quote_found': quote_found,
           'reason': data.get('reason') or '', 'llm_list_complete': bool(data.get('list_complete')),
           'allowed': [], 'excluded': [], 'dropped': [], 'no_limit_text': '', 'profile': profile}

    for item in data.get('allowed') or []:
        text = (item.get('text') or '').strip()
        label = (item.get('label') or '').strip()
        evidence = (item.get('evidence') or '').strip()
        if rough:
            # 값이 원문에 있고, quote 나 자기 근거 안에 있으면 된다(근거 문장이 조금 달라도 괜찮다)
            if not text or not loose_found(text, document):
                why = '원문에 없음'
            elif not (_loose(text) in _loose(quote) or (evidence and _loose(text) in _loose(evidence)
                                                          and loose_found(evidence, document))):
                why = '신청 자격 근거 밖의 업종'
            else:
                why = None
        else:
            why = _evidence_problem(text, evidence, doc)
            if why is None and not (quote_found and _squash(text) in quote_sq):
                why = '신청 자격 근거(quote) 밖의 업종'
        if why is None and is_size_form_value(text):
            why = '규모·형태 표현(업종 아님)'
        if why:
            out['dropped'].append({'kind': 'allowed', 'text': text, 'evidence': evidence, 'why': why})
            continue
        basis = label_basis(text, label)
        out['allowed'].append({'text': text, 'label': label if basis == 'exact' else '',
                               'label_suggested': label if basis == 'alias' else '',
                               'label_basis': basis, 'evidence': evidence})
    for item in data.get('excluded') or []:
        text = (item.get('text') or '').strip()
        evidence = (item.get('evidence') or '').strip()
        if rough:
            why = None if (text and evidence and loose_found(evidence, document)
                           and _loose(text) in _loose(evidence)) else '근거가 원문에 없거나 값이 근거 밖'
        else:
            why = _evidence_problem(text, evidence, doc)
        linked_by = 'clause'
        if why is None:
            linked, how = excluded_linked(text, evidence)
            if not linked and rough:
                # 근거가 제외 목록의 한 줄이고 머리말이 윗줄에 있는 경우(2026-09-22)
                by_header, how_h = exclusion_by_header(evidence, document)
                if by_header:
                    linked, linked_by = True, 'header'
                else:
                    how = '%s / %s' % (how, how_h)
            if not linked:
                why = '제외 표현과 연결되지 않음(%s)' % how
        if why:
            out['dropped'].append({'kind': 'excluded', 'text': text, 'evidence': evidence, 'why': why})
            continue
        out['excluded'].append({'text': text, 'evidence': evidence, 'linked_by': linked_by})

    status = data.get('status')
    reason = None
    if status == 'no_limit':
        nl = (data.get('no_limit_text') or '').strip()
        if not nl or not (loose_found(nl, document) if rough else _squash(nl) in doc):
            reason = 'no_limit 표현이 원문에 없음'
        elif not conditions.INDUSTRY_NO_LIMIT_RE.search(nl):
            reason = 'no_limit 표현이 업종 제한 없음이 아님'
        else:
            out['no_limit_text'] = nl
    elif status == 'known':
        if not quote_found:
            reason = '근거 문장이 원문에 없음'
        elif is_size_definition(quote):
            reason = '근거가 규모 정의의 업종별 인원 기준'
        else:
            role, how = quote_role(quote, document)
            out['quote_role'] = role
            blocked = ('support', 'exclusion') if rough else ('support', 'exclusion', 'unclear')
            if role in blocked:
                reason = 'quote 가 신청 자격 문장으로 보이지 않음(%s)' % how
            elif not out['allowed']:
                reason = '원문에 있는 허용 업종 표현이 없음'
    elif status != 'unknown':
        reason = '알 수 없는 상태 %r' % status
    out['status'] = 'unknown' if reason else (status or 'unknown')
    if reason:
        out['downgraded'] = reason

    # 목록 완전성: LLM 이 true 라고 해도 코드가 볼 수 있는 누락 표시가 있으면 false 로 내린다
    complete = out['llm_list_complete']
    why_incomplete = []
    if any(d['kind'] == 'allowed' for d in out['dropped']):
        why_incomplete.append('근거 검사에서 허용 값을 뺐음')
    if looks_incomplete(quote, [a['text'] for a in out['allowed']]):
        why_incomplete.append('별표·"등" 등 전체 목록이 발췌 밖에 있다는 표시')
    if why_incomplete:
        complete = False
    out['list_complete'] = bool(complete) and out['status'] == 'known'
    out['incomplete_why'] = why_incomplete
    # 불변식(Codex 전량 리뷰 F1): 최종 상태와 값이 어긋나지 않게 한다. 버린 후보는 raw_allowed 에만 둔다
    if out['status'] != 'known':
        out['raw_allowed'] = out['allowed']
        out['allowed'] = []
    if out['status'] != 'no_limit':
        out['no_limit_text'] = ''
    cap = ec.MAX_CHARS if excerpt_cap is None else excerpt_cap
    out['industry_status'], out['industry_status_why'] = industry_status(out, document, cap, title)
    out['excerpt_cap'] = cap
    # 이 실험의 어떤 결과도 탈락 필터에 쓰지 않는다. 쓸 수 있는 조건을 만족해도 사람 정답 확인 전에는 False
    out['filter_ready'] = False
    return out


def verify_for(prompt, data, document, profile='strict', excerpt_cap=None, title=''):
    if prompt == 'v3':
        return verify_v3(data, document, profile, excerpt_cap, title)
    return verify_legacy(data, document, prompt)


# ─────────────────────────────────────────────────────────── 입력

def pick_sample(lab_connection, take_all=False):
    """(대상 공고 ID, 모집단 수). take_all 이면 실험 DB 공고 전부(2026-09-22 사용자 요청 — luna 전량)."""
    with lab_connection.cursor() as cursor:
        cursor.execute('SELECT notice_id FROM lab_notices ORDER BY notice_id')
        ids = [r[0] for r in cursor.fetchall()]
    if take_all:
        return ids, len(ids)
    rng = random.Random(SEED)
    return sorted(rng.sample(ids, min(SAMPLE, len(ids)))), len(ids)


def load_items(lab_connection, source_connection, ids, max_chars=None):
    """실험 DB 의 공고 칸 + 정규식 판정, 출처 DB 의 첨부 본문."""
    items = []
    with lab_connection.cursor() as cursor:
        for nid in ids:
            cursor.execute('SELECT notice_id, title, body, target_text, target_category, category, subcategory '
                           'FROM lab_notices WHERE notice_id = %s', (nid,))
            row = dict(zip(('notice_id', 'title', 'body', 'target_text', 'target_category',
                            'category', 'subcategory'), cursor.fetchone()))
            cursor.execute("SELECT status, value_text, evidence FROM lab_conditions "
                           "WHERE notice_id = %s AND field = 'industry'", (nid,))
            r = cursor.fetchone()
            row['regex'] = {'status': r[0], 'value': r[1], 'evidence': r[2]} if r else None
            items.append(row)
    with source_connection.cursor() as cursor:
        for item in items:
            cursor.execute("""
                SELECT at.extracted_text
                  FROM notices n
                  JOIN notice_attachments na ON na.notice_fk = n.id
                  JOIN attachment_texts at ON at.attachment_fk = na.id
                 WHERE n.notice_id = %s AND at.last_status = 'ok' AND at.extracted_text IS NOT NULL
                 ORDER BY at.text_chars DESC""", (item['notice_id'],))
            item['attachments'] = [r[0] for r in cursor.fetchall()]
    for item in items:
        prepare(item, max_chars)
    return items


def prepare(item, max_chars=None):
    """문서를 만들고 지문을 붙인다. 테스트는 DB 없이 이 함수만 부른다."""
    item['body'] = item.get('body') or ''
    item['target_text'] = item.get('target_text') or ''
    item['attachments'] = item.get('attachments') or []
    # max_chars: 발췌 상한(기본 ec.MAX_CHARS=6000). 잘린 공고만 길게 다시 읽을 때 늘린다(2026-09-22)
    item['document'] = ec.build_document(item, max_chars=max_chars or ec.MAX_CHARS)
    item['document_sha256'] = sha256_text(item['document'])
    item['attachment_sha256'] = [sha256_text(a) for a in item['attachments']]
    return item


def resume_key(notice_id, document_sha, prompt, model=MODEL):
    """스키마가 바뀌면 같은 프롬프트라도 다시 부른다(후속 리뷰 F2)."""
    return '%s|%s|%s|%s|%s' % (notice_id, document_sha, prompt_sha256(prompt), schema_sha256(prompt), model)


def estimate_tokens(text):
    """한국어는 대략 1.3자당 1토큰으로 잡는다(보수적 추정). 실제 사용량은 응답의 usage 로 기록한다."""
    return int(len(text) / 1.3) + 1


# ─────────────────────────────────────────────────────────── 이전 실행·체크포인트

def load_previous(folder, items):
    """이전 실행 결과와 비교 등급.

    exact    ID 와 document_sha256 이 모두 같다 → 정식 전후 비교
    limited  이전 결과에 문서 해시가 없다 → ID·문자 수·첨부 수만 대조한 제한적 비교
    문서 해시가 하나라도 다르면 비교를 거부한다.
    """
    previous, prev_rows = {}, {}
    for row in read_jsonl(os.path.join(folder, 'results.jsonl')):
        prev_rows[row['notice_id']] = row
    missing = [it['notice_id'] for it in items if it['notice_id'] not in prev_rows]
    if missing:
        raise SystemExit('이전 실행과 표본이 다르다: %s' % missing[:5])
    grade = 'exact'
    for it in items:
        row = prev_rows[it['notice_id']]
        prev_sha = row.get('document_sha256')
        if prev_sha is None:
            grade = 'limited'
            if row.get('doc_chars') not in (None, len(it['document'])) or \
                    row.get('attachments_count') not in (None, len(it['attachments'])):
                raise SystemExit('이전 실행과 문서 길이·첨부 수가 다르다: %s' % it['notice_id'])
        elif prev_sha != it['document_sha256']:
            raise SystemExit('이전 실행과 문서 내용이 다르다(document_sha256): %s' % it['notice_id'])
        previous[it['notice_id']] = row.get('llm')
    meta_path = os.path.join(folder, 'meta.json')
    prev_prompt = read_json(meta_path).get('prompt', 'v1') if os.path.exists(meta_path) else 'v1'
    return previous, prev_prompt, grade


def load_checkpoint(folder):
    done = {}
    path = os.path.join(folder, 'checkpoint.jsonl')
    if os.path.exists(path):
        for row in read_jsonl(path):
            done[row['key']] = row
    return done


def append_jsonl(path, row):
    with io.open(path, 'a', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


# ─────────────────────────────────────────────────────────── 호출

def request_options(model, effort=None):
    """모델별 호출 옵션. 추론 모델에는 temperature 를 보내지 않는다."""
    if is_reasoning(model):
        return {'reasoning_effort': effort} if effort else {}
    if effort:
        raise SystemExit('%s 는 추론 모델이 아니라 --reasoning-effort 를 쓸 수 없다' % model)
    return {'temperature': 0}


def ask(client, item, prompt, model=MODEL, effort=None):
    started = time.time()
    response = client.chat.completions.create(
        model=model, **request_options(model, effort),
        messages=[{'role': 'system', 'content': system_message(prompt)},
                  {'role': 'user', 'content': '공고 제목: %s\n\n공고문 발췌:\n%s'
                                              % (item['title'], item['document'])}],
        response_format={'type': 'json_schema', 'json_schema': schema_for(prompt)})
    data = json.loads(response.choices[0].message.content)
    usage = response.usage
    details = getattr(usage, 'completion_tokens_details', None)
    # completion_tokens 에 추론 토큰이 포함된다(출력 요금). 얼마나 생각했는지 따로 남긴다
    reasoning = getattr(details, 'reasoning_tokens', None) if details is not None else None
    return data, {'in': usage.prompt_tokens, 'out': usage.completion_tokens, 'reasoning': reasoning,
                  'ms': round((time.time() - started) * 1000), 'model': getattr(response, 'model', None)}


def run_calls(items, prompt, outdir, call, workers=6, engine=MODEL, reuse=True):
    """체크포인트에 없는 공고만 부른다. 성공은 바로 checkpoint.jsonl, 실패는 failures.jsonl 에 적는다.

    `call(item)` 은 (data, usage) 를 돌려준다. 테스트에서 가짜를 넣는다. `engine` 은 모델@추론강도.
    `reuse=False` 면 폴더의 체크포인트를 읽지 않는다 — 새 실행이 옛 응답을 조용히 섞지 않게(Codex 전량 리뷰 F2).
    """
    done = load_checkpoint(outdir) if reuse else {}
    todo = [it for it in items if resume_key(it['notice_id'], it['document_sha256'], prompt, engine) not in done]
    failures = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(call, it): it for it in todo}
        for fut in as_completed(futures):
            it = futures[fut]
            key = resume_key(it['notice_id'], it['document_sha256'], prompt, engine)
            try:
                data, usage = fut.result()
            except Exception as exc:                     # 실패한 것만 적고 나머지는 계속한다
                row = {'key': key, 'notice_id': it['notice_id'],
                       'error': '%s: %s' % (type(exc).__name__, str(exc).splitlines()[0] if str(exc) else '')}
                failures.append(row)
                append_jsonl(os.path.join(outdir, 'failures.jsonl'), row)
                continue
            row = {'key': key, 'notice_id': it['notice_id'], 'data': data, 'usage': usage,
                   'prompt_sha256': prompt_sha256(prompt), 'schema_sha256': schema_sha256(prompt),
                   'document_sha256': it['document_sha256']}
            done[key] = row
            append_jsonl(os.path.join(outdir, 'checkpoint.jsonl'), row)
    return done, failures, len(todo)


# ─────────────────────────────────────────────────────────── 보고서

def _count(items, key):
    c = {'known': 0, 'no_limit': 0, 'unknown': 0}
    for it in items:
        src = it.get(key) or {}
        s = src.get('status') or 'unknown'
        c[s] = c.get(s, 0) + 1
    return c


def _cell(text, n=60):
    return (text or '')[:n].replace('|', '/').replace('\n', ' ')


def write_report(outdir, items, meta):
    os.makedirs(outdir, exist_ok=True)
    keep = ('notice_id', 'title', 'category', 'target_category', 'regex', 'llm', 'usage', 'doc_chars',
            'attachments_count', 'document_sha256', 'attachment_sha256', 'source_run')
    with io.open(os.path.join(outdir, 'results.jsonl'), 'w', encoding='utf-8', newline='\n') as f:
        for it in items:
            f.write(json.dumps(dict({k: it.get(k) for k in keep}, run_at=meta['run_at']),
                               ensure_ascii=False) + '\n')
    with io.open(os.path.join(outdir, 'meta.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

    done_items = [it for it in items if it.get('llm') is not None]
    rx, llm = _count(items, 'regex'), _count(done_items, 'llm')
    has_prev = any(it.get('previous') for it in items)
    lines = ['# 업종 LLM 추출 표본 (프롬프트 %s) — %s' % (meta['prompt'], meta['run_at']), '',
             '**정답(사람 판정) 없음.** 확보율·비용·오독 유형을 보는 표본이다. DB 에 쓰지 않았다. '
             '**어떤 결과도 탈락 필터에 쓰지 않는다.**', '']
    if meta.get('failures'):
        lines += ['**미완료: 실패 %d건.** `--prompt %s --resume %s` 로 이어 한다. 아래 집계는 성공한 %d건만이다.'
                  % (meta['failures'], meta['prompt'], outdir, len(done_items)), '']
    if meta.get('mixed_models'):
        lines += ['**혼합 실행: 응답 모델이 여러 개다(%s).** 재개 사이에 모델이 바뀌었다. 이 결과로 비교를 확정하지 않는다.'
                  % ', '.join(meta.get('response_models') or []), '']
    lines += ['| | known | no_limit | unknown |', '|---|---:|---:|---:|',
              '| 정규식 (lab_conditions) | %d | %d | %d |' % (rx['known'], rx['no_limit'], rx['unknown'])]
    if has_prev:
        pv = _count(items, 'previous')
        lines.append('| LLM 이전 실행 (%s) | %d | %d | %d |' % (meta.get('previous_prompt'), pv['known'],
                                                            pv['no_limit'], pv['unknown']))
    lines += ['| LLM 이번 (%s · %s, 검사 후) | %d | %d | %d |' % (meta.get('engine') or meta.get('model') or MODEL,
                                                              meta['prompt'], llm['known'],
                                                              llm['no_limit'], llm['unknown']), '']
    if meta['prompt'] == 'v3':
        complete = sum(1 for it in done_items if (it['llm'] or {}).get('list_complete'))
        alias = sum(1 for it in done_items for a in (it['llm'] or {}).get('allowed') or []
                    if a.get('label_basis') == 'alias')
        ist = Counter((it['llm'] or {}).get('industry_status') for it in done_items)
        if any(ist):
            lines.append('매칭용 판정: ' + ' · '.join('%s %d' % (INDUSTRY_STATUS[k], ist.get(k, 0))
                                                   for k in INDUSTRY_STATUS))
        lines.append('known 중 목록 완전(list_complete) %d건 · alias 라벨 %d개 · 탈락 필터 사용 가능 0건(사람 정답 전)'
                     % (complete, alias))
    lines += ['검사에서 내린 것 %d건 · 보고 토큰 입력 %d · 출력 %d · 기록 단가 기준 약 $%.4f (청구액 아님)'
              % (meta.get('downgraded') or 0, meta.get('tokens_in') or 0, meta.get('tokens_out') or 0,
                 meta.get('cost_usd') or 0)]
    if has_prev:
        lines.append('이전 실행과 비교 등급: **%s**%s' % (
            meta.get('previous_grade'),
            ' — 이전 결과에 문서 해시가 없어 ID·문자 수·첨부 수만 대조했다' if meta.get('previous_grade') == 'limited'
            else ' — ID·문서 해시 모두 같다'))
    lines.append('')

    if meta['prompt'] == 'v3':
        lines += ['| 공고 | 제목 | 정규식 | %sLLM | 허용(원문 → 라벨) | 목록 완전 | 제외 | 근거 |' % ('이전 | ' if has_prev else ''),
                  '|---|---|---|%s---|---|---|---|---|' % ('---|' if has_prev else '')]
        for it in items:
            m = it.get('llm')
            prev = ('%s | ' % ((it.get('previous') or {}).get('status') or '-')) if has_prev else ''
            if m is None:
                lines.append('| %s | %s | %s | %s(실패) | | | | |' % (
                    it['notice_id'], _cell(it['title'], 40), (it.get('regex') or {}).get('status'), prev))
                continue
            allowed = ', '.join('%s→%s' % (a['text'], a['label'] or ('(%s?)' % a['label_suggested']
                                                                    if a['label_suggested'] else '-'))
                                for a in m['allowed'])
            lines.append('| %s | %s | %s | %s%s%s | %s | %s | %s | %s |' % (
                it['notice_id'], _cell(it['title'], 40), (it.get('regex') or {}).get('status'), prev,
                m['status'], ' (내림: %s)' % m['downgraded'] if m.get('downgraded') else '',
                _cell(allowed, 80), 'O' if m['list_complete'] else ('X' if m['status'] == 'known' else ''),
                _cell(', '.join(e['text'] for e in m['excluded']), 40), _cell(m.get('quote'))))
    else:
        lines += ['| 공고 | 제목 | 정규식 | %sLLM | 업종 | 근거 |' % ('이전 | ' if has_prev else ''),
                  '|---|---|---|%s---|---|---|' % ('---|' if has_prev else '')]
        for it in items:
            llm_r = it.get('llm') or {}
            inds = ', '.join((llm_r.get('industries') or []) + (llm_r.get('other_industries') or []))
            excl = llm_r.get('excluded_industries') or []
            if excl:
                inds += (' / 제외: ' + ', '.join(excl))
            if llm_r.get('dropped_industries'):
                inds += (' / 뺌: ' + ', '.join(llm_r['dropped_industries']))
            prev = ('%s | ' % ((it.get('previous') or {}).get('status') or '-')) if has_prev else ''
            lines.append('| %s | %s | %s | %s%s%s | %s | %s |' % (
                it['notice_id'], _cell(it['title'], 40), (it.get('regex') or {}).get('status'), prev,
                llm_r.get('status'), ' (내림: %s)' % llm_r['downgraded'] if llm_r.get('downgraded') else '',
                _cell(inds, 200), _cell(llm_r.get('quote'))))
    with io.open(os.path.join(outdir, 'summary.md'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    return lines


# ─────────────────────────────────────────────────────────── 실행

def check_prompt_args(prompt, allow_legacy):
    """v1·v2 는 오독이 확인된 판이라 명시적으로 허용했을 때만 돈다."""
    if prompt in LEGACY_PROMPTS and not allow_legacy:
        raise SystemExit('%s 는 오독이 확인된 옛 판이다. 재현이 목적이면 --allow-legacy 를 함께 준다. '
                         '새 실행은 --prompt v3 를 쓴다.' % prompt)


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--prompt', choices=sorted(PROMPTS), required=True,
                    help='v3 = 원문 표현·값별 근거 검사 (권장) · v1·v2 = 옛 판(재현용, --allow-legacy 필요)')
    ap.add_argument('--allow-legacy', action='store_true', help='v1·v2 재실행을 명시적으로 허용한다')
    ap.add_argument('--plan', action='store_true', help='문서만 만들고 예상 비용을 보여준다. 호출하지 않는다')
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--previous', help='비교할 이전 실행 폴더 (results.jsonl 이 있는 곳)')
    ap.add_argument('--resume', help='중간에 멈춘 실행 폴더. 체크포인트에 있는 공고는 다시 부르지 않는다. '
                                     '그 폴더의 이전 실행 비교 정보도 그대로 이어받는다')
    ap.add_argument('--out', help='새 실행의 결과 폴더 (기본: reports/industry_llm_sample_<시각>)')
    ap.add_argument('--model', choices=sorted(PRICES), default=MODEL,
                    help='호출할 모델 (기본 %s). 단가는 PRICES 에 적힌 값으로 비용을 추정한다' % MODEL)
    ap.add_argument('--reasoning-effort', dest='reasoning_effort', choices=REASONING_EFFORTS,
                    help='추론 모델(gpt-5.*)의 생각 강도. 주지 않으면 모델 기본값(보통 medium)')
    ap.add_argument('--all', dest='take_all', action='store_true',
                    help='표본 30건 대신 실험 DB 공고 전부를 부른다. 결과는 파일에만 남긴다(DB 쓰기 없음)')
    ap.add_argument('--reverify', help='이 결과 폴더의 저장된 원답에 검사만 다시 적용한다(LLM 호출 없음). --out 필수')
    ap.add_argument('--profile', choices=PROFILES, default='strict', help='검사 강도(실행·--reverify 모두)')
    ap.add_argument('--ids-file', dest='ids_file',
                    help='이 파일(한 줄에 공고 ID 하나)의 공고만 부른다. --all·표본 대신')
    ap.add_argument('--max-chars', dest='max_chars', type=int, default=ec.MAX_CHARS,
                    help='LLM 에 보낼 발췌 상한(기본 %d자). 잘린 공고를 길게 다시 읽을 때 늘린다' % ec.MAX_CHARS)
    ap.add_argument('--merge-base', dest='merge_base', help='결과 합치기: 기준 결과 폴더')
    ap.add_argument('--merge-override', dest='merge_override', help='결과 합치기: 이 폴더의 공고로 기준을 덮는다')
    ap.add_argument('--counterpart', help='--reverify 결과 화면에서 비교할 다른 결과 폴더 이름')
    return ap


def main_reverify(args):
    if not args.out:
        raise SystemExit('--reverify 에는 --out 이 필요하다')
    if args.prompt != 'v3':
        raise SystemExit('재검사는 --prompt v3 결과만 된다')
    source = read_json(os.path.join(args.reverify, 'meta.json'))
    from shared import store_mysql
    lab = config.connect()
    src = store_mysql.connect()
    try:
        ids = source.get('notice_ids') or pick_sample(lab, bool(source.get('take_all')))[0]
        items = load_items(lab, src, ids, source.get('max_chars') or ec.MAX_CHARS)
    finally:
        lab.close()
        src.close()
    meta, lines = reverify(args.reverify, items, args.profile, args.out, args.counterpart)
    print('\n'.join(lines[:14]))
    print('재검사(%s) → %s · LLM 호출 0' % (args.profile, args.out))
    return 0


def resume_settings(args):
    """재개 폴더 meta 를 읽어 이어받을 설정을 정한다(후속 리뷰 F2).

    · 프롬프트·프롬프트 해시·스키마 해시가 다르면 거부한다
    · 이전 실행 비교(previous)는 meta 값을 이어받는다. CLI 로 다른 previous 를 주면 거부한다
    """
    meta_path = os.path.join(args.resume, 'meta.json')
    if not os.path.exists(meta_path):
        raise SystemExit('재개 폴더에 meta.json 이 없다: %s' % args.resume)
    meta = read_json(meta_path)
    if meta.get('prompt') != args.prompt:
        raise SystemExit('재개 폴더의 프롬프트(%s)와 지금 프롬프트(%s)가 다르다' % (meta.get('prompt'), args.prompt))
    if int(meta.get('max_chars') or ec.MAX_CHARS) != int(getattr(args, 'max_chars', None) or ec.MAX_CHARS):
        raise SystemExit('재개 폴더의 발췌 상한(%s)과 지금 --max-chars 가 다르다' % meta.get('max_chars'))
    if bool(meta.get('take_all')) != bool(getattr(args, 'take_all', False)):
        raise SystemExit('재개 폴더는 %s 실행이었다. --all 여부를 맞춘다' % ('전량' if meta.get('take_all') else '표본'))
    for key, now in (('prompt_sha256', prompt_sha256(args.prompt)), ('schema_sha256', schema_sha256(args.prompt))):
        if meta.get(key) and meta[key] != now:
            raise SystemExit('재개 폴더의 %s 가 지금 코드와 다르다 — 새 실행으로 돌린다' % key)
    saved_engine = meta.get('engine') or meta.get('model')
    now_engine = engine_id(args.model, args.reasoning_effort)
    if saved_engine and saved_engine != now_engine:
        raise SystemExit('재개 폴더의 모델(%s)과 지금 모델(%s)이 다르다' % (saved_engine, now_engine))
    saved_prev = meta.get('previous')
    if args.previous and saved_prev and os.path.normpath(args.previous) != os.path.normpath(saved_prev):
        raise SystemExit('재개 폴더는 이전 실행 %s 과 비교 중이었다. 다른 --previous(%s)는 줄 수 없다'
                         % (saved_prev, args.previous))
    if args.previous and not saved_prev:
        raise SystemExit('재개 폴더는 이전 실행 비교 없이 시작했다. --previous 를 빼고 재개한다')
    return meta, saved_prev


def run_experiment(args, items, ids, population, make_call):
    """표본 실행 본체. DB 읽기는 main() 이 하고, 테스트는 가짜 items·make_call 을 넣는다.

    make_call() 은 호출 함수(item → (data, usage))를 돌려준다. --plan 이면 부르지 않는다.
    """
    saved_meta = {}
    previous_path = args.previous
    if args.resume:
        saved_meta, saved_prev = resume_settings(args)
        previous_path = saved_prev
        outdir = args.resume
        started = datetime.fromisoformat(saved_meta['run_at'])
    else:
        started = datetime.now(timezone.utc)
        outdir = args.out or os.path.join(REPORTS, 'industry_llm_sample_' + started.strftime('%Y%m%dT%H%M%SZ'))

    previous_prompt = previous_grade = None
    if previous_path:
        previous, previous_prompt, previous_grade = load_previous(previous_path, items)
        if saved_meta.get('previous_grade') and saved_meta['previous_grade'] != previous_grade:
            raise SystemExit('재개 중 이전 실행 비교 등급이 바뀌었다(%s → %s)'
                             % (saved_meta['previous_grade'], previous_grade))
        for it in items:
            it['previous'] = previous[it['notice_id']]

    model, effort = args.model, args.reasoning_effort
    request_options(model, effort)            # 추론 모델이 아닌데 effort 를 주면 여기서 멈춘다
    engine = engine_id(model, effort)
    price_in, price_out = PRICES[model]
    done = load_checkpoint(outdir) if args.resume else {}
    todo = [it for it in items if resume_key(it['notice_id'], it['document_sha256'], args.prompt, engine) not in done]
    system_tokens = estimate_tokens(system_message(args.prompt))
    est_in = sum(estimate_tokens(it['document']) + estimate_tokens(it['title'] or '') + system_tokens for it in todo)
    est_reasoning = (REASONING_TOKENS_GUESS[effort] if is_reasoning(model) else 0) * len(todo)
    est_out = 250 * len(todo) + est_reasoning
    est_cost = est_in / 1e6 * price_in + est_out / 1e6 * price_out
    with_att = sum(1 for it in items if it['attachments'])
    print('%s %d건 (모집단 %d건) · 첨부 본문 있는 공고 %d건 · 모델 %s · 프롬프트 %s'
          % ('전량' if getattr(args, 'take_all', False)
             else ('ID 파일 %s' % os.path.basename(args.ids_file)) if getattr(args, 'ids_file', None)
             else '표본(seed %d)' % SEED,
             len(items), population, with_att, engine, args.prompt))
    if args.resume:
        print('재개: 체크포인트 %d건 재사용 · 새로 부를 것 %d건' % (len(items) - len(todo), len(todo)))
    print('예상 입력 약 %d 토큰 · 출력 약 %d 토큰(추론 가정 %d 포함) · 단가 $%.2f/$%.2f · 약 $%.4f (추정)'
          % (est_in, est_out, est_reasoning, price_in, price_out, est_cost))
    if previous_path:
        print('이전 실행 비교: %s · 등급 %s' % (previous_path, previous_grade))
    if args.plan:
        return 0

    if not args.resume and any(os.path.exists(os.path.join(outdir, n))
                               for n in ('meta.json', 'checkpoint.jsonl', 'results.jsonl')):
        raise SystemExit('출력 폴더에 이미 결과가 있다: %s — 이어 하려면 --resume, 새로 하려면 다른 --out' % outdir)
    call = make_call()
    os.makedirs(outdir, exist_ok=True)
    base_meta = {'run_at': started.isoformat(timespec='seconds'), 'model': model, 'reasoning_effort': effort,
                 'engine': engine, 'seed': None if getattr(args, 'take_all', False) else SEED,
                 'take_all': bool(getattr(args, 'take_all', False)),
                 'max_chars': getattr(args, 'max_chars', None) or ec.MAX_CHARS,
                 'ids_file': getattr(args, 'ids_file', None), 'profile': getattr(args, 'profile', 'strict'),
                 'prompt': args.prompt, 'prompt_sha256': prompt_sha256(args.prompt),
                 'schema_sha256': schema_sha256(args.prompt),
                 'previous': previous_path, 'previous_prompt': previous_prompt, 'previous_grade': previous_grade}
    if not args.resume:          # 실패해도 재개할 수 있게 호출 전에 남긴다
        with io.open(os.path.join(outdir, 'meta.json'), 'w', encoding='utf-8', newline='\n') as f:
            json.dump(base_meta, f, ensure_ascii=False, indent=1)

    done, failures, called = run_calls(items, args.prompt, outdir, call, args.workers, engine,
                                       reuse=bool(args.resume))
    tokens_in = tokens_out = tokens_reasoning = 0
    models = set()
    for it in items:
        row = done.get(resume_key(it['notice_id'], it['document_sha256'], args.prompt, engine))
        it['doc_chars'] = len(it['document'])
        it['attachments_count'] = len(it['attachments'])
        if row is None:
            it['llm'] = None
            continue
        it['llm'] = verify_for(args.prompt, row['data'], it['document'], args.profile, args.max_chars,
                               it.get('title') or '')
        it['usage'] = row['usage']
        tokens_in += row['usage']['in']
        tokens_out += row['usage']['out']
        tokens_reasoning += row['usage'].get('reasoning') or 0
        if row['usage'].get('model'):
            models.add(row['usage']['model'])
    cost = tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out
    meta = dict(base_meta,
                resumed=bool(args.resume),
                resume_count=int(saved_meta.get('resume_count', 0)) + (1 if args.resume else 0),
                called_this_run=called, failures=len(failures),
                sample=len(items), population=population, vocab=VOCAB,
                regex_extractor=conditions.EXTRACTOR, code_sha256=sha256_file(CODE_PATH),
                response_models=sorted(models), requested_model=model, mixed_models=len(models) > 1,
                tokens_in=tokens_in, tokens_out=tokens_out, tokens_reasoning=tokens_reasoning,
                cost_usd=round(cost, 4),
                cost_basis='API 보고 토큰 × 기록 단가 (%s). 청구액 아님. 출력 토큰에 추론 토큰 포함' % PRICE_BASIS,
                price_per_1m={'in': price_in, 'out': price_out},
                estimated_cost_usd=round(est_cost, 4),
                downgraded=sum(1 for it in items if (it.get('llm') or {}).get('downgraded')),
                notice_ids=ids, db_writes=0)
    print('\n'.join(write_report(outdir, items, meta)))
    print('결과 → %s' % outdir)
    if failures:
        print('실패 %d건 — --prompt %s --resume %s 로 이어 한다' % (len(failures), args.prompt, outdir))
        return 3
    return 0


def read_ids(path):
    """한 줄에 공고 ID 하나. 빈 줄·# 주석은 건너뛴다. 중복은 한 번만."""
    with io.open(path, encoding='utf-8') as f:
        ids = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    return list(dict.fromkeys(ids))


def merge_runs(base, override, outdir):
    """base 결과에서 override 에 있는 공고만 override 결과로 바꾼다. **LLM 호출 없음.**

    2026-09-22 — 발췌가 6,000자에서 잘린 공고만 길게 다시 읽어(override) 전량 결과(base)에 끼워 넣는다.
    override 공고는 모두 base 에 있어야 하고, 두 결과는 같은 프롬프트여야 한다. 공고마다 어느 실행에서 왔는지 `source_run` 에 남긴다.
    """
    bmeta = read_json(os.path.join(base, 'meta.json'))
    ometa = read_json(os.path.join(override, 'meta.json'))
    # 호환 검사(Codex 후속 리뷰 F2) — 같은 프롬프트·스키마·모델·검사 강도여야 한 결과로 합친다
    for key in ('prompt', 'prompt_sha256', 'schema_sha256', 'model', 'profile'):
        if bmeta.get(key) and ometa.get(key) and bmeta.get(key) != ometa.get(key):
            raise SystemExit('%s 가 다르다: %s / %s' % (key, bmeta.get(key), ometa.get(key)))
    if bmeta.get('prompt') != ometa.get('prompt'):
        raise SystemExit('프롬프트가 다르다: %s / %s' % (bmeta.get('prompt'), ometa.get('prompt')))
    brows = read_jsonl(os.path.join(base, 'results.jsonl'))
    orows = {r['notice_id']: r for r in read_jsonl(os.path.join(override, 'results.jsonl'))}
    base_ids = {r['notice_id'] for r in brows}
    stray = [i for i in orows if i not in base_ids]
    if stray:
        raise SystemExit('덮을 결과에 기준에 없는 공고가 있다: %s' % stray[:5])
    if any(os.path.exists(os.path.join(outdir, n)) for n in ('meta.json', 'results.jsonl')):
        raise SystemExit('출력 폴더에 이미 결과가 있다: %s' % outdir)
    os.makedirs(outdir, exist_ok=True)
    bname, oname = os.path.basename(os.path.normpath(base)), os.path.basename(os.path.normpath(override))
    items = []
    for r in brows:
        row = dict(orows.get(r['notice_id']) or r)
        # 기준 행이 이미 앞선 합치기에서 온 것이면 그 출처를 지킨다(여러 번 합쳐도 어느 실행의 답인지 남는다)
        row['source_run'] = oname if r['notice_id'] in orows else (r.get('source_run') or bname)
        items.append(row)
    this_merge = {'base': bname, 'override': oname, 'override_count': len(orows),
                  'override_max_chars': ometa.get('max_chars'), 'override_profile': ometa.get('profile')}
    history = list(bmeta.get('merge_history') or ([bmeta['merged_from']] if bmeta.get('merged_from') else []))
    history.append(this_merge)
    base_cost = bmeta.get('source_cost_usd') if bmeta.get('reverified_from') else bmeta.get('cost_usd')
    over_cost = ometa.get('source_cost_usd') if ometa.get('reverified_from') else ometa.get('cost_usd')
    models = sorted(set(bmeta.get('response_models') or []) | set(ometa.get('response_models') or []))
    meta = dict({k: bmeta.get(k) for k in ('model', 'reasoning_effort', 'engine', 'take_all', 'prompt', 'prompt_sha256',
                                          'schema_sha256', 'population', 'notice_ids', 'vocab', 'regex_extractor',
                                          'profile', 'counterpart')},
                run_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                merged_from=this_merge, merge_history=history,
                reverified_from=bname, called_this_run=0, failures=0, sample=len(items),
                # 토큰·비용 모두 두 실행의 원답 합계다(기준 원답 + 다시 읽은 공고)
                tokens_in=(bmeta.get('tokens_in') or 0) + (ometa.get('tokens_in') or 0),
                tokens_out=(bmeta.get('tokens_out') or 0) + (ometa.get('tokens_out') or 0),
                cost_usd=0.0, source_cost_usd=round((base_cost or 0) + (over_cost or 0), 4),
                cost_basis='합치기 — LLM 호출 없음. 토큰·source_cost_usd = 기준 원답 + 다시 읽은 공고(토큰 × 기록 단가)',
                code_sha256=sha256_file(CODE_PATH), response_models=models, mixed_models=len(models) > 1,
                downgraded=sum(1 for it in items if (it.get('llm') or {}).get('downgraded')), db_writes=0)
    lines = write_report(outdir, items, meta)
    return meta, lines


def reverify(source, items, profile, outdir, counterpart=None):
    """저장된 LLM 원답(checkpoint)에 검사만 다시 적용한다. **LLM 을 부르지 않는다**(비용 0).

    items 는 main() 이 DB 에서 다시 만든 문서다. 원답을 받을 때의 document_sha256 과 하나라도 다르면 멈춘다
    (같은 문서가 아니면 같은 원답을 다시 검사할 수 없다). counterpart 는 비교할 다른 강도의 결과 폴더 이름(화면용).
    """
    meta = read_json(os.path.join(source, 'meta.json'))
    if meta.get('prompt') != 'v3':
        raise SystemExit('재검사는 v3 결과만 된다(지금 %s)' % meta.get('prompt'))
    rows = {}
    for row in load_checkpoint(source).values():
        rows[row['notice_id']] = row
    missing = [it['notice_id'] for it in items if it['notice_id'] not in rows]
    changed = [it['notice_id'] for it in items if it['notice_id'] in rows
               and rows[it['notice_id']].get('document_sha256') != it['document_sha256']]
    if missing or changed:
        raise SystemExit('원답과 문서가 맞지 않는다 — 원답 없음 %d · 문서 바뀜 %d (예: %s)'
                         % (len(missing), len(changed), (missing + changed)[:3]))
    if any(os.path.exists(os.path.join(outdir, n)) for n in ('meta.json', 'results.jsonl')):
        raise SystemExit('출력 폴더에 이미 결과가 있다: %s' % outdir)
    os.makedirs(outdir, exist_ok=True)
    tokens_in = tokens_out = 0
    for it in items:
        row = rows[it['notice_id']]
        it['llm'] = verify_v3(row['data'], it['document'], profile, meta.get('max_chars') or ec.MAX_CHARS,
                              it.get('title') or '')
        it['usage'] = row['usage']
        it['doc_chars'] = len(it['document'])
        it['attachments_count'] = len(it['attachments'])
        tokens_in += row['usage']['in']
        tokens_out += row['usage']['out']
    new_meta = dict({k: meta.get(k) for k in ('model', 'reasoning_effort', 'engine', 'seed', 'take_all', 'prompt', 'max_chars',
                                              'prompt_sha256', 'schema_sha256', 'response_models', 'population',
                                              'notice_ids', 'vocab', 'regex_extractor')},
                    run_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                    profile=profile, reverified_from=os.path.basename(os.path.normpath(source)),
                    counterpart=counterpart, source_run_at=meta.get('run_at'),
                    called_this_run=0, failures=0, sample=len(items), tokens_in=tokens_in, tokens_out=tokens_out,
                    cost_usd=0.0, source_cost_usd=meta.get('cost_usd'),
                    cost_basis='재검사 — LLM 호출 없음. 원답을 받을 때의 비용은 source_cost_usd',
                    code_sha256=sha256_file(CODE_PATH), mixed_models=False,
                    downgraded=sum(1 for it in items if (it.get('llm') or {}).get('downgraded')), db_writes=0)
    lines = write_report(outdir, items, new_meta)
    return new_meta, lines


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.reverify:
        return main_reverify(args)
    if args.merge_base or args.merge_override:
        if not (args.merge_base and args.merge_override and args.out):
            raise SystemExit('합치기에는 --merge-base·--merge-override·--out 이 모두 필요하다')
        meta, lines = merge_runs(args.merge_base, args.merge_override, args.out)
        print('\n'.join(lines[:14]))
        print('합침 → %s · LLM 호출 0' % args.out)
        return 0
    check_prompt_args(args.prompt, args.allow_legacy)
    if args.ids_file and args.take_all:
        raise SystemExit('--ids-file 과 --all 은 함께 쓰지 않는다')
    if args.resume and args.out:
        raise SystemExit('--resume 과 --out 은 함께 쓰지 않는다')
    if args.take_all and args.previous:
        raise SystemExit('--all 은 --previous 와 함께 쓰지 않는다(이전 실행은 30건 표본이다)')

    from shared import store_mysql
    lab = config.connect()
    source = store_mysql.connect()
    try:
        ids, population = pick_sample(lab, args.take_all)
        if args.ids_file:
            ids = read_ids(args.ids_file)
            known_ids = set(pick_sample(lab, True)[0])
            unknown_ids = [i for i in ids if i not in known_ids]
            if unknown_ids:
                raise SystemExit('실험 DB 에 없는 공고 ID: %s' % unknown_ids[:5])
        items = load_items(lab, source, ids, args.max_chars)
    finally:
        lab.close()
        source.close()

    def make_call():
        key = pipeline_config.get('OPENAI_API_KEY')
        if not key:
            raise SystemExit('OPENAI_API_KEY 가 없다')
        import openai
        client = openai.OpenAI(api_key=key)
        return lambda it: ask(client, it, args.prompt, args.model, args.reasoning_effort)

    return run_experiment(args, items, ids, population, make_call)


if __name__ == '__main__':
    sys.exit(main())


