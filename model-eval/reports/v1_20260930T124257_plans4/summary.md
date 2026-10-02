# 검증-1 모델 비교 결과

- 총점은 항목 점수 합(코드 계산, 만점 70). 반복은 같은 입력 재호출이다.
- 순서 맞힘: 변형 평균 총점이 원본보다 뚜렷하게(총점 만점의 5% 이상) 낮은 변형의 비율.
- 원인 짚기: 깎여야 할 항목의 평균 점수가 원본보다 뚜렷하게(항목 만점의 10% 이상) 낮아진 (변형, 항목) 비율.
- 깎은 폭: 깎여야 할 항목이 원본보다 항목 만점의 몇 %나 내려갔나(평균, 클수록 정확). 없는 섹션에 점수를 그대로 주면 낮게 나온다.
- 흔들림: 같은 입력 반복 총점의 표준편차 평균(작을수록 안정). 추론 모델은 온도 0을 쓸 수 없다.

| 후보 | 호출 | 성공 | 형식 통과 | 원본 평균 | 순서 맞힘 | 원인 짚기 | 깎은 폭 | 흔들림 | 평균 시간(s) | 평균 추론 토큰 | 비용($) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gpt-4.1-mini | 72 | 72 | 72 | 68.8 | 20/20 | 16/16 | 74% | 0.53 | 5.9 | 0 | 0.132 |
| luna-low | 72 | 72 | 72 | 66.0 | 20/20 | 16/16 | 80% | 0.81 | 7.3 | 47 | 0.099 |
| luna-medium | 72 | 72 | 72 | 66.0 | 20/20 | 16/16 | 85% | 0.88 | 7.6 | 97 | 0.107 |
| luna-high | 72 | 72 | 72 | 66.0 | 20/20 | 16/16 | 85% | 0.86 | 9.9 | 266 | 0.120 |
| luna6-medium | 72 | 72 | 72 | 63.7 | 20/20 | 16/16 | 83% | 1.05 | 8.3 | 189 | 0.046 |

## 변형별 총점

