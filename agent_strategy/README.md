# 사업계획서 전략·작성 Agent

일반·예비창업·초기창업 사업계획서의 전략 분석, 항목별 작성, 검증 1 연동, 결과 전달을 담당한다. 검증 1 판정 코드는 별도 `agent_validation` Agent가 소유하며, 전략·작성 Agent는 생성 결과를 검증 1에 전달하고 검증 결과에 따라 재작성 흐름을 연결한다. 재도전성공패키지는 범위에 포함하지 않는다.

## 실행 방법

1. `testing/start_function_test.cmd`를 실행한다. 스크립트가 `OPENAI_API_KEY`를 확인하고 `http://127.0.0.1:8765` 로컬 테스트 서버를 시작한다.
2. 브라우저에서 `http://127.0.0.1:8765/`를 열거나 `strategy_writing_agent.html`을 `file://`로 연다. 로컬 서버를 실행한 상태에서 사용하는 것을 권장한다.
3. 서버를 종료하려면 실행 중인 터미널에서 `Ctrl+C`를 누르거나 Python 서버 프로세스를 종료한다.

## 사용 방법
style="padding:28px"
공통 실행 순서는 서버 실행 → 사업계획서 탭 선택 → back 입력 확인 → 실행 범위 선택 → 결과 확인이다. 아래에서는 탭별로 실제 사용 목적을 나눈다.

### 일반 사업계획서 탭

1. `일반 사업계획서` 탭을 선택하면 `example_general_part2.json`이 사용자 입력 데이터에 자동 적용된다.
2. 일반 사업계획서의 F01~F18 전략·작성 결과를 확인하려면 **현재 탭 전략·작성 실행**을 누른다.
3. 검증 1과 조립까지 확인하려면 **현재 탭 전체 재실행**을 누른다.
4. 기존 저장 결과만 검증·조립하려면 **현재 탭 기존 결과 검증·조립만**을 누른다.
5. 항목을 선택해 본문을 다시 작성하거나, 이미지 항목이면 **이미지만 재생성**을 선택한다.

### 예비창업 사업계획서 탭

1. `예비창업 사업계획서` 탭을 선택하면 `example_pre_startup.json`이 자동 적용된다.
2. F16 본문과 F17 개발계획·사업비·일정 표를 확인하려면 **현재 탭 전략·작성 실행**을 누른다.
3. `2.3.6` 이미지 항목에서는 USER_FLOW와 SERVICE_ARCHITECTURE 이미지를 함께 생성한다.
4. 이미지 디자인만 바꾸려면 `2.3.6`을 선택한 뒤 빨간색 **이미지만 재생성** 버튼을 누른다.
5. 선택 항목 재작성은 연관 항목을 함께 재생성하고 검증 1을 자동 수행한다.

### 초기창업 사업계획서 탭

1. `초기창업 사업계획서` 탭을 선택하면 `example_early_startup.json`이 자동 적용된다.
2. F16 본문과 F17 개발계획·사업비·일정 표를 확인하려면 **현재 탭 전략·작성 실행**을 누른다.
3. `3.3.6` 이미지 항목에서는 USER_FLOW와 SERVICE_ARCHITECTURE 이미지를 함께 생성한다.
4. 이미지 디자인만 바꾸려면 `3.3.6`을 선택한 뒤 빨간색 **이미지만 재생성** 버튼을 누른다.
5. `deadline`, `supportLimit`, `featureList`가 입력 JSON의 `_strategy_limits`에 있으면 검증 1에서 공고 제약과 기능 목록을 확인한다.

### 설명 탭

`설명` 탭에는 함수 흐름 설명과 함수별 데이터 계약만 표시된다. 사업계획서 입력 JSON, 생성 텍스트 표, 재작성 버튼, 전략 Agent 분석 기록은 표시하지 않는다.

### 공통 버튼

- **현재 탭 사용자 입력데이터 JSON 다운로드**: 현재 입력 영역의 back JSON 저장
- **현재 탭 전체 재실행**: F01~F18 재실행 후 F19 검증 1·F20 조립
- **현재 탭 기존 결과 검증·조립만**: 최신 `result.json`을 사용해 F19·F20만 실행
- **선택 항목 검증만 실행**: 생성 텍스트를 바꾸지 않고 선택 항목과 연관 항목만 검증
- **OpenAI 연결 확인**: 키 설정 여부와 실제 API 연결 상태 확인
- **result.json 다운로드**: 현재 유형의 최신 저장 결과 다운로드
back JSON은 기존 전략 함수 입력 계약이 아니어도 된다. `runtime/pipeline.py`가 일반·예비·초기 출력형(`tableData`, `sectionText`)을 전략 함수가 읽는 내부 입력으로 정규화한 뒤 실행한다.

