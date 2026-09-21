# -*- coding: utf-8 -*-
"""새 경로(정형 필터 + 의미 검색)를 실행하고 기존 결과와 나란히 보여 준다.

  python -X utf8 -m experiments.sql_semantic.compare
  python -X utf8 -m experiments.sql_semantic.compare --baseline reports/search_comparison_.../

입력은 기존 비교와 같은 10개(`inputs.jsonl`)를 쓴다. **기존 파일은 수정하지 않는다.**
각 입력마다 정형 필터 **켬/끔** 두 번 실행해, 같은 임베딩·같은 정렬에서 필터의 효과만 본다.

과거 dense/hybrid 열은 **참고용**이다. 그때와 지금은 공고 집합·임베딩 계약·기준일이 다르고,
과거 실행의 Chroma 내용은 미검증이다. 순위 차이를 새 구조의 개선량이라고 말하지 않는다(지시서 7절).
"""
import argparse
import glob
import hashlib
import html
import io
import json
import os
import sys
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from experiments.sql_semantic import conditions, config, embedding, search  # noqa: E402

REPORTS = os.path.join(ROOT, 'reports')
TOP = 5


def latest_baseline():
    folders = sorted(glob.glob(os.path.join(REPORTS, 'search_comparison_*')))
    folders = [f for f in folders if not f.endswith('_INVALID_date_changed')]
    return folders[-1] if folders else None


def read_jsonl(path):
    return [json.loads(line) for line in io.open(path, encoding='utf-8') if line.strip()]


def write_jsonl(path, rows):
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')


def applicant_from(case):
    """기존 입력(payload) → 새 경로의 신청자 값. 없는 정보를 지어내지 않는다."""
    p = case['payload']
    return {
        'idea': p.get('idea') or '',
        'region': p.get('region') or '',
        'district': p.get('district') or '',
        'founded_at': p.get('founded_at') or '',
        'prestartup': (p.get('applicant_type') == '예비창업자'),
        'preferred_support_type': '',      # 기존 입력에 없다. 가상으로 채우지 않는다
    }


def data_quality(connection):
    """실험 DB 의 정형 필드 확보율·벡터 상태. 실제 저장된 값을 센다."""
    out = {'conditions': {}, 'vectors': {}}
    with connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM lab_notices')
        out['notices'] = cursor.fetchone()[0]
        cursor.execute('SELECT field, status, COUNT(*) FROM lab_conditions GROUP BY field, status')
        for field, status, count in cursor.fetchall():
            out['conditions'].setdefault(field, {})[status] = count
        cursor.execute('SELECT COUNT(*), MIN(dim), MAX(dim) FROM lab_vectors WHERE contract=%s',
                       (embedding.CONTRACT,))
        count, dim_min, dim_max = cursor.fetchone()
        out['vectors'] = {'count': count, 'dim_min': dim_min, 'dim_max': dim_max,
                          'contract': embedding.CONTRACT}
        cursor.execute('SELECT COUNT(*) FROM lab_notices n LEFT JOIN lab_vectors v '
                       ' ON v.notice_id=n.notice_id AND v.contract=%s WHERE v.notice_id IS NULL',
                       (embedding.CONTRACT,))
        out['vectors']['without_vector'] = cursor.fetchone()[0]
    for field, counts in out['conditions'].items():
        total = sum(counts.values()) or 1
        counts['known_ratio'] = round((counts.get('known', 0) + counts.get('no_limit', 0)) / total, 3)
    return out


def esc(value):
    return html.escape(str(value if value is not None else ''))


