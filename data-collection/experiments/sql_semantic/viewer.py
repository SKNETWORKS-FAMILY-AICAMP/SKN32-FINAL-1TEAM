# -*- coding: utf-8 -*-
"""검증 화면 — 실행 상태·조건 판정·검색 결과·벡터 상태를 사람이 눈으로 본다.

  .\\.venv\\Scripts\\python.exe -X utf8 -m experiments.sql_semantic.viewer
  → http://127.0.0.1:8010

지시서: `docs/CLAUDE_UI_VERIFICATION_TASK_20260921.md`

**읽기 전용이다.** 저장된 결과 폴더(`reports/sql_semantic_*`)와 fixture 만 읽는다.
DB 에 쓰지 않는다. 근거 문장만 요청이 있을 때 실험 DB 에서 읽어 온다(SELECT 만).
실험 DB 설정이 없으면 그 사실을 화면에 적고 넘어간다.

  /compare  직접 검색 비교 (2026-09-21). 사용자가 입력하면 기존 서비스(8000)의 /api/match 를
            HTTP 로 부르고, 새 방식은 실험 DB 를 SELECT 해 검색한다. 결과는 저장하지 않는다.

기존 서비스(`search/app.py`, 8000 포트)와 **다른 앱·다른 포트**다. 운영 검색 결과와 섞지 않는다.

화면에서 숨기지 않는 것
  · F1 자격 문구 오해석 · F2 모델 리비전 미검사 · F3 재생성 메타데이터 갱신 누락의 현재 상태.
    상태는 아래 KNOWN_ISSUES 한 곳에서 관리한다 (Codex 승인 전에는 '해결'로 적지 않는다)
  · Chroma 실제 벡터 내용 미검증 · 사람 관련성 판정 없음
  · fixture 결과에는 `DEMO/FIXTURE — 실제 검색 결과 아님`
"""
import glob
import hashlib
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402

from experiments.sql_semantic import embedding, fixtures  # noqa: E402

REPORTS = os.path.join(ROOT, 'reports')
WEB = os.path.join(ROOT, 'web')
FIXTURE_ID = 'fixture'

