# CPU와 GPU가 만든 벡터가 같은지 본다: 같은 공고끼리 코사인, 검색어별 상위 10건 겹침.
#   <python> embbench_compare.py <결과폴더>
import glob
import os
import sys

import numpy as np

sys.stdout.reconfigure(encoding='utf-8')
d = sys.argv[1]
base_docs = np.load(os.path.join(d, 'docs_cpu-fp32_bs4.npy'))
base_q = np.load(os.path.join(d, 'queries_cpu-fp32.npy'))
base_top = np.argsort(-(base_q @ base_docs.T), axis=1)[:, :10]

for path in sorted(glob.glob(os.path.join(d, 'docs_*.npy'))):
    name = os.path.basename(path)[5:-4]
    if name == 'cpu-fp32_bs4':
        continue
    docs = np.load(path)
    tag = name.rsplit('_bs', 1)[0]
    q = np.load(os.path.join(d, 'queries_%s.npy' % tag))
    cos = (docs * base_docs).sum(1)
    qcos = (q * base_q).sum(1)
    top = np.argsort(-(q @ docs.T), axis=1)[:, :10]
    overlap = np.mean([len(set(a) & set(b)) / 10 for a, b in zip(top, base_top)])
    top1 = np.mean(top[:, 0] == base_top[:, 0])
    print('%-16s 공고 코사인 최저 %.6f 평균 %.6f | 검색어 코사인 최저 %.6f | 상위10 겹침 %.1f%% | 1위 같음 %.1f%%'
          % (name, cos.min(), cos.mean(), qcos.min(), overlap * 100, top1 * 100))
