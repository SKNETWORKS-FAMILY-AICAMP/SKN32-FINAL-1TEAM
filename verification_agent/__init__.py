"""검증-2(산출물) Agent — 규칙 기반 코드 채점(R-4) 패키지.

LLM 호출 없이 파싱/계산만으로 판정한다 — 동일 입력에 항상 동일 점수가 나오는 것이
이 패키지의 존재 이유다. engineering_agent를 import하지 않는다.
"""

from verification_agent.score import compute_code_check

__all__ = ["compute_code_check"]
