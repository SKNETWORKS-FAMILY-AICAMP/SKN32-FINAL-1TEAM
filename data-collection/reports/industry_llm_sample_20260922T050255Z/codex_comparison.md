# 업종 추출 대조 — Codex 판정 기준 (사람 정답 아님)

- 기준: `label_sheet_codex.csv` 30건(known 13 · unknown 17 · no_limit 0, 확신도 낮음 3건). **AI 참고 정답이다.**
- Codex 는 판정 전에 Claude 의 v3 요약 일부가 도구 출력에 노출됐다고 기록했다 — 완전한 블라인드가 아니다.
- 값 대조: 공백·가운뎃점 제거 후 포함 관계. 어휘 라벨(제조업)은 어간(제조) 포함도 같은 값.

## 전체 30건

| 방식 | 상태 일치 | 둘 다 known | 방식만 known | Codex 만 known | 값 정밀도 | 값 재현율 | 규모 표현 값 |
|---|---:|---:|---:|---:|---:|---:|---:|
| regex | 17/30 | 0 | 0 | 13 | - | - | 0 |
| v1 | 21/30 | 12 | 8 | 1 | 0.50 | 0.36 | 0 |
| v2 | 23/30 | 7 | 1 | 6 | 0.83 | 0.50 | 0 |
| v3 | 20/30 | 8 | 5 | 5 | 0.92 | 0.46 | 6 |
| luna | 24/30 | 7 | 0 | 6 | 1.00 | 1.00 | 0 |
| full_strict | 23/30 | 6 | 0 | 7 | 1.00 | 1.00 | 0 |
| full_rough | 26/30 | 9 | 0 | 4 | 0.97 | 1.00 | 0 |

## Codex 확신도 높음만 (27건)

| 방식 | 상태 일치 | 둘 다 known | 방식만 known | Codex 만 known | 값 정밀도 | 값 재현율 | 규모 표현 값 |
|---|---:|---:|---:|---:|---:|---:|---:|
| regex | 16/27 | 0 | 0 | 11 | - | - | 0 |
| v1 | 19/27 | 10 | 7 | 1 | 0.56 | 0.40 | 0 |
| v2 | 21/27 | 6 | 1 | 5 | 0.88 | 0.56 | 0 |
| v3 | 18/27 | 6 | 4 | 5 | 1.00 | 0.40 | 5 |
| luna | 22/27 | 6 | 0 | 5 | 1.00 | 1.00 | 0 |
| full_strict | 20/27 | 4 | 0 | 7 | 1.00 | 1.00 | 0 |
| full_rough | 23/27 | 7 | 0 | 4 | 0.97 | 1.00 | 0 |

v3 목록완전 대조(둘 다 known, 방식→Codex): N→N 3, N→Y 2, Y→N 1, Y→Y 2
luna 목록완전 대조(둘 다 known, 방식→Codex): N→N 1, Y→N 1, Y→Y 5
full_strict 목록완전 대조(둘 다 known, 방식→Codex): N→N 1, Y→N 1, Y→Y 4
full_rough 목록완전 대조(둘 다 known, 방식→Codex): N→N 2, N→Y 1, Y→N 1, Y→Y 5

## 공고별

