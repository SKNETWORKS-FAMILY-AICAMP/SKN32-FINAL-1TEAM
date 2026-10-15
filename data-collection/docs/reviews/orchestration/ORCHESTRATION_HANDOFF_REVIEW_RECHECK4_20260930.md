# 조율 함수 설명서 4차 개정 재검수 (2026-09-30)

검수: Codex. 대상은 [Claude의 3차 재검수 응답·요청](ORCHESTRATION_HANDOFF_REVIEW_RECHECK3_RESPONSE_20260930.md), [4차 개정 설명서](../../archive/ORCHESTRATION_HANDOFF.md), [직전 Codex 재검수](ORCHESTRATION_HANDOFF_REVIEW_RECHECK3_20260929.md)다.

## 결론

**요청 범위 재검수 승인. 직전 P2(공고 ID 입력 연결·공급 단순화 범위)는 닫는다. 추가 P1·P2·P3 지적 없음.** ⑦ 가·⑩의 보완은 현재 조율 코드와 맞고, 3.3절 5번의 판정표 오류·신선도 처리 안내와 수정한 줄 번호도 확인했다. 독립 프로브 D·A·B·C와 관련 회귀 테스트 37개가 통과했다.

이는 **설명서를 조율 담당에게 전달해 계약 합의를 진행해도 된다는 승인**이다. 실제 공고 공급과 확인 필요 화면 표시까지 구현·검증됐다는 뜻은 아니다.

## 1. 직전 P2 재확인

