# -*- coding: utf-8 -*-
"""공고 매칭 시험용 웹 화면. 로그인 없음.

  .venv/bin/python -m search.app                 EC2 에서 (0.0.0.0:8000)
  .\.venv\Scripts\python.exe -m search.app       내 PC 에서 (127.0.0.1:8000)

data-collection 폴더에서 실행한다. 패키지라 파일을 직접 부르지 않고 -m 으로 부른다.

브라우저에서 열면 입력 → 공고 3건 → 클릭하면 자격요건 3항목이 나온다.

**검색은 반드시 벡터 DB(Chroma) 를 거친다.** MySQL 의 embedding 을 직접 읽어
계산하는 경로는 쓰지 않는다. MySQL 은 제목·기관·기간 같은 표시용 값과
자격 판정용 필드를 가져오는 데만 쓴다.

**기본 검색은 하이브리드다** (search='hybrid'). 의미 검색(Chroma) 결과와 단어 검색
(BM25) 결과를 순위로 합친다(RRF, hybrid.py). BM25 색인은 서버를 켤 때 한 번 메모리에
만든다. 예전 방식이 필요하면 search='dense' 로 부른다.

지금 데이터로 안 되는 것은 화면에 넣지 않았다.
  · 지원금액(최대 N원)   금액 컬럼이 DB 에 없다
  · AI 요약 한 줄        LLM 호출이 필요하다
  · 첨부파일 업로드
  · 로그인

적합도를 0~100 으로 바꾸지 않는다. 실측으로 무관한 질의도 0.43 이 나오고
상위 3건이 0.49~0.67 사이에 몰려 있어서, 100점 척도로 보이면 정확도로 읽힌다.
원값(코사인 유사도)과 3단 라벨만 보여준다.
"""
import json
import os
import sys
import time
from datetime import date

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from search import applicant as applicant_mod
from search import bonus as bonus_mod
from search import gate
from shared import region as region_mod

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # data-collection 폴더
ON_EC2 = sys.platform.startswith('linux')

FIELDS = ('notice_id', 'title', 'organizer', 'supervising_org', 'executing_org',
          'source', 'target_category', 'age_condition_raw',
          'apply_start', 'apply_end', 'apply_period_type', 'recruitment_status',
          'category', 'region', 'url', 'apply_url')

app = FastAPI(title='S-Brain 공고 매칭 (시험용)')
STATE = {}


# ── 데이터 준비 ──────────────────────────────────────────────
def _connect():
    """EC2 에서는 ec2_vecstore, 내 PC 에서는 store_mysql 을 쓴다."""
    if ON_EC2:
        from ec2 import ec2_vecstore
        return ec2_vecstore.connect()
    from shared import store_mysql
    return store_mysql.connect()


# 조율 에이전트가 부르는 창구(수집 상태 등, 2026-10-06). 상태와 DB 연결 함수를 넘긴다 — 이유는 notice_api 머리말
from search import notice_api  # noqa: E402
app.include_router(notice_api.build_router(STATE, lambda: _connect()))  # 시험에서 _connect 를 바꿔 끼울 수 있게 감싼다


def _collection():
    """벡터 DB. EC2 와 로컬 모두 Chroma 다."""
    if ON_EC2:
        from ec2 import ec2_vecstore
        col = ec2_vecstore.open_store(create=False)
        if col is None:
            raise SystemExit('Chroma 색인이 없다. ec2_vecstore.py 를 먼저 돌린다.')
        return col
    from search import vecstore
    return vecstore.open_chroma()


def _encode(text):
    """질의를 벡터로. 공고 벡터와 같은 모델·같은 토큰 상한이어야 한다.

    파이썬 float 리스트로 돌려준다. numpy 배열을 list() 로 감싸면 np.float32
    스칼라 목록이 되어 Chroma 가 거부한다. tolist() 를 써야 한다.
    """
    import numpy as np
    if ON_EC2:
        vectors = STATE['model'].encode([text], normalize_embeddings=True,
                                        show_progress_bar=False)
        return np.asarray(vectors[0], dtype='float32').tolist()
    from search import vecstore
    return np.asarray(vecstore.embed_query(text), dtype='float32').tolist()


def _build_bm25():
    from shared import embed
    from search import hybrid
    columns = ('notice_id',) + embed.FIELDS
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT ' + ','.join(columns) + ' FROM notices')
            rows = [dict(zip(columns, r)) for r in cursor.fetchall()]
    finally:
        connection.close()
    docs = [(r['notice_id'], embed.build_input(r)) for r in rows]
    return hybrid.BM25([(nid, text) for nid, text in docs if text])


