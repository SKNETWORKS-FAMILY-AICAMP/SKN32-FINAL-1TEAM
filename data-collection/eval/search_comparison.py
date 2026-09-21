# -*- coding: utf-8 -*-
"""임베딩 단독(dense)과 하이브리드(hybrid) 검색을 같은 입력으로 비교한다.

  python -X utf8 eval/search_comparison.py --plan    선정한 입력과 실행 계획만
  python -X utf8 eval/search_comparison.py           40개 응답 수집 + 결과물 생성
  python -X utf8 eval/search_comparison.py --check-only   Chroma 실제 벡터 정합성만 검사 (검색 없음)

지시서: docs/SEARCH_COMPARISON_TASK_20260918.md

이 파일은 **얇은 실행 도구**다. 검색·규칙은 서비스(`search/app.py`)의 함수를 그대로 부르고
여기서 다시 구현하지 않는다. 서비스 코드·가중치는 건드리지 않는다.

단계
  A  후처리를 모두 끈 상태 — 검색 방식 자체의 차이를 본다
  B  현재 서비스와 같은 조건 — 사용자에게 실제로 보이는 결과를 본다

각 단계에서 `search` 만 dense/hybrid 로 바꾼다. 10입력 × 2단계 × 2방식 = 40개 응답.
"""
import argparse
import csv
import hashlib
import html
import io
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
from search import app  # noqa: E402
from shared import region as region_mod  # noqa: E402

ROOT = common.ROOT
REPORTS = os.path.join(ROOT, 'reports')

# ── 입력 선정 규칙 ───────────────────────────────────────────
# 결과를 보기 **전에** 규칙으로 고른다. 분야를 흩어 놓고, 각 분야에서 qid 가 가장 빠른 질의를
# 하나씩 집는다. 무관 질의 2개도 같은 방식으로 앞에서 둘을 집는다.
CATEGORIES = ('제조', 'IT·SW', '외식·소상공인', '콘텐츠', '수출',
              '농식품', '환경·에너지', '사회적경제')

# 질의 파일에는 소재지가 없다. 지역·시·군·구 규칙이 실제로 걸리는 사례를 보려면 보완해야 한다.
# **가상 신청자 정보**이며 원본 질의 파일은 바꾸지 않는다. 어느 입력에 무엇을 더했는지 남긴다.
SUPPLEMENT = {
    '제조': {'region': '경기', 'district': '수원시'},
    '외식·소상공인': {'region': '전남광주', 'district': '목포시'},
    'IT·SW': {'region': '서울', 'district': '강남구'},
}

STAGES = {
    'A': {'hide_expired': False, 'demote_groups': False,
          'demote_region': False, 'demote_district': False},
    'B': {'hide_expired': True, 'demote_groups': True,
          'demote_region': True, 'demote_district': True},
}
TOP = 5


def sha(text):
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()


def git_info():
    def run(*args, keep_spaces=False):
        """keep_spaces 면 앞 공백을 지우지 않는다.

        `git status --short` 는 첫 두 칸이 상태 표시라 `.strip()` 을 걸면 첫 줄의
        선행 공백이 사라지고 경로가 한 글자 잘린다(' M docs/STATUS.md' → 'ocs/STATUS.md').
        2026-09-18 Codex 리뷰 3번에서 지적된 실제 사례다.
        """
        try:
            out = subprocess.check_output(args, cwd=ROOT, text=True)
            return out.rstrip('\n') if keep_spaces else out.strip()
        except Exception:
            return None

    dirty = (run('git', 'status', '--short', keep_spaces=True) or '')
    files = []
    for line in dirty.splitlines():
        name = line[3:] if len(line) > 3 else ''
        if name:
            files.append(name)
    return {'revision': run('git', 'rev-parse', '--short', 'HEAD'),
            'branch': run('git', 'rev-parse', '--abbrev-ref', 'HEAD'),
            'dirty_files': files,
            'local_file_sha256': {f: sha(io.open(os.path.join(ROOT, f), encoding='utf-8',
                                                 errors='replace').read())
                                  for f in files
                                  if f.endswith(('.py', '.html', '.md'))
                                  and os.path.isfile(os.path.join(ROOT, f))}}