# 화면 맨 위에 항상 띄우는 미해결 목록. 고쳤다고 바꿔 쓰지 않는다 — 코드가 바뀌면 여기도 고친다.
KNOWN_ISSUES = (
    {'id': 'F1', 'state': '해결 · Codex 승인 (2026-09-21)',
     'title': '자격 제한이 아닌 문구를 허용 목록으로 읽던 문제',
     'detail': '지원대상 칸만 보고, 제외·부정·거래 상대 문장의 단어는 허용 목록에 넣지 않는다. '
               '제한 없음은 그 필드 이름이 붙은 경우만(기업 규모 제한 없음·업종 무관 등) no_limit 이다. '
               '1차 수정에서 "지역 제한 없음" 이 업종·규모로 새던 문제를 Codex 재리뷰가 찾아 다시 고쳤고 '
               '재검토에서 승인됐다. B 구역 반례가 모두 `기대대로` 여야 정상이다. '
               '2026-09-21 조건을 sql_lab_v2 로 재적재하고 비교를 다시 돌렸다(20260921T024014Z). '
               '083852Z 는 수정 전(sql_lab_v1) 결과로 보존한다. 두 실행의 Top-5·후보 수·판정은 '
               '모두 같았다 — 10개 사례에 신청자 기업 규모·업종 입력이 없어 고친 판정이 쓰이지 않기 때문이다. '
               '영향은 f1_impact_20260921.json.',
     'where': 'experiments/sql_semantic/conditions.py · 리뷰 F1 · SQL_SEMANTIC_F1_REVIEW_20260921.md'},
    {'id': 'F2', 'state': '해결 · Codex 승인 (2026-09-21)',
     'title': '검색할 때 모델 리비전을 확인하지 않던 문제',
     'detail': '이제 저장 벡터의 model_revision 을 질의 인코더의 리비전과 대조한다. 다르거나, '
               '어느 쪽이든 리비전을 모르면 낡은 벡터(stale)로 빼고 사유를 남긴다. '
               '응답에 인코더 리비전(encoder)도 기록한다. fixture fx-007 에서 확인할 수 있다. '
               '실제 벡터 1,852건은 모두 현재와 같은 리비전이라 실제 결과는 바뀌지 않는다(Codex 전수 대조). '
               '리비전은 로컬 Hugging Face 캐시의 refs/main 으로 찾는다 — 다른 캐시 경로를 쓰는 PC 에서는 '
               '먼저 리비전이 잡히는지 확인해야 한다(못 찾으면 모든 벡터가 stale 로 빠진다).',
     'where': 'experiments/sql_semantic/search.py · 리뷰 F2'},
    {'id': 'F3', 'state': '해결 · Codex 승인 (2026-09-21)',
     'title': '벡터를 다시 만들 때 메타데이터가 갱신되지 않던 문제',
     'detail': '벡터 UPSERT 가 키를 뺀 모든 칸(model·model_revision·dim·dtype·normalized 등)을 갱신한다. '
               '재생성 판정도 dtype·정규화까지 본다. 실제 DB 에서 벡터를 다시 만들지는 않았다 '
               '(모두 현재 조건과 맞아 만들 대상이 없다).',
     'where': 'experiments/sql_semantic/prepare.py · 리뷰 F3'},
    {'id': 'CHROMA', 'state': '통과 · 검사 도구 Codex 승인 (2026-09-21)',
     'title': 'Chroma 색인의 실제 벡터 내용',
     'detail': '2026-09-21 읽기 전용 검사에서 kstartup:179193 한 건만 옛 벡터였다(코사인 0.9866). '
               '사용자 승인으로 Chroma 폴더를 백업한 뒤 그 한 건만 벡터 파일 값으로 다시 넣었고, 재검사에서 '
               'DB↔벡터 파일·벡터 파일↔Chroma·메타데이터 모두 통과했다(chroma_content_verified=True). '
               '백업과 비교해 바뀐 벡터는 179193 한 건뿐이다. 이 PC 의 Chroma 만 확인했고 EC2 쪽은 확인하지 않았다. '
               '과거 dense/hybrid 비교(054314Z) 당시의 정합성을 소급 보증하지 않는다.',
     'where': 'reports/chroma_integrity_20260921T050045Z · eval/chroma_integrity.py · CHROMA_INTEGRITY_REVIEW_20260921.md'},
    {'id': 'HUMAN', 'state': '없음',
     'title': '사람 관련성 판정이 아직 없다',
     'detail': '어느 결과가 더 쓸모 있는지 사람이 매긴 점수가 없다. '
               '여기 숫자는 품질 우위의 근거가 아니다.',
     'where': 'reports/search_comparison_20260918T054314Z/human_review.csv'},
)

TEST_COMMAND = ('.\\.venv\\Scripts\\python.exe -X utf8 -m unittest '
                'discover -s tests -p "test_*.py"')


def _read_jsonl(path):
    with io.open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def _read_json(path):
    with io.open(path, encoding='utf-8') as f:
        return json.load(f)


def _sha256_file(path):
    h = hashlib.sha256()
    with io.open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _safe_lab(lab):
    """접속 정보에서 계정·비밀번호를 뺀다. 화면·로그에 남기지 않는다."""
    if not isinstance(lab, dict):
        return {'note': str(lab)}
    out = {}
    for key, value in lab.items():
        if isinstance(value, dict):
            out[key] = {k: v for k, v in value.items() if k not in ('user', 'password')}
        elif key not in ('user', 'password'):
            out[key] = value
    return out


def stored_folders():
    folders = sorted(glob.glob(os.path.join(REPORTS, 'sql_semantic_*')))
    return [f for f in folders if os.path.isfile(os.path.join(f, 'manifest.json'))]


def list_runs():
    """화면 위 드롭다운에 넣을 목록. 최신 저장 결과가 먼저 온다."""
    runs = []
    for folder in reversed(stored_folders()):
        manifest = _read_json(os.path.join(folder, 'manifest.json'))
        runs.append({
            'run_id': os.path.basename(folder),
            'kind': 'stored',
            # 추출기 버전을 붙인다. F1 수정 전(v1)·후(v2) 실행을 목록에서 바로 구분하게
            'label': '저장된 실행 · %s · 추출기 %s' % (manifest.get('run_at', ''),
                                                  manifest.get('condition_extractor', '?')),
            'run_at': manifest.get('run_at', ''),
            'as_of_date': manifest.get('as_of_date', ''),
            'is_fixture': False,
        })
    runs.append({'run_id': FIXTURE_ID, 'kind': 'fixture',
                 'label': 'FIXTURE (가짜 데이터)',
                 'run_at': '(fixture)', 'as_of_date': fixtures.AS_OF.isoformat(),
                 'is_fixture': True})
    return runs


