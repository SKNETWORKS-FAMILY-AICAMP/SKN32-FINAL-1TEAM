# engineering_agent — 구현 Agent (T-B1 · T-B2)

사업계획서를 받아 **프로토타입**을 만드는 Agent입니다. 계획서의 "준비 정도" 칸을 "개발 예정" 문장이 아니라 실제로 열어 볼 수 있는 결과물로 채우는 것이 목적입니다.

- 담당: 정재희 · 이슈 `SB-124`
- 서버 · DB · 화면이 없는 파이썬 함수입니다. 조율(Orchestrator)이 정해진 순서에 부르고, LLM · 이미지 호출도 조율이 넘겨 주는 `tools`로만 합니다.
- 채점은 하지 않습니다. 만든 결과는 [검증-2](../verification_agent/README.md)가 채점합니다.

## 무엇을 만드나

| Task | 함수 | 만드는 것 | 카테고리 |
|---|---|---|---|
| T-B1 | `tasks.run_tb1` | 한 파일로 동작하는 HTML 실행 파일 `index.html` | 웹개발(화면 2개 이상 전환) · AI API(입력 → 처리 → 출력). 원페이지는 조율이 건너뜀 |
| T-B2 | `tasks.run_tb2` | 인포그래픽 SVG | 전부. 원페이지에서는 이 SVG가 프로토타입 본체(`onepage.svg`) |

```
조율 ─┬─ (웹개발 · AI API) run_tb1 → index.html
      ├─ run_tb2 → infographic.svg / onepage.svg
      ├─ 실행 안내 문서 생성 (조율 규칙 단계)
      └─ run_tv2 (검증-2) → 산출물층 30점
```

## T-B1 — HTML 실행 파일

```
기능 목록 + 아이템 정보 + 카테고리 + 지시문 + 사업계획서
 → 프롬프트 조립 (기능마다 계획서가 그 기능을 정의한 줄을 붙인다)
 → LLM 1회 → 응답에서 index.html 코드블록 추출
 → 자체 검사 4개 → 글꼴 · 아이콘 묶음을 넣어 저장
```

- **프롬프트 규칙은 채점 항목과 짝입니다.** 제목 계층 · 입력칸 label · 대체 텍스트 · 명도 대비 · 이벤트 직접 연결 · sandbox · 1440px · id 참조 · 임시 문구 규칙이 검증-2 코드 점검 항목 하나씩에 대응합니다.
- **자체 검사 4개** (`gates.py`)는 점수가 아니라 거르는 장치입니다.

  | 코드 | 거르는 것 |
  |---|---|
  | `E-B1-ENTRY` | 응답에 `index.html`이 없거나 비었다 |
  | `E-B1-DEP` | 외부 주소 · 함께 오지 않는 파일을 가리키는 script · stylesheet · img, CSS `@import` · `url(...)` |
  | `E-B1-SANDBOX` | `sandbox="allow-scripts"` 틀에서 멈추거나(`localStorage` 등) 무시되는(`alert` · `window.open` · 페이지 이동 등) API |
  | `E-B1-SECRET` | 하드코딩된 API 키 · 토큰 · 비밀번호 값 |

- 자체 검사에 걸려도 진입 파일이 있으면 파일은 만들고 `check.passed=False`로 돌려줍니다. 조율이 재수행하고, 재수행 상한을 넘기면 그대로 채점에 넘어가 점수에 반영됩니다.
- 색은 사업 분야 낱말 · 이름 규칙으로만 고릅니다(`themes.pick`, LLM 안 부름). 실행 파일은 동작과 흐름이 중요하기 때문입니다.

## T-B2 — 인포그래픽

```
사업계획서 + 아이템 정보 + 카테고리 + 지시문
 → LLM 1회: 지면에 넣을 값과 구역 제목을 JSON으로 추출
 → 아이템명 · 목표 고객 · 한 줄 소개 · 기능 목록은 입력값으로 덮어쓴다
 → 이미지 모델 1회: 대표 도식 + 항목별 아이콘을 한 장에 그린다
 → 자체 검사 (누락 · 계획서에 없는 숫자 · 지면 폭 넘침)
 → 코드가 구역을 조립해 SVG 저장
```

- **글자는 전부 코드가 `<text>`로 씁니다.** 이미지 모델은 글자가 섞이면 한글 오타가 나서 그림만 맡깁니다. 그린 한 장은 `<defs>`에 한 번 싣고 구역마다 필요한 칸만 잘라 씁니다.
- **LLM은 값만 냅니다.** 구역 순서 · 모양 · 폭은 코드(`design.py`)가 계획서 재료의 관계로 정합니다. 같은 재료면 같은 구성이고, 재수행하면 새 구성, 미달 사유가 있는 재작성이면 구성을 지키고 문제만 고칩니다.
- 지면의 숫자는 계획서 원문에 있는 것만 씁니다. 없는 숫자, 빈 칸, 폭을 넘는 값은 자체 검사 사유가 됩니다(파일은 만듭니다).
- 그림 생성이 실패하거나 이미지 도구가 없으면 아이콘 없이 포스터 모양 지면으로 끝까지 갑니다(`poster.py` + `assets/illustrations/`). 결제 · 한도 소진처럼 재개를 기다려야 하는 실패만 예외로 올립니다.
- 사업 분야 색은 낱말로 정하고, 낱말이 없으면 LLM에게 7개 분야 중 하나를 묻습니다(`themes.decide`).
- 채점 쪽이 값을 찾을 수 있게 값 노드에 `data-field` · `data-role` · `data-feature` 표식을 붙입니다.

