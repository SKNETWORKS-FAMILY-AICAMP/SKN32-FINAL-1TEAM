# 사업계획서 시장조사 결과 수집·가공데이터보고서

## 1. 데이터 개요

| 항목 | 내용 |
| --- | --- |
| 데이터명 | KIET 근거 기반 사업계획서 시장조사 구조화 결과 |
| 입력 데이터 | `output/keyword_list.json`, `output/raw_kiet_results.json` |
| 가공 목적 | 분야별 근거 후보를 사업계획서 작성 섹션에 배치하고 추가 조사 항목을 구분 |
| 사용 예정 기능 | 사업계획서 Agent의 근거 조회와 작성 지침 제공 |
| 출처 | 산업연구원 KIET 원천 수집 결과. 개별 근거에 문서 URL과 발행일 보존 |
| 기준 파일 | `test/crawling/industry_research/output/results.json` |
| 데이터 생성 시각 | 2026-09-16T01:43:49.504566+00:00 (UTC) |
| 입력 원천 수집 시각 | 2026-09-15T07:17:53.171999+00:00 (UTC) |
| 보고서 작성일 | 2026-09-18 |

저장된 JSON과 `market_crawler.py`를 확인한 스냅샷 보고서다. `results.json`은 독립적인 웹 수집물이 아니라 원천 결과를 재배치한 가공물이다. 생성 시각은 원문 수집 시각과 다르며, 완성된 시장 분석문이나 검증된 시장 규모 추정치를 뜻하지 않는다.

## 2. 가공 방법 및 자동화 절차

| 항목 | 내용 |
| --- | --- |
| 사용 언어 / 라이브러리 | Python, json, pathlib, datetime. 변환 자체에는 네트워크 요청이나 LLM 호출 없음 |
| 실행 함수 | `build_market_report`, `build_section`, `evidence` |
| 자동화 여부 및 주기 | CLI 수동 실행. `all`, `add-keyword` 실행 시에도 시장조사 JSON 재생성 |
| 입력 연결 기준 | 원천 `industryName` 또는 `keyword`를 입력 목록의 분야명과 연결 |
| 빈 근거 처리 | evidence를 빈 배열로 두고 `no_relevant_source_found` 및 추가 조사 지침 저장 |
| 입력 누락 처리 | 현재 로더는 파일이 없으면 기본값을 사용하므로 입력 목록 누락 시 0개 보고서, 원천 누락 시 근거 없는 보고서가 생성될 수 있음 |

| 섹션 | 근거 선택 방식 | 해석 |
| --- | --- | --- |
| `marketNeed` | 연구 결과 앞부분 최대 10건 | 시장 문제와 필요성에 활용할 후보 |
| `marketTrend` | 동향 결과 앞부분 최대 10건. 동향 결과가 0건이면 전체 결과 앞부분 최대 10건 | 시장 규모·최근 동향 검토 후보. 동향이 일부 있으면 연구로 부족분을 추가 채우지는 않음 |
| `competitors` | 근거를 선택하지 않음 | 기업·제품·가격·고객 사례 별도 조사 필요 |
| `differentiation` | 근거를 선택하지 않음 | 사용자 아이템 기능과 경쟁 제품 비교 필요 |

선택 순서는 원천 배열 순서이며 별도의 전체 발행일 재정렬이나 의미 기반 순위 산정은 없다. `claim`은 SummaryPop 제목 또는 문서 제목을 재사용하고, `evidenceText`는 수집 본문을 전달한다. `analysis`는 null이다.

## 3. 예시 스크립트 및 흐름

```text
keyword_list.json + raw_kiet_results.json
→ 분야명·검색어 기준 연결 → 분야별 4개 섹션 생성
→ 연구/동향 근거 선택 → 출처 메타데이터 보존
→ 빈 근거와 추가 조사 안내 기록 → results.json 저장
```

```powershell
cd test/crawling/industry_research
python -B market_crawler.py build-report
```

