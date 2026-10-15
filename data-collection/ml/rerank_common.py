# -*- coding: utf-8 -*-
"""리랭커 학습과 평가가 같이 쓰는 것들.

학습할 때와 평가할 때 **공고를 똑같은 문장으로 만들어야** 한다. 한쪽만 바꾸면
점수가 달라지는데 원인을 찾기 어렵다. 그래서 그 규칙을 이 파일 한 곳에 둔다.

  import rerank_common as rc
  rc.notice_text(n)          공고 하나 → 리랭커에 넣을 문장
  rc.load_pairs('train')     학습용 (질의, 공고, 정답) 목록
  rc.Scorer(adapter=...)     점수 매기는 물건
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EVAL = os.path.join(ROOT, 'eval')

for p in (ROOT, EVAL):
    if p not in sys.path:
        sys.path.insert(0, p)

# ── 고정값. 바꾸면 학습과 평가 양쪽이 같이 바뀐다 ────────────
MODEL_NAME = 'BAAI/bge-reranker-v2-m3'   # 한국어를 아는 다국어 리랭커
MAX_LEN = 512                            # 질의+공고를 합쳐 이 길이로 자른다
NOTICE_BODY_CHARS = 900                  # 공고 본문에서 앞 몇 글자를 쓸지

ADAPTER_DIR = os.path.join(HERE, 'models', 'reranker_lora')


def read_jsonl(path):
    with io.open(path, encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()]


# ── 공고 → 문장 ─────────────────────────────────────────────
def notice_text(n):
    """공고 하나를 리랭커에 넣을 한 덩어리 문장으로 만든다.

    임베딩(embed.py)과 필드 구성이 다르다. 임베딩은 6필드 512토큰이지만
    리랭커는 질의와 함께 읽으므로 지원대상·기관까지 넣어 판단 근거를 늘린다.
    """
    parts = [
        n.get('title') or '',
        ' '.join(x for x in (n.get('category'), n.get('subcategory')) if x),
        n.get('target_category') or '',
        (n.get('target_text') or '')[:300],
        (n.get('body') or '')[:NOTICE_BODY_CHARS],
    ]
    text = ' '.join(' '.join(str(p).split()) for p in parts if p)
    return text.strip()


def load_notices(ids):
    """EC2 MySQL 에서 공고를 읽는다. 첨부 본문은 쓰지 않는다(길어서 잘린다)."""
    import common
    return common.load_notices(ids, with_attachment=False)


# ── 학습/평가 데이터 ────────────────────────────────────────
def load_splits():
    path = os.path.join(EVAL, 'splits.json')
    if not os.path.exists(path):
        raise SystemExit('eval/splits.json 이 없다. 01_dataset.ipynb 를 먼저 돌린다.')
    return json.load(io.open(path, encoding='utf-8'))


def load_qrels():
    """{qid: {notice_id: topic_rel}}. 판정이 없는(None) 것은 뺀다."""
    out = {}
    for r in read_jsonl(os.path.join(EVAL, 'qrels.jsonl')):
        if r.get('topic_rel') is None:
            continue
        out.setdefault(r['qid'], {})[r['notice_id']] = int(r['topic_rel'])
    return out


def load_queries():
    import common
    return common.load_queries()


def query_text(q):
    import common
    return common.query_text(q)


def load_pairs(split='train'):
    """[(질의문장, 공고문장, 정답점수)]. 정답은 0.0 / 0.5 / 1.0 으로 바꾼다.

    관련도 2(딱 맞음)=1.0 · 1(걸침)=0.5 · 0(무관)=0.0 이다.
    리랭커가 0~1 점수를 내도록 가르치기 위해서다.
    """
    splits = load_splits()
    if split not in ('train', 'test'):
        raise ValueError("split 은 'train' 또는 'test'")
    want = set(splits[split])

    queries = load_queries()
    qrels = load_qrels()

    need = {n for qid in want for n in qrels.get(qid, {})}
    notices = load_notices(need)

    pairs = []
    for qid in sorted(want):
        q = queries.get(qid)
        if q is None:
            continue
        qt = query_text(q)
        for nid, rel in sorted(qrels.get(qid, {}).items()):
            n = notices.get(nid)
            if not n:
                continue          # DB 에서 사라진 공고는 건너뛴다
            pairs.append((qt, notice_text(n), rel / 2.0, qid, nid))
    return pairs


# ── 점수 매기는 물건 ────────────────────────────────────────
class Scorer:
    """질의와 공고를 같이 읽고 0~1 점수를 낸다.

      s = Scorer()                       사전학습 그대로
      s = Scorer(adapter=ADAPTER_DIR)    우리가 학습시킨 것
      s.score(질의문장, [공고문장, ...])  →  [점수, ...]
    """

    def __init__(self, adapter=None, device=None, batch_size=16, max_len=None):
        import torch
        from transformers import AutoTokenizer, AutoModelForSequenceClassification

        self.torch = torch
        self.batch_size = batch_size
        self.max_len = max_len or MAX_LEN
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')

        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME, num_labels=1)

        if adapter:
            if not os.path.exists(adapter):
                raise SystemExit('학습한 모델이 없다: %s — 04_reranker_train.py 를 먼저 돌린다.' % adapter)
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, adapter)
            model = model.merge_and_unload()     # 합쳐두면 추론이 빠르다

        self.model = model.to(self.device).eval()

    def score(self, query, notice_texts):
        torch = self.torch
        out = []
        with torch.no_grad():
            for i in range(0, len(notice_texts), self.batch_size):
                chunk = notice_texts[i:i + self.batch_size]
                enc = self.tokenizer([query] * len(chunk), chunk,
                                     padding=True, truncation=True,
                                     max_length=self.max_len, return_tensors='pt').to(self.device)
                logits = self.model(**enc).logits.view(-1).float()
                out += torch.sigmoid(logits).cpu().tolist()
        return out
