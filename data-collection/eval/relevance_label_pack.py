# -*- coding: utf-8 -*-
"""관련도 판정 꾸러미 — 평가 목록 상위 10의 미판정 쌍을 Codex 블라인드 판정용으로 묶는다(2026-09-30).

  .\\.venv\\Scripts\\python.exe -X utf8 -m eval.relevance_label_pack [결과폴더이름]

- 대상: `reports/<결과폴더>/results.json` 에서 지금 방식(filter_first)의 hybrid·dense 상위 10 중 qrels 에 없는 쌍,
  그리고 `reports/<후보비교폴더>/results.json`(eval/match_variants.py)의 모든 스위치 상위 10 중 qrels 에 없는 쌍.
  사용법: `-m eval.relevance_label_pack [결과폴더] [후보비교폴더]`
- 대조군: qrels 의 사람(human) 판정 40쌍을 정답을 숨겨 섞는다. Codex 판정이 사람과 얼마나 맞는지 잰다.
- 판정 기준은 eval/judge_llm.py 의 SYSTEM(topic-v2)과 같다. 공고 설명은 common.notice_text() 로 LLM 판정과 같게 만든다.
- 어느 방식이 몇 위로 올렸는지, 대조군인지는 꾸러미에 넣지 않는다(answers_hidden.jsonl 에만).
- 공용 DB 는 공고 글을 읽기만 한다. OpenAI 호출 없음.
"""
import json
import os
import random
import sys
from collections import Counter
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from eval import common  # noqa: E402

RESULTS = 'filter_first_eval_20260928T104212Z'
# 매칭 개선 후보 A·B·C(eval/match_variants.py)가 새로 올린 빈칸도 함께 넣는다(2026-09-30 사용자 결정)
VARIANTS = 'match_variants_20260930T010314Z'
SEED = 20260930
CONTROLS = {2: 14, 1: 13, 0: 13}          # 사람 판정 대조군 40쌍(라벨별)
OUT_NAME = 'relevance_label_pack_20260930'


def main():
    results = sys.argv[1] if len(sys.argv) > 1 else RESULTS
    variants = sys.argv[2] if len(sys.argv) > 2 else VARIANTS
    out = os.path.join(ROOT, 'reports', OUT_NAME)
    if os.path.exists(out):
        sys.exit('이미 있다: %s — 덮어쓰지 않는다' % out)
    data = json.load(open(os.path.join(ROOT, 'reports', results, 'results.json'), encoding='utf-8'))
    qrels = {(r['qid'], r['notice_id']): r for r in common.read_jsonl(os.path.join(HERE, 'qrels.jsonl'))}
    queries = common.load_queries()

    targets = {}
    for l in data['lists']:
        if l['system'] != 'filter_first' or l['mode'] not in ('hybrid', 'dense'):
            continue
        for notice_id in l['ranked'][:10]:
            if (l['qid'], notice_id) not in qrels:
                targets.setdefault((l['qid'], notice_id), set()).add(l['mode'])
    if variants:
        vdata = json.load(open(os.path.join(ROOT, 'reports', variants, 'results.json'), encoding='utf-8'))
        for l in vdata['lists']:
            for notice_id in l['ranked'][:10]:
                if (l['qid'], notice_id) not in qrels:
                    targets.setdefault((l['qid'], notice_id), set()).add('variant:' + l['variant'])

    rng = random.Random(SEED)
    human = [r for r in qrels.values() if r['judge'] == 'human' and r['qid'] in queries]
    controls = []
    for rel, n in CONTROLS.items():
        pool = sorted((r for r in human if r['topic_rel'] == rel), key=lambda r: (r['qid'], r['notice_id']))
        controls += rng.sample(pool, n)

    pairs = [(qid, nid, None) for qid, nid in sorted(targets)] + \
            [(r['qid'], r['notice_id'], r['topic_rel']) for r in controls]
    notices = common.load_notices({nid for _, nid, _ in pairs})
    missing = sorted({nid for _, nid, _ in pairs if nid not in notices})
    if missing:
        sys.exit('공고를 찾지 못했다: %s' % missing[:5])

    # 질의별로 모으고, 질의 안의 순서는 섞는다(순위·대조군 여부가 드러나지 않게)
    by_q = {}
    for p in pairs:
        by_q.setdefault(p[0], []).append(p)
    items, hidden = [], []
    for qid in sorted(by_q):
        group = by_q[qid]
        rng.shuffle(group)
        for _, nid, rel in group:
            item_id = 'r%03d' % (len(items) + 1)
            items.append({'item_id': item_id, 'qid': qid, 'notice': common.notice_text(notices[nid])})
            hidden.append({'item_id': item_id, 'qid': qid, 'notice_id': nid, 'control': rel is not None,
                           'human_topic_rel': rel,
                           'modes': sorted(targets.get((qid, nid), ()))})

    os.makedirs(out)
    common.write_jsonl(os.path.join(out, 'queries.jsonl'),
                       [{'qid': qid, 'persona': common.persona_text(queries[qid]['payload'])} for qid in sorted(by_q)])
    common.write_jsonl(os.path.join(out, 'items.jsonl'), items)
    common.write_jsonl(os.path.join(out, 'answers_hidden.jsonl'), hidden)
    meta = {'created_at': datetime.now(timezone.utc).isoformat(), 'results': results, 'seed': SEED,
            'variants': variants, 'label_version': common.LABEL_VERSION, 'queries': len(by_q), 'items': len(items),
            'targets': len(targets), 'controls': len(controls),
            'controls_by_label': dict(Counter(r['topic_rel'] for r in controls)),
            'targets_from_base': sum(1 for v in targets.values() if v & {'hybrid', 'dense'}),
            'targets_variant_only': sum(1 for v in targets.values() if not v & {'hybrid', 'dense'}),
            'notice_text': 'eval.common.notice_text (공용 DB 현재 글, 첨부 앞부분 %d자)' % common.ATTACH_CHARS,
            'db_writes': 0, 'openai_calls': 0}
    json.dump(meta, open(os.path.join(out, 'meta.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
