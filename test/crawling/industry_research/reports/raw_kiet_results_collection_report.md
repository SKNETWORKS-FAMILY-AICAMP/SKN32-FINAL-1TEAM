# KIET 원천 검색 결과 수집데이터보고서

## 1. 수집 데이터 개요

| 항목 | 내용 |
| --- | --- |
| 데이터명 | KIET 연구·동향 SummaryPop 원천 검색 결과 |
| 수집 대상 | `keyword_list.json`의 산업 분야·예시 12개와 사용자 키워드 1개에 대한 KIET 검색 결과 |
| 수집 목적 | 사업계획서의 시장 문제와 산업 동향을 검토할 출처 있는 근거 후보 확보 |
| 사용 예정 기능 | `build_market_report`의 입력, 시장조사 Agent의 근거 조회 |
| 출처 | 산업연구원 KIET. 데이터에 원문 URL과 SummaryPop 호출 정보를 보존 |
| 기준 파일 | `test/crawling/industry_research/output/raw_kiet_results.json` |
| 데이터 수집 시각 | 2026-09-15T07:17:53.171999+00:00 (UTC) |
| 보고서 작성일 | 2026-09-18 |

이 보고서는 저장된 JSON과 `market_crawler.py`를 확인해 작성한 스냅샷이다. 보고서 작성 시 웹 재수집은 수행하지 않았다. 여기서 원천 결과는 HTML 원본이 아니라, SummaryPop 텍스트를 추출하고 수집 성공·관련성·중복 조건을 적용한 결과를 뜻한다.

## 2. 수집 방법 및 자동화 절차

`keyword_rows`가 입력 목록을 검색 단위로 변환하고, `crawl_kiet`가 각 키워드의 연구·동향 검색을 수행한다. 검색 결과의 `openSummary(menuName, menuCode, contentNo)`를 파싱한 뒤 `/getSearchEtt`에 POST 요청하여 제목과 본문을 추출한다.

| 항목 | 내용 |
| --- | --- |
| 사용 언어 / 라이브러리 | Python, requests, BeautifulSoup, json, re |
| 자동화 여부 및 주기 | CLI 수동 실행 기반 자동화. 예약 실행은 코드에 없음 |
| 검색 범위 | `category=kiet_research`, `category=kiet_trends`, `collection=ALL` |
| 정렬·페이지 | `sort=DATE`, `startCount=0`. 후속 페이지 순회 없음 |
| 검색 제한 | `limitPerCategory=10`: 검색어 변형별 연구·동향 각각의 요청·채택 제한. 전체 키워드 결과의 엄격한 상한은 아님 |
| 사용자 검색 확장 | 핵심 토큰 조합과 동의어로 최대 8개 검색어 후보 생성 |
| 사용자 결과 필터 | 제목·SummaryPop 제목·본문을 합친 텍스트에서 핵심 토큰이 2개 이상 매칭되어야 채택. 핵심 토큰이 하나면 1개 기준 |
| 기본 산업 검색 | 원래 분야명으로 검색하며 사용자 키워드용 추가 토큰 필터는 적용하지 않음 |
| 오류 처리 | 검색 요청 실패는 collection의 `failed`와 `error`로 기록. SummaryPop 요청 실패·본문 없음·호출 정보 없음은 해당 결과 제외 |

`queryVariants`는 검색 후보 목록이다. 수집량에 따른 조기 종료가 있으므로 실제 실행한 검색은 `collections`로 확인해야 한다. SummaryPop 개별 실패는 최종 결과에서 제외되므로 이 파일만으로 전체 실패율을 계산할 수 없다.

## 3. 예시 스크립트 및 흐름

```text
keyword_list.json → 분야·사용자 키워드 추출
→ 검색어 후보 생성 → KIET 연구·동향 검색
→ openSummary 호출 정보 추출 → getSearchEtt 요청
→ HTML 태그 제거·공백 정리 → 관련성 확인·URL 중복 제거
→ raw_kiet_results.json 저장
```

```powershell
cd test/crawling/industry_research
python -B market_crawler.py crawl-kiet
```