| 후보 | 계획서 | 변형 | 평균 | 반복별 |
|---|---|---|---:|---|
| gpt-4.1-mini | base_01 | drop_E3 | 63.7 | 64.0, 63.5, 63.5 |
| gpt-4.1-mini | base_01 | drop_E5 | 58.0 | 58.0, 58.0, 58.0 |
| gpt-4.1-mini | base_01 | halved | 65.3 | 65.0, 66.0, 65.0 |
| gpt-4.1-mini | base_01 | offtopic_E2 | 53.0 | 53.0, 53.0, 53.0 |
| gpt-4.1-mini | base_01 | original | 69.0 | 69.0, 69.0, 69.0 |
| gpt-4.1-mini | base_01 | unsourced_E3 | 59.7 | 59.5, 59.5, 60.0 |
| gpt-4.1-mini | base_02 | drop_E3 | 58.8 | 57.5, 59.5, 59.5 |
| gpt-4.1-mini | base_02 | drop_E5 | 58.0 | 58.0, 58.0, 58.0 |
| gpt-4.1-mini | base_02 | halved | 62.3 | 63.0, 62.0, 62.0 |
| gpt-4.1-mini | base_02 | offtopic_E2 | 55.0 | 55.0, 55.0, 55.0 |
| gpt-4.1-mini | base_02 | original | 69.0 | 69.0, 69.0, 69.0 |
| gpt-4.1-mini | base_02 | unsourced_E3 | 59.7 | 60.0, 59.5, 59.5 |
| gpt-4.1-mini | base_03 | drop_E3 | 61.5 | 62.5, 59.5, 62.5 |
| gpt-4.1-mini | base_03 | drop_E5 | 58.0 | 58.0, 58.0, 58.0 |
| gpt-4.1-mini | base_03 | halved | 63.0 | 62.0, 63.0, 64.0 |
| gpt-4.1-mini | base_03 | offtopic_E2 | 53.7 | 55.0, 55.0, 51.0 |
| gpt-4.1-mini | base_03 | original | 68.0 | 67.5, 68.5, 68.0 |
| gpt-4.1-mini | base_03 | unsourced_E3 | 57.8 | 57.5, 57.5, 58.5 |
| gpt-4.1-mini | base_04 | drop_E3 | 59.2 | 62.5, 57.5, 57.5 |
| gpt-4.1-mini | base_04 | drop_E5 | 58.7 | 58.5, 59.0, 58.5 |
| gpt-4.1-mini | base_04 | halved | 63.7 | 63.0, 63.0, 65.0 |
| gpt-4.1-mini | base_04 | offtopic_E2 | 51.8 | 53.0, 50.5, 52.0 |
| gpt-4.1-mini | base_04 | original | 69.0 | 69.0, 69.0, 69.0 |
| gpt-4.1-mini | base_04 | unsourced_E3 | 57.8 | 57.5, 58.5, 57.5 |
| luna-low | base_01 | drop_E3 | 57.0 | 59.0, 55.0, 57.0 |
| luna-low | base_01 | drop_E5 | 54.7 | 54.0, 56.0, 54.0 |
| luna-low | base_01 | halved | 54.0 | 55.0, 53.0, 54.0 |
| luna-low | base_01 | offtopic_E2 | 52.3 | 53.0, 52.0, 52.0 |
| luna-low | base_01 | original | 65.0 | 65.0, 65.0, 65.0 |
| luna-low | base_01 | unsourced_E3 | 55.0 | 55.0, 55.0, 55.0 |
| luna-low | base_02 | drop_E3 | 58.7 | 59.0, 58.0, 59.0 |
| luna-low | base_02 | drop_E5 | 55.7 | 57.0, 55.0, 55.0 |
| luna-low | base_02 | halved | 44.3 | 45.0, 43.0, 45.0 |
| luna-low | base_02 | offtopic_E2 | 51.3 | 51.0, 53.0, 50.0 |
| luna-low | base_02 | original | 66.3 | 67.0, 66.0, 66.0 |
| luna-low | base_02 | unsourced_E3 | 57.3 | 57.0, 57.0, 58.0 |
| luna-low | base_03 | drop_E3 | 57.0 | 56.0, 56.0, 59.0 |
| luna-low | base_03 | drop_E5 | 57.0 | 59.0, 56.0, 56.0 |
| luna-low | base_03 | halved | 43.0 | 45.0, 41.0, 43.0 |
| luna-low | base_03 | offtopic_E2 | 53.7 | 54.0, 53.0, 54.0 |
| luna-low | base_03 | original | 67.7 | 68.0, 68.0, 67.0 |
| luna-low | base_03 | unsourced_E3 | 56.0 | 56.0, 57.0, 55.0 |
| luna-low | base_04 | drop_E3 | 57.3 | 56.0, 58.0, 58.0 |
| luna-low | base_04 | drop_E5 | 55.7 | 54.0, 58.0, 55.0 |
| luna-low | base_04 | halved | 48.7 | 47.0, 50.0, 49.0 |
| luna-low | base_04 | offtopic_E2 | 49.7 | 50.0, 49.0, 50.0 |
| luna-low | base_04 | original | 65.0 | 65.0, 65.0, 65.0 |
| luna-low | base_04 | unsourced_E3 | 55.3 | 56.0, 55.0, 55.0 |
| luna-medium | base_01 | drop_E3 | 53.7 | 52.0, 54.0, 55.0 |
| luna-medium | base_01 | drop_E5 | 54.7 | 55.0, 55.0, 54.0 |
| luna-medium | base_01 | halved | 46.7 | 46.0, 48.0, 46.0 |
| luna-medium | base_01 | offtopic_E2 | 50.3 | 51.0, 49.0, 51.0 |
| luna-medium | base_01 | original | 64.7 | 64.0, 66.0, 64.0 |
| luna-medium | base_01 | unsourced_E3 | 54.3 | 54.0, 55.0, 54.0 |
| luna-medium | base_02 | drop_E3 | 53.7 | 52.0, 54.0, 55.0 |
| luna-medium | base_02 | drop_E5 | 54.3 | 55.0, 53.0, 55.0 |
| luna-medium | base_02 | halved | 39.0 | 37.0, 44.0, 36.0 |
| luna-medium | base_02 | offtopic_E2 | 50.0 | 50.0, 49.0, 51.0 |
| luna-medium | base_02 | original | 66.3 | 66.0, 66.0, 67.0 |
| luna-medium | base_02 | unsourced_E3 | 55.0 | 55.0, 55.0, 55.0 |
| luna-medium | base_03 | drop_E3 | 55.7 | 58.0, 54.0, 55.0 |
| luna-medium | base_03 | drop_E5 | 57.7 | 58.0, 57.0, 58.0 |
| luna-medium | base_03 | halved | 42.7 | 41.0, 40.0, 47.0 |
| luna-medium | base_03 | offtopic_E2 | 52.7 | 52.0, 54.0, 52.0 |
| luna-medium | base_03 | original | 67.3 | 66.0, 68.0, 68.0 |
| luna-medium | base_03 | unsourced_E3 | 54.3 | 54.0, 55.0, 54.0 |
| luna-medium | base_04 | drop_E3 | 55.0 | 55.0, 55.0, 55.0 |
| luna-medium | base_04 | drop_E5 | 54.0 | 54.0, 54.0, 54.0 |
| luna-medium | base_04 | halved | 45.0 | 45.0, 45.0, 45.0 |
| luna-medium | base_04 | offtopic_E2 | 49.7 | 49.0, 50.0, 50.0 |
| luna-medium | base_04 | original | 65.7 | 65.0, 66.0, 66.0 |
| luna-medium | base_04 | unsourced_E3 | 55.3 | 56.0, 55.0, 55.0 |
| luna-high | base_01 | drop_E3 | 55.3 | 55.0, 58.0, 53.0 |
| luna-high | base_01 | drop_E5 | 52.8 | 53.0, 52.5, 53.0 |
| luna-high | base_01 | halved | 43.7 | 43.0, 44.0, 44.0 |
| luna-high | base_01 | offtopic_E2 | 50.7 | 50.0, 52.0, 50.0 |
| luna-high | base_01 | original | 65.3 | 66.0, 65.0, 65.0 |
| luna-high | base_01 | unsourced_E3 | 56.0 | 55.0, 56.0, 57.0 |
| luna-high | base_02 | drop_E3 | 54.7 | 54.0, 54.0, 56.0 |
| luna-high | base_02 | drop_E5 | 55.8 | 54.0, 56.5, 57.0 |
| luna-high | base_02 | halved | 39.0 | 38.0, 39.0, 40.0 |
| luna-high | base_02 | offtopic_E2 | 50.0 | 52.0, 49.0, 49.0 |
| luna-high | base_02 | original | 65.0 | 65.0, 65.0, 65.0 |
| luna-high | base_02 | unsourced_E3 | 57.0 | 57.0, 57.0, 57.0 |
| luna-high | base_03 | drop_E3 | 57.0 | 56.0, 58.0, 57.0 |
| luna-high | base_03 | drop_E5 | 56.0 | 56.0, 58.0, 54.0 |
| luna-high | base_03 | halved | 46.3 | 45.0, 46.0, 48.0 |
| luna-high | base_03 | offtopic_E2 | 53.3 | 52.0, 54.0, 54.0 |
| luna-high | base_03 | original | 67.3 | 67.0, 68.0, 67.0 |
| luna-high | base_03 | unsourced_E3 | 55.7 | 56.0, 55.0, 56.0 |
| luna-high | base_04 | drop_E3 | 57.3 | 59.0, 54.0, 59.0 |
| luna-high | base_04 | drop_E5 | 55.3 | 55.0, 56.0, 55.0 |
| luna-high | base_04 | halved | 43.3 | 43.0, 44.0, 43.0 |
| luna-high | base_04 | offtopic_E2 | 49.3 | 50.0, 50.0, 48.0 |
| luna-high | base_04 | original | 66.5 | 65.0, 66.5, 68.0 |
| luna-high | base_04 | unsourced_E3 | 56.0 | 56.0, 56.0, 56.0 |
| luna6-medium | base_01 | drop_E3 | 52.0 | 52.0, 52.0, 52.0 |
| luna6-medium | base_01 | drop_E5 | 49.5 | 51.0, 48.5, 49.0 |
| luna6-medium | base_01 | halved | 40.0 | 41.0, 39.0, 40.0 |
| luna6-medium | base_01 | offtopic_E2 | 46.2 | 47.5, 46.0, 45.0 |
| luna6-medium | base_01 | original | 61.5 | 62.0, 62.5, 60.0 |
| luna6-medium | base_01 | unsourced_E3 | 52.7 | 53.0, 54.0, 51.0 |
| luna6-medium | base_02 | drop_E3 | 49.3 | 50.0, 49.0, 49.0 |
| luna6-medium | base_02 | drop_E5 | 50.3 | 50.0, 50.0, 51.0 |
| luna6-medium | base_02 | halved | 31.3 | 30.0, 30.0, 34.0 |
| luna6-medium | base_02 | offtopic_E2 | 44.0 | 43.0, 42.0, 47.0 |
| luna6-medium | base_02 | original | 62.0 | 62.0, 62.0, 62.0 |
| luna6-medium | base_02 | unsourced_E3 | 52.7 | 52.0, 53.0, 53.0 |
| luna6-medium | base_03 | drop_E3 | 52.7 | 52.0, 54.0, 52.0 |
| luna6-medium | base_03 | drop_E5 | 56.0 | 56.0, 55.0, 57.0 |
| luna6-medium | base_03 | halved | 41.7 | 39.0, 43.0, 43.0 |
| luna6-medium | base_03 | offtopic_E2 | 48.3 | 46.0, 49.0, 50.0 |
| luna6-medium | base_03 | original | 66.7 | 66.0, 67.0, 67.0 |
| luna6-medium | base_03 | unsourced_E3 | 53.3 | 53.0, 54.0, 53.0 |
| luna6-medium | base_04 | drop_E3 | 54.3 | 53.0, 54.0, 56.0 |
| luna6-medium | base_04 | drop_E5 | 54.3 | 55.0, 55.0, 53.0 |
| luna6-medium | base_04 | halved | 41.7 | 41.0, 45.0, 39.0 |
| luna6-medium | base_04 | offtopic_E2 | 47.0 | 46.0, 46.0, 49.0 |
| luna6-medium | base_04 | original | 64.7 | 65.0, 66.0, 63.0 |
| luna6-medium | base_04 | unsourced_E3 | 52.0 | 51.0, 52.0, 53.0 |
