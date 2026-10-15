# -*- coding: utf-8 -*-
"""지금 서비스로 추천 정확도 다시 재기 — 9/28 과 같은 질의·같은 판정 정답·같은 기준일 상태로 (2026-10-14). OpenAI 호출 없음.

  python -X utf8 -m eval.filter_first_now          공용 DB 읽기만(SELECT). 결과는 reports/filter_first_now_<UTC 시각>/

비유: 9/28 에 본 시험(같은 문제 58개·같은 채점표 1,617쌍)을 지금 학생(지금 search/app.py)에게 다시 보게 한다.
시계는 기준일(2026-09-15)로 돌려 놓고, 공고에 붙은 "모집 중/마감" 팻말도 그날 것으로 바꿔 끼운다.
오늘 팻말을 그대로 두면 9/15 뒤에 닫힌 공고가 그날도 닫혀 있던 것처럼 보여 점수가 실제보다 나빠진다.

두 방식 (9/28 의 legacy 는 뺀다 — 9/22 커밋과 Chroma 가 있어야 돌아서 지금 PC 에서 못 돈다)
  vector_only   9/28 과 같은 스위치(meta.vector_only_settings: dense 검색, 정형 필터·마감 제외·규칙 모두 끔,
                신청자 유형 판정 끔). 9/28 에는 없던 가산점 순위 반영(10/8, 기본 0.2)도 꺼서 "유사도 순서 그대로"를 지킨다.
  filter_first  지금 search/app.py 그대로(정형 필터 → 통과 공고 안에서 hybrid 검색 → 규칙 재정렬 → 가산점 0.2,
                10/13 결정 0021 의 개인사업자·법인 '불가' strong 빼기 포함).

조건 (9/28 eval/filter_first_eval.py 와 같다)
  정상 질의 58개(eval/queries.jsonl kind=normal) · 정답 eval/qrels.jsonl 1,617쌍(다르면 9/28 판을 git 에서 읽는다)
  기준일 2026-09-15 고정(app·gate 의 오늘 날짜) · 2026-09-16 전에 수집된 공고만(CORPUS_BEFORE) · 상위 10 · hybrid 만.
  말뭉치 제한: 지금 서비스는 Chroma 가 아니라 공용 DB 벡터를 메모리에 올린다(search/memvec). 그 묶음을
  CorpusMemory 로 감싸 말뭉치 밖 공고를 두 방식 모두에서 안 보이게 한다(9/28 의 CorpusCollection 과 같은 방식).

기준일 모집 상태 (as_of_status — 메모리에서만 바꾼다. DB 행은 바꾸지 않는다)
  모집 상태(recruitment_status)는 날짜를 고정해도 오늘 DB 값이다. K-Startup 은 2026-09-30 부터 매일 배치가 "모집 중 목록에서
  빠진 공고"를 closed 로 바꾼다(shared/store_mysql.close_missing — 닫을 때 snapshot_at 을 그 목록 시각으로 덮는다. 첫 실행 10/1).
  9/28 실행 때는 이 기능이 없어 말뭉치의 K-Startup 공고가 모두 open 이었다. 그래서 지금 closed 인 말뭉치 공고를 이렇게 판정한다.
    ① 닫힌 기록(snapshot_at)이 기준일 당일이나 그 전 → 그날도 마감(그대로)
    ② 마감일(apply_end)이 기준일 전 → 접수 기간이 이미 끝났다(그대로 마감)
    ③ 마감일이 기준일 당일이나 그 뒤 → 그날은 아직 모집 중이었다고 보고 open 으로 되돌린다
    ④ 마감일이 없음 → 원본 표시가 모집 중(raw.rcrt_prgs_yn='Y', 즉 close_missing 이 닫음)이고 첫 일괄 닫기(기준일 뒤)보다
       뒤의 날에 닫혔으면 그 사이 모집 중 목록에 있었다는 뜻이라 open. 첫 일괄 닫기 때 닫혔으면 언제 목록에서 빠졌는지
       알 수 없어(snapshot_at 이 덮였다) 지금 상태 그대로 둔다.
  한계: 마감일 전에 일찍 모집을 끝낸 공고는 구분하지 못한다(그런 기록이 없다).
  같은 실행에서 오늘 상태 그대로 잰 값도 summary_today_status 에 남긴다(약점·설명용).

채점 (filter_first_eval.query_metrics 를 그대로 쓴다)
  신청 불가@10   지금 기준 app.eligible_with_types — 예비창업자 + 개인사업자·법인 '불가' strong(10/13). 두 방식 같은 기준.
                9/28 은 예비창업자만 본문 판정을 썼다. 비교용으로 그 기준으로 다시 센 값도 breakdown 에 남긴다.
  P@3(2) 하한·상한, nDCG@10(판정분), 쓸모@3·@10 하한·상한, 미판정@3·@10, 반환 건수.
  지금−벡터만 차이는 질의별 짝 차이의 부트스트랩 95% 구간(evaluate.paired_diff, 9/28 과 같은 씨앗).

결과 results.json 은 9/28 결과와 같은 모양(summary.hybrid.<지표>.{label, better, vector_only, legacy, filter_first,
diff, diff_vs_vector})이다. summary 가 기준일 상태로 맞춘 값(대표 수치), summary_today_status 가 오늘 상태 값이다.
이번에 없는 legacy·diff 는 null 이다. 9/28 결과와의 비교는 reference_0928(·_today_status)에 따로 둔다.
"""
import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import date as real_date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import common  # noqa: E402
import evaluate  # noqa: E402
import filter_first_eval as ffe  # noqa: E402

