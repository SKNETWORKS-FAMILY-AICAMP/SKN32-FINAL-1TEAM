# -*- coding: utf-8 -*-
"""공고팀 작업 지표 — 수집부터 매칭·운영까지 한 번에 다시 잰다(2026-09-30). 읽기만 한다. OpenAI 호출 없음.

  python -X utf8 -m eval.metrics_report                 공용 DB 조회 + 저장된 결과 파일
  python -X utf8 -m eval.metrics_report --latency       켜져 있는 검색 서비스(8000)에 평가 질의를 보내 응답 시간도 잰다
  python -X utf8 -m eval.metrics_report --tests         전체 unittest 도 돌려 개수를 센다

결과는 reports/metrics_<시각>/metrics.json · summary.md. 기존 결과 폴더는 덮어쓰지 않는다.

영역
  A 수집·운영      공고 수, 배치 성공·가동, 소요 시간, 일일 신규, K-Startup 목록 완전성
  B 전처리 품질    정규화 거부, 접수기간 해석, 마감일 확보, 첨부 본문 추출, 임베딩 적용
  C LLM 추출       판정표 적용 범위, 지문 신선도, 블라인드 판정 일치(9/28 Codex, AI 참고 정답), 하루 비용
  D 매칭           9/28 평가(filter_first_eval): 신청 불가@10, P@3(2), nDCG@10, 쓸모@3 — 처음(벡터만) 대비 지금
  E 평가 신뢰도    판정자 일치(사람 블라인드 143쌍 기준), 상위 10 미판정 비율
  F 서비스·개발    (선택) 응답 시간, 테스트 수, Codex 검수 수
각 지표에 값·기준·근거(파일이나 SQL)를 함께 남긴다. 기준이 없는 것은 '참고'다.
"""
import argparse
import glob
import json
import os
import re
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import common  # noqa: E402

LOG = os.path.join(ROOT, 'data', 'collect_log.jsonl')
RUN_LOG = os.path.join(ROOT, 'data', 'run.log')
KST = timezone(timedelta(hours=9))


def latest(pattern):
    paths = sorted(glob.glob(os.path.join(ROOT, 'reports', pattern)))
    return paths[-1] if paths else None


def pct(n, d):
    return None if not d else n / d