HTML은 Python을 직접 실행하지 않는다. API 요청은 `http://127.0.0.1:8765`로 보내며, 로컬 서버는 `file://` 요청(`Origin: null`)과 loopback 주소를 허용한다. 브라우저에서는 `http://127.0.0.1:8765/`로 여는 방법을 권장한다.

## 실제 실행 흐름

`testing/test_server.py`가 UI의 `/api/run`, `/api/retry` 요청을 받고 기존 `gpt_functions.py`, `python_functions.py`를 호출한다. 별도의 작성 함수를 만들지 않는다.

1. F01~F15가 전략·조사·계획 데이터를 한 번 만든다. F17 표 생성은 사용자 지시에 따라 실행하지 않는다.
2. `runtime/pipeline.py`가 각 항목에 필요한 `sourceKeys`와 관련 원본 사실만 전달한다.
3. F16은 본문을, F18은 이미지 명세를 생성한다. F18 명세는 SVG 개념도로 표시하며 실물 이미지 생성 API는 호출하지 않는다.
4. `agent_validation/validation_1.py`가 구조 검사 후 F19 Terra 의미 검증을 한다. 실패한 항목은 최대 한 번 재작성하며, 계속 실패하면 F20 조립을 막는다.
5. F20 Python 조립은 모든 검증이 통과한 경우에만 수행한다.

재시도 영역은 전체 실행 전에도 현재 탭과 선택 항목으로 연관 위치를 조회할 수 있다. **연관 항목 보기**에는 선택한 위치를 제외한 함께 재생성 대상 위치만 표시한다. 재시도는 선택 항목 및 같은 Canonical Data를 직접 쓰는 연관 항목만 F16/F18·F19로 다시 수행한다. F01~F15는 다시 호출하지 않는다.

## 프롬프트와 모델

`runtime/llm_runtime.py`가 모든 AI 호출 직전에 한국어 공통 지시, JSON 계약, 근거·개인정보·환각 방지 제약, 함수별 `FIELDS`를 합성한다. F01~F19의 함수별 제약은 이 파일에 있고, F20은 Python 함수라 AI 프롬프트가 없다.

F16 작성 규칙의 단일 실행 원본은 `res/business_plan_prompts/writing_rules.json`이다. `business_plan_prompt_template_general.md`는 일반 PartⅡ 전체 문서 작성 시 참조할 JSON 출력 템플릿이며, 항목별 F16 실행에는 전달하지 않는다.

back 필드와 UI 항목 위치의 매핑은 `res/from_back/section_mapping.json`에 있다. 일반형은 `1.1.1`~`1.4.3`, 예비창업은 `2.1.1`~`2.7.4`, 초기창업은 `3.1.1`~`3.7.4`로 관리하며, F17 표 항목은 위치만 기록하고 `tableSkipped`로 표시한다.

메인 표의 `입력 매개변수·원본 경로` 열은 각 항목의 실제 `sourceKeys`, back JSON `inputPaths`, `function(매개변수) → 반환값` 예시를 표시한다. F16은 항목별로 해당 매개변수만 전달받아 호출되며, 전체 사업계획서 본문을 한 번에 다시 쓰지 않는다. 함수명 셀의 예시 코드는 제거하고 매개변수 열에 모아 토큰 범위와 반환 구조를 확인할 수 있게 했다. 재시도는 선택 항목과 직접 같은 Canonical Data를 공유하는 연관 항목만 다시 호출한다.

`재작성 시 연쇄 실행 함수` 열과 `/api/section-mapping`의 `rewriteDependencies`는 선택 항목별 `selected`, `upstreamStrategy`, `downstreamWriting`, `F19`, `F20` 목록을 제공한다. 시장 분석은 F03·F04·F10~F12, 아이템 분석은 F02와 관련 목표·자원·이미지, 개발계획은 F08·F09·F15, 팀 역량은 F05·F13, 예산은 F14, 일정은 F15로 기록한다. 현재 재시도 API는 토큰 절약을 위해 작성 연쇄 항목과 F19/F20을 실행하고, `upstreamStrategy`는 프런트 재작성 계획에 기록한다.

