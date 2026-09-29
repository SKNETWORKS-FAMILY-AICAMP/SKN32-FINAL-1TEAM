"""웹 백엔드가 검증-2를 부르는 진입점.

백엔드(back/app/agents.py)는 산출물층 점수를 `ArtifactScoreReason` 행으로 저장하고, 행의
score를 더해 총점을 낸다. 그래서 이 함수는 조율 계약(TV2Out) 대신 그 행 모양으로 돌려준다.
계약 모델(sbrain)에 의존하지 않아 백엔드에 sbrain이 없어도 돈다.

항목 코드는 예전 코드와 같은 개념이면 이름을 이어 쓴다(CHECK-ALT-TEXT 등).

점수 모양:
- 코드 점검 8행: 해당 없는 항목을 빼고 15점으로 환산한 값이 행마다 들어간다. 그래서
  8행의 score를 더하면 코드 점검 총점과 정확히 같고, max_score를 더하면 15다.
  해당 없는 항목은 score · max_score 모두 0이다.
- 계획서 대조 1행(FEATURE-MATCH): 0~15.
관리자가 층 배점을 15가 아닌 값으로 바꾸면 백엔드가 지금처럼 비율로 늘리면 된다.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from verification_agent.tasks import plan_text_of, score_artifact

# (항목 번호 → 항목 코드). 번호는 rules/r4.py · rules/r4_onepage.py의 ITEM_DEFS.
ITEM_CODES = {
    "html": {
        1: "CHECK-ACTION-WIRING", 2: "CHECK-ALT-TEXT", 3: "CHECK-INPUT-LABEL",
        4: "CHECK-CONTRAST", 5: "CHECK-HEADING", 6: "CHECK-LAYOUT-WIDTH",
        7: "CHECK-BROKEN-REF", 8: "CHECK-PLACEHOLDER",
    },
    "svg-onepage": {
        1: "CHECK-ALT-TEXT", 2: "CHECK-KEY-INFO", 3: "CHECK-CONTRAST",
        4: "CHECK-INFO-HIERARCHY", 5: "CHECK-TRUNCATION", 6: "CHECK-OVERFLOW",
        7: "CHECK-TEXT-REALNESS", 8: "CHECK-MIN-FONT",
    },
}
FEATURE_CODE = "FEATURE-MATCH"
_CENT = Decimal("0.01")


def _money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)


def _scaled_rows(kind: str, items: list[dict], code_total: float) -> list[dict]:
    """항목별 점수를 15점 환산 비율로 늘려, 행 합계가 code_total과 같게 한다."""
    counted = sum(i["weight"] for i in items if i["applicable"])
    scale = (15.0 / counted) if counted else 0.0
    rows = []
    for item in items:
        applicable = item["applicable"]
        rows.append({
            "item_code": ITEM_CODES[kind][item["id"]],
            "display_name": item["name"],
            "score": _money(item["earned"] * scale) if applicable else Decimal("0.00"),
            "max_score": _money(item["weight"] * scale) if applicable else Decimal("0.00"),
            "passed": bool(item["passed"]),
            "applicable": applicable,
            "reason_text": item["evidence"],
        })
    # 반올림으로 생긴 몇 센트 차이는 마지막 해당 항목이 흡수한다(백엔드 시드와 같은 방식).
    live = [r for r in rows if r["applicable"]]
    if live:
        live[-1]["score"] += _money(code_total) - sum(r["score"] for r in live)
        live[-1]["max_score"] += Decimal("15.00") - sum(r["max_score"] for r in live)
    return rows


def verify_artifact(*, category: str, prototype_path: str | None, infographic_path: str,
                    feature_list: list[str], plan_doc: dict | None = None,
                    readme_path: str | None = None,
                    infographic_alt_text: str | None = None) -> dict:
    """산출물 파일을 채점해 백엔드가 저장할 행 목록을 돌려준다.

    category: '원페이지' | '웹개발' | 'AI_API'
    prototype_path: index.html 경로. 원페이지는 None (T-B1이 없다)
    infographic_path: 인포그래픽 SVG 경로. 원페이지는 이것이 채점 대상이다
    plan_doc: PlanDoc 모양 dict (백엔드가 T-B2에 넘긴 것과 같은 것). 원페이지 대조의 근거
    infographic_alt_text: T-B2가 돌려준 대체 텍스트. 없으면 SVG <title>로 대신한다

    반환: {
        "code_total", "feature_score", "artifact_total",   # Decimal
        "rows": [ {item_code, display_name, score, max_score, passed, applicable, reason_text}, ... ],
        "missing_features", "gate_failures", "warnings",   # list[str]
    }
    warnings는 점수 밖 결함이다(README 없음 → G-04 재실행). 화면에 띄우지 말고 관리자 로그로.
    """
    kind = "svg-onepage" if category == "원페이지" else "html"
    entry = infographic_path if kind == "svg-onepage" else (prototype_path or "")
    source = Path(entry).read_text(encoding="utf-8") if entry and Path(entry).is_file() else ""
    svg = Path(infographic_path).read_text(encoding="utf-8") if Path(infographic_path).is_file() else ""
    if infographic_alt_text is None:
        start, end = svg.find("<title>"), svg.find("</title>")
        infographic_alt_text = svg[start + 7:end] if 0 <= start < end else ""

    raw, feature = score_artifact(
        kind=kind, entry_file_path=entry, source_text=source, readme_path=readme_path,
        infographic_path=infographic_path, infographic_alt_text=infographic_alt_text,
        feature_list=feature_list, plan_text=plan_text_of(plan_doc),
    )
    rows = _scaled_rows(kind, raw["items"], raw["total"])
    feature_score = _money(feature["score"])
    rows.append({
        "item_code": FEATURE_CODE, "display_name": "계획서 기능 대조",
        "score": feature_score, "max_score": Decimal("15.00"),
        "passed": not feature["missing_features"], "applicable": True,
        "reason_text": " / ".join(feature["findings"]),
    })
    code_total = _money(raw["total"])
    return {
        "code_total": code_total, "feature_score": feature_score,
        "artifact_total": code_total + feature_score, "rows": rows,
        "missing_features": feature["missing_features"],
        "gate_failures": raw["gate_failures"], "warnings": raw["warnings"],
    }
