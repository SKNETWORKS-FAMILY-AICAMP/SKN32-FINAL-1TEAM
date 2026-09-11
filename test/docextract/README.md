# 문서 RAG 전처리

정부 공고문·사업계획서 등 로컬 문서를 추출하고, 출처를 추적할 수 있는 청크와 FAISS 검색 인덱스를 만듭니다. 결과물에는 개발자 PC의 절대 경로를 저장하지 않습니다.

## 요구 사항

- Python 3.11 이상
- PDF, DOCX, HWPX, HWP 원문을 아래 입력 폴더에 배치

```text
Sbrain/
├─ docs/공유자료/사업계획서 자료/# 필수/
└─ test/docextract/
```

## 설치와 실행

`test/docextract` 폴더에서 실행합니다.

```powershell
python -m pip install -r requirements.txt
python -B pipeline.py
python -B -m unittest test_pipeline
```

## 저장 구조와 역할

원문 검토용 결과는 **파일별로**, RAG 검색용 결과는 **문서 전체를 통합해** 저장합니다. 두 종류의 산출물은 목적이 다르며 함께 유지합니다.

| 위치 | 역할 |
| --- | --- |
| `results/**/*.pdf.json`, `*.docx.json`, `*.hwpx.json`, `*.hwp.json` | 원문별 추출 결과. 본문, 상태, 오류 사유, 페이지·문자 수를 확인하고 재처리할 때 사용 |
| `results/rag/rag_chunks.jsonl` | 모든 추출 성공 문서의 청크를 한 줄씩 저장. 각 청크의 `relativePath`, `format`, `chunkIndex`로 원문을 역추적 |
| `results/rag/faiss.index` | 모든 문서를 한 번에 검색하는 통합 벡터 인덱스 |
| `results/rag/vectorizer.pkl` | 사용자 질의를 인덱스와 동일한 벡터로 변환하는 객체 |
| `results/rag/vector_metadata.json` | 벡터 방식, 차원, 청크 메타데이터 |
| `results/rag/rag_failures.json` | RAG에 넣지 못한 문서와 후속 처리 사유 |

문서마다 인덱스를 따로 만들지 않습니다. 통합 인덱스가 있어야 여러 사업·공고 문서에서 한 번에 관련 근거를 검색할 수 있습니다.

## 처리 방식

- PDF: 내장 텍스트를 추출합니다. 스캔본은 `needs_ocr`로 기록합니다.
- DOCX: 본문 XML만 읽습니다.
- HWPX: `Contents/section*.xml` 본문만 읽어 패키지 메타데이터를 제외합니다.
- HWP: `requirements.txt`의 `pyhwp`가 제공하는 `hwp5txt`로 본문을 추출합니다. 읽지 못한 파일만 `needs_converter`로 기록하며, HWPX 또는 PDF로 변환한 뒤 다시 실행하면 자동으로 포함됩니다.
- 청킹: 문장·문단을 우선 유지하며 최대 900자, 오버랩 최대 150자로 만듭니다.
- 벡터화: 한국어 공고의 사업명·공고번호·지원 조건 검색에 적합한 문자 n-gram TF-IDF 벡터를 만들고 FAISS 코사인 유사도 인덱스에 저장합니다. Transformer/ONNX 모델을 사용하지 않아 대규모 모델 메모리가 필요하지 않습니다.

## 실패 문서 처리

실패 문서는 삭제하거나 빈 청크로 만들지 않습니다. 원문별 JSON과 `rag_failures.json`에 상태와 사유를 남기고 벡터 인덱스에서는 제외합니다.

| 상태 | 의미 | 후속 처리 |
| --- | --- | --- |
| `needs_converter` | HWP 본문을 읽지 못함 | HWPX 또는 PDF로 변환 후 다시 실행 |
| `needs_ocr` | PDF에 내장 텍스트가 없음 | OCR한 PDF 또는 텍스트 기반 PDF로 교체 후 다시 실행 |
| `failed` | 파일 구조 또는 본문 추출 실패 | 원본 파일을 확인하고 정상 파일로 교체 후 다시 실행 |

변환 또는 OCR을 마친 원본을 입력 폴더에 넣고 `pipeline.py`를 다시 실행하면 실패 큐에서 빠지고 청킹·색인에 자동 포함됩니다.

## 현재 완료 상태

현재 입력 자료를 기준으로 다음 상태를 확인했습니다.

- 추출·청킹·FAISS 인덱스 생성 완료
- 청크 306개, 빈 청크 0개, 900자 초과 청크 0개
- 청크 메타데이터에 절대 경로 없음
- HWP·OCR 대기 문서 0개
- `python -B -m unittest test_pipeline` 통과

이 수치는 입력 문서가 바뀌면 달라집니다. 실행 후 콘솔의 `Indexed ... chunks; queued ... documents` 메시지와 `rag_failures.json`을 최신 상태로 확인합니다.

## 공유 전 확인

1. `python -B -m unittest test_pipeline`이 통과하는지 확인합니다.
2. `rag_failures.json`이 비어 있는지 확인합니다. 항목이 있으면 변환 또는 OCR이 필요한 문서입니다.
3. `rag_chunks.jsonl`의 `relativePath`, `format`, `chunkIndex`로 답변의 근거 원문을 확인합니다.
4. `vectorizer.pkl`은 신뢰할 수 있는 이 프로젝트에서 생성한 파일만 사용합니다. 외부에서 받은 pickle 파일은 열지 않습니다.


## 청크 파일 읽는 방법

`rag_chunks.jsonl`은 검색 시스템이 한 줄씩 읽는 JSON Lines 파일이라 사람용 주석을 넣지 않습니다. 대신 각 청크의 `metadata`에 아래 필드를 기록합니다.

- `documentTitle`: 원본 파일명
- `relativePath`: 원본 상대 경로
- `chunkIndex`, `documentChunkCount`: 해당 원문에서의 청크 위치와 전체 수
- `isDocumentStart`, `isDocumentEnd`: 원문 청크의 시작·끝 여부

사람이 문서별 경계를 확인할 때는 `results/rag/rag_documents.md`를 엽니다. 이 파일은 원문마다 제목, 상대 경로, 포맷, 첫·마지막 청크 ID를 줄바꿈해 보여 줍니다.

## DB 담당자 전달 사항

DB 담당자에게는 `faiss.index`, `vectorizer.pkl`, `vector_metadata.json`, `rag_chunks.jsonl`을 **같은 실행 결과 묶음**으로 전달합니다. `faiss.index`와 `vectorizer.pkl`은 서로 다른 실행 결과를 섞어 사용하면 안 됩니다.

현재 `rag_failures.json`은 비어 있으며, 색인된 청크는 376개입니다. 원본 문서와 `rag_documents.md`를 함께 전달하면 청크의 `relativePath`에서 근거 원문을 바로 확인할 수 있습니다.

일부 PDF는 원문 텍스트 레이어 자체에 띄어쓰기 정보가 부족해, 추출 텍스트가 `대퇴골두와비구컵사이의…`처럼 붙어 보일 수 있습니다. 이는 청킹 과정에서 공백을 제거한 것이 아닙니다. 문자 n-gram 벡터 검색과 출처 추적에는 영향을 주지 않지만, 사용자에게 보여 주는 최종 답변은 원본 PDF를 확인해 정상 문장으로 재서술합니다.