KIND = '지금 서비스 다시 재기'
INELIGIBILITY_CRITERION = '10/13 기준: 예비창업자 + 개인사업자·법인 강한 불가 포함'
INELIGIBILITY_CRITERION_0928 = '9/28 기준: 예비창업자만 공고 본문 판정(개인사업자·법인은 API 업력 칸·마감만)'
K = ffe.K
CORPUS_BEFORE = ffe.CORPUS_BEFORE
MODES = ('hybrid',)
SYSTEMS = ('vector_only', 'filter_first')
# 9/28 vector_only 스위치 그대로(reports/filter_first_eval_20260928T104212Z meta.vector_only_settings)
VECTOR_ONLY_SWITCHES = dict(ffe.VECTOR_ONLY)
# 9/28 에는 가산점 순위 반영이 없었다(10/8 결정 0017 부터 기본 0.2). 0 이면 가산점 전과 순서가 같다(app.Weights)
VECTOR_ONLY_WEIGHTS = {'bonus': 0.0}
QRELS_PAIRS_0928 = 1617
QRELS_COMMIT_0928 = '35358be'      # qrels.jsonl 을 마지막으로 바꾼 커밋(2026-09-22) — 9/28 평가가 쓴 판
REFERENCE_RUN = 'filter_first_eval_20260928T104212Z'
ENTITY_REASONS = ('개인사업자 불가(공고 본문)', '법인 불가(공고 본문)')
CLOSED = '모집 마감'

STATUS_RULE = ("지금 '마감'(closed)인 말뭉치 공고만 본다. ① 닫힌 기록(snapshot_at)이 기준일 당일 이전 → 그대로 마감. "
               "② 마감일(apply_end)이 기준일 전 → 그대로 마감(접수 기간이 이미 끝남). "
               "③ 마감일이 기준일 당일·이후 → 기준일에는 모집 중이었다고 보고 '열림'. "
               "④ 마감일 없음 → 원본 표시가 모집 중(raw.rcrt_prgs_yn='Y')이고 첫 일괄 닫기(close_missing 첫 실행, 기준일 뒤)보다 "
               "뒤의 날에 닫혔으면 '열림', 아니면 닫힌 날을 알 수 없어 지금 상태 그대로. DB 는 바꾸지 않고 메모리에서만 바꾼다.")
STATUS_CAVEAT = '마감일 전에 일찍 모집을 끝낸 공고는 구분하지 못한다(기록이 없다). 지금 열림·모름인 공고는 그대로 둔다.'
REOPEN = ('reopened_deadline_after_as_of', 'reopened_listed_after_first_sweep')
DECISIONS = REOPEN + ('kept_closed_recorded_by_as_of', 'kept_closed_deadline_passed', 'kept_closed_undatable')


# ── 실행 준비 (순수 — tests/test_filter_first_now.py) ─────────────────────────
class CorpusMemory(ffe.CorpusCollection):
    """공용 DB 벡터 묶음(search/memvec.MemoryCollection)을 감싸 말뭉치 밖 공고를 보이지 않게 한다.

    query 는 9/28 CorpusCollection 그대로(ids 를 말뭉치 안으로 줄여 memvec 에 넘긴다 → 서비스의 'memory' 경로).
    get 은 ids 가 없을 때도 말뭉치 안만 돌려준다(9/28 판은 감싼 묶음 전체를 돌려줬다 — match() 는 ids 를 늘 주므로 결과는 같다).
    """

    def get(self, ids=None, include=None):
        ids = self.corpus if ids is None else [n for n in ids if n in self.members]
        return self.col.get(ids=ids, include=include or [])


def restrict_corpus(state, corpus):
    """app.STATE 를 말뭉치(CORPUS_BEFORE 전 수집 + 벡터 있음)로 줄인다. 9/28 filter_first_eval.main 과 같은 네 줄.

    corpus: {공고 ID: notices 행(embed.FIELDS 포함)}. 돌려주는 값은 말뭉치 공고 ID 집합."""
    from search import hybrid
    from shared import embed
    if state.get('collection') is None or state.get('vector_ids') is None:
        raise SystemExit('공고 벡터를 올리지 못했다 — 의미 검색 없이 재면 9/28 과 비교할 수 없어 멈춘다 (%s)'
                         % sorted((state.get('boot_errors') or {})))
    ids = set(corpus) & set(state['vector_ids'])
    state['rows'] = {n: r for n, r in state['rows'].items() if n in ids}
    state['collection'] = CorpusMemory(state['collection'], ids)
    state['vector_ids'] = ids
    state['bm25'] = hybrid.BM25([(n, embed.build_input(corpus[n])) for n in sorted(ids)
                                 if embed.build_input(corpus[n])])
    return ids


def request_for(system, payload):
    """질의 payload → app.MatchRequest 인자. vector_only 는 9/28 스위치 + 가산점 끔, filter_first 는 서비스 기본값 + hybrid."""
    if system == 'vector_only':
        return dict(payload, top=K, weights=dict(VECTOR_ONLY_WEIGHTS), **VECTOR_ONLY_SWITCHES)
    if system == 'filter_first':
        return dict(payload, top=K, search='hybrid')
    raise ValueError(system)


def pair_count(rows):
    return len({(r['qid'], r['notice_id']) for r in rows})


def choose_qrels(current_rows, load_0928, expected=QRELS_PAIRS_0928):
    """지금 qrels 가 9/28 과 같은 쌍 수면 그대로, 아니면 9/28 판(load_0928())을 쓴다. (행, 출처 설명)."""
    if pair_count(current_rows) == expected:
        return current_rows, 'eval/qrels.jsonl (지금 파일 — 9/28 과 같은 %d쌍)' % expected
    rows = load_0928()
    if pair_count(rows) != expected:
        raise SystemExit('9/28 판 qrels 도 %d쌍이 아니다(%d쌍) — 멈춘다' % (expected, pair_count(rows)))
    return rows, 'git %s:data-collection/eval/qrels.jsonl (지금 파일이 %d쌍이라 9/28 판을 썼다)' % (
        QRELS_COMMIT_0928, pair_count(current_rows))


