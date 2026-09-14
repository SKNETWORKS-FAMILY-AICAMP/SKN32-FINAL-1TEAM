# -*- coding: utf-8 -*-
"""공고 매칭 시험용 웹 화면. 로그인 없음.

  .venv/bin/python app.py                 EC2 에서 (0.0.0.0:8000)
  .\.venv\Scripts\python.exe app.py       내 PC 에서 (127.0.0.1:8000)

브라우저에서 열면 입력 → 공고 3건 → 클릭하면 자격요건 3항목이 나온다.

**검색은 반드시 벡터 DB(Chroma) 를 거친다.** MySQL 의 embedding 을 직접 읽어
계산하는 경로는 쓰지 않는다. MySQL 은 제목·기관·기간 같은 표시용 값과
자격 판정용 필드를 가져오는 데만 쓴다.

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

import gate

HERE = os.path.dirname(os.path.abspath(__file__))
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
        import ec2_vecstore
        return ec2_vecstore.connect()
    import store_mysql
    return store_mysql.connect()


def _collection():
    """벡터 DB. EC2 와 로컬 모두 Chroma 다."""
    if ON_EC2:
        import ec2_vecstore
        col = ec2_vecstore.open_store(create=False)
        if col is None:
            raise SystemExit('Chroma 색인이 없다. ec2_vecstore.py 를 먼저 돌린다.')
        return col
    import vecstore
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
    import vecstore
    return np.asarray(vecstore.embed_query(text), dtype='float32').tolist()


def boot():
    started = time.time()
    STATE['collection'] = _collection()
    print('벡터 DB 색인 %d건' % STATE['collection'].count())

    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT ' + ','.join(FIELDS) + ' FROM notices')
            STATE['rows'] = {r[0]: dict(zip(FIELDS, r)) for r in cursor.fetchall()}
    finally:
        connection.close()
    print('공고 정보 %d건' % len(STATE['rows']))

    if ON_EC2:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer('BAAI/bge-m3')
        model.max_seq_length = 512
        STATE['model'] = model

    # 첫 질의가 20초 걸린다. 첫 사용자가 그걸 기다리지 않게 미리 털어낸다.
    print('워밍업...')
    _encode('워밍업')
    print('준비 완료 · %.1f초' % (time.time() - started))


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


class MatchRequest(BaseModel):
    applicant_type: str
    owner_name: str = ''
    founded_at: str = ''
    idea: str
    team: list[TeamMember] = []
    revenue: list[RevenueItem] = []
    top: int = 3
    hide_expired: bool = True


class GateRequest(BaseModel):
    notice_id: str
    applicant_type: str
    founded_at: str = ''


# ── API ─────────────────────────────────────────────────────
@app.post('/api/match')
def match(req: MatchRequest):
    query = build_query(req)
    t0 = time.time()
    qv = _encode(query)
    encode_ms = (time.time() - t0) * 1000

    t0 = time.time()
    want = req.top * 8 if req.hide_expired else req.top + 1
    col = STATE['collection']
    found = col.query(query_embeddings=[qv], n_results=min(want, col.count()))
    search_ms = (time.time() - t0) * 1000

    today = date.today().isoformat()
    results = []
    for nid, dist in zip(found['ids'][0], found['distances'][0]):
        if nid == '__watermark__':
            continue
        row = STATE['rows'].get(nid)
        if row is None:
            continue
        end = row.get('apply_end')
        if req.hide_expired and end is not None and str(end) < today:
            continue
        score = 1.0 - dist
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
            'score': round(score, 4),
            'band': band(score),
        })
        if len(results) >= req.top:
            break

    return {'query': query, 'count': len(results),
            'encode_ms': round(encode_ms, 1), 'search_ms': round(search_ms, 2),
            'source': 'chroma', 'results': results}


@app.post('/api/eligibility')
def eligibility(req: GateRequest):
    row = STATE['rows'].get(req.notice_id)
    if row is None:
        return JSONResponse({'error': '공고를 찾을 수 없다'}, status_code=404)

    months = (None if req.applicant_type == '예비창업자'
              else gate.business_age_months(req.founded_at))
    verdict = gate.judge(row, months)

    # gate.py 는 업력·접수기간·모집상태를 본다. 화면이 요구하는 '지원대상 유형'
    # 은 개인/법인 구분 데이터가 DB 에 없어 판정하지 않고 '확인 필요' 로 둔다.
    # 여기서 임의로 통과시키면 자격을 확인받은 것으로 읽힌다.
    checks = [{
        '조건': '지원대상 유형',
        '요구': row.get('target_category') or '지원대상 정보 없음',
        '내 값': req.applicant_type,
        '판정': None,
        '설명': '개인사업자·법인 구분 정보가 공고 데이터에 없습니다. 원문을 확인하세요.',
    }] + verdict['checks']

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
    with open(os.path.join(HERE, 'review.html'), encoding='utf-8') as f:
        return f.read()


@app.get('/api/health')
def health():
    return {'indexed': STATE['collection'].count(),
            'notices': len(STATE['rows']),
            'on_ec2': ON_EC2, 'source': 'chroma'}


@app.get('/', response_class=HTMLResponse)
def index():
    with open(os.path.join(HERE, 'app.html'), encoding='utf-8') as f:
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
