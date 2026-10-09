# -*- coding: utf-8 -*-
"""신청자별 가산점 — 공고 가점(notice_bonus, collect/extract_bonus.py)을 신청자 정보와 맞춘다 (2026-10-06, 03_bonus 3-3).

bonus_score 의 뜻(2026-10-07 사용자 결정, Codex 재검수 B-P2-2) — **확인된 가산점 부분합**
  신청자 입력으로 해당 여부와 배점을 확인한 묶음만 더한 값이다. 받을 수 있는 전체 합계가 아니다(미확인 묶음은 더하지 않는다).
  해당 가점이 하나도 없음이 확인되면 0, 확인된 것이 없으면 null.
bonus_items  항목별 근거 [{'name', 'points'}] — points 는 **원문 배점**이고 합이 bonus_score 와 같다. 계산하지 못하면 [].

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

확실한 것만 남기기(2026-10-07 사용자 결정) — AI 를 다시 부르지 않고 계산만 줄인다. 틀린 양수를 내느니 null 이다.
  해당 → 모름   추가 조건(extra_conditions)이 있다(단 뜻이 안 바뀌는 조건은 예외 — 아래) · 앞으로의 조건(FUTURE_WORDS: 이전·유치·예정 …) ·
               신청자 입력으로 확인할 수 없는 조건 말(CONDITION_WORDS: 모두·이내·최근·이상·한함 … — 청년의 "만 N세 이하"는 뺀다,
               Codex 재검수 B-P2-1). '해당 아님'은 그대로 둔다
  예외(2026-10-08 사용자 결정, 결정 0014) — 뜻이 안 바뀌는 추가 조건은 모름으로 내리지 않는다:
               증빙 서류 요구(BENIGN_PAPER: 인증서 첨부·확인서 제출 …) · 유효기간(BENIGN_VALID: 유효기간 내 …) · '중소기업' 단독.
               추가 조건을 ';'·'/'로 나눈 조각이 모두 이 예외여야 하고, 조각에 위험 말(RISKY_WORDS: 최근·협약·법인의 경우·추천 …)이
               섞이면 예외가 아니다. 조건 말 검사도 위험 말이 없는 증빙·유효기간 구절은 빼고 한다("유효기간 내 인증서에 한함")
  항목 → 모름   근거 문장이 지금 공고 원문에 공백만 다르고 그대로 이어져 있지 않다(in_document=False — AI 가 조각을 이어 붙임, B-P1-1).
               load() 가 found 행마다 확인해 둔다. 원문을 읽지 못했으면 found 공고는 null(document_check='failed')
  점수 인정     근거 문장에 그 점수가 "N점"으로 직접 있고, 근거 문장에 서로 다른 "N점"이 둘 이상이 아니다(B-P1-1).
               떨어진 배점 칸(points_source)·숫자만 있는 경우(연번)도 점수 없음
  묶음         같은 group 이름일 때만 한 묶음 — 해당 항목 중 가장 큰 점수(같으면 이름순)를 한 번만 센다.
               이름·근거가 같은 중복 추출만 하나로 친다. 묶음 판단이 원문과 어긋날 수 있으면 그 범위 null(B-P1-2):
               점수로 고른 항목 중 group 은 다른데 근거 문장·점수가 같다 / 한 group 에 항목이 둘 이상인데 근거에 "각"이 있다
  불확실       found 인데 불확실 메모(uncertain)가 하나라도 있으면 null(B-P1-3). none 인데 메모가 있어도 null
  합계 한도     해당 점수 합이 한도(max_total_points)를 넘으면 null(전체 한도인지 확인할 수 없어 자르지 않는다)
  세부사업      세부사업(program)마다 따로 계산해 결과가 모두 같을 때만 쓴다. 0 이면 0, 양수는 공통 항목만으로 같은 점수일 때
               꼬리표 없이 낸다. 그 밖(결과가 다르거나, 모두 같아도 세부사업 항목이 섞여야 그 점수)은 null

공고 단위
  행 없음(첨부를 못 읽은 공고 — K-Startup 등) · unverified(근거 확인 실패) → null
  none · no_mention(가점 없음·가점 말 없음) → 0
  found → 점수 있는 해당 묶음이 있으면 그 합, 모든 묶음이 '해당 아님'이면 0, 그 밖 null

Codex 재재검수(2026-10-08 CODEX_BONUS_RECHECK2_20261007.md) 처리 — 결정 0016. 더 엄격하게만(양수 → null·더 작은 양수):
  ① 결합 조건   근거에 "둘 다"로도 읽히는 잇는 말(AND_WORDS: 및·&·+·그리고)이 있고, 같은 근거에서 뽑힌 짝 항목 중
               확인할 수 없는(None) 것이 있으면 모름. 짝이 '해당 아님'(False)이 확실하면 "둘 중 하나"로 보고 점수(사용자 결정).
               '&'·'+'인데 짝이 따로 뽑히지 않았어도 모름. 또는·쉼표·"… 등" 나열은 건드리지 않는다
  ② 표 밖 기간   공고 원문 한 줄에 증빙 말 + 기간 말 + 가점·인정이 함께 있으면(PERIOD_LINE, "모든 인증서는 최근 2년간 … 인정")
               그 공고의 인증으로 받는 항목(인증·여성·장애인)은 모름. load() 가 원문 줄을 보고 표시해 둔다
  ③ 서류 예외   결정 0014 예외는 같은 인증의 증빙일 때만 — 증빙·유효기간 말과 그 항목 자신의 인증 이름, 뜻 없는 말(FILLER_WORDS)을
               빼고 남는 말이 없어야 한다("벤처기업 인증서 및 대통령 표창장 제출"은 모름)
  ④ 점수 주인   근거를 문장·항목 경계로 나눴을 때 그 "N점"이 있는 조각에 그 항목의 대상 말(이름·인증 줄임말·종류·지역)이 있어야 인정
  ⑤ 택1        공고 원문에 고르기·합산 금지 말(SELECT_WORDS)이 있고 신청자에게 점수가 두 묶음 이상에서 나오면 그 범위 null
  ⑥ 나이 구절   "만 N세 이하"를 조건 말 검사에서 빼는 것은 청년 항목에서만
  Codex 3차(2026-10-08 결정 0017): ③ 예외가 빼는 대상 말은 인증 코드·별칭·종류 말만(AI 가 지은 이름 낱말은 빼지 않음) ·
               ① "및"인데 짝 항목이 뽑히지 않았으면 모름 · ④ 원문 줄 경계(quote_lines)로도 나눔 · ② 각주(※·*) 줄은 이어진 줄과 합쳐 봄
  Codex 4차(2026-10-08 결정 0018): 배점 없는 "*" 줄은 앞줄에 자격 이름이 없을 때만 붙인다 · 원문 지문(evidence_fingerprint)으로
               첨부 글이 바뀐 것을 알아챈다 · 원문 대조 목록 값을 꼼꼼히 검사한다
  표 배점 칸(2026-10-08 결정 0019, 처음 푸는 변경 — 모름 → 양수만): 근거에 "N점"이 없어도 원문 근거 앞 1,500자 안에 표 머리
               "배점"이 있고(score_header) 근거에 단위 없는 숫자가 하나뿐이면 그 숫자를 점수로 본다(_table_cell). 점수 주인은
               숫자 줄 앞에서 행 이름을 찾아 대상 말이 있고 자격 이름이 모두 같은 근거의 짝 자격(table_mates)일 때만 인정한다
               (points_owned — 행 이름·짝은 0020 K1로 좁힘)
  완화·조이기(2026-10-08 결정 0020): R1 부분 메모는 가리키는 항목만 모름(memo_is_global) · R2 자격만 말하는 "…인 경우"는
               조건 말이 아님(condition_words_hit) · R3 같은 숫자 반복·"아니오(0)"·"예(N)"(bare_numbers) · R4 한 문장 속 여러
               "N점"은 쉼표 조각의 주인(points_supported) · R5 다른 묶음의 "각 N점"은 더함(_score_scope) · K1 짝은 cert_words,
               행 이름은 숫자 줄 바로 앞 줄 + 잇는 말(quote_mates·points_owned·qualification_words) · K2 "배점"은 같은 표만(score_header)
  공통         새 규칙을 빼고 계산한 결과(이전 계산)가 null 이면 null 을 유지하고, 이전보다 커지지 않는다 — 항목이 빠져
               한도 초과·중복 검사가 풀리는 길(null → 양수)을 막는다

최신성(2026-10-06 Codex 검수 P2-4): 가점 행은 뽑을 때의 공고 내용 지문(content_version)과 추출기 버전을 함께 저장한다.
load() 에 지금 지문·버전을 넘기면 다른 행(공고문이 바뀌었는데 아직 다시 뽑지 않음)은 버린다 → 그 공고는 null(모름).
"이전" 오탐("이전 공고와 동일하게")처럼 판단 단어가 넓게 걸려 null 이 늘어나는 것은 받아들인다(과잉 null 은 틀린 점수가 아니다).
"""
import os
import re