def pick_inputs():
    """분야별 첫 질의 8개 + 무관 2개. 선정 이유와 원래 qid 를 함께 남긴다."""
    queries = common.load_queries()
    rows = sorted(queries.values(), key=lambda q: q['qid'])
    picked = []
    for category in CATEGORIES:
        hit = next((q for q in rows if q['kind'] == 'normal' and q['category'] == category), None)
        if hit is None:
            continue
        payload = dict(hit['payload'])
        extra = SUPPLEMENT.get(category, {})
        payload.update(extra)
        picked.append({
            'case_id': 'case%02d' % (len(picked) + 1),
            'qid': hit['qid'], 'kind': hit['kind'], 'category': category,
            'as_of_date': hit['as_of_date'],
            'reason': '분야 %s 에서 qid 가 가장 빠른 정상 질의' % category,
            'supplemented': sorted(extra) or None,
            'supplement_note': ('소재지는 질의 파일에 없어 **가상으로** 더했다 (%s)'
                                % ' '.join('%s=%s' % kv for kv in extra.items())) if extra else None,
            'payload': payload,
        })
    for hit in [q for q in rows if q['kind'] == 'negative'][:2]:
        picked.append({
            'case_id': 'case%02d' % (len(picked) + 1),
            'qid': hit['qid'], 'kind': hit['kind'], 'category': hit['category'],
            'as_of_date': hit['as_of_date'],
            'reason': '무관 질의 중 qid 가 가장 빠른 2개 (그대로 검색해 결과를 본다)',
            'supplemented': None, 'supplement_note': None,
            'payload': dict(hit['payload']),
        })
    return picked


def preflight_check():
    """서버(app.boot)·모델 워밍업 **전에** 하는 읽기 전용 정합성 검사 (2026-09-21 Codex 리뷰 P2).

    DB(SELECT)·NPZ·Chroma **복사본**만 읽는다. 통과하지 않으면 비교 실행은 서버를 켜지도 않고 멈춘다.
    """
    import chroma_integrity
    from search import vecstore
    from shared import embed
    return chroma_integrity.check(chroma_integrity.default_db_loader, vecstore.NPZ,
                                  os.path.join(vecstore.STORE, 'chroma'), vecstore.COLLECTION,
                                  embed.meta())


def preflight_reuse_problem(preflight, corpus_hash, now):
    """사전 검사 결과를 다시 써도 되는지. 되면 None, 안 되면 이유 문자열.

    now = {'npz_sha256': 지금 NPZ 파일 해시, 'chroma_files': 지금 Chroma 원본 폴더 지문}
    DB 입력 해시 집합 · NPZ 파일 · Chroma 폴더 전체가 사전 검사가 **끝난 시점**과 같아야 한다.
    """
    if preflight is None:
        return '사전 검사 결과가 없다'
    if not preflight.get('chroma_content_verified'):
        return '사전 검사가 통과하지 않았다'
    if preflight.get('corpus_sha256') != corpus_hash:
        return '사전 검사 뒤 DB 공고 내용이 바뀌었다'
    after = (preflight.get('snapshot') or {}).get('after') or {}
    if not after.get('npz_sha256') or after.get('chroma_files') is None:
        return '사전 검사에 파일 지문이 없다'
    if after['npz_sha256'] != now.get('npz_sha256'):
        return '사전 검사 뒤 NPZ 파일이 바뀌었다'
    if after['chroma_files'] != now.get('chroma_files'):
        return '사전 검사 뒤 Chroma 원본 폴더가 바뀌었다'
    return None


def data_fingerprint(content, corpus_hash):
    """검색 직전 데이터 지문. Chroma 폴더 지문은 정렬 JSON 의 sha256 한 줄로 줄인다."""
    after = (content.get('snapshot') or {}).get('after') or {}
    files = after.get('chroma_files')
    return {
        'corpus_sha256': corpus_hash,
        'npz_sha256': after.get('npz_sha256'),
        'chroma_files_sha256': (hashlib.sha256(json.dumps(files, sort_keys=True).encode('utf-8'))
                                .hexdigest() if files is not None else None),
        'npz_vector_set_sha256': content.get('npz_vector_set_sha256'),
        'chroma_vector_set_sha256': content.get('chroma_vector_set_sha256'),
    }


