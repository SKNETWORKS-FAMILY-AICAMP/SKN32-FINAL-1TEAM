# -*- coding: utf-8 -*-
"""사람·LLM 판정을 합쳐 qrels.jsonl 을 만들고, 블라인드 일치율을 보고한다.

  python -X utf8 eval/merge_qrels.py

채택 순서 (쌍마다 하나)

  human     사람 판정. 모드와 무관하게 가장 마지막 것 (재확인 > 블라인드)
  llm       현재 기준(topic-v2) 프롬프트에서 A·B 가 같은 값 — **잠정**
  llm_old   이전 기준(topic-v1) 프롬프트에서 A·B 가 같은 값 — **더 잠정**
  (제외)    A·B 불일치 · null · 사람이 '판단 불가' — **미판정. 0 으로 치지 않는다**

2026-09-15 블라인드·재확인 결과 LLM 판정은 사람 판정을 대신할 수준이 아니다
(재확인 반영 정확 일치 0.64, 보정 추정 약 0.54). 사람도 같은 쌍을 다시 보면 34% 를
바꿨다 — 등급 1 의 경계가 사람에게도 애매하다. 그래서 LLM 판정은 잠정값으로만 쓰고,
평가는 사람 판정만 쓴 결과와 나란히 본다. 아래 TRUST 는 참고용으로 남겨 둔다.
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
from label_app import llm_latest  # noqa: E402

TRUST = {'exact': 0.70, 'kappa': 0.60, 'swap02': 0.03}


def old_llm():
    """이전 프롬프트들의 판정. 같은 쌍에 여러 이전 프롬프트가 있으면 파일에서 나중 것.
    gpt-4.1-mini 결과만 쓴다 — 4o-mini 시험분(2질의)은 자격 조건으로 깎는 문제가 있었다."""
    from judge_llm import PROMPT_SHA
    out = {}
    for j in common.read_jsonl(common.LLM):
        if (j.get('topic_rel') == 'err' or j.get('prompt_sha') == PROMPT_SHA
                or j.get('model') != 'gpt-4.1-mini'):
            continue
        out.setdefault((j['qid'], j['notice_id']), {})[j['run']] = j
    return out


def weighted_kappa(pairs, k=3):
    """이차 가중 카파. pairs = [(사람, LLM)] 값은 0..k-1"""
    n = len(pairs)
    if not n:
        return None
    obs = [[0] * k for _ in range(k)]
    for a, b in pairs:
        obs[a][b] += 1
    ra = [sum(obs[i]) for i in range(k)]
    rb = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    w = lambda i, j: (i - j) ** 2 / (k - 1) ** 2
    po = sum(w(i, j) * obs[i][j] for i in range(k) for j in range(k)) / n
    pe = sum(w(i, j) * ra[i] * rb[j] for i in range(k) for j in range(k)) / n / n
    return None if pe == 0 else 1 - po / pe


def agreement(human_rows, llm, use_recheck=True):
    """블라인드 표본의 사람 판정 vs LLM. use_recheck 면 재확인 판정이 있는 쌍은 그것을 쓴다.

    재확인은 LLM 과 갈린 쌍 위주로 뽑혀서, 반영한 일치율은 약간 낙관적이다.
    원 블라인드 수치와 함께 본다.
    """
    latest = {}
    for h in human_rows:
        if h['mode'] == 'blind':
            latest[(h['qid'], h['notice_id'])] = h['topic_rel']
    if use_recheck:
        for h in human_rows:
            if h['mode'] == 'recheck' and (h['qid'], h['notice_id']) in latest:
                latest[(h['qid'], h['notice_id'])] = h['topic_rel']
    latest = {k: v for k, v in latest.items() if v is not None}
    pairs_a, pairs_ab, unjudged = [], [], 0
    for key, hv in latest.items():
        runs = llm.get(key, {})
        if 'A' not in runs or runs['A']['topic_rel'] is None:
            unjudged += 1
            continue
        pairs_a.append((hv, runs['A']['topic_rel']))
        if 'B' in runs and runs['B']['topic_rel'] == runs['A']['topic_rel']:
            pairs_ab.append((hv, runs['A']['topic_rel']))
    return pairs_a, pairs_ab, unjudged


def report(name, pairs):
    n = len(pairs)
    if not n:
        print('  %s: 표본 없음' % name)
        return None
    exact = sum(a == b for a, b in pairs) / n
    swap = sum({a, b} == {0, 2} for a, b in pairs) / n
    binary = sum((a >= 1) == (b >= 1) for a, b in pairs) / n
    kappa = weighted_kappa(pairs)
    print('  %s  n=%d  정확일치 %.2f  가중카파 %s  0↔2 %.1f%%  이진(≥1) %.2f'
          % (name, n, exact, '%.2f' % kappa if kappa is not None else '-', swap * 100, binary))
    conf = Counter(pairs)
    print('           LLM→  0    1    2')
    for h in range(3):
        print('    사람 %d   %4d %4d %4d' % (h, conf[(h, 0)], conf[(h, 1)], conf[(h, 2)]))
    return {'n': n, 'exact': exact, 'kappa': kappa, 'swap02': swap, 'binary': binary}


def main():
    pool = common.read_jsonl(common.POOL)
    llm = llm_latest()
    old = old_llm()
    human_rows = common.read_jsonl(common.HUMAN)
    human = {}
    for h in human_rows:
        human[(h['qid'], h['notice_id'])] = h           # 마지막 것이 이긴다

    out, counts = [], Counter()
    for p in sorted(pool, key=lambda p: (p['qid'], p['order'])):
        key = (p['qid'], p['notice_id'])
        base = {'qid': p['qid'], 'notice_id': p['notice_id'], 'label_version': common.LABEL_VERSION}
        if key in human:
            h = human[key]
            if h['topic_rel'] is None:
                counts['human_unknown'] += 1
                continue
            out.append(dict(base, topic_rel=h['topic_rel'], judge='human',
                            reviewer=h.get('reviewer'), reason=h.get('reason')))
            counts['human'] += 1
            continue
        # 현재 기준 프롬프트 → 없으면 이전 프롬프트(topic-v1). 둘 다 A=B 일 때만 쓴다.
        picked = None
        for judge, runs in (('llm', llm.get(key, {})), ('llm_old', old.get(key, {}))):
            if len(runs) < 2:
                continue
            a, b = runs['A'], runs['B']
            if a['topic_rel'] is not None and a['topic_rel'] == b['topic_rel']:
                picked = (judge, a)
                break
        if picked is None:
            counts['llm_disagree_or_none'] += 1
            continue
        judge, a = picked
        out.append(dict(base, topic_rel=a['topic_rel'], judge=judge, model=a['model'],
                        prompt_sha=a['prompt_sha'], reason=a['reason']))
        counts[judge] += 1

    common.write_jsonl(common.QRELS, out)
    print('qrels %d쌍 / 풀 %d쌍' % (len(out), len(pool)))
    for k in ('human', 'llm', 'llm_old', 'llm_disagree_or_none', 'human_unknown'):
        print('  %-15s %d' % (k, counts[k]))
    dist = Counter(r['topic_rel'] for r in out)
    print('  topic_rel 분포  0:%d 1:%d 2:%d' % (dist[0], dist[1], dist[2]))

    rechecked = sum(1 for h in human_rows if h['mode'] == 'recheck')
    if rechecked:
        print('\n원 블라인드 판정 기준 (재확인 반영 전)')
        report('LLM A     ', agreement(human_rows, llm, use_recheck=False)[0])
        print('\n재확인 %d건 반영 (갈린 쌍 위주 표본이라 약간 낙관적)' % rechecked)
    else:
        print('\n블라인드 일치율 (사람 vs LLM)')
    pairs_a, pairs_ab, unjudged = agreement(human_rows, llm)
    ra = report('LLM A     ', pairs_a)
    report('A=B 인 쌍 ', pairs_ab)
    if unjudged:
        print('  LLM 이 null 이라 비교에서 뺀 쌍 %d' % unjudged)
    if ra and ra['n'] >= 100:
        ok = (ra['exact'] >= TRUST['exact'] and (ra['kappa'] or 0) >= TRUST['kappa']
              and ra['swap02'] <= TRUST['swap02'])
        print('  잠정 기준(%s) → %s' % (TRUST, '통과: 검수 대기열만 보면 된다' if ok
                                    else '미달: 프롬프트·모델을 고치거나 사람 판정 범위를 넓힌다'))
    elif ra:
        print('  블라인드 %d쌍 — 100쌍 이상 모이면 기준 판정을 출력한다' % ra['n'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