from search import applicant as applicant_mod
from shared import region as region_mod

KNOWN_CERTS = set(applicant_mod.CERTIFICATIONS)
_AGE_LIMIT = re.compile(r'만\s*(\d{2})\s*세\s*(이하|미만)')
# 확실한 것만 남기기(2026-10-07) — 조정 가능한 판단 단어
FUTURE_WORDS = re.compile(r'이전|이주|유치|예정|희망|신규\s*채용|신규\s*고용')
# 신청자 입력으로 확인할 수 없는 조건 말(Codex 재검수 B-P2-1, 조정 가능). 청년 나이 구절("만 39세 이하")은 빼고 본다
CONDITION_WORDS = re.compile(r'모두|이내|최근|이상|이하|미만|초과|기준|한함|한정|경우|단서|회당|(?<![가-힣])단\s*[,:]')
# 뜻이 안 바뀌는 추가 조건(2026-10-08 결정 0014, 조정 가능) — 신청자가 그 인증을 가졌다고 고르면 당연히 따라오는 조건
BENIGN_PAPER = r'첨부|제출|확인서|확인증|인증서|증명서|등록증|지정서|원본|사본|서류|증빙|발급'
BENIGN_VALID = r'유효\s*(?:기간|기한)?|만료\s*업체\s*제외|경과하지\s*않은|인증\s*기간\s*내|지정이\s*유효'
_BENIGN = re.compile('(?:%s|%s)' % (BENIGN_PAPER, BENIGN_VALID))
# 이런 말이 섞이면 증빙·유효기간 말이 있어도 뜻이 바뀌는 조건이다(조정 가능)
RISKY_WORDS = re.compile(r'최근|평균\s*점수|협약|잔류|법인의\s*경우|개인사업자|추천|업종|기업체|소공인|부품|수출\s*실적|내수|이전|입주|'
                         r'기초만|매출|종사자|근로자|비율|중복|신규|소재|거주|고용|채용|선정년도|\d+\s*년\s*(?:간|이내)')
_SME_ONLY = re.compile(r'^\s*중소\s*기업\s*$')
_BENIGN_PHRASE = re.compile(r'[^,.;()\[\]]*?(?:%s|%s)[^,.;()\[\]]*' % (BENIGN_PAPER, BENIGN_VALID))
# Codex 재재검수 처리(2026-10-08 결정 0016, 조정 가능)
AND_WORDS = re.compile(r'및|&|＋|\+|그리고')
_BOTH_MARKS = re.compile(r'&|＋|\+')
PERIOD_LINE = (re.compile(r'인증서|확인서|증빙|증명서|인증'),
               re.compile(r'최근|\d{4}\s*년?\s*[~∼\-]\s*\d{2,4}|이내|\d+\s*년\s*간|\d+\s*개\s*년|발급\s*일'),
               re.compile(r'가점|인정'))
SELECT_WORDS = re.compile(r'택\s*1|택일|1\s*개\s*(?:항목\s*)?만|하나만|중복\s*수혜\s*불가|높은\s*점수\s*1\s*개|합산\s*하지|합산\s*불가|합산되지|중복\s*(?:불가|인정\s*(?:하지|안|불가|되지)|'
                          r'적용\s*(?:불가|안|하지|되지)|제외)|중\s*1\s*개|최고\s*점수\s*1')
FILLER_WORDS = {'해당', '관련', '필수', '시', '기업', '보유', '원본', '사본', '제출', '첨부', '내', '기준', '접수', '마감일', '마감',
                '신청일', '신청', '경우', '한함', '한하여', '한해', '남아있는', '남아', '있는', '있을', '유효한', '유효', '해야', '하여야',
                '함', '한', '등', '및', '또는', '확인', '대표자', '대표', '기간', '것', '자', '서류', '증빙', '사항', '이', '여부', '반드시', '인증', '가점', '점', '우대'}
_PARTICLES = re.compile(r'(?:에서|으로|까지|부터|이며|이고|이|가|을|를|에|의|은|는|로|와|과|도|만)$')
_SEGMENT = re.compile(r'\.(?=\s|$)|[。\n◾❍▪•ㅇ①-⑳◯]|\s-\s')
CERT_ALIASES = {'벤처기업': ('벤처',), '이노비즈': ('이노비즈', '기술혁신형'), '메인비즈': ('메인비즈', '경영혁신형'),
                '여성기업': ('여성',), '장애인기업': ('장애인',), '사회적기업': ('사회적',), '예비사회적기업': ('예비사회적', '사회적'),
                '협동조합': ('협동조합',), '소셜벤처': ('소셜',), '연구소기업': ('연구소',), '기업부설연구소': ('연구소', '부설'),
                '수출기업': ('수출',), '가족친화기업': ('가족친화',), '청년친화강소기업': ('청년친화', '강소')}
