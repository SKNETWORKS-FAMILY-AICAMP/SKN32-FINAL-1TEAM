# 업종 순위 신호 안전 확인

- 정상 질의 58개 × 대표 업종 6개. 상위 10 기준. 후보 깊이 50. OpenAI 0 · DB 쓰기 0
- 업종 결과 industry_llm_full_luna_20260928_final5: 순위에 쓰는 공고 329건 / 공고 2476건
- **불변식 위반 324건** (공고가 빠짐 · 근거 없는 밀림)

| 신청자 업종 | 대분류 | 쌍 | 상위 10에서 밀린 쌍 | 상위 10이 바뀐 쌍 | 밀린 칸 |
|---|---|---:|---:|---:|---:|
| 제조업 | C | 58 | 0 | 22 | 0 |
| 음식점업 | I | 58 | 0 | 33 | 0 |
| 정보통신업 | J | 58 | 0 | 29 | 0 |
| 농업 | A | 58 | 0 | 38 | 0 |
| 건설업 | F | 58 | 0 | 43 | 0 |
| 도소매업 | G | 58 | 0 | 32 | 0 |

## 밀린 공고 (눈 검토용 — 허용 업종 추출이 맞는지 본다)

| 공고 | 허용 업종(원문) | 대분류 | 밀린 쌍 | 주제 판정 2 |
|---|---|---|---:|---:|

## 위반