def build_html(path, cases, responses, baseline_rows, manifest):
    by_key = {(r['case_id'], r['mode']): r for r in responses}
    base = {}
    for row in baseline_rows or []:
        if row['stage'] == 'B':
            base[(row['case_id'], row['search'])] = row['response']['results']

    parts = ["""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>정형 필터 + 의미 검색 — 기존 방식과 비교</title><style>
body{margin:0;background:#f7f8fa;color:#23282f;font:14px/1.65 "맑은 고딕","Malgun Gothic",system-ui,sans-serif}
.wrap{max-width:1400px;margin:0 auto;padding:24px 16px 70px}
h1{font-size:22px;color:#1f3864;margin:0 0 6px}h2{font-size:16px;color:#1f3864;margin:24px 0 8px}
.card{background:#fff;border:1px solid #d8dee9;border-radius:10px;padding:16px;margin-bottom:14px}
.cols{display:flex;gap:12px;flex-wrap:wrap}.col{flex:1 1 320px;min-width:300px}
.col h3{font-size:13.5px;margin:0 0 6px;color:#1f3864}
.hit{border:1px solid #e6e9ef;border-radius:8px;padding:8px 10px;margin-bottom:6px;font-size:12.5px}
.hit .t{font-weight:bold}.meta{color:#6b7280;font-size:11.5px;margin-top:2px}
.note{font-size:12.5px;color:#6b7280}.warn{background:#fff8e6;border:1px solid #f0d9a8;
border-radius:8px;padding:10px 12px;font-size:12.5px;margin-bottom:14px}
.tag{display:inline-block;background:#eef1f6;border-radius:9px;padding:1px 7px;font-size:11px;color:#44506b;margin-right:4px}
.check{color:#9a6b1f}.ok{color:#2f7a45}
table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid #eceff4;padding:6px 8px;
text-align:left;font-size:12.5px}th{background:#f4f6fa;color:#55617a;font-size:12px}
</style></head><body><div class="wrap">"""]
    parts.append('<h1>정형 필터 + 의미 검색 — 기존 방식과 비교</h1>')
    parts.append('<div class="warn"><b>읽는 법.</b> 왼쪽 두 열은 <b>참고용</b>이다. '
                 '과거 실행(%s)은 공고 집합·임베딩 계약·기준일이 지금과 다르고 Chroma 내용이 미검증이다. '
                 '순위 차이를 새 구조의 개선량으로 읽지 않는다. 오른쪽 두 열(필터 켬/끔)만 '
                 '같은 데이터·같은 임베딩·같은 정렬에서 비교한 것이다.</div>'
                 % esc(manifest.get('baseline_folder') or '없음'))
    parts.append('<div class="card"><table><tr><th>항목</th><th>값</th></tr>'
                 + ''.join('<tr><td>%s</td><td>%s</td></tr>' % (esc(k), esc(v)) for k, v in (
                     ('실행 시각', manifest['run_at']), ('기준일', manifest['as_of_date']),
                     ('실험 DB 공고 수', manifest['data_quality']['notices']),
                     ('벡터 수', manifest['data_quality']['vectors']['count']),
                     ('임베딩 계약', embedding.CONTRACT),
                     ('모델', '%s (%s)' % (embedding.MODEL, manifest['model_revision'])),
                     ('비교 가능 여부', manifest['comparable'])))
                 + '</table></div>')

    for case in cases:
        cid = case['case_id']
        parts.append('<div class="card"><h2>%s · %s (%s)</h2><p class="note">%s</p>'
                     % (esc(cid), esc(case['category']), esc(case['qid']),
                        esc(case['payload'].get('idea'))))
        parts.append('<div class="cols">')
        for label, rows in (('과거 dense (참고)', base.get((cid, 'dense'))),
                            ('과거 hybrid (참고)', base.get((cid, 'hybrid')))):
            items = ''.join('<div class="hit"><div class="t">%d. %s</div>'
                            '<div class="meta">유사도 %s</div></div>'
                            % (i, esc(r['title']), esc(r.get('score')))
                            for i, r in enumerate(rows or [], 1)) or '<div class="note">없음</div>'
            parts.append('<div class="col"><h3>%s</h3>%s</div>' % (esc(label), items))
        for mode, label in (('filter_on', '새 방식 · 정형 필터 켬'), ('filter_off', '새 방식 · 필터 끔')):
            out = by_key.get((cid, mode))
            if not out:
                parts.append('<div class="col"><h3>%s</h3><div class="note">없음</div></div>' % esc(label))
                continue
            res = out['response']
            items = []
            for r in res['results']:
                checks = ' '.join('<span class="tag %s">%s %s</span>'
                                  % ('ok' if v['verdict'] == 'ok' else 'check',
                                     esc(k), esc(v['why'])[:24])
                                  for k, v in (r.get('conditions') or {}).items())
                items.append('<div class="hit"><div class="t">%d. %s</div>'
                             '<div class="meta">유사도 %s · %s</div><div class="meta">%s</div></div>'
                             % (r['rank'], esc(r['title']), esc(r['similarity']),
                                esc(r['rank_reason']), checks))
            counts = res['counts']
            parts.append('<div class="col"><h3>%s</h3>'
                         '<div class="note">SQL 후보 %d → 조건 통과 %d → 비교 %d → 반환 %d '
                         '(벡터 없음 %d · 손상 %d)</div>%s</div>'
                         % (esc(label), counts['rows_from_sql'], counts['after_conditions'],
                            counts['compared'], counts['returned'], counts['missing_vector'],
                            counts['broken_vector'],
                            ''.join(items) or '<div class="note">결과 없음</div>'))
        parts.append('</div></div>')
    parts.append('</div></body></html>')
    io.open(path, 'w', encoding='utf-8', newline='\n').write('\n'.join(parts))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--baseline', default=None, help='기존 비교 결과 폴더')
    ap.add_argument('--as-of', dest='as_of', default='')
    ap.add_argument('--top', type=int, default=TOP)
    args = ap.parse_args()

    baseline = args.baseline or latest_baseline()
    if not baseline or not os.path.isdir(baseline):
        print('기존 비교 결과 폴더를 찾지 못했다. --baseline 으로 지정한다.')
        return 2
    cases = read_jsonl(os.path.join(baseline, 'inputs.jsonl'))
    baseline_rows = read_jsonl(os.path.join(baseline, 'responses.jsonl'))
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()

    try:
        lab = config.lab_settings()
        config.guard(lab)
    except config.LabConfigError as exc:
        print('실험 DB 설정 확인 실패\n%s' % exc)
        return 2

    connection = config.connect()
    run_at = datetime.now(timezone.utc)
    stamp = run_at.strftime('%Y%m%dT%H%M%SZ')
    outdir = os.path.join(REPORTS, 'sql_semantic_' + stamp)
    os.makedirs(outdir, exist_ok=True)
    try:
        quality = data_quality(connection)
        if not quality['vectors']['count']:
            print('실험 DB 에 벡터가 없다. prepare.py --embed 를 먼저 돌린다.')
            return 3
        model = embedding.load_model()
        responses = []
        for case in cases:
            applicant = applicant_from(case)
            for mode, use_filter in (('filter_on', True), ('filter_off', False)):
                out = search.run(applicant, as_of=as_of, top=args.top, use_filter=use_filter,
                                 connection=connection, model=model)
                responses.append({'case_id': case['case_id'], 'qid': case['qid'], 'mode': mode,
                                  'at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                                  'response': out})
            counts = {r['mode']: r['response']['counts'] for r in responses
                      if r['case_id'] == case['case_id']}
            print('  %s %s  필터 켬 %d건 / 끔 %d건' % (
                case['case_id'], case['qid'], counts['filter_on']['returned'],
                counts['filter_off']['returned']))
    finally:
        connection.close()

    code_hash = hashlib.sha256(
        b''.join(io.open(os.path.join(HERE, name), 'rb').read()
                 for name in sorted(os.listdir(HERE)) if name.endswith('.py'))).hexdigest()
    manifest = {
        'task': 'docs/SQL_SEMANTIC_EXPERIMENT_TASK_20260918.md',
        'run_at': run_at.isoformat(timespec='seconds'),
        'as_of_date': as_of.isoformat(),
        'baseline_folder': os.path.relpath(baseline, ROOT),
        'comparable': '아니오 — 과거 열은 참고용 (공고 집합·임베딩 계약·기준일이 다르고 Chroma 내용 미검증)',
        'lab': config.describe(lab),
        'embedding': embedding.meta(),
        'model_revision': embedding.model_revision(),
        'experiment_code_sha256': code_hash,
        'condition_extractor': conditions.EXTRACTOR,
        'top': args.top,
        'data_quality': quality,
        'counts': {'cases': len(cases), 'responses': len(responses)},
    }
    write_jsonl(os.path.join(outdir, 'inputs.jsonl'), cases)
    write_jsonl(os.path.join(outdir, 'responses.jsonl'), responses)
    with io.open(os.path.join(outdir, 'manifest.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    with io.open(os.path.join(outdir, 'data_quality.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(quality, f, ensure_ascii=False, indent=1)
    build_html(os.path.join(outdir, 'comparison.html'), cases, responses, baseline_rows, manifest)
    print('\n결과 → %s' % outdir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
