# -*- coding: utf-8 -*-
"""공고 파트 작업 지표 — 수집부터 추천·운영까지 한 번에 다시 잰다(2026-09-30 처음, 2026-10-14 HTML·Word 보고서로 넓힘).

  python -X utf8 -m eval.metrics_report --all       발표용 전체: 배치 기록 가져오기 + 추천 정확도 다시 재기
                                                    + 응답 시간 두 가지 + 자동 시험 + HTML·Word
  python -X utf8 -m eval.metrics_report             빠른 확인: 공용 DB·배치 기록·기록 파일만
                                                    (정확도는 가장 최근 다시 재기 결과를 읽는다, HTML·Word 는 만든다)
  골라 켜기: --accuracy --latency --tests · 끄기: --no-render
  주소 바꾸기(서버 이전 뒤): --server-url / METRICS_SERVER_URL (실제 서버 응답 시간),
                            --batch-host·--batch-key·--batch-dir·--batch-name / METRICS_BATCH_* (배치 기록, eval/metrics_logs.py)

결과는 reports/metrics_<UTC>Z/ 의 metrics.json · summary.md · 지표_보고서.html · 지표_보고서.docx.
metrics.json 의 "charts" 는 그래프 23개의 값이다(계산만 여기서, 그리기는 metrics_doc.py). 그래프 하나가 실패하면
그 그래프만 빠지고(이유는 화면에) 보고서는 계속 만든다.
기존 결과 폴더는 덮지 않는다. 읽기만 한다: 공용 DB 조회, 배치 서버 기록 복사, 공고 서버에 추천 요청. OpenAI 호출 0.
결과물에는 서버 주소·키를 쓰지 않는다(이름으로만).

영역: 1 수집·운영 · 2 전처리 품질 · 3 AI 판정 · 4 추천 정확도 · 5 신청 불가 차단·자격 판정 · 6 가산점
      · 7 조율 연결 · 8 서버 성능 · 9 비용 · 10 개발 품질 · 11 약점과 한계 · ML 서비스 밖 실험
값의 출처: live(이번에 잼) · record(이미 있는 결과 파일·기록 값 목록 eval/metrics_records.json 에서 읽고 측정일 표시).
못 잰 지표는 value=null + "측정 못 함(이유)" + missing 에 넣는다. 이번에 재다가 실패한 것(expected=false)이
하나라도 있으면 종료 코드 1, 원래 출처가 없는 빈칸(expected=true)만 있으면 0.
"""
import argparse
import glob
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import common  # noqa: E402

KST = timezone(timedelta(hours=9))
REPORTS = os.path.join(ROOT, 'reports')
RECORDS = os.path.join(HERE, 'metrics_records.json')
BASE_0928 = os.path.join(REPORTS, 'filter_first_eval_20260928T104212Z')
# 배치가 서버에서 처음 돈 날(결정 0006: 10/2 결정, 첫 실행 10/3 09:00 KST). 10/2 배치는 PC 의 밀린 실행이라 "서버 이전 뒤"에 넣지 않는다.
SERVER_FIRST_RUN = date(2026, 10, 3)
# collect_log 의 run_at 은 PC 시절 한국 시각, 서버 시절 UTC 로 적혀 있다(시간대 표시 없음). 이 시각(UTC)부터가 서버 줄이다.
SERVER_FIRST_RUN_UTC = datetime(2026, 10, 3, 0, 0)
DEFAULT_SERVER_URL = 'http://43.201.90.238:8000'
DEFAULT_SERVER_NAME = '공개 시험 서버'

UNITS = ('ratio', 'score', 'count', 'ms', 'sec', 'min', 'mb', 'usd', 'text')
AREAS = {'1': '수집·운영', '2': '전처리 품질', '3': 'AI 판정', '4': '추천 정확도', '5': '신청 불가 차단·자격 판정',
         '6': '가산점', '7': '조율 연결', '8': '서버 성능', '9': '비용', '10': '개발 품질', '11': '약점과 한계',
         'ML': '서비스 밖 실험(ML)'}
ADDRESS = re.compile(r'\b\d{1,3}(?:\.\d{1,3}){3}\b|https?://[^\s"\')]+|[\w.-]+\.pem\b')

# 쉬운 설명 — 지표 이름이 무엇을 뜻하는지 한 문장으로(9/30 문장을 이어받고 새 지표는 새로 씀)
PLAIN = {
    '누적 공고 수': 'DB에 쌓인 지원사업 공고 수. 매일 새 공고를 더하고 지우지 않는다.',
    '지금 모집 중인 공고 수': '모집이 끝나지 않았고 마감일도 지나지 않은 공고 수. 추천 대상이 되는 공고다.',
    '하루 평균 신규 공고': '새 공고가 들어온 날 하루에 들어온 공고 수의 평균(최근 30일).',
    '배치 성공률(전체 기간)': '매일 수집 배치가 오류 없이 끝난 비율(첫 배치부터).',
    '배치 성공률(서버 이전 뒤)': '서버에서 배치가 처음 돈 10/3부터 오류 없이 끝난 비율.',
    '배치 가동일 비율(전체 기간)': '첫 배치부터 지금까지 배치가 실제로 돈 날의 비율. 서버 이전 전에는 PC가 꺼진 날 돌지 않았다.',
    '배치 가동일 비율(서버 이전 뒤)': '서버에서 배치가 처음 돈 10/3부터 배치가 실제로 돈 날의 비율.',
    '배치 소요 시간(서버 이전 뒤, 중앙값)': '하루 배치(수집→정규화→저장→첨부→임베딩→AI 판정)가 끝나는 데 걸린 시간.',
    'K-Startup 목록 완전 수집률': '받은 공고 수가 API가 알려 준 총 수와 정확히 같았던 실행의 비율.',
    '정규화 거부율(최근 저장)': '두 출처를 공통 형식으로 바꿀 때 필수값이 없어 버린 공고의 비율.',
    '접수기간 해석률': '접수기간 원문을 고정·예산 소진·상시·선착순으로 분류해 낸 비율.',
    '마감일 확보율': '마감일(날짜)이 있는 공고의 비율. 나머지는 원래 날짜가 없는 공고(예산 소진 등)가 대부분이다.',
    '첨부 공고문 본문 추출 성공률': '첨부 공고문(PDF·HWP 등)에서 글자를 뽑아낸 비율. 이미지 스캔본은 글자가 없다.',
    '임베딩 적용률': '의미 검색용 벡터가 만들어진 공고의 비율.',
    '판정표 적용 범위: 자격요건(금액·형태·업력)': 'AI가 지원금·사업자 형태·업력을 뽑아 둔 공고의 비율(본문 있는 공고 기준).',
    '판정표 적용 범위: 신청자 유형': 'AI가 예비창업자·개인사업자·법인 신청 가능 여부를 판정해 둔 공고의 비율.',
    '판정표 적용 범위: 업종': 'AI가 신청 가능 업종을 판정해 둔 공고의 비율.',
    '판정표 적용 범위: 가점(열린 기업마당 공고)': 'AI가 가점·가산점 항목을 읽어 둔 열린 기업마당 공고의 비율. K-Startup은 첨부를 못 받아 빠진다.',
    '신청자 유형 판정 지문 신선도': '판정이 지금 공고문과 같은 글을 보고 내린 것인지(지문 일치) 확인한 비율.',
    '예비창업자 "명시 불가" 판정 정밀도': '"예비창업자 불가"로 판정해 추천에서 뺀 공고가 실제로도 불가인 비율. 틀리면 신청 가능한 공고를 잃는다.',
    '신청자 유형 판정 일치율(예비창업자)': '신청자 유형 판정이 별도 블라인드 판정과 같은 비율.',
    '업종 순위의 부당 밀림(공고)': '업종 신호로 뒤로 밀린 공고 중 밀리면 안 됐던 공고의 비율. 높아서 이 기능은 꺼 두었다.',
    '상위 10건 중 신청 불가': '추천 상위 10건 중 마감·업력·신청자 유형 때문에 확실히 신청할 수 없는 공고의 비율(신청 불가@10).',
    '상위 3건 적합(낮게 센 값)': '추천 상위 3건 중 내용이 딱 맞는 공고의 비율(P@3(2) 하한). 판정이 없는 공고는 안 맞음으로 센 낮은 쪽 값이다.',
    '상위 3건 적합(높게 센 값)': '같은 비율에서 판정이 없는 공고를 맞음으로 센 높은 쪽 값(P@3(2) 상한). 실제 값은 두 값 사이다.',
    'nDCG@10(판정분)': '상위 10건의 순서까지 반영한 점수(0~1). 판정된 공고만으로 계산했다.',
    '쓸모@3 하한': '상위 3건 중 "내용이 맞고 신청도 가능한" 공고 수(최대 3).',
    '상위 10 미판정 비율': '추천 상위 10건 중 아직 사람·AI 판정이 없는 칸의 비율. 높으면 정확도 숫자를 덜 믿어야 한다.',
    '추천 필터 ↔ 자격 판정 결론 다름': '추천에서 빼는 규칙과 조율 쪽 자격 판정이 같은 공고에 다른 결론을 낸 횟수. 0이어야 한다.',
    '개인사업자 "강한 불가" 공고가 상위 20에 뜬 질의': '개인사업자에게 "개인사업자 불가"가 확실한 공고가 추천 상위 20에 뜬 평가 질의 수.',
    '법인 "강한 불가" 공고가 상위 20에 뜬 질의': '법인에게 "법인 불가"가 확실한 공고가 추천 상위 20에 뜬 평가 질의 수.',
    '열린 공고 중 가점 언급 공고': '지금 모집 중인 공고 가운데 AI가 가점·가산점 항목을 찾아 둔 공고 수.',
    '원문 대조를 마친 가산점 공고': '가산점 계산이 공고 원문과 맞는지 AI(Claude)가 원문과 대조해 목록에 올린 공고 수(AI 참고 — 사람 검수 아님). 이 공고만 화면·순위에 쓴다.',
    '가산점 순위 반영 세기': '원문 대조를 마친 공고의 가산점을 추천 순위에 얼마나 반영하는지(0~1, 지금 0.2).',
    '신청자별 가산점이 나오는 공고': '신청자 입력으로 가산점이 계산되는 열린 공고 수.',
    'K-Startup 모집 중 공고(가산점 늘 비어 있음)': 'K-Startup은 첨부 공고문을 받을 수 없어(제공 거절) 가산점을 계산할 수 없는 공고 수.',
    '제공 HTTP 창구 수': '조율 에이전트가 부르는 공고 서버 창구(추천·수집 상태·공고 상세·자격 판정) 수.',
    '연결 계약 시험 통과': '조율 쪽 실제 코드로 공고 서버를 불러 약속한 응답 형식을 지키는지 본 시험의 통과 수.',
    '자격 판정 응답 형식 오류': '모든 공고에 자격 판정을 요청했을 때 약속과 다른 형식으로 답한 수. 0이어야 한다.',
    '공고 상세 응답 형식 오류': '모든 공고의 상세 정보를 요청했을 때 약속과 다른 형식으로 답한 수. 0이어야 한다.',
    '추천 응답 시간(이 PC, 중앙값)': '추천 요청 하나에 답하는 데 걸린 시간. 이 PC 안에서 잰 값이라 인터넷을 오가는 시간은 빠져 있다.',
    '추천 응답 시간(실제 서버, 중앙값)': '팀원이 실제로 부르는 서버에 추천을 요청해 답을 받기까지 걸린 시간(인터넷 포함 — 실제로 기다리는 시간).',
    '공고 서버 켜는 시간(시험용 새 서버)': '공고 서버가 켜져서 답할 준비가 될 때까지 걸린 시간.',
    '공고 서버 메모리(시험용 새 서버)': '공고 서버가 켜진 뒤 차지하는 메모리.',
    '배치 중 서버 최대 메모리(시험용 새 서버)': '매일 배치가 도는 동안 서버 메모리를 가장 많이 쓴 순간의 양. 4GB 서버에 들어가는지 보는 값.',
    '임베딩 공고 1건(CPU→GPU)': '공고 글 하나를 검색용 벡터로 바꾸는 시간. 집 PC의 CPU와 GPU로 같은 공고 300건을 잼.',
    '임베딩 검색어 1건(CPU→GPU)': '검색어 하나를 벡터로 바꾸는 시간(추천 요청마다 한 번).',
    '임베딩 전체 다시 만들기(CPU→GPU)': '모든 공고의 벡터를 처음부터 다시 만들 때 걸리는 시간(환산).',
    '하루 AI 비용': '매일 새 공고를 AI로 판정하는 데 든 비용(최근 배치 평균).',
    '서버 요금 참고: 지금 서버(t3.medium, 시간당)': '지금 쓰는 CPU 서버의 시간당 요금(참고).',
    '서버 요금 참고: GPU 서버(g4dn.xlarge, 시간당)': 'GPU가 달린 서버의 시간당 요금(참고). 지금 서버의 약 12배.',
    '자동 테스트 수': '코드를 고칠 때마다 손으로 돌려 확인하는 자동 시험의 수(저장소 CI에는 아직 없음).',
    'AI 교차 검수 결과 문서 수': '다른 AI(Codex)가 독립적으로 검수·판정한 결과 문서 수. 구현(Claude)과 검수(Codex)를 나눴다.',
    '결정 기록 수': '왜 그렇게 정했는지 남긴 설계 결정 문서 수.',
    '판정자 일치율: LLM(gpt-4.1-mini) vs 사람': '관련도 판정을 LLM에 맡겼을 때 사람 판정과 같은 비율. 기준(0.70)에 못 미친다.',
    '판정자 일치율: Jev vs 사람': '평가 전용 모델 Jev의 판정이 사람 판정과 같은 비율.',
    '평가 질의 수': '추천 정확도 평가에 쓴 질문 수. 많지 않아 숫자가 흔들릴 수 있다.',
    'ML 리랭커: 상위 3건 적합(학습 전 → 학습 후)': '검색 결과를 다시 줄 세우는 모델(리랭커)을 우리 판정으로 학습시킨 전후의 상위 3건 적합 비율.',
    'ML 리랭커: nDCG@3(학습 전 → 학습 후)': '같은 실험에서 상위 3건 순서까지 본 점수(0~1).',
    '리랭커 질의당 시간(GPU)': '리랭커가 검색어 하나를 처리하는 시간. GPU에서도 1초가 넘는다.',
    '리랭커 GPU 최대 사용량': '리랭커가 쓴 GPU 메모리의 최대치.',
    'ML 업력 분류기 F1(시험)': '공고 문장이 업력 조건인지 가려내는 작은 모델의 시험 점수(0~1).',
}


def read_text(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


class Book:
    """지표 모음. 이름은 겹치지 않는다(한눈에 보기가 이름으로 가리킨다)."""

    def __init__(self, today):
        self.today = today
        self.metrics, self.missing = [], []
        self.raw = {}                     # 그래프가 쓰는 원값(지표 글에만 들어가는 숫자 — 예: 응답 시간 p95)

    def names(self):
        return {m['name'] for m in self.metrics}

    def add(self, area, name, value, unit, target='참고', detail='', source='', kind='live', measured_at=None,
            compare=None, plain=None):
        if unit not in UNITS:
            raise ValueError('알 수 없는 단위 %r (%s)' % (unit, name))
        if area not in AREAS:
            raise ValueError('알 수 없는 영역 %r (%s)' % (area, name))
        if name in self.names():
            raise ValueError('지표 이름이 겹친다: %s' % name)
        m = {'area': area, 'name': name, 'value': value, 'unit': unit, 'target': target, 'detail': detail,
             'plain': PLAIN.get(name, '') if plain is None else plain, 'source': source, 'kind': kind,
             'measured_at': measured_at or self.today.isoformat()}
        if compare:
            m['compare'] = compare
        self.metrics.append(m)
        return m

    def miss(self, area, name, unit, reason, expected, target='참고', source='', kind='live', measured_at=None):
        if name in self.names():
            return
        self.add(area, name, None, unit, target, '측정 못 함(%s)' % reason, source, kind, measured_at)
        self.missing.append({'name': name, 'reason': reason, 'expected': bool(expected)})


def pct(n, d):
    return None if not d else n / d


def latest(pattern):
    paths = sorted(glob.glob(os.path.join(REPORTS, pattern)))
    return paths[-1] if paths else None


def folder_date(path):
    """결과 폴더 이름의 시각(…_20261013T032549Z)에서 날짜를 읽는다."""
    m = re.search(r'_(\d{4})(\d{2})(\d{2})(?:T|$)', os.path.basename(path or ''))
    return '%s-%s-%s' % m.groups() if m else None


def guarded(book, planned, fn, *args):
    """fn 이 실패해도 보고서는 계속 만든다 — 계획한 지표 중 못 채운 것을 '측정 못 함'으로 둔다."""
    try:
        fn(book, *args)
        reason = None
    except Exception as exc:                       # 원문에 주소·SQL 값이 섞일 수 있어 종류만 남긴다
        reason = '%s' % type(exc).__name__
    for area, name, unit, kind in planned:
        if name not in book.names():
            book.miss(area, name, unit, reason or '값을 얻지 못함', expected=False, kind=kind)


# ── 1 수집·운영 ─────────────────────────────────────────────────────────
def real_run(r):
    """실제 배치 실행인가 — 연습 실행(--dry-run: 출처 상태가 dry-run)은 뺀다.
    (9/30에는 1분 미만을 시험 실행으로 봤지만, 서버 이전 뒤 새 공고 없는 날 배치는 40초 안팎에 정상으로 끝난다)"""
    if r.get('job') != 'pipeline' or not r.get('run_at'):
        return False
    return not any((s or {}).get('status') == 'dry-run' for s in (r.get('sources') or {}).values())


def kst_day(run_at):
    """collect_log 의 run_at → 한국 날짜('YYYY-MM-DD'). 시간대가 붙어 있으면 그것을 따르고, 없으면
    PC 시절 줄(SERVER_FIRST_RUN_UTC 앞)은 한국 시각, 서버 줄은 UTC 로 보고 9시간을 더한다
    (배치 시각을 한국 새벽으로 옮겨 UTC 날짜가 하루 앞서게 돼도 날짜가 맞게)."""
    s = str(run_at).strip()
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        return s[:10]
    if dt.tzinfo is None:
        if dt < SERVER_FIRST_RUN_UTC:
            return dt.date().isoformat()
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST).date().isoformat()


