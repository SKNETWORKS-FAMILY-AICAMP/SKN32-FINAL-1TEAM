"""코드 점검 항목 한 칸의 모양과 15점 환산.

항목은 계약상 항상 8칸이다(CodeCheckResult.checks). 칸마다 배점(weight)과 실제로 얻은
점수(earned)를 따로 두는 이유는 부분 점수 때문이다 — 동작 연결처럼 "10개 중 7개"로
판정되는 항목을 통과/미통과 둘로만 적으면 결과 화면이 무엇이 모자랐는지 말하지 못한다.

검사할 대상이 아예 없는 항목(input이 없는 페이지의 라벨 연결 등)은 만점으로 치지 않고
applicable=False로 빼고 나머지 배점으로 15점을 다시 환산한다. 만점으로 치면 "아무것도
안 만들수록 점수가 오르는" 공짜 점수가 된다.
"""
from __future__ import annotations

TOTAL = 15.0


def item(no: int, name: str, weight: float, passed: bool, evidence: str, *,
         earned: float | None = None, applicable: bool = True) -> dict:
    if not applicable:
        return {"id": no, "name": name, "weight": weight, "passed": True,
                "evidence": f"해당 없음 — 배점에서 빼고 환산 ({evidence})",
                "earned": 0.0, "applicable": False}
    if earned is None:
        earned = weight if passed else 0.0
    return {"id": no, "name": name, "weight": weight, "passed": passed,
            "evidence": evidence, "earned": round(earned, 4), "applicable": True}


def skipped(defs: tuple[tuple[int, str, float], ...], reason: str) -> list[dict]:
    """통과 필수 조건이 깨졌을 때 8칸을 전부 0점으로 채운다."""
    return [item(no, name, weight, False, reason) for no, name, weight in defs]


def total(items: list[dict]) -> float:
    counted = [i for i in items if i["applicable"]]
    weight = sum(i["weight"] for i in counted)
    if not weight:
        return 0.0
    return round(TOTAL * sum(i["earned"] for i in counted) / weight, 2)


def fail(items: list[dict], no: int, reason: str) -> None:
    """호출자(run_tv2)가 파일 바깥 정보로 한 칸을 뒤집을 때 쓴다."""
    for entry in items:
        if entry["id"] == no:
            entry.update(passed=False, earned=0.0, applicable=True, evidence=reason)
