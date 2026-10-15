# -*- coding: utf-8 -*-
"""관련도 판정 꾸러미를 기존 LLM 판정자(judge_llm.py)와 **같은 기준**으로 판정한다(2026-09-30).

  python -X utf8 -m eval.judge_llm_pack --plan     호출 없이 할 일·예상 비용만
  python -X utf8 -m eval.judge_llm_pack            판정(유료). 이미 한 호출은 건너뛴다
  python -X utf8 -m eval.judge_llm_pack --score    호출 없이 합치기·채점만 다시

왜: 기존 qrels 는 대부분 gpt-4.1-mini(judge_llm.py) 판정이다. 새 빈칸을 다른 판정자(Codex, 더 엄격)로 채우면
새 공고를 많이 올리는 방식이 기준 차이 때문에 불리해진다. 같은 판정자로 맞춘다(사용자 결정 2026-09-30).

- 프롬프트·모델·스키마·A/B 두 번 판정은 judge_llm.py 의 것을 그대로 가져온다(PROMPT_SHA 같음).
- 공고 설명은 꾸러미 items.jsonl 의 notice(common.notice_text 형식, 공용 DB 현재 글)다. 기존 판정은 9/15 스냅샷 글이다.
- 합치기 규칙은 merge_qrels.py 와 같다: A 와 B 가 같고 null 이 아닐 때만 쓴다.
- 결과는 꾸러미 폴더에만 쓴다: llm_judgments.jsonl(호출 원본) · llm_qrels.jsonl(대조군 제외 대상) · llm_score.json/md.
  eval/llm_judgments.jsonl · eval/qrels.jsonl · pool·스냅샷은 고치지 않는다.
- 대조군(사람 판정 40쌍)도 판정해 LLM 과 Codex 를 **같은 40쌍**에서 사람과 비교한다.
"""
import argparse
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
import judge_llm as jl  # noqa: E402
from relevance_label_score import weighted_kappa  # noqa: E402

PACK = 'relevance_label_pack_20260930'
OUT_TOKENS = 220            # 호출당 출력 토큰 추정(support·ignored·reason 세 문장 + JSON)


def load(pack):
    items = {r['item_id']: r for r in common.read_jsonl(os.path.join(pack, 'items.jsonl'))}
    hidden = {r['item_id']: r for r in common.read_jsonl(os.path.join(pack, 'answers_hidden.jsonl'))}
    persona = {r['qid']: r['persona'] for r in common.read_jsonl(os.path.join(pack, 'queries.jsonl'))}
    return items, hidden, persona


def done_calls(path):
    if not os.path.exists(path):
        return {}
    return {(r['item_id'], r['run']): r for r in common.read_jsonl(path)
            if r.get('prompt_sha') == jl.PROMPT_SHA and r.get('topic_rel', 'err') != 'err'}