| 문서 유형 | JSON 경로 |
| --- | --- |
| 일반 | `documentTypes.general` |
| 예비창업 | `documentTypes.pre_startup` |
| 초기창업 | `documentTypes.early_startup` |
| 모든 유형 공통 | `commonRules` |

모델·항목·입력 의존성의 기준은 `runtime/execution_contract.json`이며 `전략_작성_검증1.xlsx`에서 생성한다. Sol은 F03/F06~08/F10~12/F16, Terra는 F02/F04/F09/F19, Luna는 F01/F05/F13~15/F18, Python 단독은 F20이다. `OPENAI_MODEL` 전역 재지정이나 모델 자동 대체는 하지 않는다. 필요한 경우에만 `STRATEGY_MODEL_Fxx`를 쓴다.

지정 모델 호출이 권한·요금제·일시 연결 문제로 실패하면 개발 테스트용 공용 대체 모델 `gpt-4o`로 한 번만 시도한다. 대체 호출이 성공한 결과에는 `requestedModel`, `fallbackUsed`, `fallbackReason`이 trace JSON에 기록된다. UI는 대체 사용 시 alert와 console 경고를 표시한다. 기본·대체 모델이 모두 실패하면 실행을 중단한다. 유료 Pro 키 연결 후에는 지정 모델을 다시 사용할 수 있다.

## 조사 데이터

F01·F03은 `res/crawling/`의 기존 자료만 읽는다. `runtime/research_context.py`가 로컬 키워드 검색으로 관련 발췌와 파일 경로·URL을 제한해 전달한다. 실행 중에는 크롤링 원본을 재수집하거나 수정하지 않는다.

엑셀의 함수·항목·모델을 수정한 경우에만 `tools/build_execution_contract.py`를 실행해 계약 JSON을 다시 만들고 검토한다.

## 결과와 이력

실행마다 덮어쓰지 않고 다음 폴더에 새 이력을 저장한다.

```text
res/to_back/runs/<실행시각>_<문서유형>_<runId>/
  result.json
  result.html
  manifest.json
```

재시도 결과도 별도 폴더에 저장하며 `manifest.json`의 `retry`가 부모 실행과 선택 항목을 기록한다.

## 검증

저장소 루트에서 실행한다.

```powershell
python -B -m unittest agent_strategy.testing.test_function_pipeline -v
```

현재 테스트는 16개이며 back JSON 파일명 변경과 새 예산·일정 값에 맞춰 검증한다. 실제 전략·작성 실행은 OpenAI API를 호출하므로 테스트 통과 여부와 별도로 API 비용이 발생한다.

## 2026-09-30 최신 구현 상태

- 함수 실행 테스트의 버튼을 명확히 구분했다. `현재 탭 전략·작성 실행`은 현재 탭의 F01~F18 전략·작성만 실행하고, `현재 탭 전체 실행`은 검증 1과 조립까지 포함한다. `현재 탭 검증·조립만 실행`은 최신 저장 `result.json`을 다시 사용해 F19 전체 검증 후 통과 시 F20 조립만 수행하며 F01~F18을 다시 호출하지 않는다.
- 전략·작성·검증·조립의 의미를 UI 안내문에 표시한다. 전략은 입력·Web·RAG 분석, 작성은 본문·표·이미지 명세 생성, 검증은 형식·원본·의미 점검, 조립은 통과한 결과를 최종 문서 구조로 통합하는 단계다.
- 재작성 실행은 선택 항목과 Canonical Data를 공유하는 연관 항목을 함께 재생성하고 F19 검증을 자동 수행한다. `선택 항목 검증만 실행`은 기존 생성 텍스트를 바꾸지 않고 선택 항목과 연관 항목만 검증한다.
- F16의 출력 토큰 제한은 해제했다. 응답이 잘리거나 `{}`·빈 문자열이면 성공 저장하지 않고 오류와 부분 결과를 보존한다. F16의 기존 빈 결과는 재실행해야 한다.
- 예비창업 `2.3.6`, 초기창업 `3.3.6`은 F18을 `USER_FLOW`와 `SERVICE_ARCHITECTURE`로 각각 호출한다. 생성된 두 SVG는 `result.json`의 `images`에 저장되고 UI 생성 영역에도 표시된다.
- 최신 결과의 모델 열에는 `설정 모델`, `실행 모델`, 대체 호출 시 `대체 사유`가 함께 표시된다. OpenAI 연결 확인 버튼은 `.env`/환경변수의 키 설정 여부와 실제 API 연결 성공·실패 상태를 UI와 로그에 남긴다.
- 함수 실행 테스트의 기존 `현재 탭 JSON 불러오기` 버튼은 `현재 탭 사용자 입력데이터 JSON 다운로드`로 변경했다. 입력 영역에는 back JSON이 탭 선택 시 자동 적용된다. 별도로 `result.json 다운로드` 버튼을 제공한다.
- 설명 탭은 함수 흐름 카드 없이 `함수별 데이터 계약` 표만 표시한다. 실행 결과는 `res/to_back/runs/<시각>_<유형>_<runId>/`에 `result.json`, `result.html`, `manifest.json`으로 누적 저장한다.

