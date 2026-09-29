# -*- coding: utf-8 -*-
"""Jev(TypeSafe AI, 2026-09-15 공개) 채점 시험 — 사람 블라인드 판정과 얼마나 맞는지 잰다. 유료(무료 크레딧 $5).

  python -X utf8 eval/jev_judge_probe.py --plan          쌍 수·예상 토큰·비용만 (호출 없음)
  python -X utf8 eval/jev_judge_probe.py --limit 5       5쌍만 (한국어·형식이 되는지 먼저)
  python -X utf8 eval/jev_judge_probe.py                 블라인드 표본 전체(약 150쌍)

2026-09-28 사용자 요청: "jev 를 테스트용으로 한 번 써 보자". 평가 채점(주제 관련도 0·1·2)은 보기가 정해진
객관식이라 Jev(글을 쓰지 않고 정해진 보기 중에서 고르며 확신도를 준다)에 맞는다.

무엇과 비교하나
  정답   사람 블라인드 판정(merge_qrels.agreement 와 같은 표본·같은 재확인 반영 규칙)
  대조   같은 쌍의 현재 LLM 판정(gpt-4.1-mini, A 순서) — 기존 "정확 일치 0.64" 와 같은 계산
  Jev    같은 입력(common.persona_text · common.notice_text), 같은 판정 기준(judge_llm.SYSTEM 요약)
지표는 merge_qrels.report 와 같다(정확 일치 · 가중 카파 · 0↔2 뒤바뀜 · 이진 ≥1). 추가로 Jev 확신도 구간별 일치율.

지키는 것
  - eval/llm_judgments.jsonl·qrels 는 건드리지 않는다. 결과는 reports/jev_judge_probe_<시각>/ 에만 쓴다.
  - 공용 DB 쓰기 없음. 보내는 것은 평가용 가상 신청자 입력과 공개 공고 글뿐이다.
  - 키는 .env 의 TYPESAFE_API_KEY (SDK 가 이 이름을 읽는다). 코드·결과에 키를 남기지 않는다.
"""
import argparse
import io
import json
import os
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import common  # noqa: E402
import merge_qrels  # noqa: E402

PRICE_IN = 0.042          # 1M 입력 토큰당 USD (TypeSafe 블로그, 2026-09). 출력은 무료
PER_DECISION_CAP = 0.0011  # 기사에 나온 "판단 1건 약 $0.0011" — 보수적 상한으로 같이 보인다

# judge_llm.SYSTEM 의 판정 기준을 Jev 질문 형식(지시 + 보기별 설명)으로 옮겼다. 기준 자체는 바꾸지 않는다.
INSTRUCTIONS = (
    '정부·지자체 창업/중소기업 지원사업 검색의 평가다. 신청자 정보와 공고 하나를 보고 **주제 관련도**만 판정한다. '
    '주제로 보는 것: 공고가 지원하는 내용(자금·설비·R&D·수출·판로·인력·교육·입주공간·인증 등)과 겨냥한 업종·기술 분야. '
    '자격 조건은 판정에 쓰지 않는다 — 지역 제한, 업력·매출·규모 요건, 사업자 형태(예비창업자/개인/법인), 마감일·모집 상태 때문에 점수를 깎지 않는다. '
    '다만 공고가 장애인·제대군인·체육인·재창업자·사회적기업·경력단절여성·연구자 등 특정 집단만 대상으로 하는데 '
    '신청자 정보에 그 집단이라는 근거가 없으면 0 이다. "AI", "친환경", "창업" 같은 넓은 단어가 겹친다는 이유만으로 2 를 주지 않는다.'
)
CRITERIA = {
    '2': '신청자의 업종·기술·제품을 겨냥한 공고이고 지원 내용도 신청자 입력에 드러난 필요와 맞는다.',
    '1': '한쪽만 맞는다. 분야 키워드는 겹치지만 교육·경진대회·데모데이·네트워킹·공모전 같은 범용 프로그램이라 '
         '신청자 필요와 직접 맞지 않거나, 지원 내용은 맞지만 대상 분야가 일부만 겹친다. '
         '업종을 가리지 않는 공고인데 지원 내용이 필요와 정확히 맞으면 1 과 2 중 가까운 쪽.',
    '0': '지원 내용과 대상 분야 둘 다 연결되지 않거나, 대상 업종이 명백히 다르거나, 특정 대상 집단 한정인데 신청자 근거가 없다. '
         '신청자 입력이 일상 문장이어도 0.',
    'unknown': '공고 정보가 너무 부족해 판단할 수 없다.',
}
CONF_BINS = ((0.9, '0.9 이상'), (0.7, '0.7~0.9'), (0.0, '0.7 미만'))