# ── A 수집·운영 ─────────────────────────────────────────────────────────
def collection(cur):
    out = []
    cur.execute('SELECT source, COUNT(*) FROM notices GROUP BY source')
    by_source = dict(cur.fetchall())
    total = sum(by_source.values())
    out.append(('A', '누적 공고 수', total, '참고', '%s' % ', '.join('%s %d' % kv for kv in sorted(by_source.items())),
                'SELECT COUNT(*) FROM notices'))
    rows = [json.loads(l) for l in open(LOG, encoding='utf-8') if l.strip()]
    pipe = [r for r in rows if r.get('job') == 'pipeline']
    by_day = {}
    for r in pipe:                                                           # 날짜마다 가장 긴 실행 한 번(수동 재시도 제외)
        if (r.get('elapsed_sec') or 0) >= 60 and r.get('elapsed_sec') > by_day.get(r['run_at'][:10], {}).get('elapsed_sec', 0):
            by_day[r['run_at'][:10]] = r
    daily = [by_day[d] for d in sorted(by_day)]
    ok = sum(1 for r in pipe if r.get('status') == 'ok')
    out.append(('A', '배치 성공률', pct(ok, len(pipe)), '1.00', '%d/%d회 ok' % (ok, len(pipe)), 'data/collect_log.jsonl job=pipeline'))
    days = sorted({r['run_at'][:10] for r in daily})
    if days:
        span = (date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days + 1
        out.append(('A', '배치 가동일 비율', pct(len(days), span), '1.00',
                    '%d일/%d일 (%s~%s). 배치 PC가 꺼진 날은 돌지 않는다' % (len(days), span, days[0], days[-1]),
                    'collect_log 날짜별 1분 이상 실행'))
        el = [r['elapsed_sec'] for r in daily]
        out.append(('A', '배치 소요 시간(중앙값, 분)', statistics.median(el) / 60, '참고',
                    '최근 %s분' % ', '.join('%.1f' % (x / 60) for x in el[-5:]), 'collect_log elapsed_sec'))
    ks = [r for r in rows if 'job' not in r and r.get('status') == 'ok' and r.get('reported_total')]
    full = sum(1 for r in ks if r.get('count') == r.get('reported_total'))
    out.append(('A', 'K-Startup 목록 완전 수집률', pct(full, len(ks)), '1.00', '%d/%d회 받은 수 = 서버 보고 수' % (full, len(ks)),
                'collect_log count·reported_total'))
    cur.execute('SELECT DATE(CONVERT_TZ(created_at, \'+00:00\', \'+09:00\')) d, COUNT(*) FROM notices '
                'WHERE created_at >= UTC_TIMESTAMP() - INTERVAL 30 DAY GROUP BY d ORDER BY d')
    per_day = [(str(d), n) for d, n in cur.fetchall()]
    recent = [n for d, n in per_day if d >= days[0]] if days else []
    if recent:
        out.append(('A', '배치일 평균 신규 공고', statistics.mean(recent), '참고',
                    '최근: %s' % ', '.join('%s %d' % (d[5:], n) for d, n in per_day[-5:]), 'notices.created_at(한국 날짜)'))
    return out


# ── B 전처리 품질 ────────────────────────────────────────────────────────
def preprocessing(cur):
    out = []
    cur.execute('SELECT report FROM import_runs ORDER BY imported_at DESC LIMIT 1')
    s = json.loads(cur.fetchone()[0]).get('summary') or {}
    acc, rej = s.get('accepted_count', 0), s.get('rejected_count', 0)
    out.append(('B', '정규화 거부율(최근 저장)', pct(rej, acc + rej), '0', '%d/%d건 거부' % (rej, acc + rej), 'import_runs.report.summary'))
    cur.execute('SELECT apply_period_type, COUNT(*) FROM notices GROUP BY 1')
    types = dict(cur.fetchall())
    n = sum(types.values())
    out.append(('B', '접수기간 해석률', pct(n - types.get('unknown', 0), n), '참고',
                ', '.join('%s %d' % kv for kv in sorted(types.items())), 'notices.apply_period_type ≠ unknown'))
    cur.execute('SELECT COUNT(*) FROM notices WHERE apply_end IS NOT NULL')
    out.append(('B', '마감일 확보율', pct(cur.fetchone()[0], n), '참고',
                '없는 공고는 예산 소진·상시·선착순·정보 없음', 'notices.apply_end IS NOT NULL'))
    cur.execute("SELECT t.last_status, COUNT(*) FROM attachment_texts t JOIN notice_attachments a ON a.id=t.attachment_fk "
                "WHERE a.active GROUP BY 1")
    st = dict(cur.fetchall())
    m = sum(st.values())
    out.append(('B', '첨부 공고문 본문 추출 성공률', pct(st.get('ok', 0), m), '참고',
                ', '.join('%s %d' % kv for kv in sorted(st.items())), 'attachment_texts.last_status (활성 첨부)'))
    cur.execute('SELECT COUNT(*) FROM notices WHERE embedding IS NOT NULL')
    out.append(('B', '임베딩 적용률', pct(cur.fetchone()[0], n), '1.00', 'BGE-M3 1024차원', 'notices.embedding IS NOT NULL'))
    return out


# ── C LLM 추출 ──────────────────────────────────────────────────────────
def llm(cur, connection):
    out = []
    cur.execute('SELECT COUNT(*) FROM notices')
    n = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT n.id) FROM notices n JOIN notice_attachments a ON a.notice_fk=n.id "
                "JOIN attachment_texts t ON t.attachment_fk=a.id WHERE a.active AND t.last_status='ok'")
    eligible = cur.fetchone()[0]
    for table, base, label in (('notice_conditions', eligible, '자격요건(금액·형태·업력) — 본문 있는 공고 대비'),
                               ('notice_applicant_types', n, '신청자 유형 — 전체 공고 대비'),
                               ('notice_industries', n, '업종 — 전체 공고 대비')):
        cur.execute('SELECT COUNT(*) FROM ' + table)
        k = cur.fetchone()[0]
        out.append(('C', '판정표 적용 범위: ' + label.split(' — ')[0], pct(k, base), '1.00',
                    '%d/%d (%s)' % (k, base, label.split(' — ')[1]), table))
    from search import applicant_types
    t0 = time.time()
    r = applicant_types.load_auto(connection)
    out.append(('C', '신청자 유형 판정 지문 신선도', pct(r.get('fresh_from_db', 0) + r.get('refreshed_from_file', 0), n), '1.00',
                '지문 다름 %s · 발췌 밖 확인 필요 %s · %.1f초' % (r.get('stale'), r.get('unread_pre_founder'), time.time() - t0),
                'applicant_types.load_auto'))
    score = os.path.join(ROOT, 'reports', 'label_pack_20260928', 'score.json')
    if os.path.exists(score):
        s = json.load(open(score, encoding='utf-8'))
        g = s['gate_pre_strong']
        out.append(('C', '예비창업자 "명시 불가" 판정 정밀도', g['rate'], '1.00 (잘못 빼면 안 됨)',
                    '%d/%d · 신청 가능한 공고를 뺄 오류 %d건 (Codex 블라인드, AI 참고 정답)' % (g['hit'], g['total'], len(s['gate_pre_strong_wrong_allowed'])),
                    'reports/label_pack_20260928/score.json'))
        a = s['agreement']
        out.append(('C', '신청자 유형 판정 일치율', a['pre_founder']['rate'], '참고',
                    '예비창업자 %d/%d · 개인사업자 %d/%d · 법인 %d/%d' % (a['pre_founder']['hit'], a['pre_founder']['total'],
                                                                   a['sole_proprietor']['hit'], a['sole_proprietor']['total'],
                                                                   a['corporation']['hit'], a['corporation']['total']),
                    'label_pack_20260928 (93건)'))
        w = s.get('industry_wrong_push')
        wn = len({x['notice_id'] for x in w}) if isinstance(w, list) else None
        out.append(('C', '업종 순위의 부당 밀림(공고)', pct(wn, s['industry_labeled']) if wn is not None else None, '낮을수록 · 서비스 꺼짐',
                    '%s/%d 공고 — 그래서 업종 순위는 기본 꺼짐' % (wn, s['industry_labeled']), 'label_pack_20260928'))
    costs = defaultdict(float)
    if os.path.exists(RUN_LOG):
        day = None
        for line in open(RUN_LOG, encoding='utf-8', errors='replace'):
            m = re.match(r'\[(\d{4}-\d{2}-\d{2})\s', line)
            if m:
                day = m.group(1)
            m = re.search(r'약 \$([0-9.]+)', line)
            if m and day:
                costs[day] += float(m.group(1))
    recent = sorted(costs.items())[-5:]
    if recent:
        out.append(('C', '하루 LLM 비용(신청자 유형+업종, USD)', statistics.mean(v for _, v in recent), '참고',
                    ', '.join('%s $%.3f' % (d[5:], v) for d, v in recent) + ' · 자격요건 추출은 로그에 금액이 없어 빠짐',
                    'data/run.log "약 $"'))
    return out


