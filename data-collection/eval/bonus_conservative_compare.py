# -*- coding: utf-8 -*-
"""가산점 "확실한 것만 남기기"(2026-10-07) 전후 비교 — 열린 공고 × 가상 신청자.

  .\\.venv\\Scripts\\python.exe -X utf8 -m eval.bonus_conservative_compare
  .\\.venv\\Scripts\\python.exe -X utf8 -m eval.bonus_conservative_compare --old 파일.py   예전 계산을 그 파일로

예전 계산은 git HEAD 의 search/bonus.py(--old 를 주면 그 파일), 새 계산은 작업 폴더의 search/bonus.py 다. 같은 공용 DB 가점(notice_bonus, 추출기 v4)을
지금 공고 내용 지문·추출기 버전으로 걸러 읽고, 가상 신청자 4명마다 null · 0 · 가산점 있음 건수를 센다.
Codex 재검수(10/6)가 짚은 실제 공고의 전후 값도 적는다. 공용 DB SELECT 만, 유료 호출 없음.
결과: reports/bonus_conservative_<UTC 시각>Z/ (summary.md · results.json)
"""
import importlib.util
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

APPLICANTS = {
    '속성 없음': {},
    '여성 · 서울': {'gender': '여성', 'region': '서울'},
    '여성기업 · 벤처기업 · 경기 성남시': {'certifications': ['여성기업', '벤처기업'], 'region': '경기', 'district': '성남시'},
    '남성 · 장애인기업 · 이노비즈 · 전남광주': {'gender': '남성', 'certifications': ['장애인기업', '이노비즈'],
                                       'region': '전남광주'},
}
WATCH = ('bizinfo:PBLN_000000000123858', 'bizinfo:PBLN_000000000117751', 'bizinfo:PBLN_000000000126562',
         'bizinfo:PBLN_000000000125856', 'bizinfo:PBLN_000000000126504', 'bizinfo:PBLN_000000000125935',
         # 10/7 오전 "가산점 있음" 공고(Codex 재검수 B 지적 대상)
         'bizinfo:PBLN_000000000117356', 'bizinfo:PBLN_000000000117928', 'bizinfo:PBLN_000000000120481',
         'bizinfo:PBLN_000000000122057', 'bizinfo:PBLN_000000000122147', 'bizinfo:PBLN_000000000122309',
         'bizinfo:PBLN_000000000126642')


def applicant(**kw):
    base = {'gender': '', 'certifications': [], 'region': '', 'district': '', 'birth_date': '', 'first_startup': None}
    base.update(kw)
    return SimpleNamespace(**base)