def batch_days(rows, today):
    """실제 배치 실행을 한국 날짜별로 — 날마다 가장 오래 걸린 한 번(같은 날 다시 돌린 것은 하나로)."""
    by_day = {}
    for r in rows:
        if not real_run(r):
            continue
        d = kst_day(r['run_at'])
        if (r.get('elapsed_sec') or 0) > (by_day.get(d, {}).get('elapsed_sec') or 0):
            by_day[d] = r
    return by_day


def ops_window(rows, start, end):
    """[start, end] 한국 날짜 구간의 성공률·가동일 비율. end 는 배치가 돌았어야 하는 마지막 날."""
    pipe = [r for r in rows if real_run(r) and start <= date.fromisoformat(kst_day(r['run_at'])) <= end]
    ok = sum(1 for r in pipe if r.get('status') == 'ok')
    days = {kst_day(r['run_at']) for r in pipe}
    span = (end - start).days + 1
    return {'runs': len(pipe), 'ok': ok, 'days': len(days), 'span': span, 'start': start, 'end': end,
            'not_ok': sorted({str(r.get('status')) for r in pipe if r.get('status') != 'ok'})}


def kstartup_complete(rows):
    """옛 줄(count == reported_total)과 새 줄(sources.kstartup.complete)을 함께 센다."""
    full = total = 0
    for r in rows:
        if 'job' not in r and r.get('status') == 'ok' and r.get('reported_total'):
            total += 1
            full += r.get('count') == r.get('reported_total')
        elif r.get('job') == 'pipeline':
            ks = (r.get('sources') or {}).get('kstartup') or {}
            if ks.get('status') == 'ok' and 'complete' in ks:
                total += 1
                full += bool(ks['complete'])
    return full, total


def batch_src(logs, what):
    """출처 줄: '배치 기록 collect_log(서버 sbrain-web, 이 PC 복사본과 합침)'처럼 괄호를 한 겹으로.
    logs['sources'] 는 metrics_logs 가 주는 화면용 이름('이 PC 복사본(이름)', '이름 서버')."""
    servers, copies, others = [], [], []
    for s in (logs or {}).get('sources') or []:
        m = re.match(r'^이 PC 복사본\((.+)\)$', s)
        if m:
            copies.append(m.group(1))
            continue
        m = re.match(r'^(.+) 서버$', s)
        (servers if m else others).append(m.group(1) if m else s)
    if servers:
        where = '서버 %s' % ', '.join(servers) + (', 이 PC 복사본과 합침' if copies else '')
    elif copies:
        where = '이 PC 복사본 %s — 서버에서 새로 읽지 못함' % ', '.join(copies)
    else:
        where = '없음'
    if others:
        where += ', ' + ', '.join(others)
    return '배치 기록 %s(%s)' % (what, where)


def area_collection(book, cur, connection, logs):
    cur.execute('SELECT source, COUNT(*) FROM notices GROUP BY source')
    by_source = dict(cur.fetchall())
    book.add('1', '누적 공고 수', sum(by_source.values()), 'count', detail=', '.join(
        '%s %s' % ({'kstartup': 'K-Startup', 'bizinfo': '기업마당'}.get(k, k), format(v, ',')) for k, v in sorted(by_source.items())),
        source='공용 DB notices')
    from eval.bonus_conservative_compare import open_ids
    ids = open_ids(connection, book.today)
    ks = sum(1 for n in ids if n.startswith('kstartup:'))
    book.add('1', '지금 모집 중인 공고 수', len(ids), 'count', detail='K-Startup %s · 기업마당 %s' % (format(ks, ','), format(len(ids) - ks, ',')),
             source='공용 DB notices(모집 종료 아님·마감일 안 지남)')
    cur.execute("SELECT DATE(CONVERT_TZ(created_at, '+00:00', '+09:00')) d, COUNT(*) FROM notices "
                'WHERE created_at >= UTC_TIMESTAMP() - INTERVAL 30 DAY GROUP BY d ORDER BY d')
    per_day = [(str(d), n) for d, n in cur.fetchall()]
    if per_day:
        book.add('1', '하루 평균 신규 공고', int(round(statistics.mean(n for _, n in per_day))), 'count',
                 detail='새 공고가 들어온 날 %d일 평균 · 최근: %s' % (len(per_day), ', '.join('%s %d' % (d[5:], n) for d, n in per_day[-5:])),
                 source='공용 DB notices.created_at(한국 날짜, 최근 30일)')
    rows = logs['collect_rows']
    src = batch_src(logs, 'collect_log')
    by_day = batch_days(rows, book.today)
    if not by_day:
        raise RuntimeError('배치 기록 없음')
    first = date.fromisoformat(min(by_day))
    end = book.today if book.today.isoformat() in by_day else book.today - timedelta(days=1)
    for label, start in (('전체 기간', first), ('서버 이전 뒤', SERVER_FIRST_RUN)):
        w = ops_window(rows, start, end)
        book.add('1', '배치 성공률(%s)' % label, pct(w['ok'], w['runs']), 'ratio', '1.00',
                 '%d/%d회 성공%s · %s~%s' % (w['ok'], w['runs'], (' · 그 밖 상태 ' + ', '.join(w['not_ok'])) if w['not_ok'] else '',
                                          w['start'], w['end']), src)
        book.add('1', '배치 가동일 비율(%s)' % label, pct(w['days'], w['span']), 'ratio', '1.00',
                 '%d일/%d일 (%s~%s)%s' % (w['days'], w['span'], w['start'], w['end'],
                                         ' · 서버 이전 전에는 PC가 꺼진 날 돌지 않았다' if label == '전체 기간' else ''), src)
    after = [r for d, r in sorted(by_day.items()) if date.fromisoformat(d) >= SERVER_FIRST_RUN]
    if after:
        el = [r['elapsed_sec'] / 60 for r in after]
        book.add('1', '배치 소요 시간(서버 이전 뒤, 중앙값)', round(statistics.median(el), 1), 'min',
                 detail='최근 %s분' % ', '.join('%.1f' % x for x in el[-5:]), source=src)
    full, total = kstartup_complete(rows)
    book.add('1', 'K-Startup 목록 완전 수집률', pct(full, total), 'ratio', '1.00', '%d/%d회 받은 수 = 서버 보고 수' % (full, total), src)


# ── 2 전처리 품질 ────────────────────────────────────────────────────────
def area_preprocessing(book, cur):
    cur.execute('SELECT report FROM import_runs ORDER BY imported_at DESC LIMIT 1')
    s = json.loads(cur.fetchone()[0]).get('summary') or {}
    acc, rej = s.get('accepted_count', 0), s.get('rejected_count', 0)
    book.add('2', '정규화 거부율(최근 저장)', pct(rej, acc + rej), 'ratio', '0', '%s/%s건 거부' % (format(rej, ','), format(acc + rej, ',')),
             '공용 DB import_runs(최근 저장)')
    cur.execute('SELECT apply_period_type, COUNT(*) FROM notices GROUP BY 1')
    types = dict(cur.fetchall())
    n = sum(types.values())
    names = {'fixed': '기간 고정', 'budget_exhaustion': '예산 소진', 'rolling': '상시', 'until_filled': '선착순', 'unknown': '모름'}
    book.add('2', '접수기간 해석률', pct(n - types.get('unknown', 0), n), 'ratio',
             detail=', '.join('%s %s' % (names.get(k, k), format(v, ',')) for k, v in sorted(types.items())),
             source='공용 DB notices.apply_period_type')
    cur.execute('SELECT COUNT(*) FROM notices WHERE apply_end IS NOT NULL')
    book.add('2', '마감일 확보율', pct(cur.fetchone()[0], n), 'ratio', detail='없는 공고는 예산 소진·상시·선착순·정보 없음',
             source='공용 DB notices.apply_end')
    cur.execute("SELECT t.last_status, COUNT(*) FROM attachment_texts t JOIN notice_attachments a ON a.id=t.attachment_fk "
                'WHERE a.active GROUP BY 1')
    st = dict(cur.fetchall())
    m = sum(st.values())
    names = {'ok': '성공', 'image_only': '그림만 있음', 'parse_error': '읽기 오류'}
    book.add('2', '첨부 공고문 본문 추출 성공률', pct(st.get('ok', 0), m), 'ratio',
             detail=', '.join('%s %s' % (names.get(k, k), format(v, ',')) for k, v in sorted(st.items())),
             source='공용 DB attachment_texts(활성 첨부)')
    cur.execute('SELECT COUNT(*) FROM notices WHERE embedding IS NOT NULL')
    book.add('2', '임베딩 적용률', pct(cur.fetchone()[0], n), 'ratio', '1.00', 'BGE-M3 1024차원', '공용 DB notices.embedding')


# ── 3 AI 판정 ───────────────────────────────────────────────────────────
def area_ai(book, cur, connection):
    cur.execute('SELECT COUNT(*) FROM notices')
    n = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT n.id) FROM notices n JOIN notice_attachments a ON a.notice_fk=n.id "
                "JOIN attachment_texts t ON t.attachment_fk=a.id WHERE a.active AND t.last_status='ok'")
    with_body = cur.fetchone()[0]
    for table, base, label, note in (('notice_conditions', with_body, '자격요건(금액·형태·업력)', '본문 있는 공고 대비'),
                                     ('notice_applicant_types', n, '신청자 유형', '전체 공고 대비'),
                                     ('notice_industries', n, '업종', '전체 공고 대비')):
        cur.execute('SELECT COUNT(*) FROM ' + table)
        k = cur.fetchone()[0]
        book.add('3', '판정표 적용 범위: ' + label, pct(k, base), 'ratio', '1.00',
                 '%s/%s (%s)' % (format(k, ','), format(base, ','), note), '공용 DB ' + table)
        book.raw.setdefault('coverage', {})['판정표 적용 범위: ' + label] = {'judged': k, 'base': base, 'notices': n}
    from eval.bonus_conservative_compare import open_ids
    ids = [i for i in open_ids(connection, book.today) if i.startswith('bizinfo:')]
    cur.execute('SELECT notice_id FROM notice_bonus')
    rows = {r[0] for r in cur.fetchall()}
    k = sum(1 for i in ids if i in rows)
    book.add('3', '판정표 적용 범위: 가점(열린 기업마당 공고)', pct(k, len(ids)), 'ratio', '참고',
             '%s/%s (첨부·가점 말이 없는 공고는 읽을 것이 없어 빠질 수 있다)' % (format(k, ','), format(len(ids), ',')), '공용 DB notice_bonus')
    book.raw.setdefault('coverage', {})['판정표 적용 범위: 가점(열린 기업마당 공고)'] = {'judged': k, 'base': len(ids), 'notices': n}
    from search import applicant_types
    t0 = time.time()
    r = applicant_types.load_auto(connection)
    unread = sum(r.get(x) or 0 for x in ('unread_pre_founder', 'unread_entity'))
    book.add('3', '신청자 유형 판정 지문 신선도', pct((r.get('fresh_from_db') or 0) + (r.get('refreshed_from_file') or 0), n), 'ratio', '1.00',
             '지문 다름 %s · 발췌 밖 확인 필요 %s · %.1f초' % (r.get('stale'), unread, time.time() - t0), '판정표 읽기(applicant_types)')
    score = os.path.join(REPORTS, 'label_pack_20260928', 'score.json')
    s = read_json(score)
    g = s['gate_pre_strong']
    book.add('3', '예비창업자 "명시 불가" 판정 정밀도', g['rate'], 'ratio', '1.00 (잘못 빼면 안 됨)',
             '%d/%d · 신청 가능한 공고를 뺄 오류 %d건 (Codex 블라인드, AI 참고 정답)' % (g['hit'], g['total'], len(s['gate_pre_strong_wrong_allowed'])),
             'reports/label_pack_20260928/score.json', 'record', '2026-09-28')
    a = s['agreement']
    book.add('3', '신청자 유형 판정 일치율(예비창업자)', a['pre_founder']['rate'], 'ratio', '참고',
             '예비창업자 %d/%d · 개인사업자 %d/%d · 법인 %d/%d (AI 참고 정답)' % (
                 a['pre_founder']['hit'], a['pre_founder']['total'], a['sole_proprietor']['hit'], a['sole_proprietor']['total'],
                 a['corporation']['hit'], a['corporation']['total']),
             'reports/label_pack_20260928/score.json', 'record', '2026-09-28')
    w = s.get('industry_wrong_push')
    wn = len({x['notice_id'] for x in w}) if isinstance(w, list) else None
    book.add('3', '업종 순위의 부당 밀림(공고)', pct(wn, s['industry_labeled']) if wn is not None else None, 'ratio', '낮을수록 · 서비스 꺼짐',
             '%s/%d 공고 — 그래서 업종 순위는 기본 꺼짐 (AI 참고 정답)' % (wn, s['industry_labeled']),
             'reports/label_pack_20260928/score.json', 'record', '2026-09-28')


# ── 4 추천 정확도 ───────────────────────────────────────────────────────
# 지표 이름은 쉬운 말로(10/15) — 전문 용어(신청 불가@10 · P@3(2) 하한·상한)는 쉬운 설명(PLAIN)에 함께 적는다.
INELIGIBLE, P3_LO, P3_HI = '상위 10건 중 신청 불가', '상위 3건 적합(낮게 센 값)', '상위 3건 적합(높게 센 값)'
BEFORE_NAME = '처음(의미 검색만)'          # 벡터(의미) 검색만 쓰던 처음 방식 — 그래프·한눈에 보기에서 같은 이름
ACC = (('ineligible_k', INELIGIBLE, 'ratio', '0'), ('p3_lo', P3_LO, 'ratio', '높을수록'),
       ('p3_hi', P3_HI, 'ratio', '높을수록'), ('ndcg_k', 'nDCG@10(판정분)', 'score', '높을수록'),
       ('useful3_lo', '쓸모@3 하한', 'count', '높을수록'), ('unjudgedk', '상위 10 미판정 비율', 'ratio', '참고'))


def load_accuracy():
    """(9/28 요약, 지금 다시 잰 요약, 지금 폴더) — 없으면 None."""
    base = read_json(os.path.join(BASE_0928, 'results.json'))['summary']['hybrid']
    now_dir = latest('filter_first_now_*')
    now = None
    if now_dir and os.path.exists(os.path.join(now_dir, 'results.json')):
        now = read_json(os.path.join(now_dir, 'results.json'))
    return base, now, now_dir


