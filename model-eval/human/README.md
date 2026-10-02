# 사람 채점

1. `rating_tool.html`을 브라우저로 열어 12편을 채점한다(약 25~35분). 정답 열쇠 `key.json`은 채점이 끝나기 전에 열지 않는다.
2. 맨 아래 버튼으로 `ratings.json`을 내려받아 이 폴더에 둔다.
3. `python -m v6_hard.human_tool score human/ratings.json reports/v6_gradient_…` 로 모델 점수와의 일치도를 계산한다.

## Codex에게 맡기는 경우

도메인 지식이 부족해 사람이 채점하기 어려우면 `codex_pack/`(12편 본문과 평가 기준만 있음)과 `docs/CODEX_RATING_TASK_20260930.md`를 Codex에게 준다. Codex는 `codex_pack/ratings.json`을 쓰고 `python -m v6_hard.human_tool check human/codex_pack/ratings.json`으로 형식을 검사한다. 채점이 끝난 뒤 `score human/codex_pack/ratings.json reports/v6_gradient_…`로 비교한다. 결과는 사람 정답이 아니라 AI 참고 점수다.
