# ml/ — 리랭커·업력 분류기 학습 (제출물)

## 맡는 것
- 리랭커: `04_reranker_train.py`(BAAI/bge-reranker-v2-m3에 LoRA), `06_rerank_pool.py`, `07_rerank_demo.py`, `05_reranker_report.ipynb`, 공용 규칙 `rerank_common.py`(공고 → 리랭커 입력 문장 `notice_text`, 학습 쌍 `load_pairs`, `Scorer`). 학습 결과 `models/reranker_lora/`(LoRA 어댑터만 — 원본 모델은 HuggingFace에서 받음).
- 업력 근거 문장 분류기: `02_age_classifier.ipynb`, `models/age_classifier_v1.joblib`·`v2.joblib`(TF-IDF + 로지스틱 회귀).
- 데이터·실험: `01_dataset.ipynb`, `03_ml_experiments.ipynb`, `data/`(학습 결과·그림), 노트북 생성기 `make_notebook*.py`.

## 맡지 않는 것
- 서비스 추천 경로. **리랭커와 분류기는 서비스에 연결하지 않는다.** 공고 서버에서는 시연 화면(`/demo`·`/classify`)만 이 폴더 결과를 쓴다(`rerank_common`, `models/age_classifier_v2.joblib`).
- 평가 정답 만들기(`eval/`). 학습 데이터는 `eval/qrels.jsonl` 등 기존 판정을 읽어서 쓴다.

## 항상 지켜야 할 것
- 학습·시험 분할은 **질의 단위**다. 사람 판정 143쌍이 49개 질의에 흩어져 있어, 쌍 단위로 나누면 같은 질의가 학습·시험 양쪽에 들어가 결과가 부풀려진다.
- 학습과 평가는 같은 `notice_text`를 쓴다. 한쪽만 바꾸지 않는다.
- 제출한 결과서(`docs/deliverables/`)가 가리키는 모델 파일을 덮어쓰지 않는다. 새로 학습하면 새 이름(`…_v3` 등)으로 둔다.
- `ml/data/age_labels.jsonl`은 git에서 제외한다(EC2 DB로 다시 만들 수 있다). 어댑터는 두 PC가 같이 쓰므로 저장소에 둔다.

## 이 폴더의 방식
- GPU 학습은 사용자 집 PC(RTX 3060 12GB)에서 원격으로 한다. `requirements-ml.txt`를 설치하고 torch는 CUDA 판을 따로 설치한다. 이 PC의 `.venv`에는 학습 패키지가 없을 수 있다.
- 노트북은 `make_notebook*.py`로 만들어 재현한다.

## 시험
- 자동 시험은 없다. 공고 서버 시연 경로는 `peft`가 없거나 어댑터가 없으면 사전학습 모델로 대신 돌고 화면에 그렇게 표시한다 — 이 동작을 깨지 않는다.
- 학습을 다시 돌리면 결과를 `ml/data/`와 `reports/`에 새로 남기고, 이전 결과와 같은 분할·같은 지표로 비교한다.