KIND_WORDS = {'여성': ('여성',), '장애인': ('장애인',), '청년': ('청년', '세이하', '세미만'), '재창업': ('재창업', '재도전', '재기')}
_GENERIC = {'기업', '인증', '가점', '우대', '지정', '선정', '보유', '확인', '대상', '경우', '사업'}
# 자격 이름 — "*" 설명 줄을 앞줄에 붙일지 정할 때(결정 0018). '세이하·세미만' 같은 나이 구절 조각은 이름이 아니라 뺀다
_QUALIFICATION_WORDS = ({c for c in CERT_ALIASES} | {a for v in CERT_ALIASES.values() for a in v}
                        | {w for k, v in KIND_WORDS.items() for w in v if not w.startswith('세')})
_EACH = re.compile(r'(?<![가-힣])각(?:각)?(?![가-힣])')        # "각 1점" — 독립 가점을 한 묶음으로 묶었을 수 있다
_POINTS = re.compile(r'(?<![\d.])(\d+(?:\.\d+)?)\s*점')
# 표 배점 칸(결정 0019) — 근거에 "N점"이 없어도, 원문에서 근거 바로 앞에 표 머리("배점")가 있고 근거에 단위 없는 숫자가
# 하나뿐이면 그 숫자를 점수로 본다. 머리 말·거리는 조정 가능한 값
SCORE_HEADER_WORDS = ('배점',)
SCORE_HEADER_WINDOW = 1500            # 근거 시작 앞 원문 글자 수(공백·줄바꿈 포함)
# 단위: 붙어 있으면("3년간") 늘 단위, 띄어 있으면("3 년") 단위 글자 뒤에 한글이 이어지지 않을 때만 — 근거는 원문 줄바꿈이
# 띄어쓰기로 이어진 글이라 "10⏎일자리"(배점 칸 다음 칸)가 "10 일자리"가 된다
_UNITS = r'(?:점|%|년|개|인|명|억|만|원|회|건|호|조|월|일)'
_BARE_NUMBER = re.compile(r'(?<![\d.])(\d+(?:\.\d+)?)(?![\d.]|%s|\s+%s(?![가-힣]))' % (_UNITS, _UNITS))
# 결정 0020 — 계산 완화(R1~R5)와 Codex 6차 조이기(K1·K2). 단어 목록은 조정 가능
# R1 메모 범위: 전체를 흔드는 말이 있거나 특정 대상을 가리키지 않는 메모는 "전체 메모"(공고 전체 null)
MEMO_GLOBAL_WORDS = re.compile(r'합산|한도|최대|총점|합계|병합|중복|택\s*1|택일|선택|전체|모든|공통|세부\s*사업|가점\s*표|배점\s*표|'
                               r'(?<![가-힣])각(?![가-힣])|묶음|그룹|group')
# 대상 표시: 따옴표 속 이름, "‹낱말› 항목"(앞 두 낱말까지). 그 안에 일반 말이 아닌 낱말이 있어야 대상이다
# ("가점 항목 일부 누락", "'우대' 조건", "⑱ 근거가 끊김"은 대상이 아니다 — 최종 점검 지적)
_MEMO_TARGET = re.compile(r'[‘\'"“「『]([^’\'"”」』]+)[’\'"”」』]|((?:[가-힣A-Za-z]+\s*){1,2})항목')
_MEMO_NUMBERED_ITEM = re.compile(r'[①-⑳](?:\s*[·ㆍ,]\s*[①-⑳])*\s*(?:번\s*)?항목')     # "⑮·⑯ 항목" — 번호로 집은 항목
_MEMO_GENERIC = {'가점', '가산점', '평가', '배점', '심사', '세부', '일부', '기타', '해당', '우대', '인증', '선정', '추가', '개별', '각',
                 '모든', '전체', '발췌', '발췌문', '원문', '문장', '점수', '부분', '내용', '표', '조건', '항목', '근거', '사항', '기준'}
# R2 "…인 경우" 구절에서 뜻 없이 지나가는 서술 말
_CLAUSE_VERBS = {'인', '받은', '받는', '해당하는', '해당되는', '보유한', '보유하는', '기관이', '기업이', '기관', '인증을', '인증받은',
                 '지정받은', '선정된', '각'}
_CLAUSE_BOUNDARY = re.compile(r'[,;()\[\]。\n◾❍▪•ㅇ①-⑳◯○◦∘]|\.(?=\s|$)|\s-\s')
# R3 "아니오(0)" 같은 해당 없음 칸의 0, K2 번호 숫자("등록번호 10")
_NO_ZERO_BEFORE = re.compile(r'(?:아니오|아니요|미해당|해당\s*없음|없음)\s*[(:]?\s*$')
_SERIAL_BEFORE = re.compile(r'(?:번호|등록|(?<![가-힣])제|No\.?)\s*$', re.I)
# K1 표 행 이름: 뜻 없는 줄은 건너뛰고, 잇는 말로 끝나는 윗줄만 같은 칸으로 본다
_LABEL_FILLER = re.compile(r'[\s○ㆍ·•∘◦\-*:()]*(?:해당|가점|우대|예|대상)?[\s:()]*')
_LABEL_JOIN = re.compile(r'(?:및|또는|,|·|ㆍ|&|/|＋|\+)\s*$')
# K2 "배점" 뒤에 조사가 붙으면 표 머리가 아니다("배점에 관한 문의")
_HEADER_PARTICLE = re.compile(r'[ \t]?(?:에서|으로|에|을|를|은|는|이|의)(?=[\s가-힣]|$)')    # 줄바꿈 너머 다음 칸 글자는 조사가 아니다