def qrels_from_rows(rows):
    qrels = {}
    for r in rows:
        qrels.setdefault(r['qid'], {})[r['notice_id']] = r['topic_rel']
    return qrels


def _qrels_0928():
    """9/28 판 qrels — git 에서 읽기만 한다(작업 트리는 건드리지 않는다)."""
    text = subprocess.run(['git', 'show', '%s:data-collection/eval/qrels.jsonl' % QRELS_COMMIT_0928],
                          cwd=ROOT, capture_output=True, check=True).stdout.decode('utf-8')
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def eligibility_checks(eligible_fn, rows, ranked, age, as_of, types_table, applicant_type, entity_blocks=True):
    """{공고: (남길지, 이유)} — filter_first_eval.main 의 채점과 같다(지금 기준).

    entity_blocks=False 는 9/28 기준(예비창업자만 본문 판정) 재현 — 개인사업자·법인 신청자에게 판정표를 넘기지 않는다."""
    from search import applicant_types as types_mod
    types_table = types_table or {}
    pre = applicant_type == types_mod.PRE_FOUNDER
    entity = bool(types_mod.entity_key(applicant_type))
    use = bool(types_table.get('active')) and (pre or (entity_blocks and entity))
    return {n: tuple(eligible_fn(n, rows[n], age, as_of, True, types_table if use else None, applicant_type)[:2])
            for n in ranked}


