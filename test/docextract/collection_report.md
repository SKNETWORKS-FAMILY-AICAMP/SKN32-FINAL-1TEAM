# 사업계획서 문서 추출 수집데이터보고서

## 1. 수집 데이터 개요

| **데이터명** | **수집 대상** | **수집 목적** | **사용 예정 기능** | **출처 / 저작권** |
| -------- | --------- | --------- | ------------ | ------------ |
| 사업계획서 문서 추출 데이터 | 사용자가 직접 다운로드한 정부지원사업 공고문, 사업계획서 양식, 질의응답, 세부관리기준 HWP/PDF/DOCX/HWPX 문서 | 사업계획서 작성 Agent가 공고 조건, 작성 양식, 검증 기준을 근거 문서 기반으로 검색·참조할 수 있도록 텍스트와 RAG 인덱스 생성 | 문서 근거 검색, 사업계획서 작성 보조, 공고 조건 검증, 양식 기반 항목 생성 | 사용자가 공공기관 등에서 직접 수집한 원문 파일 기반. 원문 저작권은 각 발행기관 또는 권리자에게 귀속 |

## 2. 수집 방법 및 자동화 절차

사용자가 예비창업패키지, 재도전성공패키지, 초기창업패키지 관련 공고문과 사업계획서 양식 파일을 직접 다운로드해 로컬 입력 폴더에 저장했다. 이후 `pipeline.py`가 입력 폴더의 PDF, DOCX, HWPX, HWP 파일을 순회하며 텍스트를 추출하고, 파일별 JSON과 통합 RAG 검색 인덱스를 생성했다.

입력 폴더는 다음 경로를 기준으로 한다.

```text
docs/공유자료/사업계획서 자료/# 필수
```

처리 결과는 원문별 추출 JSON과 검색용 RAG 파일로 분리해 저장한다. 원문별 JSON은 추출 상태 확인과 재처리에 사용하고, RAG 산출물은 Agent 검색에 사용한다.

## 2.2 수집 방식

| **사용 언어 / 라이브러리** |
| -------------------- |
| Python, PyMuPDF(fitz), zipfile, ElementTree, pyhwp/hwp5txt, scikit-learn, FAISS, numpy |
| **자동화 여부 및 주기** |
| 수동 파일 수집 후 자동 추출. 사용자가 원문 HWP/PDF/DOCX/HWPX를 추가하거나 교체할 때 `pipeline.py`를 재실행 |
| **오류 발생 시 예외 처리 전략** |
| PDF 텍스트 레이어가 없으면 `needs_ocr`, HWP 추출기가 없거나 실패하면 `needs_converter`, 기타 구조 오류는 `failed`로 기록하고 RAG 인덱스에서는 제외 |

## 4. 예시 스크립트 또는 흐름도 첨부

```text
사용자가 HWP/PDF/DOCX/HWPX 원문 다운로드
→ docs/공유자료/사업계획서 자료/# 필수 폴더에 저장
→ pipeline.py 실행
→ 파일별 텍스트 추출
→ 추출 결과 JSON 저장
→ 문단·문장 기준 청킹
→ 문자 n-gram TF-IDF 벡터화
→ FAISS 통합 인덱스 생성
→ 실패 문서는 rag_failures.json에 분리 기록
```

```powershell
cd test/docextract
python -B pipeline.py
python -B -m unittest test_pipeline
```

## 5. 파일 및 필드 설명

| **파일명 / 테이블명** | **필드명** | **데이터 타입** | **설명** | **예시** |
| -------------- | ------- | ---------- | ------ | ------ |
| `results/**/*.json` | `relativePath` | string | 입력 폴더 기준 원문 상대 경로 | 예비창업패키지/.../공고.pdf |
| `results/**/*.json` | `format` | string | 원문 파일 확장자 | `.pdf`, `.hwp` |
| `results/**/*.json` | `status` | string | 추출 상태 | `extracted`, `needs_ocr` |
| `results/**/*.json` | `text` | string | 추출된 본문 텍스트 | 사업 목적 및 지원 대상 |
| `results/**/*.json` | `error` | string 또는 null | 실패 또는 대기 사유 | No embedded text; OCR required |
| `results/**/*.json` | `details` | object | 페이지 수, 문자 수 등 부가 정보 | `pageCount`, `textCharacterCount` |
| `results/rag/rag_chunks.jsonl` | `chunkId` | string | 청크 고유 ID | `a1b2c3d4-0000` |
| `results/rag/rag_chunks.jsonl` | `documentId` | string | 원문 문서 ID | SHA-256 기반 16자 ID |
| `results/rag/rag_chunks.jsonl` | `text` | string | 검색 대상 청크 텍스트 | 지원대상은 예비창업자... |
| `results/rag/rag_chunks.jsonl` | `metadata.relativePath` | string | 근거 원문 상대 경로 | 재도전성공패키지/... |
| `results/rag/rag_chunks.jsonl` | `metadata.chunkIndex` | number | 원문 내 청크 순번 | 0 |
| `results/rag/vector_metadata.json` | `embeddingMethod` | string | 벡터화 방식 | TF-IDF Korean character n-grams |
| `results/rag/vector_metadata.json` | `chunkCount` | number | 색인 청크 수 | 376 |
| `results/rag/rag_failures.json` | `status` | string | RAG 제외 사유 상태 | `needs_converter` |