### 서버 재시작

```powershell
Get-Process python,pythonw -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
cmd /c agent_strategy\\testing\\start_function_test.cmd
```

서버는 `http://127.0.0.1:8765/`에서 실행하며, `file://` UI도 로컬 API에 연결할 수 있다.


## 2026-09-30 추가 검증 규칙

back JSON에 `_strategy_limits`를 전달하면 작성 결과 검증에 공고 제약과 기능 목록 불변식을 적용한다.

```json
"_strategy_limits": {
  "deadline": "2027-02",
  "supportLimit": 100000000,
  "featureList": ["핵심 기능 1", "핵심 기능 2"]
}
```

- `deadline`: 개발 종료월이 공고 접수 마감일 이후이면 F19가 실패한다.
- `supportLimit`: 정부지원사업비가 지원규모 상한을 넘으면 F19가 실패한다.
- `featureList`: 전략 단계에서 확정한 기능이 F16 본문에 누락되면 F19가 실패한다.

공통 제약 파일은 사용하지 않는다. 실제 값은 각 back 수령 JSON의 `_strategy_limits`에 프로젝트·공고별로 함께 전달한다. 값이 없으면 해당 제약 비교를 수행하지 않으며, 임의의 마감일·지원금·기능을 생성하지 않는다.

검증 결과는 항목별 `results[].validation`, 전체 `validation1`, 정리된 `validation_results`에 기록되며 실행 폴더에 `validation.json`을 별도로 저장한다.

## Agent 영역 연결 상태

검증 1 판정 코드는 `agent_validation/validation_1.py`에 별도 Agent 영역으로 관리한다. 현재 개발 테스트에서는 `agent_strategy/runtime/pipeline.py`가 F16/F17/F18 결과 생성 후 검증 1을 호출하고, `agent_strategy/testing/test_server.py`가 UI 요청·진행 상태·결과 저장을 담당한다. 전체 Supervisor인 `agent-orchestration`과의 통합은 이후 연동 단계이며, 현재 전략·작성 테스트가 전체 7개 Agent가 완료된 것처럼 결과를 기록하지 않는다.

## 전략 Agent 분석 기록

F01~F15 trace는 사업계획서 항목별 생성 결과와 분리해 UI의 `전략 Agent 분석 기록` 영역에서 확인할 수 있다. 함수별 요청 모델·실제 사용 모델·상태·입력 크기·토큰 사용량·결과 요약을 별도 표시하며, 실행 결과 JSON의 `trace`를 기준으로 복원한다.




## 오류 처리 및 변경 이력

### 2026-09-30

- F17 표 생성을 Python 원본 행 변환으로 복구했다. 전략·작성 실행에도 표를 포함한다.
- 예비창업은 수령한 단계별 예산을 사용하고, 초기창업은 사업비_집행계획을 보존한다.
- 단계가 없는 예산은 두 단계에 임의 배분하지 않고 각 표의 
ules.unassignedOriginalRows와 생성 텍스트에 단계 미지정 원본으로 표시하며 합계에는 중복 산입하지 않는다.
- 추가 항목은 
ules.additions에 별도로 관리하며 현재 자동 추가하지 않는다. 미입력 수량·단가는 확인 필요로 남긴다.
- F16의 빈 응답·{}를 본문 성공 결과로 저장하지 않으며, 출력 토큰 한도 도달도 실패로 처리한다.
- 기존 저장 파일의 빈 본문은 자동 복구하지 않으므로 해당 항목을 재생성해야 한다.