## 입력 · 출력 요약

| 함수 | 입력 | 출력 |
|---|---|---|
| `run_tb1` | `TB1In` — `feature_list` · `item_spec` · `category` · `instruction` · `rework_input` · `plan_doc` | `TB1Out` — `prototype`(HTML 원문) · `check`(통과 여부 · 사유) · `implemented_features`(모델의 자기 신고, 채점 근거 아님) |
| `run_tb2` | `TB2In` — `plan_doc` · `item_spec` · `category` · `instruction` · `rework_input` | `TB2Out` — `infographic`(SVG · 대체 텍스트) · `check` |

- 입력 · 출력 모델은 조율 패키지(`sbrain.contracts.tasks`)의 것입니다. 품질 미달은 예외가 아니라 `check`에 담겨 정상 반환됩니다.
- 예외는 "결과를 만들 수 없었다"는 뜻입니다: 모르는 카테고리(`ValueError`), 응답 형식 오류가 재시도 뒤에도 계속됨(`ToolCallExhausted`).

## 파일 구성

| 파일 | 하는 일 |
|---|---|
| `tasks.py` | 진입 함수 둘, T-B2 자체 검사 |
| `builder_html.py` | T-B1 프롬프트 · 응답 파싱 · 자체 검사 호출 · 저장 |
| `html_kit.py` | T-B1 기본 디자인 CSS(대비 4.5:1 이상), 저장 직전에 넣는 글꼴 · 아이콘 묶음 |
| `gates.py` · `file_writer.py` | T-B1 자체 검사 4개, 코드블록 파싱 · 저장 |
| `infographic/content.py` · `compose_guide.py` | T-B2 추출 프롬프트 · 응답 스키마, 구역 제목 지시 |
| `infographic/design.py` · `design_kit.py` | 지면 구성 · 그림체 · 구역 틀 결정 |
| `infographic/artsheet.py` | 이미지 모델 호출, 그림에서 칸 찾기, 지면에 끼워 넣기 |
| `infographic/composer.py` · `poster.py` · `showcase.py` | 구역 조립(그림 있음 · 그림 없음 · 기본 지면) |
| `infographic/layout.py` · `render.py` | 글자 폭 · 줄바꿈 · 넘침 판정, 바깥 틀 채우기 · 저장 |
| `infographic/themes.py` · `fonts.py` · `icons.py` · `illustrations.py` | 분야별 색, 글꼴, 기본 아이콘, 대체 일러스트 |
| `infographic/assets/` · `infographic_templates/` | Pretendard 글꼴(SIL OFL), CC0 일러스트, 카테고리별 SVG 바깥 틀 |

## 모델

| 쓰는 곳 | 모델 | 고른 이유 (2026-10-15 실제 계획서 비교) |
|---|---|---|
| HTML · 인포그래픽 글 | `gpt-6-luna` | 6개 모델 중 평균 29.53 / 30점으로 가장 높고 4개 모두 첫 시도 통과. 1개 약 12원 · 약 2분. 최상위 Astra는 28.75점에 비용 110배 |
| 인포그래픽 그림 | `gpt-image-2.5-flare` (medium) | sunburst와 같은 가격에 더 빠름. 1장 약 35원 |

모델 이름은 이 패키지가 아니라 조율 설정(`agent-orchestration/sbrain/orchestrator/settings.py`)에 있습니다.

## 테스트

저장소 루트에서 실행합니다(필요한 것은 Python 3.12+와 `pydantic>=2`). 실제 모델은 부르지 않고, 조율 계약은 `tests/fake_sbrain.py`가 대신합니다.

```bash
python -m unittest discover -s tests -t .          # 구현 · 검증-2 함께 188개
python -m tests.preview_infographics               # 예시 데이터로 인포그래픽 미리보기 (그림 없이)
```

미리보기 결과는 `engineering_agent/output/`에 생기고 git에 올라가지 않습니다.

## 서비스에서 도는 곳

이 폴더는 담당자 원본입니다. 서비스에서는 조율이 이 코드를 `agent-orchestration/sbrain/agents/partner_bv/engineering_agent/`로 옮겨 붙여 실행합니다. 옮기면서 파일 저장만 조율의 파일 저장소(`tools.files`)로 바뀌고, 나머지 로직은 같습니다. 바뀐 곳은 [`partner_bv/VENDORED.md`](../agent-orchestration/sbrain/agents/partner_bv/VENDORED.md)에 있습니다. 원본을 고치면 조율 담당에게 알려 다음 판에 옮기게 합니다.