이 명령은 저장된 원천 JSON으로 결과 JSON을 갱신한다. 이 Markdown 보고서는 자동 갱신되지 않는다.

## 4. 파일 및 필드 설명

| 파일명/테이블명 | 필드 | 타입 | 설명 |
| --- | --- | --- | --- |
| `results.json` | `researchYear`, `researchMode` | number / string | 조사 기준 연도, `kiet_summary_pop` 방식 |
| `results.json` | `source` | object | 출처명, 검색 URL, SummaryPop 엔드포인트, 원천 파일 경로 |
| `results.json` | `reports` | array | 분야·사용자 검색어별 결과 |
| `results.json` | `reports[].industryName`, `sourceKeyword` | string | 분야명 또는 사용자 검색어 |
| `results.json` | `reports[].researchYear`, `category` | number / object | 기준 연도와 입력 분야의 ID·분류·사업·트랙 정보 |
| `results.json` | `reports[].subjectType` | string | 산업 분야 / 사용자 키워드 |
| `results.json` | `reports[].sourceResultCount` | number | 해당 키워드의 원천 문서 수. 섹션 배치 수와 다름 |
| `results.json` | `reports[].sections` | object | marketNeed, marketTrend, competitors, differentiation |
| `results.json` | `sections.<섹션>.status`, `label` | string | 근거 유무 상태와 한글 섹션명 |
| `results.json` | `sections.<섹션>.evidence` | array | 해당 섹션에 배치한 근거 후보 |
| `results.json` | `evidence[].claim`, `evidenceText` | string | 출처 제목에서 가져온 문구와 SummaryPop 본문 |
| `results.json` | `evidence[].source` | object | 제목, URL, type, publisher, 발행일, 자료 유형, 검색 카테고리, 실제 검색어, 매칭 토큰, openSummary 정보 |
| `results.json` | `evidence[].verificationStatus` | string | SummaryPop 수집 성공 상태. 사실 검증 완료 표시가 아님 |
| `results.json` | `evidence[].businessPlanUse` | string | 근거가 배치된 섹션 키 |
| `results.json` | `evidence[].analysis` | null | 별도 분석문 미생성 |
| `results.json` | `sections.<섹션>.promptBrief` | string | 섹션별 근거 활용·추가 조사 지침 |
| `results.json` | `reports[].promptBrief`, `collectedAt` | string | 주제별 작성 지침과 생성 시각 |
| `results.json` | `summary` | object | 보고서 수와 입력 원천의 카테고리·문서 집계 |
| `results.json` | `methodNote`, `collectedAt` | string | 가공 방식 설명과 전체 생성 시각 |

## 5. 데이터 양 및 분야별 결과

| **전체 수집 데이터 건수** |
| --- |
| 입력 원천 결과 123건(고유 URL 96개)을 바탕으로 주제별 보고서 13개, 섹션 52개 생성. 별도 웹 수집은 수행하지 않음 |
| **추출된 고품질 데이터 건수 (필터링 후 기준)** |
| 섹션별 선택 기준에 따라 배치한 근거 137건(marketNeed 86건, marketTrend 51건). 섹션 간 재사용 14건을 포함하며, 별도 품질 검증을 통과한 고유 문서 건수를 뜻하지 않음 |

| 지표 | 값 |
| --- | --- |
| 분야·검색어별 보고서 | 13개 |
| 섹션 | 52개: 주제당 4개 |
| 근거가 있는 주제 | 10개 |
| 근거가 있는 섹션 | 20개 |
| 근거가 없는 섹션 | 32개 |
| 입력 원천 문서 합계 | 123건, 키워드 간 URL 중복 제거 시 96개 |
| 섹션에 배치된 evidence 합계 | 137건: marketNeed 86건, marketTrend 51건 |
| competitors / differentiation 근거 | 각각 0건 |

