# -*- coding: utf-8 -*-
"""수집 상태 — 매칭 전에 "공고 데이터가 믿을 만큼 새것인가"를 판정한다 (2026-09-28, 기획서 대조 F).

기능정의서 v1.9
  R-1 출력   collectionStatus: enum('정상','지연','실패'), lastRunAt
  R-1 ①     소스 응답 실패 → 재시도 후 collectionStatus='실패'로 기록하고 화면에 표시한다. 조용한 실패 금지
  R-3 ②     collectionStatus='실패' 또는 최종 수집 시각이 24시간 초과 → 매칭을 진행하지 않고 수집 상태 경고(E-C2-STALE)

판정 (강한 것부터)
  실패   ① 저장 기록(import_runs)이 하나도 없다
         ② 가장 최근 배치 로그가 error 다(저장 전 단계에서 멈춤 — 기존 데이터를 그대로 둔다)
         ③ 가장 최근 배치에서 출처 하나라도 실패했다(partial). 그 출처는 직전 데이터를 재사용한 것이다
         ④ 기업마당 입력 스냅샷이 마지막 저장보다 max_age 이상 오래됐다(DB 만으로 아는 재사용)
  지연   마지막 저장 성공(import_runs.imported_at)이 max_age(기본 24시간)를 넘었다
  정상   그 밖
  실패·지연이면 block_matching=True — 매칭하지 않고 경고한다.

읽는 곳
  DB    공용 MySQL import_runs 의 가장 최근 행(imported_at 은 UTC). EC2 서비스도 읽을 수 있다
  로그  data/collect_log.jsonl 의 가장 최근 배치(job='pipeline') 행. 배치를 돌리는 PC 에만 있다. 없으면 DB 만으로 판정한다
        (로그 run_at 은 배치 PC 의 현지 시각 — 한국 시간으로 본다)

읽기 전용이다. DB 에 쓰지 않는다. 판정 규칙은 judge() 순수 함수에 있고 tests/test_collection_status.py 가 고정한다.
"""
import io
import json
import os
import re
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG = os.path.join(ROOT, 'data', 'collect_log.jsonl')
MAX_AGE_HOURS = 24
KST = timezone(timedelta(hours=9))
_BIZINFO_STAMP = re.compile(r'bizinfo_(\d{8}T\d{6})\d*Z\.json')


