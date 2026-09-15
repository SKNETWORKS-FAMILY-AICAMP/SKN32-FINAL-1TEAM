# 2026 창업지원사업 키워드 목록 수집데이터보고서

## 1. 수집 데이터 개요

| **데이터명** | **수집 대상** | **수집 목적** | **사용 예정 기능** | **출처 / 저작권** |
| -------- | --------- | --------- | ------------ | ------------ |
| 2026 창업지원사업 키워드 목록 | 예비창업패키지, 재도전성공패키지, 초기창업패키지의 공식 모집 분야·예시·전 분야 여부 | 시장조사 자동화의 기준이 되는 사업별 분야 목록 확보 | `market_crawler.py`의 KIET 검색 입력 데이터, 사용자 키워드 구분, 사업계획서 시장조사 기준 데이터 | 중소벤처기업부 공개 공고·보도자료 URL 기반. 원문 저작권은 해당 기관에 귀속 |

## 2. 수집 방법 및 자동화 절차

웹 크롤링과 PDF 문서 수집을 통해 중소벤처기업부 공고 페이지와 첨부 PDF에서 사업명, 분야명, 특화 유형, 전 분야 지원 여부를 확인했다. 공식 분야가 없는 사업은 임의 산업명을 생성하지 않고, 산업별 모집표 부재 또는 전 분야 지원 상태를 JSON에 기록했다.

## 2.2 수집 방식

| **사용 언어 / 라이브러리** |
| -------------------- |
| Python, requests, BeautifulSoup, PyMuPDF(fitz), json, re |
| **자동화 여부 및 주기** |
| 수동 실행 기반 자동화. 공고 변경 또는 신규 공고 확인 시 `market_crawler.py init-keywords` 재실행 |
| **오류 발생 시 예외 처리 전략** |
| 공식 페이지 제목 또는 PDF 내 분야명이 확인되지 않으면 `ValueError`를 발생시켜 잘못된 목록 생성을 중단 |

## 4. 예시 스크립트 또는 흐름도 첨부

```text
중기부 공고·보도자료 URL 요청
→ HTML 본문 텍스트 추출
→ 예비창업패키지 PDF 다운로드 및 텍스트 추출
→ 공식 분야명 존재 여부 검증
→ 사업별 programs 구조 생성
→ 기존 userKeywords 보존
→ keyword_list.json 저장
```

```powershell
cd test/crawling/industry_research
python -B market_crawler.py init-keywords
```

## 5. 파일 및 필드 설명

| **파일명 / 테이블명** | **필드명** | **데이터 타입** | **설명** | **예시** |
| -------------- | ------- | ---------- | ------ | ------ |
| `keyword_list.json` | `researchYear` | number | 수집 기준 연도 | 2026 |
| `keyword_list.json` | `sourcePublisher` | string | 기준 출처 기관 | 중소벤처기업부 |
| `keyword_list.json` | `scopeNote` | string | 데이터 해석 범위 | 사업별 공식 분야만 표시 |
| `keyword_list.json` | `programs` | array | 사업 유형별 목록 | 예비창업패키지 |
| `keyword_list.json` | `programId` | string | 내부 사업 ID | pre_startup |
| `keyword_list.json` | `programName` | string | 사업명 | 초기창업패키지 |
| `keyword_list.json` | `track` | string | 모집 트랙 | 딥테크 특화형 |
| `keyword_list.json` | `industryRestriction` | string | 산업 제한 또는 분야 기준 상태 | five_official_fields |
| `keyword_list.json` | `industries` | array | 공식 분야 또는 공고상 예시 분야 | 빅데이터·AI |
| `keyword_list.json` | `classificationType` | string | 공식 분야, 비한정 예시, 사용자 키워드 구분 | official_program_field |
| `keyword_list.json` | `sourceUrl` | string | 근거 URL | https://www.mss.go.kr/... |
| `keyword_list.json` | `userKeywords` | array | 사용자가 추가한 검색 키워드 | 기업용 AI 문서 검색 |
| `keyword_list.json` | `collectedAt` | string | 수집 시각 | 2026-09-14T... |