def area_accuracy(book, acc):
    base, now, now_dir = acc
    meta = (now or {}).get('meta') or {}
    s = ((now or {}).get('summary') or {}).get('hybrid') or {}
    as_of = meta.get('status_as_of') or {}
    as_of_note = (' · 모집 상태는 %s 당시로 맞춤(되돌린 공고 %s건)' % (as_of.get('date'), as_of.get('reopened'))) if as_of else ''
    if meta:
        book.raw['acc_meta'] = meta
    for key, name, unit, target in ACC:
        b = base.get(key) or {}
        ref = {'label': '9/28 평가', 'before': b.get('vector_only'), 'after': b.get('filter_first'),
               'label_before': BEFORE_NAME, 'label_after': '9/28 서비스'}
        x = s.get(key)
        if not x or x.get('filter_first') is None:
            book.miss('4', name, unit, '지금 서비스 다시 재기 결과 없음 — --accuracy 로 다시 잰다', expected=False,
                      target=target, source='reports/filter_first_now_*')
            continue
        diff = x.get('diff_vs_vector') or [None, None, None]
        ci = (' · 차이 %+.3f [%+.3f, %+.3f]' % tuple(diff)) if all(v is not None for v in diff) else ''
        book.add('4', name, x['filter_first'], unit, target,
                 '%s %.3f → 지금 서비스 %.3f%s · 9/28 평가: %s → %s' % (
                     BEFORE_NAME, x['vector_only'], x['filter_first'], ci, _f(ref['before']), _f(ref['after'])),
                 '%s · 질의 %s · 판정 %s쌍%s · 9/28 기준 filter_first_eval_20260928T104212Z' % (
                     os.path.basename(now_dir), meta.get('queries'), meta.get('qrels_pairs'), as_of_note),
                 'live', folder_date(now_dir),
                 compare={'before': x['vector_only'], 'after': x['filter_first'], 'label_before': BEFORE_NAME,
                          'label_after': '지금 서비스', 'reference': ref})


def _f(v):
    return '-' if v is None else '%.3f' % v


# ── 5 신청 불가 차단·자격 판정 ──────────────────────────────────────────
def area_blocking(book):
    after_dir = os.path.join(REPORTS, 'entity_block_after_20261013T031546Z')
    probe_dir = os.path.join(REPORTS, 'entity_block_probe_20261013T030233Z')
    a = read_json(os.path.join(after_dir, 'entity_block_after.json'))
    p = read_json(os.path.join(probe_dir, 'entity_block_probe.json'))
    c = a['consistency']
    book.add('5', '추천 필터 ↔ 자격 판정 결론 다름', len(c['diff']), 'count', '0',
             '%s회 비교(공고 × 가상 신청자 6가지)' % format(c['checks'], ','),
             'reports/entity_block_after_20261013T031546Z', 'record', '2026-10-13')
    for t in ('개인사업자', '법인'):
        before, after = p['stats'][t], a['top20_after'][t]
        book.add('5', '%s "강한 불가" 공고가 상위 20에 뜬 질의' % t, after['질의_상위20에_있음'], 'count', '0',
                 '평가 질의 58개 · 상위 20: %d → %d · 상위 10: %d → %d (차단 전 → 후)' % (
                     before['질의_상위20에_있음'], after['질의_상위20에_있음'], before['질의_상위10에_있음'], after['질의_상위10에_있음']),
                 'reports/entity_block_probe_20261013T030233Z · entity_block_after_20261013T031546Z', 'record', '2026-10-13',
                 compare={'before': before['질의_상위20에_있음'], 'after': after['질의_상위20에_있음'],
                          'label_before': '차단 전', 'label_after': '차단 후'})


# ── 6 가산점 ───────────────────────────────────────────────────────────
def reviewers(reviewed):
    """원문 대조 목록(search/bonus_reviewed.json)의 대조한 쪽(reviewed_by)별 공고 수."""
    notices = reviewed.get('notices') or {}
    items = notices.values() if isinstance(notices, dict) else notices
    out = defaultdict(int)
    for x in items:
        out[str((x or {}).get('reviewed_by') or '기록 없음')] += 1
    return dict(out)


def all_ai_reviewed(reviewed):
    """목록의 모든 공고를 AI(Claude 등)가 대조했는가 — 그러면 '사람이 대조'라고 쓰지 않는다."""
    who = reviewers(reviewed)
    return bool(who) and all(('AI' in k or 'Claude' in k or 'Codex' in k) for k in who)


def area_bonus(book, cur, connection):
    from eval.bonus_conservative_compare import open_ids
    ids = open_ids(connection, book.today)
    cur.execute("SELECT notice_id FROM notice_bonus WHERE status='found'")
    found = {r[0] for r in cur.fetchall()}
    book.add('6', '열린 공고 중 가점 언급 공고', sum(1 for i in ids if i in found), 'count',
             detail='열린 공고 %s건 중' % format(len(ids), ','), source='공용 DB notice_bonus(status=found)')
    reviewed = read_json(os.path.join(ROOT, 'search', 'bonus_reviewed.json'))
    who = reviewers(reviewed)
    book.add('6', '원문 대조를 마친 가산점 공고', len(reviewed.get('notices') or {}), 'count',
             detail='목록 갱신 %s · 대조: %s' % (reviewed.get('updated_at'), ', '.join('%s %d건' % kv for kv in who.items()) or '기록 없음'),
             source='search/bonus_reviewed.json')
    src = read_text(os.path.join(ROOT, 'search', 'app.py'))
    m = re.search(r'^\s*bonus:\s*float\s*=\s*([0-9.]+)', src, re.M)
    book.add('6', '가산점 순위 반영 세기', float(m.group(1)) if m else None, 'score',
             detail='원문 대조를 마친 공고에만 적용(결정 0017)', source='search/app.py 기본값')
    bb = latest('bonus_boostable_*')
    s = read_json(os.path.join(bb, 'results.json'))['summary']
    per = s.get('persona_positive') or {}
    book.add('6', '신청자별 가산점이 나오는 공고', s.get('boostable'), 'count',
             detail='열린 공고 %s건 중 · 가상 신청자별: %s' % (format(s.get('open_notices') or 0, ','),
                                                    ', '.join('%s %d건' % (k, len(v)) for k, v in per.items())),
             source='reports/' + os.path.basename(bb), kind='record', measured_at=folder_date(bb))
    ks = sum(1 for i in ids if i.startswith('kstartup:'))
    book.add('6', 'K-Startup 모집 중 공고(가산점 늘 비어 있음)', ks, 'count',
             detail='첨부 공고문 URL 제공을 창업진흥원이 거절(10/14) — 대신할 길 없음', source='공용 DB notices')


# ── 7 조율 연결 ─────────────────────────────────────────────────────────
def area_link(book, records):
    doc = read_text(os.path.join(ROOT, 'docs', 'contracts.md'))
    eps = re.findall(r'^## \d+\. `(GET|POST) ([^`]+)`', doc, re.M)
    book.add('7', '제공 HTTP 창구 수', len(eps), 'count', detail=' · '.join('%s %s' % e for e in eps), source='docs/contracts.md')
    d = latest('notice_api_contract_*')
    r = read_json(os.path.join(d, 'results.json'))
    checks = r.get('checks') or []
    ok = sum(1 for c in checks if c.get('ok'))
    book.add('7', '연결 계약 시험 통과', ok, 'count', str(len(checks)),
             '조율 쪽 실제 코드로 공고 서버 호출 · 가상 신청자 %d명' % len(r.get('fake_applicants') or []),
             'reports/' + os.path.basename(d), 'record', folder_date(d))
    g = (r.get('log') or {}).get('g01_all') or {}
    book.add('7', '자격 판정 응답 형식 오류', g.get('error_count'), 'count', '0',
             '%s건 검사(모든 공고) · 통과 %s' % (format(g.get('notices') or 0, ','), format(g.get('passed') or 0, ',')),
             'reports/' + os.path.basename(d), 'record', folder_date(d))
    add_record(book, records, 'detail_format_errors',
               detail_fn=lambda rec: '%s건 검사(모든 공고) · %s' % (format(rec.get('checked') or 0, ','), rec['where']))


# ── 8 서버 성능 ─────────────────────────────────────────────────────────
def normal_queries():
    return [q for q in common.load_queries().values() if q['kind'] == 'normal']


def healthy(url, timeout=5):
    import urllib.request
    try:
        return json.loads(urllib.request.urlopen(url + '/api/health', timeout=timeout).read())
    except Exception:
        return None


def measure(url):
    """평가 정상 질의를 하나씩 보내 응답 시간(ms)을 잰다. 첫 조회 10건."""
    import urllib.request
    times = []
    for q in normal_queries():
        body = json.dumps(dict(q['payload'], top=10)).encode('utf-8')
        req = urllib.request.Request(url + '/api/match', data=body, headers={'Content-Type': 'application/json'})
        t0 = time.time()
        urllib.request.urlopen(req, timeout=120).read()
        times.append((time.time() - t0) * 1000)
    times.sort()
    return {'median': statistics.median(times), 'p95': times[max(0, int(len(times) * 0.95) - 1)], 'max': times[-1], 'n': len(times)}


def start_pc_server(port=8000, wait=600):
    """이 PC 공고 서버. 이미 켜져 있으면 그것을 쓰고(끄지 않는다), 꺼져 있으면 잠시 켠다 — 켠 프로세스를 돌려준다."""
    url = 'http://127.0.0.1:%d' % port
    if healthy(url):
        return url, None
    env = dict(os.environ, PORT=str(port), HF_HUB_OFFLINE='1')
    flags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    proc = subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'search.app'], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    t0 = time.time()
    while time.time() - t0 < wait:
        if proc.poll() is not None:
            raise RuntimeError('이 PC 공고 서버가 켜지다 멈춤')
        if healthy(url):
            return url, proc
        time.sleep(3)
    stop(proc)
    raise TimeoutError('이 PC 공고 서버가 %d초 안에 켜지지 않음' % wait)


def stop(proc):
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()


def area_latency(book, server_url, server_name):
    proc = None
    try:
        url, proc = start_pc_server()
        h = healthy(url) or {}
        r = measure(url)
        book.raw.setdefault('latency', {})['pc'] = r
        book.add('8', '추천 응답 시간(이 PC, 중앙값)', round(r['median'], 1), 'ms',
                 detail='p95 %.0fms · 최대 %.0fms · 질의 %d개 · 공고 %s건 · 첫 조회 10건' % (r['p95'], r['max'], r['n'], h.get('notices') or h.get('indexed')),
                 source='이 PC 공고 서버 /api/match' + (' (이 도구가 잠시 켬)' if proc else ' (이미 켜져 있던 서버)'))
    except Exception as exc:
        book.miss('8', '추천 응답 시간(이 PC, 중앙값)', 'ms', type(exc).__name__, expected=False)
    finally:
        stop(proc)
    try:
        h = healthy(server_url, timeout=15)
        if h is None:
            raise ConnectionError('서버 응답 없음')
        r = measure(server_url)
        book.raw.setdefault('latency', {})['server'] = r
        book.add('8', '추천 응답 시간(실제 서버, 중앙값)', round(r['median'], 1), 'ms',
                 detail='p95 %.0fms · 최대 %.0fms · 질의 %d개 · 공고 %s건 · 이 PC에서 인터넷을 거쳐 잼' % (
                     r['p95'], r['max'], r['n'], h.get('notices') or h.get('indexed')),
                 source='%s /api/match' % server_name)
    except Exception as exc:
        book.miss('8', '추천 응답 시간(실제 서버, 중앙값)', 'ms', '%s — %s' % (type(exc).__name__, server_name), expected=False)


def area_server_records(book, records):
    for key in ('notice_server_boot', 'notice_server_memory', 'batch_peak_memory'):
        add_record(book, records, key)
    d = os.path.join(REPORTS, 'embedding_cpu_gpu_20261014T082732Z')
    cpu = read_json(os.path.join(d, 'result_cpu-fp32.json'))
    gpu = read_json(os.path.join(d, 'result_cuda-fp32.json'))
    src = 'reports/embedding_cpu_gpu_20261014T082732Z'
    note = '집 PC Ryzen 5 5600X ↔ RTX 3060(같은 결과 벡터)'
    for name, b, a, unit in (('임베딩 공고 1건(CPU→GPU)', cpu['docs']['4']['per_doc_ms'], gpu['docs']['4']['per_doc_ms'], 'ms'),
                             ('임베딩 검색어 1건(CPU→GPU)', cpu['query_ms']['median'], gpu['query_ms']['median'], 'ms'),
                             ('임베딩 전체 다시 만들기(CPU→GPU)', cpu['docs']['4']['full_est_min'], gpu['docs']['4']['full_est_min'], 'min')):
        book.add('8', name, a, unit, detail='CPU %s → GPU %s · %s' % (b, a, note), source=src, kind='record', measured_at='2026-10-14',
                 compare={'before': b, 'after': a, 'label_before': 'CPU', 'label_after': 'GPU'})


def add_record(book, records, key, detail_fn=None):
    rec = records.get(key)
    if not rec:
        raise KeyError(key)
    detail = detail_fn(rec) if detail_fn else rec.get('where', '')
    book.add(rec['area'], rec['name'], rec['value'], rec['unit'], rec.get('target', '참고'), detail,
             '%s (%s)' % (rec['source'], rec.get('evidence', '')), 'record', rec.get('measured_at'))


def load_records(path=RECORDS):
    data = read_json(path)
    return {r['key']: r for r in data['records']}


# ── 9 비용 ─────────────────────────────────────────────────────────────
PROGRESS = re.compile(r'^\s*\d+/\d+\s*·')       # "    150/300 · 실패 0 · 약 $0.136" — 그때까지 누적 금액(끝의 "저장 … 약 $" 와 겹침)
RUN_START = re.compile(r'^\[(\d{4}-\d{2}-\d{2})\s+\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\]\s*start')


def daily_costs(run_log):
    """run.log 의 "약 $" 를 날짜별로 더한다. 두 번 세지 않게 미리 어림한 "예상 약 $" 줄과
    진행 줄("50/300 · … 약 $" — 누적 금액이라 마지막 "저장 … 약 $" 와 같은 돈)은 뺀다."""
    costs, day = defaultdict(float), None
    for line in run_log.split('\n'):
        m = re.match(r'\[(\d{4}-\d{2}-\d{2})\s', line)
        if m:
            day = m.group(1)
        if '예상 약 $' in line or PROGRESS.match(line):
            continue
        m = re.search(r'약 \$([0-9.]+)', line)
        if m and day:
            costs[day] += float(m.group(1))
    return dict(costs)


def area_cost(book, logs, records):
    costs = daily_costs(logs['run_log'])
    recent = sorted(costs.items())[-5:]
    if not recent:
        raise RuntimeError('배치 기록에 비용 줄 없음')
    book.add('9', '하루 AI 비용', round(statistics.mean(v for _, v in recent), 3), 'usd',
             detail='%s · 자격요건 추출 비용은 기록에 금액이 없어 빠짐' % ', '.join('%s $%.3f' % (d[5:], v) for d, v in recent),
             source='배치 기록 run.log "약 $"(최근 %d일)' % len(recent))
    for key in ('server_price_now', 'server_price_gpu'):
        add_record(book, records, key)


# ── 10 개발 품질 ────────────────────────────────────────────────────────
def codex_docs():
    found = []
    for p in glob.glob(os.path.join(ROOT, 'docs', 'reviews', '*', '*.md')):
        if re.search(r'_REVIEW(_RECHECK\d*)?_\d{8}\.md$', p) or re.search(r'_RESULT_\d{8}\.md$', p):
            found.append(p)
    for p in glob.glob(os.path.join(ROOT, 'docs', 'notice_api', 'CODEX_*.md')):
        if not re.search(r'_(REQUEST|RESPONSE)_', os.path.basename(p)):
            found.append(p)
    return sorted(found)


def run_tests():
    r = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'unittest', 'discover', '-s', 'tests'], cwd=ROOT,
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    m = re.search(r'Ran (\d+) tests', r.stderr)
    tail = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ''
    return (int(m.group(1)) if m else None), r.returncode == 0, tail


def area_dev(book, with_tests):
    if with_tests:
        n, ok, tail = run_tests()
        if n is None:
            raise RuntimeError('시험 결과를 읽지 못함')
        book.add('10', '자동 테스트 수', n, 'count', '모두 통과', ('통과 · ' if ok else '실패 있음 · ') + tail, 'unittest discover -s tests')
        if not ok:
            book.missing.append({'name': '자동 테스트 수', 'reason': '실패한 시험 있음', 'expected': False})
    docs = codex_docs()
    rev = sum(1 for p in docs if os.sep + 'reviews' + os.sep in p)
    book.add('10', 'AI 교차 검수 결과 문서 수', len(docs), 'count',
             detail='검수 폴더 %d · 조율 창구·가산점 검수 %d (요청·답변 문서 제외)' % (rev, len(docs) - rev),
             source='docs/reviews/*/ · docs/notice_api/CODEX_*')
    dec = glob.glob(os.path.join(ROOT, 'docs', 'tracking', 'decisions', '[0-9][0-9][0-9][0-9]-*.md'))
    book.add('10', '결정 기록 수', len(dec), 'count', source='docs/tracking/decisions/')


