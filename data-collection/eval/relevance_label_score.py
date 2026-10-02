# -*- coding: utf-8 -*-
"""관련도 판정 꾸러미 채점 — Codex 가 쓴 labels.jsonl 을 검사하고 사람 대조군과 비교한다(2026-09-30).

  .\\.venv\\Scripts\\python.exe -X utf8 -m eval.relevance_label_score [꾸러미폴더이름]

- labels.jsonl 이 items.jsonl 의 모든 item_id 를 한 번씩, topic_rel 0·1·2·null 로 채웠는지 먼저 본다.
- 대조군(사람 판정 40쌍)과의 일치율·가중 카파, 라벨 분포를 score.json·score.md 로 쓴다.
- 대상 쌍(대조군 제외)을 qrels 에 넣을 줄(judge='codex')을 codex_qrels.jsonl 로 만든다. **qrels.jsonl 자체는 고치지 않는다**
  — 합칠지는 사용자가 채점 결과를 보고 정한다(eval/merge_qrels.py 로).
"""
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from eval import common  # noqa: E402

PACK = 'relevance_label_pack_20260930'


def weighted_kappa(pairs):
    """0·1·2 등급의 선형 가중 카파. pairs = [(사람, codex)]."""
    cats = (0, 1, 2)
    n = len(pairs)
    if not n:
        return None
    w = lambda a, b: 1 - abs(a - b) / 2
    po = sum(w(a, b) for a, b in pairs) / n
    pa = Counter(a for a, _ in pairs)
    pb = Counter(b for _, b in pairs)
    pe = sum(w(a, b) * pa[a] * pb[b] for a in cats for b in cats) / (n * n)
    return None if pe == 1 else (po - pe) / (1 - pe)


def main():
    pack = os.path.join(ROOT, 'reports', sys.argv[1] if len(sys.argv) > 1 else PACK)
    items = {r['item_id']: r for r in common.read_jsonl(os.path.join(pack, 'items.jsonl'))}
    hidden = {r['item_id']: r for r in common.read_jsonl(os.path.join(pack, 'answers_hidden.jsonl'))}
    path = os.path.join(pack, 'labels.jsonl')
    if not os.path.exists(path):
        sys.exit('labels.jsonl 이 없다: %s' % path)
    labels, problems = {}, []
    for i, row in enumerate(common.read_jsonl(path), 1):
        item_id = row.get('item_id')
        if item_id not in items:
            problems.append('%d행: 없는 item_id %r' % (i, item_id))
        elif item_id in labels:
            problems.append('%d행: 중복 item_id %s' % (i, item_id))
        elif row.get('topic_rel') not in (0, 1, 2, None) or 'topic_rel' not in row:
            problems.append('%d행: topic_rel 은 0·1·2·null 이어야 한다 (%r)' % (i, row.get('topic_rel')))
        else:
            labels[item_id] = row
    missing = sorted(set(items) - set(labels))
    if missing:
        problems.append('판정 없음 %d건: %s' % (len(missing), ', '.join(missing[:10])))
    if problems:
        sys.exit('labels.jsonl 검사 실패\n  ' + '\n  '.join(problems[:30]))

    ctrl = [(hidden[k]['human_topic_rel'], labels[k]['topic_rel']) for k in sorted(hidden) if hidden[k]['control']]
    judged = [(a, b) for a, b in ctrl if b is not None]
    exact = sum(a == b for a, b in judged) / len(judged) if judged else None
    within1 = sum(abs(a - b) <= 1 for a, b in judged) / len(judged) if judged else None
    # P@3(2) 에 쓰는 '2냐 아니냐' 로도 본다
    binary = sum((a == 2) == (b == 2) for a, b in judged) / len(judged) if judged else None
    confusion = Counter('%s→%s' % (a, 'null' if b is None else b) for a, b in ctrl)
    targets = [k for k in sorted(hidden) if not hidden[k]['control']]
    dist = Counter('null' if labels[k]['topic_rel'] is None else labels[k]['topic_rel'] for k in targets)
    score = {'pack': os.path.basename(pack), 'items': len(items), 'controls': len(ctrl),
             'controls_null': len(ctrl) - len(judged), 'exact': exact, 'within1': within1,
             'binary_2': binary, 'weighted_kappa': weighted_kappa(judged),
             'confusion_human_to_codex': dict(sorted(confusion.items())),
             'targets': len(targets), 'target_labels': dict(dist),
             'borderline': sum(1 for k in targets if labels[k].get('borderline'))}
    json.dump(score, open(os.path.join(pack, 'score.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    rows = [{'qid': hidden[k]['qid'], 'notice_id': hidden[k]['notice_id'], 'label_version': common.LABEL_VERSION,
             'topic_rel': labels[k]['topic_rel'], 'judge': 'codex', 'borderline': bool(labels[k].get('borderline')),
             'reason': labels[k].get('reason', ''), 'source_pack': os.path.basename(pack)}
            for k in targets if labels[k]['topic_rel'] is not None]
    common.write_jsonl(os.path.join(pack, 'codex_qrels.jsonl'), rows)

    fmt = lambda x: '-' if x is None else '%.2f' % x
    md = ['# 관련도 판정 꾸러미 채점 (%s)' % score['pack'], '',
          '- 사람 대조군 %d쌍 (Codex가 판단 불가로 둔 것 %d)' % (score['controls'], score['controls_null']),
          '- 정확 일치 **%s** · 한 등급 이내 %s · "2냐 아니냐" 일치 %s · 선형 가중 카파 %s'
          % (fmt(exact), fmt(within1), fmt(binary), fmt(score['weighted_kappa'])),
          '- 참고: 같은 사람 판정에 대한 LLM(gpt-4.1-mini) 일치 0.64, Jev 0.52 (9/28 기록, 143쌍 전체 기준이라 표본이 다르다)',
          '- 사람→Codex 혼동: ' + ', '.join('%s %d' % kv for kv in score['confusion_human_to_codex'].items()),
          '- 대상 %d쌍 라벨: %s · 경계 %d' % (len(targets), ', '.join('%s %d' % kv for kv in sorted(dist.items(), key=str)),
                                          score['borderline']),
          '- qrels 에 넣을 줄: `codex_qrels.jsonl` %d줄 (null 제외). qrels.jsonl 은 고치지 않았다.' % len(rows)]
    open(os.path.join(pack, 'score.md'), 'w', encoding='utf-8').write('\n'.join(md) + '\n')
    print('\n'.join(md))


if __name__ == '__main__':
    main()
