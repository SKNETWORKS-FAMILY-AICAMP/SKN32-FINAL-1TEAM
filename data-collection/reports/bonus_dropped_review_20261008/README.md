# 가산점: AI는 뽑았지만 계산이 버린 경우 — 하나씩 보기 (2026-10-08)

- 범위: 지금 열린 공고 중 가점을 찾은(found) 공고에서, AI가 뽑은 항목이 신청자에게 해당하고 점수도 있는데 공고 결과가 "모름"인 경우. **55개 공고·150개 항목**(`cases.json`). 공용 DB SELECT만.
- 판정: Claude 첫 판단(**AI 참고**, 사람 정답 아님). A = 규칙 하나만 바꾸면 통과 가능, B = 원문 표를 봐야 정할 수 있음, C = 막는 게 맞음(입력으로 확인할 수 없는 조건).
- 계산 규칙은 바꾸지 않았다. A로 정한 것도 규칙을 바꾸고(계획 → 승인) 원문 대조 목록에 넣어야 화면·순위에 나간다.

## A. 통과 가능 (12건)

| 공고 | 막힌 이유(계산) | 판단 | 왜 |
|---|---|---|---|
| [117162 [경북] 2026년 창업 및 경쟁력강화 사업자금 지원 계획 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000117162) | AI 불확실 메모 | 통과 가능 | 메모는 "경영혁신형 중소기업 배점" 표가 깨졌다는 것 — 장애인·여성·사회적·벤처 각 3점은 근거에 분명(한도 5) |
| [118974 2026년 중소기업 기술침해 손해액 산정 지원사업 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000118974) | AI 불확실 메모 | 통과 가능 | 메모는 "기타(최대 2점)" 줄이 끊겼다는 것 — 벤처·이노비즈·메인비즈·여성·장애인 각 1점은 근거에 분명 |
| [119636 [세종] 2026년 중소기업육성자금 지원계획 변경 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000119636) | AI 불확실 메모 | 통과 가능 | 메모는 ⑱ 녹색기업·지역인재 줄이 잘렸다는 것 — 여성기업·장애인기업 5점은 근거에 분명 |
| [125856 [세종] 2026년 2차 중소기업육성자금 지원계획 변경 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000125856) | AI 불확실 메모 | 통과 가능 | 메모는 ⑱ 녹색기업·지역인재 줄이 잘렸다는 것 — 여성기업·장애인기업 5점은 근거에 분명 |
| [124915 [대전] 2026년 하반기 중소기업 창업 및 경쟁력강화사업자금 지원 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000124915) | AI 불확실 메모 | 통과 가능 | 메모는 ⑭ 녹색기업 줄이 잘렸다는 것 — 여성기업·장애인기업 5점은 근거에 분명 |
| [121208 2026년 해외지사화사업 참여기업 모집 재수정 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000121208) | AI 불확실 메모 | 통과 가능(일부) | 사회적 경제기업(사회적·예비사회적기업·협동조합·소셜벤처) 5점은 분명. 청년친화("및")·가족친화("&")는 그대로 모름 |
| [119754 2026년 팁스(TIPS) 창업기업 지원계획 수정 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000119754) | 확인 못 하는 조건 말(이상·이하·기준·한함…) | 통과 가능 | "벤처기업 인증 또는 이노비즈 인증을 받은 경우 1점" — 조건 말 "경우"가 걸렸을 뿐, 조건은 인증 자체 |
| [126046 2026년 4차 과학기술분야 R&D 대체인력 활용 지원사업 모집 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000126046) | 확인 못 하는 조건 말(이상·이하·기준·한함…) | 통과 가능 | "기관이 여성기업인 경우 1" — 조건 말 "경우"가 걸렸을 뿐(표 배점 칸) |
| [126848 [경북] 포항시 2026년 4차 외국인 근로자 기숙사 환경개선 지원 대상](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000126848) | 근거에 그 점수가 없음/여러 점수 | 통과 가능 | "(장애인기업, 여성기업, 가족친화인증기업, 사회적기업 …) (5) ∘우대기업(1개 이상) : 5" — 같은 숫자 5가 두 번 나와 "숫자 하나" 조건에 걸림. 1개 이상이면 5점 |
| [126856 [경북] 울진군 2026년 4차 외국인 근로자 기숙사 등 시설 환경개선 ](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000126856) | 근거에 그 점수가 없음/여러 점수 | 통과 가능 | "(장애인기업, 여성기업, 가족친화인증기업, 사회적기업 …) (5) ∘우대기업(1개 이상) : 5" — 같은 숫자 5가 두 번 나와 "숫자 하나" 조건에 걸림. 1개 이상이면 5점 |
| [122724 [충북] 청주시 2026년 2차 공정혁신시뮬레이션센터 구축 및 운영사업 ](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000122724) | 근거에 그 점수가 없음/여러 점수 | 통과 가능 | "뿌리기업, 여성기업, 장애인기업 예(1) 아니오(0)" — 해당하면 1점. "아니오(0)" 때문에 숫자가 둘로 걸림 |
| [123858 2026년 바이오ㆍ메디컬 패키지지원 프로그램 참여기업 모집 공고(특화역량](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000123858) | 근거에 그 점수가 없음/여러 점수 | 통과 가능(일부) | "벤처·이노비즈·메인비즈 각 1점, 여성기업 3점" — 여성기업 3점은 주인이 분명. 한 근거에 점수가 둘이라 통째로 막힘 |

## B. 원문 확인 필요 (24건)

| 공고 | 막힌 이유(계산) | 판단 | 왜 |
|---|---|---|---|
| [117751 [충남] 2026년 중소기업육성자금 융자 지원계획 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000117751) | 근거에 그 점수가 없음/여러 점수 | 원문 확인 | 근거에 점수가 없음(표의 떨어진 배점 칸) — 원문 표에서 행·점수 짝을 봐야 함 |
| [118209 2026년 중소기업 연구인력지원사업 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000118209) | 근거에 그 점수가 없음/여러 점수 | 원문 확인 | "여성기업"만 근거 — 점수 1은 다른 칸 |
| [119409 [경남] 2026 중소기업 통ㆍ번역 지원사업 참가업체 모집 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000119409) | 근거에 그 점수가 없음/여러 점수 | 원문 확인 | "A. 고용우수기업, …, 청년친화 강소기업 …" — A등급 점수가 근거 밖 |
| [119739 2026년 소상공인 온라인판로 지원사업 참여기업 모집공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000119739) | 근거에 그 점수가 없음/여러 점수 | 원문 확인 | 소상공인 판로 사업 같은 양식 5건 — "협동조합" 줄에 점수가 없음(표의 다른 칸). 한 건만 보면 다섯 건이 같이 정해짐 |
| [120821 2026년 디지털커머스 전문기관(소담스퀘어강원) 소상공인 모집 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000120821) | 근거에 그 점수가 없음/여러 점수 | 원문 확인 | 소상공인 판로 사업 같은 양식 5건 — "협동조합" 줄에 점수가 없음(표의 다른 칸). 한 건만 보면 다섯 건이 같이 정해짐 |
| [121480 2026년 TV홈쇼핑 및 데이터홈쇼핑 입점지원사업 소상공인 모집 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000121480) | 근거에 그 점수가 없음/여러 점수 | 원문 확인 | 소상공인 판로 사업 같은 양식 5건 — "협동조합" 줄에 점수가 없음(표의 다른 칸). 한 건만 보면 다섯 건이 같이 정해짐 |
| [126060 2026년 5차 소상공인 온라인쇼핑몰 판매지원(온라인쇼핑몰ㆍ로컬상품관) ](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000126060) | 근거에 그 점수가 없음/여러 점수 | 원문 확인 | 소상공인 판로 사업 같은 양식 5건 — "협동조합" 줄에 점수가 없음(표의 다른 칸). 한 건만 보면 다섯 건이 같이 정해짐 |
| [126982 2026년 5차 라이브커머스 제작ㆍ운영 사업 참여기업 모집 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000126982) | 근거에 그 점수가 없음/여러 점수 | 원문 확인 | 소상공인 판로 사업 같은 양식 5건 — "협동조합" 줄에 점수가 없음(표의 다른 칸). 한 건만 보면 다섯 건이 같이 정해짐 |
| [120512 [울산] 2026년 1차 통상변화 대응 중소기업 육성자금 지원계획 변경 ](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000120512) | AI 불확실 메모 | 원문 확인 | "여성기업 여성기업 확인증" 등 점수가 근거 밖 + 메모(사회공헌도 표) |
| [120618 [충북] 충주시 2026년 중소기업육성기금 지원계획 변경 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000120618) | AI 불확실 메모 | 원문 확인 | 점수가 근거 밖 + 메모("비제조업 표는 점수가 안 보인다") |
| [122373 2026년 과천시 중소기업 및 소상공인 육성자금 이자차액보전 지원계획 변](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000122373) | 근거에 그 점수가 없음/여러 점수 | 원문 확인 | 과천 — "벤처기업/여성기업/장애인기업/가족친화" 이름만, 10점은 다른 칸 |
| [122968 2026년 2차 안전일터 조성지원 사업 수정 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000122968) | 근거에 그 점수가 없음/여러 점수 | 원문 확인 | 이름만 근거, 점수는 표의 다른 칸 |
| [126362 [충북] 2026년 2차 미취업청년 취업연계 일경험 지원사업 참여기업 모](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000126362) | 근거에 그 점수가 없음/여러 점수 | 원문 확인 | 이름만 근거, 점수는 표의 다른 칸 |
| [126769 [경기] 광명시 2026년 상권친화형 도시조성 지원사업 사업 소상공인 분](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000126769) | 근거에 그 점수가 없음/여러 점수 | 원문 확인 | 이름만 근거, 점수는 표의 다른 칸 |
| [126796 [인천] 2026년 5차 지역상품 공공 조달정보 지원사업 맞춤형 조달 컨](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000126796) | 근거에 그 점수가 없음/여러 점수 | 원문 확인 | 이름만 근거, 점수는 표의 다른 칸 |
| [126926 2026년 대구국제기계산업대전 참가지원 모집 공고(생활지원을 위한 서비스](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000126926) | 근거에 그 점수가 없음/여러 점수 | 원문 확인 | 이름만 근거, 점수는 표의 다른 칸 |
| [124232 2026년 투ㆍ융자 연계 기술개발사업 지원계획 수정 공고(스케일업 팁스ㆍ](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000124232) | AI 불확실 메모 | 원문 확인 | "벤처기업 인증 또는 이노비즈 인증을 받은 경우" — 점수가 근거 밖 + 메모 |
| [124300 AIoT융합부품 성능검증시스템 고도화사업 수혜기업모집 수시 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000124300) | 근거에 그 점수가 없음/여러 점수 | 원문 확인 | "충북도내 기업(3점), 청주시 기업(5점)" — 청주 기업이 3+5인지 5만인지 원문 확인 |
| [126783 [경기] 2026년 우수 환경서비스업 선정을 위한 신청 접수 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000126783) | 근거에 그 점수가 없음/여러 점수 | 원문 확인 | "공공기관 인증: 이노비즈, 메인비즈, 벤처기업 … 등 1" — 인증마다 1점인지 통틀어 1점인지 |
| [126892 [경기] 2026년 중소기업 마케팅 지원사업 해외 오프라인 지원기업 모집](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000126892) | AI 불확실 메모 | 원문 확인 | "여성 기업, 장애인 기업" — 점수가 근거 밖 + 메모 |
| [126987 [경북] 2026년 푸드테크 로봇 플래그쉽 지역거점 구축 지원사업 통합 ](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000126987) | 근거에 그 점수가 없음/여러 점수 | 원문 확인 | "우대사항(20) - 경상북도 소재 기업 20" — 소재지 기준(본사?)과 우대사항이 가점인지 |
| [123160 [부산] 2026년 9차 중소기업 자금지원계획 변경 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000123160) | AI 불확실 메모 | 원문 확인 | 부산 — 메모가 "우대기업 점수 칸이 병합 셀인지 모르겠다"(계산 전체를 흔드는 메모). 표를 봐야 함 |
| [126643 [부산] 2026년 10차 중소기업ㆍ소상공인 자금지원계획 변경 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000126643) | AI 불확실 메모 | 원문 확인 | 부산 — 메모가 "우대기업 점수 칸이 병합 셀인지 모르겠다"(계산 전체를 흔드는 메모). 표를 봐야 함 |
| [122394 [제주] 2026년 전기차 사용 후 배터리 실증 지원사업(KC인증) 상시](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000122394) | 추가 조건 | 판단 필요 | 모든 가점에 "발표평가 60점 이상 과제에 한하여" — 문턱을 넘으면 받는 가점을 "확인된 가산점"으로 볼지 정책 판단 |

## C. 막는 게 맞음 (19건)

| 공고 | 막힌 이유(계산) | 판단 | 왜 |
|---|---|---|---|
| [117356 [전북] 2026년 중소기업육성자금 융자 지원계획 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000117356) | 앞으로의 조건 말 · 확인 못 하는 조건 말(이상·이하·기준·한함…) | 막는 게 맞음 | 공장 "이전하는" 기업(앞으로의 일), "본사 및 사업장 모두 도내"(입력으로 공장 위치 모름) |
| [126642 [전북] 2026년 중소기업 육성자금 융자 지원계획 수정 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000126642) | 앞으로의 조건 말 · 추가 조건 | 막는 게 맞음 | 공장 "이전하는" 기업(앞으로의 일), "본사 및 사업장 모두 도내"(입력으로 공장 위치 모름) |
| [127034 2026년 대전 웰컴 스테이 지원사업 참가기업 모집 연장 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000127034) | 근거가 원문과 그대로 안 이어짐 · 앞으로의 조건 말 | 막는 게 맞음 | 이전 예정·이전 완료·신규설립 — 입력으로 모름 |
| [124940 2026년 대경권(대구) 지역혁신클러스터육성(비R&D) 기업지원 수혜기업](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000124940) | 추가 조건 | 막는 게 맞음 | 이전 예정·이전 완료·신규설립 — 입력으로 모름 |
| [123291 [전북] 군산시 2026년 2차 AX얼라이언스 산ㆍ학ㆍ연 종합프로그램 지](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000123291) | 확인 못 하는 조건 말(이상·이하·기준·한함…) | 막는 게 맞음 | 컨소시엄·공급기업 소재지 — 신청 기업 자신이 아님 |
| [127017 [전북] 김제시 2026년 4차 미래 Special 차Car세대 성장프로](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000127017) | 근거에 그 점수가 없음/여러 점수 | 막는 게 맞음 | 컨소시엄·공급기업 소재지 — 신청 기업 자신이 아님 |
| [126558 [충북] 2026년 제조 AI 현장 적용 지원 사업 수혜기업 모집 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000126558) | 추가 조건 | 막는 게 맞음 | 컨소시엄·공급기업 소재지 — 신청 기업 자신이 아님 |
| [126911 [경북] 포항시 2026년 3차 경북형(포항) 스마트공장(기초단계) 구축](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000126911) | 근거에 그 점수가 없음/여러 점수 | 막는 게 맞음 | 컨소시엄·공급기업 소재지 — 신청 기업 자신이 아님 |
| [127014 [경북] 2026년 지역특화형(방산ㆍ모빌리티) 스마트공장 보급확산 사업(](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000127014) | 근거에 그 점수가 없음/여러 점수 | 막는 게 맞음 | 컨소시엄·공급기업 소재지 — 신청 기업 자신이 아님 |
| [126773 [경남] 2026년 스마트공장 기초구축 지원사업 추가모집 수정 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000126773) | 근거가 원문과 그대로 안 이어짐 | 막는 게 맞음 | 컨소시엄·공급기업 소재지 — 신청 기업 자신이 아님 |
| [120707 2026년 구미시 스타트업 제작센터 참여기업 모집 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000120707) | 근거에 그 점수가 없음/여러 점수 | 막는 게 맞음 | 근로자 거주 비율·거주 기간 — 입력에 없음 |
| [127032 [서울] 성북구 2026년 길음청년희망스토어 청년창업팀(12호점) 모집 ](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000127032) | 근거가 원문과 그대로 안 이어짐 | 막는 게 맞음 | 근로자 거주 비율·거주 기간 — 입력에 없음 |
| [125185 [강원] 2026년 하반기 중소기업 밀집지역 위기대응 체계 구축사업 St](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000125185) | 추가 조건 | 막는 게 맞음 | 매출·영업손실·종사자 수·거래처 수 기준 |
| [125271 [충남] 2026년 하반기 중소기업 밀집지역 위기대응 체계 구축사업 St](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000125271) | 근거가 원문과 그대로 안 이어짐 | 막는 게 맞음 | 매출·영업손실·종사자 수·거래처 수 기준 |
| [126672 2026년 4차 성능인증(EPC) 신규신청 접수 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000126672) | 근거가 원문과 그대로 안 이어짐 | 막는 게 맞음 | "없음 1개 2개 3개이상" — 해당 개수로 점수가 정해지는데 칸별 점수가 근거에 없음 |
| [126384 2026년 3차 디지털혁신기술국제공동연구사업 신규지원 대상과제 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000126384) | 근거에 그 점수가 없음/여러 점수 · 추가 조건 | 막는 게 맞음 | "최근 3년 이내" 선정, "공동대표는 모두 여성" |
| [125705 [충북] 2026년 2차 중소기업육성자금 융자(이차보전) 지원계획 변경 ](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000125705) | AI 불확실 메모 | 막는 게 맞음 | 여성 항목이 3점·5점·10점(전용단지 입주) 여러 줄에 걸치고 "중복적용 불가" — 어느 점수인지 입력으로 못 정함 + 메모 |
| [120238 [울산] 2026년 중소기업 해외지사화 사업 참가기업 모집 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000120238) | "및·&" 결합 조건 | 막는 게 맞음 | "일자리 으뜸기업 및 청년친화 강소기업" — "및" 결합(결정 0016 사용자 결정) |
| [126819 [충남] 2026년 수원메가쇼 2026 시즌 2 참가 경영체 모집 공고](https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=PBLN_000000000126819) | 표 밖 증빙 기간 조건 | 막는 게 맞음 | 공고에 인증서 기간 조건(결정 0016 ②) — Codex가 짚은 사례 |