def data_check(preflight=None):
    """DB·Chroma·BM25 가 **같은 내용의** 같은 공고를 보고 있는지.

    ID 집합만 맞춰 보면, 공고 본문이 바뀌었는데 벡터는 옛 내용인 색인을 통과시킨다
    (2026-09-18 Codex 리뷰 3번). 그래서 공고별 입력 해시까지 본다.

      DB            embed.build_input 으로 만든 지금 내용의 해시
      벡터 파일      벡터를 만들 때 쓴 입력의 해시(data/embeddings_v1.npz 에 저장돼 있다)
      BM25          서버가 올린 문서 텍스트의 해시

    Chroma 자체에는 입력 해시가 없다. 그래서 **Chroma 의 실제 벡터를 NPZ 벡터와 원소 단위로** 맞춘다
    (2026-09-21, eval/chroma_integrity.py). 모든 공고 벡터와 메타데이터가 맞을 때만
    `chroma_content_verified: True` 다. 원본 Chroma 폴더는 복사본으로 연다.
    """
    from shared import embed
    from build_pool import corpus
    docs, corpus_hash, shas = corpus()
    db_ids = {nid for nid, _text in docs}

    col = app.STATE['collection']
    got = col.get(include=[])
    chroma_ids = {i for i in got['ids'] if i != '__watermark__'}
    bm25_ids = set(app.STATE['bm25'].ids)
    rows_ids = set(app.STATE['rows'])

    # BM25 는 원문 텍스트를 보관하지 않고 토큰 집계만 갖고 있다. 서비스 코드를 바꾸지 않고
    # 확인하려면 DB 내용을 같은 방식으로 잘라 토큰 집계가 같은지 본다.
    from search.hybrid import tokenize
    from collections import Counter
    bm25 = app.STATE['bm25']
    db_text = dict(docs)
    tf_by_id = dict(zip(bm25.ids, bm25.tfs))
    bm25_mismatch = sorted(nid for nid, tf in tf_by_id.items()
                           if nid in db_text and tf != Counter(tokenize(db_text[nid])))

    # 벡터 파일에 기록된 입력 해시와 DB 내용 해시를 맞춘다
    vector_info = {'checked': False, 'reason': None}
    try:
        import numpy as np
        from search import vecstore
        data = np.load(vecstore.NPZ, allow_pickle=False)
        vec_sha = dict(zip([str(x) for x in data['notice_ids']],
                           [str(x) for x in data['input_sha256']]))
        stale = sorted(nid for nid in db_ids
                       if nid in vec_sha and vec_sha[nid] != shas.get(nid))
        missing = sorted(nid for nid in db_ids if nid not in vec_sha)
        vector_info = {'checked': True, 'vectors': len(vec_sha),
                       'stale_content': stale[:10], 'stale_count': len(stale),
                       'missing_vectors': missing[:10], 'missing_count': len(missing),
                       'meta': json.loads(str(data['meta'])) if 'meta' in data else None}
    except Exception as exc:
        vector_info = {'checked': False, 'reason': '%s: %s' % (type(exc).__name__, exc)}

    # Chroma 실제 벡터 — 사전 검사 결과는 **DB·NPZ·Chroma 가 그 뒤로 그대로일 때만** 다시 쓴다.
    # 처음에는 DB 해시만 봐서, 부팅이나 동시 배치가 NPZ·Chroma 벡터만 바꿔도 옛 통과 판정을 썼다
    # (2026-09-21 Codex 후속 리뷰 P2). 하나라도 바뀌었으면 지금 상태로 다시 검사한다.
    import chroma_integrity
    from search import vecstore

    chroma_dir = os.path.join(vecstore.STORE, 'chroma')
    now = {'npz_sha256': chroma_integrity.file_sha256(vecstore.NPZ),
           'chroma_files': chroma_integrity.folder_fingerprint(chroma_dir)}
    recheck_reason = preflight_reuse_problem(preflight, corpus_hash, now)
    if recheck_reason is None:
        content = preflight
    else:
        def db_loader(first=[True]):
            if first[0]:
                first[0] = False
                return shas, corpus_hash
            _docs, again_hash, again_shas = corpus()
            return again_shas, again_hash

        content = chroma_integrity.check(db_loader, vecstore.NPZ, chroma_dir,
                                         vecstore.COLLECTION, embed.meta())
    chroma_content = {
        'status': content['status'],
        'preflight_reused': recheck_reason is None,
        'recheck_reason': recheck_reason,
        # 검색 직전에 쓴 데이터의 지문 — manifest 에 그대로 남는다
        'data_fingerprint': data_fingerprint(content, corpus_hash),
        'parts': {k: {'status': v.get('status'),
                      'problems': v.get('problems') or ([v['reason']] if v.get('reason') else [])}
                  for k, v in content['parts'].items()},
        'compared': content['parts'].get('npz_chroma', {}).get('compared'),
        'byte_equal': content['parts'].get('npz_chroma', {}).get('byte_equal'),
        'max_abs_diff': content['parts'].get('npz_chroma', {}).get('max_abs_diff'),
        'tolerance': chroma_integrity.TOLERANCE,
        'failure_lines': chroma_integrity.failure_lines(content),
    }

    return {
        'db_notices': len(db_ids), 'chroma_vectors': len(chroma_ids),
        'bm25_docs': len(bm25_ids), 'server_rows': len(rows_ids),
        'db_equals_chroma': db_ids == chroma_ids,
        'db_equals_bm25': db_ids == bm25_ids,
        'db_equals_rows': db_ids == rows_ids,
        'only_in_db': sorted(db_ids - chroma_ids)[:5],
        'only_in_chroma': sorted(chroma_ids - db_ids)[:5],
        'corpus_sha256': corpus_hash,
        'embed_input_version': embed.INPUT_VERSION,
        'embed_model': embed.MODEL,
        'embed_model_revision': embed.resolved_revision(),
        'bm25_content_mismatch': bm25_mismatch[:10],
        'bm25_content_mismatch_count': len(bm25_mismatch),
        'bm25_content_checked': True,
        'vector_file': vector_info,
        'chroma_content': chroma_content,
        'chroma_content_verified': content['chroma_content_verified'],
    }