def load(connection, versions=None, extractor_version=None, stale=None, errors=None):
    """{notice_id: {'status','max_total_points','bonus_info','items','uncertain'}} — 공용 DB notice_bonus. SELECT 만 한다.

    versions({notice_id: 지금 공고 내용 지문})를 주면 지문이 다른 행을, extractor_version 을 주면 버전이 다른 행을 버린다.
    stale 에 dict 를 넘기면 버린 이유별 건수를 적는다.
    found 행은 항목마다 근거 문장이 지금 공고 원문에 그대로 이어져 있는지(item['in_document'])를 확인해 둔다(Codex 재검수 B-P1-1).
    원문을 읽지 못하면 found 행에 document_check='failed' 를 붙이고(→ 가산점 null) errors(list)에 이유를 적는다.
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
            if status == 'found':                 # 원문 확인 칸을 덧붙이기 전에, DB 원래 값으로(결정 0017)
                out[nid]['row_fingerprint'] = row_fingerprint(out[nid])
    _check_documents(connection, out, errors)
    return out


def row_fingerprint(entry):
    """가점 행 지문 — 상태·한도·항목·불확실 메모(DB 원래 값). 원문 대조를 마친 공고 목록(결정 0017)이 대조 당시 행과 같은지 본다.
    원문 확인 때 덧붙는 칸(in_document·period_condition·quote_lines·score_header·table_mates)은 넣지 않는다."""
    import hashlib
    import json
    added = ('in_document', 'period_condition', 'quote_lines', 'score_header', 'table_mates')
    items = [{k: v for k, v in it.items() if k not in added} for it in entry.get('items') or []]
    body = {'status': entry.get('status'), 'max_total_points': entry.get('max_total_points'), 'items': items,
            'uncertain': entry.get('uncertain') or []}
    return 'bf1-' + hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()[:16]


def _compact(text):
    return re.sub(r'\s+', '', str(text or ''))


def document_parts(connection, notice_ids):
    """{notice_id: [원문 조각(공백·줄바꿈 그대로)]} — 가점 추출(collect/extract_bonus.pick_targets)과 같은 범위:
    공고 본문 + 지원대상 + 지금 달린(active)·추출 성공 첨부 본문."""
    ids = sorted(notice_ids)
    if not ids:
        return {}
    marks = ','.join(['%s'] * len(ids))
    parts = {}
    with connection.cursor() as cursor:
        cursor.execute('SELECT notice_id, body, target_text FROM notices WHERE notice_id IN (%s)' % marks, tuple(ids))
        for nid, body, target in cursor.fetchall():
            parts.setdefault(nid, []).extend([body, target])
        cursor.execute('SELECT n.notice_id, at.extracted_text FROM notices n '
                       'JOIN notice_attachments na ON na.notice_fk = n.id AND na.active '
                       'JOIN attachment_texts at ON at.attachment_fk = na.id '
                       "WHERE at.last_status = 'ok' AND at.extracted_text IS NOT NULL AND n.notice_id IN (%s)" % marks,
                       tuple(ids))
        for nid, text in cursor.fetchall():
            parts.setdefault(nid, []).append(text)
    return {nid: [str(t) for t in texts if t] for nid, texts in parts.items()}


def documents(connection, notice_ids):
    """{notice_id: 공백을 뺀 원문} — document_parts 와 같은 범위. 조각 사이에 구분 글자를 넣어 경계를 넘는 일치를 막는다."""
    return {nid: '\x00'.join(_compact(t) for t in texts) for nid, texts in document_parts(connection, notice_ids).items()}


_FOOTNOTE = re.compile(r'^\s*[※*]')
_SCORE_CELL = re.compile(r'[\s()\[\]~\-·,]*(?:(?:최대|가점|각)\s*)?(?:\d+(?:\.\d+)?\s*점)?[\s()\[\]~\-·,]*(?:가점)?[\s()]*')
_NEW_ITEM = re.compile(r'^\s*(?:[※*\-•◾❍▪ㅇ□○●◯]|[①-⑳]|\d+[.)])')


def period_lines(texts):
    """원문 줄 가운데 증빙 말 + 기간 말 + 가점·인정이 함께 있는 줄(결정 0016 ②) — "모든 인증서는 최근 2년간 … 만 인정".
    한 줄로 안 되는 각주(※·*) 줄은 바로 이어진 줄(최대 2줄, 빈 줄·새 머리 기호 전까지)과 합쳐 본다(결정 0017, Codex R3-P2-1)."""
    out = []
    for text in texts:
        lines = str(text).splitlines()
        for i, line in enumerate(lines):
            if all(rx.search(line) for rx in PERIOD_LINE):
                out.append(' '.join(line.split())[:200])
                continue
            if not _FOOTNOTE.match(line):
                continue
            joined = line
            for nxt in lines[i + 1:i + 3]:
                if not nxt.strip() or _NEW_ITEM.match(nxt):
                    break
                joined += ' ' + nxt
                if all(rx.search(joined) for rx in PERIOD_LINE):
                    out.append(' '.join(joined.split())[:200])
                    break
    return out


def _has_qualification(text):
    """글에 자격 이름(인증 이름·별칭, 종류 말)이 있나 — "*" 설명 줄을 앞줄에 붙일지 정할 때만 쓴다."""
    compact = _compact(text)
    return any(w in compact for w in _QUALIFICATION_WORDS)


def evidence_fingerprint(texts):
    """원문 지문 — 계산에 쓴 원문 조각(본문·지원대상·지금 달린 추출 성공 첨부 글)을 줄바꿈 표기만 통일하고 순서를 정해
    구분 글자로 이어 만든다(결정 0018 R4-P2-3). 첨부를 읽는 순서가 달라도 같고, 첨부 글을 다시 뽑아 글자·줄이 바뀌면 다르다."""
    import hashlib
    parts = sorted(str(t).replace('\r\n', '\n').replace('\r', '\n') for t in texts if t)
    return 'ev1-' + hashlib.sha1('\x00'.join(parts).encode('utf-8')).hexdigest()[:16]


def quote_lines(texts, quote):
    """근거 문장(공백 무시)이 원문에서 걸친 구간을 원문 줄 경계로 나눈 조각들 — 두 줄 이상일 때만, 못 찾으면 None(결정 0017 ④)."""
    q = _compact(quote)
    if not q:
        return None
    for text in texts:
        text = str(text)
        chars, index = [], []
        for i, ch in enumerate(text):
            if not ch.isspace():
                chars.append(ch)
                index.append(i)
        pos = ''.join(chars).find(q)
        if pos < 0:
            continue
        span = text[index[pos]:index[pos + len(q) - 1] + 1]
        parts = []
        for ln in (x.strip() for x in span.splitlines()):
            if not ln:
                continue
            # 표의 배점 칸("1점", "최대 3점")과 배점이 없는 "*" 설명 줄은 그 행의 앞줄에 붙인다 — 다른 행의 줄과만 나눈다.
            # 배점이 든 "*" 줄("*벤처기업 가점 10점")은 붙이지 않는다(그 점수가 앞줄 항목의 것이라는 증거가 아니다)
            # 배점 없는 "*" 줄도 앞줄에 자격 이름이 없을 때만 붙인다 — 앞줄이 "혁신형 중소기업 1점"처럼 일반 이름이고
            # "*" 줄이 그 정의일 때. 앞줄이 "벤처기업 가점 10점"이면 "* 여성기업 우대 안내"를 붙이지 않는다(결정 0018 R4-P2-1)
            star_ok = ln.startswith('*') and not _POINTS.search(ln) and parts and not _has_qualification(parts[-1])
            if parts and (_SCORE_CELL.fullmatch(ln) or star_ok):
                parts[-1] += ' ' + ln
            else:
                parts.append(ln)
        return parts if len(parts) >= 2 else None
    return None


def score_header(texts, quote, window=SCORE_HEADER_WINDOW):
    """근거 문장(공백 무시)을 처음 찾은 원문 조각에서, 근거 시작 앞 window 글자 안에 표 머리 말("배점")이 있나(결정 0019 ①).
    결정 0020 K2(Codex R6-P2-2): 뒤에 조사가 붙은 "배점"("배점에 관한 문의")은 머리가 아니고, 가장 가까운 머리 줄의 끝부터
    근거 시작까지가 공백뿐이거나 숫자 든 줄(배점 칸 행)이 하나 이상 있어야 같은 표로 본다."""
    q = _compact(quote)
    if not q:
        return False
    for text in texts:
        text = str(text)
        index = [i for i, ch in enumerate(text) if not ch.isspace()]
        pos = ''.join(text[i] for i in index).find(q)
        if pos < 0:
            continue
        start = index[pos]
        lo = max(0, start - window)
        heads = [m for w in SCORE_HEADER_WORDS for m in re.finditer(re.escape(w), text[lo:start])
                 if not _HEADER_PARTICLE.match(text[lo + m.end():start])]
        if not heads:
            return False
        head_end = lo + max(m.end() for m in heads)
        line_end = text.find('\n', head_end)
        between = text[line_end:start] if 0 <= line_end < start else ''
        return not between.strip() or any(re.search(r'\d', ln) for ln in between.splitlines())
    return False


def quote_mates(items):
    """{공백 뺀 근거: 짝 자격 말(집합)} — 같은 근거에서 뽑힌 항목들(자기 포함)의 인증 코드·별칭·종류 말(cert_words).
    AI 가 지은 항목 이름 낱말은 넣지 않는다(결정 0020 K1, Codex R6-P2-1)."""
    out = {}
    for it in items:
        out.setdefault(_compact(it.get('quote')), set()).update(cert_words(it))
    return out


def table_mates(items):
    """{공백 뺀 근거: 짝 자격 말(정렬 목록)} — quote_mates 를 load() 가 항목에 덧붙이는 모양으로(결정 0019 ③·0020 K1)."""
    return {k: sorted(v) for k, v in quote_mates(items).items()}


def _check_documents(connection, table, errors=None):
    """found 행의 항목마다 in_document 를 매긴다. 원문을 읽지 못하면 그 행들은 document_check='failed'.
    원문 줄로 ② 표 밖 기간 조건(period_lines)과 ⑤ 고르기·합산 금지 말(selection)도 표시해 둔다(결정 0016)."""
    targets = [nid for nid, e in table.items() if e['status'] == 'found']
    if not targets:
        return
    try:
        parts = document_parts(connection, targets)
    except Exception as exc:                  # 모르면 점수를 확정하지 않는다
        for nid in targets:
            table[nid]['document_check'] = 'failed'
        if errors is not None:
            errors.append('가점 근거 원문 읽기 실패 — found 공고 가산점 null (%s: %s)' % (type(exc).__name__, str(exc)[:200]))
        return
    for nid in targets:
        texts = parts.get(nid, [])
        doc = '\x00'.join(_compact(t) for t in texts)
        entry = table[nid]
        entry['document_check'] = 'ok'
        entry['evidence_fingerprint'] = evidence_fingerprint(texts)
        entry['period_lines'] = period_lines(texts)
        entry['selection'] = any(SELECT_WORDS.search(t) for t in texts)
        mates = table_mates(entry['items'])
        for it in entry['items']:
            quote = _compact(it.get('quote'))
            it['score_header'] = score_header(texts, it.get('quote'))      # 결정 0019 표 배점 칸
            it['table_mates'] = mates.get(quote, [])
            it['in_document'] = bool(quote) and quote in doc
            if entry['period_lines']:
                it['period_condition'] = True
            if it['in_document']:
                lines = quote_lines(texts, it.get('quote'))
                if lines:
                    it['quote_lines'] = lines


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


def benign_extra(extra):
    """추가 조건이 뜻을 바꾸지 않는가 — ';'·'/'로 나눈 조각이 모두 증빙 서류·유효기간(위험 말 없음)이거나 '중소기업' 단독(결정 0014)."""
    for part in re.split(r'[;/]', str(extra or '')):
        part = part.strip()
        if not part or _SME_ONLY.match(part):
            continue
        if not _BENIGN.search(part) or RISKY_WORDS.search(part):
            return False
    return True


def _drop_benign_phrases(text, item=None):
    """조건 말 검사 전에 증빙·유효기간 구절을 뺀다. 위험 말이 든 구절("최근 3년 이내 … 확인서 제출")은 남긴다.
    item 을 주면(결정 0016 ③) 그 항목 자신의 인증 증빙인 구절만 뺀다."""
    def keep(m):
        phrase = m.group(0)
        if RISKY_WORDS.search(phrase) or (item is not None and not same_cert_paper(phrase, item)):
            return phrase
        return ' '
    return _BENIGN_PHRASE.sub(keep, text)


def subject_words(item):
    """항목의 대상 말 — 이름(통째·핵심어), 인증 이름과 줄임말, 종류 말, 지역 이름(결정 0016 ③·④, 조정 가능)."""
    words = set()
    name = _compact(item.get('name'))
    if name:
        words.add(name)
    words |= {w for w in re.findall(r'[가-힣A-Za-z]{2,}', str(item.get('name') or '')) if w not in _GENERIC}
    for cert in item.get('certs') or []:
        words.add(_compact(cert))
        words |= set(CERT_ALIASES.get(cert, ()))
    words |= set(KIND_WORDS.get(item.get('kind'), ()))
    for raw in item.get('regions') or []:
        sido = region_mod.canonical(raw)
        words.add(_compact(raw))
        if sido and sido != region_mod.NATIONWIDE:
            words |= {sido} | {a for a, c in region_mod.ALIASES.items() if c == sido}
            if sido == '전남광주':
                words |= {'전남', '광주'}
    return {w for w in words if w}


def cert_words(item):
    """항목이 요구하는 인증 코드·별칭·종류 말 — 신청자 입력으로 확인하는 말만(AI 가 지은 이름 낱말은 넣지 않는다, 결정 0017)."""
    words = set()
    for cert in item.get('certs') or []:
        words.add(_compact(cert))
        words |= set(CERT_ALIASES.get(cert, ()))
    words |= set(KIND_WORDS.get(item.get('kind'), ()))
    return {w for w in words if w}


def same_cert_paper(fragment, item):
    """추가 조건 조각이 그 항목 자신의 인증 증빙·유효기간만 말하는가(결정 0016 ③) — 증빙·유효기간 말, 대상 말, 뜻 없는 말을
    빼고 남는 말이 없어야 한다. "벤처기업 인증서 및 대통령 표창장 제출"은 '대통령·표창장'이 남아 아니다."""
    rest = re.sub(BENIGN_VALID, ' ', str(fragment or ''))
    rest = re.sub(BENIGN_PAPER, ' ', rest)
    for word in sorted(cert_words(item), key=len, reverse=True):
        rest = rest.replace(word, ' ')
    for token in re.findall(r'[가-힣A-Za-z]+', rest):
        if token in FILLER_WORDS or _PARTICLES.fullmatch(token):
            continue
        stem = _PARTICLES.sub('', token)          # '인증서가' → '인증서' 처럼 조사만 뗀다
        if stem and stem not in FILLER_WORDS:
            return False
    return True


def benign_extra_strict(extra, item):
    """benign_extra 에 더해 조각마다 그 항목 자신의 인증 증빙일 것(결정 0016 ③)."""
    if not benign_extra(extra):
        return False
    return all(_SME_ONLY.match(p) or same_cert_paper(p, item)
               for p in (x.strip() for x in re.split(r'[;/]', str(extra or ''))) if p)


def _qualification_clause(clause, item, mates):
    """"…경우" 구절이 자격 자체만 말하나(결정 0020 R2) — 대상 말·짝 자격 말·증빙·유효기간 말·뜻 없는 말·서술 말을 빼면 남는 말이 없다."""
    rest = re.sub(BENIGN_VALID, ' ', str(clause or ''))
    rest = re.sub(BENIGN_PAPER, ' ', rest)
    for word in sorted(set(subject_words(item)) | set(mates or ()), key=len, reverse=True):
        rest = rest.replace(word, ' ')
    for token in re.findall(r'[가-힣A-Za-z]+', rest):
        if token in FILLER_WORDS or token in _CLAUSE_VERBS or _PARTICLES.fullmatch(token):
            continue
        stem = _PARTICLES.sub('', token)
        if stem and stem not in FILLER_WORDS and stem not in _CLAUSE_VERBS:
            return False
    return True


def qualification_words(text):
    """글에 나오는 자격 이름(_QUALIFICATION_WORDS). 띄어쓰기를 지운 글에서 찾지 않는다 — "소재 기업"이 "재기(재창업)"로
    읽히지 않게(결정 0020). 줄바꿈·연속 공백만 한 칸으로 줄인다."""
    spaced = ' '.join(str(text or '').split())
    return {q for q in _QUALIFICATION_WORDS if q in spaced}


def condition_words_hit(text, item, mates=None):
    """확인할 수 없는 조건 말이 있나. "경우"만 걸렸고 그 "…경우" 구절이 모두 자격 자체만 말하면 조건으로 보지 않는다(결정 0020 R2 —
    "벤처기업 인증 또는 이노비즈 인증을 받은 경우", "기관이 여성기업인 경우"). "법인의 경우"는 그대로 조건."""
    found = CONDITION_WORDS.findall(text)
    if not found:
        return False
    if any(w != '경우' for w in found):
        return True
    for m in re.finditer('경우', text):
        bounds = [b.end() for b in _CLAUSE_BOUNDARY.finditer(text, 0, m.start())]
        if not _qualification_clause(text[(bounds[-1] if bounds else 0):m.start()], item, mates):
            return True
    return False


def points_owned(item, mates=None):
    """그 "N점"이 항목 자신의 것인가(결정 0016 ④) — 근거를 문장·항목 경계로 나눠 N점이 있는 조각에 대상 말이 있어야 한다."""
    if item.get('points') is None:
        return False
    pattern = re.compile(r'(?<![\d.])%s\s*점' % re.escape(_num(item['points'])))
    words = [_compact(w) for w in subject_words(item)]
    if not words:
        return False
    pieces = item.get('quote_lines') or [str(item.get('quote') or '')]
    for piece in pieces:
        for seg in _SEGMENT.split(piece):
            if pattern.search(seg) and any(w in _compact(seg) for w in words):
                return True
    if not _table_cell(item):
        return False
    # 표 배점 칸(결정 0019 ③, 0020 K1) — 숫자만 있는 줄 바로 앞 줄(뜻 없는 "해당" 줄은 건너뜀)에서 시작해 잇는 말(및·또는·쉼표)로
    # 끝나는 윗줄만 같은 칸(행 이름)으로 본다 — 그 밖의 앞줄은 다른 행·설명 줄이다("여성기업 우대 안내 / 벤처기업 / 10").
    # 행 이름에 대상 말이 있어야 하고, 숫자 줄 앞의 모든 줄의 자격 이름이 짝 자격(인증·종류 말)이어야 한다
    mates = set(mates) if mates is not None else set(item.get('table_mates') or ())
    num = re.escape(_num(item['points']))
    cell = re.compile(r'\s*(?:예\s*)?\(?\s*%s\s*\)?\s*' % num)          # "10", "(2)", "예(1)"(결정 0020 R3)
    for i, piece in enumerate(pieces):
        if not cell.fullmatch(piece):
            continue
        j = i - 1
        while j >= 0 and _LABEL_FILLER.fullmatch(pieces[j]):
            j -= 1
        if j < 0:
            return False
        label = [pieces[j]]
        while j - 1 >= 0 and _LABEL_JOIN.search(pieces[j - 1]):
            j -= 1
            label.insert(0, pieces[j])
        if not any(w in _compact(' '.join(label)) for w in words):
            return False
        return not (qualification_words(' '.join(pieces[:i])) - mates)
    # 숫자만 있는 줄이 없으면 같은 조각에서 대상 말이 그 숫자보다 앞에 있어야 한다(표 한 행 "이름 … 배점").
    # 숫자가 대상 말보다 앞이면 연번일 수 있다("1 여성기업 가점")
    bare = re.compile(r'(?<![\d.])%s(?![\d.])' % num)
    for piece in pieces:
        for seg in _SEGMENT.split(piece):
            m = bare.search(seg)
            if m and any(w in _compact(seg[:m.start()]) for w in words):
                return True
    return False


def item_hit(item, req, strict=True, mates=None):
    """항목 하나 × 신청자 → True · False · None.

    근거가 지금 원문에 그대로 없으면(in_document=False) None. 추가 조건·앞으로의 조건(이전·유치·예정 …)·입력으로 확인할 수 없는
    조건 말(모두·이내·최근 …)이 있으면 True 를 None 으로 낮춘다(P2-1, R-P2-2, B-P2-1 — extra_conditions 를 AI 가 비워도 글을 본다).
    in_document 칸이 없는 항목(load() 를 거치지 않은 직접 호출)은 원문 확인을 하지 않는다.
    strict(기본)면 결정 0016 ②③④⑥을 더한다. strict=False 는 이전 계산(새 규칙이 null 을 풀지 않게 비교하는 데만 쓴다).
    """
    if item.get('in_document') is False or item.get('_memo_blocked'):
        return None                                   # 부분 메모가 이 항목을 가리킨다(결정 0020 R1)
    hit = _base_hit(item, req)
    if hit is not True:
        return hit
    base = _text(item)
    if not strict or item.get('kind') == '청년':        # ⑥ 나이 구절은 실제 나이를 본 청년 항목에서만 뺀다
        base = _AGE_LIMIT.sub(' ', base)
    text = _drop_benign_phrases(base, item if strict else None)
    if strict and any(not RISKY_WORDS.search(m.group(0)) and not same_cert_paper(m.group(0), item)
                      for m in _BENIGN_PHRASE.finditer(base)):
        return None                                   # ③ 근거에 다른 자격의 서류 요구("… 및 대통령 표창장 제출")
    extra = item.get('extra_conditions')
    benign = benign_extra_strict(extra, item) if strict else benign_extra(extra)
    if (extra and not benign) or FUTURE_WORDS.search(text) or condition_words_hit(text, item, mates):
        return None
    if strict:
        if item.get('period_condition') and item.get('kind') in ('인증', '여성', '장애인'):
            return None                                   # ② 표 밖 증빙 기간 조건
        if item.get('points') is not None and not points_owned(item, mates):
            return None                                   # ④ 그 점수가 이 항목의 것인지 모른다
    return hit


def _num(points):
    value = float(points)
    return ('%d' % value) if value == int(value) else ('%g' % value)


def points_supported(item, mates=None):
    """항목 점수를 믿을 수 있나 — 떨어진 배점 칸(points_source)에서 가져오지 않았고, 근거 문장에 "N점"이 직접 있고(R-P1-1),
    근거에 서로 다른 "N점"이 둘 이상이 아니다(B-P1-1). "1 여성기업 가점"처럼 연번이 점수로 읽힌 경우(근거에 1점이 없음)도 믿지 않는다."""
    if item.get('points') is None or item.get('points_source'):
        return False
    quote = str(item.get('quote') or '')
    pattern = r'(?<![\d.])%s\s*점' % re.escape(_num(item['points']))
    if len({float(v) for v in _POINTS.findall(quote)}) >= 2:
        # 근거에 다른 배점이 섞여 있다(B-P1-1) — 쉼표까지 나눈 조각에 그 점수 하나만 있고 대상 말이 있고 자격 이름이 모두
        # 짝 자격이면 그 항목 점수로 인정한다(결정 0020 R4, "벤처·이노비즈·메인비즈 각 1점, 여성기업 3점"의 여성기업 3점)
        mates = set(mates) if mates is not None else set(cert_words(item))
        words = [_compact(w) for w in subject_words(item)]
        for seg in (x for part in _SEGMENT.split(quote) for x in re.split(r'[,;，]', part)):
            if re.search(pattern, seg) and len({float(v) for v in _POINTS.findall(seg)}) == 1 \
                    and any(w in _compact(seg) for w in words) \
                    and not (qualification_words(seg) - mates) \
                    and _qualification_clause(re.sub(pattern, ' ', seg), item, mates):
                # 조각에 자격 말 말고 다른 말이 남으면("여성기업 (법인 3점" — 법인) 그 점수의 조건일 수 있어 인정하지 않는다
                return True
        return False
    return bool(re.search(pattern, quote)) or _table_cell(item)


def _table_cell(item):
    """표 배점 칸 점수인가(결정 0019 ①②) — load() 가 원문에서 표 머리("배점")를 확인했고(score_header), 근거에 "N점"이 하나도
    없고, 단위 없는 숫자가 정확히 하나이며 그 값이 항목 점수다. 떨어진 배점 칸에서 가져온 점수(points_source)는 아니다."""
    if item.get('points') is None or item.get('points_source') or not item.get('score_header'):
        return False
    quote = str(item.get('quote') or '')
    if _POINTS.search(quote):
        return False
    nums = bare_numbers(quote)
    return bool(nums) and set(nums) == {float(item['points'])}


def bare_numbers(quote):
    """근거의 단위 없는 숫자(값 목록). 같은 값이 되풀이되어도 된다(결정 0020 R3 — "(5) … 1개 이상 : 5"). "아니오(0)" 같은 해당 없음
    칸의 0과 번호·등록·제·No 뒤의 숫자("등록번호 10", K2)는 배점 숫자가 아니다."""
    out = []
    for m in _BARE_NUMBER.finditer(quote):
        before = quote[:m.start()]
        value = float(m.group(1))
        if _SERIAL_BEFORE.search(before) or (value == 0 and _NO_ZERO_BEFORE.search(before)):
            continue
        out.append(value)
    return out


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


def _joined_hits(items, req, strict):
    """범위 안 항목마다 해당 여부. strict 면 ① 결합 조건 — "및·&"로 묶인 짝이 확인할 수 없는(None) 것이면 모름,
    '&'·'+'인데 짝이 따로 뽑히지 않았으면 모름. 짝이 해당 아님(False)이 확실하면 "둘 중 하나"로 본다(결정 0016)."""
    mates = quote_mates(items)
    hits = {id(it): item_hit(it, req, strict, mates.get(_compact(it.get('quote')))) for it in items}
    if not strict:
        return hits
    by_quote = {}
    for it in items:
        by_quote.setdefault(_compact(it.get('quote')), []).append(it)
    out = dict(hits)
    for it in items:
        quote = str(it.get('quote') or '')
        if hits[id(it)] is not True or not AND_WORDS.search(quote):
            continue
        mates = [m for m in by_quote[_compact(quote)]
                 if m is not it and (m.get('name'), m.get('kind')) != (it.get('name'), it.get('kind'))]
        if any(hits[id(m)] is None for m in mates) or not mates:
            out[id(it)] = None                    # 짝을 확인 못 함, 또는 짝이 뽑히지 않음("및"도 — 결정 0017 R3-P1-3)
    return out


def _score_scope(items, req, cap, label=None, strict=True, selection=False):
    """한 세부사업(또는 공통) 범위 → (점수 또는 None, 항목)."""
    states, picked, keys = [], [], []
    hit_of = _joined_hits(items, req, strict)
    mates = quote_mates(items)
    for group in _groups(items):
        hits = [(it, hit_of[id(it)]) for it in group]
        scored = [it for it, hit in hits if hit is True and points_supported(it, mates.get(_compact(it.get('quote'))))]
        if scored:
            if len(group) >= 2 and any(_EACH.search(str(it.get('quote') or '')) for it in group):
                return None, []               # "각 N점"인데 한 묶음 — 독립 가점을 묶었을 수 있다(B-P1-2)
            best = min(scored, key=lambda it: (-float(it['points']), it.get('name') or ''))     # 같은 점수면 이름순(R-P3-2)
            key = (_compact(best.get('quote')), float(best['points']))
            # "각 N점"이면 독립 가점이라 더한다(결정 0020 R5, Codex 6차 5.2 — 122309 "여성, 장애인, 사회적, 녹색 기업 : 각 1점")
            each = re.search(r'(?<![가-힣])각\s*%s\s*점' % re.escape(_num(best['points'])), str(best.get('quote') or ''))
            if key in keys and not each:
                return None, []               # 다른 묶음인데 근거·점수가 같다 — 선택 가점을 둘로 나눴을 수 있다(B-P1-2)
            keys.append(key)
            picked.append({'name': best.get('name') or '', 'points': float(best['points'])})
            states.append('scored')
        elif all(hit is False for _it, hit in hits):
            states.append('false')
        else:
            states.append('unknown')
    if not picked:
        return (0, []) if states and all(x == 'false' for x in states) else (None, [])
    if strict and selection and len(picked) >= 2:
        return None, []                       # ⑤ 원문에 택1·합산 금지 말이 있는데 두 묶음 이상에서 점수(결정 0016)
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
    """공고 한 건의 가점(entry, load() 값 또는 None) × 신청자 → (bonus_score, bonus_items).

    결정 0016 공통 규칙: 새 규칙을 뺀 이전 계산이 null 이면 null, 새 계산이 이전보다 크면 null — 더 엄격하게만 움직인다."""
    before = _score(entry, req, strict=False)
    if before[0] is None:
        return before
    after = _score(entry, req, strict=True)
    if after[0] is not None and after[0] > before[0]:
        return None, []
    return after


def memo_is_global(memo):
    """AI 불확실 메모가 공고 전체를 흔드나(결정 0020 R1) — 전체를 흔드는 말(합산·한도·최대·중복·택1·가점표 …)이 있거나,
    특정 대상(①~⑳ 번호, 따옴표 속 이름, "‹낱말› 항목", 자격 이름)을 가리키지 않으면 전체 메모다."""
    memo = str(memo or '')
    if MEMO_GLOBAL_WORDS.search(memo):
        return True
    if qualification_words(memo) or _MEMO_NUMBERED_ITEM.search(memo):
        return False
    for m in _MEMO_TARGET.finditer(memo):
        for token in re.findall(r'[가-힣A-Za-z]+', m.group(1) or m.group(2) or ''):
            stem = _PARTICLES.sub('', token)
            if len(stem) >= 2 and stem not in _MEMO_GENERIC and token not in _MEMO_GENERIC:
                return False
    return True


def _score(entry, req, strict=True):
    if not entry or entry.get('status') == 'unverified':
        return None, []
    notes = ' '.join(str(x) for x in entry.get('uncertain') or []).strip()
    if entry.get('status') == 'none' and notes:
        return None, []                       # '가점 없음'을 확정하지 못했다(2026-10-07 R-P2-3)
    if entry.get('status') in ('none', 'no_mention'):
        return 0, []
    if entry.get('document_check') == 'failed':
        return None, []                       # 근거 원문을 읽지 못해 확인하지 못했다(B-P1-1)
    items = entry.get('items') or []
    if notes:
        memos = [str(x).strip() for x in entry.get('uncertain') or [] if str(x).strip()]
        if any(memo_is_global(m) for m in memos):
            return None, []                   # AI 가 공고 전체를 흔드는 불확실 메모를 남겼다 — 한도·합산·읽기를 확정하지 못함(B-P1-3)
        # 부분 메모(결정 0020 R1) — 메모가 가리키는 항목만 모름, 나머지는 계산한다
        memo_text = _compact(' '.join(memos))
        items = [dict(it, _memo_blocked=True) if any(len(w) >= 2 and _compact(w) in memo_text for w in subject_words(it))
                 else it for it in items]
    cap = entry.get('max_total_points')
    sel = bool(entry.get('selection'))
    programs = sorted({it.get('program') for it in items if it.get('program')})
    if len(programs) <= 1:
        return _score_scope(items, req, cap, strict=strict, selection=sel)
    # 세부사업이 나뉜 공고 — 신청자가 어느 세부사업에 내는지 모른다. 결과가 모두 같을 때만 쓴다(2026-10-07 R-P2-4)
    results = [_score_scope([it for it in items if not it.get('program') or it.get('program') == p], req, cap, p,
                            strict=strict, selection=sel)
               for p in programs]
    if len({r[0] for r in results}) == 1 and results[0][0] is not None:
        if results[0][0] == 0:
            return 0, []
        common = _score_scope([it for it in items if not it.get('program')], req, cap, None, strict=strict, selection=sel)
        if common[0] == results[0][0]:
            return common                     # 공통 항목만으로 같은 점수 — 세부사업 꼬리표 없이 낸다
    return None, []


# ── 원문 대조를 마친 공고 목록(2026-10-08 결정 0017) ─────────────────────────────
# 순위에 가산점을 얹는 것은 이 목록에 있고, 대조 당시와 공고 내용 지문·가점 행 지문이 같고, 지금 결과의 항목이 모두 승인 항목 안일 때만이다.
# 표시(bonus_score·bonus_items)는 목록과 상관없다. 목록 추가는 eval/bonus_boostable.py --write-reviewed 로만 한다(지문을 손으로 쓰지 않는다).
REVIEWED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bonus_reviewed.json')


def load_reviewed(path=REVIEWED_PATH):
    """{notice_id: 목록 항목}. 파일이 없거나 형식이 깨지면 예외 — 공고 서버는 목록 전체를 쓰지 않는다(순위 반영 0건)."""
    import json
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    notices = data.get('notices')
    if not isinstance(notices, dict):
        raise ValueError('bonus_reviewed.json 에 notices(사전)가 없다')
    import math

    def text_ok(v):
        return isinstance(v, str) and v.strip() != ''
    for nid, e in notices.items():
        if not isinstance(e, dict) or not all(text_ok(e.get(k)) for k in ('content_version', 'row_fingerprint',
                                                                          'evidence_fingerprint')) \
                or not isinstance(e.get('approved_items'), list) or not e['approved_items']:
            raise ValueError('bonus_reviewed.json 항목 형식이 틀렸다: %s' % nid)
        for it in e['approved_items']:
            points = it.get('points') if isinstance(it, dict) else None
            # 점수는 참·거짓이 아닌 유한한 양수여야 한다 — 글자·null·{} 가 들어가면 목록 전체를 쓰지 않는다(결정 0018 R4-P2-2)
            if not isinstance(it, dict) or not text_ok(it.get('name')) or isinstance(points, bool) \
                    or not isinstance(points, (int, float)) or not math.isfinite(points) or points <= 0:
                raise ValueError('bonus_reviewed.json 승인 항목 형식이 틀렸다: %s' % nid)
    return notices


def reviewed_ok(reviewed, nid, entry, content_version, items):
    """이 공고의 지금 가산점(items = bonus_items)을 순위에 써도 되나 — 목록에 있고, 내용·가점 행 지문이 대조 당시와 같고,
    지금 결과의 항목이 모두 승인 항목 안이어야 한다. 원문 지문(evidence_fingerprint)도 같아야 한다(결정 0018)."""
    e = (reviewed or {}).get(nid)
    if not e or not entry or not items or not entry.get('evidence_fingerprint'):
        return False                          # 원문 지문이 없는 행(원문을 못 읽음 등)은 대조된 것으로 보지 않는다
    if e.get('content_version') != content_version or e.get('row_fingerprint') != entry.get('row_fingerprint') \
            or e.get('evidence_fingerprint') != entry.get('evidence_fingerprint'):
        return False
    approved = {(str(i['name']), float(i['points'])) for i in e['approved_items']}
    names = [(str(i['name']), float(i['points'])) for i in items]
    return all(n in approved for n in names)