| # | 공고 | Codex | v2 | v3 | luna | 전량 엄격 | 전량 러프 | 러프 허용 값 | Codex 허용 값 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 116998 | unknown | unknown | unknown | unknown | unknown | unknown |  |  |
| 2 | 117330 | unknown | unknown | known ✗ | unknown | unknown | unknown |  |  |
| 3 | 117568 | unknown | known ✗ | known ✗ | unknown | unknown | unknown |  |  |
| 4 | 117600 | known | known | known | known | unknown ✗ | known | 제조업; 지식·정보 관련업; 광업; 건설업; 관광업; 도·소매업; 숙박업; 이미용업; 목욕 | 제조업; 지식·정보 관련업; 광업; 건설업; 관광업; 도·소매업; 숙박업; 이미용업; 목욕 |
| 5 | 117666 | unknown | unknown | unknown | unknown | unknown | unknown |  |  |
| 6 | 117972 | unknown | unknown | unknown | unknown | unknown | unknown |  |  |
| 7 | 119026 | unknown | unknown | unknown | unknown | unknown | unknown |  |  |
| 8 | 120031 | unknown | unknown | unknown | unknown | unknown | unknown |  |  |
| 9 | 122801 | known | known | known | unknown ✗ | unknown ✗ | unknown ✗ |  | 농식품(신선농산물 및 가공농산물) 수출기업 및 농가 |
| 10 | 123905 | known | unknown ✗ | known | unknown ✗ | unknown ✗ | unknown ✗ |  | 충북 주력산업 영위기업 |
| 11 | 124849 | unknown (낮음) | unknown | known ✗ | unknown | unknown | unknown |  |  |
| 12 | 125621 | known | unknown ✗ | unknown ✗ | unknown ✗ | unknown ✗ | unknown ✗ |  | 헬스케어; 로봇; 미래모빌리티; ABB; 반도체 |
| 13 | 125665 | unknown | unknown | unknown | unknown | unknown | unknown |  |  |
| 14 | 125687 | known | known | known | known | unknown ✗ | known | 제조; 무역업 | 제조 및 무역업 |
| 15 | 125723 | unknown | unknown | known ✗ | unknown | unknown | unknown |  |  |
| 16 | 125978 | known | known | unknown ✗ | unknown ✗ | unknown ✗ | known | 제조기업; 식품; 뷰티; 제약; 자동차부품; 섬유·패션; 생활 소비재(Life); 기계·장 | 식품; 뷰티; 제약; 자동차부품; 섬유·패션; 생활 소비재(Life); 기계·장비; 금속가 |
| 17 | 126157 | known (낮음) | unknown ✗ | known | unknown ✗ | known | known | 충남지역 주축산업 영위 기업; 관련 기업 | 충남지역 주축산업 영위 기업 및 관련 기업 |
| 18 | 126183 | known (낮음) | known | known | known | known | known | 생활밀접업종; 100대 생활업종; 택시 및 화물자동차 운송업 | 인천광역시 소상공인통계 생활밀접업종; 국세청에서 선정한 100대 생활업종; 택시 및 화물자 |
| 19 | 126296 | unknown | unknown | known ✗ | unknown | unknown | unknown |  |  |
| 20 | 126362 | unknown | unknown | unknown | unknown | unknown | unknown |  |  |
| 21 | 126368 | known | unknown ✗ | unknown ✗ | unknown ✗ | unknown ✗ | unknown ✗ |  | 국방분야에 적용 가능한 기술이나 품목을 보유하고 군 사업화를 추진 또는 희망하는 |
| 22 | 126402 | unknown | unknown | unknown | unknown | unknown | unknown |  |  |
| 23 | 126403 | known | known | known | known | known | known | 바이오 분야 | 바이오 분야 |
| 24 | 126470 | known | unknown ✗ | unknown ✗ | known | known | known | 뷰티·헬스케어 분야 | 뷰티·헬스케어 분야 |
| 25 | 126488 | known | known | known | known | known | known | 여행사; 관광숙박업소; 관광체험관 | 여행사; 관광숙박업소; 관광체험관 |
| 26 | 126497 | unknown | unknown | unknown | unknown | unknown | unknown |  |  |
| 27 | 179125 | unknown | unknown | unknown | unknown | unknown | unknown |  |  |
| 28 | 179172 | known | unknown ✗ | unknown ✗ | known | known | known | IT·SW 및 이에 준하는 기술분야 | IT·SW 및 이에 준하는 기술분야 |
| 29 | 179245 | unknown | unknown | unknown | unknown | unknown | unknown |  |  |
| 30 | 179297 | unknown | unknown | unknown | unknown | unknown | unknown |  |  |