def integrity_failures(checks):
    """비교를 계속하면 안 되는 조건. 하나라도 걸리면 실행을 멈춘다."""
    bad = []
    for key in ('db_equals_chroma', 'db_equals_bm25', 'db_equals_rows'):
        if not checks[key]:
            bad.append('%s = False (공고 ID 집합이 다르다)' % key)
    if checks['bm25_content_checked'] and checks['bm25_content_mismatch_count']:
        bad.append('BM25 문서 내용이 DB 와 다른 공고 %d건' % checks['bm25_content_mismatch_count'])
    vec = checks['vector_file']
    if vec.get('checked'):
        if vec['stale_count']:
            bad.append('벡터가 옛 내용인 공고 %d건' % vec['stale_count'])
        if vec['missing_count']:
            bad.append('벡터가 없는 공고 %d건' % vec['missing_count'])
    else:
        bad.append('벡터 파일 입력 해시를 확인하지 못했다 (%s)' % vec.get('reason'))
    # Chroma 실제 벡터·메타데이터가 확인되지 않았으면 비교를 하지 않는다 (지시서 3절)
    if not checks.get('chroma_content_verified'):
        lines = (checks.get('chroma_content') or {}).get('failure_lines') or []
        bad.append('Chroma 실제 벡터 내용이 확인되지 않았다 (%s)'
                   % ((checks.get('chroma_content') or {}).get('status') or '검사 결과 없음'))
        bad.extend('  ' + line for line in lines[:10])
    return bad


def run_case(case, stage, search):
    # 서비스는 실행일(date.today())로 마감·업력을 판단한다. 질의 파일의 as_of_date 를
    # 적용하지 않는다(2026-09-18 Codex 리뷰 1번). 둘을 구분해 남긴다.
    payload = dict(case['payload'])
    payload.update(STAGES[stage])
    payload.update({'top': TOP, 'search': search})
    req = app.MatchRequest(**payload)
    started = datetime.now(timezone.utc)
    before = date.today().isoformat()
    out = app.match(req)
    after = date.today().isoformat()
    return {
        'case_id': case['case_id'], 'qid': case['qid'], 'stage': stage, 'search': search,
        'at': started.isoformat(timespec='seconds'),
        # 검색 호출 **직전·직후**의 날짜. 호출 도중 자정을 넘으면 두 값이 달라지고,
        # 서비스가 실제로 쓴 날짜를 특정할 수 없다(2026-09-18 Codex 재검토 추가 P2).
        'applied_date': before,
        'applied_date_after': after,
        'query_as_of_date': case['as_of_date'],        # 원본 질의에 적힌 날짜(적용되지 않음)
        'request': payload, 'response': out,
    }


def notice_records(ids):
    rows = app.STATE['rows']
    notices = common.load_notices(sorted(ids), with_attachment=False)
    out = []
    for nid in sorted(ids):
        row = dict(rows.get(nid) or {})
        full = notices.get(nid) or {}
        body = (full.get('body') or '')
        target = (full.get('target_text') or full.get('target_category') or '')
        out.append({
            'notice_id': nid,
            'title': row.get('title') or full.get('title'),
            'region': row.get('region'),
            'target_category': row.get('target_category'),
            'age_condition_raw': row.get('age_condition_raw'),
            'apply_start': str(row.get('apply_start') or ''),
            'apply_end': str(row.get('apply_end') or ''),
            'apply_period_type': row.get('apply_period_type'),
            'url': row.get('url') or row.get('apply_url') or '',
            'body_excerpt': body[:400],
            'target_excerpt': target[:300],
            'content_sha256': sha('%s|%s|%s' % (row.get('title'), target, body)),
        })
    return out


