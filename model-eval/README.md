# model-eval — Agent별 모델 비교 실험

S-Brain Agent에 어떤 모델을 쓸지 **한 Agent씩** 실측하는 폴더다. 팀 코드(`agent-orchestration/`, `data-collection/`)는 수정하지 않고 이 폴더 안에서만 돌린다.

원칙: 요리 대회처럼 **입력과 채점 기준은 고정하고 모델만 바꾼다.** 결과는 매번 `reports/` 아래 새 폴더에 쓰고 기존 폴더는 덮어쓰지 않는다.

## 팀 공유용 요약

`docs/TEAM_SUMMARY_20260930.md`(Notion·PR에 붙이기 좋은 마크다운)와 `docs/TEAM_SUMMARY_20260930.html`(파일로 열리는 시각 버전). 결과·추천·팀 코드 제안·한계를 한 장에 담았다. 상세는 `docs/HANDOFF_20260930.md`.

## 폴더

| 경로 | 내용 |
|---|---|
| `candidates.json` | 후보 모델 목록(모델명·추론 강도·단가·로컬 주소). 후보 추가는 한 줄 |
| `clients/openai_compat.py` | OpenAI와 로컬 서버(Ollama·LM Studio·vLLM)를 같은 코드로 부르는 어댑터 |
| `fixtures/` | 고정 입력: 평가 기준(`rubric.json`), 원본 계획서(`plans/`) |
| `v1_verifier/` | **검증-1(계획서 채점)** 실험: 변형 생성·프롬프트·실행·채점 |
| `v2_coordinator/` ~ `v5_builder/` | 조율 · 전략 · 작성 · 구현 실험(각 폴더에 프롬프트·실행·채점·리포트) |
| `v6_hard/` | **더 어려운 시험**: 검증-1 좋음/보통/나쁨, 전략 함정 자료, 작성 유혹 요청. 사람 채점 도구(`human_tool.py`)도 여기 |
| `human/` | 사람 채점 도구(`rating_tool.html`)와 안내. 저장한 `ratings.json`을 여기에 둔다 |
| `tests/` | 가짜 모델로 하는 테스트 91개(API 호출 없음) |
| `reports/` | 실행 결과 |

## 검증-1 실험이 재는 것

원본 계획서와, 일부러 망가뜨린 변형(섹션 삭제·출처 없는 수치·무관한 내용·분량 절반)을 각 모델에 채점시킨다. 어느 항목이 깎여야 하는지 미리 알기 때문에 사람 점수 없이도 비교할 수 있다.

| 지표 | 뜻 |
|---|---|
| 순서 맞힘 | 망가뜨린 계획서에 원본보다 낮은 총점을 줬는가 |
| 원인 짚기 | 망가뜨린 바로 그 항목을 깎았는가 |
| 흔들림 | 같은 입력을 반복했을 때 총점이 얼마나 달라지는가(추론 모델은 온도 0 불가) |
| 형식 통과 | 항목 5개가 빠짐없이 정해진 JSON으로 나왔는가 |
| 시간·추론 토큰·비용 | 가성비 비교용 |

한계: 노골적으로 나쁜 글을 걸러내는지만 본다. 미묘한 품질 차이는 사용자가 직접 매긴 점수(10~20건)로 따로 확인해야 한다. 원본 계획서는 가상 샘플(AI 초안)이라 나중에 실제 샘플로 다시 확인한다.

## 실행

이 폴더에서 실행한다. 파이썬은 `data-collection`의 가상환경을 그대로 쓴다(`openai` 설치됨).

```powershell
$py = "..\data-collection\.venv\Scripts\python.exe"

# 1) 계획만 보기 — API 호출 0, 비용 0. 호출 수와 예상 비용을 출력한다
& $py -X utf8 -m v1_verifier.run

# 2) 테스트 (가짜 모델, API 호출 없음)
& $py -X utf8 -m unittest discover -s tests

# 3) 실제 실행 — 반드시 --execute. 처음엔 후보 하나, 반복 1회로 작게
& $py -X utf8 -m v1_verifier.run --candidates luna-medium --reps 1 --execute
```

- 실행이 끝나면 `reports/v1_…/report.html`(눈으로 보는 리포트)과 `summary.md`(표)가 함께 생긴다. `report.html`은 파일 하나로 완결돼 있어서 서버·인터넷 없이 더블클릭으로 열린다. 이미 있는 결과에서 다시 만들려면 `python -m v1_verifier.report reports/v1_…`.
- 리포트 구성: 후보별 요약 카드 → 총점 점 그래프(흔들림이 점의 퍼짐으로 보임) → 변형×평가항목 히트맵(칸을 누르면 모델이 준 이유와 인용문) → 표 보기.
- "깎였다"는 반복 오차와 구분하려고 **뚜렷하게** 낮아진 경우만 센다: 항목은 만점의 10% 이상, 총점은 5% 이상(`score.py`의 `MARGIN_*`, 잠정).
- API 키는 환경 변수 `OPENAI_API_KEY` 또는 `model-eval/.env`(`.env.example` 참고, 커밋 금지)에서 읽는다.
- 예상 비용이 `--max-usd`(기본 1.0)를 넘으면 실행하지 않는다.
- 끊기면 `--resume reports/v1_… --execute`로 남은 호출만 이어서 한다.
- 예상 비용의 출력·추론 토큰은 **가정값**이다. 첫 실행 뒤 실측치로 바로잡는다.
- 단가는 2026-09-22 OpenAI 요금 페이지 기준(저장소 기록)이다. 실행 전에 다시 확인한다.

## 결과 목록 페이지

`reports/index.html`은 실험별 카드(종류·시각·호출 수·비용·후보 모델)와 리포트 링크를 모아 둔 목록 화면이다. 실제 실행이 끝날 때마다 자동으로 다시 만들어지며, 손으로 만들려면 `python build_index.py`. 결과 폴더를 로컬 서버로 열면 기본 파일 목록 대신 이 화면이 나온다.

## 로컬 모델 추가

집 PC(3060)에서 Ollama 등을 켜고 `candidates.json`의 `local_example` 모양대로 `candidates` 배열에 한 줄 추가한다. 스키마 강제를 지원하지 않는 서버는 `"json_mode": "object"`로 둔다. 실험 코드는 바꿀 필요가 없다.

## 더 어려운 시험 (v6_hard)

```powershell
& $py -X utf8 -m v6_hard.run --exp gradient        # 계획만 출력(호출 0). writer / strategy 도 같다
& $py -X utf8 -m v6_hard.run --exp gradient --execute
& $py -X utf8 -m v6_hard.report reports\v6_gradient_…   # 표·리포트 다시 만들기(호출 0)
& $py -X utf8 -m v6_hard.human_tool build                # 사람 채점 도구 다시 만들기
& $py -X utf8 -m v6_hard.human_tool score human\ratings.json reports\v6_gradient_…   # 사람 점수와 모델 점수 비교
```

판정은 모두 코드가 한다. 성공 기준은 `v6_hard/evaluate.py` 머리말, 결과·사후 기준 수정 내역은 `docs/HANDOFF_20260930.md` 3-7절.

## 다음 Agent

조율·전략·작성·구현 실험은 끝났다(`v2_…`~`v5_…`). 남은 Agent는 검수와 검증-2다. 각 Agent는 폴더를 하나씩 더하고 `clients/`와 `candidates.json`을 함께 쓴다.
