# 가산점 "확실한 것만 남기기" 전후 비교

- 만든 시각 2026-10-07T02:41:47.002504+00:00 · 기준일 2026-10-07 · 열린 공고 1741건 · 가점 행 2077건(extract_bonus/v4 gpt-5.6-luna medium) · 공용 DB SELECT 만
- 예전 = `bonus_before_20261007pm.py`, 새 = 작업 폴더 `search/bonus.py`

| 가상 신청자 | 예전 null · 0 · 있음 | 새 null · 0 · 있음 | 바뀐 것 |
|---|---|---|---|
| 속성 없음 | 719 · 1022 · 0 | 719 · 1022 · 0 | - |
| 여성 · 서울 | 706 · 1035 · 0 | 707 · 1034 · 0 | 0 → null 1 |
| 여성기업 · 벤처기업 · 경기 성남시 | 701 · 1033 · 7 | 706 · 1032 · 3 | 0 → null 1, 가산점 있음 → null 4 |
| 남성 · 장애인기업 · 이노비즈 · 전남광주 | 701 · 1033 · 7 | 706 · 1032 · 3 | 0 → null 1, 가산점 있음 → null 4 |

## 재검수 예시

- bizinfo:PBLN_000000000123858 · 벤처기업 · 여성기업: 예전 (4.0, [{'name': '여성기업', 'points': 3.0}, {'name': '벤처기업', 'points': 1.0}]) → 새 (None, [])
- bizinfo:PBLN_000000000117751 · 충남 천안시 · 여성기업: 예전 (None, []) → 새 (None, [])

## 재검수가 짚은 공고(가상 신청자 4명)

- bizinfo:PBLN_000000000123858 (found, 불확실 0개): 속성 없음 0→0; 여성 · 서울 0→0; 여성기업 · 벤처기업 · 경기 성남시 4.0→None; 남성 · 장애인기업 · 이노비즈 · 전남광주 1.0→None
- bizinfo:PBLN_000000000117751 (found, 불확실 3개): 속성 없음 None→None; 여성 · 서울 None→None; 여성기업 · 벤처기업 · 경기 성남시 None→None; 남성 · 장애인기업 · 이노비즈 · 전남광주 None→None
- bizinfo:PBLN_000000000126562 (found, 불확실 2개): 속성 없음 None→None; 여성 · 서울 None→None; 여성기업 · 벤처기업 · 경기 성남시 None→None; 남성 · 장애인기업 · 이노비즈 · 전남광주 None→None
- bizinfo:PBLN_000000000125856 (found, 불확실 1개): 속성 없음 None→None; 여성 · 서울 None→None; 여성기업 · 벤처기업 · 경기 성남시 None→None; 남성 · 장애인기업 · 이노비즈 · 전남광주 None→None
- bizinfo:PBLN_000000000126504 (none, 불확실 1개): 속성 없음 None→None; 여성 · 서울 None→None; 여성기업 · 벤처기업 · 경기 성남시 None→None; 남성 · 장애인기업 · 이노비즈 · 전남광주 None→None
- bizinfo:PBLN_000000000125935 (found, 불확실 2개): 속성 없음 None→None; 여성 · 서울 None→None; 여성기업 · 벤처기업 · 경기 성남시 None→None; 남성 · 장애인기업 · 이노비즈 · 전남광주 None→None
- bizinfo:PBLN_000000000117356 (found, 불확실 1개): 속성 없음 None→None; 여성 · 서울 None→None; 여성기업 · 벤처기업 · 경기 성남시 8.0→None; 남성 · 장애인기업 · 이노비즈 · 전남광주 5.0→None
- bizinfo:PBLN_000000000117928 (found, 불확실 0개): 속성 없음 None→None; 여성 · 서울 None→None; 여성기업 · 벤처기업 · 경기 성남시 1.0→1.0; 남성 · 장애인기업 · 이노비즈 · 전남광주 None→None
- bizinfo:PBLN_000000000120481 (found, 불확실 0개): 속성 없음 None→None; 여성 · 서울 None→None; 여성기업 · 벤처기업 · 경기 성남시 10.0→10.0; 남성 · 장애인기업 · 이노비즈 · 전남광주 10.0→10.0
- bizinfo:PBLN_000000000122057 (found, 불확실 1개): 속성 없음 None→None; 여성 · 서울 None→None; 여성기업 · 벤처기업 · 경기 성남시 10.0→None; 남성 · 장애인기업 · 이노비즈 · 전남광주 10.0→None
- bizinfo:PBLN_000000000122147 (found, 불확실 0개): 속성 없음 None→None; 여성 · 서울 None→None; 여성기업 · 벤처기업 · 경기 성남시 1.0→1.0; 남성 · 장애인기업 · 이노비즈 · 전남광주 1.0→1.0
- bizinfo:PBLN_000000000122309 (found, 불확실 2개): 속성 없음 None→None; 여성 · 서울 None→None; 여성기업 · 벤처기업 · 경기 성남시 4.0→None; 남성 · 장애인기업 · 이노비즈 · 전남광주 1.0→None
- bizinfo:PBLN_000000000126642 (found, 불확실 0개): 속성 없음 None→None; 여성 · 서울 None→None; 여성기업 · 벤처기업 · 경기 성남시 None→None; 남성 · 장애인기업 · 이노비즈 · 전남광주 5.0→5.0