- {"qid": "q001", "industry": "제조업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000123753", "bizinfo:PBLN_000000000124903", "bizinfo:PBLN_000000000125888"]}
- {"qid": "q001", "industry": "음식점업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000123753", "bizinfo:PBLN_000000000124248", "bizinfo:PBLN_000000000124779", "bizinfo:PBLN_000000000125888", "bizinfo:PBLN_000000000125913", "bizinfo:PBLN_000000000126103", "bizinfo:PBLN_000000000126512"]}
- {"qid": "q001", "industry": "정보통신업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000123764", "bizinfo:PBLN_000000000124248", "bizinfo:PBLN_000000000124779", "bizinfo:PBLN_000000000125913", "bizinfo:PBLN_000000000126103", "bizinfo:PBLN_000000000126512", "bizinfo:PBLN_000000000126513"]}
- {"qid": "q001", "industry": "농업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000120385", "bizinfo:PBLN_000000000123753", "bizinfo:PBLN_000000000124248", "bizinfo:PBLN_000000000124779", "bizinfo:PBLN_000000000125913", "bizinfo:PBLN_000000000126103", "bizinfo:PBLN_000000000126512", "bizinfo:PBLN_000000000126513"]}
- {"qid": "q001", "industry": "건설업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000123753", "bizinfo:PBLN_000000000123764", "bizinfo:PBLN_000000000124248", "bizinfo:PBLN_000000000124779", "bizinfo:PBLN_000000000125888", "bizinfo:PBLN_000000000125913", "bizinfo:PBLN_000000000126103", "bizinfo:PBLN_000000000126512", "bizinfo:PBLN_000000000126513"]}
- {"qid": "q001", "industry": "도소매업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000122357", "bizinfo:PBLN_000000000123753", "bizinfo:PBLN_000000000124248", "bizinfo:PBLN_000000000124779", "bizinfo:PBLN_000000000125888", "bizinfo:PBLN_000000000125913", "bizinfo:PBLN_000000000126103", "bizinfo:PBLN_000000000126512", "bizinfo:PBLN_000000000126513"]}
- {"qid": "q002", "industry": "음식점업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000120385", "bizinfo:PBLN_000000000124708", "bizinfo:PBLN_000000000126103"]}
- {"qid": "q002", "industry": "정보통신업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000120385", "bizinfo:PBLN_000000000123299", "bizinfo:PBLN_000000000124708", "bizinfo:PBLN_000000000124779", "bizinfo:PBLN_000000000126103", "bizinfo:PBLN_000000000126512"]}
- {"qid": "q002", "industry": "농업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000117162", "bizinfo:PBLN_000000000120385", "bizinfo:PBLN_000000000122368", "bizinfo:PBLN_000000000123299", "bizinfo:PBLN_000000000124708", "bizinfo:PBLN_000000000124779", "bizinfo:PBLN_000000000125303", "bizinfo:PBLN_000000000126103", "bizinfo:PBLN_000000000126132", "bizinfo:PBLN_000000000126489"]}
- {"qid": "q002", "industry": "건설업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000117162", "bizinfo:PBLN_000000000120385", "bizinfo:PBLN_000000000123299", "bizinfo:PBLN_000000000124708", "bizinfo:PBLN_000000000124779", "bizinfo:PBLN_000000000126103"]}
- {"qid": "q002", "industry": "도소매업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000117162", "bizinfo:PBLN_000000000120385", "bizinfo:PBLN_000000000123299", "bizinfo:PBLN_000000000124708", "bizinfo:PBLN_000000000126103"]}
- {"qid": "q003", "industry": "제조업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000123753"]}
- {"qid": "q003", "industry": "음식점업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000120786", "bizinfo:PBLN_000000000121103", "bizinfo:PBLN_000000000121288", "bizinfo:PBLN_000000000123753", "bizinfo:PBLN_000000000125916", "bizinfo:PBLN_000000000126499", "kstartup:176085"]}
- {"qid": "q003", "industry": "정보통신업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000120786", "bizinfo:PBLN_000000000121103", "bizinfo:PBLN_000000000121288", "bizinfo:PBLN_000000000124248", "bizinfo:PBLN_000000000125913", "bizinfo:PBLN_000000000125916", "bizinfo:PBLN_000000000126499", "bizinfo:PBLN_000000000126512"]}
- {"qid": "q003", "industry": "농업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000117943", "bizinfo:PBLN_000000000120786", "bizinfo:PBLN_000000000121103", "bizinfo:PBLN_000000000121288", "bizinfo:PBLN_000000000123753", "bizinfo:PBLN_000000000125916", "bizinfo:PBLN_000000000126499"]}
- {"qid": "q003", "industry": "건설업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000117943", "bizinfo:PBLN_000000000120786", "bizinfo:PBLN_000000000121103", "bizinfo:PBLN_000000000123753", "bizinfo:PBLN_000000000125916", "bizinfo:PBLN_000000000126499"]}
- {"qid": "q003", "industry": "도소매업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000117943", "bizinfo:PBLN_000000000120786", "bizinfo:PBLN_000000000123753", "bizinfo:PBLN_000000000125916", "bizinfo:PBLN_000000000126499"]}
- {"qid": "q004", "industry": "제조업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000123753"]}
- {"qid": "q004", "industry": "음식점업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000123753", "bizinfo:PBLN_000000000126239"]}
- {"qid": "q004", "industry": "정보통신업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000126572"]}
- {"qid": "q004", "industry": "농업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000117162", "bizinfo:PBLN_000000000123753", "kstartup:179094"]}
- {"qid": "q004", "industry": "건설업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000117162", "bizinfo:PBLN_000000000123753", "kstartup:179094"]}
- {"qid": "q004", "industry": "도소매업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000117162", "bizinfo:PBLN_000000000123753", "bizinfo:PBLN_000000000125916"]}
- {"qid": "q005", "industry": "음식점업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000123753"]}
- {"qid": "q005", "industry": "농업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000122906"]}
- {"qid": "q005", "industry": "건설업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000122906"]}
- {"qid": "q005", "industry": "도소매업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000122906", "bizinfo:PBLN_000000000123753"]}
- {"qid": "q006", "industry": "제조업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000122153", "kstartup:176248"]}
- {"qid": "q006", "industry": "음식점업", "kind": "후보 집합이 달라짐", "missing": ["kstartup:176248"]}
- {"qid": "q006", "industry": "정보통신업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000122153", "kstartup:176248"]}
- {"qid": "q006", "industry": "농업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000122153", "kstartup:176248", "kstartup:179094"]}
- {"qid": "q006", "industry": "건설업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000122153", "kstartup:176248", "kstartup:179094"]}
- {"qid": "q006", "industry": "도소매업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000122153", "kstartup:176248", "kstartup:179094"]}
- {"qid": "q007", "industry": "제조업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000120474", "bizinfo:PBLN_000000000123513"]}
- {"qid": "q007", "industry": "음식점업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000120474", "bizinfo:PBLN_000000000121288"]}
- {"qid": "q007", "industry": "정보통신업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000120474", "bizinfo:PBLN_000000000123513"]}
- {"qid": "q007", "industry": "농업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000120474", "bizinfo:PBLN_000000000123513"]}
- {"qid": "q007", "industry": "건설업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000120474", "bizinfo:PBLN_000000000123513"]}
- {"qid": "q007", "industry": "도소매업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000123513"]}
- {"qid": "q008", "industry": "제조업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000123753", "bizinfo:PBLN_000000000124903", "kstartup:179094"]}
- {"qid": "q008", "industry": "음식점업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000123753", "bizinfo:PBLN_000000000124903", "bizinfo:PBLN_000000000126342", "bizinfo:PBLN_000000000126531", "kstartup:179094"]}
- {"qid": "q008", "industry": "정보통신업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000124903", "bizinfo:PBLN_000000000126342"]}
- {"qid": "q008", "industry": "농업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000117162", "bizinfo:PBLN_000000000124903", "bizinfo:PBLN_000000000125920", "bizinfo:PBLN_000000000126342", "kstartup:179094"]}
- {"qid": "q008", "industry": "건설업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000124779", "bizinfo:PBLN_000000000124903", "bizinfo:PBLN_000000000125920", "bizinfo:PBLN_000000000126342", "kstartup:179094"]}
- {"qid": "q008", "industry": "도소매업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000123753", "bizinfo:PBLN_000000000124903", "bizinfo:PBLN_000000000126342", "bizinfo:PBLN_000000000126531", "kstartup:179094"]}
- {"qid": "q009", "industry": "제조업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000122968", "kstartup:179094"]}
- {"qid": "q009", "industry": "음식점업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000122968", "bizinfo:PBLN_000000000123841"]}
- {"qid": "q009", "industry": "정보통신업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000122968", "bizinfo:PBLN_000000000124779"]}
- {"qid": "q009", "industry": "농업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000120010", "bizinfo:PBLN_000000000122968", "bizinfo:PBLN_000000000124779", "bizinfo:PBLN_000000000126513", "kstartup:179094"]}
- {"qid": "q009", "industry": "건설업", "kind": "후보 집합이 달라짐", "missing": ["bizinfo:PBLN_000000000123841", "bizinfo:PBLN_000000000124779"]}