# ── 11 약점과 한계 ──────────────────────────────────────────────────────
def area_weak(book, acc):
    jev = latest('jev_judge_probe_*')
    j = read_json(os.path.join(jev, 'summary.json'))
    same = j.get('same_pairs') or {}
    for who, label in (('llm_gpt41mini_A', 'LLM(gpt-4.1-mini)'), ('jev', 'Jev')):
        x = same.get(who)
        if isinstance(x, dict):
            book.add('11', '판정자 일치율: %s vs 사람' % label, x['exact'], 'ratio', '≥0.70',
                     '가중 카파 %.2f (기준 ≥0.60) · 0↔2 뒤바뀜 %.1f%% (기준 ≤3%%) · n=%d' % (x['kappa'], 100 * x['swap02'], x['n']),
                     'reports/' + os.path.basename(jev), 'record', folder_date(jev))
    book.add('11', '평가 질의 수', len(normal_queries()), 'count', detail='정답 판정 1,617쌍(사람·AI 판정 섞임, AI 참고 정답 포함)',
             source='eval/queries.jsonl · eval/qrels.jsonl')
    base, now, now_dir = acc
    texts = [
        ('약점: 신청 불가 0%의 뜻', '같은 규칙으로 거른 결과',
         '지금 서비스의 신청 불가 0%는 서비스가 추천 전에 같은 규칙으로 걸러 낸 결과다. "확실히 신청할 수 없는 공고를 추천에서 모두 뺀다"는 뜻이지, 판정이 틀릴 일이 없다는 뜻은 아니다.',
         'docs/business-rules.md · eval/filter_first_eval.py'),
        ('약점: K-Startup 첨부 미수집', 'K-Startup 가산점·첨부 정보 없음',
         'K-Startup은 첨부 공고문 자동 수집이 금지(robots.txt)되고 URL 제공도 거절되어, K-Startup 공고는 가산점과 첨부 기반 정보가 늘 비어 있다.',
         'docs/tracking/status.md "막힌 것"'),
        ('약점: 업종 순위 꺼짐', '업종 신호는 순위에 안 씀', '업종 판정으로 순위를 조정하면 밀리면 안 될 공고가 밀려(3. AI 판정의 부당 밀림) 기본으로 꺼 두었다.',
         'docs/tracking/status.md "만들었지만 완성 아님"'),
        ('약점: 매일 09:00~09:20 "지연"', '서버 이전 전까지 매일 약 20분',
         '시험 서버는 09:00 배치 뒤 09:20에 다시 켜져, 그 사이 수집 상태가 "지연"으로 나오고 조율 쪽 추천이 0건이 된다(서버 이전 뒤 새벽 순서로 바뀌면 사라짐).',
         'docs/tracking/findings.md'),
        ('약점: 하루 AI 비용에서 빠진 것', '자격요건 추출 비용', '배치 기록에 자격요건 추출 금액이 남지 않아 하루 AI 비용에서 빠져 있다.',
         '배치 기록 run.log'),
    ]
    if now:
        readme = 'reports/%s/README.md' % os.path.basename(now_dir or '')
        b, n = base.get('p3_lo') or {}, ((now.get('summary') or {}).get('hybrid') or {}).get('p3_lo') or {}
        queries = (now.get('meta') or {}).get('queries')
        run_day = short(folder_date(now_dir)) if folder_date(now_dir) else '다시 잰 날'
        if n.get('filter_first') is not None and b.get('filter_first') is not None and n['filter_first'] < b['filter_first']:
            gap = cell_gap(n['filter_first'], b['filter_first'], queries)
            if gap is not None and gap <= 2:
                texts.append(('참고: 다시 잰 정확도(9/28 대비)',
                              '상위 3건 적합 %.1f%% → %.1f%%(%s칸 중 %d칸 차이)' % (b['filter_first'] * 100, n['filter_first'] * 100, num(queries * 3), gap),
                              '같은 질문·같은 정답·같은 기준일로 %s 서비스를 다시 재니 9/28과 %d칸 차이였다. 이 정도는 차이를 말할 수 없다.' % (run_day, gap),
                              readme))
            else:
                texts.append(('약점: 다시 잰 정확도가 9/28보다 낮음',
                              '상위 3건 적합 %.1f%% → %.1f%%' % (b['filter_first'] * 100, n['filter_first'] * 100),
                              '같은 질문·같은 정답·같은 기준일로 %s 서비스를 다시 재니 9/28보다 낮게 나왔다. 원인은 4. 추천 정확도의 다시 재기 결과 폴더 설명을 본다.' % run_day,
                              readme))
        t = ((now.get('summary_today_status') or {}).get('hybrid') or {}).get('p3_lo') or {}
        if t.get('filter_first') is not None:
            texts.append(('약점: 평가 시점 어긋남', '%s 모집 상태로 재면 상위 3건 적합 %.1f%%' % (run_day, t['filter_first'] * 100),
                          '평가는 9/15 기준인데 공고의 "모집 중/마감" 표시를 다시 잰 날(%s) 값으로 쓰면, 그 뒤 마감된 공고가 신청 불가로 빠져 숫자가 낮아진다. '
                          '시계는 9/15로 돌려 놓고 가게 팻말만 %s 것을 건 셈이라, 한눈에 보기는 9/15 당시 모집 상태로 맞춘 값을 쓴다.' % (run_day, run_day),
                          readme))
    for name, value, plain, source in texts:
        book.add('11', name, value, 'text', detail='', source=source, kind='record', plain=plain)


# ── ML 서비스 밖 실험 ──────────────────────────────────────────────────
def area_ml(book, records):
    r = read_json(os.path.join(ROOT, 'ml', 'data', 'reranker_results.json'))
    sysd = {s['system']: s for s in r['systems']}
    b, a = sysd.get('rrf (의미+단어)'), sysd.get('rrf+rerank (학습)')
    n = a['queries']
    book.add('ML', 'ML 리랭커: 상위 3건 적합(학습 전 → 학습 후)', a['p3_rec'], 'ratio', '참고',
             '하이브리드 %.3f → 리랭커(학습) %.3f · 시험 질의 %d개 · 95%% 구간 [%.2f, %.2f] — 구간이 넓어 차이를 단정할 수 없다' % (
                 b['p3_rec'], a['p3_rec'], n, a['p3_rec_ci95'][0], a['p3_rec_ci95'][1]),
             'ml/data/reranker_results.json', 'record', '2026-09-16',
             compare={'before': b['p3_rec'], 'after': a['p3_rec'], 'label_before': '하이브리드', 'label_after': '리랭커(학습)'})
    book.add('ML', 'ML 리랭커: nDCG@3(학습 전 → 학습 후)', a['ndcg3'], 'score', '참고',
             '하이브리드 %.3f → 리랭커(학습) %.3f · 시험 질의 %d개' % (b['ndcg3'], a['ndcg3'], n),
             'ml/data/reranker_results.json', 'record', '2026-09-16',
             compare={'before': b['ndcg3'], 'after': a['ndcg3'], 'label_before': '하이브리드', 'label_after': '리랭커(학습)'})
    for key in ('reranker_query_ms', 'reranker_gpu_memory'):
        add_record(book, records, key)
    m = read_json(os.path.join(ROOT, 'ml', 'data', 'ml_experiments.json'))
    e = next(x for x in m['experiments'] if x['exp'] == m['chosen'])
    book.add('ML', 'ML 업력 분류기 F1(시험)', e['f1'], 'score', '참고',
             '%s(%s) · 정확도 %.3f · 시험 %d건(학습 %d건) · 실험 %d가지 비교' % (e['exp'], e['desc'], e['accuracy'], m['n_test'], m['n_train'],
                                                               len(m['experiments'])),
             'ml/data/ml_experiments.json', 'record', '2026-09-16')
    book.add('ML', 'ML: 서비스에 안 쓴 이유', '서버 4GB·CPU에 못 올림', 'text', '참고',
             '리랭커는 GPU에서도 질의당 1초가 넘고 GPU 메모리가 필요해 4GB CPU 서버에 올리지 못했다. 업력 분류기는 시연 화면에만 쓴다.',
             'ml/AGENTS.md · docs/tracking/decisions/0004-hybrid-search.md', 'record', '2026-09-28',
             plain='두 모델은 학습·평가까지 했고 서비스 추천 경로에는 연결하지 않았다.')


# ── 한눈에 보기 ────────────────────────────────────────────────────────
def headline(book):
    by = {m['name']: m for m in book.metrics}
    queries = (book.raw.get('acc_meta') or {}).get('queries')
    q_text = '평가 질의 %s개 기준. ' % queries if queries else ''
    p3 = by.get(P3_LO) or {}
    ref = ((p3.get('compare') or {}).get('reference') or {}).get('after')
    hi = (by.get(P3_HI) or {}).get('value')
    judge = (by.get('판정자 일치율: LLM(gpt-4.1-mini) vs 사람') or {}).get('value')
    # 그림(PNG)만 떼어 붙여도 뜻이 통하게: 낮게 센 값이라는 것, 높게 센 값, 판정 일부가 AI 라는 것을 함께 적는다
    p3_note = q_text + '판정이 없는 공고는 안 맞음으로 센 낮은 쪽 값이다%s.' % (
        '(높게 세면 %.1f%%)' % (hi * 100) if is_num(hi) else '')
    share = ai_share_text(judge)
    if share:
        p3_note += ' %s.' % share
    gap = cell_gap(p3.get('value'), ref, queries)
    if p3.get('value') is not None and ref is not None and p3['value'] != ref and gap is not None and gap <= 2:
        p3_note += ' 9/28 평가(%.1f%%)와 %s칸 중 %d칸 차이라 차이를 말할 수 없다.' % (ref * 100, num(queries * 3), gap)
    elif p3.get('value') is not None and ref is not None and p3['value'] < ref:
        p3_note += ' 9/28 평가(%.1f%%)보다 %.1f%%p 낮다(%s칸 중 %s칸).' % (ref * 100, (ref - p3['value']) * 100,
                                                                 num(queries * 3) if queries else '-', gap if gap is not None else '-')
    elif ref is not None:
        p3_note += ' 9/28 평가는 참고로 함께 보인다.'
    cards = [
        {'title': '신청 불가 공고 비율(상위 10건)', 'values': [{'label': '지금 서비스', 'metric': INELIGIBLE}], 'chart': INELIGIBLE,
         'note': q_text + '지금 서비스 값이 0%인 것은 서비스가 채점과 같은 규칙으로 걸러 낸 결과다(확실히 신청할 수 없는 공고를 추천에서 모두 뺀다는 뜻).'},
        {'title': '상위 3건 적합 비율', 'values': [{'label': '지금 서비스', 'metric': P3_LO}], 'chart': P3_LO, 'note': p3_note},
        {'title': '공고 수', 'values': [{'label': '누적', 'metric': '누적 공고 수'},
                                     {'label': '하루 평균 신규(새 공고가 들어온 날)', 'metric': '하루 평균 신규 공고'}],
         'chart': None, 'note': '매일 자동 수집(K-Startup·기업마당 공공 API)'},
        {'title': '첨부 공고문 글자 뽑기', 'values': [{'label': '성공률', 'metric': '첨부 공고문 본문 추출 성공률'}], 'chart': None,
         'note': '이미지 스캔본은 글자가 없어 실패로 센다'},
        {'title': '조율 연결', 'values': [{'label': '연결 시험', 'metric': '연결 계약 시험 통과'},
                                      {'label': '자격 판정 형식 오류', 'metric': '자격 판정 응답 형식 오류'}],
         'chart': None, 'note': '조율 에이전트의 실제 코드로 공고 서버를 불러 확인(최근 기록)'},
        {'title': '추천 응답 시간', 'values': [{'label': '이 PC 기준', 'metric': '추천 응답 시간(이 PC, 중앙값)'},
                                        {'label': '실제 서버 기준(인터넷 포함)', 'metric': '추천 응답 시간(실제 서버, 중앙값)'}],
         'chart': None, 'note': '이 PC 기준은 이 PC 안에서 잰 값(인터넷 시간 빠짐), 실제 서버 기준은 사용자가 실제로 기다리는 시간'},
        {'title': '하루 AI 비용', 'values': [{'label': '최근 배치 평균', 'metric': '하루 AI 비용'}], 'chart': None,
         'note': '자격요건 추출 비용은 기록에 금액이 없어 빠짐'},
    ]
    names = book.names()
    for c in cards:
        for v in c['values']:
            if v['metric'] not in names:
                raise ValueError('한눈에 보기가 없는 지표를 가리킨다: %s' % v['metric'])
    return cards


# ── 그래프(metrics.json 의 "charts") ───────────────────────────────────
# 값만 계산한다. 그리기·색은 eval/metrics_doc.py. 출처가 없거나 못 읽으면 그 그래프를 빼고 이유를 화면에 쓴다(값을 지어내지 않는다).
CHART_FORMS = ('line', 'column', 'bar', 'stacked', 'pairs')
CHART_UNITS = ('ratio', 'score', 'count', 'ms', 'sec', 'min', 'mb', 'usd')
CHART_KEYS = ('id', 'area', 'title', 'subtitle', 'form', 'unit', 'units', 'categories', 'series', 'highlight', 'max',
              'reference', 'errors', 'note', 'source', 'kind', 'measured_at')
CHART_ID = re.compile(r'^[a-z0-9_]+$')
DAY = re.compile(r'^\d{4}-\d{2}-\d{2}$')
REPORT_0930 = os.path.join(REPORTS, 'metrics_20260930T105348', 'metrics.json')
UNIT_TEST_DIRS = ('unit_test_20261007T062019Z', 'unit_test_20261012T020731Z')


class NoData(Exception):
    """그래프에 쓸 값이 없다 — 그 그래프만 뺀다."""


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def check_chart(c):
    """그래프 계약 검사. 어긋나면 ValueError(그 그래프만 빠진다), 값이 하나도 없으면 NoData."""
    def bad(why):
        return ValueError('%s: %s' % (c.get('id'), why))
    if set(c) != set(CHART_KEYS):
        raise bad('키가 계약과 다름')
    if not isinstance(c['id'], str) or not CHART_ID.match(c['id']):
        raise bad('id 형식')
    if c['area'] not in AREAS:
        raise bad('영역')
    if c['form'] not in CHART_FORMS:
        raise bad('form')
    cats = c['categories']
    if not isinstance(cats, list) or not cats or not all(isinstance(x, str) and x for x in cats):
        raise bad('categories')
    n = len(cats)
    if c['form'] == 'pairs':
        if c['unit'] is not None or not isinstance(c['units'], list) or len(c['units']) != n \
                or any(u not in CHART_UNITS for u in c['units']):
            raise bad('pairs 는 unit=null, units=항목마다 단위')
    elif c['unit'] not in CHART_UNITS or c['units'] is not None:
        raise bad('단위')
    series = c['series']
    if not isinstance(series, list) or not 1 <= len(series) <= 3:
        raise bad('계열은 1~3개')
    if c['form'] == 'line' and len(series) != 1:
        raise bad('line 은 계열 1개')
    for s in series:
        if not isinstance(s, dict) or set(s) != {'name', 'values'} or not isinstance(s['name'], str) or not s['name']:
            raise bad('계열 모양')
        if not isinstance(s['values'], list) or len(s['values']) != n:
            raise bad('값 수가 항목 수와 다름')
        if any(v is not None and not is_num(v) for v in s['values']):
            raise bad('값이 숫자가 아님')
    if all(v is None for s in series for v in s['values']):
        raise NoData('%s: 값이 하나도 없음' % c['id'])
    hl = c['highlight']
    if hl is not None:
        if len(series) != 1 or not isinstance(hl, list) or len(set(hl)) != len(hl) \
                or any(not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < n for i in hl):
            raise bad('highlight')
    if c['max'] is not None:
        if not is_num(c['max']):
            raise bad('max')
        uppers = [e[1] for e in (c['errors'] or []) if isinstance(e, list) and len(e) == 2 and is_num(e[1])]
        if any(v is not None and v > c['max'] for s in series for v in s['values']) or any(u > c['max'] for u in uppers):
            raise bad('축의 끝(max)보다 큰 값')
    ref = c['reference']
    if not isinstance(ref, list) or any(not isinstance(r, dict) or set(r) != {'value', 'label'} or not is_num(r['value'])
                                        or not isinstance(r['label'], str) for r in ref):
        raise bad('reference')
    err = c['errors']
    if err is not None:
        if not isinstance(err, list) or len(err) != n:
            raise bad('errors 수')
        for e in err:
            if e is not None and not (isinstance(e, list) and len(e) == 2 and all(is_num(x) for x in e) and e[0] <= e[1]):
                raise bad('errors 구간')
    for k in ('title', 'subtitle', 'note', 'source'):
        if not isinstance(c[k], str) or not c[k].strip():
            raise bad(k)
    if c['kind'] not in ('live', 'record'):
        raise bad('kind')
    if not isinstance(c['measured_at'], str) or not DAY.match(c['measured_at']):
        raise bad('measured_at')
    return c