def boot():
    started = time.time()
    # 벡터 DB·임베딩이 죽어 있어도 서버는 연다(2026-09-28 Codex 통합 검수 P1). 공고 정보·BM25 만 있으면
    # match() 가 BM25 단독으로 내려간다(E). 여기서 막히면 대체 경로가 서버 재시작 때 쓸모가 없다.
    # 공고 정보(DB)·BM25 는 정형 필터와 대체 검색의 바탕이라 실패하면 그대로 멈춘다.
    STATE['boot_errors'] = {}
    STATE['collection'] = STATE['vector_ids'] = None
    try:
        STATE['collection'] = _collection()
        print('벡터 DB 색인 %d건' % STATE['collection'].count())
        # 정형 필터 통과 공고 안에서만 의미 검색을 하려면 색인에 있는 ID 를 알아야 한다(_dense_within)
        STATE['vector_ids'] = set(STATE['collection'].get(include=[])['ids']) - {'__watermark__'}
    except BaseException as exc:                  # _collection() 은 색인이 없으면 SystemExit 를 낸다
        if isinstance(exc, KeyboardInterrupt):
            raise
        STATE['collection'] = STATE['vector_ids'] = None
        STATE['boot_errors']['vector_db'] = _describe(exc, '벡터 DB 연결')
        print('경고: 벡터 DB 를 열지 못했다 — 의미 검색 없이 시작한다 (%s)' % STATE['boot_errors']['vector_db']['error'],
              file=sys.stderr)

    from search import collection_status, content_version
    connection = _connect()
    try:
        # 올릴 공고의 저장 시각 — 공고보다 **먼저** 읽는다(그 사이 배치가 저장해도 더 오래된 쪽으로 남는다).
        # 수집 상태 창구가 "서버가 들고 있는 공고가 오래됐는가"를 볼 때 쓴다(search/notice_api.py). 실패해도 서버는 연다
        try:
            STATE['loaded_store_at'] = collection_status.read_latest_store(connection)[0]
        except Exception as exc:
            STATE['loaded_store_at'] = None
            STATE['boot_errors']['loaded_store_at'] = _describe(exc, '공고 저장 시각 읽기')
        with connection.cursor() as cursor:
            cursor.execute('SELECT ' + ','.join(FIELDS) + ' FROM notices')
            STATE['rows'] = {r[0]: dict(zip(FIELDS, r)) for r in cursor.fetchall()}
    finally:
        connection.close()
    print('공고 정보 %d건' % len(STATE['rows']))

    # 공고 내용 지문(조율 요청서 3.1, search/content_version.py). 실패하면 추천 결과의 content_version 이 null 이 된다
    # (조율 쪽은 null 이면 카드 정보 비교로만 "내용 바뀜"을 판단한다)
    STATE['content_versions'] = {}
    try:
        connection = _connect()
        try:
            STATE['content_versions'] = content_version.load(connection)
        finally:
            connection.close()
    except Exception as exc:
        STATE['boot_errors']['content_version'] = _describe(exc, '공고 내용 지문 계산')
    print('공고 내용 지문 %d건' % len(STATE['content_versions']))
    # 공고 상세 창구의 지원 금액(notice_conditions, 02). 실패하면 금액이 모두 null 이 된다
    STATE['amounts'] = {}
    try:
        connection = _connect()
        try:
            STATE['amounts'] = notice_api.load_amounts(connection)
        finally:
            connection.close()
    except Exception as exc:
        STATE['boot_errors']['amounts'] = _describe(exc, '지원 금액 읽기')
    print('지원 금액 %d건' % len(STATE['amounts']))
    # 공고 가점(notice_bonus, 03_bonus). 실패하면 가산점이 모두 null(계산하지 못함)이 된다.
    # 뽑을 때의 공고 내용 지문·추출기 버전이 지금과 다른 행은 쓰지 않는다(공고문이 바뀌었는데 아직 다시 뽑지 않음 → null).
    # 지문을 계산하지 못했으면 가점도 쓰지 않는다(최신인지 알 수 없다) — 2026-10-06 Codex 검수 P2-4
    STATE['bonus'] = {}
    stale = {}
    try:
        if 'content_version' in STATE['boot_errors']:
            raise RuntimeError('공고 내용 지문이 없어 가점 최신성을 확인할 수 없다')
        from collect.extract_bonus import EXTRACTOR_VERSION
        connection = _connect()
        try:
            STATE['bonus'] = bonus_mod.load(connection, versions=STATE['content_versions'],
                                            extractor_version=EXTRACTOR_VERSION, stale=stale)
        finally:
            connection.close()
    except Exception as exc:
        STATE['boot_errors']['bonus'] = _describe(exc, '공고 가점 읽기')
    print('공고 가점 %d건 (내용이 바뀌어 뺌 %d · 추출기 버전이 달라 뺌 %d)'
          % (len(STATE['bonus']), stale.get('content', 0), stale.get('version', 0)))

    # 단어 검색 색인. 공고 문장은 임베딩과 **같은 입력**(embed.build_input)을 쓴다.
    # 평가(eval/build_pool.py corpus)와도 같다. 매일 배치 뒤에는 서버를 다시 켜야 반영된다.
    t0 = time.time()
    STATE['bm25'] = _build_bm25()
    print('BM25 색인 %d건 · %.1f초' % (len(STATE['bm25']), time.time() - t0))

    # 업종 순위 신호(2026-09-28)·신청자 유형(G). 없으면 해당 기능이 꺼진다
    from search import industry_rank
    from search import applicant_types
    # 판정(2026-09-28): 공용 DB(배치 13단계가 올린 표)를 먼저 읽고, 없거나 실패하면 배치 PC 의 파일을 쓴다.
    # 신청자 유형은 기본 auto, 업종은 기본 file(final5 — Codex 재검수 뒤 바꾸기로 한 결정). 환경 변수로 바꾼다
    try:
        judgments_conn = _connect()
    except Exception as exc:
        judgments_conn = None
        STATE['boot_errors']['judgments_db'] = _describe(exc, '판정 DB 연결')
    # 두 판정 읽기는 예외를 내지 않게 만들었지만, 예상 밖 예외가 나도 **기능만 끄고** 서버는 연다
    # (2026-09-29 Codex 재검수 P1-4 — 조율 에이전트도 이 boot() 를 부른다)
    def judged(name, load, where):
        try:
            return load(judgments_conn, expected=len(STATE['rows']))
        except Exception as exc:
            STATE['boot_errors'][name] = _describe(exc, where)
            return {'active': False, 'source': None, 'rows': 0, 'notices': {},
                    'error': '%s 중 예외: %s' % (where, type(exc).__name__)}
    try:
        # 업종: expected 로 DB 표가 "다 올라간" 것인지 본다(공고 수의 95%, Codex 검수 P1). 순위 기능은 기본 꺼짐
        STATE['industry'] = judged('industry', industry_rank.load_auto, '업종 판정 읽기')
        # 신청자 유형: 지금 공고문의 지문과 같은 판정만 쓴다(2026-09-29 Codex 재검수 P1). 지문을 계산하지 못하거나
        # 쓸 판정이 0건이면 기능만 꺼지고 error 에 이유가 남는다
        STATE['applicant_types'] = judged('applicant_types', applicant_types.load_auto, '신청자 유형 판정 읽기')
    finally:
        if judgments_conn is not None:
            judgments_conn.close()
    if STATE['applicant_types'].get('error') and not STATE['applicant_types'].get('active') \
            and 'applicant_types' not in STATE['boot_errors']:
        STATE['boot_errors']['applicant_types'] = {'where': '신청자 유형 판정 읽기',
                                                   'error': STATE['applicant_types']['error']}
    # 업력 근거(2026-09-28 B). 자격 확인의 업력 줄에 공고문 추출 값을 **근거로만** 보여 준다. 실패해도 서버는 연다
    from search import age_evidence
    # load() 는 예외를 내지 않는다 — DB·파일 중 실패한 쪽만 비우고 error 에 적는다(Codex 검수 P1)
    try:
        connection = _connect()
    except Exception as exc:
        connection = None
        STATE['boot_errors']['age_evidence'] = _describe(exc, '업력 근거 읽기(DB 연결)')
    try:
        STATE['age_evidence'] = age_evidence.load(connection)
    finally:
        if connection is not None:
            connection.close()
    if STATE['age_evidence']['error']:
        STATE['boot_errors']['age_evidence'] = {'where': '업력 근거 읽기', 'error': STATE['age_evidence']['error']}
    print('업력 근거 %d건 (%s)' % (len(STATE['age_evidence']['notices']), ' + '.join(STATE['age_evidence']['sources'])))
    for label, key in (('신청자 유형', 'applicant_types'), ('업종 순위 신호', 'industry')):
        t = STATE[key]
        print('%s %d건 (%s)%s%s' % (label, len(t['notices']), t['source'],
                                    ' · ' + t['error'] if t.get('error') else '', ' · ' + t['note'] if t.get('note') else ''))

    if ON_EC2:
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer('BAAI/bge-m3')
            model.max_seq_length = 512
            STATE['model'] = model
        except Exception as exc:
            STATE['boot_errors']['embedding'] = _describe(exc, '임베딩 모델 올리기')
            print('경고: 임베딩 모델을 올리지 못했다 — %s' % STATE['boot_errors']['embedding']['error'], file=sys.stderr)

    # 첫 질의가 20초 걸린다. 첫 사용자가 그걸 기다리지 않게 미리 털어낸다.
    print('워밍업...')
    try:
        _encode('워밍업')
    except Exception as exc:
        # 요청마다 다시 시도한다. 그동안은 match() 가 BM25 단독으로 답한다
        STATE['boot_errors']['embedding'] = _describe(exc, '임베딩 워밍업')
        print('경고: 임베딩 워밍업 실패 — %s' % STATE['boot_errors']['embedding']['error'], file=sys.stderr)
    print('준비 완료 · %.1f초%s' % (time.time() - started,
                                 ' · 경고 %s' % ', '.join(sorted(STATE['boot_errors'])) if STATE['boot_errors'] else ''))