| 항목 | 확인 결과와 근거 |
|---|---|
| ⑦ 가·⑩의 공고 ID 전달 | **수정 확인.** 설명서 [113행](../../archive/ORCHESTRATION_HANDOFF.md#L113)과 [457행](../../archive/ORCHESTRATION_HANDOFF.md#L457)이 `G01In` 모델과 G-01 입력 연결을 함께 바꾸도록 적었다. 현재 [catalog.py:55-58](../../../../agent-orchestration/sbrain/flow/catalog.py#L55)의 입력에는 공고 ID가 없다. [engine.py:277-331](../../../../agent-orchestration/sbrain/orchestrator/engine.py#L277)은 `spec.inputs`에 명시된 칸만 만들고, [232-237행](../../../../agent-orchestration/sbrain/orchestrator/engine.py#L232)에서 모델 검증한다. 따라서 새 필수 ID 칸만 추가하고 연결을 빠뜨리면 입력 검증에서 실패한다는 설명이 맞다. |
| (ㄱ) 확인 필요 목록만 추가 | **수정 확인.** 현재 [Announcement:164-165](../../../../agent-orchestration/sbrain/models/domain.py#L164)와 [G01In:101-102](../../../../agent-orchestration/sbrain/contracts/tasks.py#L101)의 `eligibility`·`eligibility_parsed`는 기본값 없는 필수 필드다. 이 계약을 유지한다면 공고 공급 단계의 `eligibility_of()`도 유지해야 한다는 설명이 맞다. |
| (ㄴ) 공고 공급까지 단순화 | **수정 확인.** 두 필드를 `Announcement`와 `G01In`에서 선택으로 바꾸거나 제거하고 입력 연결에서도 빼야 한다는 범위가 적혔다. 그 뒤 G-01 내부에서 `eligibility_of(공고ID)`로 조건을 구하도록 안내한다. ID만 추가하고 공급 변환을 없애면 필수 칸이 비어 실패한다는 경고도 적절하다. |
| 확인 필요의 화면 전달 경로 | **문서 보완 확인.** [RunView:42-51](../../../../agent-orchestration/sbrain/flow/service.py#L42)에 `gateResult`가 없다는 설명은 현재 코드와 같다. 화면이 해당 산출물을 읽거나 별도 표시용 칸을 받도록 합의해야 한다는 점을 [설명서 105행](../../archive/ORCHESTRATION_HANDOFF.md#L105)에 적었다. 화면 구현은 이번 범위 밖이다. |

합격·불합격은 설명서의 `g01()` 규칙으로 정하고 `app.eligibility()`는 확인 필요 목록의 재료로만 사용하는 구분도 유지됐다. 후자는 접수 시작 전 공고를 X로 판정하므로 그대로 G-01의 통과 여부에 사용하면 안 된다는 4.5절 안내와 일치한다.

## 2. 3.3절 5번 판정표 동작 안내

[설명서 164-170행](../../archive/ORCHESTRATION_HANDOFF.md#L164)을 현재 코드 및 관련 회귀 시험과 대조했다.

| 안내 | 확인 결과 |
|---|---|
| 깨진 결과 파일 줄은 건너뜀 | `applicant_types.load()`는 줄별 JSON·필드 오류를 `bad_lines`로 세고 계속 읽는다. 구조화된 잘못된 ID, 손상된 JSON, 파일 읽기 오류 관련 기존 시험도 통과했다. |
| 현재 공고문과 지문이 다른 판정은 쓰지 않음 | [fresh_only()](../../../search/applicant_types.py#L260)가 현재 지문과 일치하는 출처만 고른다. [load_auto()](../../../search/applicant_types.py#L290)는 DB·파일·개발용 file 모드 모두 이 검사를 거친다. |
| 지문 계산 실패·사용 가능한 판정 0건이면 기능만 끄고 이유 기록 | `load_auto()`는 `active=False`와 `error`를 반환한다. [boot():171-174](../../../search/app.py#L171)는 그 이유를 `boot_errors.applicant_types`에 남긴다. 지문 계산 실패·빈 판정표 관련 회귀 시험도 통과했다. |
| 예상 밖 판정 읽기 예외도 기능만 끔 | [boot():155-167](../../../search/app.py#L155)의 `judged()`가 두 판정 로더의 `Exception`을 잡아 해당 기능을 비활성화하고 `boot_errors`에 기록한다. 이 경로는 코드로 확인했다. |
| 발췌 밖 '예비창업' 언급이 있으면 strong 불가를 확인 필요로 낮춤 | [mark_unread()](../../../search/applicant_types.py#L239) → [pre_founder()](../../../search/applicant_types.py#L375)·[type_check()](../../../search/applicant_types.py#L402)의 연결을 확인했다. 원문 없음·지문 불일치의 확인 불가도 strong 불가로 쓰지 않는다. 반복 문구·단어 중간 공백·첨부 경계의 기존 회귀 시험이 통과했고, 실제 DB 프로브에서도 확인 필요 2건이 유지됐다. |

여기서 ‘지원대상 유형 줄’은 공고팀 `app.eligibility()`의 `checks`에 있는 조건 줄이다. 현재 조율 `GateResult`에 확인 필요 목록이 이미 저장되거나 화면에 표시된다는 의미로 확대하지 않는다. 그 계약과 화면 전달은 설명서 ⑦의 합의 대상이다.

시작 시간 증가 약 2초·21.7초는 설명서에 기록된 9/29 측정값이다. 이번 독립 실행의 전체 준비 시간은 27.1초였으며, 지문 처리만의 추가 시간을 따로 재측정하지 않았다.

## 3. 줄 번호·코드 블록 확인

- 공고팀 정의 시작 줄 **7곳 일치**: `search/app.py`의 `FIELDS` 47, `boot` 108, `MatchRequest` 294, `GateRequest` 348, `match` 387, `eligibility` 828; `search/collection_status.py`의 `check` 133.
- 업력 설명 구간 `app.py:859-885`는 실제 업력 조건의 근거·설명 처리 구간이다.
- 설명서의 줄 번호가 붙은 코드 링크 **19개**를 실제 파일과 대조했다. `catalog.py:55-58`, `RunView:42-51`, 날짜 비교 `service.py:259`, `isoformat()` 사용 `stubs.py:247,392` 등을 포함해 가리키는 내용이 맞았다. 예시 코드 안의 `service.py:103,120`·`sbrain_flow.py:196` 주석도 현재 분기와 맞다.
- 설명서의 Python 코드 블록 **3개**는 커밋 `2720490`과 동일하다. `experiments/orchestration_probe.py`도 `2720490`부터 현재 HEAD까지 변경이 없다.

## 4. 이번 독립 실행 결과

검수 기준: `feature/SB-189-data-collection`, HEAD `6ad6ffc`; 조율 파일의 마지막 변경 커밋은 `0a48e34`(SB-85 #9)이다. 이번에 읽은 설명서·프로브·주요 검수 대상 코드는 HEAD와 차이가 없었다.

프로젝트 `.venv/Scripts/python.exe`는 기반 Python 프로세스를 만들지 못했다. 번들 Python과 기존 `.venv/Lib/site-packages`를 조합해 같은 모듈을 실행했다. 기본 샌드박스에서는 DB 소켓이 `WinError 10013`으로 차단되어 프로브가 D의 `boot()`에서 중단됐다. 공용 DB 읽기 전용 실행을 위한 권한 확대가 승인된 뒤 다시 실행했고, 아래 결과를 얻었다. 모델은 오프라인 캐시를 사용했고 바이트코드 생성을 껐다.

실행 대상은 다음과 같다(`data-collection/` 작업 디렉터리).

```text
python -B -X utf8 -m experiments.orchestration_probe --sbrain ../agent-orchestration
python -B -X utf8 -m unittest discover -s tests -p test_judgments_source.py
```

위 명령은 실행 대상 표현이다. 실제 호출은 번들 Python에서 `sys.path`에 프로젝트 가상환경 패키지를 추가한 뒤 각각 `runpy.run_module()`·`unittest` discovery로 실행했다.

| 검사 | 이번 결과 |
|---|---|
| 준비·판정 신선도 | 공고·Chroma·BM25 각 **2,603건**, 준비 **27.1초**. 신청자 유형 판정 **2,603건 모두 현재 지문 일치**(DB 2,603·파일 0), 발췌 밖 언급으로 확인 필요 **2건**. |
| D 빠른 시작 | 수집 정상·추천 10건. 지연 대역은 `('지연', [])`, 0건 대역은 `('정상', [])`. **통과**. |
| A T-C2 | offset 0은 1~10위, offset 10은 11~20위. 필터 통과 1,637건. 수집 지연 대역은 첫 조회 0건·더 보기 10건. **통과**. |
| B G-01 | 공고 **2,603건 × 신청자 5가지 경우 = 13,015회** 대조. 매칭 필터(마감 검사 제외)와 G-01 통과 여부의 **차이 0**. |
| C 조율 스텁 흐름 | 더 보기 11~20위·후보 버전 2·실패 알림 없음 → G-01 통과 → `계획서작성/사용자대기`. **통과**. |
| C′ 더 보기 시간 초과 주입 | 후보 버전 1·1위부터·`X-C2-FAIL`이 남아 검사 세 항목이 실패했다. **검사가 실패를 검출함**. |
| 프로브 종합 | **D·A·B·C 모두 통과, 종료 코드 0**. |
| 판정표 출처·신선도·발췌 경계 회귀 시험 | `test_judgments_source.py` **37개 실행, 실패·오류·건너뜀 0**, 종료 코드 0. 공용 DB 없는 대역 시험이다. |

B는 두 구현의 결론 일치를 확인한 것이며, 사람 기준 신청 자격의 정확도를 뜻하지 않는다. C는 양식·평가 항목·금액 등을 조율 스텁에서 공급하므로 실제 `Announcement` 공급의 검증을 대신하지 않는다.

## 5. 변경 범위·미검증·다음 단계

- **이번에 작성한 파일은 이 결과 문서 하나뿐이다.** 사용자 지시를 우선해 STATUS·WORKLOG·문서 지도도 수정하지 않았다. 코드·DB 데이터·설명서·프로브·Git 스테이징·커밋·push는 변경하지 않았다. 공용 DB는 프로브의 조회만 실행했고 유료 API는 호출하지 않았다.
- 시작 때 존재한 Claude의 상태·이력·인계서·공유 자료 변경과 미추적 파일을 보존했다. 검수 중 별도 작업의 `collect/daily_job.py`·`shared/store_mysql.py` 수정도 나타났으며, 이 작업에서 수정하거나 검수 대상으로 확장하지 않았다.
- 전체 테스트 663개는 이번에 재실행하지 않았다. 이번 결과는 위 프로브와 관련 회귀 시험 37개에 한정한다.
- 요청서가 제외한 실제 공고 공급, 확인 필요 화면 표시, `apply_period_type` 모델 추가, Linux(EC2), 동시 요청·프로세스 교체는 검증하지 않았다. 서비스 서버도 재시작하지 않았다.
- **다음 단계:** 설명서를 조율 담당에게 전달하고 2절 ①②③⑦ 및 나머지 계약을 합의한 뒤, 합의한 모델·입력 연결·화면 경로로 실제 공고 공급 통합 시험을 한다.