def date_problems(start_day, end_day, responses):
    """날짜가 섞였는지. 비어 있으면 정상.

    경고만 남기고 결과를 정상으로 저장하면, 뒷날 그 비교표를 하루치 기준으로 읽게 된다.
    그래서 하나라도 걸리면 **무효 실행**으로 처리한다.
    """
    bad = []
    if end_day != start_day:
        bad.append('실행 시작일 %s 와 종료일 %s 가 다르다' % (start_day, end_day))
    mixed = sorted({r['applied_date'] for r in responses} |
                   {r.get('applied_date_after', r['applied_date']) for r in responses})
    if len(mixed) > 1:
        bad.append('응답들의 적용 날짜가 섞였다: %s' % ' · '.join(mixed))
    crossing = [r for r in responses
                if r.get('applied_date_after', r['applied_date']) != r['applied_date']]
    if crossing:
        bad.append('검색 도중 날짜가 바뀐 응답 %d건 (%s)'
                   % (len(crossing), crossing[0]['case_id']))
    if responses and mixed and mixed[0] != start_day:
        bad.append('응답 날짜 %s 가 실행 시작일 %s 와 다르다' % (mixed[0], start_day))
    return bad


def compare(responses):
    """같은 (case, stage) 의 dense/hybrid 를 맞대어 공통·신규·미노출과 순위 이동을 낸다."""
    index = {(r['case_id'], r['stage'], r['search']): r for r in responses}
    out = []
    for case_id, stage in sorted({(r['case_id'], r['stage']) for r in responses}):
        d = index[(case_id, stage, 'dense')]['response']
        h = index[(case_id, stage, 'hybrid')]['response']
        d_rank = {r['notice_id']: i + 1 for i, r in enumerate(d['results'])}
        h_rank = {r['notice_id']: i + 1 for i, r in enumerate(h['results'])}
        shared = [n for n in d_rank if n in h_rank]
        out.append({
            'case_id': case_id, 'stage': stage,
            'dense_count': d['count'], 'hybrid_count': h['count'],
            'shared': len(shared),
            'only_dense': [n for n in d_rank if n not in h_rank],
            'only_hybrid': [n for n in h_rank if n not in d_rank],
            # 상위 5 밖은 순위를 모른다. '미노출' 로만 적고 이동 폭을 만들지 않는다
            'moves': {n: {'dense': d_rank[n], 'hybrid': h_rank[n],
                          'moved': d_rank[n] - h_rank[n]} for n in shared},
        })
    return out


def esc(value):
    return html.escape(str(value if value is not None else ''))


def result_block(res, other_ids, notices):
    rows = []
    for i, r in enumerate(res['results'], 1):
        info = notices.get(r['notice_id'], {})
        marks = []
        if r.get('dense_rank'):
            marks.append('의미 %d위' % r['dense_rank'])
        if r.get('bm25_rank'):
            marks.append('단어 %d위' % r['bm25_rank'])
        if r.get('rrf_score') is not None:
            marks.append('RRF %.5f' % r['rrf_score'])
        rules = r.get('rules') or {}
        flags = []
        if rules.get('groups'):
            flags.append('집단: ' + ' · '.join(rules['groups']))
        if rules.get('off_region'):
            flags.append('다른 시·도')
        if rules.get('off_district'):
            flags.append('다른 시·군·구')
        rows.append(
            '<tr class="%s"><td>%d</td><td><a href="%s" target="_blank" rel="noopener">%s</a>'
            '<div class="meta">%s · 지역 %s · 접수 %s~%s</div>'
            '<div class="ex">%s</div></td>'
            '<td class="num">%s</td><td class="small">%s</td><td class="small">%s</td></tr>' % (
                'new' if r['notice_id'] not in other_ids else '',
                i, esc(info.get('url')), esc(r['title']),
                esc(r['notice_id']), esc(r.get('region') or '정보 없음'),
                esc(r.get('apply_start')), esc(r.get('apply_end')),
                esc((info.get('target_excerpt') or info.get('body_excerpt') or '')[:140]),
                esc(r['score']), esc(' · '.join(marks)), esc(' · '.join(flags) or '-')))
    if not rows:
        rows = ['<tr><td colspan="5" class="small">결과 없음</td></tr>']
    return ('<table><thead><tr><th>순위</th><th>공고</th><th>유사도</th>'
            '<th>검색 순위</th><th>적용된 규칙</th></tr></thead><tbody>%s</tbody></table>'
            % ''.join(rows))