이 명령은 원천 JSON을 갱신한다. 이 Markdown 보고서는 자동 갱신되지 않으므로 재수집 후 통계를 다시 확인해야 한다.

## 4. 파일 및 필드 설명

| 파일명/테이블명 | 필드 | 타입 | 설명 |
| --- | --- | --- | --- |
| `raw_kiet_results.json` | `researchYear` | number | 조사 기준 연도. 문서 발행 연도 필터를 뜻하지 않음 |
| `raw_kiet_results.json` | `sourceName`, `sourceUrl` | string | 출처 이름과 검색 URL |
| `raw_kiet_results.json` | `limitPerCategory` | number | 검색어 변형별 검색 카테고리 제한 |
| `raw_kiet_results.json` | `categories` | array | 키워드별 수집 단위 |
| `raw_kiet_results.json` | `categories[].industryId`, `industryName` | string | 입력 목록의 내부 ID와 분야명·사용자 검색어 |
| `raw_kiet_results.json` | `categories[].classificationType`, `programName`, `track` | string | 공식 분야·공고 예시·사용자 키워드 구분과 사업 정보 |
| `raw_kiet_results.json` | `categories[].keyword`, `queryVariants`, `requiredTerms` | string / array | 원 검색어, 검색 후보, 관련성 검사 토큰 |
| `raw_kiet_results.json` | `categories[].status`, `error` | string / string 또는 null | 키워드 수집 상태와 검색 요청 오류 |
| `raw_kiet_results.json` | `categories[].collections` | array | 실제 검색어·연구/동향별 실행 결과. 자체 `results`, `status`, 수집 시각 포함 |
| `raw_kiet_results.json` | `categories[].resultCount`, `results` | number / array | 키워드 내부 URL 중복 제거 후 건수와 문서 목록 |
| `raw_kiet_results.json` | `results[].title`, `summaryTitleText`, `summaryText` | string 또는 null | 검색 제목, SummaryPop 제목과 추출 본문. 채택 결과의 본문은 비어 있지 않음 |
| `raw_kiet_results.json` | `results[].contentType`, `author`, `publishedAt` | string 또는 null | 유형, 저자, 발행일. 메타데이터 파싱 실패 시 null 가능 |
| `raw_kiet_results.json` | `results[].url`, `sourceUrl`, `sourceName` | string | 개별 문서 URL, SummaryPop 엔드포인트, 출처 이름 |
| `raw_kiet_results.json` | `results[].keyword`, `sourceSearchQuery` | string | 사용자에게 보여줄 원 검색어와 실제 검색에 사용한 검색어 |
| `raw_kiet_results.json` | `results[].searchCategory`, `searchCategoryName` | string | 연구/동향 검색 카테고리 |
| `raw_kiet_results.json` | `results[].openSummary` | object | `menuName`, `menuCode`, `contentNo` 호출 정보 |
| `raw_kiet_results.json` | `results[].matchedTerms` | array | 관련성 검사에서 매칭된 핵심 토큰 |
| `raw_kiet_results.json` | `results[].verificationStatus` | string | `kiet_summary_pop_collected`. 수집 성공을 뜻하며 내용의 사실 검증 완료를 뜻하지 않음 |
| `raw_kiet_results.json` | `summary` | object | 키워드 수, 수집 성공 키워드 수, 키워드별 결과 수의 합계 |
| `raw_kiet_results.json` | `methodNote`, `collectedAt` | string | 수집 방식 설명과 UTC 수집 시각 |

표의 `results[]`는 `categories[].results[]`를 기준으로 설명한다. `collections[].results[]`에도 같은 문서 구조가 들어가므로 두 배열을 합쳐 전체 건수를 세면 중복 집계된다.

## 5. 데이터 양 및 수집 결과

| **전체 수집 데이터 건수** |
| --- |
| 저장된 키워드별 수집 결과 123건(고유 URL 96개). 필터링 전 검색 결과 총건수는 기록되지 않음 |
| **추출된 고품질 데이터 건수 (필터링 후 기준)** |
| 본문 수집 성공·키워드 내부 URL 중복 제거·사용자 키워드 관련성 조건을 통과한 123건(고유 URL 96개). 기본 산업 검색에는 추가 토큰 필터를 적용하지 않으며, 사람의 품질 검토가 완료된 건수는 아님 |

