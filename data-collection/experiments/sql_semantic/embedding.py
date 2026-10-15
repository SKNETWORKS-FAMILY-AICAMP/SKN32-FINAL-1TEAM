# -*- coding: utf-8 -*-
"""새 임베딩 입력 계약과 벡터 저장 규약.

기존 계약(`shared/embed.py`, 6필드)은 **건드리지 않는다.** 이건 별도 버전이다.

  새 계약 순서 : 제목 → 지원 분야/목적 → 지원 내용 → 신청 자격

각 조각의 출처와 대체 규칙을 남긴다. 공고 데이터에 '지원 내용' 칸이 따로 없어서,
없으면 본문을 쓰고 그 사실을 `sources` 에 적는다. 없는 내용을 지어내지 않는다.
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CONTRACT = 'sql_lab_v1:title+purpose+content+eligibility'
MODEL = 'BAAI/bge-m3'
MAX_TOKENS = 512
DIM = 1024
DTYPE = 'float32'
NORMALIZED = True

LABELS = ('제목', '지원 분야', '지원 내용', '신청 자격')


def build_input(notice):
    """(텍스트, 출처 설명). 빈 조각은 넣지 않는다."""
    title = (notice.get('title') or '').strip()
    purpose = ' · '.join(p for p in [(notice.get('category') or '').strip(),
                                     (notice.get('subcategory') or '').strip()] if p)
    content = (notice.get('body') or '').strip()
    eligibility = ((notice.get('target_text') or '').strip()
                   or (notice.get('target_category') or '').strip())

    sources = {
        '제목': 'title',
        '지원 분야': 'category+subcategory' if purpose else '(없음)',
        # 공고 데이터에 '지원 내용' 칸이 따로 없다. 본문을 대신 쓴다는 사실을 남긴다
        '지원 내용': 'body (별도 지원내용 칸이 없어 본문 사용)' if content else '(없음)',
        '신청 자격': ('target_text' if (notice.get('target_text') or '').strip()
                      else ('target_category (target_text 없음)' if eligibility else '(없음)')),
    }
    parts = []
    for label, value in zip(LABELS, (title, purpose, content, eligibility)):
        value = ' '.join(str(value).split())
        if value:
            parts.append('%s: %s' % (label, value))
    return '\n'.join(parts), sources


def input_sha256(text):
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()


def pack(vector):
    """float32 리틀엔디언 바이트로 저장한다. 차원은 따로 칸에 적는다."""
    import numpy as np
    array = np.asarray(vector, dtype='<f4')
    if array.ndim != 1:
        raise ValueError('1차원 벡터만 저장한다')
    return array.tobytes()


def unpack(blob, dim):
    """저장한 바이트 → 벡터. 길이·유한값을 검사한다. 이상하면 예외를 던진다."""
    import numpy as np
    array = np.frombuffer(blob, dtype='<f4')
    if array.size != dim:
        raise ValueError('벡터 길이가 다르다: 저장 %d · 기대 %d' % (array.size, dim))
    if not np.all(np.isfinite(array)):
        raise ValueError('벡터에 NaN/Inf 가 있다')
    return array.astype('float32')


def model_revision():
    """로컬 캐시에 실제로 받아진 리비전. 이름만으로는 모델이 고정되지 않는다."""
    try:
        from shared import embed
        return embed.resolved_revision()
    except Exception:
        return None


_TOKENIZER = [None]


def tokenizer():
    """토크나이저는 한 번만 올린다. 캐시에 없으면 예외가 그대로 올라간다."""
    if _TOKENIZER[0] is None:
        os.environ.setdefault('HF_HUB_OFFLINE', '1')
        from transformers import AutoTokenizer
        _TOKENIZER[0] = AutoTokenizer.from_pretrained(MODEL)
    return _TOKENIZER[0]


def token_info(text):
    """(토큰 수, 잘렸는지). 상한을 넘으면 앞부분만 임베딩되므로 그 사실을 남긴다.

    처음에는 `truncated=0` 을 상수로 넣었다. 본문이 길면 뒤에 붙인 '신청 자격' 이
    임베딩에 안 들어갔을 수 있는데 기록만 보면 알 수 없었다(2026-09-18 Codex 리뷰 5번).
    """
    ids = tokenizer()(text, add_special_tokens=True)['input_ids']
    count = len(ids)
    return count, count > MAX_TOKENS


def load_model():
    """캐시에 있는 BGE-M3 를 쓴다. 없으면 환경 장애로 보고한다(내려받지 않는다)."""
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL)
    model.max_seq_length = MAX_TOKENS
    return model


def encode(model, texts, batch_size=4):
    import numpy as np
    vectors = model.encode(list(texts), batch_size=batch_size,
                           normalize_embeddings=NORMALIZED, show_progress_bar=False)
    return np.asarray(vectors, dtype='float32')


def cosine(query, matrix):
    """정규화된 벡터라 내적이 코사인이다. 그래도 노름을 확인해 다르면 나눠 준다."""
    import numpy as np
    q = np.asarray(query, dtype='float32')
    m = np.asarray(matrix, dtype='float32')
    qn = float(np.linalg.norm(q)) or 1.0
    mn = np.linalg.norm(m, axis=1)
    mn[mn == 0] = 1.0
    return (m @ q) / (mn * qn)


def meta():
    return {'contract': CONTRACT, 'model': MODEL, 'model_revision': model_revision(),
            'dim': DIM, 'dtype': DTYPE, 'normalized': NORMALIZED, 'max_tokens': MAX_TOKENS}
