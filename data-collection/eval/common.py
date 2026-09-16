# -*- coding: utf-8 -*-
"""평가셋 공용 — 경로 · JSONL 입출력 · 질의 문장 · 공고 표시 텍스트.

평가셋 파일 (전부 이 폴더, git 에 커밋한다)

  queries.jsonl         질의. /api/match 의 MatchRequest 모양 그대로
  pool.jsonl            질의별 판정 후보 (build_pool.py)
  pool_meta.json        후보를 뽑은 시점·설정
  llm_judgments.jsonl   LLM 1차 판정 (judge_llm.py)
  human_judgments.jsonl 사람 판정 (label_app.py) — 블라인드·검수 모두
  qrels.jsonl           최종 판정 (merge_qrels.py). 사람 > LLM 순으로 채택
"""
import json
import os
import random
import sys

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(EVAL_DIR)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

QUERIES = os.path.join(EVAL_DIR, 'queries.jsonl')
POOL = os.path.join(EVAL_DIR, 'pool.jsonl')
POOL_META = os.path.join(EVAL_DIR, 'pool_meta.json')
LLM = os.path.join(EVAL_DIR, 'llm_judgments.jsonl')
HUMAN = os.path.join(EVAL_DIR, 'human_judgments.jsonl')
QRELS = os.path.join(EVAL_DIR, 'qrels.jsonl')
# 판정 시점 공고 내용. 판정·검수·평가가 같은 내용을 보게 한다. 용량 때문에 git 제외.
SNAPSHOT = os.path.join(EVAL_DIR, 'snapshot', 'pool_notices.jsonl')
RUNS = os.path.join(EVAL_DIR, 'runs')


def load_snapshot():
    return {n['notice_id']: n for n in read_jsonl(SNAPSHOT)}

# 블라인드 표본 크기. 사람이 LLM 답을 보지 않고 판정해 일치율을 잰다.
BLIND_SIZE = 150
BLIND_SEED = 20260915


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def append_jsonl(path, rows):
    with open(path, 'a', encoding='utf-8', newline='\n') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')


def write_jsonl(path, rows):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    os.replace(tmp, path)


# topic-v1 → v2 (2026-09-15, 블라인드 150쌍 뒤 판정자 확인)
#   · 특정 대상 집단 한정(장애인·제대군인 등)에 신청자가 해당하지 않으면 0
#   · 분야 키워드만 겹치는 범용 프로그램(교육·경진대회·데모데이)은 1
#   · 업종 무관 + 필요 정확히 일치는 1/2 사례별, 경계 사례로 표시
LABEL_VERSION = 'topic-v2'
KINDS = ('normal', 'negative')
APPLICANT_TYPES = ('예비창업자', '개인사업자', '법인')


def validate_queries(rows):
    """스키마 검사. 틀린 것을 모아 한 번에 보고한다."""
    from datetime import date
    errors, seen = [], set()
    for i, q in enumerate(rows, 1):
        where = '%d행 %s' % (i, q.get('qid'))
        for key in ('qid', 'scenario_group', 'category', 'kind', 'as_of_date', 'payload'):
            if key not in q:
                errors.append('%s: %s 없음' % (where, key))
        if q.get('qid') in seen:
            errors.append('%s: qid 중복' % where)
        seen.add(q.get('qid'))
        if q.get('kind') not in KINDS:
            errors.append('%s: kind=%r' % (where, q.get('kind')))
        p = q.get('payload') or {}
        if p.get('applicant_type') not in APPLICANT_TYPES:
            errors.append('%s: applicant_type=%r' % (where, p.get('applicant_type')))
        if not (p.get('idea') or '').strip():
            errors.append('%s: idea 비어 있음' % where)
        try:
            date.fromisoformat(q.get('as_of_date', ''))
            if p.get('founded_at'):
                date.fromisoformat(p['founded_at'])
        except ValueError as exc:
            errors.append('%s: 날짜 %s' % (where, exc))
    return errors


def load_queries():
    rows = read_jsonl(QUERIES)
    errors = validate_queries(rows)
    if errors:
        raise SystemExit('queries.jsonl 오류\n  ' + '\n  '.join(errors))
    return {q['qid']: q for q in rows}


def query_text(q):
    """app.build_query 를 그대로 쓰되 업력 계산 기준일을 `as_of_date` 로 고정한다.

    build_query 는 오늘 날짜로 '창업 N년차' 를 만든다. 평가 질의가 날마다 바뀌지
    않도록 gate.business_age_months 의 기본 날짜만 이 호출 동안 바꾼다.
    app.py 는 고치지 않는다.
    """
    from datetime import date
    import app
    import gate
    original = gate.business_age_months
    as_of = date.fromisoformat(q['as_of_date'])
    gate.business_age_months = lambda founded, today=None: original(founded, today or as_of)
    try:
        return app.build_query(app.MatchRequest(**q['payload']))
    finally:
        gate.business_age_months = original


def persona_text(payload):
    """판정자(LLM·사람)에게 보여줄 신청자 설명. 검색용 질의 문장과 별개다."""
    lines = ['신청자 유형: %s' % payload.get('applicant_type', '')]
    if payload.get('founded_at'):
        lines.append('설립일자: %s' % payload['founded_at'])
    lines.append('사업 아이디어: %s' % payload.get('idea', ''))
    items = [r.get('item', '') for r in payload.get('revenue') or [] if r.get('item')]
    if items:
        lines.append('수익모델: %s' % ', '.join(items))
    careers = [m.get('career', '') for m in payload.get('team') or [] if m.get('career')]
    if careers:
        lines.append('팀 경력: %s' % ', '.join(careers))
    return '\n'.join(lines)


