# -*- coding: utf-8 -*-
"""공고 요약 임베딩 생성.

  python embed.py --plan            만들 대상만 세어 본다
  python embed.py --limit 20        20건만
  python embed.py                   전량
  python embed.py --out vecs.npz    파일로 저장 (DB 컬럼이 생기기 전까지)

**임베딩 입력은 `match.notice_text()` 와 다르다.** 그쪽은 8필드이고 TF-IDF·기존 실험이
쓰고 있어 조용히 바꾸지 않는다. 여기는 6필드 전용 계약이며 `INPUT_VERSION` 으로 고정한다.

정형 필터 → 유사도 순서는 이 파일이 정하지 않는다. 여기는 벡터를 만들 뿐이다.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import store_mysql

MODEL = 'BAAI/bge-m3'
MAX_TOKENS = 512
DIM = 1024

# 입력 계약 — 이 여섯 필드를 이 순서로, 개행으로 잇는다.
FIELDS = ('title', 'body', 'target_text', 'target_category', 'category', 'subcategory')
INPUT_VERSION = 'v1:' + '+'.join(FIELDS)

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(HERE, 'data', 'embeddings_v1.npz')


def build_input(row):
    """공고 하나의 임베딩 입력을 만든다. **이 함수가 유일한 정의다.**

    - 필드 순서는 FIELDS 고정
    - NULL 과 빈 문자열은 건너뛴다 (빈 줄을 남기지 않는다)
    - 각 필드 안의 연속 공백은 한 칸으로, 앞뒤 공백은 제거
    - 필드 사이는 개행 하나
    """
    parts = []
    for name in FIELDS:
        value = row.get(name)
        if value is None:
            continue
        text = ' '.join(str(value).split())
        if text:
            parts.append(text)
    return '\n'.join(parts)


def input_sha256(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def resolved_revision():
    """로컬 캐시에 실제로 받아진 리비전. 이름만으로는 모델이 고정되지 않는다."""
    try:
        from huggingface_hub import HfApi  # noqa: F401
        from transformers.utils import TRANSFORMERS_CACHE  # noqa: F401
    except Exception:
        pass
    base = os.path.expanduser('~/.cache/huggingface/hub/models--BAAI--bge-m3/refs/main')
    try:
        with open(base, encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return None


def meta(truncated=False, original_tokens=None):
    info = {'model': MODEL, 'revision': resolved_revision(),
            'input_version': INPUT_VERSION, 'max_tokens': MAX_TOKENS,
            'dim': DIM, 'dtype': 'float32', 'normalized': True,
            'byte_order': 'little'}
    if truncated:
        info['truncated'] = True
        info['original_tokens'] = original_tokens
    return info


def fingerprint():
    """설정 묶음 하나로 요약. 이 값이 다르면 다시 만들어야 한다."""
    base = meta()
    keys = ('model', 'revision', 'input_version', 'max_tokens', 'dim', 'dtype', 'normalized')
    blob = json.dumps({k: base[k] for k in keys}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def load_rows(connection):
    columns = ('notice_id',) + FIELDS
    with connection.cursor() as cursor:
        cursor.execute('SELECT ' + ','.join(columns) + ' FROM notices ORDER BY notice_id')
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def encode(texts, say=print):
    """길이 초과는 앞부분만 쓰고 그 사실을 돌려준다."""
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    from sentence_transformers import SentenceTransformer
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(MODEL)
    counts = [len(tokenizer(t, add_special_tokens=True)['input_ids']) for t in texts]
    over = [i for i, n in enumerate(counts) if n > MAX_TOKENS]
    if over:
        say('  %d건이 %d토큰을 넘어 앞부분만 쓴다 (최대 %d토큰)'
            % (len(over), MAX_TOKENS, max(counts)))

    say('  모델 로딩...')
    model = SentenceTransformer(MODEL)
    model.max_seq_length = MAX_TOKENS
    vectors = model.encode(texts, batch_size=4, normalize_embeddings=True,
                           show_progress_bar=True)
    return vectors, counts, set(over)


def load_existing(path=DEFAULT_OUT):
    """이미 만들어둔 벡터. {notice_id: (입력해시, 벡터)} 와 설정 지문."""
    import numpy as np
    if not os.path.exists(path):
        return {}, None
    data = np.load(path, allow_pickle=False)
    kept = {}
    for nid, sha, vec in zip(data['notice_ids'], data['input_sha256'], data['vectors']):
        kept[str(nid)] = (str(sha), vec)
    try:
        old_meta = json.loads(str(data['meta']))
        keys = ('model', 'revision', 'input_version', 'max_tokens',
                'dim', 'dtype', 'normalized')
        blob = json.dumps({k: old_meta.get(k) for k in keys},
                          ensure_ascii=False, sort_keys=True)
        old_fp = hashlib.sha256(blob.encode()).hexdigest()[:16]
    except Exception:
        old_fp = None
    return kept, old_fp


def plan(rows, existing, old_fingerprint):
    """(만들 것, 그대로 둘 것). 세 경우에 다시 만든다.

    ① 벡터가 없다            새 공고
    ② 입력 해시가 다르다      공고 내용이 바뀌었다
    ③ 설정이 다르다          모델·리비전·입력구성·토큰상한이 바뀌었다
                            이때는 전부 다시 만든다
    """
    setting_changed = old_fingerprint is not None and old_fingerprint != fingerprint()
    todo, keep = [], {}
    for row in rows:
        text = build_input(row)
        if not text:
            continue
        nid = row['notice_id']
        sha = input_sha256(text)
        found = existing.get(nid)
        if setting_changed or found is None or found[0] != sha:
            todo.append({'notice_id': nid, 'text': text, 'sha': sha})
        else:
            keep[nid] = found
    return todo, keep, setting_changed


def run(limit=None, plan_only=False, out=DEFAULT_OUT, say=print):
    connection = store_mysql.connect()
    try:
        rows = load_rows(connection)
    finally:
        connection.close()

    existing, old_fp = load_existing(out)
    todo, keep, setting_changed = plan(rows, existing, old_fp)

    say('공고 %d건 · 기존 벡터 %d건 · 설정 %s' % (len(rows), len(existing), fingerprint()))
    if setting_changed:
        say('  설정이 바뀌었다(%s → %s). 전부 다시 만든다.' % (old_fp, fingerprint()))
    say('  그대로 %d건 · 만들 것 %d건' % (len(keep), len(todo)))

    if plan_only:
        return {'total': len(rows), 'kept': len(keep), 'todo': len(todo)}
    if limit:
        todo = todo[:limit]
    if not todo:
        say('  만들 것이 없다.')
        return {'total': len(rows), 'kept': len(keep), 'todo': 0,
                'made': 0, 'out': out}

    import numpy as np
    vectors, counts, over = encode([i['text'] for i in todo], say=say)
    vectors = np.asarray(vectors, dtype='float32')
    if vectors.shape[1] != DIM:
        raise ValueError('차원이 %d 가 아니다: %d' % (DIM, vectors.shape[1]))
    if not np.isfinite(vectors).all():
        raise ValueError('NaN 또는 Inf 가 섞였다')

    # 새로 만든 것과 그대로 둔 것을 합친다. 공고번호 순으로 고정한다.
    merged = dict(keep)
    for item, vec in zip(todo, vectors):
        merged[item['notice_id']] = (item['sha'], vec)
    ids = sorted(merged)

    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + '.tmp.npz'
    np.savez_compressed(
        tmp,
        vectors=np.asarray([merged[i][1] for i in ids], dtype='float32'),
        notice_ids=np.array(ids),
        input_sha256=np.array([merged[i][0] for i in ids]),
        meta=np.array(json.dumps(meta(), ensure_ascii=False)),
        generated_at=np.array(datetime.now(timezone.utc).isoformat()))
    os.replace(tmp, out)      # 중간에 끊겨도 반쯤 쓰다 만 파일이 남지 않는다

    say('저장 %s · 전체 %d건 (새로 만든 것 %d건)' % (out, len(ids), len(todo)))
    return {'total': len(rows), 'kept': len(keep), 'todo': len(todo),
            'made': len(todo), 'truncated': len(over), 'out': out,
            'changed_ids': [i['notice_id'] for i in todo]}


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('--out', default=DEFAULT_OUT)
    args = parser.parse_args()
    run(limit=args.limit, plan_only=args.plan, out=args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