def score(pack, items, hidden):
    calls = done_calls(os.path.join(pack, 'llm_judgments.jsonl'))
    runs = {}
    for (item_id, run), r in calls.items():
        runs.setdefault(item_id, {})[run] = r['topic_rel']
    agreed = {k: v['A'] for k, v in runs.items() if 'A' in v and 'B' in v and v['A'] is not None and v['A'] == v['B']}
    codex = {r['item_id']: r['topic_rel'] for r in common.read_jsonl(os.path.join(pack, 'labels.jsonl'))} \
        if os.path.exists(os.path.join(pack, 'labels.jsonl')) else {}

    def compare(pred):
        pairs = [(hidden[k]['human_topic_rel'], pred[k]) for k in hidden if hidden[k]['control'] and pred.get(k) is not None]
        if not pairs:
            return None
        return {'n': len(pairs), 'exact': sum(a == b for a, b in pairs) / len(pairs),
                'binary_2': sum((a == 2) == (b == 2) for a, b in pairs) / len(pairs),
                'weighted_kappa': weighted_kappa(pairs),
                'confusion': dict(sorted(Counter('%s→%s' % p for p in pairs).items()))}

    a_only = {k: v['A'] for k, v in runs.items() if 'A' in v}
    targets = [k for k in hidden if not hidden[k]['control']]
    rows = [{'qid': hidden[k]['qid'], 'notice_id': hidden[k]['notice_id'], 'label_version': common.LABEL_VERSION,
             'topic_rel': agreed[k], 'judge': 'llm', 'model': jl.JUDGE_MODEL, 'prompt_sha': jl.PROMPT_SHA,
             'source_pack': os.path.basename(pack)} for k in targets if k in agreed]
    common.write_jsonl(os.path.join(pack, 'llm_qrels.jsonl'), rows)
    both = [k for k in targets if k in agreed and codex.get(k) is not None]
    out = {'calls_ok': len(calls), 'items_judged_A': len(a_only), 'items_agreed_AB': len(agreed),
           'ab_disagree_or_null': sum(1 for v in runs.values() if len(v) == 2 and k_not_agree(v)),
           'controls_vs_human_A': compare(a_only), 'controls_vs_human_AB': compare(agreed),
           'controls_codex_vs_human': compare(codex),
           'targets': len(targets), 'targets_llm_qrels': len(rows),
           'target_labels_llm': dict(Counter(str(r['topic_rel']) for r in rows)),
           'targets_llm_vs_codex_exact': (sum(agreed[k] == codex[k] for k in both) / len(both)) if both else None,
           'targets_llm_vs_codex_n': len(both)}
    json.dump(out, open(os.path.join(pack, 'llm_score.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    f = lambda x: '-' if x is None else '%.2f' % x
    lines = ['# 꾸러미 LLM 판정 채점 (%s, %s, prompt %s)' % (os.path.basename(pack), jl.JUDGE_MODEL, jl.PROMPT_SHA), '',
             '| 대조군 40쌍 vs 사람 | n | 정확 일치 | "2냐 아니냐" | 가중 카파 |', '|---|---:|---:|---:|---:|']
    for name, key in (('LLM A 판정', 'controls_vs_human_A'), ('LLM A=B 인 쌍', 'controls_vs_human_AB'),
                      ('Codex', 'controls_codex_vs_human')):
        x = out[key]
        if x:
            lines.append('| %s | %d | %s | %s | %s |' % (name, x['n'], f(x['exact']), f(x['binary_2']), f(x['weighted_kappa'])))
    lines += ['', '- 대상 %d쌍 중 A=B 로 쓸 수 있는 것 %d쌍 → `llm_qrels.jsonl` · 라벨 %s'
              % (len(targets), len(rows), ', '.join('%s %d' % kv for kv in sorted(out['target_labels_llm'].items()))),
              '- 대상에서 LLM(A=B)과 Codex 정확 일치 %s (n=%d)' % (f(out['targets_llm_vs_codex_exact']), len(both)),
              '- eval/qrels.jsonl 은 고치지 않았다.']
    open(os.path.join(pack, 'llm_score.md'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


def k_not_agree(v):
    return v.get('A') is None or v.get('A') != v.get('B')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--score', action='store_true')
    ap.add_argument('--pack', default=PACK)
    ap.add_argument('--workers', type=int, default=8)
    args = ap.parse_args()
    pack = os.path.join(ROOT, 'reports', args.pack)
    items, hidden, persona = load(pack)
    if args.score:
        score(pack, items, hidden)
        return 0
    out_path = os.path.join(pack, 'llm_judgments.jsonl')
    done = done_calls(out_path)
    todo = [(k, run) for k in sorted(items) for run in ('A', 'B') if (k, run) not in done]
    est_in = sum(len(jl.SYSTEM) + len(persona[items[k]['qid']]) + len(items[k]['notice']) + 20 for k, _ in todo) * 0.9
    est_out = len(todo) * OUT_TOKENS
    cost = est_in / 1e6 * jl.PRICE_IN + est_out / 1e6 * jl.PRICE_OUT
    print('쌍 %d · 호출 %d (이미 %d) · 모델 %s · prompt %s (judge_llm.py 와 같음)'
          % (len(items), len(todo), len(done), jl.JUDGE_MODEL, jl.PROMPT_SHA))
    print('예상 입력 약 %.2fM 토큰 · 출력 약 %.2fM 토큰 · 약 $%.2f (단가 입력 $%.2f·출력 $%.2f /1M, 추정)'
          % (est_in / 1e6, est_out / 1e6, cost, jl.PRICE_IN, jl.PRICE_OUT))
    if args.plan or not todo:
        if not todo:
            score(pack, items, hidden)
        return 0

    import openai
    from shared import config
    key = config.get('OPENAI_API_KEY')
    if not key:
        print('OPENAI_API_KEY 가 .env 에 없다')
        return 1
    client = openai.OpenAI(api_key=key)
    lock = threading.Lock()
    stats = {'in': 0, 'out': 0, 'ok': 0, 'fail': 0}

    def one(item_id, run):
        item = items[item_id]
        text = jl.prompt(run, persona[item['qid']], item['notice'])
        err = ''
        for attempt in range(6):
            try:
                r = client.chat.completions.create(
                    model=jl.JUDGE_MODEL, temperature=0,
                    messages=[{'role': 'system', 'content': jl.SYSTEM}, {'role': 'user', 'content': text}],
                    response_format={'type': 'json_schema', 'json_schema': jl.SCHEMA})
                data = json.loads(r.choices[0].message.content)
                return {'item_id': item_id, 'qid': item['qid'], 'run': run, 'topic_rel': data['topic_rel'],
                        'borderline': data['borderline'], 'support': data['support'], 'ignored': data['ignored'],
                        'reason': data['reason'], 'model': jl.JUDGE_MODEL, 'prompt_sha': jl.PROMPT_SHA,
                        'at': datetime.now(timezone.utc).isoformat(timespec='seconds')}, r.usage
            except Exception as exc:
                err = '%s: %s' % (type(exc).__name__, str(exc)[:200])
                time.sleep((10 if 'RateLimit' in err else 1) * 2 ** attempt)
        return {'item_id': item_id, 'run': run, 'topic_rel': 'err', 'error': err, 'prompt_sha': jl.PROMPT_SHA}, None

    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(one, k, run) for k, run in todo]
        for i, fut in enumerate(as_completed(futures), 1):
            row, usage = fut.result()
            with lock:
                common.append_jsonl(out_path, [row])
                if usage:
                    stats['in'] += usage.prompt_tokens
                    stats['out'] += usage.completion_tokens
                    stats['ok'] += 1
                else:
                    stats['fail'] += 1
            if i % 100 == 0 or i == len(futures):
                print('  %d/%d · 실패 %d · %.0f초' % (i, len(futures), stats['fail'], time.time() - started))
    real = stats['in'] / 1e6 * jl.PRICE_IN + stats['out'] / 1e6 * jl.PRICE_OUT
    print('완료 %d · 실패 %d · 입력 %d · 출력 %d 토큰 · 약 $%.3f' % (stats['ok'], stats['fail'], stats['in'], stats['out'], real))
    score(pack, items, hidden)
    return 0


if __name__ == '__main__':
    sys.exit(main())