NOTICE_FIELDS = ('notice_id', 'title', 'body', 'target_text', 'target_category',
                 'category', 'subcategory', 'organizer', 'supervising_org',
                 'executing_org', 'region', 'apply_end', 'url', 'apply_url')

ATTACH_CHARS = 1200


def load_notices(ids=None, with_attachment=True):
    """{notice_id: dict}. 첨부 공고문 본문 앞부분을 `attachment_excerpt` 로 붙인다.

    GROUP_CONCAT 을 쓰지 않는다 — 1024바이트에서 조용히 잘린다(HANDOFF 10절).
    첨부는 행별로 받아 파이썬에서 고른다.
    """
    import store_mysql
    connection = store_mysql.connect()
    try:
        with connection.cursor() as cursor:
            sql = 'SELECT id,' + ','.join(NOTICE_FIELDS) + ' FROM notices'
            args = ()
            if ids is not None:
                ids = list(ids)
                if not ids:
                    return {}
                sql += ' WHERE notice_id IN (' + ','.join(['%s'] * len(ids)) + ')'
                args = tuple(ids)
            cursor.execute(sql, args)
            rows = {}
            by_fk = {}
            for r in cursor.fetchall():
                item = dict(zip(NOTICE_FIELDS, r[1:]))
                item['apply_end'] = str(item['apply_end'] or '')
                rows[item['notice_id']] = item
                by_fk[r[0]] = item
            if with_attachment and by_fk:
                fks = list(by_fk)
                for i in range(0, len(fks), 500):
                    chunk = fks[i:i + 500]
                    cursor.execute(
                        'SELECT a.notice_fk, a.role, t.extracted_text '
                        '  FROM notice_attachments a '
                        '  JOIN attachment_texts t ON t.attachment_fk = a.id '
                        ' WHERE a.active AND t.extracted_text IS NOT NULL '
                        '   AND a.notice_fk IN (' + ','.join(['%s'] * len(chunk)) + ') '
                        ' ORDER BY a.notice_fk, a.role = \'notice\' DESC, t.text_chars DESC',
                        tuple(chunk))
                    for fk, role, text in cursor.fetchall():
                        item = by_fk[fk]
                        if 'attachment_excerpt' not in item:
                            item['attachment_excerpt'] = ' '.join((text or '').split())[:ATTACH_CHARS]
    finally:
        connection.close()
    return rows


def notice_text(n, attachment=True):
    """판정용 공고 설명. 자격(지역·마감)이 아니라 주제를 보게 하려는 것이라
    지역·마감일은 넣지 않는다."""
    org = n.get('organizer') or n.get('supervising_org') or n.get('executing_org') or ''
    lines = ['제목: %s' % (n.get('title') or '')]
    if org:
        lines.append('기관: %s' % org)
    cat = ' / '.join(x for x in (n.get('category'), n.get('subcategory')) if x)
    if cat:
        lines.append('분류: %s' % cat)
    if n.get('target_category'):
        lines.append('지원대상 분류: %s' % n['target_category'])
    if n.get('body'):
        lines.append('사업개요: %s' % ' '.join(n['body'].split())[:1500])
    if n.get('target_text'):
        lines.append('지원대상: %s' % ' '.join(n['target_text'].split())[:600])
    if attachment and n.get('attachment_excerpt'):
        lines.append('첨부 공고문 앞부분: %s' % n['attachment_excerpt'])
    return '\n'.join(lines)


RECHECK = os.path.join(EVAL_DIR, 'recheck.json')


def recheck_sample(blind_human, llm_a):
    """기준을 바꾼 뒤 사람이 블라인드 판정을 새 기준으로 다시 볼 쌍.

    LLM 과 갈린 쌍만 다시 보게 하면 사람이 LLM 쪽으로 옮겨 가는 기회만 생겨 일치율이
    부풀려진다. 그래서 **일치한 쌍도 갈린 쌍의 절반만큼 무작위로 섞는다.** 화면에는
    LLM 답을 보여주지 않고, 어느 쪽 표본인지도 알려주지 않는다.

    blind_human: {(qid, nid): rel}   llm_a: {(qid, nid): rel}
    """
    rng = random.Random(BLIND_SEED + 2)
    keys = sorted(k for k, v in blind_human.items() if v is not None and k in llm_a)
    differ = [k for k in keys if blind_human[k] != llm_a[k]]
    agree = [k for k in keys if blind_human[k] == llm_a[k]]
    rng.shuffle(agree)
    picked = differ + agree[:max(1, len(differ) // 2)]
    return {'created': __import__('datetime').date.today().isoformat(),
            'label_version': LABEL_VERSION, 'differ': len(differ),
            'agree_sampled': len(picked) - len(differ),
            'pairs': [list(k) for k in sorted(picked)]}


def blind_sample(pool_rows):
    """블라인드 표본. LLM 결과와 무관하게 뽑아야 한다(아니면 표본이 기울어진다).

    무관 질의 제외 · 검색 순위 구간(상위 3 / 4~10 / 그 밖)별로 고르게.
    """
    rng = random.Random(BLIND_SEED)
    normal = [p for p in pool_rows if not p['qid'].startswith('n')]
    buckets = {'top3': [], 'top10': [], 'rest': []}
    for p in normal:
        r = p.get('dense_rank')
        key = 'top3' if r and r <= 3 else 'top10' if r and r <= 10 else 'rest'
        buckets[key].append(p)
    picked = []
    share = {'top3': 0.4, 'top10': 0.3, 'rest': 0.3}
    for key, items in buckets.items():
        items = sorted(items, key=lambda p: (p['qid'], p['notice_id']))
        rng.shuffle(items)
        picked += items[:round(BLIND_SIZE * share[key])]
    return {(p['qid'], p['notice_id']) for p in picked}