## 6. 데이터 양

| **전체 수집 데이터 건수** |
| ----------------------------- |
| 4개 사업 유형, 공식 분야·예시 12개, 사용자 키워드 1개 |
| **추출된 고품질 데이터 건수 (필터링 후 기준)** |
| 공식 출처에서 검증된 분야·예시 12개 |

## 7. 저장 위치 및 포맷

| **저장 경로** |
| --------- |
| `test/crawling/industry_research/output/keyword_list.json` |
| **저장 포맷** |
| JSON, Markdown |
| **인코딩** |
| UTF-8 |

## 8. 법적·윤리적 검토

| **개인정보 포함 여부** |
| -------------------- |
| 없음 |
| **포함된 경우 필드** |
| 해당 없음 |
| **비식별화 조치 여부** |
| 해당 없음 |
| **출처 및 사용권 — 공개 여부** |
| 중소벤처기업부 공개 공고·보도자료 URL 기반. 원문 전체 복제 없이 분야명과 출처 URL을 저장 |
| **라이선스 / 약관 검토 여부** |
| 출처 URL 보존. 실제 사업계획서 제출 전 최신 공고와 이용 조건 재확인 필요 |
| **검토자** |
| 박상희 |
| **검토 일자** |
| 2026-09-14 |

## 9. 데이터 품질 및 정합성 관리 방안

| **중복 제거 기준** |
| -------------------- |
| 동일 사업 ID, 동일 트랙, 동일 분야명 기준으로 중복 제거. 사용자 키워드는 동일 keyword 기준으로 1회만 유지 |
| **정합성 검증 방법** |
| 공고 페이지 제목 확인, PDF 내 분야명 존재 여부 확인, 공식 분야와 사용자 키워드 분리 저장 |
| **Null 처리 및 결측치 전략** |
| 공식 산업표가 없는 사업은 빈 배열로 저장하고 `note`에 사유 기록 |
| **표준화 전략** |
| 내부 ID, 분야명, 분류 타입, 출처 URL, 수집 시각 필드 형식 통일 |

## 10. 변경 이력 및 보완 내역

| **변경일** | **변경자** | **변경 내용** | **비고** |
| ------- | ------- | --------- | ------ |
| 2026-09-14 | 박상희 | 2026 창업지원사업 키워드 목록 생성 | 최초 산출 |
| 2026-09-14 | 박상희 | 지정 보고서 양식 추가 | 기존 상세 본문 유지 |

## 기존 상세 보고서

## 1. 수집 목적

이 보고서는 2026년 정부지원사업 사업계획서 작성과 시장조사 자동화의 기준이 되는 키워드 목록 데이터를 설명한다.

대상 사업은 다음 3개 창업지원사업이다.

- 예비창업패키지
- 재도전성공패키지
- 초기창업패키지

키워드 목록의 목적은 임의 산업 목록을 만드는 것이 아니라, 공식 공고와 중소벤처기업부 자료에서 확인되는 모집 분야, 예시 분야, 전 분야 지원 여부를 구조화하는 것이다.

## 2. 산출물

- 데이터 파일: `keyword_list.json`
- 생성 코드: `market_crawler.py`의 `init-keywords` 명령
- 보고서 파일: `reports/keyword_list_collection_report.md`

`keyword_list.json`은 시장조사 단계의 입력 데이터로 사용된다. `market_crawler.py crawl-kiet`가 이 파일의 공식 분야와 사용자 키워드를 읽어 KIET SummaryPop 원천 결과를 수집하고, `market_crawler.py build-report`가 사업계획서용 `results.json`을 생성한다.

## 3. 수집 기준

공식 자료에서 산업 분야가 명시된 경우에는 해당 명칭을 그대로 사용했다.

