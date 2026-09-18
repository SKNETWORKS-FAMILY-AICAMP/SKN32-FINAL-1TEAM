# crawling_industry_research

2026년 창업지원사업 사업계획서에 활용할 산업 배경과 시장 동향 근거를 수집합니다. 코드는 `market_crawler.py` 하나이며, 대표 산출물은 `output/results.json`입니다.

## 핵심 원칙

이 폴더는 경쟁사 목록처럼 기업을 코드에 고정해두는 구조가 아닙니다.

다만 `keyword_list.json`에 들어가는 기본 산업 키워드는 중소벤처기업부 공고·보도자료·첨부 PDF에서 확인해야 하므로, 코드에 후보 명칭을 상수로 두고 실행 시 공식 문서에서 실제 존재 여부를 검증합니다.

- `PRE_EXAMPLES`: 예비창업패키지 공고 PDF에 있는 전 기술 분야 예시 7개를 검증하기 위한 후보명
- `DEEPTECH`: 중기부 보도자료의 초기창업패키지 딥테크 5대 분야를 검증하기 위한 후보명
- `build_keyword_list`: 중기부 페이지/PDF를 실제 요청하고, 후보명이 원문에 없으면 `ValueError`로 중단
- `crawl_kiet`: `keyword_list.json`의 키워드를 KIET 통합검색에 실제 요청
- `build_market_report`: KIET 원천 결과를 사업계획서 Agent가 읽기 좋은 구조로 변환

즉, 산업 키워드 후보명은 코드에 있지만, 결과 본문은 KIET에서 실제 수집한 SummaryPop 텍스트입니다.

## 파일 구조

| 경로 | 역할 |
| --- | --- |
| `market_crawler.py` | 키워드 목록 생성, KIET SummaryPop 수집, 시장조사 JSON 생성, 사용자 키워드 추가를 모두 처리 |
| `output/keyword_list.json` | KIET에 검색할 입력 목록. 공식 공고에서 확인한 산업 키워드와 사용자 추가 키워드 |
| `output/raw_kiet_results.json` | 원천 수집물. KIET 연구/동향 SummaryPop 본문, 제목, URL, 검색어 변형, 매칭 토큰 저장 |
| `output/results.json` | 대표 산출물. 사업계획서 Agent가 사용할 구조화 시장조사 결과 |
| `output/keyword_history.json` | 사용자가 직접 `add-keyword`로 실행한 검색 이력 |
| `reports/keyword_list_collection_report.md` | 키워드 목록 수집 데이터 보고서 |
| `reports/raw_kiet_results_collection_report.md` | KIET 원천 결과의 수집 방식, 필드, 분야별 통계와 품질 한계 보고서 |
| `reports/results_collection_report.md` | 시장조사 결과의 가공 방식, 섹션별 근거 통계와 활용 범위 보고서 |
| `test_search_quality.py` | 최소 동작 검증 테스트 |

`reports/`의 Markdown 보고서는 저장된 데이터 기준으로 작성한 문서이며 CLI 실행 시 자동 갱신되지 않습니다. 데이터 재수집·가공 후에는 각 보고서의 기준 시각과 통계를 다시 확인해야 합니다.

## 실행 방법

```powershell
cd test/crawling/industry_research
pip install -r requirements.txt
python -B market_crawler.py init-keywords
python -B market_crawler.py crawl-kiet
python -B market_crawler.py build-report
python -B market_crawler.py add-keyword "기업용 AI 문서 검색"
python -B market_crawler.py all
python -B -m unittest test_search_quality
```

## 데이터 파일 관계

```text
output/keyword_list.json
  → KIET에 검색할 입력 목록
  → 공식 공고에서 확인한 산업 키워드 + 사용자가 add-keyword로 추가한 키워드

output/raw_kiet_results.json
  → keyword_list.json의 각 키워드로 KIET를 실제 검색한 원천 수집 결과
  → SummaryPop 본문, 제목, URL, 검색어 변형, 매칭 토큰 저장

output/results.json
  → raw_kiet_results.json을 사업계획서 Agent가 읽기 좋게 가공한 대표 산출물
  → marketNeed, marketTrend, competitors, differentiation 섹션 구조로 변환

output/keyword_history.json
  → 사용자가 직접 add-keyword로 실행한 검색 이력
  → 같은 keyword는 중복 누적하지 않고 최신 결과로 덮어씀
  → firstCollectedAt/searchCount/lastCollectedAt으로 실행 이력 보존
```

## 명령 설명

| 명령 | 설명 |
| --- | --- |
| `init-keywords` | 중기부 공고/PDF를 확인해 기본 산업 키워드 목록을 생성하고 기존 사용자 키워드를 유지 |
| `crawl-kiet` | `keyword_list.json`의 키워드로 KIET 연구/동향 SummaryPop 본문 수집 |
| `build-report` | KIET 원천 결과를 `marketNeed`, `marketTrend`, `competitors`, `differentiation` 구조로 변환 |
| `add-keyword "키워드"` | 사용자 키워드를 중복 없이 추가하고 KIET 수집과 시장조사 JSON을 재생성 |
| `all` | 키워드 목록 생성, KIET 수집, 시장조사 JSON 생성을 한 번에 실행 |

## KIET 수집 방식

```text
검색어 = output/keyword_list.json의 산업 키워드 또는 userKeywords.keyword
→ https://www.kiet.re.kr/searchAll?query=검색어
→ 연구 더보기: collection=ALL&category=kiet_research
→ 동향 더보기: collection=ALL&category=kiet_trends
→ 결과별 openSummary(menu_nm, menu_cd, no) 추출
→ https://www.kiet.re.kr/getSearchEtt POST 호출
→ SummaryPop 제목/본문 텍스트 저장
```

사용자 키워드는 제품명처럼 KIET 산업 키워드와 바로 맞지 않을 수 있어 확장 검색을 적용합니다. 예를 들어 `기업용 AI 문서 검색`은 `기업용` 같은 범용 단어를 단독 검색어로 쓰지 않고, `AI 문서 검색`, `AI 문서`, `AI 검색`, `문서 검색`, `인공지능 문서 검색`처럼 2개 이상 핵심 토큰이 포함된 조합으로만 추가 검색합니다.

결과도 제목·SummaryPop 본문에서 핵심 토큰이 최소 2개 이상 확인될 때만 저장하고, 저장된 결과에는 `sourceSearchQuery`와 `matchedTerms`를 남깁니다.

## 경쟁사/단가 비교

KIET는 산업 배경과 동향 근거에는 적합하지만, 경쟁사 목록과 가격/단가 비교에는 적합하지 않습니다. 해당 작업은 `test/crawling/competitor_research`에서 별도로 관리합니다.

이 폴더의 `results.json`은 KIET 근거를 `marketNeed`, `marketTrend`에 주로 배치하고, `competitors`, `differentiation`에는 추가 수집 필요 문장을 남깁니다.
