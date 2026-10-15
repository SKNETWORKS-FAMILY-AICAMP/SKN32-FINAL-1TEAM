# -*- coding: utf-8 -*-
"""평가셋 사람 판정 화면. **내부 검토 전용** — 서비스 배포 대상이 아니다.

  python -X utf8 eval/label_app.py            http://127.0.0.1:8001

모드 세 가지 (화면 상단에서 고른다)

  blind    블라인드 표본 150쌍. LLM 판정을 **보여주지 않는다.** 먼저 한다.
           여기서 사람–LLM 일치율을 재고, LLM 판정을 믿어도 되는지 정한다.
  recheck  판정 기준(LABEL_VERSION)을 바꾼 뒤, 옛 기준으로 한 블라인드 판정을 새 기준으로
           다시 본다. LLM 과 갈린 쌍 + 일치한 쌍 일부를 섞어 내고 LLM 답·이전 판정은 숨긴다.
           표본은 recheck.json 에 한 번 고정한다.
  review   LLM 판정이 흔들린 쌍만. LLM 답과 이유를 보여준다.
           (A/B 불일치 · null · low · topic_rel=1 · 현재 검색 상위 3 · 무관 질의의 1 이상)
  query    질의 하나를 골라 후보 전부. 첫 10질의로 기준 맞출 때 쓴다.

어느 모드에서도 검색 순위·점수·후보를 낸 시스템은 보여주지 않는다.
판정은 human_judgments.jsonl 에 덧붙인다. 같은 쌍을 다시 판정하면 마지막 것이 쓰인다.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

app = FastAPI(title='평가셋 판정 (내부용)')
S = {}


def llm_latest():
    """{(qid, nid): {'A': row, 'B': row}} — 현재 프롬프트의 쌍·run 별 마지막 정상 판정."""
    from judge_llm import PROMPT_SHA
    out = {}
    for j in common.read_jsonl(common.LLM):
        if j.get('topic_rel') == 'err' or j.get('prompt_sha') != PROMPT_SHA:
            continue
        out.setdefault((j['qid'], j['notice_id']), {})[j['run']] = j
    return out


def human_latest():
    """{(qid, nid, mode): row}. mode = blind / recheck / review"""
    out = {}
    for h in common.read_jsonl(common.HUMAN):
        out[(h['qid'], h['notice_id'], h['mode'])] = h
    return out


def seen(human, qid, nid):
    return any((qid, nid, m) in human for m in ('blind', 'recheck', 'review'))


def ensure_recheck():
    """재확인 표본을 한 번만 만들어 파일로 고정한다. 다시 만들면 표본이 바뀐다."""
    import json
    if os.path.exists(common.RECHECK):
        with open(common.RECHECK, encoding='utf-8') as f:
            return {tuple(k) for k in json.load(f)['pairs']}
    human = {(h['qid'], h['notice_id']): h['topic_rel']
             for h in common.read_jsonl(common.HUMAN)
             if h['mode'] == 'blind' and h.get('label_version') != common.LABEL_VERSION}
    if not human:
        return set()                     # 기준이 바뀐 적 없으면 재확인할 것도 없다
    llm = {k: v['A']['topic_rel'] for k, v in llm_latest().items() if 'A' in v}
    sample = common.recheck_sample(human, llm)
    with open(common.RECHECK, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(sample, f, ensure_ascii=False, indent=1)
    print('재확인 표본 생성: 갈린 쌍 %d + 일치 쌍 %d' % (sample['differ'], sample['agree_sampled']))
    return {tuple(k) for k in sample['pairs']}


def needs_review(p, llm, queries):
    """검수 대기열에 올릴 이유 목록. 비어 있으면 LLM 판정을 그대로 쓴다."""
    runs = llm.get((p['qid'], p['notice_id']), {})
    why = []
    if len(runs) < 2:
        why.append('LLM 판정 없음')
        return why
    a, b = runs['A'], runs['B']
    if a['topic_rel'] != b['topic_rel']:
        why.append('A/B 불일치')
    if a['topic_rel'] is None or b['topic_rel'] is None:
        why.append('판단 불가')
    if a.get('borderline') or b.get('borderline'):
        why.append('경계 사례')
    if 1 in (a['topic_rel'], b['topic_rel']):
        why.append('부분 관련')
    if p.get('dense_rank') and p['dense_rank'] <= 3:
        why.append('현재 상위 3')
    if queries[p['qid']]['kind'] == 'negative' and (a['topic_rel'] or 0) + (b['topic_rel'] or 0) > 0:
        why.append('무관 질의인데 관련')
    return why


def load():
    S['queries'] = common.load_queries()
    S['snap'] = common.load_snapshot()
    S['pool'] = common.read_jsonl(common.POOL)
    S['blind'] = common.blind_sample(S['pool'])
    S['recheck'] = ensure_recheck()


def queue(mode, qid=None):
    import random
    llm = llm_latest()
    human = human_latest()
    items = []
    pool = sorted(S['pool'], key=lambda p: (p['qid'], p['order']))
    if mode == 'recheck':
        # 질의 순으로 나오면 앞뒤 판정이 서로 끌려간다. 섞어서 낸다.
        random.Random(common.BLIND_SEED + 3).shuffle(pool)
    for p in pool:
        key = (p['qid'], p['notice_id'])
        if mode == 'blind':
            if key not in S['blind']:
                continue
            done = (p['qid'], p['notice_id'], 'blind') in human
            why = []
        elif mode == 'recheck':
            if key not in S['recheck']:
                continue
            done = (p['qid'], p['notice_id'], 'recheck') in human
            why = []
        elif mode == 'review':
            why = needs_review(p, llm, S['queries'])
            if not why:
                continue
            # 블라인드·재확인에서 이미 사람이 본 쌍은 다시 묻지 않는다
            done = seen(human, *key)
        else:
            if p['qid'] != qid:
                continue
            why = []
            done = seen(human, *key)
        items.append((p, why, done))
    return items, llm, human


@app.get('/api/status')
def status():
    out = {}
    for mode in ('blind', 'recheck', 'review'):
        items, _, _ = queue(mode)
        out[mode] = {'total': len(items), 'done': sum(1 for _, _, d in items if d)}
    human = human_latest()
    out['label_version'] = common.LABEL_VERSION
    out['queries'] = [{'qid': qid, 'idea': q['payload']['idea'][:40], 'kind': q['kind'],
                       'total': sum(1 for p in S['pool'] if p['qid'] == qid),
                       'done': sum(1 for p in S['pool'] if p['qid'] == qid
                                   and seen(human, qid, p['notice_id']))}
                      for qid, q in S['queries'].items()]
    return out


@app.get('/api/next')
def next_item(mode: str = 'blind', qid: str = '', skip: int = 0):
    items, llm, human = queue(mode, qid or None)
    todo = [x for x in items if not x[2]]
    if not todo:
        return {'empty': True, 'total': len(items)}
    p, why, _ = todo[min(skip, len(todo) - 1)]
    q = S['queries'][p['qid']]
    n = S['snap'][p['notice_id']]
    item = {
        'empty': False, 'total': len(items), 'left': len(todo),
        'qid': p['qid'], 'notice_id': p['notice_id'], 'kind': q['kind'],
        'persona': common.persona_text(q['payload']),
        'query_text': common.query_text(q),
        'notice': {k: n.get(k) for k in ('title', 'organizer', 'supervising_org', 'executing_org',
                                         'category', 'subcategory', 'target_category', 'body',
                                         'target_text', 'attachment_excerpt', 'url', 'apply_url')},
        'why': why,
    }
    # 블라인드·재확인에서는 LLM 답도, 사람의 이전 판정도 내보내지 않는다
    if mode not in ('blind', 'recheck'):
        runs = llm.get((p['qid'], p['notice_id']), {})
        item['llm'] = [{'run': r, 'topic_rel': j['topic_rel'], 'borderline': j.get('borderline'),
                        'support': j.get('support'), 'ignored': j.get('ignored'),
                        'reason': j['reason']} for r, j in sorted(runs.items())]
        prev = (human.get((p['qid'], p['notice_id'], 'review'))
                or human.get((p['qid'], p['notice_id'], 'recheck'))
                or human.get((p['qid'], p['notice_id'], 'blind')))
        item['previous'] = prev and {'topic_rel': prev['topic_rel'], 'reason': prev.get('reason')}
    return item


class Label(BaseModel):
    qid: str
    notice_id: str
    topic_rel: int | None
    mode: str
    reviewer: str = ''
    reason: str = ''


@app.post('/api/label')
def label(x: Label):
    if x.topic_rel not in (0, 1, 2, None):
        return {'ok': False, 'error': 'topic_rel 은 0·1·2·null'}
    if x.mode not in ('blind', 'recheck', 'review'):
        return {'ok': False, 'error': 'mode 는 blind·recheck·review'}
    common.append_jsonl(common.HUMAN, [{
        'qid': x.qid, 'notice_id': x.notice_id, 'topic_rel': x.topic_rel,
        'judge': 'human', 'reviewer': x.reviewer.strip(), 'mode': x.mode,
        'reason': x.reason.strip(), 'label_version': common.LABEL_VERSION,
        'at': datetime.now(timezone.utc).isoformat(timespec='seconds')}])
    return {'ok': True}


@app.get('/', response_class=HTMLResponse)
def index():
    with open(os.path.join(common.EVAL_DIR, 'label.html'), encoding='utf-8') as f:
        return f.read()


def main():
    import uvicorn
    load()
    print('질의 %d · 풀 %d쌍 · 블라인드 %d쌍' % (len(S['queries']), len(S['pool']), len(S['blind'])))
    print('열기: http://127.0.0.1:8001')
    uvicorn.run(app, host='127.0.0.1', port=8001, log_level='warning')


if __name__ == '__main__':
    main()