def build_html(path, inputs, responses, comparisons, manifest, notices):
    by_case = {c['case_id']: c for c in inputs}
    index = {(r['case_id'], r['stage'], r['search']): r for r in responses}
    cmp_index = {(c['case_id'], c['stage']): c for c in comparisons}
    parts = ["""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>임베딩 단독 · 하이브리드 검색 비교</title><style>
body{margin:0;background:#f7f8fa;color:#222;font:14px/1.6 "맑은 고딕","Malgun Gothic",system-ui,sans-serif}
.wrap{max-width:1280px;margin:0 auto;padding:24px 16px 70px}
h1{font-size:22px;color:#1f3864;margin:0 0 6px} h2{font-size:17px;color:#1f3864;margin:26px 0 6px}
h3{font-size:14px;margin:14px 0 6px;color:#1f3864}
.card{background:#fff;border:1px solid #d8dee9;border-radius:10px;padding:16px;margin-bottom:16px}
table{width:100%;border-collapse:collapse;margin-top:6px}
th,td{border-bottom:1px solid #e6e9ef;padding:7px 8px;text-align:left;vertical-align:top;font-size:12.5px}
th{background:#f1f4f9;color:#55617a;font-size:12px}
td.num{white-space:nowrap} .small{font-size:11.5px;color:#6b7280}
.meta{color:#6b7280;font-size:11.5px;margin-top:2px} .ex{color:#55617a;font-size:11.5px;margin-top:3px}
tr.new{background:#f2f8f2}
.cols{display:flex;gap:14px;flex-wrap:wrap}.col{flex:1 1 520px;min-width:420px}
.note{font-size:12.5px;color:#6b7280}.tag{display:inline-block;background:#eef1f6;border-radius:10px;
padding:2px 9px;font-size:11.5px;color:#44506b;margin-right:5px}
a{color:#1f3864}
</style></head><body><div class="wrap">"""]
    parts.append('<h1>임베딩 단독(dense) · 하이브리드(hybrid) 검색 비교</h1>')
    parts.append('<p class="note">실행 %s · 공고 %s건 · Chroma %s건 · BM25 %s건 · git %s<br>'
                 'A = 후처리(마감 숨김·집단·지역·시군구) 모두 끔 · B = 현재 서비스와 같은 조건 · 각 단계에서 검색 방식만 바꿈<br>'
                 '초록 배경 = 반대쪽 상위 %d 에 없는 공고. 유사도(코사인)와 RRF 점수는 서로 비교할 수 없는 값이다.</p>'
                 % (esc(manifest['run_at']), esc(manifest['data']['db_notices']),
                    esc(manifest['data']['chroma_vectors']), esc(manifest['data']['bm25_docs']),
                    esc(manifest['git']['revision']), TOP))
    for case in inputs:
        c = by_case[case['case_id']]
        parts.append('<div class="card"><h2>%s · %s (%s · %s)</h2>' % (
            esc(c['case_id']), esc(c['category']), esc(c['qid']),
            '무관 질의' if c['kind'] == 'negative' else '정상 질의'))
        p = c['payload']
        parts.append('<p class="note">%s<br>신청자: %s · 설립일 %s · 소재지 %s %s%s<br>'
                     '<b>실제 적용된 기준일 %s</b> (마감·업력 판단) · 원본 질의 기준일 %s (적용되지 않음)</p>' % (
                         esc(p.get('idea')), esc(p.get('applicant_type')),
                         esc(p.get('founded_at') or '없음'),
                         esc(p.get('region') or '선택 안 함'), esc(p.get('district') or ''),
                         (' <span class="tag">가상 소재지 보완</span>' if c['supplement_note'] else ''),
                         esc(manifest['as_of_today']), esc(c['as_of_date'])))
        for stage, label in (('A', 'A. 후처리 제외 — 검색 방식 차이'),
                             ('B', 'B. 현재 서비스 조건 — 최종 노출 결과')):
            d = index[(c['case_id'], stage, 'dense')]['response']
            h = index[(c['case_id'], stage, 'hybrid')]['response']
            cmp_ = cmp_index[(c['case_id'], stage)]
            d_ids = {r['notice_id'] for r in d['results']}
            h_ids = {r['notice_id'] for r in h['results']}
            moves = ' · '.join('%s %d위→%d위' % (n, m['dense'], m['hybrid'])
                               for n, m in cmp_['moves'].items() if m['moved'])
            parts.append('<h3>%s</h3>' % esc(label))
            parts.append('<p class="note">질의: "%s"<br>공통 %d건 · dense 만 %d건 · hybrid 만 %d건%s</p>' % (
                esc(d['query']), cmp_['shared'], len(cmp_['only_dense']), len(cmp_['only_hybrid']),
                ('<br>순위 이동: ' + esc(moves)) if moves else ''))
            parts.append('<div class="cols"><div class="col"><b>dense</b> '
                         '<span class="small">%d건 · 깊이 %s · 라운드 %s · 인코딩 %sms + 검색 %sms</span>%s</div>'
                         '<div class="col"><b>hybrid</b> '
                         '<span class="small">%d건 · 깊이 %s · 라운드 %s · 인코딩 %sms + 검색 %sms</span>%s</div></div>'
                         % (d['count'], esc(d.get('depth')), esc(d.get('search_rounds')),
                            esc(d['encode_ms']), esc(d['search_ms']),
                            result_block(d, h_ids, notices),
                            h['count'], esc(h.get('depth')), esc(h.get('search_rounds')),
                            esc(h['encode_ms']), esc(h['search_ms']),
                            result_block(h, d_ids, notices)))
        parts.append('</div>')
    parts.append('</div></body></html>')
    io.open(path, 'w', encoding='utf-8', newline='\n').write('\n'.join(parts))


