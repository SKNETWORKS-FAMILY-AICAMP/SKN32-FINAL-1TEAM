# -*- coding: utf-8 -*-
"""EC2 에서 BGE-M3 가 실제로 뜨는지, 메모리와 속도가 어떤지 측정한다.

  .venv/bin/python ec2_check_model.py

측정하는 것
  · 모델 로딩 시간과 피크 메모리
  · 질의 인코딩 속도 (첫 회는 워밍업이라 느리다)
  · 만들어진 질의 벡터가 EC2 Chroma 색인에서 제대로 검색되는지
  · MySQL 이 살아 있는지

이 스크립트는 아무것도 바꾸지 않는다. 읽기와 측정만 한다.
"""
import os
import resource
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def peak_mb():
    """이 프로세스가 지금까지 쓴 최대 메모리(MB). 리눅스는 KB 단위로 준다."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def show(label):
    print('  %-26s 피크 %7.0f MB' % (label, peak_mb()))


def free_output():
    try:
        return subprocess.run(['free', '-h'], capture_output=True, text=True).stdout.strip()
    except Exception as exc:
        return '(free 실행 실패: %s)' % exc


def mysql_active():
    try:
        out = subprocess.run(['systemctl', 'is-active', 'mysql'],
                             capture_output=True, text=True).stdout.strip()
        return out or '(판단 불가)'
    except Exception as exc:
        return '(확인 실패: %s)' % exc


def main():
    print('=== 1. 모델 로딩 ===')
    show('시작')
    started = time.time()
    from sentence_transformers import SentenceTransformer
    show('라이브러리 임포트')

    model = SentenceTransformer('BAAI/bge-m3')
    model.max_seq_length = 512
    load_sec = time.time() - started
    print('  로딩 %.1f초' % load_sec)
    show('모델 로딩 완료')

    print()
    print('=== 2. 질의 인코딩 속도 ===')
    queries = ['청년 창업 초기기업 자금 지원',
               '제조업 스마트공장 구축 보조금',
               '수출 바우처 지원사업',
               '소상공인 임대료 지원']
    vectors = []
    for i, q in enumerate(queries, 1):
        t = time.time()
        v = model.encode([q], normalize_embeddings=True, show_progress_bar=False)
        ms = (time.time() - t) * 1000
        vectors.append(v[0])
        note = '  (첫 회는 워밍업)' if i == 1 else ''
        print('  %d회  %6.0fms  shape=%s%s' % (i, ms, v.shape, note))
    show('인코딩 후')

    print()
    print('=== 3. 이 벡터로 Chroma 색인 검색 ===')
    try:
        from ec2 import ec2_vecstore
        col = ec2_vecstore.open_store(create=False)
        if col is None:
            print('  색인이 없다. ec2_vecstore.py 를 먼저 돌린다')
        else:
            for q, v in zip(queries[:2], vectors[:2]):
                t = time.time()
                out = col.query(query_embeddings=[v.tolist()], n_results=3,
                                where={'kind': {'$ne': 'watermark'}})
                ms = (time.time() - t) * 1000
                print('  "%s"  %.0fms' % (q, ms))
                for nid, dist, meta in zip(out['ids'][0], out['distances'][0],
                                           out['metadatas'][0]):
                    print('     %.4f  %s' % (1.0 - dist, (meta.get('title') or nid)[:52]))
    except Exception as exc:
        print('  검색 실패: %s: %s' % (type(exc).__name__, str(exc)[:200]))
    show('검색 후')

    print()
    print('=== 4. 서버 상태 ===')
    print(free_output())
    print()
    print('  mysql: %s' % mysql_active())
    print()
    print('=== 판단 기준 ===')
    print('  피크 2300~2800MB  정상')
    print('  피크 3000MB 초과   빠듯. Swap used 가 0 인지 확인')
    print('  mysql active      가장 중요. inactive 면 모델이 DB 를 밀어낸 것')
    return 0


if __name__ == '__main__':
    sys.exit(main())