def load_run(run_id):
    """실행 하나를 읽는다. fixture 는 그 자리에서 만든다(같은 값이 나온다)."""
    if run_id == FIXTURE_ID:
        data = fixtures.fixture_run()
        return {'manifest': data['manifest'], 'cases': data['cases'],
                'responses': data['responses'], 'evidence': data['evidence'],
                'condition_cases': data['condition_cases'], 'is_fixture': True,
                'folder': None, 'files': []}
    folder = os.path.join(REPORTS, os.path.basename(run_id))
    if not os.path.isdir(folder) or not os.path.isfile(os.path.join(folder, 'manifest.json')):
        return None
    manifest = _read_json(os.path.join(folder, 'manifest.json'))
    manifest = dict(manifest, run_id=os.path.basename(folder), kind='stored')
    manifest['lab'] = _safe_lab(manifest.get('lab'))
    files = []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            files.append({'name': name, 'bytes': os.path.getsize(path),
                          'sha256': _sha256_file(path)})
    return {
        'manifest': manifest,
        'cases': _read_jsonl(os.path.join(folder, 'inputs.jsonl')),
        'responses': _read_jsonl(os.path.join(folder, 'responses.jsonl')),
        'evidence': {},
        'condition_cases': fixtures.condition_cases(),   # 반례는 항상 fixture 로 보여 준다
        'is_fixture': False,
        'folder': os.path.relpath(folder, ROOT),
        'files': files,
    }


def vector_summary(responses):
    """벡터 상태를 실행 전체로 합친다. 사유도 같이 모은다."""
    totals = {'missing_vector': 0, 'broken_vector': 0, 'stale_vector': 0}
    examples = {'missing_vector': [], 'broken_vector': [], 'stale_vector': []}
    for row in responses:
        res = row['response']
        counts = res.get('counts') or {}
        for key in totals:
            totals[key] += int(counts.get(key) or 0)
        for key, field in (('missing_vector', 'missing_vector_examples'),
                           ('broken_vector', 'broken_vector_examples'),
                           ('stale_vector', 'stale_vector_examples')):
            for item in (res.get(field) or []):
                entry = item if isinstance(item, dict) else {'notice_id': item}
                entry = dict(entry, case_id=row['case_id'], mode=row['mode'])
                if key == 'missing_vector':
                    entry.setdefault('reason', '이 공고의 벡터가 저장돼 있지 않다')
                if len(examples[key]) < 20:
                    examples[key].append(entry)
    return {'totals': totals, 'examples': examples,
            'note': '같은 공고가 사례마다 다시 세어진다. 고유 공고 수가 아니다.'}


def case_rows(run, case_id):
    return {row['mode']: row for row in run['responses'] if row['case_id'] == case_id}


def compare_modes(on_response, off_response):
    """필터 켬/끔 두 목록을 맞춰 본다. 공통·전용·순위 이동."""
    on_results = (on_response or {}).get('results') or []
    off_results = (off_response or {}).get('results') or []
    on_rank = {r['notice_id']: r['rank'] for r in on_results}
    off_rank = {r['notice_id']: r['rank'] for r in off_results}
    rows = []
    for result in on_results:
        nid = result['notice_id']
        in_off = nid in off_rank
        rows.append({
            'notice_id': nid, 'title': result.get('title'), 'url': result.get('url'),
            'rank_on': result['rank'], 'rank_off': off_rank.get(nid),
            'similarity': result.get('similarity'),
            'where': '공통' if in_off else '필터 켬 전용',
            'move': (off_rank[nid] - result['rank']) if in_off else None,
        })
    for result in off_results:
        nid = result['notice_id']
        if nid in on_rank:
            continue
        rows.append({
            'notice_id': nid, 'title': result.get('title'), 'url': result.get('url'),
            'rank_on': None, 'rank_off': result['rank'],
            'similarity': result.get('similarity'),
            'where': '필터 끔 전용', 'move': None,
        })
    rows.sort(key=lambda r: (r['rank_on'] is None, r['rank_on'] or 0,
                             r['rank_off'] or 0, r['notice_id']))
    return rows