공고가 특정 산업을 제한하지 않고 전 분야 지원으로 안내하는 경우에는 임의 산업을 추가하지 않고, `industryRestriction`과 `note`에 그 상태를 기록했다.

사용자가 입력한 키워드는 공식 지원 분야가 아니므로 `userKeywords`에 별도로 저장한다. 이 값은 시장조사를 위한 사용자 관심 키워드이며, 사업 신청 자격이나 우대 분야로 해석하면 안 된다.

## 4. 수집 결과 요약

| 구분 | 결과 |
| --- | --- |
| 기준 연도 | 2026 |
| 출처 기관 | 중소벤처기업부 |
| 사업 유형 수 | 4개 |
| 공식 분야·예시 수 | 12개 |
| 사용자 키워드 수 | 1개 |
| 데이터 파일 | `test/crawling/industry_research/output/keyword_list.json` |

사업 유형은 예비창업패키지, 재도전성공패키지, 초기창업패키지 일반형, 초기창업패키지 딥테크 특화형으로 분리했다. 초기창업패키지는 일반형과 딥테크 특화형의 분야 기준이 다르므로 별도 항목으로 관리한다.

## 5. 사업별 리스팅 내용

| 사업 | 수집된 분야 | 해석 |
| --- | --- | --- |
| 예비창업패키지 | 정보·통신, 전기·전자, 기계·소재(재료), 바이오·의료(생명·식품), 에너지·자원(환경·에너지), 화학(화공·섬유), 공예·디자인 | 공고 PDF에 제시된 전 기술 분야의 비한정 예시다. 공식 코드가 아니라 내부 ID로 관리한다. |
| 재도전성공패키지 | 없음 | 공고에서 산업별 모집표를 확인하지 못했다. 지원 대상과 제외 업종은 공고 PDF 확인이 필요하다. |
| 초기창업패키지 일반형 | 없음 | 중기부 자료 기준 전 분야 창업기업으로 정리했다. 특정 산업 리스트를 임의 생성하지 않았다. |
| 초기창업패키지 딥테크 특화형 | 빅데이터·AI, 바이오헬스, 미래모빌리티, 친환경에너지, 로봇 | 중기부 보도자료의 딥테크 5대 분야를 공식 분야로 저장했다. |

## 5-1. 산업 카테고리 지정 근거와 임의 생성 여부

`keyword_list.json`의 산업 카테고리는 자체 산업분류표를 임의로 만든 것이 아니라, 중소벤처기업부 공고·보도자료·첨부 PDF에서 확인되는 명칭만 추출하여 저장했다. 다만 모든 항목이 동일한 성격의 공식 산업분류는 아니므로 `classificationType`으로 구분한다.

| 구분 | JSON 분류값 | 지정 근거 | 해석 |
| --- | --- | --- | --- |
| 예비창업패키지 7개 분야 | `official_non_exhaustive_example` | 예비창업패키지 공고 PDF에 제시된 전 기술 분야 예시 | 공식 산업 코드 또는 전체 모집 분야가 아니라, 공고에 제시된 비한정 예시 분야다. KIET 검색을 위한 기본 키워드로 사용한다. |
| 초기창업패키지 딥테크 특화형 5개 분야 | `official_program_field` | 중소벤처기업부 보도자료에서 확인한 딥테크 5대 분야 | 해당 트랙에서 확인되는 공식 프로그램 분야로 저장한다. |
| 재도전성공패키지 | 해당 없음 | 공고에서 산업별 모집표를 확인하지 못함 | 산업 카테고리를 임의로 만들지 않고 `industries: []`로 유지한다. |
| 초기창업패키지 일반형 | 해당 없음 | 전 분야 창업기업 대상 성격으로 확인 | 특정 산업 리스트를 임의로 만들지 않고 `industries: []`로 유지한다. |
| 사용자 입력 키워드 | `user_keyword` | 사용자가 `add-keyword`로 입력 | 공식 지원 분야가 아니며, KIET 검색과 시장조사 보조용 키워드로만 사용한다. |

