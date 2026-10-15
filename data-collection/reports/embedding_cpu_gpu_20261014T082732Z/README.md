# BGE-M3 임베딩 CPU vs GPU 비교 (2026-10-14)

배포 EC2를 GPU 인스턴스로 할지 정하려고, 같은 입력·같은 설정으로 CPU와 GPU의 임베딩 속도와 결과 벡터를 비교했다. 공용 DB는 SELECT만 했고 쓰기는 없다. 비용 $0.

## 환경

| | CPU 측정 | GPU 측정 |
|---|---|---|
| 장비 | 집 PC AMD Ryzen 5 5600X(6코어, torch 스레드 6), 메모리 32GB | 같은 PC의 NVIDIA RTX 3060 12GB |
| 파이썬 환경 | `data-collection/.venv`(torch 2.14.1+cpu) | 따로 만든 환경(torch 2.14.1+cu126) — 저장소 밖 |
| 공통 | sentence-transformers 6.1.0 · transformers 5.19.0 · BGE-M3 리비전 `5617a9f…`(서비스와 같음) · 최대 512토큰 · 정규화 · 출력 float32 | |

GPU 측정 때는 GPU를 쓰던 다른 프로그램(ComfyUI)이 꺼져 있었다(측정 전 GPU 여유 메모리 약 11GB).

## 입력

- 공고: 공용 DB `notices` 3,016건(입력 문장이 빈 공고 제외)에서 `notice_id` 순서로 일정 간격 300건(`sample.json`). 입력 문장은 서비스와 같은 `shared.embed.build_input`. 글자 수 중앙값 321.
- 검색어: `eval/queries.jsonl` 66개를 공고 서버와 같은 `search.app.build_query`로 만든 문장. 글자 수 중앙값 68.

## 결과

공고 300건 묶음 임베딩(배치 = 한 번에 넣는 건수, 서비스는 4):

| 방식 | 배치 4 | 배치 16 | 배치 32 | 전체 3,016건 환산 | GPU 메모리 최대 |
|---|---|---|---|---|---|
| CPU | 122.5초(건당 408ms) | 136.6초(455ms) | — | 약 20.5분 | — |
| GPU 기본 정밀도(fp32) | 6.4초(21ms) | 6.2초(21ms) | 9.9초(33ms) | 약 1.1분 | 2.2~2.7GB |
| GPU 반정밀도(fp16) | 2.5초(8ms) | 2.1초(7ms) | 2.1초(7ms) | 약 0.4분 | 1.1~1.4GB |

검색어 1건 인코딩(공고 서버가 요청마다 하는 일, 66개):

| 방식 | 중앙값 | p95 | 최대 |
|---|---|---|---|
| CPU | 178.5ms | 203.0ms | 230.1ms |
| GPU fp32 | 21.7ms | 26.4ms | 74.5ms |
| GPU fp16 | 23.1ms | 26.8ms | 72.0ms |

모델 올리기: CPU 2.7초 + 첫 호출 4.0초, GPU 5.0초 + 첫 호출 0.7초.

## 벡터가 같은가 (`vector_compare.txt`, 기준 = CPU 배치 4)

- **GPU fp32: CPU와 같다.** 같은 공고끼리 코사인 최저 1.000000, 검색어별 상위 10건 겹침 100%, 1위 같음 100%. → GPU로 만든 벡터를 지금 CPU 벡터와 섞어 써도 된다. 설정 지문(모델·리비전·입력 버전·토큰 상한·차원·float32·정규화)에도 장치는 들어가지 않는다.
- GPU fp16: 코사인 최저 0.99976, 상위 10건 겹침 99.4%, 1위 같음 100%. 거의 같지만 같지는 않다. 쓰려면 전량을 한 방식으로 다시 만드는 편이 깔끔하다.

## EC2(t3.medium, CPU 2코어·4GB) 기존 측정과 견주기