def drop_split(response, baseline_response=None):
    """SQL 단계에서 빠진 수와 파이썬 조건에서 빠진 수를 **나눠서** 돌려준다.

    `rows_from_sql` 은 SQL 이 돌려준 줄 수다. 같은 사례의 **필터 끔** 실행이 전체 후보 수이므로
    그 차이가 SQL 단계에서 빠진 수다(2026-09-21 Codex 리뷰 2번).

      전체 후보 → SQL 제외 → SQL 통과 → 조건 제외 → 비교한 벡터 → 반환

    사례 단위의 줄 수다. 고유 공고 수가 아니다. 기준값이 없거나 더 작으면(비정상 입력)
    음수를 만들지 않고 `None` 으로 두고 그 이유를 적는다.
    """
    counts = (response or {}).get('counts') or {}
    fields = {}
    for item in (response or {}).get('dropped_examples') or []:
        for field in item.get('fields') or []:
            fields[field] = fields.get(field, 0) + 1

    rows_from_sql = counts.get('rows_from_sql')
    baseline = ((baseline_response or {}).get('counts') or {}).get('rows_from_sql')
    sql_dropped, sql_note = None, ''
    if baseline is None or rows_from_sql is None:
        sql_note = '비교할 필터 끔 실행이 없어 SQL 단계 제외를 계산하지 않았다.'
    elif baseline < rows_from_sql:
        sql_note = ('기준 후보 수(%s)가 SQL 후보 수(%s)보다 작다. 같은 조건의 실행이 아닐 수 있어 '
                    '계산하지 않았다.' % (baseline, rows_from_sql))
    else:
        sql_dropped = baseline - rows_from_sql

    # 벡터 문제로 비교에서 빠진 수 — 조건 제외와 다른 이유다. 따로 보여 준다.
    vector_dropped = None
    if counts.get('after_conditions') is not None and counts.get('compared') is not None:
        vector_dropped = counts['after_conditions'] - counts['compared']

    return {
        'total_candidates': baseline,
        'sql_dropped': sql_dropped,
        'sql_note': sql_note,
        'rows_from_sql': rows_from_sql,
        'dropped_by_conditions': counts.get('dropped'),
        'after_conditions': counts.get('after_conditions'),
        'dropped_by_vector': vector_dropped,
        'compared': counts.get('compared'),
        'returned': counts.get('returned'),
        'dropped_fields_in_examples': fields,
        'note': ('모두 사례 단위의 줄 수이며 고유 공고 수가 아니다. '
                 '조건별 사유는 저장된 예시(최대 10건) 기준이고 전체 탈락의 집계가 아니다.'),
    }


app = FastAPI(title='SQL 의미 검색 검증 화면')


@app.get('/api/runs')
def api_runs():
    return JSONResponse({'runs': list_runs(), 'issues': list(KNOWN_ISSUES),
                         'test_command': TEST_COMMAND})


@app.get('/api/run/{run_id}')
def api_run(run_id: str):
    run = load_run(run_id)
    if not run:
        return JSONResponse({'error': '실행을 찾지 못했다: %s' % run_id}, status_code=404)
    manifest = run['manifest']
    cases = []
    for case in run['cases']:
        modes = case_rows(run, case['case_id'])
        cases.append({
            'case_id': case['case_id'], 'qid': case.get('qid'),
            'kind': case.get('kind'), 'category': case.get('category'),
            'idea': (case.get('payload') or {}).get('idea', ''),
            'reason': case.get('reason'), 'supplement_note': case.get('supplement_note'),
            'counts': {mode: (row['response'].get('counts') or {})
                       for mode, row in modes.items()},
        })
    return JSONResponse({
        'run_id': manifest.get('run_id', run_id),
        'is_fixture': run['is_fixture'],
        'banner': fixtures.BANNER if run['is_fixture'] else '',
        'manifest': manifest,
        'embedding': manifest.get('embedding') or embedding.meta(),
        'data_quality': manifest.get('data_quality') or {},
        'vectors': vector_summary(run['responses']),
        'cases': cases,
        'folder': run['folder'],
        'files': run['files'],
        'issues': list(KNOWN_ISSUES),
        'test_command': TEST_COMMAND,
        'tests': load_test_result(),
    })