def chart(cid, area, title, subtitle, form, unit, categories, series, note, source, kind, measured_at,
          units=None, highlight=None, top=None, reference=None, errors=None):
    """series 는 [(이름, 값 목록)]. top 은 축의 끝(계약 키 "max")."""
    return check_chart({'id': cid, 'area': area, 'title': title, 'subtitle': subtitle, 'form': form, 'unit': unit,
                        'units': units, 'categories': list(categories),
                        'series': [{'name': name, 'values': list(values)} for name, values in series],
                        'highlight': highlight, 'max': top, 'reference': reference or [], 'errors': errors,
                        'note': note, 'source': source, 'kind': kind, 'measured_at': measured_at})


def qrels_ai_share(path=None):
    """평가 정답(qrels) 중 AI(LLM) 판정 수와 전체 수. 사람 판정은 judge='human'."""
    path = path or common.QRELS
    ai = total = 0
    with open(path, encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            total += 1
            ai += json.loads(line).get('judge') != 'human'
    return ai, total


def ai_share_text(judge=None):
    """'평가 정답 1,617쌍 중 1,474쌍(91%)은 AI 참고 정답(…)' — 정확도 그림만 떼어 붙여도 정답 출처가 보이게."""
    try:
        ai, total = qrels_ai_share()
    except OSError:
        return ''
    if not total:
        return ''
    tail = ('AI와 사람 판정 일치 %.0f%%, 기준 70%% 미달 — 참고 수치' % (judge * 100)) if is_num(judge) else '참고 수치'
    return '평가 정답 %s쌍 중 %s쌍(%.0f%%)은 AI 참고 정답(%s)' % (num(total), num(ai), ai / total * 100, tail)


def ai_share_short():
    """부제용 짧은 말: '정답의 91%는 AI 참고 정답'."""
    try:
        ai, total = qrels_ai_share()
    except OSError:
        return ''
    return ('정답의 %.0f%%는 AI 참고 정답' % (ai / total * 100)) if total else ''


def cell_gap(a, b, queries, k=3):
    """상위 k건 비율 두 값의 차이를 칸 수로(질의 수 × k 칸 기준)."""
    if not (is_num(a) and is_num(b) and queries):
        return None
    return int(round(abs(a - b) * queries * k))


def short(day):
    """'2026-10-02' → '10/2'"""
    y, m, d = str(day)[:10].split('-')
    return '%d/%d' % (int(m), int(d))


def num(v):
    return format(int(round(v)), ',')


def r6(v):
    """그래프 값은 화면에 보일 자리(비율 0.1%p = 소수 넷째 자리)보다 넉넉히 남긴다.
    넷째 자리로 한 번 줄이면 그리기 쪽에서 한 번 더 반올림할 때 틀어진다(0.8235294 → 0.8235 → 82.3%)."""
    return None if v is None else round(v, 6)


def metric(ctx, name):
    m = ctx['metrics'].get(name)
    if m is None:
        raise NoData('지표 없음: %s' % name)
    return m


def compare_of(ctx, name):
    c = metric(ctx, name).get('compare')
    if not c:
        raise NoData('전후 값 없음: %s' % name)
    return c


def cumulative_by_day(per_day, end):
    """[(YYYY-MM-DD, 그날 새 공고 수)] → 첫날부터 end 까지 모든 날짜와 누적 수(빈 날은 앞 값 그대로)."""
    counts = defaultdict(int)
    for d, n in per_day:
        counts[str(d)[:10]] += n
    if not counts:
        return [], []
    day, last = date.fromisoformat(min(counts)), max(end, date.fromisoformat(max(counts)))
    days, values, total = [], [], 0
    while day <= last:
        total += counts.get(day.isoformat(), 0)
        days.append(day.isoformat())
        values.append(total)
        day += timedelta(days=1)
    return days, values


def daily_new(per_day, end, span=30):
    """end 까지 최근 span 일의 날짜별 새 공고 수 — 없던 날은 0. 첫 수집일보다 앞 날짜는 넣지 않는다."""
    counts = defaultdict(int)
    for d, n in per_day:
        counts[str(d)[:10]] += n
    start = end - timedelta(days=span - 1)
    if counts:
        start = max(start, date.fromisoformat(min(counts)))
    days = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    return days, [counts.get(d, 0) for d in days]


def batch_minutes(rows, today):
    """첫 배치일부터 날짜마다(한국 날짜) 배치 소요 시간(분) — 배치가 안 돈 날은 None(빈칸, 0으로 짐작하지 않는다).
    마지막 날은 오늘 배치가 돌았으면 오늘, 아니면 어제(지표 '배치 가동일 비율'과 같은 기준).
    (날짜 목록, 값 목록, 서버에서 처음 돈 날(SERVER_FIRST_RUN)부터의 위치)."""
    by_day = batch_days(rows, today)
    if not by_day:
        return [], [], []
    day = date.fromisoformat(min(by_day))
    end = max(date.fromisoformat(max(by_day)), today if today.isoformat() in by_day else today - timedelta(days=1))
    days, values, after = [], [], []
    while day <= end:
        r = by_day.get(day.isoformat())
        if day >= SERVER_FIRST_RUN:
            after.append(len(days))
        days.append(day.isoformat())
        values.append(round(r['elapsed_sec'] / 60, 1) if r and is_num(r.get('elapsed_sec')) else None)
        day += timedelta(days=1)
    return days, values, after


def cost_days(run_log, span=14):
    """비용 그래프용 — run.log 에서 배치가 시작된 날 가운데 비용 줄이 처음 나온 날부터 최근 span 일.
    비용이 0인 날도 넣는다. 배치는 돌았는데 비용 줄이 없는 날은 None(모름 — 0으로 짐작하지 않는다)."""
    costs = daily_costs(run_log)
    if not costs:
        return [], []
    first = min(costs)
    days = set(costs)
    for line in run_log.split('\n'):
        m = RUN_START.match(line)
        if m and m.group(1) >= first:
            days.add(m.group(1))
    picked = sorted(days)[-span:]
    return picked, [r6(costs[d]) if d in costs else None for d in picked]


def readme_test_count(folder):
    m = re.search(r'전체 ([0-9,]+)개', read_text(os.path.join(REPORTS, folder, 'README.md')))
    if not m:
        raise NoData('%s README 에 "전체 N개" 없음' % folder)
    return int(m.group(1).replace(',', ''))


def chart_db(cur, connection, today, say=print):
    """그래프용 공용 DB 조회(SELECT만). 조각마다 따로 해서 하나가 실패해도 나머지는 남는다."""
    out = {}

    def per_day():
        cur.execute("SELECT DATE(CONVERT_TZ(created_at, '+00:00', '+09:00')) d, COUNT(*) FROM notices "
                    'WHERE created_at IS NOT NULL GROUP BY d ORDER BY d')
        return [(str(d), int(n)) for d, n in cur.fetchall() if d is not None]

    def by_source():
        cur.execute('SELECT source, COUNT(*) FROM notices GROUP BY source')
        return {k: int(v) for k, v in cur.fetchall()}

    def open_by_source():
        from eval.bonus_conservative_compare import open_ids
        got = defaultdict(int)
        for i in open_ids(connection, today):
            got[i.split(':', 1)[0]] += 1
        return dict(got)

    def att_status():
        cur.execute('SELECT t.last_status, COUNT(*) FROM attachment_texts t JOIN notice_attachments a ON a.id=t.attachment_fk '
                    'WHERE a.active GROUP BY 1')
        return {k: int(v) for k, v in cur.fetchall()}

    def att_sources():
        cur.execute('SELECT n.source, COUNT(*) FROM attachment_texts t JOIN notice_attachments a ON a.id=t.attachment_fk '
                    'JOIN notices n ON n.id=a.notice_fk WHERE a.active GROUP BY 1')
        return {k: int(v) for k, v in cur.fetchall()}

    def period_types():
        cur.execute('SELECT apply_period_type, COUNT(*) FROM notices GROUP BY 1')
        return {k: int(v) for k, v in cur.fetchall()}

    for key, fn in (('per_day', per_day), ('by_source', by_source), ('open_by_source', open_by_source),
                    ('att_status', att_status), ('att_sources', att_sources), ('period_types', period_types)):
        try:
            out[key] = fn()
        except Exception as exc:                   # 원문에 주소·SQL 값이 섞일 수 있어 종류만
            say('그래프용 공용 DB 조회 실패: %s (%s)' % (key, type(exc).__name__))
    return out


def db_part(ctx, key):
    v = ctx['db'].get(key)
    if not v:
        raise NoData('공용 DB 값을 읽지 못함(%s)' % key)
    return v


# 1 수집·운영
def c01_cumulative_notices(ctx):
    per_day = db_part(ctx, 'per_day')
    days, values = cumulative_by_day(per_day, ctx['today'])
    first = min(per_day)
    return chart('c01_cumulative_notices', '1', '누적 공고 수',
                 '첫 수집일(%s)부터 오늘까지 날짜별로 쌓인 공고 수(건, DB에 들어온 한국 날짜 기준)' % short(days[0]),
                 'line', 'count', [short(d) for d in days], [('누적 공고', values)],
                 '%s 처음 %s건을 한꺼번에 넣은 뒤 매일 배치로 조금씩 늘어 지금 %s건이 쌓였다.' % (short(first[0]), num(first[1]), num(values[-1])),
                 '공용 DB notices.created_at(UTC → 한국 시간)', 'live', ctx['today'].isoformat())


def c02_daily_new_notices(ctx):
    per_day = db_part(ctx, 'per_day')
    today = ctx['today']
    end = today if any(str(d)[:10] == today.isoformat() for d, _ in per_day) else today - timedelta(days=1)
    days, values = daily_new(per_day, end, 30)
    zero = sum(1 for v in values if v == 0)
    note = '%d일 중 %d일은 0건이다 — 주말·연휴라 새 공고가 없었거나(배치는 아침에 전날까지 올라온 공고를 받는다)' % (len(days), zero)
    if days and date.fromisoformat(days[0]) < SERVER_FIRST_RUN:
        note += ', 서버에서 배치가 처음 돈 %s 전 PC가 꺼져 배치가 돌지 않은 날이다(그날 공고는 다음 배치 날에 함께 들어왔다).' % short(SERVER_FIRST_RUN)
    else:
        note = note.replace('없었거나', '없었던 날이다', 1) + '.'
    nonzero = [v for v in values if v]
    if nonzero and zero:                     # 한눈에 보기의 '하루 평균 신규'(공고가 들어온 날 평균)와 헷갈리지 않게 두 평균을 함께
        note += ' 새 공고가 들어온 날만 세면 하루 평균 %s건, 0인 날까지 넣은 %d일 평균은 %s건이다.' % (
            num(statistics.mean(nonzero)), len(days), num(statistics.mean(values)))
    return chart('c02_daily_new_notices', '1', '하루 새 공고 수', '최근 %d일 날짜별로 새로 들어온 공고 수(건, 0인 날 포함)' % len(days),
                 'column', 'count', [short(d) for d in days], [('새 공고', values)], note,
                 '공용 DB notices.created_at(UTC → 한국 시간)', 'live', today.isoformat())


def c03_notices_by_source(ctx):
    by, op = db_part(ctx, 'by_source'), ctx['db'].get('open_by_source')
    if op is None:
        raise NoData('지금 모집 중인 공고를 읽지 못함')
    names = [('kstartup', 'K-Startup'), ('bizinfo', '기업마당')]
    others = sorted(set(by) - {k for k, _ in names})
    series = [(label, [by.get(k, 0), op.get(k, 0)]) for k, label in names]
    if others:
        series.append(('그 밖', [sum(by.get(k, 0) for k in others), sum(op.get(k, 0) for k in others)]))
    total, total_open = sum(by.values()), sum(op.values())
    note = '누적의 %d%%, 지금 모집 중의 %d%%가 기업마당 공고다.' % (round(100 * by.get('bizinfo', 0) / total),
                                                       round(100 * op.get('bizinfo', 0) / total_open) if total_open else 0)
    return chart('c03_notices_by_source', '1', '출처별 공고 수', '누적 공고와 지금 모집 중인 공고를 출처별로 나눈 수(건)',
                 'stacked', 'count', ['누적', '지금 모집 중'], series, note,
                 '공용 DB notices(지금 모집 중 = 모집 종료 아님·마감일 안 지남)', 'live', ctx['today'].isoformat())


def c04_batch_minutes(ctx):
    logs = ctx['logs'] or {}
    days, values, after = batch_minutes(logs.get('collect_rows') or [], ctx['today'])
    if not days:
        raise NoData('배치 기록 없음')
    after_set = set(after)
    after_vals = [values[i] for i in after if values[i] is not None]
    first = short(SERVER_FIRST_RUN)
    note = '진한 막대가 서버에서 배치가 처음 돈 %s부터다' % first
    if after_vals:
        note += ' — 그 뒤 중앙값은 %.1f분이다%s' % (
            statistics.median(after_vals), '(새 공고가 없는 날은 1분 안에 끝나 막대가 아주 낮다)' if any(v < 1 for v in after_vals) else '')
    note += '.'
    before_gap = sum(1 for i, v in enumerate(values) if v is None and i not in after_set)
    after_gap = sum(1 for i in after if values[i] is None)
    gaps = (['서버 이전 전 PC가 꺼진 날 %d일' % before_gap] if before_gap else []) + \
        (['서버에서 돈 뒤 %d일' % after_gap] if after_gap else [])
    if gaps:
        note += ' 빈 동그라미는 배치가 돌지 않은 날이다(%s).' % ', '.join(gaps)
    return chart('c04_batch_minutes', '1', '하루 배치 소요 시간',
                 '첫 배치일부터 날짜별 배치 소요 시간(분) · 같은 날 여러 번이면 가장 오래 걸린 한 번 · 빈 동그라미 = 배치가 안 돈 날',
                 'column', 'min', [short(d) for d in days], [('소요 시간', values)], note,
                 batch_src(logs, 'collect_log'), 'live', ctx['today'].isoformat(), highlight=after or None)


# 2 전처리 품질
def c05_attachment_extraction(ctx):
    st = db_part(ctx, 'att_status')
    names = [('ok', '성공'), ('image_only', '그림만 있음'), ('parse_error', '읽기 오류')]
    cats, vals = [label for _, label in names], [st.get(k, 0) for k, _ in names]
    others = sorted(set(st) - {k for k, _ in names})
    if others:
        cats.append('그 밖(%s)' % ', '.join(str(k) for k in others))
        vals.append(sum(st[k] for k in others))
    total = sum(vals)
    fail = total - st.get('ok', 0)
    srcs = ctx['db'].get('att_sources') or {}
    biz_only = bool(srcs) and set(srcs) == {'bizinfo'}      # 지금은 K-Startup 첨부를 받지 않아 모두 기업마당 공고다
    who = '기업마당 공고의 첨부' if biz_only else '첨부'
    note = '%s %s건 중 %.1f%%에서 글자를 뽑았다' % (who, num(total), 100 * st.get('ok', 0) / total)
    note += (' — 실패 %s건 중 %s건은 글자가 없는 그림(스캔본) 파일이다.' % (num(fail), num(st.get('image_only', 0)))) if fail else '.'
    sub = '%s 공고문(PDF·HWP 등)을 결과별로 센 수(건)' % who
    if biz_only:
        sub += ' · K-Startup은 첨부를 받지 않아 빠짐'
    return chart('c05_attachment_extraction', '2', '첨부 공고문 글자 뽑기 결과', sub,
                 'bar', 'count', cats, [('첨부 수', vals)], note, '공용 DB attachment_texts(지금 쓰는 첨부)', 'live',
                 ctx['today'].isoformat(), highlight=[0])


def c06_apply_period_types(ctx):
    types = db_part(ctx, 'period_types')
    names = {'fixed': '기간 고정', 'budget_exhaustion': '예산 소진', 'rolling': '상시', 'until_filled': '선착순', 'unknown': '모름'}
    rows = sorted(types.items(), key=lambda kv: (-kv[1], str(kv[0])))
    total = sum(types.values())
    top = rows[0]
    note = '가장 많은 유형은 "%s"(%s건)이고, 해석하지 못한 "모름"은 %s건(%.1f%%)이다.' % (
        names.get(top[0], top[0]), num(top[1]), num(types.get('unknown', 0)), 100 * types.get('unknown', 0) / total)
    return chart('c06_apply_period_types', '2', '접수기간 유형', '접수기간 원문을 유형별로 나눈 공고 수(건, 많은 순)',
                 'bar', 'count', [names.get(k, str(k)) for k, _ in rows], [('공고 수', [v for _, v in rows])], note,
                 '공용 DB notices.apply_period_type', 'live', ctx['today'].isoformat())


# 3 AI 판정
def c07_judgment_coverage(ctx):
    items = [('자격요건', '판정표 적용 범위: 자격요건(금액·형태·업력)'), ('신청자 유형', '판정표 적용 범위: 신청자 유형'),
             ('업종', '판정표 적용 범위: 업종'), ('가점(열린 기업마당)', '판정표 적용 범위: 가점(열린 기업마당 공고)')]
    vals = [r6(metric(ctx, name)['value']) for _, name in items]
    known = [(label, v) for (label, _), v in zip(items, vals) if v is not None]
    if not known:
        raise NoData('영역 3 적용 범위 값 없음')
    cov = (ctx.get('raw') or {}).get('coverage') or {}
    bases = {'자격요건': '첨부 글자 있는 %s건 중', '신청자 유형': '전체 %s건 중', '업종': '전체 %s건 중',
             '가점(열린 기업마당)': '열린 기업마당 %s건 중'}
    cats = []
    for label, name in items:                       # 막대마다 분모가 다르다 — 이름에 분모를 넣는다
        c = cov.get(name) or {}
        cats.append('%s(%s)' % (label.replace('(열린 기업마당)', ''), bases[label] % num(c['base'])) if is_num(c.get('base')) else label)
    low = min(known, key=lambda x: x[1])
    note = '가장 낮은 것은 "%s" %.0f%%다 — 판정할 글(본문·가점 문구)이 없는 공고는 빠질 수 있다.' % (low[0], low[1] * 100)
    c = cov.get(items[0][1]) or {}
    if all(is_num(c.get(k)) for k in ('judged', 'base', 'notices')) and c['notices'] > c['base']:
        note += (' 자격요건은 첨부 글자를 뽑은 공고만 센 값이라, 전체 %s건으로 보면 %.0f%%다'
                 '(K-Startup 공고 등 첨부 글자가 없는 공고 %s건은 자격요건 판정이 없다).') % (
            num(c['notices']), 100 * c['judged'] / c['notices'], num(c['notices'] - c['base']))
    return chart('c07_judgment_coverage', '3', 'AI 판정표 적용 범위',
                 'AI 판정이 들어 있는 공고 비율 · 막대마다 기준이 되는 공고(분모)가 다르다(이름 괄호 안)',
                 'bar', 'ratio', cats, [('적용 비율', vals)], note,
                 '공용 DB notice_conditions·notice_applicant_types·notice_industries·notice_bonus', 'live',
                 ctx['today'].isoformat(), top=1)


def c08_type_agreement(ctx):
    a = read_json(os.path.join(REPORTS, 'label_pack_20260928', 'score.json'))['agreement']
    items = [('예비창업자', 'pre_founder'), ('개인사업자', 'sole_proprietor'), ('법인', 'corporation')]
    vals = [r6(a[k]['rate']) for _, k in items]
    pairs = sorted(zip([label for label, _ in items], vals), key=lambda x: x[1])
    total = a['pre_founder']['total']
    return chart('c08_type_agreement', '3', '신청자 유형 판정 일치율',
                 '신청자 유형 판정이 AI 참고 정답(Codex 블라인드 판정)과 같은 비율 · 공고 %d건' % total,
                 'bar', 'ratio', [label for label, _ in items], [('일치율', vals)],
                 '가장 낮은 것은 %s(%.0f%%), 가장 높은 것은 %s(%.0f%%)다.' % (pairs[0][0], pairs[0][1] * 100, pairs[-1][0], pairs[-1][1] * 100),
                 'reports/label_pack_20260928/score.json', 'record', '2026-09-28', top=1)


# 4 추천 정확도
def c09_accuracy_before_after(ctx):
    base, now, now_dir = ctx['acc'] or ({}, None, None)
    s = ((now or {}).get('summary') or {}).get('hybrid') or {}
    if not s:
        raise NoData('지금 서비스 다시 재기 결과 없음(reports/filter_first_now_*)')
    # 줄 이름에 좋은 방향을 붙인다(낮을수록·높을수록이 섞여 있어 "막대가 길다 = 좋다"로 읽히지 않게).
    # 판정 없는 칸은 좋고 나쁨이 아니라 참고 값이다(평가 정답에 아직 없는 공고 비율 — 근거 보고서도 '참고').
    keys = [('ineligible_k', '상위 10건 중 신청 불가 (낮을수록 좋음)'), ('p3_lo', '상위 3건 적합, 낮게 센 값 (높을수록 좋음)'),
            ('p3_hi', '상위 3건 적합, 높게 센 값 (높을수록 좋음)'), ('unjudgedk', '상위 10건 중 판정 없는 칸 (참고)')]
    before = [r6((s.get(k) or {}).get('vector_only')) for k, _ in keys]
    after = [r6((s.get(k) or {}).get('filter_first')) for k, _ in keys]
    meta = now.get('meta') or {}
    as_of = (meta.get('status_as_of') or {}).get('date') or meta.get('as_of')
    parts = []
    if before[0] is not None and after[0] is not None:
        parts.append('신청 불가 공고를 상위 10에서 %s(%.0f%% → %.0f%%)' % ('모두 뺐고' if after[0] == 0 else '줄였고', before[0] * 100, after[0] * 100))
    if before[1] is not None and after[1] is not None:
        parts.append('상위 3건 적합(낮게 센 값)은 %.0f%% → %.0f%%가 됐다' % (before[1] * 100, after[1] * 100))
    note = '지금 서비스는 ' + ', '.join(parts) + '.' if parts else '%s과 지금 서비스를 같은 질문·정답으로 비교했다.' % BEFORE_NAME
    if after[0] == 0:
        note += ' 신청 불가 0%는 서비스가 채점과 같은 규칙으로 걸러 낸 결과다(확실히 신청할 수 없는 공고를 빼도록 만든 대로 동작한다는 뜻).'
    if before[3] is not None and after[3] is not None:
        note += ' 판정 없는 칸(%.0f%% → %.0f%%)은 평가 정답에 아직 없는 공고 비율이라 참고로만 보고, 실제 적합은 낮게 센 값과 높게 센 값 사이다.' % (
            before[3] * 100, after[3] * 100)
    sub = '평가 질의 %s개 평균 · 판정 없는 칸 = 평가 정답에 아직 없는 공고 비율(참고)' % meta.get('queries')
    if as_of:
        sub += ' · 모집 상태는 %s 당시로 맞춤' % short(as_of)
    share = ai_share_text(ctx.get('judge'))
    if share:
        sub += ' · ' + ai_share_short()
        note += ' %s.' % share
    # 나중(지금 서비스)을 첫 계열로 — 첫 계열 색(청록)이 한눈에 보기·다른 그래프의 '지금'과 같은 색이 되게
    return chart('c09_accuracy_before_after', '4', '추천 정확도: 처음과 지금', sub, 'bar', 'ratio', [label for _, label in keys],
                 [('지금 서비스', after), (BEFORE_NAME, before)], note,
                 'reports/%s/results.json (summary.hybrid)' % os.path.basename(now_dir), 'live', folder_date(now_dir), top=1)


def c10_status_timing(ctx):
    base, now, now_dir = ctx['acc'] or ({}, None, None)
    if not now:
        raise NoData('지금 서비스 다시 재기 결과 없음(reports/filter_first_now_*)')
    meta = now.get('meta') or {}
    as_of = (meta.get('status_as_of') or {}).get('date') or meta.get('as_of')
    pick = lambda summary: r6((((summary or {}).get('hybrid') or {}).get('p3_lo') or {}).get('filter_first'))
    vals = [r6(((base or {}).get('p3_lo') or {}).get('filter_first')), pick(now.get('summary')), pick(now.get('summary_today_status'))]
    as_of_label = short(as_of) if as_of else '평가 기준일'
    run_label = short(folder_date(now_dir)) if folder_date(now_dir) else '다시 잰 날'
    note = ('평가는 %s 기준인데 모집 상태를 다시 잰 날(%s) 값으로 쓰면 그 뒤 마감된 공고가 신청 불가로 빠져 숫자가 낮아지므로, '
            '%s 당시 모집 상태로 맞춘 값(진한 막대)을 쓴다.' % (as_of_label, run_label, as_of_label))
    share = ai_share_text(ctx.get('judge'))
    sub = '상위 3건 적합 비율(판정 없는 공고는 안 맞음으로 센 낮은 쪽 값) · 같은 질문·같은 정답'
    if share:
        sub += ' · ' + ai_share_short()
    return chart('c10_status_timing', '4', '모집 상태 날짜에 따른 상위 3건 적합', sub,
                 'bar', 'ratio', ['9/28 평가(그때 서비스)', '%s 서비스 · %s 모집 상태' % (run_label, as_of_label),
                                  '%s 서비스 · %s 모집 상태' % (run_label, run_label)], [(P3_LO, vals)], note,
                 'reports/filter_first_eval_20260928T104212Z · reports/%s (summary · summary_today_status)' % os.path.basename(now_dir),
                 'live', folder_date(now_dir), highlight=[1], top=1)


# 5 신청 불가 차단·자격 판정
def c11_entity_block(ctx):
    rows = [(t, compare_of(ctx, '%s "강한 불가" 공고가 상위 20에 뜬 질의' % t)) for t in ('개인사업자', '법인')]
    note = '차단 전 → 후: ' + ', '.join('%s %d → %d개' % (t, c['before'], c['after']) for t, c in rows) + ' 질의(평가 질의 58개 중).'
    if dict(rows)['법인']['after'] == 1:
        # 근거: reports/entity_block_after_20261013T031546Z/README.md B·C절 — 남은 1건(121832)은 '확인 필요로 낮춤'
        note += (' 법인에 남은 1건은 원문 신청서 서식의 "법인등록번호" 칸 때문에 일부러 "확인 필요"로 낮춘 공고다'
                 '(확실하지 않으면 빼지 않는다). 차단 전 숫자도 차단에 쓰는 것과 같은 "강한 불가" 목록으로 셌다.')
    # 나중(차단 후)을 첫 계열로 — '나중'은 늘 청록
    return chart('c11_entity_block', '5', '신청 불가 공고 차단 전후',
                 '"강한 불가" 공고(그 신청자는 확실히 신청할 수 없는 공고)가 추천 상위 20에 뜬 평가 질의 수(개)',
                 'bar', 'count', [t for t, _ in rows], [('차단 후', [c['after'] for _, c in rows]), ('차단 전', [c['before'] for _, c in rows])],
                 note, 'reports/entity_block_probe_20261013T030233Z · entity_block_after_20261013T031546Z', 'record', '2026-10-13')


# 6 가산점
def c12_bonus_steps(ctx):
    open_n = metric(ctx, '지금 모집 중인 공고 수')['value']
    found = metric(ctx, '열린 공고 중 가점 언급 공고')['value']
    boost = metric(ctx, '신청자별 가산점이 나오는 공고')
    reviewed = metric(ctx, '원문 대조를 마친 가산점 공고')['value']
    vals = [open_n, found, boost['value']]
    note = '단계마다 크게 줄어든다: 신청자 입력으로 가산점이 실제로 계산되는 공고는 %s건이다.' % (num(vals[2]) if vals[2] is not None else '-')
    if reviewed is not None:
        rv = read_json(os.path.join(ROOT, 'search', 'bonus_reviewed.json'))
        who = 'AI(Claude)가 원문과 대조한 목록(%s건, AI 참고)' if all_ai_reviewed(rv) else '원문과 대조한 목록(%s건)'
        note += ' 화면·순위에는 %s에 오른 공고만 쓴다.' % (who % num(reviewed))
        # 그림의 마지막 막대(그날 계산된 공고)와 목록 수가 왜 다른지 — 같은 기록(bonus_boostable)의 목록 비교로 적는다
        bb = os.path.join(ROOT, boost['source'].split(' ')[0])
        s = read_json(os.path.join(bb, 'results.json'))['summary'] if os.path.isfile(os.path.join(bb, 'results.json')) else {}
        rc, gone = s.get('reviewed_counts') or {}, s.get('reviewed_listed_not_observed')
        if all(is_num(rc.get(k)) for k in ('listed', 'recheck', 'new')) and isinstance(gone, list) and vals[2] is not None \
                and rc['listed'] + rc['recheck'] + rc['new'] == vals[2]:
            then = rc['listed'] + rc['recheck'] + len(gone)
            note += ' %s 계산된 %s건 중 %d건은 목록에 있고%s %d건은 아직 목록 밖 새 후보다. 그날 목록 %d건 중 %d건은 그날 계산에서 나오지 않았다.' % (
                short(boost['measured_at']), num(vals[2]), rc['listed'],
                (' %d건은 다시 대조가 필요하며,' % rc['recheck']) if rc['recheck'] else '', rc['new'], then, len(gone))
    return chart('c12_bonus_steps', '6', '가산점 공고 좁혀 가기',
                 '공고 수(건) · 앞의 둘은 지금 공용 DB, 세 번째는 %s 기록' % short(boost['measured_at']),
                 'bar', 'count', ['지금 모집 중인 공고', '가점·가산점 언급이 있는 공고', '신청자 입력으로 가산점이 계산되는 공고'],
                 [('공고 수', vals)], note, '공용 DB notices·notice_bonus · %s · search/bonus_reviewed.json' % boost['source'],
                 'live', ctx['today'].isoformat())


def c13_bonus_by_persona(ctx):
    bb = latest('bonus_boostable_*')
    if not bb:
        raise NoData('reports/bonus_boostable_* 없음')
    per = read_json(os.path.join(bb, 'results.json'))['summary'].get('persona_positive') or {}
    if not per:
        raise NoData('가상 신청자별 값 없음')
    rows = [(k, len(v)) for k, v in per.items()]
    lo, hi = min(rows, key=lambda x: x[1]), max(rows, key=lambda x: x[1])
    return chart('c13_bonus_by_persona', '6', '가상 신청자별 가산점 공고', '가상 신청자마다 가산점이 계산되는 열린 공고 수(건)',
                 'bar', 'count', [k for k, _ in rows], [('공고 수', [v for _, v in rows])],
                 '신청자 속성(인증·기업 유형·지역)에 따라 크게 다르다 — 가장 적은 "%s" %d건, 가장 많은 "%s" %d건.' % (lo[0], lo[1], hi[0], hi[1]),
                 'reports/%s/results.json (summary.persona_positive)' % os.path.basename(bb), 'record', folder_date(bb))


# 7 조율 연결
G01_ALL_APPLICANT = '개인사업자 · 경기도 성남시 · 여성기업·벤처'   # experiments/notice_api_contract.py --all 이 모든 공고에 쓰는 신청자


def c14_g01_all(ctx):
    d = latest('notice_api_contract_*')
    g = ((read_json(os.path.join(d, 'results.json')).get('log') or {}).get('g01_all')) if d else None
    if not g or not is_num(g.get('notices')) or not is_num(g.get('passed')):
        raise NoData('모든 공고 자격 판정 기록 없음')
    n, ok = g['notices'], g['passed']
    note = '%s건 중 %s건 통과(%.1f%%), 통과 못 함 %s건(%.1f%%), 형식 오류 %d건 — 모든 공고에 약속한 형식으로 답했다. ' \
        '통과 못 함은 이 신청자가 확실히 신청할 수 없는 공고다(판정할 수 없으면 통과로 센다).' % (
            num(n), num(ok), 100 * ok / n, num(n - ok), 100 * (n - ok) / n, g.get('error_count') or 0)
    fakes = read_json(os.path.join(d, 'results.json')).get('fake_applicants') or []
    who = '가상 신청자 1명(%s)' % G01_ALL_APPLICANT if G01_ALL_APPLICANT in fakes else '가상 신청자 1명'
    return chart('c14_g01_all', '7', '모든 공고 자격 판정', '%s으로 모든 공고에 자격 판정을 요청한 결과(건)' % who,
                 'stacked', 'count', ['모든 공고 %s건' % num(n)], [('통과', [ok]), ('통과 못 함', [n - ok])], note,
                 'reports/%s/results.json (log.g01_all)' % os.path.basename(d), 'record', folder_date(d))


# 8 서버 성능
PC_LATENCY = '추천 응답 시간(이 PC, 중앙값)'


def past_pc_latency():
    """지난 새 형식 실행(reports/metrics_*Z)이 잰 '이 PC' 추천 응답 시간 중앙값. [(폴더 이름, 값)]"""
    out = []
    for d in sorted(glob.glob(os.path.join(REPORTS, 'metrics_*Z'))):
        try:
            ms = read_json(os.path.join(d, 'metrics.json')).get('metrics') or []
        except (OSError, ValueError, AttributeError):
            continue
        for m in ms:
            if isinstance(m, dict) and m.get('name') == PC_LATENCY and is_num(m.get('value')):
                out.append((os.path.basename(d), m['value']))
    return out


UNIT_WORDS = {'ms': 'ms', 'sec': '초', 'min': '분', 'mb': 'MB', 'usd': '달러', 'ratio': '%', 'count': '건', 'score': '점수'}


def with_topic(word):
    """받침에 맞춰 '은/는'을 붙인다: '1건' → '1건은', '만들기' → '만들기는'."""
    ch = word[-1:]
    if '가' <= ch <= '힣':
        return word + ('은' if (ord(ch) - 0xAC00) % 28 else '는')
    return word + '은(는)'


def notice_count(detail):
    """지표 설명의 '공고 2603건' → 2603 (없으면 None)."""
    m = re.search(r'공고 (\d+)건', detail or '')
    return int(m.group(1)) if m else None


def c15_latency(ctx):
    old = next(m for m in read_json(REPORT_0930)['metrics'] if m.get('name') == '매칭 응답 시간 중앙값(ms)')
    p = re.search(r'p95 ([0-9.]+)ms', old.get('detail') or '')
    lat = ctx['raw'].get('latency') or {}
    pc, srv = lat.get('pc') or {}, lat.get('server') or {}

    def r1(v):
        return None if v is None else round(v, 1)
    meds = [r1(old['value']), r1(pc.get('median')), r1(srv.get('median'))]
    p95s = [r1(float(p.group(1))) if p else None, r1(pc.get('p95')), r1(srv.get('p95'))]
    live = bool(pc or srv)
    # 9/30 값은 옛 검색 방식(10/7에 바꾸기 전)·그때 공고 수·그때 쓰던 PC에서 잰 값이다 — 조건을 이름에 드러내 '빨라졌다'로 읽히지 않게
    n_old = notice_count(old.get('detail'))
    n_now = notice_count((ctx['metrics'].get(PC_LATENCY) or {}).get('detail')) if pc else None
    cats = ['9/30 · 그때 PC(옛 검색 방식%s)' % (', 공고 %s건' % num(n_old) if n_old else ''),
            '이 PC · 지금' + ('(공고 %s건)' % num(n_now) if n_now else ''), '실제 서버 · 지금(인터넷 포함)']
    cond = '9/30 값은 그때 쓰던 PC에서 옛 검색 방식(10/7에 바꾸기 전)으로%s 잰 값이다' % (
        ' 공고 %s건을 두고' % num(n_old) if n_old else '')
    src = 'reports/metrics_20260930T105348/metrics.json' + (' · 이번 실행 /api/match 측정' if live else '')
    if pc:
        note = cond + '. 검색 방식·공고 수가 다르고 PC도 다를 수 있어, 9/30과 지금 값을 견줘 빨라졌다고 말할 수 없다.'
        past = past_pc_latency()
        runs = [v for _, v in past] + [pc['median']]
        if past:
            note += ' 이 도구로 잰 "이 PC" 값도 실행마다 %.0f~%.0fms로 달랐다(%d번).' % (min(runs), max(runs), len(runs))
            src += ' · 지난 실행 ' + ', '.join('reports/%s/metrics.json' % name for name, _ in past)
    else:
        note = '이번 실행에서는 응답 시간을 재지 않아(--latency) 9/30 값만 있다. ' + cond + '.'
    if srv:
        note += ' 실제 서버 값은 인터넷을 거친 시간(%.0fms)이라 이 PC 값과 바로 견주지 않는다.' % meds[2]
    return chart('c15_latency', '8', '추천 응답 시간',
                 '추천 요청 하나에 답하는 시간(ms) · p95 = 100번 중 95번은 이 시간 안에 답함 · 막대마다 잰 조건이 다름',
                 'bar', 'ms', cats, [('중앙값', meds), ('p95', p95s)], note, src,
                 'live' if live else 'record', ctx['today'].isoformat() if live else '2026-09-30')


def c16_embedding_cpu_gpu(ctx):
    items = [('공고 1건', '임베딩 공고 1건(CPU→GPU)'), ('검색어 1건', '임베딩 검색어 1건(CPU→GPU)'),
             ('전체 다시 만들기', '임베딩 전체 다시 만들기(CPU→GPU)')]
    cmp = [compare_of(ctx, name) for _, name in items]
    units = [metric(ctx, name)['unit'] for _, name in items]
    ratios = [c['before'] / c['after'] for c in cmp if is_num(c['before']) and is_num(c['after']) and c['after']]
    note = 'GPU가 %.0f~%.0f배 빠르다. 다만 집 PC(RTX 3060)에서 잰 값이고, 하루 새 공고는 수십 건이라 매일 배치에서 아끼는 시간은 1분 남짓이다.' % (
        min(ratios), max(ratios)) if ratios else 'CPU와 GPU의 같은 일 시간을 견줬다.'
    groups = []                                     # 같은 단위끼리 묶어 '공고 1건·검색어 1건은 ms, 전체 다시 만들기는 분'
    for (label, _), u in zip(items, units):
        for g in groups:
            if g[0] == u:
                g[1].append(label)
                break
        else:
            groups.append((u, [label]))
    by_unit = ', '.join('%s %s' % (with_topic('·'.join(labels)), UNIT_WORDS.get(u, u)) for u, labels in groups)
    return chart('c16_embedding_cpu_gpu', '8', '임베딩 CPU와 GPU', '같은 일을 집 PC의 CPU와 GPU로 한 시간(%s)' % by_unit,
                 'pairs', None, [label for label, _ in items], [('CPU', [c['before'] for c in cmp]), ('GPU', [c['after'] for c in cmp])],
                 note, 'reports/embedding_cpu_gpu_20261014T082732Z', 'record', '2026-10-14', units=units)


def c17_server_memory(ctx):
    recs = ctx['records']
    a, b = recs['notice_server_memory'], recs['batch_peak_memory']
    return chart('c17_server_memory', '8', '서버 메모리', '시험용 새 서버(4GB)에서 잰 메모리 사용량(MB)',
                 'bar', 'mb', ['공고 서버', '배치 중 최대'], [('메모리', [a['value'], b['value']])],
                 '배치가 도는 동안 서버 전체가 가장 많이 쓴 순간도 %sMB로, 4GB(4,096MB)의 약 %d%%다.' % (num(b['value']), round(100 * b['value'] / 4096)),
                 'eval/metrics_records.json (%s)' % a['source'], 'record', b['measured_at'],
                 top=4096, reference=[{'value': 4096, 'label': '서버 메모리 4GB'}])


# 9 비용
def c18_daily_ai_cost(ctx):
    logs = ctx['logs'] or {}
    days, values = cost_days(logs.get('run_log') or '', 14)
    if not days:
        raise NoData('배치 기록에 비용 줄 없음')
    known = [(d, v) for d, v in zip(days, values) if v is not None]
    zero = sum(1 for _, v in known if v == 0)
    hi = max(known, key=lambda x: x[1])
    note = ('판정할 새 공고가 없는 날 %d번은 $0이고, ' % zero if zero else '') + \
        '가장 많이 든 날(%s)도 $%.2f다 — 자격요건 추출 비용은 기록에 금액이 없어 빠졌으므로 실제 하루 비용은 이보다 많다.' % (short(hi[0]), hi[1])
    return chart('c18_daily_ai_cost', '9', '하루 AI 비용(자격요건 추출 제외)',
                 '배치가 돈 날짜별 AI 판정 비용(달러, 최근 %d개 배치 날짜, 0인 날 포함) · 자격요건 추출 비용은 빠짐' % len(days),
                 'column', 'usd', [short(d) for d in days], [('AI 비용', values)], note,
                 batch_src(logs, 'run.log') + ' · "약 $" 줄만(예상·진행 줄 제외)', 'live', ctx['today'].isoformat())


def c19_server_monthly_cost(ctx):
    recs = ctx['records']
    a, b = recs['server_price_now'], recs['server_price_gpu']
    vals = [round(a['value'] * 730, 2), round(b['value'] * 730, 2)]
    return chart('c19_server_monthly_cost', '9', '서버 한 달 요금', '한 달 요금(달러, 시간당 요금 × 730시간 · 서울 리전 온디맨드)',
                 'bar', 'usd', ['지금 서버(t3.medium)', 'GPU 서버(g4dn.xlarge)'], [('한 달 요금', vals)],
                 'GPU 서버는 지금 서버보다 한 달 요금이 약 %d배다(제3자 가격표 기준 — 실제 결정 전 AWS 계산기로 확인).' % round(vals[1] / vals[0]),
                 'eval/metrics_records.json (%s)' % a['source'], 'record', a['measured_at'])


# 10 개발 품질
def c20_test_count(ctx):
    old = next(m for m in read_json(REPORT_0930)['metrics'] if m.get('name') == '자동 테스트 수')
    cats, vals = ['9/30'], [old['value']]
    for folder in UNIT_TEST_DIRS:
        cats.append(short(folder_date(folder)))
        vals.append(readme_test_count(folder))
    now = ctx['metrics'].get('자동 테스트 수')
    live = bool(now and is_num(now['value']))
    if live:
        cats.append('지금(%s)' % short(ctx['today']))
        vals.append(now['value'])
    return chart('c20_test_count', '10', '자동 시험 수', '코드를 고칠 때마다 손으로 돌려 확인하는 자동 시험의 수(개)',
                 'column', 'count', cats, [('자동 시험', vals)],
                 '%s %s개에서 %s %s개로 늘었다 — 고칠 때마다 이 시험을 모두 돌려 실패 0을 확인한다(저장소 CI에는 아직 없음).' % (
                     cats[0], num(vals[0]), cats[-1], num(vals[-1])),
                 'reports/metrics_20260930T105348/metrics.json · ' + ' · '.join('reports/%s/README.md' % f for f in UNIT_TEST_DIRS)
                 + (' · 이번 실행 unittest' if live else ''),
                 'live' if live else 'record', ctx['today'].isoformat() if live else folder_date(UNIT_TEST_DIRS[-1]))


# 11 약점과 한계
def c21_judge_agreement(ctx):
    jev = latest('jev_judge_probe_*')
    same = (read_json(os.path.join(jev, 'summary.json')).get('same_pairs') or {}) if jev else {}
    cats, vals = [], []
    for who, label in (('llm_gpt41mini_A', 'LLM(gpt-4.1-mini)'), ('jev', 'Jev(외부 채점 모델)')):
        x = same.get(who)
        if isinstance(x, dict) and is_num(x.get('exact')):
            cats.append(label)
            vals.append(r6(x['exact']))
    if not cats:
        raise NoData('판정자 일치 결과 없음')
    when = folder_date(jev)
    sub = '관련도 판정이 사람 판정과 정확히 같은 비율 · LLM·Jev는 같은 %s쌍(%s)' % (same.get('n'), short(when) if when else '날짜 모름')
    src = 'reports/%s/summary.json' % os.path.basename(jev)
    codex_dir = os.path.join(REPORTS, 'relevance_label_pack_20260930')
    codex_path = os.path.join(codex_dir, 'score.json')
    if os.path.exists(codex_path):
        s = read_json(codex_path)
        if is_num(s.get('exact')) and s.get('controls'):
            cats.append('Codex(다른 표본)')
            vals.append(r6(s['exact']))
            sub += ', Codex는 다른 %d쌍(%s)' % (s['controls'], short(folder_date(codex_dir)))
            src += ' · reports/relevance_label_pack_20260930/score.json'
            when = max(d for d in (when, folder_date(codex_dir)) if d)      # 측정일 = 가장 늦은 출처 날짜
    codex = len(cats) > 2
    note = ('모두 기준 70%에 못 미쳐 판정 기반 정확도 숫자는 참고로 본다' if all(v < 0.70 for v in vals) else '기준 70%와 견준 값이다') + \
        ('(Codex는 표본이 달라 회색으로 두고 바로 견주지 않는다).' if codex else '.')
    # 같은 쌍으로 잰 LLM·Jev 만 진하게 — 표본이 다른 Codex 는 회색이라 '바로 견주지 않음'이 그림에서도 보인다
    return chart('c21_judge_agreement', '11', '판정자와 사람의 일치율', sub, 'bar', 'ratio', cats, [('일치율', vals)], note, src,
                 'record', when, top=1, reference=[{'value': 0.70, 'label': '기준 70%'}],
                 highlight=list(range(len(cats) - 1)) if codex else None)


# ML 서비스 밖 실험
ML_PREFIX = '서비스 밖 실험(서비스에는 안 씀) · '     # 그림만 떼어 붙여도 서비스에 쓰는 것으로 읽히지 않게
RERANK_NAMES = {'dense (현재 서비스)': '의미 검색만(9/16 당시 서비스 방식)', 'rrf (의미+단어)': '하이브리드(의미+단어)',
                'rrf+rerank (사전학습)': '하이브리드+리랭커(학습 전)', 'rrf+rerank (학습)': '하이브리드+리랭커(학습)'}
AGE_NAMES = {'EXP-01': '단어+로지스틱', 'EXP-02': '글자+로지스틱', 'EXP-03': '글자+보정 끔', 'EXP-04': '글자+SVM',
             'EXP-05': '글자+판단 보류', 'EXP-06': '글자+단위 힌트'}


def c22_reranker(ctx):
    systems = read_json(os.path.join(ROOT, 'ml', 'data', 'reranker_results.json'))['systems']
    cats = [RERANK_NAMES.get(s['system'], s['system']) for s in systems]
    vals = [r6(s['p3_rec']) for s in systems]
    errs = [[r6(s['p3_rec_ci95'][0]), r6(s['p3_rec_ci95'][1])] if s.get('p3_rec_ci95') else None for s in systems]
    hl = [i for i, s in enumerate(systems) if s['system'] == 'rrf+rerank (학습)']
    best = hl and vals[hl[0]] == max(v for v in vals if v is not None)
    note = ('학습한 리랭커가 가장 높지만(%.0f%%) ' % (vals[hl[0]] * 100) if best else '') + \
        '95% 구간(오차 막대)이 서로 크게 겹쳐, 구간이 넓어 차이를 단정할 수 없다.'
    n_now = ((((ctx.get('acc') or (None, None, None))[1]) or {}).get('meta') or {}).get('queries')
    note += ' 질의 %d개로 9/16에 한 별도 시험이라 4. 추천 정확도의 숫자%s와 견주지 않는다.' % (
        systems[0]['queries'], '(질의 %s개)' % n_now if n_now else '')
    return chart('c22_reranker', 'ML', '리랭커 실험',
                 ML_PREFIX + '검색 방식별 상위 3건 적합 비율(시험 질의 %d개, 9/16) · 오차 막대는 95%% 구간' % systems[0]['queries'],
                 'bar', 'ratio', cats, [('상위 3건 적합', vals)], note, 'ml/data/reranker_results.json', 'record', '2026-09-16',
                 highlight=hl or None, top=1, errors=errs)


def c23_age_classifier(ctx):
    m = read_json(os.path.join(ROOT, 'ml', 'data', 'ml_experiments.json'))
    exps = m['experiments']
    chosen = next(e for e in exps if e['exp'] == m['chosen'])
    # 계열이 둘이라 강조 색을 쓸 수 없다 — 고른 모델은 이름 끝에 표시한다
    cats = ['%s %s%s' % (e['exp'], AGE_NAMES.get(e['exp'], e['desc'][:12]), ' (고른 것)' if e is chosen else '') for e in exps]
    test = [r6(e['f1']) for e in exps]
    cv = [r6(e['cv_f1_mean']) if is_num(e.get('cv_f1_mean')) else None for e in exps]
    # 시험지(83건 한 번)와 교차검증(학습 249건을 나눠 여러 번)이 순위를 다르게 말하면 그대로 적는다(ml/make_notebook_03.py 결과표 아래 경고)
    full = [e for e in exps if is_num(e.get('coverage')) and e['coverage'] >= 0.999]   # 모든 문장을 판단하는 모델끼리만 순위를 말한다
    top_test = max(full, key=lambda e: e['f1'])
    top_cv = max((e for e in full if is_num(e.get('cv_f1_mean'))), key=lambda e: e['cv_f1_mean'], default=None)
    if top_cv is not None and top_cv is not top_test:
        note = ('모든 문장을 판단하는 모델 중 1위가 시험 %d건 F1로는 %s(%.3f), 교차검증 F1로는 %s(%.3f)로 서로 다르다. '
                '시험지가 작아 순위를 단정할 수 없다.' % (m['n_test'], top_test['exp'], top_test['f1'], top_cv['exp'], top_cv['cv_f1_mean']))
    else:
        note = '모든 문장을 판단하는 모델 중 1위는 시험 F1과 교차검증 F1 모두 %s다.' % top_test['exp']
    # 고른 기준(정밀도 1순위, 같으면 F1)은 ml/make_notebook_03.py 결과표 — 결과 파일 값으로 그 기준에 맞는지 확인한 뒤에만 적는다
    by_rule = max(full, key=lambda e: (round(e['precision'], 3), e['f1'])) if all(is_num(e.get('precision')) for e in full) else None
    if by_rule is chosen:
        note += ' 고른 모델(%s)은 F1이 아니라 "잘못 말하지 않기(정밀도) 우선" 기준으로 정했다(시연 화면에만 씀).' % chosen['exp']
    else:
        note += ' 고른 모델(%s)은 시연 화면에만 쓴다.' % chosen['exp']
    held = [e for e in exps if e['f1'] > chosen['f1'] and is_num(e.get('coverage')) and e['coverage'] < 1]
    if held:
        e = held[0]
        note += ' %s는 시험 F1이 더 높아 보이지만 판단을 %d%%만 하고 나머지는 보류해서 고르지 않았다.' % (e['exp'], round(e['coverage'] * 100))
    return chart('c23_age_classifier', 'ML', '업력 분류기 실험',
                 ML_PREFIX + '공고 문장이 업력 조건인지 가려내는 모델 %d가지의 F1(0~1) · 시험 F1은 시험 %d건으로 한 번, '
                 '교차검증 F1은 학습 %d건을 나눠 여러 번 잰 평균'
                 % (len(exps), m['n_test'], m['n_train']),
                 'bar', 'score', cats, [('시험 F1(%d건)' % m['n_test'], test), ('교차검증 F1(학습 %d건)' % m['n_train'], cv)],
                 note, 'ml/data/ml_experiments.json (f1 · cv_f1_mean)', 'record', '2026-09-16', top=1)


CHART_BUILDERS = (c01_cumulative_notices, c02_daily_new_notices, c03_notices_by_source, c04_batch_minutes,
                  c05_attachment_extraction, c06_apply_period_types, c07_judgment_coverage, c08_type_agreement,
                  c09_accuracy_before_after, c10_status_timing, c11_entity_block, c12_bonus_steps, c13_bonus_by_persona,
                  c14_g01_all, c15_latency, c16_embedding_cpu_gpu, c17_server_memory, c18_daily_ai_cost,
                  c19_server_monthly_cost, c20_test_count, c21_judge_agreement, c22_reranker, c23_age_classifier)
CHART_IDS = tuple(f.__name__ for f in CHART_BUILDERS)


def build_charts(ctx, builders=CHART_BUILDERS, say=print):
    """그래프를 하나씩 만든다. 하나가 실패하면 그것만 빼고 이유를 화면에 쓴다(예외 원문 대신 종류 — 주소가 섞일 수 있어서)."""
    out, seen = [], set()
    for fn in builders:
        cid = fn.__name__
        try:
            c = fn(ctx)
            if c['id'] != cid or cid in seen:
                raise ValueError('%s: id 가 함수 이름과 다르거나 겹침' % cid)
        except (NoData, ValueError) as exc:
            say('그래프 빠짐: %s — %s' % (cid, exc))
            continue
        except Exception as exc:
            say('그래프 빠짐: %s — %s' % (cid, type(exc).__name__))
            continue
        seen.add(cid)
        out.append(c)
    return out


# ── 조립·저장 ──────────────────────────────────────────────────────────
def scrub(text):
    """결과물에 주소·키 파일 이름이 섞이지 않게 마지막으로 걸러 낸다. (걸러 낸 수, 글)"""
    found = ADDRESS.findall(text)
    return len(found), ADDRESS.sub('[주소 생략]', text)


def build(args, logs=None, acc=None, records=None):
    from shared import store_mysql
    from eval import metrics_logs
    today = datetime.now(KST).date()
    book = Book(today)
    records = records or load_records()
    if logs is None:
        cfg = metrics_logs.settings(args.batch_host, args.batch_key, args.batch_dir, args.batch_name)
        logs = metrics_logs.load(cfg)
    if logs.get('errors'):
        book.missing.append({'name': '배치 서버 기록 새로 읽기', 'reason': '; '.join(logs['errors']) + ' — 이 PC 복사본으로 셈',
                             'expected': False})
    chart_data = {}
    connection = store_mysql.connect()
    try:
        with connection.cursor() as cur:
            guarded(book, [('1', '누적 공고 수', 'count', 'live'), ('1', '지금 모집 중인 공고 수', 'count', 'live'),
                           ('1', '하루 평균 신규 공고', 'count', 'live'), ('1', '배치 성공률(전체 기간)', 'ratio', 'live'),
                           ('1', '배치 성공률(서버 이전 뒤)', 'ratio', 'live'), ('1', '배치 가동일 비율(전체 기간)', 'ratio', 'live'),
                           ('1', '배치 가동일 비율(서버 이전 뒤)', 'ratio', 'live'), ('1', '배치 소요 시간(서버 이전 뒤, 중앙값)', 'min', 'live'),
                           ('1', 'K-Startup 목록 완전 수집률', 'ratio', 'live')], area_collection, cur, connection, logs)
            guarded(book, [('2', n, 'ratio', 'live') for n in ('정규화 거부율(최근 저장)', '접수기간 해석률', '마감일 확보율',
                                                              '첨부 공고문 본문 추출 성공률', '임베딩 적용률')], area_preprocessing, cur)
            guarded(book, [('3', '신청자 유형 판정 지문 신선도', 'ratio', 'live')], area_ai, cur, connection)
            guarded(book, [('6', '열린 공고 중 가점 언급 공고', 'count', 'live'), ('6', 'K-Startup 모집 중 공고(가산점 늘 비어 있음)', 'count', 'live')],
                    area_bonus, cur, connection)
            chart_data = chart_db(cur, connection, today)
    finally:
        connection.close()
    if acc is None:
        try:
            acc = load_accuracy()
        except Exception:
            acc = ({}, None, None)
    guarded(book, [('4', name, unit, 'live') for _, name, unit, _ in ACC], area_accuracy, acc)
    guarded(book, [('5', '추천 필터 ↔ 자격 판정 결론 다름', 'count', 'record'),
                   ('5', '개인사업자 "강한 불가" 공고가 상위 20에 뜬 질의', 'count', 'record'),
                   ('5', '법인 "강한 불가" 공고가 상위 20에 뜬 질의', 'count', 'record')], area_blocking)
    guarded(book, [('7', '제공 HTTP 창구 수', 'count', 'live'), ('7', '연결 계약 시험 통과', 'count', 'record'),
                   ('7', '자격 판정 응답 형식 오류', 'count', 'record'), ('7', '공고 상세 응답 형식 오류', 'count', 'record')],
            area_link, records)
    if args.latency:
        area_latency(book, args.server_url, args.server_name)
    else:
        for name in ('추천 응답 시간(이 PC, 중앙값)', '추천 응답 시간(실제 서버, 중앙값)'):
            book.miss('8', name, 'ms', '이번 실행에서 재지 않음(요청 안 함) — --latency 또는 --all', expected=True)
    guarded(book, [('8', '공고 서버 켜는 시간(시험용 새 서버)', 'sec', 'record'), ('8', '공고 서버 메모리(시험용 새 서버)', 'mb', 'record'),
                   ('8', '배치 중 서버 최대 메모리(시험용 새 서버)', 'mb', 'record'), ('8', '임베딩 공고 1건(CPU→GPU)', 'ms', 'record'),
                   ('8', '임베딩 검색어 1건(CPU→GPU)', 'ms', 'record'), ('8', '임베딩 전체 다시 만들기(CPU→GPU)', 'min', 'record')],
            area_server_records, records)
    guarded(book, [('9', '하루 AI 비용', 'usd', 'live'), ('9', '서버 요금 참고: 지금 서버(t3.medium, 시간당)', 'usd', 'record'),
                   ('9', '서버 요금 참고: GPU 서버(g4dn.xlarge, 시간당)', 'usd', 'record')], area_cost, logs, records)
    guarded(book, [('10', 'AI 교차 검수 결과 문서 수', 'count', 'live'), ('10', '결정 기록 수', 'count', 'live')]
            + ([('10', '자동 테스트 수', 'count', 'live')] if args.tests else []), area_dev, args.tests)
    if not args.tests:
        book.miss('10', '자동 테스트 수', 'count', '이번 실행에서 돌리지 않음(요청 안 함) — --tests 또는 --all', expected=True)
    guarded(book, [('11', '판정자 일치율: LLM(gpt-4.1-mini) vs 사람', 'ratio', 'record'), ('11', '평가 질의 수', 'count', 'live')],
            area_weak, acc)
    guarded(book, [('ML', 'ML 리랭커: 상위 3건 적합(학습 전 → 학습 후)', 'ratio', 'record'),
                   ('ML', 'ML 리랭커: nDCG@3(학습 전 → 학습 후)', 'score', 'record'),
                   ('ML', '리랭커 질의당 시간(GPU)', 'ms', 'record'), ('ML', '리랭커 GPU 최대 사용량', 'mb', 'record'),
                   ('ML', 'ML 업력 분류기 F1(시험)', 'score', 'record')], area_ml, records)
    order = list(AREAS)
    book.metrics.sort(key=lambda m: order.index(m['area']))      # 같은 영역 안에서는 넣은 순서
    charts = build_charts({'today': today, 'metrics': {m['name']: m for m in book.metrics}, 'raw': book.raw,
                           'db': chart_data, 'logs': logs, 'acc': acc, 'records': records,
                           'judge': (next((m for m in book.metrics if m['name'] == '판정자 일치율: LLM(gpt-4.1-mini) vs 사람'), {})
                                     .get('value'))})
    return {'run_at': datetime.now(KST).isoformat(timespec='seconds'),
            'conditions': ['공용 DB 조회만(쓰기 없음)', 'OpenAI 호출 0', '서버는 읽기만(배치 기록 복사, 추천 요청)',
                           '배치 기록: %s' % (', '.join(logs.get('sources') or []) or '없음'),
                           '판정 기반 수치는 사람·AI 판정을 함께 쓴다(AI 참고 정답 표시)'],
            'metrics': book.metrics, 'headline': headline(book), 'missing': book.missing, 'charts': charts}


def fmt(m):
    v, u = m['value'], m['unit']
    if v is None:
        return '측정 못 함'
    if u == 'ratio':
        return '%.1f%%' % (v * 100)
    if u == 'score':
        return '%.3f' % v
    if u == 'count':
        s = format(int(v), ',') if float(v).is_integer() else '%.2f' % v
        return s + ('/' + m['target'] if str(m.get('target', '')).isdigit() and m['name'] == '연결 계약 시험 통과' else '')
    if u == 'usd':
        return '$%.3f' % v
    if u in ('ms', 'sec', 'min', 'mb'):
        return ('%s' % format(v, ',') if isinstance(v, int) else '%.1f' % v) + {'ms': 'ms', 'sec': '초', 'min': '분', 'mb': 'MB'}[u]
    return str(v)


def summary_md(data):
    lines = ['# 공고 파트 작업 지표 (%s)' % data['run_at'], '']
    lines += ['- ' + c for c in data['conditions']] + ['']
    lines += ['## 한눈에 보기', '']
    by = {m['name']: m for m in data['metrics']}
    for c in data['headline']:
        lines.append('- **%s**: %s%s' % (c['title'], ' · '.join('%s %s' % (v['label'], fmt(by[v['metric']])) for v in c['values']),
                                       (' — ' + c['note']) if c['note'] else ''))
    lines.append('')
    for area, title in AREAS.items():
        part = [m for m in data['metrics'] if m['area'] == area]
        if not part:
            continue
        lines += ['## %s %s' % (area, title), '', '| 지표 | 값 | 기준·목표 | 내용 | 근거 | 측정 |', '|---|---:|---|---|---|---|']
        lines += ['| %s | %s | %s | %s | %s | %s %s |' % (m['name'], fmt(m), m['target'], m['detail'].replace('|', '/'), m['source'].replace('|', '/'),
                                                          '이번에 잼' if m['kind'] == 'live' else '기록', m['measured_at'] or '') for m in part]
        lines.append('')
    charts = data.get('charts') or []
    if charts:
        lines += ['## 그래프 %d개' % len(charts), ''] + ['- %s %s: %s' % (c['id'], c['title'], c['note']) for c in charts] + ['']
    if data['missing']:
        lines += ['## 이번에 재지 못한 것', ''] + ['- %s: %s%s' % (x['name'], x['reason'], '' if x['expected'] else ' (이번 실행 실패)')
                                                  for x in data['missing']] + ['']
    return '\n'.join(lines)


def write(data, out_dir):
    os.makedirs(out_dir, exist_ok=False)
    text = json.dumps(data, ensure_ascii=False, indent=1)
    n, text = scrub(text)
    if n:
        print('경고: 결과에 주소처럼 보이는 글자 %d곳을 지웠다' % n)
        data = json.loads(text)
    with open(os.path.join(out_dir, 'metrics.json'), 'w', encoding='utf-8') as f:
        f.write(text)
    md = scrub(summary_md(data))[1]
    with open(os.path.join(out_dir, 'summary.md'), 'w', encoding='utf-8') as f:
        f.write(md)
    return data


def run_accuracy():
    r = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'eval.filter_first_now'], cwd=ROOT,
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return r.returncode