# ── D 매칭 · E 평가 신뢰도 ──────────────────────────────────────────────
def matching():
    out = []
    path = latest('filter_first_eval_*')
    if not path:
        return out
    d = json.load(open(os.path.join(path, 'results.json'), encoding='utf-8'))
    s, meta = d['summary']['hybrid'], d['meta']
    name = os.path.basename(path)
    for key, target in (('ineligible_k', '0'), ('p3_lo', '높을수록'), ('p3_hi', '높을수록'), ('ndcg_k', '높을수록'),
                        ('useful3_lo', '높을수록')):
        x = s[key]
        diff = x['diff_vs_vector']
        out.append(('D', x['label'], x['filter_first'], target,
                    '처음(벡터만) %.3f → 지금 %.3f · 차이 %+.3f [%+.3f, %+.3f]' % ((x['vector_only'], x['filter_first']) + tuple(diff)),
                    '%s · 질의 %d · 판정 %d쌍' % (name, meta['queries'], meta['qrels_pairs'])))
    out.append(('E', '상위 10 미판정 비율', s['unjudgedk']['filter_first'], '낮을수록 (지금 방식)',
                '판정이 없는 칸 — 높으면 D 지표의 하한·상한이 벌어진다', name))
    jev = latest('jev_judge_probe_*')
    if jev:
        j = json.load(open(os.path.join(jev, 'summary.json'), encoding='utf-8'))
        same = j.get('same_pairs') or {}
        for who, label in (('llm_gpt41mini_A', 'LLM(gpt-4.1-mini)'), ('jev', 'Jev')):
            x = same.get(who)
            if x:
                out.append(('E', '판정자 일치율: %s vs 사람' % label, x['exact'], '≥0.70 (merge_qrels.TRUST)',
                            '가중 카파 %.2f (기준 ≥0.60) · 0↔2 뒤바뀜 %.1f%% (기준 ≤3%%) · n=%d' % (x['kappa'], 100 * x['swap02'], x['n']),
                            os.path.basename(jev)))
    codex = os.path.join(ROOT, 'reports', 'relevance_label_pack_20260930', 'score.json')
    if os.path.exists(codex):
        c = json.load(open(codex, encoding='utf-8'))
        out.append(('E', '판정자 일치율: Codex vs 사람(대조군)', c['exact'], '≥0.70',
                    '가중 카파 %s · 대조군 %d쌍' % (c['weighted_kappa'] and '%.2f' % c['weighted_kappa'], c['controls']),
                    'relevance_label_pack_20260930/score.json'))
    return out


