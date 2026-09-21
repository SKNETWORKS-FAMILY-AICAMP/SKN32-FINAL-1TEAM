# -*- coding: utf-8 -*-
"""Chroma 에 들어 있는 **실제 벡터**가 벡터 파일(NPZ)·DB 공고와 맞는지 확인한다. 읽기 전용.

  python -X utf8 eval/chroma_integrity.py              검사만 하고 끝낸다 (검색 없음)
  python -X utf8 eval/search_comparison.py --check-only   같은 검사 (비교 도구 진입점)

지시서: docs/CHROMA_INTEGRITY_TASK_20260918.md

무엇을 대조하나

  DB 공고(현재 내용의 입력 해시)  ─①─  NPZ(벡터를 만든 입력 해시)  ─②─  Chroma(실제 벡터)
                                                  └──────────③ 메타데이터 ──────────┘

  ① 기존 data_check 와 같다. 공고 ID 집합과 공고별 입력 해시.
  ② 같은 ID 의 NPZ 벡터와 Chroma 벡터를 **원소 단위**로 맞춘다. 반환 순서에 기대지 않는다.
     코사인 하나로 판정하지 않는다 — 서로 다른 벡터도 코사인이 높을 수 있다.
  ③ Chroma 컬렉션의 embed_meta · NPZ meta · 지금 로컬 임베딩 설정.

판정은 세 가지다: 통과 / 불일치 / 확인 실패. 빈 결과나 예외를 통과로 바꾸지 않는다.

**원본 Chroma 를 열지 않는다.** chromadb 는 PersistentClient 로 열기만 해도 chroma.sqlite3 를 건드린다
(2026-09-21 실제로 수정 시각이 바뀌는 것을 확인). 그래서 폴더를 임시 위치로 복사해 사본을 연다.
원본은 파일 해시만 계산한다. DB 는 SELECT 만 한다. 색인·벡터 파일·DB 를 고치거나 다시 만들지 않는다.
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

ROOT = common.ROOT
REPORTS = os.path.join(ROOT, 'reports')
WATERMARK = '__watermark__'

PASS, MISMATCH, UNVERIFIED = '통과', '불일치', '확인 실패'
EXIT = {PASS: 0, MISMATCH: 2, UNVERIFIED: 4}

# ── 수치 비교 기준 — 결과를 보기 전에 정했다 ────────────────────────────────
# build_chroma 는 float32 배열을 .tolist() 로 넘긴다(float32 → 파이썬 float 는 정확한 변환).
# 허용 오차 1e-6 은 float32 반올림 몇 번(|x|≤1 에서 1회 약 6e-8)보다 크고, 정규화된 1024차원 벡터의
# 원소 크기(대략 0.03)나 다른 공고 벡터와의 차이(1e-3 이상)보다 훨씬 작다.
# 실제 실패를 통과시키려고 넓히지 않는다. 바이트 일치 건수는 따로 센다.
#
# 2026-09-21 첫 실행에서 알게 된 것 (허용 오차는 바꾸지 않았다):
#   처음에는 "왕복은 비트 단위로 같아야 정상" 이라고 적었는데 틀렸다. 2,328건 중 552건이 비트로는 달랐고,
#   **552건 모두 NPZ 벡터를 길이 1로 다시 나누면 Chroma 값과 같았다**(최대 차이 1.5e-8).
#   코사인 공간 색인은 저장할 때 벡터를 다시 정규화한다. NPZ 벡터의 길이는 float32 오차로 1±1e-7 이라
#   다시 나누면 마지막 자리가 바뀐다. 그래서 이 경우를 '재정규화 일치' 로 따로 센다.
TOLERANCE = {
    'dtype': 'float32',
    'atol': 1e-6,
    'rtol': 0.0,
    'why': 'float32 → .tolist() → Chroma float32 왕복. 코사인 색인의 재정규화로 마지막 자리가 바뀔 수 있다 '
           '(관측 최대 1.5e-8). 1e-6 은 그보다 크고 서로 다른 벡터의 차이(1e-3 이상)보다 훨씬 작다.',
}

# 벡터의 의미를 바꾸는 메타데이터 칸
META_FIELDS = ('model', 'revision', 'input_version', 'max_tokens', 'dim', 'dtype',
               'normalized', 'byte_order')


# ─────────────────────────────────────────────────────────────── 식별 해시

def vector_set_sha256(ids, vectors):
    """벡터 집합 해시. ID 를 정렬하고, 각 줄을 `ID(utf-8) + 0x00 + float32 리틀엔디언 바이트` 로 잇는다.

    바이트 일치 확인용이다. 허용 오차 기반 일치와 섞어 쓰지 않는다.
    """
    import numpy as np
    order = sorted(range(len(ids)), key=lambda i: ids[i])
    h = hashlib.sha256()
    for i in order:
        h.update(str(ids[i]).encode('utf-8') + b'\x00')
        h.update(np.asarray(vectors[i], dtype='<f4').tobytes())
    return h.hexdigest()


def file_sha256(path):
    h = hashlib.sha256()
    with io.open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def folder_fingerprint(path):
    """폴더 안 모든 파일의 (상대경로, 크기, sha256). 검사 전후 비교로 변경을 감지한다."""
    out = {}
    for base, _dirs, files in os.walk(path):
        for name in sorted(files):
            full = os.path.join(base, name)
            rel = os.path.relpath(full, path).replace('\\', '/')
            out[rel] = {'bytes': os.path.getsize(full), 'sha256': file_sha256(full)}
    return out


# ─────────────────────────────────────────────────────────────── ② 벡터 대조

def compare_vectors(npz_ids, npz_vectors, chroma_ids, chroma_vectors, dim, atol=TOLERANCE['atol']):
    """NPZ 와 Chroma 의 벡터를 ID 로 맞춰 원소 단위로 비교한다.

    반환 dict 의 `status` 는 PASS / MISMATCH / UNVERIFIED 중 하나다.
      · ID 와 벡터 배열 길이가 다르면 대응을 믿을 수 없다 → 확인 실패
      · 중복 ID·추가/누락 ID·벡터 없음·차원 오류·NaN/Inf·값 차이 → 불일치
    """
    import numpy as np
    out = {'tolerance': TOLERANCE, 'expected_dim': dim}
    if len(chroma_ids) != len(chroma_vectors):
        out.update(status=UNVERIFIED,
                   reason='Chroma ID %d개와 벡터 %d개의 길이가 다르다'
                          % (len(chroma_ids), len(chroma_vectors)))
        return out
    if len(npz_ids) != len(npz_vectors):
        out.update(status=UNVERIFIED,
                   reason='NPZ ID %d개와 벡터 %d개의 길이가 다르다' % (len(npz_ids), len(npz_vectors)))
        return out

    def duplicates(ids):
        seen, dup = set(), set()
        for i in ids:
            (dup if i in seen else seen).add(i)
        return sorted(dup)

    def validate(pairs):
        """(ID, 벡터) → (정상 벡터 dict, 이상 목록). **양쪽 모두** 이 검사를 거친 뒤에만 비교한다.

        처음에는 Chroma 쪽만 검사했다. NPZ 에 NaN 이 있으면 차이도 NaN 이 되고 `NaN > 허용치` 가
        거짓이라 **통과**로 나왔다(2026-09-21 Codex 리뷰 P1). 차원이 틀리면 뺄셈에서 예외가 났다.
        """
        good, bad = {}, []
        for i, v in pairs:
            if v is None:
                bad.append({'notice_id': i, 'problem': '벡터 없음'})
                continue
            try:
                arr = np.asarray(v, dtype='float64')
            except (TypeError, ValueError) as exc:
                bad.append({'notice_id': i, 'problem': '숫자 배열이 아니다 (%s)' % type(exc).__name__})
                continue
            if arr.ndim != 1 or arr.size != dim:
                bad.append({'notice_id': i, 'problem': '차원 %s (기대 %d)' % (arr.shape, dim)})
                continue
            if not np.all(np.isfinite(arr)):
                bad.append({'notice_id': i, 'problem': 'NaN/Inf 포함'})
                continue
            good[i] = arr
        return good, bad

    npz_dup, chroma_dup = duplicates(npz_ids), duplicates(chroma_ids)
    npz_map, npz_broken = validate(zip(npz_ids, npz_vectors))
    chroma_map, broken = validate(zip(chroma_ids, chroma_vectors))

    only_npz = sorted(set(npz_ids) - set(chroma_ids))
    only_chroma = sorted(set(chroma_ids) - set(npz_ids))
    common_ids = sorted(set(npz_map) & set(chroma_map))

    mismatched, byte_equal, renorm_equal, max_abs = [], 0, 0, 0.0
    for i in common_ids:
        a = npz_map[i].astype('float32')
        b = chroma_map[i].astype('float32')
        diff = float(np.max(np.abs(a.astype('float64') - b.astype('float64'))))
        max_abs = max(max_abs, diff)
        if not diff <= atol:              # NaN 이 끼어도 통과로 새지 않게 '이하가 아니면' 으로 쓴다
            cosine = float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) or 1.0))
            mismatched.append({'notice_id': i, 'max_abs_diff': diff, 'cosine': cosine})
        if a.tobytes() == b.tobytes():
            byte_equal += 1
        elif diff <= atol:
            # 판정에는 쓰지 않는다. 비트가 다른 이유를 설명하기 위한 분류다
            norm = float(np.linalg.norm(a.astype('float64'))) or 1.0
            again = (a.astype('float64') / norm).astype('float32')
            if float(np.max(np.abs(again.astype('float64') - b.astype('float64')))) <= 1e-7:
                renorm_equal += 1
    mismatched.sort(key=lambda x: -x['max_abs_diff'])

    out.update({
        'npz_count': len(npz_ids), 'chroma_count': len(chroma_ids),
        'compared': len(common_ids), 'byte_equal': byte_equal,
        'renormalized_equal': renorm_equal,
        'within_tolerance_other': len(common_ids) - len(mismatched) - byte_equal - renorm_equal,
        'max_abs_diff': max_abs,
        'max_abs_diff_excluding_mismatches': max(
            [0.0] + [float(np.max(np.abs(npz_map[i].astype('float32').astype('float64')
                                         - chroma_map[i].astype('float32').astype('float64'))))
                     for i in common_ids if i not in {m['notice_id'] for m in mismatched}]),
        'mismatch_count': len(mismatched), 'mismatch_examples': mismatched[:10],
        'npz_duplicates': npz_dup[:10], 'chroma_duplicates': chroma_dup[:10],
        'only_in_npz': only_npz[:10], 'only_in_npz_count': len(only_npz),
        'only_in_chroma': only_chroma[:10], 'only_in_chroma_count': len(only_chroma),
        'broken': broken[:10], 'broken_count': len(broken),              # Chroma 쪽 이상
        'npz_broken': npz_broken[:10], 'npz_broken_count': len(npz_broken),
    })
    problems = []
    if npz_dup or chroma_dup:
        problems.append('중복 ID (NPZ %d · Chroma %d)' % (len(npz_dup), len(chroma_dup)))
    if only_npz:
        problems.append('Chroma 에 없는 공고 %d건' % len(only_npz))
    if only_chroma:
        problems.append('NPZ 에 없는 Chroma 공고 %d건' % len(only_chroma))
    if npz_broken:
        problems.append('NPZ 벡터 이상 %d건' % len(npz_broken))
    if broken:
        problems.append('Chroma 벡터 이상 %d건' % len(broken))
    if mismatched:
        problems.append('벡터 값이 허용 오차(%g)를 넘게 다른 공고 %d건' % (atol, len(mismatched)))
    if not common_ids and not problems:
        problems.append('비교한 공고가 0건')      # 빈 결과를 통과로 바꾸지 않는다
        out.update(status=UNVERIFIED, problems=problems)
        return out
    out.update(status=MISMATCH if problems else PASS, problems=problems)
    return out


# ─────────────────────────────────────────────────────────────── ③ 메타데이터

def compare_meta(chroma_raw, npz_meta, current_meta):
    """Chroma 컬렉션 metadata['embed_meta'](문자열) · NPZ meta · 지금 설정을 칸별로 맞춘다.

    Chroma 쪽이 없거나 해석이 안 되면 **확인 실패**다. vecstore.stat() 처럼 NPZ 값으로 대신 채우지 않는다.
    """
    out = {'fields': META_FIELDS, 'chroma_raw': chroma_raw, 'npz': npz_meta, 'current': current_meta}
    if chroma_raw is None:
        out.update(status=UNVERIFIED, reason='Chroma 컬렉션에 embed_meta 가 없다')
        return out
    try:
        chroma_meta = json.loads(chroma_raw) if isinstance(chroma_raw, str) else dict(chroma_raw)
    except Exception as exc:
        out.update(status=UNVERIFIED, reason='Chroma embed_meta 를 해석하지 못했다: %s' % exc)
        return out
    if not isinstance(npz_meta, dict):
        out.update(status=UNVERIFIED, reason='NPZ meta 를 해석하지 못했다')
        return out
    out['chroma'] = chroma_meta
    table, differ, unknown = [], [], []
    for field in META_FIELDS:
        c, n, now = chroma_meta.get(field), npz_meta.get(field), (current_meta or {}).get(field)
        same = c == n == now
        table.append({'field': field, 'chroma': c, 'npz': n, 'current': now, 'same': same})
        if c is None or n is None or now is None:
            unknown.append(field)
        elif not same:
            differ.append(field)
    out['table'] = table
    if differ:
        out.update(status=MISMATCH, reason='다른 칸: %s' % ', '.join(differ))
    elif unknown:
        out.update(status=UNVERIFIED, reason='값이 없는 칸: %s' % ', '.join(unknown))
    else:
        out.update(status=PASS)
    return out


# ─────────────────────────────────────────────────────────────── ① DB ↔ NPZ

def compare_db(db_shas, npz_ids, npz_input_sha):
    """DB 의 지금 내용 해시와 NPZ 에 기록된 입력 해시. 기존 data_check 와 같은 기준."""
    vec_sha = dict(zip(npz_ids, npz_input_sha))
    db_ids = set(db_shas)
    stale = sorted(i for i in db_ids if i in vec_sha and vec_sha[i] != db_shas[i])
    missing = sorted(i for i in db_ids if i not in vec_sha)
    extra = sorted(set(vec_sha) - db_ids)
    problems = []
    if stale:
        problems.append('벡터가 옛 내용인 공고 %d건' % len(stale))
    if missing:
        problems.append('벡터가 없는 DB 공고 %d건' % len(missing))
    if extra:
        problems.append('DB 에 없는 공고의 벡터 %d건' % len(extra))
    status = UNVERIFIED if not db_ids else (MISMATCH if problems else PASS)
    if not db_ids:
        problems.append('DB 공고가 0건')
    return {'status': status, 'problems': problems, 'db_count': len(db_ids),
            'stale_count': len(stale), 'stale_examples': stale[:10],
            'missing_count': len(missing), 'missing_examples': missing[:10],
            'extra_count': len(extra), 'extra_examples': extra[:10]}


def overall(parts):
    """부분 판정을 합친다. 하나라도 확인 실패면 확인 실패, 그다음 불일치."""
    states = [p['status'] for p in parts.values()]
    if UNVERIFIED in states:
        return UNVERIFIED
    if MISMATCH in states:
        return MISMATCH
    return PASS


# ─────────────────────────────────────────────────────────────── Chroma 읽기

def read_collection(col, batch=500):
    """컬렉션의 모든 줄을 (ids, embeddings, metadata) 로 읽는다. 관리용 워터마크는 뺀다.

    `get` 이 실패하면 예외를 그대로 올린다 — 호출한 쪽이 '확인 실패'로 기록한다.
    """
    total = col.count()
    ids, vectors = [], []
    offset = 0
    while offset < total:
        got = col.get(include=['embeddings'], limit=batch, offset=offset)
        got_ids = list(got.get('ids') or [])
        got_vecs = got.get('embeddings')
        got_vecs = [] if got_vecs is None else list(got_vecs)
        if not got_ids:
            break
        ids.extend(got_ids)
        vectors.extend(got_vecs)
        offset += len(got_ids)
    keep = [k for k, i in enumerate(ids) if i != WATERMARK]
    if len(ids) != len(vectors):
        # 길이가 다르면 그대로 넘겨 compare_vectors 가 확인 실패로 판정하게 한다
        return [i for i in ids if i != WATERMARK], vectors, dict(col.metadata or {}), total
    return ([ids[k] for k in keep], [vectors[k] for k in keep],
            dict(col.metadata or {}), total)


def open_copy(source_dir, collection):
    """원본을 건드리지 않도록 임시 폴더에 복사한 뒤 사본을 연다. (client, col, tmpdir)."""
    import chromadb
    tmp = tempfile.mkdtemp(prefix='chroma_check_')
    target = os.path.join(tmp, 'chroma')
    shutil.copytree(source_dir, target)
    client = chromadb.PersistentClient(path=target)
    return client, client.get_collection(collection), tmp


# ─────────────────────────────────────────────────────────────── 전체 검사

def check(db_loader, npz_path, chroma_dir, collection, current_meta, open_collection=open_copy):
    """세 가지 대조를 모두 하고 판정을 돌려준다. 실제 데이터는 읽기만 한다.

    db_loader() → (db_shas{id: 입력 해시}, corpus_sha256)
    open_collection(chroma_dir, collection) → (client, col, tmpdir 또는 None)
    """
    import numpy as np
    started = datetime.now(timezone.utc)
    result = {'started_at': started.isoformat(timespec='seconds'), 'parts': {},
              'sources': {'npz': os.path.relpath(npz_path, ROOT).replace('\\', '/'),
                          'chroma_dir': os.path.relpath(chroma_dir, ROOT).replace('\\', '/'),
                          'collection': collection,
                          'db': 'MYSQL_* 설정의 notices (SELECT 만 · 접속 정보 기록하지 않음)'}}
    # 검사 전 식별 정보 — 끝나고 다시 재서 바뀌었으면 한 시점의 일치로 보지 않는다
    def fingerprint():
        return {'npz_sha256': file_sha256(npz_path) if os.path.isfile(npz_path) else None,
                'chroma_files': folder_fingerprint(chroma_dir) if os.path.isdir(chroma_dir) else None}
    before = fingerprint()

    try:
        db_shas, corpus_before = db_loader()
    except Exception as exc:
        result['parts']['db_npz'] = {'status': UNVERIFIED,
                                     'problems': ['DB 를 읽지 못했다: %s' % type(exc).__name__]}
        db_shas, corpus_before = None, None

    # NPZ 를 못 읽으면 traceback 으로 끝내지 않고 '확인 실패' 보고서를 남긴다 (Codex 리뷰 P1-4)
    npz_ids, npz_vectors, npz_input, npz_meta = None, None, None, None
    try:
        data = np.load(npz_path, allow_pickle=False)
        npz_ids = [str(x) for x in data['notice_ids']]
        npz_vectors = np.asarray(data['vectors'])
        npz_input = [str(x) for x in data['input_sha256']]
        try:
            npz_meta = json.loads(str(data['meta']))
        except Exception:
            npz_meta = None
        lengths = {'notice_ids': len(npz_ids), 'vectors': len(npz_vectors),
                   'input_sha256': len(npz_input)}
        if len(set(lengths.values())) != 1:
            raise ValueError('NPZ 배열 길이가 다르다 %s' % lengths)
    except Exception as exc:
        result['parts']['npz'] = {'status': UNVERIFIED,
                                  'problems': ['NPZ 를 읽지 못했다: %s: %s' % (type(exc).__name__, exc)]}
        npz_ids = None

    if db_shas is not None and npz_ids is not None:
        result['parts']['db_npz'] = compare_db(db_shas, npz_ids, npz_input)
    if db_shas is not None:
        result['corpus_sha256'] = corpus_before

    tmp = None
    try:
        if npz_ids is None:
            raise RuntimeError('NPZ 를 읽지 못해 비교할 기준이 없다')
        _client, col, tmp = open_collection(chroma_dir, collection)
        chroma_ids, chroma_vectors, col_meta, raw_count = read_collection(col)
        result['chroma_raw_count'] = raw_count
        # 기대 차원은 **현재 설정**에서 가져온다. NPZ meta 가 틀려도 그것을 기준으로 삼지 않는다
        dim = int((current_meta or {}).get('dim') or (npz_meta or {}).get('dim') or 0)
        result['parts']['npz_chroma'] = compare_vectors(
            npz_ids, npz_vectors, chroma_ids, chroma_vectors, dim)
        result['parts']['meta'] = compare_meta(col_meta.get('embed_meta'), npz_meta, current_meta)
        if len(chroma_ids) == len(chroma_vectors):
            try:
                result['chroma_vector_set_sha256'] = vector_set_sha256(chroma_ids, chroma_vectors)
            except Exception:
                result['chroma_vector_set_sha256'] = None
    except Exception as exc:
        result['parts']['npz_chroma'] = {'status': UNVERIFIED,
                                         'reason': 'Chroma 벡터를 비교하지 못했다: %s: %s'
                                                   % (type(exc).__name__, exc)}
        result['parts'].setdefault('meta', {'status': UNVERIFIED,
                                             'reason': 'Chroma 를 읽지 못해 메타데이터도 확인하지 못했다'})
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    if npz_ids is not None:
        try:
            result['npz_vector_set_sha256'] = vector_set_sha256(npz_ids, npz_vectors)
        except Exception:
            result['npz_vector_set_sha256'] = None

    # 검사 후 다시 잰다
    after = fingerprint()
    changed = []
    if before['npz_sha256'] != after['npz_sha256']:
        changed.append('NPZ 파일이 검사 중에 바뀌었다')
    if before['chroma_files'] != after['chroma_files']:
        changed.append('Chroma 원본 폴더가 검사 중에 바뀌었다')
    if db_shas is not None:
        try:
            _shas_after, corpus_after = db_loader()
            result['corpus_sha256_after'] = corpus_after
            if corpus_after != corpus_before:
                changed.append('DB 공고 내용이 검사 중에 바뀌었다')
        except Exception as exc:
            changed.append('검사 후 DB 를 다시 읽지 못했다: %s' % type(exc).__name__)
    result['snapshot'] = {
        'before': before, 'after': after, 'changed': changed,
        'method': 'NPZ 는 파일 sha256, Chroma 는 원본 폴더 전체 파일의 크기·sha256, '
                  'DB 는 공고 입력 해시 집합의 sha256 을 검사 전후에 비교한다. '
                  '검사 도중 잠깐 바뀌었다가 되돌아간 경우는 잡지 못한다.',
    }
    if changed:
        result['parts']['snapshot'] = {'status': UNVERIFIED, 'problems': changed}

    result['status'] = overall(result['parts'])
    # DB → NPZ → Chroma **전체**가 통과해야 참이다. 처음에는 db_npz 를 빠뜨려 DB 와 어긋난 Chroma 도
    # '검증 완료' 로 표시될 수 있었다(2026-09-21 Codex 리뷰 P2).
    required = ('db_npz', 'npz_chroma', 'meta')
    result['chroma_content_verified'] = (
        all(result['parts'].get(k, {}).get('status') == PASS for k in required)
        and result['status'] == PASS and not changed)
    result['finished_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    return result


def failure_lines(result):
    """integrity_failures 에 붙일 사람이 읽는 사유."""
    lines = []
    for name, part in result.get('parts', {}).items():
        if part.get('status') == PASS:
            continue
        reasons = part.get('problems') or ([part['reason']] if part.get('reason') else [])
        for reason in reasons or ['(사유 없음)']:
            lines.append('[%s · %s] %s' % (name, part.get('status'), reason))
    return lines


# ─────────────────────────────────────────────────────────────── 보고서

def git_revision():
    try:
        return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True,
                              text=True, timeout=10).stdout.strip() or None
    except Exception:
        return None


def code_hashes():
    here = os.path.dirname(os.path.abspath(__file__))
    # 비교 실행의 중단 로직(search_comparison.py)도 넣는다 — 일반 비교를 재현할 때 필요하다
    files = [os.path.join(here, 'chroma_integrity.py'), os.path.join(here, 'search_comparison.py'),
             os.path.join(ROOT, 'shared', 'embed.py'), os.path.join(ROOT, 'search', 'vecstore.py'),
             os.path.join(here, 'build_pool.py')]
    return {os.path.relpath(f, ROOT).replace('\\', '/'): file_sha256(f)
            for f in files if os.path.isfile(f)}


def write_report(result, outdir):
    os.makedirs(outdir, exist_ok=True)
    with io.open(os.path.join(outdir, 'integrity.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(result, f, ensure_ascii=False, indent=1, default=str)
    parts = result.get('parts', {})
    vec = parts.get('npz_chroma', {})
    meta = parts.get('meta', {})
    db = parts.get('db_npz', {})
    lines = [
        '# Chroma 실제 벡터 검증 — %s' % result['status'], '',
        '- 실행: %s → %s' % (result['started_at'], result.get('finished_at')),
        '- 명령: `python -X utf8 eval/chroma_integrity.py`',
        '- 판정: **%s** · chroma_content_verified = %s'
        % (result['status'], result.get('chroma_content_verified')),
        '- 읽은 것: DB(SELECT 만), `%s`, `%s` (원본을 임시 폴더로 복사해 사본을 열었다)'
        % (result['sources']['npz'], result['sources']['chroma_dir']),
        '- 쓰기: 이 보고서 폴더뿐. DB·NPZ·Chroma 는 고치지 않았다.', '',
        '## ① DB ↔ NPZ (입력 해시)', '',
        '- 판정: %s · DB 공고 %s건' % (db.get('status'), db.get('db_count')),
    ]
    lines += ['- %s' % p for p in db.get('problems') or []]
    for key, label in (('stale_examples', '옛 내용 예'), ('missing_examples', '벡터 없음 예'),
                       ('extra_examples', 'DB 에 없는 벡터 예')):
        if db.get(key):
            lines.append('- %s: %s' % (label, ', '.join('`%s`' % x for x in db[key][:5])))
    lines += ['', '## ② NPZ ↔ Chroma (실제 벡터 원소 단위)', '',
              '- 판정: %s' % vec.get('status')]
    if vec.get('reason'):
        lines.append('- 사유: %s' % vec['reason'])
    if 'compared' in vec:
        lines += [
            '- NPZ %d건 · Chroma %d건 · 비교 %d건' % (vec['npz_count'], vec['chroma_count'],
                                                 vec['compared']),
            '- 허용 오차 이내: 바이트 일치 %d건 · 재정규화 일치 %d건 · 그 외 %d건'
            % (vec['byte_equal'], vec.get('renormalized_equal', 0),
               vec.get('within_tolerance_other', 0)),
            '  (재정규화 일치 = NPZ 벡터를 길이 1로 다시 나누면 Chroma 값과 같다. 코사인 색인이 저장할 때 다시 정규화한다)',
            '- 최대 절대 차이 %g · 불일치 공고를 뺀 최대 %g (허용 %g, %s)'
            % (vec['max_abs_diff'], vec.get('max_abs_diff_excluding_mismatches', 0.0),
               TOLERANCE['atol'], TOLERANCE['dtype']),
            '- 허용 오차 근거: %s' % TOLERANCE['why'],
        ]
        lines += ['- %s' % p for p in vec.get('problems') or []]
        for m in vec.get('mismatch_examples', [])[:5]:
            lines.append('  - `%s` 최대 차이 %g · 코사인 %.4f'
                         % (m['notice_id'], m['max_abs_diff'], m.get('cosine', float('nan'))))
        for b in vec.get('npz_broken', [])[:5]:
            lines.append('  - NPZ `%s` %s' % (b['notice_id'], b['problem']))
        for b in vec.get('broken', [])[:5]:
            lines.append('  - Chroma `%s` %s' % (b['notice_id'], b['problem']))
    lines += ['', '## ③ 메타데이터 (Chroma · NPZ · 현재 설정)', '',
              '- 판정: %s%s' % (meta.get('status'), (' — ' + meta['reason']) if meta.get('reason') else '')]
    if meta.get('table'):
        lines += ['', '| 칸 | Chroma | NPZ | 현재 | 같음 |', '|---|---|---|---|---|']
        lines += ['| %s | %s | %s | %s | %s |' % (r['field'], r['chroma'], r['npz'], r['current'],
                                                 '예' if r['same'] else '**아니오**')
                  for r in meta['table']]
    if parts.get('npz', {}).get('status') not in (None, PASS):
        lines += ['', '## NPZ 읽기', ''] + ['- %s' % p for p in parts['npz'].get('problems') or []]
    snap = result.get('snapshot', {})
    lines += ['', '## 검사 중 변경 감지', '',
              '- %s' % ('; '.join(snap.get('changed') or []) or '변경 없음'),
              '- 방법: %s' % snap.get('method', ''), '',
              '## 식별 해시', '',
              '- DB 입력 해시 집합: `%s`' % result.get('corpus_sha256'),
              '- NPZ 파일: `%s`' % snap.get('before', {}).get('npz_sha256'),
              '- NPZ 벡터 집합: `%s`' % result.get('npz_vector_set_sha256'),
              '- Chroma 조회 벡터 집합: `%s`' % result.get('chroma_vector_set_sha256'),
              '- 벡터 집합 해시 계산: ID 정렬 → `ID(utf-8) + 0x00 + float32 리틀엔디언` 을 이어 sha256. '
              '바이트 일치용이며 허용 오차 기반 일치와 다르다.', '',
              '## 한계', '',
              '- 이번 검사는 **지금 시점**의 정합성이다. 과거 `search_comparison_20260918T054314Z` 실행 당시의 정합성 증명이 아니다.',
              '- 검색 품질을 증명하지 않는다. 사람 관련성 판정은 여전히 없다.',
              '- 불일치가 있어도 색인·벡터를 자동으로 고치지 않았다. 고치는 것은 별도 작업이다.', '']
    with io.open(os.path.join(outdir, 'summary.md'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines))


# ─────────────────────────────────────────────────────────────── 진입점

def default_db_loader():
    """DB(EC2)에서 공고를 SELECT 해 지금 내용의 입력 해시를 만든다. 기존 build_pool.corpus 를 쓴다."""
    from build_pool import corpus
    _docs, corpus_hash, shas = corpus()
    return shas, corpus_hash


def run(say=print, db_loader=None, open_collection=open_copy, outdir=None):
    """검사만 한다. 검색·모델 인코딩·색인 생성은 부르지 않는다. 반환: (종료코드, 결과, 결과 폴더)."""
    from search import vecstore
    from shared import embed
    result = check(db_loader or default_db_loader, vecstore.NPZ,
                   os.path.join(vecstore.STORE, 'chroma'), vecstore.COLLECTION,
                   embed.meta(), open_collection=open_collection)
    result['git_revision'] = git_revision()
    result['code_sha256'] = code_hashes()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    outdir = outdir or os.path.join(REPORTS, 'chroma_integrity_' + stamp)
    write_report(result, outdir)
    say('판정: %s · chroma_content_verified = %s'
        % (result['status'], result['chroma_content_verified']))
    for line in failure_lines(result):
        say('  - ' + line)
    say('결과 → %s' % outdir)
    return EXIT[result['status']], result, outdir


def main():
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    code, _result, _outdir = run()
    return code


if __name__ == '__main__':
    sys.exit(main())