def _utc(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def bizinfo_snapshot_at(report):
    """import_runs.report 의 기업마당 입력 파일 이름 → 그 스냅샷을 받은 시각(UTC). 없으면 None."""
    for item in (report or {}).get('inputs') or []:
        if item.get('source') == 'bizinfo':
            m = _BIZINFO_STAMP.search(os.path.basename(item.get('input_file') or '').replace('\\', '/'))
            if m:
                return datetime.strptime(m.group(1), '%Y%m%dT%H%M%S').replace(tzinfo=timezone.utc)
    return None


def judge(last_store_at, now, latest_batch=None, bizinfo_at=None, max_age_hours=MAX_AGE_HOURS):
    """판정 순수 함수.

    last_store_at  마지막 저장 성공 시각(UTC aware) 또는 None
    latest_batch   {'status': 'ok'|'partial'|'error', 'run_at': aware datetime, 'degraded': [...], 'error': str} 또는 None
    bizinfo_at     마지막 저장에 쓰인 기업마당 스냅샷 시각(UTC aware) 또는 None
    """
    reasons = []
    status = '정상'
    max_age = timedelta(hours=max_age_hours)
    age_hours = None
    if last_store_at is None:
        status = '실패'
        reasons.append('저장 기록(import_runs)이 없다')
    else:
        age = now - last_store_at
        age_hours = round(age.total_seconds() / 3600, 1)
        if age > max_age:
            status = '지연'
            reasons.append('마지막 수집 저장이 %.1f시간 전이다(기준 %d시간)' % (age_hours, max_age_hours))
    if latest_batch:
        newer = last_store_at is None or latest_batch['run_at'] >= last_store_at - timedelta(minutes=10)
        if latest_batch.get('status') == 'error' and newer:
            status = '실패'
            reasons.append('가장 최근 배치가 실패했다: %s' % (latest_batch.get('error') or '원인 미기록'))
        elif latest_batch.get('status') == 'partial' and newer:
            status = '실패'
            reasons.append('가장 최근 배치에서 출처가 실패해 직전 데이터를 재사용했다: %s'
                           % ', '.join(latest_batch.get('degraded') or ['(출처 미기록)']))
    if bizinfo_at is not None and last_store_at is not None and last_store_at - bizinfo_at > max_age:
        status = '실패'
        reasons.append('기업마당 입력이 %.1f시간 전 스냅샷이다(재사용)'
                       % ((last_store_at - bizinfo_at).total_seconds() / 3600))
    return {'status': status, 'block_matching': status != '정상', 'reasons': reasons,
            'last_run_at': last_store_at.isoformat() if last_store_at else None, 'age_hours': age_hours,
            'max_age_hours': max_age_hours}


def read_latest_store(connection):
    """(imported_at UTC, report dict) — import_runs 가장 최근 행. 없으면 (None, None)."""
    with connection.cursor() as cur:
        cur.execute('SELECT imported_at, report FROM import_runs ORDER BY imported_at DESC LIMIT 1')
        row = cur.fetchone()
    if not row:
        return None, None
    report = row[1]
    if isinstance(report, (bytes, str)):
        report = json.loads(report)
    return _utc(row[0]), report


def read_latest_batch(path=LOG):
    """배치 로그의 가장 최근 pipeline 행. 파일이 없으면 None."""
    if not os.path.exists(path):
        return None
    last = None
    with io.open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get('job') == 'pipeline':
                last = row
    if not last:
        return None
    run_at = datetime.fromisoformat(last['run_at'])
    run_at = run_at.replace(tzinfo=KST) if run_at.tzinfo is None else run_at
    return {'status': last.get('status'), 'run_at': run_at.astimezone(timezone.utc),
            'degraded': last.get('degraded') or [], 'error': last.get('error'),
            'sources': last.get('sources') or {},
            # 후처리(LLM) 경고. 매칭을 막지 않는다 — 공고 데이터 자체는 새것이다(2026-09-28)
            'stage_warnings': last.get('stage_warnings') or []}


def check(connection=None, now=None, log_path=LOG, max_age_hours=MAX_AGE_HOURS):
    """지금 수집 상태. connection 을 주지 않으면 공용 MySQL 에 잠깐 붙는다(SELECT 만)."""
    now = now or datetime.now(timezone.utc)
    own = connection is None
    if own:
        from shared import store_mysql
        connection = store_mysql.connect()
    try:
        last_store_at, report = read_latest_store(connection)
    finally:
        if own:
            connection.close()
    batch = read_latest_batch(log_path)
    biz_at = bizinfo_snapshot_at(report)
    out = judge(last_store_at, now, batch, biz_at, max_age_hours)
    out.update({
        'checked_at': now.isoformat(),
        'basis': ['db'] + (['log'] if batch else []),
        'latest_batch': ({'status': batch['status'], 'run_at': batch['run_at'].isoformat(),
                          'sources': batch['sources'], 'stage_warnings': batch.get('stage_warnings') or []}
                         if batch else None),
        'bizinfo_snapshot_at': biz_at.isoformat() if biz_at else None,
        'stored_counts': ((report or {}).get('summary') or {}).get('input_counts'),
    })
    return out


def history(connection=None, max_age_hours=MAX_AGE_HOURS):
    """import_runs 전체 → 저장 시각 목록과 "매칭이 멈췄을" 구간(간격이 max_age 를 넘은 만큼). 화면 참고용."""
    own = connection is None
    if own:
        from shared import store_mysql
        connection = store_mysql.connect()
    try:
        with connection.cursor() as cur:
            cur.execute('SELECT imported_at, notice_count FROM import_runs ORDER BY imported_at')
            rows = [(_utc(r[0]), r[1]) for r in cur.fetchall()]
    finally:
        if own:
            connection.close()
    max_age = timedelta(hours=max_age_hours)
    gaps, blocked = [], timedelta()
    for (a, _n), (b, _m) in zip(rows, rows[1:]):
        if b - a > max_age:
            gaps.append({'from': a.isoformat(), 'to': b.isoformat(), 'gap_hours': round((b - a).total_seconds() / 3600, 1),
                         'blocked_hours': round((b - a - max_age).total_seconds() / 3600, 1)})
            blocked += b - a - max_age
    span = (rows[-1][0] - rows[0][0]) if len(rows) > 1 else timedelta()
    return {'runs': [{'at': t.isoformat(), 'notices': n} for t, n in rows], 'gaps': gaps,
            'blocked_hours': round(blocked.total_seconds() / 3600, 1),
            'span_days': round(span.total_seconds() / 86400, 1), 'max_age_hours': max_age_hours}


if __name__ == '__main__':
    print(json.dumps(check(), ensure_ascii=False, indent=1))