def build_csv(path, inputs, responses):
    by_case = {c['case_id']: c for c in inputs}
    seen = set()
    with io.open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['case_id', 'qid', '단계', '검색방식', '순위', 'notice_id', '공고 제목',
                    '내용 관련성(0/1/2)', '신청 자격(가능/불가/모름)', '선호 결과(dense/hybrid/같음)', '이유'])
        for r in responses:
            for i, hit in enumerate(r['response']['results'], 1):
                key = (r['case_id'], r['stage'], r['search'], hit['notice_id'])
                if key in seen:
                    continue
                seen.add(key)
                w.writerow([r['case_id'], by_case[r['case_id']]['qid'], r['stage'], r['search'],
                            i, hit['notice_id'], hit['title'], '', '', '', ''])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plan', action='store_true', help='선정한 입력만 보고 끝낸다')
    ap.add_argument('--check-only', dest='check_only', action='store_true',
                    help='Chroma 실제 벡터 정합성만 검사하고 끝낸다 (검색·워밍업·색인 생성 없음)')
    args = ap.parse_args()

    if args.check_only:
        # app.boot() 를 부르지 않는다 — 워밍업(모델 인코딩)과 색인 열기를 하지 않는다
        import chroma_integrity
        code, _result, _outdir = chroma_integrity.run()
        return code

    inputs = pick_inputs()
    print('입력 %d개 (정상 %d · 무관 %d)' % (
        len(inputs), sum(1 for c in inputs if c['kind'] == 'normal'),
        sum(1 for c in inputs if c['kind'] == 'negative')))
    for c in inputs:
        print('  %s %s %-12s %s%s' % (c['case_id'], c['qid'], c['category'],
                                      c['payload']['idea'][:40],
                                      ' [소재지 보완]' if c['supplement_note'] else ''))
    if args.plan:
        print('\n--plan 이라 검색하지 않는다. 계획: %d입력 × 2단계 × 2방식 = %d개 응답'
              % (len(inputs), len(inputs) * 4))
        return 0

    # 서버·모델을 켜기 **전에** 읽기 전용으로 먼저 확인한다. 실패하면 app.boot() 를 부르지 않는다
    # (2026-09-21 Codex 리뷰 P2 — 예전에는 서버를 켜고 모델 워밍업까지 한 뒤에 멈췄다)
    print('\n사전 정합성 검사 (읽기 전용 · 서버·모델을 켜기 전)')
    import chroma_integrity
    preflight = preflight_check()
    if not preflight.get('chroma_content_verified'):
        print('  판정: %s — 서버를 켜지 않고 중단한다:' % preflight.get('status'))
        for line in chroma_integrity.failure_lines(preflight) or ['(사유 없음)']:
            print('  - %s' % line)
        print('색인을 자동으로 다시 만들지 않는다. `--check-only` 로 보고서를 남겨 원인을 본다.')
        return 2

    print('\n서버와 같은 방식으로 색인·공고를 올린다 (app.boot)')
    app.boot()
    checks = data_check(preflight)
    print('  DB %d · Chroma %d · BM25 %d · 공고정보 %d · ID 집합 동일: chroma %s · bm25 %s · rows %s'
          % (checks['db_notices'], checks['chroma_vectors'], checks['bm25_docs'],
             checks['server_rows'], checks['db_equals_chroma'], checks['db_equals_bm25'],
             checks['db_equals_rows']))
    vec = checks['vector_file']
    print('  내용 확인: BM25 불일치 %d건 · 벡터 옛 내용 %s · 벡터 없음 %s · Chroma 실제 벡터 %s'
          % (checks['bm25_content_mismatch_count'],
             vec.get('stale_count') if vec.get('checked') else '확인 못함',
             vec.get('missing_count') if vec.get('checked') else '확인 못함',
             (checks.get('chroma_content') or {}).get('status', '확인 못함')))
    failures = integrity_failures(checks)
    if failures:
        print('\n정합성 문제로 비교를 중단한다:')
        for line in failures:
            print('  - %s' % line)
        print('색인을 자동으로 다시 만들지 않는다. daily_pipeline 또는 ec2_vecstore 로 먼저 맞춘다.')
        return 2

    run_at = datetime.now(timezone.utc)
    start_day = date.today().isoformat()
    stamp = run_at.strftime('%Y%m%dT%H%M%SZ')
    outdir = os.path.join(REPORTS, 'search_comparison_' + stamp)
    os.makedirs(outdir, exist_ok=True)

    # 첫 질의는 모델·색인을 데우는 데 쓰이므로 결과에서 뺀다
    app.match(app.MatchRequest(applicant_type='법인사업자', idea='워밍업', top=1))

    responses = []
    for case in inputs:
        for stage in ('A', 'B'):
            for search in ('dense', 'hybrid'):
                responses.append(run_case(case, stage, search))
        counts = {(r['stage'], r['search']): r['response']['count']
                  for r in responses if r['case_id'] == case['case_id']}
        print('  %s %s  A dense %d / hybrid %d · B dense %d / hybrid %d' % (
            case['case_id'], case['qid'], counts[('A', 'dense')], counts[('A', 'hybrid')],
            counts[('B', 'dense')], counts[('B', 'hybrid')]))

    end_day = date.today().isoformat()
    problems = date_problems(start_day, end_day, responses)
    if problems:
        # 무효 실행 — 원본은 진단용으로 남기되 비교표·판정 양식은 만들지 않는다
        bad_dir = outdir + '_INVALID_date_changed'
        os.makedirs(bad_dir, exist_ok=True)
        common.write_jsonl(os.path.join(bad_dir, 'responses.jsonl'), responses)
        common.write_jsonl(os.path.join(bad_dir, 'inputs.jsonl'), inputs)
        lines = ['# 무효 실행 — 실행 중 날짜가 바뀌었다', '',
                 '마감·업력 판단 기준일이 사례마다 다를 수 있어 비교표를 만들지 않았다.',
                 '원본 응답은 진단용으로만 남긴다. **정상 결과로 인용하지 않는다.**', '']
        lines += ['- %s' % line for line in problems]
        lines += ['', '다시 실행한다: `python -X utf8 eval/search_comparison.py`', '']
        io.open(os.path.join(bad_dir, 'INVALID.md'), 'w',
                encoding='utf-8', newline='\n').write('\n'.join(lines))
        try:
            os.rmdir(outdir)
        except OSError:
            pass
        print('\n무효 실행으로 처리했다 (비교표를 만들지 않는다):')
        for line in problems:
            print('  - %s' % line)
        print('진단용 원본 → %s' % bad_dir)
        return 3
    comparisons = compare(responses)
    ids = {hit['notice_id'] for r in responses for hit in r['response']['results']}
    notices = notice_records(ids)
    manifest = {
        'task': 'docs/SEARCH_COMPARISON_TASK_20260918.md',
        'run_at': run_at.isoformat(timespec='seconds'),
        'as_of_today': start_day,
        'run_end_date': end_day,
        'date_consistent': True,      # date_problems() 를 통과한 실행만 여기에 온다
        'git': git_info(),
        'data': checks,
        'settings': {'top': TOP, 'stages': STAGES, 'searches': ['dense', 'hybrid'],
                     'weights': app.Weights().model_dump(), 'reranker': False},
        'counts': {'inputs': len(inputs), 'responses': len(responses),
                   'notices_in_results': len(ids)},
    }
    common.write_jsonl(os.path.join(outdir, 'inputs.jsonl'), inputs)
    common.write_jsonl(os.path.join(outdir, 'responses.jsonl'), responses)
    common.write_jsonl(os.path.join(outdir, 'notices.jsonl'), notices)
    common.write_jsonl(os.path.join(outdir, 'comparison.jsonl'), comparisons)
    with io.open(os.path.join(outdir, 'manifest.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    build_html(os.path.join(outdir, 'comparison.html'), inputs, responses, comparisons,
               manifest, {n['notice_id']: n for n in notices})
    build_csv(os.path.join(outdir, 'human_review.csv'), inputs, responses)

    print('\n결과 → %s' % outdir)
    for name in sorted(os.listdir(outdir)):
        print('  %-20s %7.1f KB' % (name, os.path.getsize(os.path.join(outdir, name)) / 1024))
    return 0


if __name__ == '__main__':
    sys.exit(main())
