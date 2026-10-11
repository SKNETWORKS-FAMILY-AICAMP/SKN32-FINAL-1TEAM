# 옮겨 온 담당자 코드 — 구현 · 검증-2 (T-B1 · T-B2 · T-V2)

담당자 코드를 파일 구조 그대로 옮기고 **연결부만** 우리 규칙으로 바꿨다(spec 4.1와 같은 방식). 담당자 새 판을 받으면 이 문서의 목록으로 비교해 다시 가져온다.

## 1. 받은 판

| 항목 | 값 |
|---|---|
| 받은 날짜 | 2026-10-08 |
| 원본 사본(읽기 전용) | 담당자 브랜치의 `engineering_agent/` · `verification_agent/` (작업 공간에 받아 둠) |
| 의존 | 표준 라이브러리 + pydantic(이미 고정 목록에 있음). 새 패키지 없음 |

## 2. 옮긴 파일

경로는 이 폴더(`sbrain/agents/partner_bv/`) 기준이고 원본 사본의 같은 경로에서 바이트 그대로 복사한 뒤 3절만 고쳤다. 모두 59개(코드 36 · 자료 23).

**engineering_agent/** (T-B1 · T-B2 — 코드 23개, 자료 23개)
- `__init__.py` · `builder_html.py` · `file_writer.py` · `gates.py` · `html_kit.py` · `tasks.py`(4절)
- `infographic/` 17개: `__init__.py` · `artsheet.py` · `compose_guide.py` · `composer.py` · `content.py` · `design.py` · `design_kit.py` · `fonts.py` · `icons.py` · `illustrations.py` · `layout.py` · `poster.py` · `render.py` · `showcase.py` · `style.py` · `svg_parts.py` · `themes.py`
- `infographic/assets/`: `pretendard-ksx1001.woff2`(Pretendard 부분 글꼴, SIL OFL 1.1) · `LICENSE-Pretendard.txt`
- `infographic/assets/illustrations/`: 장면 SVG 17개(`ai` · `city` · `conversation` · `cook` · `delivery` · `dev` · `growth` · `maintenance` · `mobile` · `monitor` · `package` · `presentation` · `robot` · `sales` · `store` · `video` · `workers`, Lukasz Adam CC0) · `LICENSE.txt`
- `infographic_templates/`: `ai_api_template.svg` · `onepage_template.svg` · `webdev_template.svg`

**verification_agent/** (T-V2 — 코드 13개)
- `__init__.py` · `feature_match.py` · `llm_judge.py` · `score.py` · `tasks.py`(4절)
- `rules/`: `__init__.py` · `color.py` · `gates.py` · `html_parser.py` · `items.py` · `r4.py` · `r4_onepage.py` · `wiring.py`

**옮기지 않은 것:** 원본 사본에 담당자 테스트 · 시험 도구 · `output/` · `.cache/` · `__pycache__`가 없었다(2026-10-08 판). 다음 판에 생기면 옮기지 않는다.

## 3. 바꾼 곳 (연결부만)

바꾼 줄에는 `[S-Brain]` 주석을 달았다. 담당자 코드에서 `grep -n "S-Brain"`으로 모두 찾을 수 있다.

| 파일 | 바꾼 곳 | 이유 |
|---|---|---|
| 모든 코드(`tasks.py` 둘 포함, 68줄) | `from engineering_agent…` · `from verification_agent…` → 패키지 상대 import(`.` · `..`). 함수 안 늦은 import(composer의 `poster`, artsheet · layout의 `composer` · `showcase`, design_kit의 `svg_parts` · `layout`, builder_html의 `themes`)도 같다 | 우리 패키지 안에서 돈다 |
| `engineering_agent/builder_html.py` | `uuid` · `save_files` import, 시도 ID(`run_id`) 삭제. 통과 시 `save_files` 호출 삭제. 결과의 `entryFilePath` · `readmePath` → `entryFileName`(통과면 `index.html`, 아니면 `None`). 통과 요약의 `run_id=…:` 머리말 삭제 | 저장하지 않는다. 연결 코드(T3)가 `sourceText`를 `entryFileName`으로 `tools.files.put` 한다 |
| `engineering_agent/builder_html.py` — 끼워 넣기 | **바꾸지 않음**: 통과면 담당자가 `decorate`(글꼴 · 아이콘)한 HTML, 외부 의존 · 샌드박스 · 비밀값 실패면 끼워 넣기 전 원문을 `sourceText`로 돌려준다(담당자 동작 그대로) | spec 4.2는 두 경우 모두 끼워 넣은 HTML을 쓴다 — **실패 경우의 `decorate`는 T3 연결 코드가 한다.** `decorate`는 먼저 `strip`하므로 거듭 불러도 결과가 같다(테스트) |
| `engineering_agent/file_writer.py` | 저장 함수 `save_files`(폴더 만들기 · 파일 쓰기) · 저장 화이트리스트 `_ENTRY_FILENAME` · `pathlib` import 삭제. 코드블록 꺼내기(`parse_code_blocks`)만 남김 | 같음 |
| `engineering_agent/infographic/render.py` | `re` · `uuid` · `Path` import, 템플릿 폴더 · 산출물 폴더 상수(`_TEMPLATE_DIR` · `_OUTPUT_DIR`) 삭제. `_load_template` → `resources.template(name)`. `render_infographic(category, data, run_id=None)` → `render_infographic(category, data)`. 시도 폴더 만들기 · 파일 쓰기 삭제. 결과 `{"file_path", "alt_text", "source_text"}` → `{"file_name", "alt_text", "source_text"}`(`file_name`은 담당자가 저장하던 이름 — 원페이지 `onepage.svg`, 그 밖 `infographic.svg`) | 저장하지 않고 SVG 글자를 돌려준다. 연결 코드가 `tools.files.put` 한다. 템플릿은 불러올 때 읽은 상수 |
| `engineering_agent/infographic/fonts.py` `_style` | `FONT_FILE` 경로 · `Path` import 삭제, `FONT_FILE.read_bytes()` → `resources.FONT`(없으면 `b""` → 빈 값 = 기본 글꼴, 원래 `OSError`와 같음) | 자료는 불러올 때 한 번 읽은 상수(Task 실행 중 디스크 안 열기). `lru_cache`(메모리 안 계산 저장)는 그대로 |
| `engineering_agent/infographic/illustrations.py` `_uri` | `DIR` 경로 · `Path` import 삭제, `(DIR / f"{key}.svg").read_bytes()` → `resources.ILLUSTRATIONS.get(key, b"")`(없으면 빈 값 — 원래와 같음) | 같음 |
| `engineering_agent/html_kit.py` `font_style` | `fonts.FONT_FILE.read_bytes()` → `resources.FONT`(없으면 빈 값) | 같음 |
| `verification_agent/rules/gates.py` `_entry_matches` · `html_gates` · `svg_gates` | 인자 경로(`entry_file_path`) → 파일 이름(`entry_file_name`, `FileRef.name`, 없으면 `None`). `Path.is_file` · `read_text` · 원문 대조 삭제 — 진입 파일 없음 = 이름이 비어 있음, 확장자 = 이름의 확장자(`PurePosixPath(name).suffix`, 대소문자 무시는 그대로). 문구 `진입 파일 없음 ('…')` → `진입 파일 없음`, `진입 파일 확장자가 .html가 아님 (index.htm)` → `진입 파일 확장자가 .html가 아님`(나머지 글자 그대로). `진입 파일과 Prototype.source_text 원문 불일치` 검사는 없어졌다 | 연결 코드가 `tools.files.get`으로 읽은 내용과 이름을 넘긴다(파일 자체를 읽으므로 경로 대조가 필요 없다). 진단 · 기록에 경로 · 이름을 남기지 않는다 |
| `verification_agent/score.py` `compute_code_check` · `compute_infographic_check` | 첫 인자 이름 `entry_file_path` → `entry_file_name`(값도 이름) | 위와 같음 |
| `verification_agent/llm_judge.py` 요소 목록 | 파일 저장소(`ELEMENT_STORE = .cache/elements.json`) · `Path` import 삭제. `_stored(key)` → `_stored(store, key)`, `_store(key, elements)` → `_store(store, key, elements)`(사전에 더함 — 폴더 만들기 · 파일 쓰기 없음), `elements_for(…)`에 `store` 인자, `make_judge(tools, kind, source, plan_text, elements=None)` — `elements`가 요소 목록 사전(열쇠 = 담당자 열쇠 `_store_key` = 종류 · 기능 이름 · 정의 줄의 SHA-1 16진수, 값 = 요소 글자 목록 1 ~ 5개). `None`이면 빈 사전. 있는 열쇠는 LLM을 부르지 않고, 새로 뽑은 목록을 **그 사전에 제자리로 더한다**(출력 = 입력 ∪ 새 것). 요소 뽑기가 재시도 소진이면 사전에 넣지 않고 통째로 묻는 판정으로 간다(담당자 동작) | spec 4.4. 연결 코드(T3)가 입력 사전의 사본을 넘기고 그 사전을 출력으로 돌려준다. 목록은 산출물 내용이다 — 기록 · 로그 · 예외 메시지에 넣지 않는다 |
| `verification_agent/llm_judge.py` 예외 | `except Exception` 셋(요소 뽑기 `elements_for` · 판정 `make_judge.ask` · 핵심 칸 `make_field_judge.ask`) → `except ToolCallExhausted`(`orchestrator.errors`). 그 밖의 예외는 올린다 | standards 4절 "T-V2가 받아도 되는 것은 대조 LLM 실패뿐" |
| `verification_agent/llm_judge.py` `_MAX_WORKERS` | 6 → 3. `_VOTES = 3` 그대로. 스레드마다 `tools.for_item(<항목 키>)`, 항목 키는 담당자 문구 그대로(`{기능}#요소` · `{기능}#{n}` · `{칸}#{n}`) | spec 4.4 |
| `engineering_agent/tasks.py` 머리 (T3) | import 둘 더함 — `builder_html._extract_implemented_features`(자기 신고 뽑기) · `html_kit.decorate`(끼워 넣기). 파일 이름 · 형식 상수 `ENTRY_FILE_NAME`(`index.html`) · `HTML_MEDIA_TYPE`(`text/html`) · `SVG_MEDIA_TYPE`(`image/svg+xml`)와 `_text(bytes)`(UTF-8, 풀 수 없는 바이트는 대체 문자 — 잠정) 더함 | 파일은 `tools.files`로 넣고 읽는다 |
| `engineering_agent/tasks.py` `run_tb1` (T3) | 이전 원문: `rework_input.previous_source_text`(글자) → `previous_source_file`(참조)을 `tools.files.get`으로 읽어 `previous_html`로 넘김(파일 창구 실패는 받지 않음 — 끼워 넣은 것은 담당자 `user_message`가 뺀다). 결과: `entryFilePath` · `sourceText` 칸 → **원문(`sourceText`)이 있으면**(통과 · 외부 의존 · 샌드박스 · 비밀값 실패) `decorate` 한 HTML을 `index.html`로 `tools.files.put` 하고 그 참조를 `Prototype.entryFile` · `TB1Out.entryFile`에, 자기 신고는 끼워 넣은 HTML에서 `_extract_implemented_features`로(실패 경우도 통과 때와 같은 방식). 원문이 없으면(진입 파일 실패) 진입 파일 없음 · 빈 목록. `check` = 통과 여부 · 실패면 담당자 요약 문구 한 줄(그대로). `Prototype(asset_paths · readme_path · source_text)` → `Prototype(asset_files=[] · readme_file=None)` | spec 4.2 · D2 · D3 — 검사에 걸린 HTML도 진입 파일로 넘겨 검증-2가 채점한다. 담당자는 실패 원문을 끼워 넣지 않고 돌려준다(2절 표 위 줄) |
| `engineering_agent/tasks.py` `run_tb2` (T3) | 아이콘판 바로 뒤에 `icon_fallback = content["_art"] is None and bool(artsheet.icon_items(category, content))` — 담당자가 아이콘 항목을 고르는 함수 그대로. 결과: `render_infographic`의 `file_path` → `file_name`으로 `tools.files.put`(SVG, UTF-8) 한 참조를 `Infographic.imageFile`에, `iconFallback` 칸 채움. 자체 검사 · 지면 구성 · 아이콘판 · 넓은 예외 받기는 그대로 | spec 4.3 · D13 — 흐름이 '이미지대체' 사건에 쓴다 |
| `verification_agent/tasks.py` `_read` · `score_artifact` · `run_tv2` (T3) | `Path` import 삭제. `_read(경로)` → `_read(tools, 참조)` = `tools.files.get(ref).decode("utf-8", errors="replace")`(잠정 — `tv2.fileDecode`, 실패는 받지 않음). `score_artifact` 인자: 경로 칸(`entry_file_path` · `readme_path` · `infographic_path`) → 이름 · 내용(`entry_file_name` · `readme` · `svg`), `elements`(요소 목록 사전) 더함 → `make_judge(…, elements)`. 원페이지 불일치 문구 `Infographic.image_path와 Prototype.source_text 불일치` → `Infographic.imageFile과 Prototype.entryFile 내용 불일치`(필드 이름만). `run_tv2`: 진입 파일(있으면) · 안내 문서(있으면) · 인포그래픽을 읽는다 — 원페이지처럼 진입 파일과 인포그래픽이 같은 키면 한 번만. 진입 파일 없음 = `entryFile` 비어 있음, 이름 = `FileRef.name`. 요소 목록 = `dict(입력 featureElements or {})` 사본을 넘기고 그 사전을 출력 `featureElements`로. `CodeCheck`에 `earned` · `applicable`(담당자 항목 값) 채움 | spec 4.4 · 4.5 |
| `verification_agent/tasks.py` `run_tv2` 합계 (2026-10-11, 실제 호출 확인 뒤) | `ArtifactScore.total = code.total + feature.score` → `round(…, 2)` | 실제 원페이지 채점에서 15.0 + 14.06이 `29.060000000000002`로 나왔다(소수 계산 오차). 원점수 칸은 웹으로 그대로 나가므로 소수 둘째 자리로 맞춘다. 두 원점수 · 채점 규칙은 그대로 |

**바꾸지 않은 것(알려 둘 것)**
- 담당자 프롬프트 · 자체 검사 규칙(진입 파일 → 외부 의존 → 샌드박스 → 비밀값, 첫 실패에서 멈춤) · 코드 점검 8항목 · 대조 공식 · 지면 조립 · 아이콘판 그리기 · 호출 목적 문구(`T-B1 HTML 생성` · `T-B2 인포그래픽 정보 추출` · `인포그래픽 아이콘` · `계획서 대조 요소: {기능}` · `계획서 대조: {기능 또는 칸}`).
- `engineering_agent/gates.py`(T-B1 자체 검사)의 진입 파일 문구(`진입 파일 'index.html'이 생성된 파일 목록에 없음: [모델이 지은 이름들]`)는 그대로다 — spec 4.1 표가 경로 · 이름을 빼라고 한 것은 검증-2 진단 문구다. 이 문구는 T-B1 `check.failures`(산출물 값)로 간다.
- `verification_agent/rules/gates.py` `svg_gates`의 `SVG 파싱 실패: {exc}`(파서 오류 위치 — 내용 없음)는 그대로다.
- T-B2 아이콘판의 넓은 예외 받기(`artsheet.generate`의 `except Exception` → `None`, 기본 아이콘)는 그대로다(T-B2는 `tools.image` 실패를 받아도 된다).
- `content.py` · `builder_html.py` · `llm_judge.py`의 `_format_error`(함수 안 `from sbrain.orchestrator.errors import FormatError`)는 그대로다 — `partner_bv/__init__.py`가 그 모듈을 미리 불러 둔다.
- `fonts._style` · `html_kit.font_style` · `html_kit.icon_sprite` · `illustrations._uri`의 `lru_cache`는 그대로다(디스크가 아니라 상수에서 만든 글자를 메모리에 둔다).
- 모듈 docstring · 주석 중 저장 · 경로를 말하는 담당자 문장(예: `infographic/__init__.py`의 "render 템플릿 채우기 · 파일 저장")은 그대로 두었다.

## 4. 담당자 `tasks.py` 두 개 (T3 — 지금 계약으로 연결부만 고침)

- `engineering_agent/tasks.py`(`run_tb1` · `run_tb2` · T-B2 자체 검사 `_check_content` · `_plan_text` · `_wants_redesign` · `_USER_ONLY_REASON`)와 `verification_agent/tasks.py`(`run_tv2` · `score_artifact` · `plan_text_of` · `_check_infographic_alt` · `_detail` · `diagnostics_of`)는 담당자 구조를 그대로 두고 **계약 칸 · 파일 창구 연결부만** 고쳤다(3절 표의 T3 줄, `[S-Brain]` 주석). 자체 검사 · 계획서 글 만들기(`_plan_text` · `plan_text_of`) · 재구성 판단 · 대체 텍스트 확인 · 진단 문구는 바꾸지 않았다.
- Task 함수 모양은 우리 약속 그대로 `run_xxx(inp, tools) -> 출력`이다. Task 함수 안의 늦은 import(`sbrain.contracts.tasks` · `sbrain.models`)는 담당자 그대로다 — 조립이 먼저 불러 두므로 실행 중 디스크에 닿지 않는다.
- 등록은 우리 연결 코드 `partner_bv/tasks.py`(5절)가 한다. 두 담당자 패키지는 서로 import하지 않는다.
- 받는 예외: T-B2 아이콘판(`artsheet.generate` — 담당자 넓은 예외 받기)과 T-V2 대조 LLM(`llm_judge` — `ToolCallExhausted`만)뿐이다. 파일 창구 실패 · T-B1 글 호출 · T-B2 글 호출 · T-V2의 그 밖의 예외는 올린다.
- 바뀐 동작(담당자 원본과 다름): 담당자 `run_tb1`은 실패 원문을 저장하지 않고 진입 파일을 비웠지만, 우리는 끼워 넣어 진입 파일로 넣는다(spec 4.2 D2 · D3, 검증-2가 채점). 외부 의존은 검증-2에 검사가 없어 감점 없이 채점되는 것이 알려진 한계다.

## 5. 연결 코드 (이 폴더 바로 아래 — 우리 파일)

| 파일 | 내용 |
|---|---|
| `__init__.py` | 담당자 모듈 · 자료 상수 · 함수 안에서 늦게 import하는 모듈(`poster` · `composer` · `showcase` · `svg_parts` · `layout` · `themes` · `sbrain.orchestrator.errors`)을 불러올 때 미리 불러 둔다 — Task 실행 중 디스크에 닿지 않게. 담당자 `tasks.py` 둘은 등록 모듈(`tasks.py`)이 불러온다 |
| `resources.py` | 구현 담당자 자료 상수 — `FONT`(글꼴 바이트, 없으면 `b""`) · `ILLUSTRATIONS`(장면 → SVG 바이트) · `TEMPLATES`(파일 이름 → 템플릿 글자) · `template(name)`(없으면 `FileNotFoundError`, 메시지에 이름 없음). 엔지니어링 자료만 — 검증-2는 쓰지 않는다 |
| `tasks.py` (T3) | 실구현 Task 등록 — `IMPLEMENTED`(T-B1 · T-B2 → `engineering_agent/tasks.py` `run_tb1` · `run_tb2`, T-V2 → `verification_agent/tasks.py` `run_tv2`) · `IMPLEMENTED_TASKS` · `IMAGE_TASKS`(`T-B2` — 이미지 호출을 하는 실구현) · `bind_partner_bv(registry)`. partner_sw와 같은 모양. 워커 조립(`bootstrap.build_app`)이 묶고, LLM 호출은 `IMPLEMENTED_TASKS`, 이미지 호출은 `IMAGE_TASKS`를 실제 호출처로 보낸다. 스텁 조립은 그대로 스텁 — 테스트는 `bind_partner_bv(app.registry)`로 바꿔 끼운다 |

`partner_bv`를 가져다 쓰는 곳은 조립(`bootstrap.py`)뿐이다. `flow/` · `orchestrator/`는 import하지 않는다. `partner_bv`가 우리 쪽에서 가져다 쓰는 것은 `orchestrator.errors` · `orchestrator.registry`(등록 타입) · `contracts` · `models` · `orchestrator.tools`(타입)뿐이다(담당자 고정 문구 `_USER_ONLY_REASON`은 `flow`를 import하지 않고 글자 그대로 두고, 테스트가 `flow/rework_map.REWORK_DEFAULT_REASON`과 같은지 본다).

**'이미지대체' 사건(흐름 쪽, T3):** `flow/sbrain_flow.py` `after_execution`이 T-B2 실행 기록마다 한 번 — 최종 실패인 이미지 호출이 있으면 `IMAGE_FALLBACK_DETAIL`, 그 밖에 출력 `iconFallback`이 참이면 `ICON_FALLBACK_DETAIL`(잠정)로 남긴다. 필드로만 가른다.

### 끼워 넣은 글꼴 · 아이콘 빼기 (T3가 쓴다)

- `engineering_agent/html_kit.py` `strip(html)` — 끼워 넣은 글꼴(`<style data-kit="font">`) · 아이콘 묶음(`<svg data-kit="icons">`)을 뺀다. `decorate(html)`는 먼저 `strip`한 뒤 다시 넣는다(거듭 불러도 같음).
- `engineering_agent/builder_html.py` `user_message(instruction, previous_html)` — 재수행 · 재작성 때 이전 HTML을 `strip`해서 `<이전HTML>` 태그로 싣는다. 이전 원문(`previous_source_file`)을 읽어 `build_prototype_html(…, previous_html=…)`에 넘기면 담당자 코드가 알아서 뺀다.

## 6. 다음 판 받을 때 비교 방법

1. 새 판을 작업 공간에 사용자가 풀어 둔다(갱신은 사용자).
2. 2절 목록의 파일마다 **옛 원본 사본 ↔ 새 원본**을 비교해 담당자가 바꾼 곳을 찾는다(우리 사본끼리 비교하지 않는다 — 3절 변경이 섞인다). 옛 원본 사본이 덮어써졌으면 우리 사본에서 `[S-Brain]` 줄을 3절 표대로 되돌린 것과 비교한다.
3. 담당자가 바꾼 파일은 새 원본을 복사한 뒤 3절 표의 변경을 다시 적용한다(`[S-Brain]` 주석 자리). 자료 파일(woff2 · SVG · 라이선스)은 그대로 덮어쓴다. 새 자료 파일이 생기면 `resources.py`와 `pyproject.toml` 패키지 자료를 함께 본다.
4. 새 판에 OpenAI 직접 호출 · `os.getenv` · `datetime.now` · `.env` 읽기 · `time.sleep` · 파일 쓰기 · 폴더 만들기 · 실행 중 파일 읽기 · 넓은 예외 받기(`except Exception`)가 새로 생겼는지, 함수 안 import가 새로 생겼는지(생기면 `__init__.py`에 미리 불러 두기를 더한다) 본다 — `tests/test_partner_bv_vendored.py`의 소스 검사 · 디스크 차단 테스트가 잡는다.
5. 담당자 `_USER_ONLY_REASON`(`engineering_agent/tasks.py`)이 `flow/rework_map.REWORK_DEFAULT_REASON`과 같은지(테스트), 검증-2 `_MAX_WORKERS`가 다시 6이 되지 않았는지 본다.
6. 이 문서의 1절 날짜와 2 · 3절 목록을 고친다.

## 7. 저장소 사본

빼는 경로가 없다. 담당자 자료(글꼴 woff2 — SIL OFL · 그림 SVG — CC0 · 라이선스 파일 · 템플릿 SVG)는 코드의 일부라 설치본(`pyproject.toml` 패키지 자료)과 저장소 사본에 들어간다. 라이선스 파일(`LICENSE-Pretendard.txt` · `illustrations/LICENSE.txt`)을 빼지 않는다.