def parse(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--all', action='store_true', help='--accuracy --latency --tests 를 모두')
    ap.add_argument('--accuracy', action='store_true', help='추천 정확도를 지금 서비스로 다시 잰다(eval.filter_first_now)')
    ap.add_argument('--latency', action='store_true', help='응답 시간 두 가지(이 PC · 실제 서버)')
    ap.add_argument('--tests', action='store_true', help='전체 자동 시험을 돌려 센다')
    ap.add_argument('--no-render', action='store_true', help='HTML·Word 를 만들지 않는다')
    ap.add_argument('--server-url', default=os.environ.get('METRICS_SERVER_URL') or DEFAULT_SERVER_URL)
    ap.add_argument('--server-name', default=os.environ.get('METRICS_SERVER_NAME') or DEFAULT_SERVER_NAME)
    ap.add_argument('--batch-host')
    ap.add_argument('--batch-key')
    ap.add_argument('--batch-dir')
    ap.add_argument('--batch-name')
    ap.add_argument('--out')
    args = ap.parse_args(argv)
    if args.all:
        args.accuracy = args.latency = args.tests = True
    return args


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    args = parse(argv)
    out_dir = args.out or os.path.join(REPORTS, 'metrics_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    acc_fail = None
    if args.accuracy:
        print('추천 정확도 다시 재는 중(공용 DB 읽기만, 몇 분 걸림)…')
        code = run_accuracy()
        if code != 0:
            acc_fail = '정확도 다시 재기 실패(종료 코드 %d)' % code
    data = build(args)
    if acc_fail:
        data['missing'].append({'name': '추천 정확도 다시 재기', 'reason': acc_fail, 'expected': False})
    data = write(data, out_dir)
    print(summary_md(data))
    if not args.no_render:
        try:
            from eval import metrics_doc
            html_path, docx_path = metrics_doc.render(out_dir)
            print('HTML:', os.path.relpath(html_path, ROOT))
            print('Word:', os.path.relpath(docx_path, ROOT))
        except Exception as exc:
            data['missing'].append({'name': 'HTML·Word 만들기', 'reason': type(exc).__name__, 'expected': False})
            print('HTML·Word 를 만들지 못함:', type(exc).__name__, exc)
    print('결과:', os.path.relpath(out_dir, ROOT))
    failed = [x for x in data['missing'] if not x['expected']]
    if data['missing']:
        print('재지 못한 것 %d개(이번 실행 실패 %d개):' % (len(data['missing']), len(failed)))
        for x in data['missing']:
            print('  - %s: %s' % (x['name'], x['reason']))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
