"""호출 목적 이름 — 담당자 함수 번호(F번호) 그대로 (spec 4.2).

tools.llm(…, purpose=F번호)의 목적이고, Task 설정의 목적별 모델(purposeModels) 키다. 이름은 이 상수에서만 쓴다 —
글자가 갈라지면 목적별 모델이 적용되지 않고 Task 모델로 부른다. 엔진(orchestrator/)은 이 이름을 모른다.
F17(표) · F20(문서 조립)은 LLM을 부르지 않지만 담당자 번호 체계를 그대로 두려고 F17까지 둔다(F20은 범위 밖).
"""
from __future__ import annotations

F01, F02, F03, F04, F05, F06, F07, F08, F09, F10 = (f"F{n:02d}" for n in range(1, 11))
F11, F12, F13, F14, F15, F16, F17, F18, F19 = (f"F{n:02d}" for n in range(11, 20))

# 모든 목적 이름 (F01 ~ F19)
PURPOSES: frozenset[str] = frozenset((F01, F02, F03, F04, F05, F06, F07, F08, F09, F10,
                                      F11, F12, F13, F14, F15, F16, F17, F18, F19))

# 로컬 자료 검색(research_context.retrieve)의 tools.search 목적 (spec 4.1) — LLM 호출이 아니다
SEARCH = "자료 검색"