## 6. 데이터 양

| **전체 수집 데이터 건수** |
| ----------------------------- |
| 원문 추출 결과 17건, 총 추출 문자 254,159자, PDF 페이지 145쪽 |
| **추출된 고품질 데이터 건수 (필터링 후 기준)** |
| 추출 성공 문서 17건, RAG 청크 376개, 실패 문서 0건 |

## 7. 저장 위치 및 포맷

| **저장 경로** |
| --------- |
| `test/docextract/results/**/*.json`, `test/docextract/results/rag/*` |
| **저장 포맷** |
| JSON, JSON Lines, FAISS index, pickle, Markdown |
| **인코딩** |
| UTF-8 |

## 8. 법적·윤리적 검토

| **개인정보 포함 여부** |
| -------------------- |
| 현재 추출 대상은 공고문, 사업계획서 양식, 질의응답, 관리기준 중심으로 개인정보를 수집 대상으로 하지 않음 |
| **포함된 경우 필드** |
| 해당 없음. 단, 사용자가 실제 사업계획서 샘플이나 신청서 원본을 추가할 경우 대표자명, 연락처, 이메일, 사업자 정보 등이 포함될 수 있음 |
| **비식별화 조치 여부** |
| 현재 개인정보 비식별화 대상 없음. 개인정보가 포함된 파일을 추가하는 경우 RAG 투입 전 마스킹 필요 |
| **출처 및 사용권 — 공개 여부** |
| 사용자가 직접 다운로드한 공공 공고·양식 파일 기반. 원문 재배포가 아니라 내부 검색용 텍스트와 메타데이터 생성 |
| **라이선스 / 약관 검토 여부** |
| 원문 발행기관의 공고·자료 이용 조건을 최종 산출물 배포 전 확인 필요 |
| **검토자** |
| 박상희 |
| **검토 일자** |
| 2026-09-14 |

## 9. 데이터 품질 및 정합성 관리 방안

| **중복 제거 기준** |
| -------------------- |
| 입력 폴더의 상대 경로와 파일명을 기준으로 문서를 구분. 동일 파일이 다른 형식으로 존재하는 경우 각각 추출하되 `relativePath`로 근거를 추적 |
| **정합성 검증 방법** |
| `python -B -m unittest test_pipeline`으로 청크 길이, 실패 문서 분리, FAISS 인덱스, 메타데이터 청크 수, 절대 경로 미포함 여부를 검증 |
| **Null 처리 및 결측치 전략** |
| 본문 텍스트가 없는 PDF는 `needs_ocr`, 추출 불가 HWP는 `needs_converter`, 실패 문서는 `rag_failures.json`에 기록하고 인덱스에서 제외 |
| **표준화 전략** |
| 모든 원문은 `relativePath`, `format`, `status`, `text`, `error`, `details` 구조로 저장. 청크는 최대 900자, 오버랩 최대 150자 기준으로 통일 |

## 10. 변경 이력 및 보완 내역

| **변경일** | **변경자** | **변경 내용** | **비고** |
| ------- | ------- | --------- | ------ |
| 2026-09-14 | 박상희 | 사업계획서 문서 추출 파이프라인 정리 및 RAG 산출물 확인 | 원문 17건, 청크 376개 |
| 2026-09-14 | 박상희 | 지정 수집데이터보고서 양식으로 보고서 작성 | 사용자가 직접 다운로드한 HWP/PDF 기반 수집 과정 반영 |

## 기존 상세 설명

이 데이터는 웹에서 자동 수집한 자료가 아니라, 사용자가 직접 다운로드해 로컬 폴더에 넣은 사업계획서 관련 문서를 대상으로 한다. 입력 문서는 예비창업패키지, 재도전성공패키지, 초기창업패키지의 공고문, 사업계획서 양식, 주요 질의응답, 세부관리기준으로 구성되어 있다.

파이프라인은 PDF의 내장 텍스트를 추출하고, DOCX와 HWPX는 압축 패키지 내부 XML 본문을 읽는다. HWP는 `hwp5txt`를 통해 본문을 추출한다. 읽지 못한 파일은 빈 청크로 만들지 않고 실패 큐에 남긴다.

검색 인덱스는 문서별로 분리하지 않고 전체 문서를 통합해 만든다. 사업계획서 작성 Agent가 여러 사업의 공고, 양식, 관리기준을 한 번에 검색해야 하기 때문이다. 각 청크에는 원문 상대 경로와 청크 순번이 남아 있어 답변 생성 후 근거 문서를 다시 확인할 수 있다.

결과물에는 개발자 PC의 절대 경로를 저장하지 않는다. 공유 가능한 메타데이터는 입력 폴더 기준 상대 경로로 기록한다.