| 지표 | 값 |
| --- | --- |
| 전체 검색 키워드 | 13개 |
| 결과가 있는 키워드 | 10개 |
| 결과가 없는 키워드 | 3개 |
| 실제 검색 collection | 40개: collected 28개, no_relevant_source_found 12개 |
| 저장된 키워드별 문서 합계 | 123건: 연구 86건, 동향 37건 |
| 전체 키워드 간 URL 중복 제거 시 | 96개 문서 |
| 저장 문서 발행일 범위 | 2014-04-23 ~ 2026-09-01 |

| 검색 키워드 | 저장 건수 | 상태 |
| --- | --- | --- |
| 정보·통신 | 12 | collected |
| 전기·전자 | 10 | collected |
| 기계·소재(재료) | 4 | collected |
| 바이오·의료(생명·식품) | 0 | no_relevant_source_found |
| 에너지·자원(환경·에너지) | 20 | collected |
| 화학(화공·섬유) | 0 | no_relevant_source_found |
| 공예·디자인 | 0 | no_relevant_source_found |
| 빅데이터·AI | 19 | collected |
| 바이오헬스 | 10 | collected |
| 미래모빌리티 | 11 | collected |
| 친환경에너지 | 15 | collected |
| 로봇 | 13 | collected |
| 기업용 AI 문서 검색 | 9 | collected |

0건은 현재 검색·본문 수집·필터 조건에서 채택된 문서가 없다는 뜻이다. 해당 산업의 자료가 KIET에 전혀 없다는 뜻은 아니다. 123건은 수집 조건을 통과한 근거 후보 수이며, 사람이 품질을 확정한 문서 수가 아니다.

## 6. 저장 위치 및 포맷

- 데이터: `test/crawling/industry_research/output/raw_kiet_results.json`
- 보고서: `test/crawling/industry_research/reports/raw_kiet_results_collection_report.md`
- 포맷: JSON / Markdown, UTF-8
- 다음 단계: `python -B market_crawler.py build-report`로 `output/results.json` 생성

## 7. 개인정보·출처 및 이용 조건 기록

수집 스키마에는 문헌 저자명인 `author`가 포함되며, 본문에도 인명이 포함될 수 있다. 별도의 비식별화 로직은 없다. 문서 URL과 출처를 보존하며 원문 저작권은 해당 권리자에게 귀속된다. 코드와 JSON에는 이용 약관·라이선스·robots.txt 검토 완료 기록이 없으므로 이용 허가가 확인된 데이터로 표시하지 않는다. 본 보고서는 법률 검토 결과가 아니다.

## 8. 데이터 품질 및 정합성 관리

- 중복 제거: collection 내부와 동일 키워드 전체 결과에서 URL 기준 제거. 서로 다른 키워드 간 동일 문서는 유지한다.
- 결측치: 메타데이터 파싱 실패는 null을 허용하지만 SummaryPop 본문이 없으면 결과를 제외한다.
- 표준화: HTML 태그 제거, 공백 정리, 파싱된 발행일을 `YYYY-MM-DD`로 변환한다.
- 본문 품질: 태그 제거만 수행하므로 메뉴·목차 등 주변 텍스트가 포함될 수 있다.
- 관련성: 사용자 토큰 매칭은 문자열 포함 기준이며 의미적 관련성이나 근거의 정확성을 보장하지 않는다.
- 최신성: `researchYear=2026`이어도 과거 문서를 포함한다. 인용 전 `publishedAt`을 확인한다.
- 집계 검증: 각 `resultCount`와 `results` 길이, `summary.totalResultCount`와 키워드별 결과 합계가 일치하는지 확인한다.

## 9. 변경 이력

| 변경일 | 변경 내용 | 근거 |
| --- | --- | --- |
| 2026-09-18 | 원천 결과의 수집 방식·필드·통계·한계 보고서 신규 작성 | 저장된 JSON 및 market_crawler.py 확인 |