# ── 기준일 모집 상태 (순수) ───────────────────────────────────────────────────
def _day(value):
    """date·datetime·'YYYY-MM-DD…' → date. 못 읽으면 None(예외 없음)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, real_date):
        return value
    try:
        return real_date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def status_decision(evidence, as_of, first_sweep=None):
    """지금 closed 인 공고 한 건의 기준일 상태 판정 — DECISIONS 중 하나. closed 가 아니면 None(그대로 둔다).

    evidence: {'status', 'apply_end', 'snapshot_at', 'listed_open'(원본 표시가 모집 중 = close_missing 이 닫음)}.
    first_sweep: close_missing 이 처음 공고를 닫은 날(그날 닫힌 공고는 언제 목록에서 빠졌는지 알 수 없다)."""
    if evidence.get('status') != 'closed':
        return None
    snap, end, sweep = _day(evidence.get('snapshot_at')), _day(evidence.get('apply_end')), _day(first_sweep)
    if snap is not None and snap <= as_of:
        return 'kept_closed_recorded_by_as_of'
    if end is not None:
        return 'kept_closed_deadline_passed' if end < as_of else 'reopened_deadline_after_as_of'
    if evidence.get('listed_open') and sweep is not None and sweep > as_of and snap is not None and snap > sweep:
        return 'reopened_listed_after_first_sweep'
    return 'kept_closed_undatable'


def as_of_status(evidence, as_of, first_sweep=None):
    """{공고: 판정} (지금 closed 인 공고만) — 결과의 REOPEN 판정 공고를 기준일에 열려 있던 것으로 본다."""
    out = {}
    for nid, ev in evidence.items():
        d = status_decision(ev, as_of, first_sweep)
        if d is not None:
            out[nid] = d
    return out


def reopen(rows, ids):
    """rows(메모리의 STATE['rows'])에서 ids 의 closed 를 open 으로 바꾼다. DB 는 건드리지 않는다. 바꾼 공고 집합."""
    changed = set()
    for n in ids:
        row = rows.get(n)
        if row is not None and row.get('recruitment_status') == 'closed':
            row['recruitment_status'] = 'open'
            changed.add(n)
    return changed


def status_meta(decisions, evidence, as_of, first_sweep, reopened):
    closed = [n for n in decisions]
    return {'date': as_of.isoformat(), 'rule': STATUS_RULE, 'caveat': STATUS_CAVEAT,
            'reopened': len(reopened),
            'decisions': {d: sum(1 for v in decisions.values() if v == d) for d in DECISIONS},
            'closed_now_in_corpus': len(closed),
            'closed_by_close_missing': sum(1 for n in closed if evidence[n].get('listed_open')),
            'source_said_closed': sum(1 for n in closed if evidence[n].get('listed_open') is False),
            'first_close_sweep': _day(first_sweep).isoformat() if _day(first_sweep) else None,
            'evidence': 'notices.recruitment_status·apply_end·snapshot_at·raw.rcrt_prgs_yn (SELECT 만)',
            'db_rows_changed': 0}


def status_evidence(corpus_ids):
    """기준일 상태 판정 근거 — 공용 DB SELECT 만. ({공고: 근거}, 첫 일괄 닫기 시각)."""
    from shared import store_mysql
    flag = "JSON_UNQUOTE(JSON_EXTRACT(raw, '$.rcrt_prgs_yn'))"
    con = store_mysql.connect()
    try:
        with con.cursor() as cur:
            cur.execute('SELECT notice_id, recruitment_status, apply_end, snapshot_at, ' + flag
                        + ' FROM notices WHERE created_at < %s', (CORPUS_BEFORE,))
            rows = cur.fetchall()
            # close_missing 만 원본 표시가 모집 중(Y)인 공고를 closed 로 만든다(upsert 는 원본 표시대로 쓴다)
            cur.execute("SELECT MIN(snapshot_at) FROM notices WHERE recruitment_status='closed' AND " + flag + "='Y'")
            first_sweep = cur.fetchone()[0]
    finally:
        con.close()
    evidence = {nid: {'status': st, 'apply_end': end, 'snapshot_at': snap,
                      'listed_open': {'Y': True, 'N': False}.get(yn)}
                for nid, st, end, snap, yn in rows if nid in corpus_ids}
    return evidence, first_sweep


# ── 요약 (순수) ───────────────────────────────────────────────────────────────
def build_summary(per, modes=MODES):
    """per {mode: {system: [질의별 지표]}} → 9/28 결과와 같은 모양의 summary. legacy·diff 는 null."""
    summary = {}
    for mode in modes:
        summary[mode] = {}
        for key, label, better in ffe.METRICS:
            v = [m[key] for m in per[mode]['vector_only']]
            b = [m[key] for m in per[mode]['filter_first']]
            d = evaluate.paired_diff(v, b)
            summary[mode][key] = {'label': label, 'better': better, 'vector_only': ffe.mean(v), 'legacy': None,
                                  'filter_first': ffe.mean(b), 'diff': None,
                                  'diff_vs_vector': list(d) if d else None}
    return summary


def build_meta(started, corpus_ids, as_of, queries, qrels, qrels_source, qrels_sha256, state, fallbacks=0,
               status_as_of=None):
    from search import app, hybrid
    vec = state.get('vectors_info') or {}
    types_table = state.get('applicant_types') or {}
    weights = app.Weights().model_dump()
    return {
        'run_at': started.isoformat(timespec='seconds'), 'kind': KIND, 'legacy_commit': None,
        'corpus_before': CORPUS_BEFORE, 'corpus_notices': len(corpus_ids), 'as_of': as_of.isoformat(),
        'queries': len(queries), 'k': K, 'modes': list(MODES),
        'qrels_pairs': sum(len(v) for v in qrels.values()), 'qrels_source': qrels_source, 'qrels_sha256': qrels_sha256,
        'judges': 'all (human·llm·llm_old)', 'label_note': 'LLM 판정(llm·llm_old)은 AI 참고 정답이다',
        'openai_calls': 0, 'db_writes': 0, 'systems': list(SYSTEMS),
        'ineligibility_criterion': INELIGIBILITY_CRITERION,
        'ineligibility_criterion_0928': INELIGIBILITY_CRITERION_0928,
        'summary_status': '기준일 모집 상태(status_as_of 규칙). 오늘 상태 그대로 잰 값은 summary_today_status',
        'status_as_of': status_as_of,
        'vector_only_settings': dict(VECTOR_ONLY_SWITCHES),
        'vector_only_weights': dict(VECTOR_ONLY_WEIGHTS),
        'filter_first_settings': {'search': 'hybrid', 'request': 'app.MatchRequest 기본값(정형 필터·마감 제외·'
                                  '신청자 유형 판정 켬, 지역·시군구·집단 규칙 켬, 업종 규칙 꺼짐)', 'weights': weights},
        'rrf': {'k': weights['rrf_k'], 'dense': weights['dense'], 'bm25': weights['bm25'], 'depth': hybrid.DEPTH},
        'reranker': None,
        'vectors': {'source': '공용 DB notices.embedding → search/memvec(정확 계산)',
                    'count': vec.get('count'), 'dropped': vec.get('dropped'),
                    'fingerprints': vec.get('fingerprints')},
        'reference_vectors_0928': 'Chroma(근사 검색) — 같은 BGE-M3 벡터라도 순서가 조금 다를 수 있다',
        'applicant_types': {'active': bool(types_table.get('active')), 'source': types_table.get('source'),
                            'notices': len(types_table.get('notices') or {})},
        'bonus_reviewed': len(state.get('bonus_reviewed') or {}),
        'boot_warnings': sorted(state.get('boot_errors') or {}),
        'fallback_lists': fallbacks,
        'reference_run': REFERENCE_RUN,
    }


def ineligible_breakdown(lists, rows, as_of, system):
    """한 방식의 신청 불가 칸을 이유별로 센다. 9/28 기준(예비창업자만)으로 다시 센 값도 함께."""
    items = [l for l in lists if l['system'] == system]
    by_reason, only = Counter(), Counter()
    closed_open_on_as_of = 0
    for l in items:
        for n in l['ineligible']:
            why = list(l['why'].get(n) or [])
            by_reason.update(why)
            if len(why) == 1:
                only[why[0]] += 1
            if why == [CLOSED]:
                end = str((rows.get(n) or {}).get('apply_end') or '')[:10]
                if not end or end >= as_of.isoformat():
                    closed_open_on_as_of += 1
    old = [len(l.get('ineligible_0928_criterion') or []) / len(l['ranked']) if l['ranked'] else None for l in items]
    return {'lists': len(items), 'slots': sum(len(l['ranked']) for l in items),
            'ineligible_slots': sum(len(l['ineligible']) for l in items),
            'by_reason': dict(by_reason.most_common()), 'only_reason': dict(only.most_common()),
            'entity_block_slots': sum(1 for l in items for n in l['ineligible']
                                      if set(l['why'].get(n) or []) & set(ENTITY_REASONS)),
            'closed_status_but_open_on_as_of': closed_open_on_as_of,
            'ineligible_slots_0928_criterion': sum(len(l.get('ineligible_0928_criterion') or []) for l in items),
            'ineligible_k_0928_criterion': ffe.mean(old)}


def list_overlap(ref_lists, lists, system, mode='hybrid'):
    """9/28 결과와 지금 결과의 같은 질의·같은 방식 목록 비교. 신청 불가 칸이 어디서 바뀌었는지 센다."""
    old = {l['qid']: l for l in ref_lists if l['mode'] == mode and l['system'] == system}
    new = {l['qid']: l for l in lists if l['mode'] == mode and l['system'] == system}
    same_order = same_set = same_top3 = 0
    overlap_k, overlap_3 = [], []
    slots = Counter()
    now_only_reasons = Counter()
    for qid, nl in new.items():
        ol = old.get(qid)
        if not ol:
            continue
        same_order += ol['ranked'] == nl['ranked']
        same_set += set(ol['ranked']) == set(nl['ranked'])
        same_top3 += ol['ranked'][:3] == nl['ranked'][:3]
        shared = set(ol['ranked']) & set(nl['ranked'])
        overlap_k.append(len(shared) / max(len(nl['ranked']), 1))
        overlap_3.append(len(set(ol['ranked'][:3]) & set(nl['ranked'][:3])) / 3)
        oi, ni = set(ol['ineligible']), set(nl['ineligible'])
        for n in shared:
            if n in oi and n in ni:
                slots['both'] += 1
            elif n in ni:
                slots['now_only'] += 1
                now_only_reasons.update(nl['why'].get(n) or [])
            elif n in oi:
                slots['then_only'] += 1
        slots['now_in_new_notices'] += len((set(nl['ranked']) - shared) & ni)
        slots['then_in_dropped_notices'] += len((set(ol['ranked']) - shared) & oi)
    return {'queries': len([q for q in new if q in old]), 'same_order': same_order, 'same_set_k': same_set,
            'same_top3_order': same_top3, 'overlap_k': ffe.mean(overlap_k), 'overlap_3': ffe.mean(overlap_3),
            'ineligible_slots': dict(slots), 'now_only_reasons': dict(now_only_reasons.most_common())}


def compare_reference(ref, summary, lists, mode='hybrid'):
    """9/28 결과(reports/REFERENCE_RUN)와 지표·목록 비교. 9/28 결과가 없으면 None."""
    if not ref:
        return None
    rs = (ref.get('summary') or {}).get(mode) or {}
    metrics = {}
    for key, s in summary[mode].items():
        old = rs.get(key) or {}
        metrics[key] = {'label': s['label'],
                        'vector_only_0928': old.get('vector_only'), 'vector_only_now': s['vector_only'],
                        'filter_first_0928': old.get('filter_first'), 'filter_first_now': s['filter_first']}
        for system in SYSTEMS:
            a, b = metrics[key][system + '_0928'], metrics[key][system + '_now']
            metrics[key][system + '_change'] = (b - a) if a is not None and b is not None else None
    return {'run': REFERENCE_RUN, 'ref_meta': {k: (ref.get('meta') or {}).get(k) for k in
                                               ('run_at', 'corpus_notices', 'qrels_pairs', 'queries', 'as_of')},
            'metrics': metrics,
            'lists': {system: list_overlap(ref.get('lists') or [], lists, system, mode) for system in SYSTEMS}}


def direction(old, new, eps=1e-9):
    if old is None or new is None:
        return '비교할 수 없다'
    if new > old + eps:
        return '올랐다'
    if new < old - eps:
        return '내렸다'
    return '같다'


# ── 출력 ─────────────────────────────────────────────────────────────────────
def fmt(v, key):
    return ffe.fmt(v, key)


def span(d):
    if not d:
        return '-'
    text = '%+.3f [%+.3f, %+.3f]' % tuple(d)
    return text + (' (0 포함 — 차이를 말할 수 없다)' if d[1] <= 0 <= d[2] else '')


def _pp(old, new):
    return 100 * ((new or 0) - (old or 0))


def render_readme(meta, summary, summary_today, breakdown, breakdown_today, reference, reference_today=None):
    s = summary['hybrid']
    st = meta.get('status_as_of') or {}
    lines = ['# 지금 서비스로 추천 정확도 다시 재기 (%s)' % meta['run_at'][:10], '',
             '9/28 에 본 시험(같은 질의 %d개·같은 판정 정답 %d쌍)을 **지금 서비스**에게 다시 보게 했다. '
             '문제와 채점표는 그대로 두고, 학생(지금 `search/app.py`)과 "신청 불가" 채점 기준만 지금 것이다.'
             % (meta['queries'], meta['qrels_pairs']), '',
             '**시계 비유.** 시험 날짜를 9/15 로 돌려 놓았으면 공고에 붙은 "모집 중/마감" 팻말도 9/15 것이어야 한다. '
             '오늘(10/14) 팻말을 그대로 두면 9/15 뒤에 닫힌 공고까지 그날 닫혀 있던 것처럼 보여, 점수가 실제보다 나빠진다. '
             '그래서 **대표 수치(아래 "결과")는 팻말을 9/15 것으로 바꿔 끼운 값**이고(공고 %d건을 메모리에서만 "모집 중"으로 되돌림, DB 는 그대로), '
             '오늘 팻말 그대로 잰 값은 이 약점을 보여 주는 참고값으로 따로 둔다.' % st.get('reopened', 0), '',
             '## 조건', '',
             '| 항목 | 값 |', '|---|---|',
             '| 질의 | `eval/queries.jsonl` 정상 질의 %d개 |' % meta['queries'],
             '| 정답 | %s · 판정 출처 사람·LLM 모두(LLM 판정은 AI 참고 정답) |' % meta['qrels_source'],
             '| 기준일 | %s (app·gate 의 오늘 날짜 고정) |' % meta['as_of'],
             '| 모집 상태 | 기준일 상태로 맞춤 — 지금 마감인 말뭉치 공고 %s건 중 %s건을 "모집 중"으로 되돌림(규칙은 아래 "기준일 모집 상태") |'
             % (st.get('closed_now_in_corpus', '-'), st.get('reopened', '-')),
             '| 말뭉치 | %s 전에 수집되고 공용 DB 벡터가 있는 공고 %d건 (9/28: %s건) |'
             % (meta['corpus_before'], meta['corpus_notices'],
                (reference or {}).get('ref_meta', {}).get('corpus_notices', '-')),
             '| 벡터 | %s · 전체 %s건 중 말뭉치만 씀 (9/28 은 Chroma 근사 검색) |'
             % (meta['vectors']['source'], meta['vectors']['count']),
             '| 상위 K · 검색 방식 | %d · hybrid (벡터만은 dense) |' % meta['k'],
             '| RRF | k=%(k)s · 의미 %(dense)s · 단어 %(bm25)s · 각 검색 후보 %(depth)s |' % meta['rrf'],
             '| 리랭커 | 안 씀 |',
             '| 벡터만 | 9/28 스위치 그대로(정형 필터·마감 제외·지역·시군구·집단·업종 규칙·신청자 유형 판정 모두 끔) + 가산점 순위 반영 끔(9/28 에는 없던 기능) |',
             '| 지금(필터 먼저) | 서비스 기본값 그대로 — 정형 필터(마감·업력·신청자 유형, 10/13 개인사업자·법인 강한 불가 포함) → hybrid → 규칙 재정렬 → 가산점 세기 %.1f(원문 대조 목록 %d건) |'
             % (meta['filter_first_settings']['weights']['bonus'], meta['bonus_reviewed']),
             '| 신청 불가 채점 기준 | %s — 두 방식 같은 기준 |' % meta['ineligibility_criterion'],
             '| 비용 | OpenAI 호출 %d · DB 쓰기 %d (SELECT 만) |' % (meta['openai_calls'], meta['db_writes']),
             '', '## 결과 — 기준일(9/15) 모집 상태 (hybrid, 정상 질의 %d개)' % meta['queries'], '',
             '| 지표 | 벡터만 | 지금(필터 먼저) | 지금−벡터만 [95% 구간] | 좋은 쪽 |', '|---|---:|---:|---|---|']
    for key, row in s.items():
        lines.append('| %s | %s | %s | %s | %s |' % (
            row['label'], fmt(row['vector_only'], key), fmt(row['filter_first'], key), span(row['diff_vs_vector']),
            {'lower': '낮을수록', 'higher': '높을수록', 'info': '참고'}[row['better']]))
    lines += ['', '- 쓸모@3·@10 은 "내용이 맞고(topic_rel=2) + 신청 가능" 공고 수. 하한은 미판정을 아님으로, 상한은 맞음으로 센 값.',
              '- 95% 구간은 질의별 짝 차이의 부트스트랩(2,000회, 9/28 과 같은 씨앗). 구간이 0 을 포함하면 차이를 말할 수 없다.']

    t = summary_today['hybrid']
    lines += ['', '## 참고 — 오늘(%s) 모집 상태 그대로 잰 값 (약점·설명용)' % meta['run_at'][:10], '',
              '| 지표 | 벡터만(기준일 상태) | 벡터만(오늘 상태) | 필터 먼저(기준일 상태) | 필터 먼저(오늘 상태) |',
              '|---|---:|---:|---:|---:|']
    for key in ('ineligible_k', 'p3_lo', 'p3_hi', 'ndcg_k', 'useful3_lo', 'unjudgedk'):
        lines.append('| %s | %s | %s | %s | %s |' % (s[key]['label'], fmt(s[key]['vector_only'], key),
                                                 fmt(t[key]['vector_only'], key), fmt(s[key]['filter_first'], key),
                                                 fmt(t[key]['filter_first'], key)))
    lines += ['', '- 오늘 상태로 재면 9/15 뒤에 닫힌 공고가 벡터만에서는 "신청 불가"로 세지고, 필터 먼저에서는 정형 필터가 미리 빼 버린다. '
                  '그 공고 중 내용이 맞던 것이 많아 필터 먼저 점수가 깎인다. 평가 날짜를 고정해도 데이터가 오늘 것이면 생기는 약점이다.']

    if reference:
        m = reference['metrics']
        mt = (reference_today or {}).get('metrics') or {}
        lines += ['', '## 9/28 과 비교', '',
                  '| 지표 | 벡터만 9/28 | 벡터만 지금(기준일 상태) | 필터 먼저 9/28 | 필터 먼저 지금(기준일 상태) | 필터 먼저 지금(오늘 상태) |',
                  '|---|---:|---:|---:|---:|---:|']
        for key, row in m.items():
            lines.append('| %s | %s | %s | %s | %s | %s |' % (
                row['label'], fmt(row['vector_only_0928'], key), fmt(row['vector_only_now'], key),
                fmt(row['filter_first_0928'], key), fmt(row['filter_first_now'], key),
                fmt((mt.get(key) or {}).get('filter_first_now'), key)))
        vi, p3 = m['ineligible_k'], m['p3_lo']
        b = breakdown['vector_only']
        lines += ['',
                  '- **벡터만 신청 불가@10**: 9/28 %s → 지금 %s (%s, %+.1f%%p). 9/28 기준(예비창업자만 본문 판정)으로 다시 세면 %s — '
                  '기준 변경(개인사업자·법인 강한 불가)으로 늘어난 칸은 %d칸이다.'
                  % (fmt(vi['vector_only_0928'], 'ineligible_k'), fmt(vi['vector_only_now'], 'ineligible_k'),
                     direction(vi['vector_only_0928'], vi['vector_only_now']),
                     _pp(vi['vector_only_0928'], vi['vector_only_now']),
                     fmt(b['ineligible_k_0928_criterion'], 'ineligible_k'), b['entity_block_slots']),
                  '- **필터 먼저 P@3(2) 하한**: 9/28 %s → 지금 %s — **%s** (%+.1f%%p).'
                  % (fmt(p3['filter_first_0928'], 'p3_lo'), fmt(p3['filter_first_now'], 'p3_lo'),
                     direction(p3['filter_first_0928'], p3['filter_first_now']),
                     _pp(p3['filter_first_0928'], p3['filter_first_now']))]
        if mt:
            vt, pt = mt['ineligible_k'], mt['p3_lo']
            lines.append('- 오늘 상태 그대로였다면: 벡터만 신청 불가@10 %s, 필터 먼저 P@3(2) 하한 %s (9/28 대비 %s, %+.1f%%p).'
                         % (fmt(vt['vector_only_now'], 'ineligible_k'), fmt(pt['filter_first_now'], 'p3_lo'),
                            direction(pt['filter_first_0928'], pt['filter_first_now']),
                            _pp(pt['filter_first_0928'], pt['filter_first_now'])))
        for system, title in (('vector_only', '벡터만'), ('filter_first', '필터 먼저')):
            o = reference['lists'][system]
            lines.append('- %s 상위 10 목록(기준일 상태): 질의 %d개 중 순서까지 같음 %d · 같은 공고 10건 %d · 상위 3 순서 같음 %d · '
                         '평균 겹침 @10 %.1f%% · @3 %.1f%%'
                         % (title, o['queries'], o['same_order'], o['same_set_k'], o['same_top3_order'],
                            100 * (o['overlap_k'] or 0), 100 * (o['overlap_3'] or 0)))
        o = reference['lists']['vector_only']['ineligible_slots']
        lines.append('- 벡터만 목록에서 9/28 과 지금 모두 뜬 공고: 둘 다 불가 %d칸 · 지금만 불가 %d칸(이유: %s) · 9/28 만 불가 %d칸.'
                     % (o.get('both', 0), o.get('now_only', 0),
                        ' · '.join('%s %d' % kv for kv in reference['lists']['vector_only']['now_only_reasons'].items())
                        or '없음', o.get('then_only', 0)))

    lines += ['', '## 신청 불가 칸 나눠 보기', '',
              '| 방식 | 모집 상태 | 칸 | 신청 불가 칸 | 이유별(겹침 있음) | 개인사업자·법인 본문 불가 칸 | 9/28 기준으로 다시 센 신청 불가@10 |',
              '|---|---|---:|---:|---|---:|---:|']
    for system, title in (('vector_only', '벡터만'), ('filter_first', '지금(필터 먼저)')):
        for label, bd in (('기준일', breakdown), ('오늘', breakdown_today)):
            b = bd[system]
            lines.append('| %s | %s | %d | %d | %s | %d | %s |' % (
                title, label, b['slots'], b['ineligible_slots'],
                ' · '.join('%s %d' % kv for kv in b['by_reason'].items()) or '-',
                b['entity_block_slots'], fmt(b['ineligible_k_0928_criterion'], 'ineligible_k')))

    dec = st.get('decisions') or {}
    lines += ['', '## 기준일 모집 상태 — 규칙과 근거', '',
              '- 근거: %s. 9/30 부터 매일 배치가 K-Startup "모집 중 목록에서 빠진 공고"를 마감으로 바꾼다'
              '(`shared/store_mysql.close_missing`, 닫을 때 `snapshot_at` 을 그 목록 시각으로 덮는다). 첫 일괄 닫기 %s. '
              '9/28 실행 때는 이 기능이 없어 이 공고들이 모두 "모집 중"이었다.'
              % (st.get('evidence', '-'), st.get('first_close_sweep') or '없음'),
              '- 지금 마감인 말뭉치 공고 %s건 — close_missing 이 닫음(원본 표시 모집 중) %s건 · 출처가 마감으로 준 것 %s건.'
              % (st.get('closed_now_in_corpus', '-'), st.get('closed_by_close_missing', '-'), st.get('source_said_closed', '-')),
              '- 규칙: %s' % st.get('rule', '-'),
              '- 판정 결과: 마감일이 기준일 이후라 되돌림 %d · 첫 일괄 닫기 뒤에 닫혀 되돌림(마감일 없음) %d · '
              '기준일 전에 닫힌 기록이 있어 그대로 %d · 마감일이 기준일 전이라 그대로 %d · 마감일이 없고 닫힌 날을 알 수 없어 그대로 %d.'
              % tuple(dec.get(d, 0) for d in DECISIONS),
              '- 한계: %s' % st.get('caveat', '-')]
    lines += ['', '## 그 밖의 한계', '',
              '- 판정 정답은 9/15 풀에서 나왔다. 지금 방식이 미판정 공고를 많이 올리면(미판정@10) P@3 하한·상한 폭이 넓어진다.',
              '- LLM 판정(llm·llm_old)은 AI 참고 정답이다. 사람 판정은 143쌍뿐이다.',
              '- 9/28 과의 남은 작은 차이 후보(따로 나눠 재지 않음): Chroma 근사 검색 → 메모리 정확 계산, 9/28 뒤 공고 본문 갱신에 따른 '
              '단어 검색 색인 변화, 신청자 유형 판정표 갱신.',
              '', '## 다시 돌리기', '',
              '```powershell',
              '$env:HF_HUB_OFFLINE = "1"',
              '.\\.venv\\Scripts\\python.exe -X utf8 -m eval.filter_first_now',
              '```']
    return lines


def load_reference():
    path = os.path.join(ROOT, 'reports', REFERENCE_RUN, 'results.json')
    if not os.path.exists(path):
        return None
    with io.open(path, encoding='utf-8') as f:
        return json.load(f)


# ── 실행 ─────────────────────────────────────────────────────────────────────
def run_systems(app, gate, queries, qrels, as_of, rows, types_table):
    """두 방식을 지금 STATE 로 한 번씩 돌려 질의별 지표·목록을 만든다. (per, lists, 보인 공고, 대체 경로 수)."""
    per = {m: {s: [] for s in SYSTEMS} for m in MODES}
    lists, shown, fallbacks = [], set(), 0
    for q in queries:
        p = q['payload']
        kind = p.get('applicant_type')
        age = gate.applicant_age(kind, p.get('founded_at'), as_of)
        rels = qrels.get(q['qid'], {})
        for name in SYSTEMS:
            out = app.match(app.MatchRequest(**request_for(name, p)))
            ranked = [r['notice_id'] for r in out['results']]
            fallbacks += bool(out.get('fallback_used'))
            checks = eligibility_checks(app.eligible_with_types, rows, ranked, age, as_of, types_table, kind)
            old = eligibility_checks(app.eligible_with_types, rows, ranked, age, as_of, types_table, kind,
                                     entity_blocks=False)
            eligible = {n: ok for n, (ok, _why) in checks.items()}
            m = ffe.query_metrics(ranked, rels, eligible)
            per['hybrid'][name].append(m)
            shown.update(ranked)
            lists.append({'qid': q['qid'], 'mode': 'hybrid', 'system': name, 'ranked': ranked,
                          'ineligible': [n for n in ranked if not eligible[n]],
                          'why': {n: why for n, (ok, why) in checks.items() if not ok},
                          'rels': {n: rels.get(n) for n in ranked},
                          'unjudged': [n for n in ranked if n not in rels], 'metrics': m,
                          'ineligible_0928_criterion': [n for n in ranked if not old[n][0]],
                          'search': out.get('search'), 'fallback_mode': out.get('fallback_mode'),
                          'dense_path': out.get('dense_path'), 'filtered_count': out.get('filtered_count'),
                          'bonus_rank_applied': [r['notice_id'] for r in out['results'] if r.get('bonus_rank_applied')]})
    return per, lists, shown, fallbacks


def pool_info(lists):
    ff = [l for l in lists if l['system'] == 'filter_first']
    return {'filtered_count_mean': ffe.mean([l['filtered_count'] for l in ff]),
            'lists_with_bonus_rank_applied': sum(1 for l in ff if l['bonus_rank_applied']),
            'bonus_rank_applied_slots': sum(len(l['bonus_rank_applied']) for l in ff)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', help='결과 폴더 (기본 reports/filter_first_now_<UTC 시각>)')
    args = ap.parse_args(argv)
    os.environ.setdefault('HF_HUB_OFFLINE', '1')

    queries = [q for q in common.load_queries().values() if q['kind'] == 'normal']
    as_ofs = {q['as_of_date'] for q in queries}
    if len(as_ofs) != 1:
        raise SystemExit('질의 기준일이 여러 개다: %s' % sorted(as_ofs))
    as_of = real_date.fromisoformat(as_ofs.pop())
    qrel_rows, qrels_source = choose_qrels(common.read_jsonl(common.QRELS), _qrels_0928)
    qrels = qrels_from_rows(qrel_rows)
    qrels_sha = hashlib.sha256('\n'.join(json.dumps(r, ensure_ascii=False, sort_keys=True)
                                         for r in qrel_rows).encode('utf-8')).hexdigest()

    from search import app, gate
    started = datetime.now(timezone.utc)
    app.boot()
    corpus = ffe.corpus_rows(app)
    corpus_ids = restrict_corpus(app.STATE, corpus)
    evidence, first_sweep = status_evidence(corpus_ids)
    ffe.pin_today((app, gate), as_of)

    cache, encode = {}, app._encode

    def cached(text):
        if text not in cache:
            cache[text] = encode(text)
        return cache[text]
    app._encode = cached

    rows = app.STATE['rows']
    types_table = app.STATE.get('applicant_types') or {}
    today_status = {n: r.get('recruitment_status') for n, r in rows.items()}

    # 1) 오늘 모집 상태 그대로(참고값) → 2) 기준일 모집 상태로 메모리에서 되돌린 뒤(대표 수치)
    per_t, lists_t, shown_t, fb_t = run_systems(app, gate, queries, qrels, as_of, rows, types_table)
    decisions = as_of_status(evidence, as_of, first_sweep)
    reopened = reopen(rows, [n for n, d in decisions.items() if d in REOPEN])
    per, lists, shown, fb = run_systems(app, gate, queries, qrels, as_of, rows, types_table)

    summary, summary_today = build_summary(per), build_summary(per_t)
    st_meta = status_meta(decisions, evidence, as_of, first_sweep, reopened)
    meta = build_meta(started, corpus_ids, as_of, queries, qrels, qrels_source, qrels_sha, app.STATE, fb + fb_t, st_meta)
    breakdown = {s: ineligible_breakdown(lists, rows, as_of, s) for s in SYSTEMS}
    breakdown_today = {s: ineligible_breakdown(lists_t, rows, as_of, s) for s in SYSTEMS}
    ref = load_reference()
    reference, reference_today = compare_reference(ref, summary, lists), compare_reference(ref, summary_today, lists_t)
    meta['filter_first_pool'] = pool_info(lists)
    meta['filter_first_pool_today_status'] = pool_info(lists_t)
    if fb or fb_t:
        print('경고: 대체 경로로 답한 목록 %d개 — 의미 검색이 실패했다. 수치를 9/28 과 비교하지 않는다' % (fb + fb_t),
              file=sys.stderr)

    out_dir = args.out or os.path.join(ROOT, 'reports', 'filter_first_now_' + started.strftime('%Y%m%dT%H%M%SZ'))
    os.makedirs(out_dir, exist_ok=False)
    with io.open(os.path.join(out_dir, 'results.json'), 'w', encoding='utf-8') as f:
        json.dump({'meta': meta, 'summary': summary, 'summary_today_status': summary_today,
                   'breakdown': breakdown, 'breakdown_today_status': breakdown_today,
                   'reference_0928': reference, 'reference_0928_today_status': reference_today,
                   'lists': lists, 'lists_today_status': lists_t,
                   'queries': [{'qid': q['qid'], 'category': q.get('category'), 'idea': q['payload'].get('idea'),
                                'applicant_type': q['payload'].get('applicant_type'),
                                'founded_at': q['payload'].get('founded_at') or ''} for q in queries],
                   'notices': {n: {'title': rows[n].get('title') or '', 'source': rows[n].get('source'),
                                   'apply_end': str(rows[n].get('apply_end') or ''),
                                   'recruitment_status': today_status.get(n),
                                   'status_as_of': rows[n].get('recruitment_status'),
                                   'status_decision': decisions.get(n),
                                   'age_condition': rows[n].get('age_condition_raw') or ''}
                               for n in sorted(shown | shown_t)}}, f, ensure_ascii=False, indent=1)
    lines = render_readme(meta, summary, summary_today, breakdown, breakdown_today, reference, reference_today)
    with io.open(os.path.join(out_dir, 'README.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    print('결과 → %s' % out_dir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