따라서 현재 목록은 “정부지원사업 전체 산업분류”가 아니라 “사업계획서 시장조사 자동화를 위해 공식 자료에서 확인 가능한 분야명과 사용자 키워드를 모은 검색 기준 목록”이다. 공식 분야가 없는 사업에 대해 임의 산업명을 추가하지 않았으며, 예비창업패키지 7개 분야도 전체 모집 분야를 확정한 값이 아니라 공고 PDF의 예시 분야로 처리한다.

## 6. 데이터 구조

`keyword_list.json`의 주요 필드는 다음과 같다.

| 필드 | 의미 |
| --- | --- |
| `researchYear` | 수집 기준 연도 |
| `sourcePublisher` | 기준 출처 기관 |
| `scopeNote` | 데이터 해석 범위 |
| `programs` | 사업 유형별 분야 목록 |
| `programs[].industryRestriction` | 전 분야, 공식 5대 분야, 산업표 부재 등 제한 조건 |
| `programs[].industries` | 공고에서 확인된 분야 또는 예시 |
| `programs[].specializedTracks` | 산업이 아닌 신청 유형 |
| `userKeywords` | 사용자가 추가한 검색 키워드 |
| `collectedAt` | 마지막 생성 시각 |

## 7. 출처

- 중소벤처기업부 2026 창업패키지 유형 및 딥테크 5대 분야 보도자료  
  https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1064518&cbIdx=86&parentSeq=1064518
- 예비창업패키지 2026 모집공고  
  https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1066579&cbIdx=310
- 예비창업패키지 수정 공고 PDF  
  https://www.mss.go.kr/common/board/Download.do?bcIdx=1066579&cbIdx=310&streFileNm=236d517e-fc4d-4607-8ba0-6b2557afeb62.pdf
- 재도전성공패키지 2026 모집공고  
  https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1065552&cbIdx=310
- 초기창업패키지 일반형 2026 모집공고  
  https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1065015&cbIdx=310
- 초기창업패키지 딥테크 특화형 2026 모집공고  
  https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1064566&cbIdx=310

## 8. 활용 방법

`keyword_list`은 시장조사의 시작점이다.

1. `market_crawler.py init-keywords`가 공식 사업별 분야 기준과 기존 사용자 키워드를 보존해 `output/keyword_list.json`을 만든다.
2. `market_crawler.py crawl-kiet`가 `keyword_list.json`의 키워드로 KIET SummaryPop 본문을 수집해 `output/raw_kiet_results.json`을 만든다.
3. `market_crawler.py build-report`가 원천 수집 결과를 사업계획서 Agent가 읽기 쉬운 `output/results.json`으로 변환한다.
4. `market_crawler.py add-keyword "키워드"`가 사용자 키워드를 추가하고, KIET 수집·보고서 생성을 다시 실행하며 `output/keyword_history.json`에는 같은 키워드를 중복 누적하지 않고 최신 실행 결과로 덮어쓴다.

사업계획서 작성 Agent는 이 데이터를 사용할 때 공식 분야와 사용자 키워드를 구분해야 한다. 특히 `userKeywords`는 사용자가 관심 시장을 검색하기 위한 값이며, 공고상 공식 산업 분류가 아니다.

## 9. 한계와 검증 상태

이 데이터는 공식 페이지와 PDF에서 분야 명칭이 존재하는지 확인한 뒤 JSON으로 저장한 결과다. 다만 공고 원문의 세부 신청 자격, 제외 업종, 우대 조건까지 모두 해석한 것은 아니다.

`industryId`는 내부 처리를 위한 생성 ID다. 공고 원문에 존재하는 공식 코드가 아니다.

최종 사업계획서 작성 전에는 각 사업의 최신 공고 PDF를 다시 열어 신청 자격과 제외 업종을 확인해야 한다.
