# 원문 대조를 마친 공고 목록 처음 만들기 — 결정 0017 (2026-10-08)

- 명령: `.\.venv\Scripts\python.exe -X utf8 -m eval.bonus_boostable --old <결정 0017 전 bonus.py 사본> --write-reviewed <10건>` → `search/bonus_reviewed.json`, 이 폴더 `results.json`·`summary.md`.
- 기준: 2026-10-08, 열린 공고 1,748건, found 317건, 추출기 `extract_bonus/v4 gpt-6-luna medium`, 결정 0017(Codex 3차 지적 처리) 반영 `search/bonus.py`. 공용 DB SELECT만.
- 800개 조합 탐색에서 양수가 관측된 공고 10건(전체 집합 증명은 아님). 결정 0017 전 계산과 조합 단위 비교: 같음 800.
- 목록에 넣은 10건과 승인 항목은 `search/bonus_reviewed.json`. 원문 대조 근거(Claude, AI 참고)는 `reports/bonus_boostable_20261008T034650Z/README.md`와 같다 — 같은 공고·같은 항목이고, 결정 0017 수정은 이 10건의 결과를 바꾸지 않았다. Codex 3차 검수 7절도 이 10건의 채택 항목에서 배점 오류를 찾지 못했다(승인 목록은 아님).
- 목록과 비교: 목록 안 그대로 10 · 다시 대조 필요 0 · 새 후보 0.