| 분야·검색어 | 원천 문서 | marketNeed | marketTrend |
| --- | --- | --- | --- |
| 정보·통신 | 12 | 9 | 3 |
| 전기·전자 | 10 | 9 | 1 |
| 기계·소재(재료) | 4 | 4 | 4 |
| 바이오·의료(생명·식품) | 0 | 0 | 0 |
| 에너지·자원(환경·에너지) | 20 | 10 | 10 |
| 화학(화공·섬유) | 0 | 0 | 0 |
| 공예·디자인 | 0 | 0 | 0 |
| 빅데이터·AI | 19 | 10 | 9 |
| 바이오헬스 | 10 | 10 | 10 |
| 미래모빌리티 | 11 | 10 | 1 |
| 친환경에너지 | 15 | 9 | 6 |
| 로봇 | 13 | 10 | 3 |
| 기업용 AI 문서 검색 | 9 | 5 | 4 |
| 합계 | 123 | 86 | 51 |

기계·소재(재료) 4건과 바이오헬스 10건은 동향 자료가 없어 연구 자료를 `marketTrend`에도 배치했다. 따라서 evidence 137건은 서로 다른 문서 137개가 아니며, 원천 123건에 섹션 간 재사용 14건이 더해진 수치다. 모든 주제의 `competitors`, `differentiation`은 근거가 없는 상태로 보존된다.

`summary.sourceTotalResultCount`는 입력 원천의 집계를 복사한 값이다. evidence 합계와 같은 지표로 해석하면 안 된다.

## 6. 저장 위치 및 포맷

- 데이터: `test/crawling/industry_research/output/results.json`
- 보고서: `test/crawling/industry_research/reports/results_collection_report.md`
- 포맷: JSON / Markdown, UTF-8
- 원천 설명: [KIET 원천 검색 결과 수집데이터보고서](raw_kiet_results_collection_report.md)
- 입력 설명: [키워드 목록 수집데이터보고서](keyword_list_collection_report.md)

## 7. 개인정보·출처 및 이용 조건 기록

`evidence.source`에는 별도의 author 필드를 복사하지 않지만, `evidenceText`에 저자명 등 인명이 남을 수 있다. 별도 비식별화는 수행하지 않는다. 출처 URL과 발행일을 보존하며 원문 저작권은 해당 권리자에게 귀속된다. 이 가공 과정에서 새로운 이용 허가를 확인하거나 부여하지 않는다. 이용 조건 검토 완료 기록은 입력 코드·JSON에서 확인되지 않는다.

## 8. 데이터 품질 및 정합성 관리

- 출처 추적: evidence의 URL과 본문을 해당 분야의 원천 결과와 대조한다.
- 집계 확인: 보고서 수, 분야별 원천 문서 수, 섹션별 evidence 길이를 별도로 검증한다.
- 중복 처리: 섹션 간 동일 근거를 허용한다. 고유 문서 수가 필요하면 URL로 별도 집계한다.
- 결측치: 경쟁사·차별화와 미수집 분야를 빈 배열로 유지하며 추정 문장으로 근거를 채우지 않는다.
- 분석 한계: 제목을 사용한 claim과 원천 본문은 근거 후보다. 시장 규모 수치·인과관계·제품 경쟁력이 자동 검증된 것은 아니다.
- 최신성: 결과 생성 시각과 원천 수집 시각, 개별 문서 발행일을 구분한다. 조사 연도가 발행 연도를 제한하지 않는다.
- 입력 정합성: 분야명 변경이나 원천 파일 누락으로 빈 결과가 발생할 수 있어 재생성 전 두 입력 파일의 존재와 키워드 대응을 확인한다.

## 9. 변경 이력

| 변경일 | 변경 내용 | 근거 |
| --- | --- | --- |
| 2026-09-18 | 구조화 결과의 가공 방식·필드·통계·한계 보고서 신규 작성 | 저장된 JSON 및 market_crawler.py 확인 |
