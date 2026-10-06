"""코드 점검 15점을 조립한다: 통과 필수 조건 → 8항목 → 15점 환산.

verification_agent는 engineering_agent를 import하지 않는다 — 그래서 검사
대상은 파일 경로/문자열로만 받는다. 산출물을 메모리 객체로 공유하면 "계획서 대조가
성립하려면 계획서와 프로토타입이 각각 독립적으로 존재해야 한다"는 전제가 깨진다.

반환 모양은 두 카테고리가 같다:
    {"total": 0~15, "items": 8칸, "passed": 필수 조건 통과 여부,
     "gate_failures": [사유 문구], "gate_codes": ["entry" | "secret" | "sandbox"],
     "warnings": [...]}
passed는 "채점 자격이 있었는가"만 뜻한다. 최종 합격/불합격은 팀 Threshold로 따로 판정한다.
gate_codes는 조율이 재수행 대상을 고르는 값이고(CodeCheckResult.gate_failures), gate_failures는
화면 · 진단용 문구다. warnings는 점수에 들어가지 않는 결함이다(지금은 README — rules/gates.py).
"""

from verification_agent.rules import items as item_rules
from verification_agent.rules.gates import GateFailure, html_gates, readme_warnings, svg_gates
from verification_agent.rules.r4 import ITEM_DEFS as HTML_ITEMS, check_html
from verification_agent.rules.r4_onepage import ITEM_DEFS as ONEPAGE_ITEMS, check_onepage


def _assemble(gates: list[GateFailure], warnings: list[str], defs, run) -> dict:
    if gates:
        messages = [message for _, message in gates]
        codes = list(dict.fromkeys(code for code, _ in gates))
        reason = "통과 필수 조건 실패로 검사 생략: " + "; ".join(messages)
        return {"total": 0.0, "items": item_rules.skipped(defs, reason), "passed": False,
                "gate_failures": messages, "gate_codes": codes, "warnings": warnings}
    items = run()
    return {"total": item_rules.total(items), "items": items, "passed": True,
            "gate_failures": [], "gate_codes": [], "warnings": warnings}


def compute_code_check(entry_file_path: str, html_content: str, readme_content: str | None,
                       infographic_content: str | None = None) -> dict:
    """웹개발 · AI_API. infographic_content는 T-B2 인포그래픽 SVG 원문(선택) —
    넘기면 2번(대체 텍스트)이 인포그래픽도 함께 판정한다."""
    return _assemble(html_gates(entry_file_path, html_content),
                     readme_warnings(readme_content, "html"), HTML_ITEMS,
                     lambda: check_html(html_content, infographic_content))


def compute_infographic_check(entry_file_path: str, svg_content: str,
                              readme_content: str | None = None) -> dict:
    """원페이지. 검사 대상은 T-B2가 만든 SVG다 — 원페이지는 T-B1이 생략돼 HTML이 없다.
    어느 함수를 부를지는 호출자(run_tv2)가 Prototype.kind로 고른다."""
    return _assemble(svg_gates(entry_file_path, svg_content),
                     readme_warnings(readme_content, "svg-onepage"), ONEPAGE_ITEMS,
                     lambda: check_onepage(svg_content))