@app.get('/api/run/{run_id}/case/{case_id}')
def api_case(run_id: str, case_id: str):
    run = load_run(run_id)
    if not run:
        return JSONResponse({'error': '실행을 찾지 못했다: %s' % run_id}, status_code=404)
    modes = case_rows(run, case_id)
    if not modes:
        return JSONResponse({'error': '사례를 찾지 못했다: %s' % case_id}, status_code=404)
    case = next((c for c in run['cases'] if c['case_id'] == case_id), {})
    on_response = (modes.get('filter_on') or {}).get('response') or {}
    off_response = (modes.get('filter_off') or {}).get('response') or {}
    return JSONResponse({
        'run_id': run['manifest'].get('run_id', run_id),
        'is_fixture': run['is_fixture'],
        'banner': fixtures.BANNER if run['is_fixture'] else '',
        'case': {'case_id': case_id, 'qid': case.get('qid'),
                 'category': case.get('category'), 'kind': case.get('kind'),
                 'idea': (case.get('payload') or {}).get('idea', ''),
                 'reason': case.get('reason'),
                 'supplement_note': case.get('supplement_note')},
        'applicant': on_response.get('applicant') or off_response.get('applicant') or {},
        'query_text': on_response.get('query_text') or off_response.get('query_text') or '',
        'as_of_date': on_response.get('as_of_date') or off_response.get('as_of_date'),
        'filter_on': on_response,
        'filter_off': off_response,
        'side_by_side': compare_modes(on_response, off_response),
        # 필터 끔 실행이 전체 후보 수의 기준이다. 자기 자신을 기준으로 두면 SQL 제외는 0 이다.
        'drops': {'filter_on': drop_split(on_response, off_response),
                  'filter_off': drop_split(off_response, off_response)},
        'evidence': run['evidence'],
        'timing_ms': {'filter_on': on_response.get('timing_ms'),
                      'filter_off': off_response.get('timing_ms')},
    })


@app.get('/api/conditions/cases')
def api_condition_cases():
    """조건 판정 반례. F1 이 살아 있으면 '문제 재현됨' 으로 나온다."""
    cases = fixtures.condition_cases()
    return JSONResponse({
        'banner': fixtures.BANNER,
        'cases': cases,
        'reproduced': [c['id'] for c in cases if not c['passed']],
        'note': '가짜 공고를 실제 추출기에 넣은 결과다. 실제 공고에서 같은 일이 몇 건 일어나는지는 세지 않았다.',
    })


@app.get('/api/evidence/{notice_id:path}')
def api_evidence(notice_id: str):
    """공고 한 건의 조건 근거 문장. 실험 DB 를 **읽기만** 한다.

    저장된 실행 결과에는 근거 문장이 들어 있지 않다. 설정이 없으면 그 사실을 돌려준다.
    """
    from experiments.sql_semantic import config
    try:
        lab = config.lab_settings()
        config.guard(lab)
        connection = config.connect()
    except Exception as exc:      # 설정 없음·거부·연결 실패 모두 화면에 이유를 적는다
        return JSONResponse({'notice_id': notice_id, 'available': False,
                             'reason': '실험 DB 에서 근거를 읽지 못했다: %s'
                                       % str(exc).splitlines()[0]})
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT field, status, value_text, value_min, value_max, bound_note, evidence'
                '  FROM lab_conditions WHERE notice_id = %s ORDER BY field', (notice_id,))
            rows = [dict(zip(('field', 'status', 'value_text', 'value_min', 'value_max',
                              'bound_note', 'evidence'), r)) for r in cursor.fetchall()]
            cursor.execute('SELECT title, url, target_text FROM lab_notices WHERE notice_id = %s',
                           (notice_id,))
            head = cursor.fetchone()
    finally:
        connection.close()
    return JSONResponse({'notice_id': notice_id, 'available': True, 'conditions': rows,
                         'title': head[0] if head else None,
                         'url': head[1] if head else None,
                         'target_text': (head[2] if head else None)})


def load_test_result():
    """저장된 테스트 결과. `--save-tests` 로 만든 파일이 있으면 보여 준다."""
    path = os.path.join(REPORTS, 'verify_ui', 'test_result.json')
    if not os.path.isfile(path):
        return {'available': False,
                'note': '저장된 테스트 결과가 없다. 아래 명령을 직접 돌린다.',
                'command': TEST_COMMAND}
    data = _read_json(path)
    data['available'] = True
    return data


# ─────────────────────────────────────────────────────────── 직접 검색 비교 (2026-09-21)
#
# 같은 입력을 기존 서비스(8000, 하이브리드·의미 검색만)와 새 방식(정형 필터 → 임베딩)에 넣어
# 결과를 나란히 본다. **서비스 코드는 고치지 않는다** — 8000 의 /api/match 를 HTTP 로 부르기만 한다.
# 새 방식은 이 PC 의 실험 DB 를 SELECT 로만 읽는다. 둘 다 아무것도 저장하지 않는다.
#
# 두 쪽은 보는 공고가 다르다(서비스: 운영 DB 전체 / 새 방식: 9/18 접수 중 스냅샷).
# 검색어도 다르다(서비스는 아이디어에 업종·인증 등을 붙이고, 새 방식은 아이디어만 쓴다).
# 그래서 결과 차이를 '방식의 우열'로 읽지 않도록 화면에 적는다.