# ── F 서비스·개발 (선택) ─────────────────────────────────────────────────
def latency(url='http://127.0.0.1:8000'):
    import urllib.request
    out = []
    try:
        health = json.loads(urllib.request.urlopen(url + '/api/health', timeout=5).read())
    except Exception as exc:
        return [('F', '검색 서비스 응답 시간', None, '참고', '8000이 꺼져 있어 재지 않음 (%s)' % type(exc).__name__, url)]
    times = []
    for q in [q for q in common.load_queries().values() if q['kind'] == 'normal']:
        body = json.dumps(dict(q['payload'], top=10)).encode('utf-8')
        req = urllib.request.Request(url + '/api/match', data=body, headers={'Content-Type': 'application/json'})
        t0 = time.time()
        urllib.request.urlopen(req, timeout=60).read()
        times.append((time.time() - t0) * 1000)
    times.sort()
    p95 = times[max(0, int(len(times) * 0.95) - 1)]
    out.append(('F', '매칭 응답 시간 중앙값(ms)', statistics.median(times), '참고',
                'p95 %.0fms · 최대 %.0fms · 질의 %d개 · 공고 %s건' % (p95, times[-1], len(times), health.get('notices')),
                url + '/api/match (첫 조회 10건, 이 PC)'))
    return out


def dev_stats(run_tests):
    out = []
    reviews = [p for p in glob.glob(os.path.join(ROOT, 'docs', 'reviews', '*', '*.md'))
               if re.search(r'_REVIEW(_RECHECK\d*)?_\d{8}\.md$', p) or re.search(r'_RESULT_\d{8}\.md$', p)]
    out.append(('F', 'Codex 검수·판정 결과 문서 수', len(reviews), '참고', '요청·응답 문서 제외', 'docs/reviews/*/'))
    if run_tests:
        r = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'unittest', 'discover', '-s', 'tests'], cwd=ROOT,
                           capture_output=True, text=True, encoding='utf-8')
        m = re.search(r'Ran (\d+) tests', r.stderr)
        ok = '\nOK' in r.stderr
        out.append(('F', '자동 테스트 수', int(m.group(1)) if m else None, '모두 통과',
                    ('통과' if ok else '실패 있음') + (' · ' + re.search(r'OK \((.*)\)', r.stderr).group(1) if ok and '(' in r.stderr.split('\nOK')[-1] else ''),
                    'unittest discover -s tests'))
    return out


AREAS = {'A': '수집·운영', 'B': '전처리 품질', 'C': 'LLM 추출', 'D': '매칭 (9/28 평가, 하이브리드)',
         'E': '평가 신뢰도', 'F': '서비스·개발'}


def fmt(v):
    if v is None:
        return '-'
    if isinstance(v, float):
        return '%.3f' % v if v < 10 else '%.1f' % v
    return str(v)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--latency', action='store_true')
    ap.add_argument('--tests', action='store_true')
    ap.add_argument('--out')
    args = ap.parse_args(argv)
    started = datetime.now(KST)
    from shared import store_mysql
    connection = store_mysql.connect()
    try:
        with connection.cursor() as cur:
            rows = collection(cur) + preprocessing(cur) + llm(cur, connection)
    finally:
        connection.close()
    rows += matching()
    if args.latency:
        rows += latency()
    rows += dev_stats(args.tests)

    out_dir = args.out or os.path.join(ROOT, 'reports', 'metrics_' + started.strftime('%Y%m%dT%H%M%S'))
    os.makedirs(out_dir, exist_ok=False)
    items = [{'area': a, 'name': n, 'value': v, 'target': t, 'detail': d, 'source': s} for a, n, v, t, d, s in rows]
    json.dump({'run_at': started.isoformat(timespec='seconds'), 'metrics': items}, open(os.path.join(out_dir, 'metrics.json'), 'w',
              encoding='utf-8'), ensure_ascii=False, indent=1)
    lines = ['# 공고팀 작업 지표 (%s)' % started.strftime('%Y-%m-%d %H:%M KST'), '',
             '- 공용 DB는 조회만 했다. OpenAI 호출 0. 비율은 0~1. 매칭 수치는 9/28 평가 결과 파일에서 읽었다.',
             '- 판정 기반 수치(C 블라인드 일치, D 매칭)는 **AI 참고 정답·LLM 판정**을 포함한다. 약점은 E에 있다.', '']
    for area, title in AREAS.items():
        part = [x for x in items if x['area'] == area]
        if not part:
            continue
        lines += ['## %s %s' % (area, title), '', '| 지표 | 값 | 기준·목표 | 내용 | 근거 |', '|---|---:|---|---|---|']
        lines += ['| %s | %s | %s | %s | `%s` |' % (x['name'], fmt(x['value']), x['target'], x['detail'], x['source']) for x in part]
        lines.append('')
    md = '\n'.join(lines)
    open(os.path.join(out_dir, 'summary.md'), 'w', encoding='utf-8').write(md)
    print(md)
    print('결과:', out_dir)


if __name__ == '__main__':
    main()
