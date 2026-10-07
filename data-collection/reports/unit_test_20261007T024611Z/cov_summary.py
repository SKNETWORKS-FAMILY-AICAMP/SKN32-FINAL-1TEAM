# -*- coding: utf-8 -*-
"""범위 모듈만 골라 기능별·파일별 줄 커버리지와 기능별 시험 수를 만든다.

  python cov_summary.py <리포트 폴더>
"""
import collections
import io
import json
import os
import sys

import coverage

FEATURES = [
    ('①', '공고 수집', ['collect/daily_job.py', 'collect/fetch.py', 'collect/fetch_bizinfo.py', 'collect/job_lock.py']),
    ('②', '정규화·공용 DB 저장', ['collect/normalize.py', 'shared/store_mysql.py']),
    ('③', '첨부 본문 추출', ['collect/attachment_pipeline.py', 'collect/attachment_store.py', 'collect/doctext.py', 'collect/hwp5.py']),
    ('④', '임베딩·벡터 공유', ['shared/embed.py', 'collect/upload_vectors.py', 'collect/upload_attachments.py', 'search/vecstore.py']),
    ('⑤', 'AI 추출·판정 올리기', ['collect/extract_conditions.py', 'collect/applicant_type_daily.py', 'collect/industry_daily.py',
                            'collect/upload_judgments.py', 'collect/extract_bonus.py',
                            'experiments/sql_semantic/applicant_type_llm.py', 'experiments/sql_semantic/industry_llm_sample.py',
                            'experiments/sql_semantic/industry_groups.py']),
    ('⑥', '매일 배치 흐름', ['collect/daily_pipeline.py']),
    ('⑦', '정형 필터·자격 판정', ['search/gate.py', 'search/eligibility.py', 'search/applicant_types.py', 'search/age_evidence.py']),
    ('⑧', '검색·순위', ['search/app.py', 'search/hybrid.py', 'search/memvec.py', 'search/rank_rules.py',
                     'search/industry_rank.py', 'search/applicant.py', 'shared/region.py']),
    ('⑨', '조율 창구', ['search/notice_api.py', 'search/collection_status.py', 'search/content_version.py']),
    ('⑩', '가산점', ['search/bonus.py']),
    ('⑪', '공통 설정', ['shared/config.py', 'ec2/ec2_vecstore.py']),
]

# 시험 파일 → 기능. 범위 밖 시험(평가 도구·검증 화면·옛 비교)은 넣지 않는다
TEST_FEATURE = {
    'test_fetch': '①', 'test_pipeline': '⑥',
    'test_normalize': '②', 'test_store_mysql': '②',
    'test_attachment_pipeline': '③', 'test_attachment_store': '③', 'test_doctext': '③', 'test_hwp5': '③',
    'test_active_attachments': '③',
    'test_upload_vectors': '④', 'test_upload_attachments': '④',
    'test_extract_conditions_age': '⑤', 'test_applicant_type_daily': '⑤', 'test_industry_daily': '⑤',
    'test_upload_judgments': '⑤', 'test_extract_bonus': '⑤', 'test_applicant_type_llm': '⑤',
    'test_industry_llm_sample': '⑤', 'test_industry_groups': '⑤', 'test_judgments_source': '⑦',
    'test_gate': '⑦', 'test_eligibility': '⑦', 'test_applicant_types': '⑦', 'test_age_evidence': '⑦',
    'test_match_rules': '⑧', 'test_match_deh': '⑧', 'test_memvec': '⑧', 'test_industry_rank': '⑧',
    'test_applicant': '⑧',
    'test_notice_api': '⑨', 'test_collection_status': '⑨',
    'test_bonus': '⑩',
    'test_config': '⑪',
}
NEW = {'test_fetch', 'test_attachment_pipeline', 'test_hwp5', 'test_upload_vectors',
       'test_upload_attachments', 'test_config', 'test_eligibility'}


def main(folder):
    cov = coverage.Coverage(data_file=os.path.join(folder, '.coverage'))
    cov.load()
    root = os.getcwd()
    files, feats = [], []
    tot_s = tot_m = 0
    for mark, name, paths in FEATURES:
        fs = fm = 0
        for rel in paths:
            path = os.path.join(root, *rel.split('/'))
            _, statements, _, missing, _ = cov.analysis2(path)
            s, m = len(statements), len(missing)
            files.append({'feature': mark, 'file': rel, 'statements': s, 'missed': m,
                          'covered': s - m, 'percent': round(100.0 * (s - m) / s, 1) if s else 100.0})
            fs += s
            fm += m
        feats.append({'feature': mark, 'name': name, 'statements': fs, 'missed': fm,
                      'percent': round(100.0 * (fs - fm) / fs, 1) if fs else 100.0})
        tot_s += fs
        tot_m += fm

    with open(os.path.join(folder, 'tests.json'), encoding='utf-8') as f:
        run = json.load(f)
    per = collections.defaultdict(collections.Counter)
    out_scope = collections.Counter()
    new = collections.Counter()
    for t in run['tests']:
        module = t['id'].split('.')[0] if not t['id'].startswith('tests.') else t['id'].split('.')[1]
        t['module'] = module
        mark = TEST_FEATURE.get(module)
        t['feature'] = mark
        if mark:
            per[mark][t['outcome']] += 1
        else:
            out_scope[t['outcome']] += 1
        if module in NEW:
            new[t['outcome']] += 1
    for f in feats:
        c = per[f['feature']]
        f['tests'] = sum(c.values())
        f['passed'] = c['pass']
        f['skipped'] = c['skip']
        f['failed'] = c['fail'] + c['error']

    summary = {
        'run': {k: run[k] for k in ('started_at', 'finished_at', 'python', 'platform', 'total',
                                    'failures', 'errors', 'skipped', 'successful')},
        'scope_coverage': {'statements': tot_s, 'missed': tot_m,
                           'percent': round(100.0 * (tot_s - tot_m) / tot_s, 1)},
        'scope_tests': {k: sum(per[f][k] for f in per) for k in ('pass', 'skip', 'fail', 'error')},
        'out_of_scope_tests': dict(out_scope),
        'new_tests': dict(new),
        'features': feats,
        'files': files,
    }
    with open(os.path.join(folder, 'coverage_summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    with open(os.path.join(folder, 'tests.json'), 'w', encoding='utf-8') as f:
        json.dump(run, f, ensure_ascii=False, indent=1)

    lines = ['# 단위 테스트 결과 — %s' % run['started_at'], '',
             '전체 %d개 · 통과 %d · 실패 %d · 오류 %d · 건너뜀 %d' % (
                 run['total'], run['total'] - run['failures'] - run['errors'] - run['skipped'],
                 run['failures'], run['errors'], run['skipped']),
             '범위 안 줄 커버리지 %.1f%% (%d줄 중 %d줄 실행)' % (
                 summary['scope_coverage']['percent'], tot_s, tot_s - tot_m), '',
             '| 기능 | 시험 | 통과 | 건너뜀 | 실패 | 커버리지 |', '|---|---|---|---|---|---|']
    for f in feats:
        lines.append('| %s %s | %d | %d | %d | %d | %.1f%% |' % (
            f['feature'], f['name'], f['tests'], f['passed'], f['skipped'], f['failed'], f['percent']))
    lines += ['', '| 파일 | 줄 | 실행 | 커버리지 |', '|---|---|---|---|']
    for f in files:
        lines.append('| %s | %d | %d | %.1f%% |' % (f['file'], f['statements'], f['covered'], f['percent']))
    with io.open(os.path.join(folder, 'README.md'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main(sys.argv[1])
