# -*- coding: utf-8 -*-
"""공고 내용 지문(content_version) — 공고 내용이 바뀔 때만 바뀌는 문자열 (2026-10-06, 조율 요청서 3.1).

조율 쪽은 추가 조회 때 같은 공고의 두 값이 **같은지만** 비교해 "내용 바뀜"을 붙인다.
그래서 매일 수집할 때마다 바뀌는 값이 들어가면 안 된다. 그런 값이 섞이면 내용이 그대로인 공고도
매일 "내용 바뀜"이 된다.

넣는 것 (공고 원문에서 온 값만)
  notices      CONTENT_FIELDS — 제목·본문·지원대상·제외·업력 칸·지역·분류·기관·접수기간(원본 포함)·모집 상태·링크
  첨부         공고에 **지금 달린**(notice_attachments.active) 첨부 파일의 **파일 바이트 SHA-256**(attachment_texts.content_sha256)
               — 추출한 글자가 아니라 파일 자체의 지문이다. 추출기를 바꿔도 지문은 그대로다.
               첨부가 빠지거나 바뀌면(active=FALSE) 지문도 바뀐다(cv2, 2026-10-06 Codex 검수 P2-5 — cv1 은 빠진 첨부도 넣었다)

넣지 않는 것
  수집 시각·행 수정 시각(snapshot_at·updated_at·last_import_id·created_at), API 수정 시각(source_updated_at_raw),
  정규화 경고(issues), 원본 행 전체(raw — 수집 때마다 붙는 값이 섞일 수 있다),
  LLM 이 뽑은 값(notice_conditions·판정표·가점) — 추출기를 바꿔 다시 뽑으면 내용이 그대로여도 달라진다.
  원문(본문·첨부 파일)이 지문에 들어 있으므로 원문이 바뀌면 지문도 바뀐다.

값 모양  'cv2-' + SHA-256 앞 32자(cv1 은 10/6 하루 쓴 첫 판). 만드는 방식을 바꾸면 접두어를 올린다(모든 공고 값이 함께 바뀐다).
읽기 전용이다. DB 에 쓰지 않는다.
"""
import hashlib
import json
from datetime import date, datetime

PREFIX = 'cv2-'
CONTENT_FIELDS = ('title', 'body', 'target_text', 'target_category', 'exclude_text', 'age_condition_raw',
                  'region', 'category', 'subcategory', 'organizer', 'supervising_org', 'executing_org',
                  'apply_start', 'apply_end', 'apply_period_raw', 'apply_period_type', 'recruitment_status',
                  'url', 'apply_url')


def _plain(name, value):
    """DB 값을 비교 가능한 값으로. 날짜는 ISO 문자열, JSON 칸은 키 순서를 고정해 다시 쓴다."""
    if isinstance(value, (bytes, bytearray)):
        value = value.decode('utf-8')
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if name == 'apply_period_raw' and isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def compute(row, attachment_hashes=()):
    """공고 한 건의 지문. row 는 CONTENT_FIELDS 를 키로 가진 dict, attachment_hashes 는 첨부 파일 SHA-256 목록.

    첨부 순서가 바뀌어도 같은 값이 나오게 정렬한다. 비어 있는 첨부 지문(None)은 넣지 않는다.
    """
    payload = {name: _plain(name, row.get(name)) for name in CONTENT_FIELDS}
    payload['attachments'] = sorted(h for h in attachment_hashes if h)
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)
    return PREFIX + hashlib.sha256(text.encode('utf-8')).hexdigest()[:32]


def load(connection):
    """{notice_id: content_version} — 모든 공고. SELECT 만 한다(2,765건 약 0.2초, 2026-10-06)."""
    return snapshot(connection)['versions']


# ── 하루 뒤 비교 (지문이 수집 잡음 없이 내용 변경에만 바뀌는지 확인) ──────────────
def _short(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
                          .encode('utf-8')).hexdigest()[:12]


def snapshot(connection):
    """{'versions': {id: 지문}, 'field_hashes': {id: {칸: 짧은 지문}}} — 어느 칸이 바뀌었는지 볼 수 있게 칸별로도 남긴다."""
    columns = ('id', 'notice_id') + CONTENT_FIELDS
    with connection.cursor() as cursor:
        cursor.execute('SELECT ' + ','.join(columns) + ' FROM notices')
        rows = [dict(zip(columns, r)) for r in cursor.fetchall()]
        cursor.execute('SELECT a.notice_fk, t.content_sha256 FROM notice_attachments a '
                       'JOIN attachment_texts t ON t.attachment_fk = a.id WHERE a.active AND t.content_sha256 IS NOT NULL')
        hashes = {}
        for notice_fk, sha in cursor.fetchall():
            hashes.setdefault(notice_fk, []).append(sha.decode('ascii') if isinstance(sha, bytes) else sha)
    versions, fields = {}, {}
    for r in rows:
        files = sorted(h for h in hashes.get(r['id'], ()) if h)
        versions[r['notice_id']] = compute(r, files)
        fields[r['notice_id']] = dict({f: _short(_plain(f, r.get(f))) for f in CONTENT_FIELDS}, attachments=_short(files))
    return {'prefix': PREFIX, 'count': len(versions), 'versions': versions, 'field_hashes': fields}


def compare(old, new):
    """두 스냅샷 → 바뀐 공고 수와 칸별 바뀐 수. 두 날 모두 있는 공고만 본다."""
    common = set(old['versions']) & set(new['versions'])
    changed = sorted(n for n in common if old['versions'][n] != new['versions'][n])
    by_field = {}
    for n in changed:
        for f, h in new['field_hashes'][n].items():
            if old['field_hashes'][n].get(f) != h:
                by_field.setdefault(f, []).append(n)
    return {'common': len(common), 'changed': len(changed),
            'added': len(set(new['versions']) - set(old['versions'])),
            'removed': len(set(old['versions']) - set(new['versions'])),
            'by_field': {f: {'count': len(ids), 'examples': ids[:5]} for f, ids in sorted(by_field.items())}}


if __name__ == '__main__':
    # python -m search.content_version --save data/notice_api/content_version_YYYYMMDD.json
    # python -m search.content_version --compare data/notice_api/content_version_20261006_cv2.json
    import argparse
    import io
    from datetime import timezone
    from shared import store_mysql
    parser = argparse.ArgumentParser(description='공고 내용 지문 저장·비교 (DB 읽기만)')
    parser.add_argument('--save', help='지금 지문을 이 파일에 저장한다')
    parser.add_argument('--compare', help='이 파일(이전 스냅샷)과 지금을 비교한다')
    args = parser.parse_args()
    conn = store_mysql.connect()
    try:
        from search import collection_status
        store_at = collection_status.read_latest_store(conn)[0]
        now_snap = snapshot(conn)
    finally:
        conn.close()
    now_snap.update({'made_at': datetime.now(timezone.utc).isoformat(),
                     'store_at': store_at.isoformat() if store_at else None})
    if args.save:
        with io.open(args.save, 'w', encoding='utf-8') as f:
            json.dump(now_snap, f, ensure_ascii=False, sort_keys=True)
        print('저장 %d건 → %s (저장 시각 %s)' % (now_snap['count'], args.save, now_snap['store_at']))
    if args.compare:
        with io.open(args.compare, encoding='utf-8') as f:
            before = json.load(f)
        print('이전 저장 시각 %s → 지금 %s' % (before.get('store_at'), now_snap['store_at']))
        print(json.dumps(compare(before, now_snap), ensure_ascii=False, indent=1))
