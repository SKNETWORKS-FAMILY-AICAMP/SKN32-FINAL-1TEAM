# business_plan_prompts

정부지원사업 사업계획서 작성 Agent가 참고할 프롬프트 모음입니다.

실제 Agent 실행에는 사업별 템플릿 하나만 사용합니다. 공통 문체·페르소나·예시 기반 작성 규칙은 각 사업별 템플릿에 필요한 만큼 흡수되어 있으므로, 초기창업패키지를 작성할 때는 `business_plan_prompt_template_early_startup.md` 하나만 넘기면 됩니다.

## 실행용 템플릿

| 파일 | 대상 사업 | 사용 방식 |
| --- | --- | --- |
| `business_plan_prompt_template_pre_startup.md` | 예비창업패키지 | 예비창업패키지 HWP 양식에 맞춘 단독 실행용 프롬프트 |
| `business_plan_prompt_template_restart.md` | 재도전성공패키지 | 재도전성공패키지 HWP 양식에 맞춘 단독 실행용 프롬프트 |
| `business_plan_prompt_template_early_startup.md` | 초기창업패키지(일반형) | 초기창업패키지 HWP 양식 및 `plan_document_export.py`의 `PlanDocumentData`에 맞춘 단독 실행용 프롬프트 |

## 참고용 파일

| 경로 | 역할 |
| --- | --- |
| `reference/business_plan_agent_persona.md` | 사업계획서 작성 Agent의 역할, 문체, 금지사항 원본 |
| `reference/part2_writing_style_guide.md` | 샘플 PDF 기반 작성 어투·문장 구조·항목별 작성 규칙 원본 |
| `reference/business_plan_prompt_template.md` | 사업 구분 전 공통 프롬프트 원본 |
| `reference/section_checklist.md` | 추후 검증 Agent가 참고할 수 있는 작성 후 검토 체크리스트 |

참고용 파일은 사업별 템플릿을 수정하거나 새 사업 템플릿을 만들 때만 확인합니다.

## 기준 샘플 문서

`docs/공유자료/사업계획서 자료/4_(1-2)사업계획서_작성_예시_사업계획서_Part2.pdf`

이 폴더는 원문을 복제하지 않고, 샘플 PDF에서 확인한 작성 방식·문체·구성 규칙을 Agent용 지침으로 재구성합니다.

## 사용 예시

초기창업패키지를 작성할 때:

```text
1. business_plan_prompt_template_early_startup.md 파일 하나를 Agent 프롬프트로 제공
2. 시장조사 results.json, 경쟁사 competitor_results.json, 사용자 입력값을 변수에 채움
3. Agent 출력의 tableData를 HWP/docx export 단계에 전달
```

누락 항목 검토는 추후 별도 검증 Agent가 담당한다. 검증 Agent가 필요할 경우 `reference/section_checklist.md`를 참고 자료로 사용할 수 있다.

예비창업패키지와 재도전성공패키지도 같은 방식으로 각각의 사업별 템플릿 하나만 사용합니다.

## 작성 방향

- 평가자가 빠르게 이해할 수 있는 공문서형 문체를 사용한다.
- 주장만 쓰지 않고, 문제 → 개발 필요성 → 개발 내용 → 성능지표 → 검증방법 → 사업화 계획 순서로 연결한다.
- 기술적 표현은 정량 목표, 적용 대상, 검증 방법과 함께 쓴다.
- 시장성과 사업화 계획은 고객, 판로, 가격, 마케팅, 고용 효과로 나누어 작성한다.
- HWP 표 셀 삽입을 전제로 `tableData`와 `sectionText`를 함께 출력한다.