SERVICE_URL = os.environ.get('SERVICE_URL', 'http://127.0.0.1:8000')
_LAB_MODEL = [None]
TOP_MIN, TOP_MAX = 1, 10


def call_service(payload, search_mode, timeout=120):
    """기존 서비스 /api/match 호출. 실패하면 예외 대신 {'error': 이유} 를 돌려준다."""
    import urllib.error
    import urllib.request
    body = json.dumps(dict(payload, search=search_mode), ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(SERVICE_URL + '/api/match', data=body,
                                     headers={'Content-Type': 'application/json; charset=utf-8'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.URLError as exc:
        return {'error': '기존 서비스(%s)에 연결하지 못했다: %s. `python -m search.app` 으로 켠다.'
                         % (SERVICE_URL, exc.reason)}
    except Exception as exc:
        return {'error': '기존 서비스 호출 실패: %s: %s' % (type(exc).__name__, exc)}


def run_lab(applicant, top):
    """새 방식(정형 필터 → 임베딩). 모델은 처음 한 번만 올린다."""
    from datetime import date
    from experiments.sql_semantic import search as lab_search
    if _LAB_MODEL[0] is None:
        _LAB_MODEL[0] = embedding.load_model()
    return lab_search.run(applicant, as_of=date.today(), top=top, use_filter=True,
                          model=_LAB_MODEL[0])


def lab_notice_ids():
    """실험 DB 에 들어 있는 공고 ID. 기존 결과가 새 방식 데이터에 아예 없는지 표시하려고 쓴다.

    **요청마다 새로 읽는다.** 처음에는 한 번 읽고 계속 썼는데, 서버를 켠 채 실험 DB 를 재적재하면
    검색은 새 데이터로 하면서 '데이터에 없는 공고' 표시와 건수는 옛 목록을 썼다
    (2026-09-21 Codex /compare 리뷰 P2). 1,852줄 SELECT 라 매번 읽어도 부담이 없다.
    """
    from experiments.sql_semantic import config
    connection = config.connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT notice_id FROM lab_notices')
            return {r[0] for r in cursor.fetchall()}
    finally:
        connection.close()


def parse_top(value, default=5):
    """(값, 오류). 정수만 받고 1~10 으로 자른다. '1.5'·'abc' 는 오류(400) — 조용히 바꾸지 않는다."""
    if value is None or value == '':
        return default, None
    if isinstance(value, bool):
        return None, 'top 은 정수여야 한다'
    if isinstance(value, float):
        if not value.is_integer():
            return None, 'top 은 정수여야 한다 (받은 값: %s)' % value
        value = int(value)
    try:
        number = int(str(value).strip())
    except ValueError:
        return None, 'top 은 정수여야 한다 (받은 값: %s)' % value
    return max(TOP_MIN, min(number, TOP_MAX)), None


def mark_overlap(columns, lab_ids):
    """각 결과에 '어느 방식의 **Top N 목록에** 같이 나왔는지'와 '새 방식 데이터에 있는지'를 붙인다.

    Top N 목록끼리만 비교한다. 목록에 없다는 것은 N위 밖이라는 뜻이지 그 방식이 못 찾았다는 뜻이 아니다
    (2026-09-21 Codex /compare 리뷰 P2 — 'Top 5 에만' 이던 공고가 Top 10 에서는 다른 방식에도 나왔다).
    """
    seen = {}
    for name, rows in columns.items():
        for row in rows:
            seen.setdefault(row['notice_id'], []).append(name)
    for rows in columns.values():
        for row in rows:
            row['also_in'] = seen[row['notice_id']]
            row['in_lab_data'] = None if lab_ids is None else (row['notice_id'] in lab_ids)
    return {nid: names for nid, names in seen.items()}


@app.post('/api/compare')
def api_compare(body: dict):
    """입력 계약은 compare_input.py 에 있다 (2026-09-21 입력 확장).

    검증에 실패하면 검색·모델·DB 를 부르기 **전에** 400 과 칸별 오류를 돌려준다. 오류에는 입력값을 넣지 않는다.
    """
    from experiments.sql_semantic import compare_input
    top, top_error = parse_top(body.get('top') if isinstance(body, dict) else None)
    clean, errors = compare_input.validate(body)
    if top_error:
        errors = list(errors) + [{'field': 'top', 'label': '몇 개씩', 'message': top_error}]
    if errors:
        return JSONResponse({'error': '입력을 확인한다 (%d개 칸)' % len(errors), 'fields': errors},
                            status_code=400)

    service_payload = compare_input.service_payload(clean, top)
    hybrid = call_service(service_payload, 'hybrid')
    dense = call_service(service_payload, 'dense')

    applicant, lab_industry = compare_input.lab_applicant(clean)
    try:
        lab = run_lab(applicant, top)
    except Exception as exc:
        lab = {'error': '새 방식 실행 실패: %s: %s' % (type(exc).__name__, str(exc).splitlines()[0])}
    lab_ids_error = None
    try:
        lab_ids = lab_notice_ids()
    except Exception as exc:
        # 비교는 계속하되, '데이터에 없는 공고' 표시를 왜 못 하는지 화면에 적는다
        lab_ids = None
        lab_ids_error = ('실험 DB 공고 목록을 읽지 못해 "새 방식 데이터에 없는 공고" 표시를 하지 않는다: %s'
                         % type(exc).__name__)

    def rows_of(result, kind):
        if not isinstance(result, dict) or result.get('error'):
            return []
        out = []
        for i, r in enumerate(result.get('results') or [], 1):
            row = {'notice_id': r['notice_id'], 'title': r.get('title'), 'url': r.get('url'),
                   'rank': r.get('rank') or i}
            if kind == 'service':
                row.update(score=r.get('score'), band=r.get('band'), region=r.get('region'),
                           apply_end=r.get('apply_end'), dense_rank=r.get('dense_rank'),
                           bm25_rank=r.get('bm25_rank'))
            else:
                row.update(score=r.get('similarity'), region=r.get('region'),
                           apply_end=r.get('apply_end'), conditions=r.get('conditions'),
                           needs_check=r.get('needs_check'), rank_reason=r.get('rank_reason'))
            out.append(row)
        return out

    columns = {'hybrid': rows_of(hybrid, 'service'), 'dense': rows_of(dense, 'service'),
               'lab': rows_of(lab, 'lab')}
    overlap = mark_overlap(columns, lab_ids)
    return JSONResponse({
        # 개인정보(이름·생년월일·사업자번호)는 되돌려주지 않는다
        'input_summary': compare_input.input_summary(clean),
        'usage': compare_input.field_usage(clean, lab_industry),
        'columns': columns,
        'errors': {k: v.get('error') for k, v in (('hybrid', hybrid), ('dense', dense), ('lab', lab))
                   if isinstance(v, dict) and v.get('error')},
        'meta': {
            'hybrid': {'query': hybrid.get('query'), 'search_ms': hybrid.get('search_ms')}
            if not hybrid.get('error') else None,
            'dense': {'query': dense.get('query'), 'search_ms': dense.get('search_ms')}
            if not dense.get('error') else None,
            'lab': {'query': lab.get('query_text'), 'counts': lab.get('counts'),
                    'as_of_date': lab.get('as_of_date'), 'timing_ms': lab.get('timing_ms'),
                    'encoder_revision': (lab.get('encoder') or {}).get('model_revision')}
            if not lab.get('error') else None,
        },
        'top': top,
        # 겹침은 세 방식의 **Top N 목록 안에서만** 센 것이다. 전체 검색 공간의 공통·독점이 아니다
        'overlap_scope': '세 방식의 Top %d 목록 안에서만 비교했다. 목록에 없다는 것은 %d위 밖이라는 뜻이다.'
                         % (top, top),
        'in_all_three': sorted(nid for nid, names in overlap.items() if len(names) == 3),
        'lab_notice_count': None if lab_ids is None else len(lab_ids),
        'lab_ids_error': lab_ids_error,
        'notes': [
            '두 방식은 보는 공고가 다르다. 기존: 운영 DB 전체(마감 공고는 숨김) · 새 방식: 2026-09-18 접수 중 스냅샷.',
            '검색어가 다르다. 기존은 아이디어에 업종·인증 등을 붙인 문장, 새 방식은 아이디어만 쓴다.',
            '점수는 코사인 유사도(기존 하이브리드는 표시용 유사도)다. 정확도·확률이 아니다.',
            '사람 관련성 판정이 없다. 여기서 보이는 차이로 어느 방식이 낫다고 말하지 않는다.',
        ],
    })


@app.get('/api/compare/form')
def api_compare_form():
    """비교 화면 선택지. 서비스 메인 화면(/api/form)과 **같은 어휘**를 같은 모듈에서 가져온다."""
    from experiments.sql_semantic import compare_input
    from shared import region as region_mod
    labels = {'전남광주': '광주·전남'}
    return JSONResponse({
        'applicant_types': list(compare_input.APPLICANT_TYPES),
        'genders': list(compare_input.GENDERS),
        'regions': [{'value': r, 'label': labels.get(r, r),
                     'districts': list(region_mod.districts_of(r))} for r in region_mod.REGIONS],
        'certifications': list(compare_input.CERTIFICATIONS),
    })


@app.get('/compare/selftest', response_class=HTMLResponse)
def compare_selftest_page():
    """비교 화면의 **브라우저 동작** 자체 시험 (2026-09-21 Codex 리뷰). /api/compare 만 가짜로 바꿔 부른다."""
    with io.open(os.path.join(WEB, 'compare_selftest.html'), encoding='utf-8') as f:
        return f.read()


@app.get('/compare', response_class=HTMLResponse)
def compare_page():
    with io.open(os.path.join(WEB, 'compare.html'), encoding='utf-8') as f:
        return f.read()


@app.post('/api/industry-probe')
def api_industry_probe(body: dict):
    """업종 강조 4변형(그대로·업종 없음·업종 반복·업종 앞배치)을 실제 데이터로 나란히 본다.

    2026-09-22 사용자 요청 — `eval/industry_weight_probe.py` 결론(유의미한 차이 없음)을
    눈으로도 직접 확인할 수 있게. 기존 서비스(8000, `search/app.py` 파일)는 건드리지 않는다.
    이 프로세스 안에서 서비스를 한 번 더 부팅해서 쓴다(첫 요청은 시간이 걸린다).
    """
    from experiments.sql_semantic import industry_probe
    idea = str(body.get('idea') or '').strip()
    applicant_type = str(body.get('applicant_type') or '').strip()
    if not idea or not applicant_type:
        return JSONResponse({'error': '아이디어와 신청자 유형은 필수다'}, status_code=400)
    payload = {'idea': idea, 'applicant_type': applicant_type,
               'founded_at': str(body.get('founded_at') or ''),
               'main_industry': str(body.get('main_industry') or ''),
               'region': str(body.get('region') or '')}
    try:
        out = industry_probe.run(payload, top=5)
    except Exception as exc:
        return JSONResponse({'error': '실행 실패: %s: %s' % (type(exc).__name__, str(exc).splitlines()[0])},
                            status_code=500)
    return JSONResponse(out)


@app.get('/industry-probe', response_class=HTMLResponse)
def industry_probe_page():
    with io.open(os.path.join(WEB, 'industry_probe.html'), encoding='utf-8') as f:
        return f.read()


@app.get('/api/industry-results')
def api_industry_results(run: str = ''):
    """업종 LLM 추출 결과(`reports/industry_llm_*`)를 읽어 보낸다. 읽기 전용 — DB·LLM 호출 없음.

    2026-09-22 사용자 요청 — luna 전량 결과에서 어떤 업종이 됐는지 눈으로 본다.
    """
    from experiments.sql_semantic import industry_results
    name = run or industry_results.default_run()
    data = industry_results.load_run(name)
    if data is None:
        return JSONResponse({'error': '결과 폴더를 찾을 수 없다: %s' % name[:80],
                             'runs': industry_results.list_runs()}, status_code=404)
    data['runs'] = industry_results.list_runs()
    return JSONResponse(data)


@app.get('/industry-results', response_class=HTMLResponse)
def industry_results_page():
    with io.open(os.path.join(WEB, 'industry_results.html'), encoding='utf-8') as f:
        return f.read()


@app.get('/api/health')
def api_health():
    return JSONResponse({'ok': True, 'runs': len(list_runs()),
                         'contract': embedding.CONTRACT, 'read_only': True})


@app.get('/', response_class=HTMLResponse)
def index():
    with io.open(os.path.join(WEB, 'verify.html'), encoding='utf-8') as f:
        return f.read()


def main():
    import argparse
    import uvicorn
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8010)
    args = ap.parse_args()
    print('검증 화면 → http://%s:%d   (읽기 전용 · Ctrl+C 로 종료)' % (args.host, args.port))
    uvicorn.run(app, host=args.host, port=args.port, log_level='warning')
    return 0


if __name__ == '__main__':
    sys.exit(main())