- 공고 임베딩: 10/2 시험 서버 112건 109.6초(건당 약 1초), 10/12 새 서버 40건 46초(건당 약 1.2초) → 집 PC CPU(408ms)보다 약 2.5~3배 느림. 전체 3,016건이면 약 50분.
- 검색어 1건: EC2 258~390ms(`docs/archive/HANDOFF.md`) vs 집 PC CPU 178ms.

## 해석 (결정은 사용자)

- 매일 배치: 새 공고가 하루 수십 건이라 EC2 CPU로 1분 안팎(10/12 40건 46초). 배치 전체(약 8~10분, 대부분 수집·LLM 호출) 가운데 작은 몫이라 GPU로 줄어드는 시간은 하루 1분 남짓이다.
- 공고 서버 응답: 검색어 인코딩이 EC2에서 약 0.3초 → GPU면 약 0.02초. 매칭 응답(중앙값 345ms)은 줄지만, 뒤이어 도는 조율 에이전트의 LLM 단계(수 초~수십 초)에 비하면 사용자가 느끼는 차이는 작다.
- 전량 다시 만들기(모델·입력 방식 변경 때): EC2 CPU 약 50분 vs GPU 약 1분. 드문 일이고, GPU fp32 벡터가 CPU와 같으므로 필요하면 집 PC GPU로 만들어 올릴 수 있다.
- 요금(서울 리전 온디맨드, 제3자 가격표 기준 — 실제 결정 전 AWS 가격 계산기로 확인): t3.medium 시간당 약 $0.052(월 약 $38) vs g4dn.xlarge(T4 16GB, 메모리 16GB) 시간당 약 $0.647(월 약 $472) — 약 12배.
- 임베딩만 보면 GPU 인스턴스를 쓸 이유가 약하다. 다만 다른 팀원의 검수 모델처럼 GPU가 꼭 필요한 것이 있어 GPU 서버를 어차피 띄운다면, 공고 서버를 같은 서버에 올리는 것은 검토할 만하다.

## 한계

- GPU는 RTX 3060이다. AWS g4dn의 T4와는 성능이 다르다(대략 fp32는 T4가 더 느리고, fp16은 비슷한 수준으로 알려져 있다 — 직접 재지는 않음).
- CPU 측정은 집 PC CPU다. EC2 수치는 다른 날 다른 공고로 잰 기존 기록이라 정확히 같은 조건이 아니다.
- 한 번씩만 쟀다.

## 다시 재기

```
cd data-collection
.venv\Scripts\python.exe reports\embedding_cpu_gpu_20261014T082732Z\embbench_export.py <작업폴더>\inputs.json
.venv\Scripts\python.exe reports\embedding_cpu_gpu_20261014T082732Z\embbench_run.py <작업폴더>\inputs.json <작업폴더> --device cpu --batches 4,16
<GPU 환경 python> reports\embedding_cpu_gpu_20261014T082732Z\embbench_run.py <작업폴더>\inputs.json <작업폴더> --device cuda --batches 4,16,32
<GPU 환경 python> reports\embedding_cpu_gpu_20261014T082732Z\embbench_run.py <작업폴더>\inputs.json <작업폴더> --device cuda --fp16 --batches 4,16,32
<GPU 환경 python> reports\embedding_cpu_gpu_20261014T082732Z\embbench_compare.py <작업폴더>
```

GPU 환경 만들기(저장소 밖 폴더에): `uv venv <폴더> --python 3.12` → `uv pip install --python <폴더>\Scripts\python.exe "torch==2.14.1" --index-url https://download.pytorch.org/whl/cu126` → `uv pip install --python <폴더>\Scripts\python.exe sentence-transformers==6.1.0 transformers==5.19.0 numpy==2.5.4 tokenizers==0.23.3 psutil`. (cu128 판에는 torch 2.14.1이 없다. 패키지를 먼저 깔면 CPU 판 torch가 들어오므로 torch를 먼저 깐다.)