def legacy_bonus(path=None):
    """예전 계산을 별도 모듈로 올린다(저장소 파일은 바꾸지 않는다). path 가 없으면 git HEAD 의 search/bonus.py."""
    if path:
        with open(path, encoding='utf-8') as f:
            src = f.read()
    else:
        src = subprocess.run(['git', 'show', 'HEAD:data-collection/search/bonus.py'], cwd=ROOT,
                             capture_output=True, check=True).stdout.decode('utf-8')
    spec = importlib.util.spec_from_loader('bonus_legacy', loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = os.path.join(ROOT, 'search', 'bonus_legacy.py')   # 예전 파일이 자기 위치를 쓰는 경우(목록 경로 등)
    exec(compile(src, 'bonus_legacy.py', 'exec'), mod.__dict__)
    return mod


def open_ids(connection, today):
    with connection.cursor() as cur:
        # 정형 필터와 같은 뜻의 '열린 공고' — 모집 마감(closed)이 아니고 접수 마감일이 지나지 않음(기업마당은 상태가 unknown)
        cur.execute("SELECT notice_id, apply_end FROM notices WHERE recruitment_status <> 'closed'")
        return [nid for nid, end in cur.fetchall() if end is None or end >= today]


def bucket(value):
    return 'null' if value is None else ('0' if value == 0 else '가산점 있음')


def run(say=print, old_path=None):
    from collect.extract_bonus import EXTRACTOR_VERSION
    from search import bonus as new
    from search import content_version
    from shared import store_mysql
    old = legacy_bonus(old_path)
    today = date.today()
    conn = store_mysql.connect()
    try:
        versions = content_version.load(conn)
        table_new = new.load(conn, versions=versions, extractor_version=EXTRACTOR_VERSION)
        table_old = old.load(conn, versions=versions, extractor_version=EXTRACTOR_VERSION)
        ids = open_ids(conn, today)
    finally:
        conn.close()
    rows, changed = [], []
    for label, kw in APPLICANTS.items():
        req = applicant(**kw)
        counts = {'old': {'null': 0, '0': 0, '가산점 있음': 0}, 'new': {'null': 0, '0': 0, '가산점 있음': 0}}
        moved = {}
        for nid in ids:
            o = old.score(table_old.get(nid), req)[0]
            n = new.score(table_new.get(nid), req)[0]
            counts['old'][bucket(o)] += 1
            counts['new'][bucket(n)] += 1
            if o != n:
                key = '%s → %s' % (bucket(o), bucket(n)) if bucket(o) != bucket(n) else '점수 바뀜'
                moved[key] = moved.get(key, 0) + 1
                if len(changed) < 200:
                    changed.append({'applicant': label, 'notice_id': nid, 'old': o, 'new': n})
        rows.append({'applicant': label, 'counts': counts, 'moved': moved})
    watch = []
    for nid in WATCH:
        per = {}
        for label, kw in APPLICANTS.items():
            req = applicant(**kw)
            per[label] = {'old': old.score(table_old.get(nid), req), 'new': new.score(table_new.get(nid), req)}
        watch.append({'notice_id': nid, 'status': (table_new.get(nid) or {}).get('status'),
                      'uncertain': (table_new.get(nid) or {}).get('uncertain'), 'scores': per})
    # 재검수 예시 신청자(벤처기업 + 여성기업)로 123858 을 따로 본다
    vw = applicant(certifications=['벤처기업', '여성기업'])
    example = {'applicant': '벤처기업 · 여성기업', 'notice_id': WATCH[0],
               'old': old.score(table_old.get(WATCH[0]), vw), 'new': new.score(table_new.get(WATCH[0]), vw)}
    move = applicant(region='충남', district='천안시', certifications=['여성기업'])
    example2 = {'applicant': '충남 천안시 · 여성기업', 'notice_id': WATCH[1],
                'old': old.score(table_old.get(WATCH[1]), move), 'new': new.score(table_new.get(WATCH[1]), move)}
    summary = {'made_at': datetime.now(timezone.utc).isoformat(), 'today': today.isoformat(), 'open_notices': len(ids),
               'old': os.path.basename(old_path) if old_path else 'git HEAD search/bonus.py',
               'bonus_rows': len(table_new), 'extractor_version': EXTRACTOR_VERSION, 'applicants': rows,
               'examples': [example, example2]}
    out = os.path.join(ROOT, 'reports', 'bonus_conservative_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    os.makedirs(out)
    with open(os.path.join(out, 'results.json'), 'w', encoding='utf-8') as f:
        json.dump({'summary': summary, 'watch': watch, 'changed_sample': changed}, f, ensure_ascii=False, indent=1,
                  default=str)
    md = summary_md(summary, watch)
    with open(os.path.join(out, 'summary.md'), 'w', encoding='utf-8') as f:
        f.write(md)
    say(md)
    say('→ ' + out)
    return summary, out


def summary_md(s, watch):
    lines = ['# 가산점 "확실한 것만 남기기" 전후 비교', '',
             '- 만든 시각 %s · 기준일 %s · 열린 공고 %d건 · 가점 행 %d건(%s) · 공용 DB SELECT 만'
             % (s['made_at'], s['today'], s['open_notices'], s['bonus_rows'], s['extractor_version']),
             '- 예전 = `%s`, 새 = 작업 폴더 `search/bonus.py`' % s['old'], '',
             '| 가상 신청자 | 예전 null · 0 · 있음 | 새 null · 0 · 있음 | 바뀐 것 |', '|---|---|---|---|']
    for r in s['applicants']:
        o, n = r['counts']['old'], r['counts']['new']
        lines.append('| %s | %d · %d · %d | %d · %d · %d | %s |' % (
            r['applicant'], o['null'], o['0'], o['가산점 있음'], n['null'], n['0'], n['가산점 있음'],
            ', '.join('%s %d' % kv for kv in sorted(r['moved'].items())) or '-'))
    lines += ['', '## 재검수 예시', '']
    for e in s['examples']:
        lines.append('- %s · %s: 예전 %s → 새 %s' % (e['notice_id'], e['applicant'], e['old'], e['new']))
    lines += ['', '## 재검수가 짚은 공고(가상 신청자 4명)', '']
    for w in watch:
        cells = '; '.join('%s %s→%s' % (k, v['old'][0], v['new'][0]) for k, v in w['scores'].items())
        lines.append('- %s (%s, 불확실 %d개): %s' % (w['notice_id'], w['status'], len(w['uncertain'] or []), cells))
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='가산점 계산 전후 비교(공용 DB SELECT 만)')
    ap.add_argument('--old', help='예전 계산으로 쓸 bonus.py 파일(기본: git HEAD)')
    run(old_path=ap.parse_args().old)