# ── 질의 문장 만들기 ─────────────────────────────────────────
def build_query(payload):
    """입력을 한 문장으로 엮는다.

    공고 벡터가 `제목+개요+지원대상+분류` 로 만들어졌으므로 질의도 그 결에
    맞춘다. 대표자명·단가 숫자는 넣지 않는다. 공고 쪽에 대응하는 내용이 없어
    잡음만 된다(금액 컬럼이 DB 에 없다).
    """
    parts = [payload.idea.strip()]

    items = [r.item.strip() for r in (payload.revenue or []) if r.item.strip()]
    if items:
        parts.append('수익모델: ' + ', '.join(items))

    if payload.applicant_type == '예비창업자':
        parts.append('예비창업자')
    else:
        months = gate.business_age_months(payload.founded_at)
        if months is not None:
            parts.append('창업 %d년차 %s' % (months // 12 + 1, payload.applicant_type))
        else:
            parts.append(payload.applicant_type)

    careers = [m.career.strip() for m in (payload.team or []) if m.career.strip()]
    if careers:
        parts.append('팀 경력: ' + ', '.join(careers))

    # 늘어난 입력 중 공고 본문에 대응하는 말이 있는 것만 (applicant.py 1번 갈래)
    parts.extend(applicant_mod.query_extras(payload))
    return '. '.join(p for p in parts if p)


def band(score):
    """점수를 3단 라벨로. 숫자만 보여주면 정확도로 읽힌다."""
    if score >= 0.62:
        return '매우 적합'
    if score >= 0.55:
        return '적합'
    return '참고'


# ── 요청 모델 ────────────────────────────────────────────────
class TeamMember(BaseModel):
    name: str = ''
    role: str = ''
    career: str = ''


class RevenueItem(BaseModel):
    item: str = ''
    price: str = ''


class Weights(BaseModel):
    """검색·규칙의 무게. **기본값은 지금 서비스와 완전히 같다**(전부 1.0 · 순서 방식).

    두 가지를 조절한다.

      섞는 무게   의미 검색과 단어 검색 중 어느 쪽 순위를 더 믿을지
      규칙 방식   order = 해당되면 맨 뒤로 (지금 방식, 중간이 없다)
                  score = 점수를 깎는다 (0.3 이면 30% 깎임, 1.0 이면 사실상 배제)

    값을 정할 근거가 아직 없다(평가 질의 52개). 그래서 기본은 건드리지 않고,
    바꿔 보고 싶을 때만 넘긴다. 효과는 eval/weight_eval.py 로 잰다.
    """
    dense: float = 1.0
    bm25: float = 1.0
    rrf_k: int = 60
    mode: str = 'order'            # 'order' | 'score'
    penalty_group: float = 0.5     # score 방식에서 집단 근거 없음
    penalty_region: float = 1.0    # score 방식에서 다른 시·도 전용
    penalty_district: float = 0.3  # score 방식에서 같은 시·도의 다른 시·군·구
    penalty_industry: float = 0.5  # score 방식에서 업종 허용 목록 밖 (잠정 — LLM 추출이라 지역보다 약하게)
    penalty_pre_implied: float = 0.5  # score 방식에서 예비창업자인데 대상이 기존 사업자로 보이는 공고(추정)
    # 가산점 반영 세기(03_bonus 3-4). 검색 점수 × (1 + bonus × min(가산점, 10)/10). 0 이면 가산점 전과 순서가 같다.
    # order 방식에서는 규칙 묶음(다른 지역 등)을 넘지 않고 같은 묶음 안에서만 순서를 바꾼다.
    # 기본 0(2026-10-06 Codex 검수 P3-1): 0.1~0.3 모두 관련도 지표 변화 0 이었지만(eval/bonus_rank_eval.py,
    # reports/bonus_rank_eval_20261006T015155Z/) 정답이 가산점을 몰라 "좋은 순위"인지 재지 못했고 가점 추출 정확도도
    # 사람 정답으로 확인하지 않았다. 확인될 때까지 순위에는 반영하지 않는다(결과의 bonus_score 는 그대로 나간다)
    bonus: float = 0.0


class MatchRequest(BaseModel):
    applicant_type: str
    owner_name: str = ''
    founded_at: str = ''
    idea: str
    team: list[TeamMember] = []
    revenue: list[RevenueItem] = []
    # 후보 수(기능정의서 T-C2 topK·offset, 2026-09-28 D): 첫 조회 10건(상위 3 카드 + 7 리스트),
    # 추가 조회는 offset=10 으로 다음 10건, 누적 최대 MAX_CANDIDATES(20)건. 평가 스크립트는 top 을 크게 줘 후보 전체를 받는다
    top: int = 10
    offset: int = 0
    # 정형 필터(검색 전, gate.prefilter). hide_expired 는 그중 모집 상태·접수 마감 부분이다.
    # 둘 다 비교·평가용 스위치이며 서비스 화면은 항상 True 로 부른다
    structured_filter: bool = True
    hide_expired: bool = True
    # 회사 소재지. 시·도 16개 중 하나(region.REGIONS) 또는 빈 값(고르지 않음).
    region: str = ''
    # 소재지를 골랐을 때, 다른 지역 전용 공고를 뒤로 보낸다. 빼지는 않는다.
    # 지역 정보가 없는 공고는 건드리지 않는다(모른다고 벌주지 않는다).
    demote_region: bool = True
    # 개선안 B. 특정 대상 집단 공고를 신청자 입력에 근거가 없으면 뒤로 보낸다(rank_rules.py)
    demote_groups: bool = True
    # 'hybrid' = 의미 검색 + 단어 검색(BM25) 을 RRF 로 합친다 (기본)
    # 'dense'  = 의미 검색만 (2026-09-17 이전 방식)
    search: str = 'hybrid'

    # ── 신청자 정보 (2026-09-18 확장) ────────────────────────
    # 무엇이 매칭에 쓰이고 무엇이 저장만 되는지는 search/applicant.py 에 적혀 있다.
    name: str = ''                      # 저장만
    birth_date: str = ''                # 저장만 (나이 조건이 공고 칸에 없다)
    gender: str = ''                    # 규칙 — '여성' 이면 여성기업 공고를 지키지 않는다
    district: str = ''                  # 시·군·구. 공고 제목에 적힌 곳과 맞춰 본다
    demote_district: bool = True
    certifications: list[str] = []      # 질의 + 규칙
    main_industry: str = ''             # 질의 + 규칙 + 업종 순위(industry_rank)
    # 주 업종이 공고 허용 업종 목록 밖이면 뒤로 보낸다. 빼지 않는다. 모르면 건드리지 않는다(2026-09-28)
    # **기본 꺼짐**(2026-09-28 사용자 결정): Codex 블라인드 판정에서 밀린 공고 34건 중 11건이 부당하게 밀렸다
    # (허가·상품·창업 예정 업종·역할 갈래를 신청자 업종 제한으로 읽음). 추출을 고친 뒤 다시 켠다. 평가는 True 로 부른다
    demote_industry: bool = False
    # 공고 본문의 신청자 유형(G, 2026-09-28). 예비창업자 신청자에게만 쓴다(search/applicant_types.py)
    use_applicant_types: bool = True
    hiring_plan: bool = False           # 질의
    partners: list[str] = []            # 규칙 (협력 기관·기업)
    equipment: list[str] = []           # 저장만
    first_startup: bool | None = None   # 규칙 — False(재창업) 면 재창업 공고를 지킨다
    budget_scale: int | None = None     # 저장만 (예비창업자 2,000만원 한도 등)
    business_no: str = ''               # 저장만 (국세청 API 를 붙이면 설립일 검증)
    self_funding: bool | None = None    # 저장만
    self_funding_budget: int | None = None

    # 가중치. 주지 않으면 기본값이라 예전과 같은 결과가 나온다
    weights: Weights = Weights()


class GateRequest(BaseModel):
    notice_id: str
    applicant_type: str
    founded_at: str = ''


# ── API ─────────────────────────────────────────────────────
def _public(req):
    """공개 경로의 요청 — 누적 MAX_CANDIDATES 건을 넘지 않게 top 을 자른다(기능정의서 T-C2 최대 20건,
    2026-09-28 Codex 통합 검수 P2). 평가 도구는 HTTP 가 아니라 match() 를 직접 불러 후보 전체를 받는다."""
    offset = max(0, req.offset)
    return req.model_copy(update={'top': max(0, min(req.top, MAX_CANDIDATES - offset))})


@app.post('/api/match')
def api_match(req: MatchRequest):
    return match(_public(req))


def eligible_with_types(nid, row, age_months, today, check_deadline=True, types_table=None):
    """정형 필터 한 건 — gate.prefilter 에 공고 본문 신청자 유형 판정(G)을 얹는다. (남길지, 이유, 바뀜)

    types_table 은 예비창업자 신청자일 때만 넘긴다(None 이면 prefilter 그대로). 바뀜은 None | 'restored' | 'blocked'.
    매칭(match)과 평가 채점(eval/filter_first_eval.py)이 같은 기준을 쓰도록 한곳에 둔다(2026-09-28).
    """
    from search import applicant_types as types_mod
    keep, why = gate.prefilter(row, age_months, today, check_deadline=check_deadline)
    if types_table is None:
        return keep, why, None
    verdict = types_mod.pre_founder(types_table, nid)
    if verdict == 'allowed' and '업력·신청자 유형' in why:
        # K-Startup API 업력 칸은 예비창업자 불가인데 본문은 가능 — 본문을 우선한다(Codex 판정 9/9)
        why = [w for w in why if w != '업력·신청자 유형']
        return not why, why, 'restored'
    if verdict == 'blocked' and '업력·신청자 유형' not in why:
        return False, why + ['예비창업자 불가(공고 본문)'], 'blocked'
    return keep, why, None


BONUS_SCALE = 10.0     # 가산점 10점을 "가득"으로 본다(공고 가점 한도는 대개 3~10점, 2026-10-06 표본)


def bonus_boost(candidates, ranks, hybrid_on, req):
    """{공고 ID: 가산점을 얹은 검색 점수} — order 방식의 같은 규칙 묶음 안 정렬에 쓴다(03_bonus 3-4).

    검색 점수는 scored 방식과 같은 척도: 하이브리드면 RRF, 의미 검색만이면 유사도. 점수가 없는 경로(마감임박순)는 빈 사전 —
    순서를 바꾸지 않는다. 가산점이 null(계산하지 못함)·0 이면 얹지 않는다.
    """
    out, any_bonus = {}, False
    for nid, dist, _row in candidates:
        base = ranks.get(nid, {}).get('rrf_score') if (hybrid_on or dist is None) else 1.0 - dist
        if base is None:
            return {}
        points = bonus_mod.score(STATE.get('bonus', {}).get(nid), req)[0] or 0.0
        any_bonus = any_bonus or points > 0
        out[nid] = base * (1.0 + req.weights.bonus * min(points, BONUS_SCALE) / BONUS_SCALE)
    # 가산점이 있는 후보가 하나도 없으면 다시 정렬하지 않는다 — 가산점 전과 순서가 정확히 같다
    return out if any_bonus else {}


def match(req: MatchRequest):
    """매칭 본체. 공개 경로(/api/match)는 _public() 으로 20건을 넘지 않게 자른 뒤 이것을 부른다.
    파이썬에서 직접 부르면(평가 도구) top 제한이 없다 — offset 을 쓸 때만 누적 20건으로 자른다."""
    query = build_query(req)
    hybrid_on = req.search != 'dense'
    col = STATE['collection']

    # ── 1. 정형 필터 — 검색보다 **먼저** 모든 공고에 적용한다 (기획서 5-3, 기능정의서 R-3) ──
    # 2026-09-28 이전에는 검색 상위 후보를 먼저 자르고 마감만 거른 뒤 모자라면 더 깊이 찾았다.
    # 기능정의서는 그 순서를 결함으로 본다(R-3 ①). 지역·업종은 여기서 쓰지 않고 순위에만 쓴다.
    today = date.today()
    age_months = gate.applicant_age(req.applicant_type, req.founded_at, today)
    # 신청자 유형(G): 예비창업자 신청자에게만. 본문 '불가'(강한 근거)는 빼고, 본문 '가능'은 API 업력 칸보다 우선한다
    from search import applicant_types as types_mod
    types_table = STATE.get('applicant_types') or {}
    use_types = bool(req.use_applicant_types and req.structured_filter and types_table.get('active')
                     and req.applicant_type == types_mod.PRE_FOUNDER)
    passed, excluded = [], {}
    types_blocked, types_restored = [], []
    for nid, row in STATE['rows'].items():
        if not req.structured_filter:
            keep, why = True, []
        else:
            keep, why, change = eligible_with_types(nid, row, age_months, today, req.hide_expired,
                                                    types_table if use_types else None)
            if change == 'restored':
                types_restored.append(nid)
            elif change == 'blocked':
                types_blocked.append(nid)
        if keep:
            passed.append(nid)
        for reason in why:
            excluded[reason] = excluded.get(reason, 0) + 1
    allowed = set(passed)

    # 쪽수 나누기(D). offset 이 있으면 누적 MAX_CANDIDATES 를 넘지 않게 자른다
    offset = max(0, req.offset)
    top = max(0, req.top)
    if offset:
        top = max(0, min(top, MAX_CANDIDATES - offset))

    # 각 검색에서 합치기 전에 가져올 후보 수. 필터를 통과한 공고 안에서만 센다
    depth = max(offset + top, _hybrid_depth())

    # 검색 구간 전체를 바깥에서 잰다. dense·BM25 세부 시간만 더하면 그 사이에 일어나는
    # 벡터 추가 조회(_fill_distances)·RRF 결합 시간이 빠져 화면에 실제보다 짧게 찍힌다
    # (2026-09-18 Codex 검토 P3). 세부 시간은 어디에 시간이 쓰였는지 보려고 그대로 둔다.
    # 필터 통과 0건이면 질의를 인코딩하지도 검색하지도 않고 빈 결과를 돌려준다(R-3 ②, Codex 검수 P2 2026-09-28)
    #
    # 대체 경로(E, 기능정의서 R-3 ③·E-C2-EMBED, 2026-09-28): 인코딩·Chroma·BM25 오류를 따로 잡는다.
    #   임베딩 쪽 오류 → BM25 단독 · BM25 오류 → 임베딩 단독 · 둘 다 → 필터 통과 공고를 마감 임박순(잠정)
    #   정형 필터는 어느 경로에서도 생략하지 않는다. dense 방식도 의미 검색이 실패하면 BM25 단독으로 간다
    encode_ms = 0.0
    search_started = time.time()
    dense_ms = bm25_ms = 0.0
    ranks = {}
    ordered = []
    dense_path = dense_error = None
    fallback_mode = None
    search_errors = {}
    fit_max = None
    w = req.weights
    if passed:
        # ── 2. 필터 통과 공고 안에서만 검색 ──
        qv = dense = lexical = None
        t0 = time.time()
        try:
            qv = _encode(query)
        except Exception as exc:
            search_errors['embedding'] = _describe(exc, '질의 인코딩')
        encode_ms = (time.time() - t0) * 1000
        search_started = time.time()
        if qv is not None and col is None:
            boot_error = (STATE.get('boot_errors') or {}).get('vector_db') or {}
            search_errors['embedding'] = {'where': '의미 검색',
                                          'error': '벡터 DB 가 열려 있지 않다(서버 시작 때 실패 — %s)'
                                                   % (boot_error.get('error') or '원인 기록 없음')}
        elif qv is not None:
            t0 = time.time()
            try:
                dense, dense_path, dense_error = _dense_within(col, qv, passed, depth)
            except Exception as exc:
                search_errors['embedding'] = _describe(exc, '의미 검색')
            dense_ms = (time.time() - t0) * 1000
        if hybrid_on or dense is None:
            t1 = time.time()
            try:
                lexical = STATE['bm25'].search(query, top=depth, allowed=allowed)
            except Exception as exc:
                search_errors['bm25'] = _describe(exc, '단어 검색')
            bm25_ms = (time.time() - t1) * 1000

        from search import hybrid
        if dense is not None and lexical is not None and hybrid_on:
            ranks = {nid: {'dense_rank': i} for i, (nid, _) in enumerate(dense, 1)}
            for i, (nid, _) in enumerate(lexical, 1):
                ranks.setdefault(nid, {})['bm25_rank'] = i
            fused = hybrid.rrf(dense, lexical, k=w.rrf_k, weights=(w.dense, w.bm25))
            # 표시용 점수(유사도)와 3단 라벨은 예전 기준 그대로다. 단어 검색에서만 올라온
            # 공고는 Chroma 에서 벡터를 꺼내 질의와의 코사인을 구한다.
            dist_of = dict(dense)
            try:
                _fill_distances(col, qv, [nid for nid, _ in fused if nid not in dist_of], dist_of)
                ordered = [(nid, dist_of[nid]) for nid, _ in fused if nid in dist_of]
            except Exception as exc:
                # 보조 조회만 실패했다(2026-09-28 Codex 통합 검수 P1). 순위(RRF)는 그대로 쓰고,
                # 단어 검색에서만 찾은 공고는 유사도 없이(score·band None) 보여 준다. 500 으로 끝내지 않는다
                search_errors['embedding'] = _describe(exc, '벡터 추가 조회')
                ordered = [(nid, dist_of.get(nid)) for nid, _ in fused]
            for nid, sc in fused:
                ranks[nid]['rrf_score'] = round(sc, 5)
            fit_max = (w.dense + w.bm25) / (w.rrf_k + 1)
        elif dense is not None:
            # 의미 검색만(dense 방식) 또는 BM25 가 실패한 하이브리드
            if hybrid_on:
                fallback_mode = '임베딩단독'
            ordered = dense
            for i, (nid, _) in enumerate(dense, 1):
                ranks[nid] = {'dense_rank': i, 'rrf_score': round(w.dense / (w.rrf_k + i), 5)}
            fit_max = w.dense / (w.rrf_k + 1)
        elif lexical is not None:
            fallback_mode = 'BM25단독'
            ordered = [(nid, None) for nid, _ in lexical]
            for i, (nid, _) in enumerate(lexical, 1):
                ranks[nid] = {'bm25_rank': i, 'rrf_score': round(w.bm25 / (w.rrf_k + i), 5)}
            fit_max = w.bm25 / (w.rrf_k + 1)
        else:
            fallback_mode = '마감임박순'
            ordered = [(nid, None) for nid in _by_deadline(passed)][:depth]
    search_ms = (time.time() - search_started) * 1000

    candidates = [(nid, dist, STATE['rows'][nid]) for nid, dist in ordered if nid in allowed]

    # ── 규칙 ────────────────────────────────────────────────
    # 어떤 공고가 어떤 규칙에 걸리는지 먼저 한 번에 판정한다. 그 다음
    #   order 방식  걸린 것을 맨 뒤로 보낸다 (지금 서비스)
    #   score 방식  걸린 만큼 점수를 깎아 다시 정렬한다 (가중치 시험)
    from search import rank_rules
    from search import industry_rank
    applicant_words = rank_rules.applicant_text(
        req.idea, [m.career for m in req.team or []] + applicant_mod.rule_words(req))
    industry_table = STATE.get('industry') or {}
    industry_section = industry_rank.applicant_section(req.main_industry) if req.demote_industry else None
    flags = {}
    for nid, _dist, row in candidates:
        groups = (rank_rules.groups_not_matched(row.get('title'), row.get('target_category'),
                                                applicant_words)
                  if req.demote_groups else [])
        off_region = (req.demote_region and req.region
                      and region_mod.matches(row.get('region'), req.region) is False)
        off_district = (req.demote_district and req.district and req.region
                        and region_mod.district_matches(row.get('title'), row.get('region'),
                                                        req.region, req.district) is False)
        off_industry = industry_rank.off_industry(industry_table, nid, industry_section)
        pre_implied = use_types and types_mod.pre_founder(types_table, nid) == 'implied_no'
        flags[nid] = {'groups': groups, 'region': bool(off_region), 'district': bool(off_district),
                      'industry': off_industry, 'pre_implied': pre_implied}

    scored_mode = req.weights.mode == 'score'
    if scored_mode:
        w = req.weights

        def factor(nid):
            f = 1.0
            hit = flags[nid]
            if hit['groups']:
                f *= max(0.0, 1 - w.penalty_group)
            if hit['region']:
                f *= max(0.0, 1 - w.penalty_region)
            if hit['district']:
                f *= max(0.0, 1 - w.penalty_district)
            if hit['industry']:
                f *= max(0.0, 1 - w.penalty_industry)
            if hit['pre_implied']:
                f *= max(0.0, 1 - w.penalty_pre_implied)
            return f

        # 한 검색 안에서는 한 가지 점수만 쓴다. 하이브리드면 RRF, 의미 검색만이면 유사도.
        # 섞으면 척도가 달라 감점을 하나도 주지 않아도 순서가 바뀐다(검토 2번).
        base = {nid: (ranks.get(nid, {}).get('rrf_score') or 0.0 if (hybrid_on or dist is None) else (1.0 - dist))
                for nid, dist, _row in candidates}
        order = {nid: i for i, (nid, _d, _r) in enumerate(candidates)}
        candidates.sort(key=lambda c: (-base[c[0]] * factor(c[0]), order[c[0]]))
        for nid in base:
            ranks.setdefault(nid, {})['weighted_score'] = round(base[nid] * factor(nid), 6)

    # order 방식 — 규칙에 걸린 공고를 뒤로 보낸다. 빼지는 않는다.
    #
    # 규칙을 하나씩 순서대로 밀어내면 **나중 규칙이 앞선 규칙을 덮어쓴다.**
    # 예: 신청자가 경기 수원시일 때 서울 공고는 시·군·구 판정이 '모름' 이라 제자리에 남고,
    # 경기 성남시 공고는 '다름' 이라 맨 뒤로 가서, 다른 시·도 공고가 같은 시·도 공고보다
    # 앞서는 일이 생겼다(2026-09-18 Codex 검토 1번). 그래서 한 번만 정렬하고
    # **우선순위를 여기 한 줄로 못 박는다.**
    #
    #   1) 다른 시·도 전용    신청 자체가 안 된다 — 가장 강함
    #   2) 다른 시·군·구 전용  대개 신청이 안 된다
    #   3) 예비창업자인데 대상이 기존 사업자로 보임(추정)  Codex 판정 23/23 이 불가·추정. 추정이라 빼지 않는다(2026-09-28 G)
    #   4) 업종 허용 목록 밖   신청이 안 될 가능성이 크다. 다만 LLM 추출이라 사람 검증 전 — 지역보다 약하게. 기본 꺼짐
    #   5) 집단 근거 없음      신청자가 실제로 그 집단일 수 있다 — 가장 약함
    #   6) 같은 조건이면 검색 순서를 그대로 둔다
    #   6') 가산점(03_bonus 3-4, weights.bonus > 0 일 때만) — 같은 묶음 안에서 검색 점수 × (1 + 세기 × 가산점/10)
    demoted, region_demoted, district_demoted, industry_demoted = [], [], [], []
    if not scored_mode:
        order_of = {nid: i for i, (nid, _d, _r) in enumerate(candidates)}
        boosted = bonus_boost(candidates, ranks, hybrid_on, req) if req.weights.bonus > 0 else {}
        candidates.sort(key=lambda c: (flags[c[0]]['region'],
                                       flags[c[0]]['district'],
                                       flags[c[0]]['pre_implied'],
                                       flags[c[0]]['industry'],
                                       bool(flags[c[0]]['groups']),
                                       -boosted.get(c[0], 0.0),
                                       order_of[c[0]]))
        demoted = [{'notice_id': nid, 'title': row.get('title') or '',
                    'score': None if dist is None else round(1.0 - dist, 4),
                    'groups': flags[nid]['groups']}
                   for nid, dist, row in candidates if flags[nid]['groups']][:5]
        region_demoted = [{'notice_id': nid, 'title': row.get('title') or '',
                           'region': row.get('region') or ''}
                          for nid, _dist, row in candidates if flags[nid]['region']][:5]
        district_demoted = [{'notice_id': nid, 'title': row.get('title') or '',
                             'districts': sorted(region_mod.districts_in_title(row.get('title'),
                                                                              req.region))}
                            for nid, _dist, row in candidates if flags[nid]['district']][:5]
        industry_demoted = [{'notice_id': nid, 'title': row.get('title') or '',
                             'sections': industry_table['notices'][nid]['sections'],
                             'allowed': industry_table['notices'][nid]['allowed']}
                            for nid, _dist, row in candidates if flags[nid]['industry']][:5]

    results = []
    for position, (nid, dist, row) in enumerate(candidates, 1):
        if position <= offset:
            continue
        if len(results) >= top:
            break
        end = row.get('apply_end')
        score = None if dist is None else 1.0 - dist
        rrf_score = ranks.get(nid, {}).get('rrf_score')
        results.append({
            'notice_id': nid,
            'title': row.get('title') or '',
            'organizer': (row.get('organizer') or row.get('supervising_org')
                          or row.get('executing_org') or ''),
            'source': row.get('source'),
            'target_category': row.get('target_category'),
            'category': row.get('category'),
            'apply_start': str(row.get('apply_start') or ''),
            'apply_end': str(end or ''),
            'apply_period_type': row.get('apply_period_type'),
            'url': row.get('url') or row.get('apply_url') or '',
            'score': None if score is None else round(score, 4),
            'band': None if score is None else band(score),
            # 순위(전체 기준)와 표시 방식(T-C2 AnnouncementCard.rank·displayType)
            'rank': position,
            'display_type': 'card' if position <= CARD_COUNT else 'list',
            # 적합도(H, 잠정) — 이 요청이 쓴 검색 경로의 RRF 점수 ÷ 그 경로의 이론 최대값(모두 1위). 규칙으로 밀려도 값은 그대로다
            'fit_score': (round(min(1.0, rrf_score / fit_max), 3)
                          if rrf_score is not None and fit_max else None),
            'region': row.get('region') or '',
            # True 대상 지역 · False 다른 지역 전용 · None 판단 불가(공고에 지역이
            # 없거나 신청자가 고르지 않음). None 을 False 로 바꾸지 않는다.
            'region_match': region_mod.matches(row.get('region'), req.region),
            # True 내 시·군·구 · False 같은 시·도의 다른 시·군·구 · None 제목에 없음
            'district_match': region_mod.district_matches(row.get('title'), row.get('region'),
                                                          req.region, req.district),
            # 조율 요청서 3.1·3.2 (2026-10-06). 지문을 계산하지 못한 공고는 null.
            'content_version': STATE.get('content_versions', {}).get(nid),
        })
        # 신청자별 가산점(search/bonus.py, 03_bonus 3-3). 0 = 해당 가점 없음, null = 계산하지 못함
        results[-1]['bonus_score'], results[-1]['bonus_items'] = bonus_mod.score(STATE.get('bonus', {}).get(nid), req)
        hit = flags.get(nid, {})
        results[-1]['rules'] = {'groups': hit.get('groups') or [],
                                'off_region': bool(hit.get('region')),
                                'off_district': bool(hit.get('district')),
                                'off_industry': bool(hit.get('industry')),
                                'pre_founder_implied_no': bool(hit.get('pre_implied'))}
        if scored_mode:
            results[-1]['weighted_score'] = ranks.get(nid, {}).get('weighted_score')
        if hybrid_on:
            # 어느 검색이 이 공고를 찾았는지. 없으면 그 검색 상위 50 밖이다
            info = ranks.get(nid, {})
            results[-1].update({'dense_rank': info.get('dense_rank'),
                                'bm25_rank': info.get('bm25_rank'),
                                'rrf_score': info.get('rrf_score')})

    out = {'query': query, 'count': len(results),
           'encode_ms': round(encode_ms, 1), 'search_ms': round(search_ms, 2),
           'source': 'chroma+bm25' if hybrid_on else 'chroma', 'search': 'hybrid' if hybrid_on else 'dense',
           'demote_groups': req.demote_groups,
           'demoted': demoted, 'results': results,
           'region': req.region, 'demote_region': bool(req.demote_region and req.region),
           'region_demoted': region_demoted,
           'district': req.district,
           'demote_district': bool(req.demote_district and req.district and req.region),
           'district_demoted': district_demoted,
           # 업종 순위 신호. active 가 False 면 결과 파일이 없어 규칙이 꺼진 것이다.
           # section 이 None 이면 신청자 업종을 대분류 하나로 정할 수 없어 업종으로 순서를 바꾸지 않았다
           'industry': {'main_industry': req.main_industry, 'section': industry_section,
                        'demote_industry': bool(req.demote_industry),
                        'active': bool(industry_table.get('active')),
                        'source': industry_table.get('source'),
                        'notices_with_rule': len(industry_table.get('notices') or {})},
           'industry_demoted': industry_demoted,
           # 신청자 유형(G). 예비창업자 신청자일 때만 active. blocked 는 정형 필터에서 뺀 수, restored 는 본문 우선으로 되살린 수
           'applicant_types': {'active': use_types, 'source': types_table.get('source'),
                               'blocked': len(types_blocked), 'restored': len(types_restored),
                               'restored_examples': types_restored[:5],
                               'implied_demoted': sum(1 for f in flags.values() if f.get('pre_implied'))},
           # 무엇이 매칭에 쓰였고 무엇이 저장만 됐는지 화면에 그대로 보여 준다
           'weights': req.weights.model_dump(),
           'rule_words': applicant_mod.rule_words(req),
           'stored_only': applicant_mod.stored_only(req),
           'why_not_used': applicant_mod.why_not_used()}
    # 필터 → 검색 → 순위 통합 순서가 결과에 남는다(R-3). filtered_count 는 기능정의서 filteredCount
    out.update({'offset': offset, 'top': top, 'max_candidates': MAX_CANDIDATES,
                'has_more': offset + len(results) < min(len(candidates), MAX_CANDIDATES),
                # 대체 경로(E). fallback_mode: None | '임베딩단독' | 'BM25단독' | '마감임박순'
                'fallback_used': fallback_mode is not None, 'fallback_mode': fallback_mode,
                'search_errors': search_errors,
                'fit_basis': ('RRF ÷ 이론 최대값(%s, 잠정)' % ('두 검색 모두 1위' if fallback_mode is None and hybrid_on
                                                          else '사용한 검색 1위')) if fit_max else None,
                'depth': depth, 'search_rounds': 1,
                'filter': {'applied': bool(req.structured_filter), 'check_deadline': bool(req.hide_expired),
                           'total': len(STATE['rows']), 'excluded': excluded},
                'filtered_count': len(passed), 'dense_path': dense_path, 'dense_error': dense_error,
                # 실제로 돈 단계만 적는다. 통과 0건이면 검색·순위 통합을 하지 않는다
                'pipeline': ['정형 필터', '검색', '순위 통합'] if passed else ['정형 필터']})
    if hybrid_on:
        out.update({'dense_ms': round(dense_ms, 2), 'bm25_ms': round(bm25_ms, 2)})
    return out


MAX_CANDIDATES = 20     # 누적 최대 후보 수(T-C2 offset 0|10)
CARD_COUNT = 3          # 상위 3건은 카드, 나머지는 리스트


def _describe(exc, where):
    """검색 오류를 응답·stderr 에 남길 한 줄. 조용히 넘기지 않는다(E-C2-EMBED)."""
    text = '%s: %s' % (type(exc).__name__, (str(exc).splitlines() or [''])[0][:200])
    print('[match] %s 실패 — %s' % (where, text), file=sys.stderr)
    return {'where': where, 'error': text}


def _by_deadline(ids):
    """마감 임박순(둘 다 실패한 경우의 잠정 순서). 마감일 없는 공고는 뒤, 같으면 공고 ID 순."""
    def key(nid):
        end = STATE['rows'][nid].get('apply_end')
        return (end is None, str(end or ''), nid)
    return sorted(ids, key=key)


def _hybrid_depth():
    from search import hybrid
    return hybrid.DEPTH


def _dense_within(col, qv, ids, n):
    """의미 검색을 ids(정형 필터 통과 공고) 안에서만 한다. ([(공고 ID, 거리)] 가까운 순, 쓴 경로, 오류 설명).

    Chroma 의 query(ids=...) 로 후보를 좁힌다. 색인에 없는 ID 를 넘기면 Chroma 가 오류를 내므로
    boot() 가 기억한 색인 ID 와 겹치는 것만 넘긴다(로컬·EC2 모두 chromadb 1.5.9, ids 지원 확인 2026-09-28).

    경로 (Codex 검수 P2, 2026-09-28 — 호환성 문제와 색인 장애를 구분한다)
      'chroma'   정상
      'vectors'  ids 인자를 모르는 색인(평가용 NumpyCollection·옛 Chroma, TypeError)이다. 벡터를 꺼내 코사인을
                 직접 계산한다(벡터가 정규화돼 있어 결과 순서가 같다). 오류가 아니므로 설명은 None
      'vectors'  + 설명  그 밖의 Chroma 오류(타임아웃·색인 오류 등). 원인을 로그와 응답(dense_error)에 남기고
                 같은 방식으로 대신 계산한다. 대신 계산도 실패하면 예외를 그대로 올린다(폴백 E 는 별도 항목)
    """
    known = STATE.get('vector_ids')
    ids = [nid for nid in ids if known is None or nid in known]
    if not ids:
        return [], 'chroma', None
    error = None
    try:
        found = col.query(query_embeddings=[qv], ids=ids, n_results=min(n, len(ids)))
        return list(zip(found['ids'][0], found['distances'][0])), 'chroma', None
    except TypeError as exc:
        if 'ids' not in str(exc):
            error = '%s: %s' % (type(exc).__name__, str(exc).splitlines()[0][:200])
    except Exception as exc:
        error = '%s: %s' % (type(exc).__name__, str(exc).splitlines()[0][:200] if str(exc) else '')
    if error:
        print('경고: Chroma 필터 검색 실패 — 벡터 %d건을 직접 계산한다 (%s)' % (len(ids), error), file=sys.stderr)
    dist_of = {}
    _fill_distances(col, qv, ids, dist_of)
    return sorted(dist_of.items(), key=lambda x: (x[1], x[0]))[:n], 'vectors', error


def _fill_distances(col, qv, ids, dist_of):
    """Chroma 에서 공고 벡터를 꺼내 질의와의 코사인 거리(1 - 유사도)를 채운다.
    벡터는 정규화되어 있어 내적이 코사인이다. 색인에 없는 공고는 건너뛴다."""
    if not ids:
        return
    import numpy as np
    got = col.get(ids=ids, include=['embeddings'])
    q = np.asarray(qv, dtype='float32')
    for nid, vec in zip(got['ids'], got['embeddings']):
        dist_of[nid] = 1.0 - float(np.dot(q, np.asarray(vec, dtype='float32')))


@app.post('/api/match_compare')
def match_compare(req: MatchRequest):
    """기본 설정과 넘겨준 가중치를 **같은 질의로 나란히** 돌려준다.

    가중치를 시험할 때 눈으로 볼 것은 점수가 아니라 **순위가 어떻게 달라지는가** 다.
    그래서 양쪽 상위 목록과, 공고별로 몇 계단 움직였는지를 함께 싣는다.
    """
    req = _public(req)
    base = match(req.model_copy(update={'weights': Weights()}))
    tuned = match(req)

    rank_of = {r['notice_id']: i + 1 for i, r in enumerate(base['results'])}
    moved = []
    for i, r in enumerate(tuned['results'], 1):
        before = rank_of.get(r['notice_id'])
        moved.append({'notice_id': r['notice_id'], 'title': r['title'],
                      'rank_before': before, 'rank_after': i,
                      'moved': (before - i) if before else None,
                      'rules': r.get('rules'), 'score': r.get('score'),
                      'weighted_score': r.get('weighted_score')})
    same = [r['notice_id'] for r in tuned['results']] == [r['notice_id'] for r in base['results']]
    return {'query': base['query'], 'weights': req.weights.model_dump(),
            'identical': same, 'base': base['results'], 'tuned': tuned['results'],
            'moved': moved,
            'new_in_top': [m for m in moved if m['rank_before'] is None],
            'dropped': [r['title'] for r in base['results']
                        if r['notice_id'] not in {t['notice_id'] for t in tuned['results']}]}


@app.get('/weights', response_class=HTMLResponse)
def weights_page():
    with open(os.path.join(ROOT, 'web', 'weights.html'), encoding='utf-8') as f:
        return f.read()


@app.get('/api/form')
def form_options():
    """화면이 입력칸을 채울 때 쓰는 목록. 지역 어휘가 코드와 어긋나지 않게 서버가 준다."""
    labels = {'전남광주': '광주·전남'}
    return {
        'regions': [{'value': r, 'label': labels.get(r, r),
                     'districts': list(region_mod.districts_of(r))}
                    for r in region_mod.REGIONS],
        'certifications': list(applicant_mod.CERTIFICATIONS),
    }


@app.post('/api/eligibility')
def eligibility(req: GateRequest):
    row = STATE['rows'].get(req.notice_id)
    if row is None:
        return JSONResponse({'error': '공고를 찾을 수 없다'}, status_code=404)

    # 판정은 search/eligibility.py 한 곳에 있다(2026-10-06 옮김 — 조율 창구와 함께 쓴다). 내용은 그대로다
    from search import eligibility as eligibility_mod
    checks, _age_months = eligibility_mod.conditions(
        row, req.notice_id, req.applicant_type, req.founded_at,
        types_table=STATE.get('applicant_types') or {}, age_table=STATE.get('age_evidence'))

    return {
        'notice_id': req.notice_id,
        'title': row.get('title'),
        'url': row.get('url') or row.get('apply_url') or '',
        'passed': all(c['판정'] is not False for c in checks),
        'unknown': sum(1 for c in checks if c['판정'] is None),
        'checks': checks,
        'marks': {str(c['조건']): gate.mark(c['판정']) for c in checks},
        'deadline_days': gate.deadline_days(row),
    }


BANDS = {
    'all': (None, None),
    'under10m': (0, 10 ** 7),
    '10m_100m': (10 ** 7, 10 ** 8),
    '100m_1b': (10 ** 8, 10 ** 9),
    'over1b': (10 ** 9, None),
}


@app.get('/api/conditions')
def conditions(band: str = 'all', kind: str = 'amount', limit: int = 300):
    """LLM 추출 결과를 눈으로 검토하기 위한 조회.

    근거 문장(source_quote)을 함께 준다. 금액·형태가 맞는지는 근거를 봐야
    판단할 수 있다. 특히 '억' 단위 큰 금액은 숫자는 맞고 의미가 틀린 경우가
    있어(사업 총예산·매출 기준) 사람이 봐야 한다.
    """
    where = ['1=1']
    args = []
    if kind == 'amount':
        where.append('c.amount_max_won IS NOT NULL')
        low, high = BANDS.get(band, (None, None))
        if low is not None:
            where.append('c.amount_max_won >= %s')
            args.append(low)
        if high is not None:
            where.append('c.amount_max_won < %s')
            args.append(high)
    elif kind == 'type':
        where.append('JSON_LENGTH(c.business_type) > 0')
    elif kind == 'age_rejected':
        where.append('c.age_rejected IS NOT NULL')
    elif kind == 'corrected':
        where.append('c.amount_corrected IS NOT NULL')
    elif kind == 'age_kept':
        where.append('(c.age_years_max IS NOT NULL OR c.age_years_min IS NOT NULL)')

    sql = ("""SELECT c.notice_id, n.title, n.url, n.apply_url, n.source,
                     c.amount_max_won, c.business_type, c.pre_startup_allowed,
                     c.age_years_max, c.age_years_min, c.age_source_quote,
                     c.age_rejected, c.source_quote, c.amount_corrected, c.uncertain
                FROM notice_conditions c
                JOIN notices n ON n.notice_id = c.notice_id
               WHERE """ + ' AND '.join(where) +
           ' ORDER BY c.amount_max_won DESC, c.notice_id LIMIT %s')

    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(args) + (min(limit, 1000),))
            rows = cursor.fetchall()
            cursor.execute("""
                SELECT COUNT(*),
                       SUM(amount_max_won IS NOT NULL),
                       SUM(amount_max_won < 10000000),
                       SUM(amount_max_won >= 10000000 AND amount_max_won < 100000000),
                       SUM(amount_max_won >= 100000000 AND amount_max_won < 1000000000),
                       SUM(amount_max_won >= 1000000000),
                       SUM(JSON_LENGTH(business_type) > 0),
                       SUM(age_rejected IS NOT NULL),
                       SUM(amount_corrected IS NOT NULL),
                       SUM(age_years_max IS NOT NULL OR age_years_min IS NOT NULL)
                  FROM notice_conditions""")
            s = cursor.fetchone()
    finally:
        connection.close()

    keys = ('notice_id', 'title', 'url', 'apply_url', 'source', 'amount_max_won',
            'business_type', 'pre_startup_allowed', 'age_years_max', 'age_years_min',
            'age_source_quote', 'age_rejected', 'source_quote', 'amount_corrected',
            'uncertain')
    out = []
    for row in rows:
        item = dict(zip(keys, row))
        for key in ('business_type', 'amount_corrected', 'uncertain'):
            if isinstance(item[key], str):
                try:
                    item[key] = json.loads(item[key])
                except ValueError:
                    pass
        item['url'] = item['url'] or item['apply_url'] or ''
        out.append(item)

    labels = ('total', 'amount', 'under10m', '10m_100m', '100m_1b', 'over1b',
              'type', 'age_rejected', 'corrected', 'age_kept')
    return {'stats': {k: int(v or 0) for k, v in zip(labels, s)},
            'count': len(out), 'rows': out}


@app.get('/review', response_class=HTMLResponse)
def review():
    with open(os.path.join(ROOT, 'web', 'review.html'), encoding='utf-8') as f:
        return f.read()


@app.get('/api/health')
def health():
    col = STATE.get('collection')
    try:
        indexed = col.count() if col is not None else None
    except Exception:
        indexed = None
    types = STATE.get('applicant_types') or {}
    return {'indexed': indexed, 'boot_errors': STATE.get('boot_errors') or {},
            'notices': len(STATE['rows']),
            'bm25_indexed': len(STATE['bm25']) if STATE.get('bm25') else 0,
            'on_ec2': ON_EC2, 'source': 'chroma+bm25', 'default_search': 'hybrid',
            # 신청자 유형 판정의 신선도(2026-09-29 — Codex 재검수: 실행 중 상태를 볼 곳이 없었다)
            'applicant_types': {'active': bool(types.get('active')), 'source': types.get('source'),
                                'used': len(types.get('notices') or {}),
                                'fresh_from_db': types.get('fresh_from_db'),
                                'refreshed_from_file': types.get('refreshed_from_file'),
                                'stale': types.get('stale'), 'bad_lines': types.get('bad_lines'),
                                # 발췌 밖 원문에 예비창업 언급이 있어 불가 → 확인 필요로 낮춘 공고 수(Codex 재검수 P1-2)
                                'unread_pre_founder': types.get('unread_pre_founder'),
                                'unverified_pre_founder': types.get('unverified_pre_founder'),
                                'error': types.get('error')}}


# ── 리랭커 시연 (내부 검토용) ────────────────────────────────
# 서비스 경로가 아니다. 학습한 리랭커가 검색 결과의 순서를 어떻게 바꾸는지,
# 그리고 그 대가로 얼마나 느려지는지를 눈으로 보기 위한 화면이다.
# 모델은 처음 요청할 때 한 번만 올린다(수십 초). GPU 가 없으면 매우 느리다.

def _scorer():
    if STATE.get('scorer') is None:
        sys.path.insert(0, os.path.join(ROOT, 'ml'))
        import rerank_common as rc
        adapter = rc.ADAPTER_DIR if os.path.exists(rc.ADAPTER_DIR) else None
        STATE['scorer'] = rc.Scorer(adapter=adapter)
        STATE['scorer_kind'] = '학습한 모델' if adapter else '사전학습(학습 전)'
        STATE['notice_text'] = rc.notice_text
    return STATE['scorer']


@app.post('/api/match_rerank')
def match_rerank(req: MatchRequest):
    """검색만 한 결과와 리랭커를 얹은 결과를 **둘 다** 돌려준다."""
    req = _public(req)
    base = match(req.model_copy(update={'top': 30, 'demote_groups': False}))
    before = base['results']
    if not before:
        return {'query': base['query'], 'before': [], 'after': [], 'ready': False,
                'message': '후보가 없다'}

    try:
        scorer = _scorer()
    except Exception as exc:                      # 모델이 없거나 못 올릴 때
        return {'query': base['query'], 'before': before[:req.top], 'after': [],
                'ready': False, 'message': '리랭커를 올리지 못했다: %s' % exc}

    from shared import store_mysql  # noqa: F401  (load_notices 가 쓴다)
    sys.path.insert(0, os.path.join(ROOT, 'eval'))
    import common

    ids = [r['notice_id'] for r in before]
    notices = common.load_notices(ids, with_attachment=False)
    texts = [STATE['notice_text'](notices[n]) if n in notices else '' for n in ids]

    t0 = time.time()
    scores = scorer.score(base['query'], texts)
    rerank_ms = (time.time() - t0) * 1000

    rank_before = {r['notice_id']: i + 1 for i, r in enumerate(before)}
    by_id = {r['notice_id']: r for r in before}
    ordered = sorted(zip(ids, scores), key=lambda x: -x[1])

    after = []
    for pos, (nid, sc) in enumerate(ordered[:req.top], 1):
        row = dict(by_id[nid])
        row['rerank_score'] = round(float(sc), 4)
        row['rank_before'] = rank_before[nid]
        row['moved'] = rank_before[nid] - pos
        after.append(row)

    return {'query': base['query'], 'ready': True,
            'before': before[:req.top], 'after': after,
            'pool': len(before), 'model': STATE.get('scorer_kind'),
            'device': scorer.device,
            'encode_ms': base['encode_ms'], 'search_ms': base['search_ms'],
            'rerank_ms': round(rerank_ms, 0)}


@app.get('/demo', response_class=HTMLResponse)
def demo():
    with open(os.path.join(ROOT, 'web', 'demo.html'), encoding='utf-8') as f:
        return f.read()


# ── 업력 분류기 시연 (내부 검토용) ───────────────────────────
# 규칙(extract_conditions.py)과 학습한 분류기가 같은 문장을 어떻게 판단하는지
# 나란히 보여준다. 규칙은 지금 서비스가 쓰는 것이고, 분류기는 아직 미연결이다.

ABSTAIN = (0.35, 0.65)


class ClassifyRequest(BaseModel):
    text: str


def _classifier():
    if STATE.get('clf') is None:
        import joblib
        path = os.path.join(ROOT, 'ml', 'models', 'age_classifier_v2.joblib')
        if not os.path.exists(path):
            raise FileNotFoundError('학습한 분류기가 없다: %s' % path)
        STATE['clf'] = joblib.load(path)
    return STATE['clf']


def _rule_verdict(quote):
    """extract_conditions.py 의 검산 규칙을 그대로 적용해 본다."""
    # 10단계와 같은 함수를 쓴다(2026-09-28 Codex 검수 P3 — 따로 적어 두어 새 검사가 빠졌었다)
    from collect import extract_conditions as ec
    problem = ec.age_quote_problem(quote)
    return (False, problem) if problem else (True, '업력 근거로 인정')


@app.post('/api/classify')
def classify(req: ClassifyRequest):
    """한 문장에 대해 규칙과 모델의 판단을 둘 다 돌려준다."""
    text = ' '.join(req.text.split())
    rule_ok, rule_why = _rule_verdict(text)
    out = {'text': text, 'rule': rule_ok, 'rule_why': rule_why}
    try:
        bundle = _classifier()
    except Exception as exc:
        out.update({'ready': False, 'message': str(exc)})
        return out

    proba = float(bundle['model'].predict_proba([text])[0][1])
    low, high = ABSTAIN
    verdict = 'hold' if low <= proba <= high else ('age' if proba > high else 'not')
    out.update({'ready': True, 'proba': round(proba, 4), 'verdict': verdict,
                'abstain': list(ABSTAIN), 'exp': bundle.get('exp'),
                'agree': (verdict == 'age') == rule_ok if verdict != 'hold' else None})
    return out


@app.get('/api/classify/samples')
def classify_samples(limit: int = 24):
    """실제 공고에서 뽑힌 업력 근거 문장. 규칙이 버린 것을 앞에 둔다."""
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT age_source_quote, age_years_max, age_rejected '
                '  FROM notice_conditions '
                " WHERE age_source_quote IS NOT NULL AND age_source_quote <> '' "
                ' ORDER BY age_rejected IS NULL, CHAR_LENGTH(age_source_quote) '
                ' LIMIT %s', (limit,))
            rows = cursor.fetchall()
    finally:
        connection.close()
    return {'samples': [{'text': ' '.join(str(q).split()),
                         'kept': y is not None,
                         'rejected': r} for q, y, r in rows]}


@app.get('/classify', response_class=HTMLResponse)
def classify_page():
    with open(os.path.join(ROOT, 'web', 'classify.html'), encoding='utf-8') as f:
        return f.read()


@app.get('/', response_class=HTMLResponse)
def index():
    with open(os.path.join(ROOT, 'web', 'app.html'), encoding='utf-8') as f:
        return f.read()


def main():
    import uvicorn
    boot()
    host = '0.0.0.0' if ON_EC2 else '127.0.0.1'
    port = int(os.environ.get('PORT', '8000'))
    print('\n열기: http://%s:%d' % ('43.201.90.238' if ON_EC2 else '127.0.0.1', port))
    uvicorn.run(app, host=host, port=port, log_level='warning')


if __name__ == '__main__':
    main()
