# BGE-M3 임베딩 속도 측정(CPU/GPU). 서비스 설정(최대 512토큰, 정규화, float32 출력)과 같게 돈다.
#   <python> embbench_run.py <inputs.json> <결과폴더> --device cpu|cuda [--fp16] [--batches 4,16]
import argparse
import json
import os
import statistics
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
os.environ['HF_HUB_OFFLINE'] = '1'

ap = argparse.ArgumentParser()
ap.add_argument('inputs')
ap.add_argument('outdir')
ap.add_argument('--device', default='cpu')
ap.add_argument('--fp16', action='store_true')
ap.add_argument('--batches', default='4,16')
args = ap.parse_args()

import numpy as np  # noqa: E402
import torch  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

try:
    import psutil
    proc = psutil.Process()
except Exception:
    proc = None

data = json.load(open(args.inputs, encoding='utf-8'))
texts, queries = data['texts'], data['queries']
tag = args.device + ('-fp16' if args.fp16 else '-fp32')
res = {'tag': tag, 'torch': torch.__version__, 'threads': torch.get_num_threads(),
       'n_docs': len(texts), 'n_queries': len(queries), 'total_notices': data['total_notices']}
if args.device == 'cuda':
    res['gpu'] = torch.cuda.get_device_name(0)
    free, total = torch.cuda.mem_get_info()
    res['gpu_free_mb_before'] = round(free / 2**20)


def sync():
    if args.device == 'cuda':
        torch.cuda.synchronize()


t0 = time.perf_counter()
model = SentenceTransformer('BAAI/bge-m3', device=args.device)
model.max_seq_length = 512
if args.fp16:
    model.half()
sync()
res['load_s'] = round(time.perf_counter() - t0, 2)

# 첫 호출 준비(서버의 워밍업과 같은 역할)
t0 = time.perf_counter()
model.encode(texts[:8], batch_size=4, normalize_embeddings=True)
sync()
res['warmup_s'] = round(time.perf_counter() - t0, 2)

# 공고 묶음 임베딩(배치) — 배치 크기별
res['docs'] = {}
for bs in [int(x) for x in args.batches.split(',')]:
    if args.device == 'cuda':
        torch.cuda.reset_peak_memory_stats()
    t0 = time.perf_counter()
    vec = model.encode(texts, batch_size=bs, normalize_embeddings=True, convert_to_numpy=True)
    sync()
    sec = time.perf_counter() - t0
    vec = vec.astype(np.float32)
    row = {'sec': round(sec, 2), 'per_doc_ms': round(sec / len(texts) * 1000, 1),
           'full_est_min': round(sec / len(texts) * data['total_notices'] / 60, 2)}
    if args.device == 'cuda':
        row['gpu_peak_mb'] = round(torch.cuda.max_memory_allocated() / 2**20)
    res['docs'][str(bs)] = row
    np.save(os.path.join(args.outdir, 'docs_%s_bs%d.npy' % (tag, bs)), vec)
    print(tag, '공고', len(texts), '건 배치', bs, ':', row, flush=True)

# 검색어 1건씩(공고 서버가 요청마다 하는 일)
lat = []
for q in queries:
    t0 = time.perf_counter()
    model.encode([q], batch_size=1, normalize_embeddings=True)
    sync()
    lat.append((time.perf_counter() - t0) * 1000)
lat.sort()
res['query_ms'] = {'median': round(statistics.median(lat), 1),
                   'p95': round(lat[int(len(lat) * 0.95) - 1], 1), 'max': round(lat[-1], 1)}
qv = model.encode(queries, batch_size=8, normalize_embeddings=True).astype(np.float32)
np.save(os.path.join(args.outdir, 'queries_%s.npy' % tag), qv)
if proc:
    res['rss_mb_now'] = round(proc.memory_info().rss / 2**20)
    try:
        res['rss_mb_peak'] = round(proc.memory_info().peak_wset / 2**20)
    except Exception:
        pass
print(tag, '검색어 1건:', res['query_ms'], flush=True)
json.dump(res, open(os.path.join(args.outdir, 'result_%s.json' % tag), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False))