def blind_truth(human_rows):
    """merge_qrels.agreement 와 같은 규칙 — 블라인드 판정, 재확인이 있으면 재확인. (재확인 반영, 원 블라인드)"""
    blind, recheck = {}, {}
    for h in human_rows:
        key = (h['qid'], h['notice_id'])
        if h['mode'] == 'blind':
            blind[key] = h['topic_rel']
    for h in human_rows:
        key = (h['qid'], h['notice_id'])
        if h['mode'] == 'recheck' and key in blind:
            recheck[key] = h['topic_rel']
    with_recheck = {k: recheck.get(k, v) for k, v in blind.items()}
    drop_none = lambda d: {k: v for k, v in d.items() if v is not None}
    return drop_none(with_recheck), drop_none(blind)


def metrics(pairs):
    """merge_qrels.report 와 같은 숫자를 조용히(출력 없이) 계산한다."""
    n = len(pairs)
    if not n:
        return None
    return {'n': n, 'exact': sum(a == b for a, b in pairs) / n,
            'kappa': merge_qrels.weighted_kappa(pairs),
            'swap02': sum({a, b} == {0, 2} for a, b in pairs) / n,
            'binary': sum((a >= 1) == (b >= 1) for a, b in pairs) / n,
            'confusion': {'%d>%d' % k: v for k, v in sorted(Counter(pairs).items())}}


def conf_bin(c):
    for lo, name in CONF_BINS:
        if c is not None and c >= lo:
            return name
    return '확신도 없음'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plan', action='store_true', help='호출 없이 쌍 수·예상 비용만')
    ap.add_argument('--limit', type=int, help='앞에서 N쌍만')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--model', help='Jev 모델 버전 고정(예: jev-1.13.0). 없으면 SDK 기본값')
    args = ap.parse_args(argv)

    queries = common.load_queries()
    snap = common.load_snapshot()
    human_rows = common.read_jsonl(common.HUMAN)
    truth, truth_blind = blind_truth(human_rows)
    keys = sorted(truth)
    missing = [k for k in keys if k[1] not in snap or k[0] not in queries]
    if missing:
        raise SystemExit('스냅샷·질의에 없는 쌍 %d개 — build_pool.py 상태를 확인한다' % len(missing))
    if args.limit:
        keys = keys[:args.limit]

    def inputs(key):
        return {'신청자': common.persona_text(queries[key[0]]['payload']),
                '공고': common.notice_text(snap[key[1]])}

    chars = sum(len(INSTRUCTIONS) + len(json.dumps(CRITERIA, ensure_ascii=False)) +
                sum(len(v) for v in inputs(k).values()) for k in keys)
    est_tokens = chars * 0.9                     # 한국어는 대략 글자당 0.9토큰(judge_llm 과 같은 추정)
    print('쌍 %d · 예상 입력 약 %.0f 토큰 · 토큰 단가 기준 약 $%.3f · 판단당 상한 기준 최대 $%.2f (무료 크레딧 $5)'
          % (len(keys), est_tokens, est_tokens / 1e6 * PRICE_IN, len(keys) * PER_DECISION_CAP))
    if args.plan:
        return 0

    from shared import config
    if not config.get('TYPESAFE_API_KEY'):          # config.load() 가 .env 를 환경변수로 올린다
        print('TYPESAFE_API_KEY 가 .env 에 없다')
        return 1
    try:
        from typesafe_sdk import Choice, TypeSafeClient
    except ImportError:
        print('typesafe-sdk 가 설치돼 있지 않다:  .venv\\Scripts\\python.exe -m pip install typesafe-sdk')
        return 1

    started = datetime.now(timezone.utc)
    out_dir = os.path.join(ROOT, 'reports', 'jev_judge_probe_' + started.strftime('%Y%m%dT%H%M%SZ'))
    os.makedirs(out_dir, exist_ok=False)
    lock = threading.Lock()
    rows = []

    with TypeSafeClient() as client:
        def one(key):
            question = Choice(instructions=INSTRUCTIONS, criteria=CRITERIA)
            err = None
            for attempt in range(4):
                try:
                    t0 = time.time()
                    kw = {'model': args.model} if args.model else {}
                    r = client.system_one(state=inputs(key), questions={'topic_rel': question}, **kw)
                    a = r.answers['topic_rel']
                    return {'qid': key[0], 'notice_id': key[1], 'choice': a.choice,
                            'topic_rel': None if a.choice == 'unknown' else int(a.choice),
                            'confidence': getattr(a, 'confidence', None),
                            'probabilities': {str(k): v for k, v in (getattr(a, 'probabilities', None) or {}).items()},
                            'model': getattr(r, 'model', None), 'usage': str(getattr(r, 'usage', '')),
                            'ms': round((time.time() - t0) * 1000)}
                except Exception as exc:            # 한 건 실패로 전체를 멈추지 않는다
                    err = '%s: %s' % (type(exc).__name__, str(exc)[:300])
                    time.sleep(2 ** attempt)
            return {'qid': key[0], 'notice_id': key[1], 'topic_rel': 'err', 'error': err}

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = [ex.submit(one, k) for k in keys]
            for i, fut in enumerate(as_completed(futures), 1):
                row = fut.result()
                with lock:
                    rows.append(row)
                    common.append_jsonl(os.path.join(out_dir, 'judgments.jsonl'), [row])
                    if i % 10 == 0 or i == len(keys):
                        print('  %d/%d' % (i, len(keys)))

    ok = [r for r in rows if r.get('topic_rel') != 'err']
    errors = [r for r in rows if r.get('topic_rel') == 'err']
    jev = {(r['qid'], r['notice_id']): r for r in ok}

    # 대조: 같은 쌍의 현재 LLM(A 순서) — merge_qrels 가 0.64 를 낸 것과 같은 방식
    from label_app import llm_latest
    llm = llm_latest()
    llm_a = {k: v['A']['topic_rel'] for k, v in llm.items() if 'A' in v and v['A']['topic_rel'] is not None}

    def pairs(judge, truth_map, only=None):
        return [(truth_map[k], judge[k]) for k in truth_map
                if k in judge and judge[k] is not None and (only is None or k in only)]

    jev_rel = {k: r['topic_rel'] for k, r in jev.items()}
    judged = {k for k, v in jev_rel.items() if v is not None}
    both = judged & set(llm_a)
    by_bin = {}
    for name in [b for _, b in CONF_BINS]:
        ks = {k for k in judged if conf_bin(jev[k].get('confidence')) == name}
        by_bin[name] = metrics(pairs(jev_rel, truth, ks))
    summary = {
        'meta': {'run_at': started.isoformat(timespec='seconds'), 'pairs': len(keys), 'answered': len(ok),
                 'errors': len(errors), 'unknown': sum(1 for r in ok if r['topic_rel'] is None),
                 'models': sorted({str(r.get('model')) for r in ok}),
                 'median_ms': sorted(r['ms'] for r in ok)[len(ok) // 2] if ok else None,
                 'truth': 'human blind (+recheck), merge_qrels.agreement 규칙', 'db_writes': 0},
        'jev_vs_human': metrics(pairs(jev_rel, truth)),
        'jev_vs_human_blind_only': metrics(pairs(jev_rel, truth_blind)),
        'same_pairs': {'n': len(both), 'jev': metrics(pairs(jev_rel, truth, both)),
                       'llm_gpt41mini_A': metrics(pairs(llm_a, truth, both))},
        'jev_by_confidence': by_bin,
        'error_samples': [r['error'] for r in errors[:5]],
    }
    with io.open(os.path.join(out_dir, 'summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    lines = render(summary)
    with io.open(os.path.join(out_dir, 'summary.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    print('결과 → %s' % out_dir)
    return 0 if ok else 2


def render(s):
    m = s['meta']
    f = lambda x: '0 | - | - | - | -' if not x else '%d | %.2f | %s | %.1f%% | %.2f' % (
        x['n'], x['exact'], '-' if x['kappa'] is None else '%.2f' % x['kappa'], x['swap02'] * 100, x['binary'])
    head = ['| 비교 | n | 정확 일치 | 가중 카파 | 0↔2 뒤바뀜 | 이진(≥1) |', '|---|---:|---:|---:|---:|---:|']
    lines = ['# Jev 채점 시험 — 사람 블라인드 판정과 일치율', '',
             '- 실행 %s · 쌍 %d · 응답 %d · 오류 %d · 판단불가 %d · 모델 %s · 응답 시간 중앙값 %s ms'
             % (m['run_at'], m['pairs'], m['answered'], m['errors'], m['unknown'], ', '.join(m['models']), m['median_ms']),
             '- 기준(잠정): 정확 일치 ≥0.70 · 가중 카파 ≥0.60 · 0↔2 ≤3% (merge_qrels.TRUST)', '', '## 전체', ''] + head + [
        '| Jev vs 사람(재확인 반영) | %s |' % f(s['jev_vs_human']),
        '| Jev vs 사람(원 블라인드) | %s |' % f(s['jev_vs_human_blind_only']), '',
        '## 같은 쌍에서 기존 LLM 과 나란히 (n=%d)' % s['same_pairs']['n'], ''] + head + [
        '| Jev | %s |' % f(s['same_pairs']['jev']),
        '| gpt-4.1-mini (A 순서) | %s |' % f(s['same_pairs']['llm_gpt41mini_A']), '',
        '## Jev 확신도 구간별 (확신이 높을수록 더 맞아야 쓸모가 있다)', ''] + head
    for name, x in s['jev_by_confidence'].items():
        lines.append('| 확신도 %s | %s |' % (name, f(x)))
    if s['error_samples']:
        lines += ['', '## 오류 예시', ''] + ['- %s' % e for e in s['error_samples']]
    return lines


if __name__ == '__main__':
    sys.exit(main())
