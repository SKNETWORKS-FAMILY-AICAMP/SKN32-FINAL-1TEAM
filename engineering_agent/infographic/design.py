"""인포그래픽의 내부 디자인 사양. 계획서에서 뽑은 재료가 보여 주는 관계로 지면 구성 · 대표 그림 · 그림체를 정한다.

예전에는 아이템 이름 해시로 뼈대 6개 중 하나를 골라 모델에게 "그대로 따르라"고 했다. 이름은 사업 내용과
관계가 없어서, 계획서가 달라도 구성이 비슷하거나 사업에 맞지 않는 구성이 나왔다(실측: 예시 계획서 셋이 같은
첫인상). 이제 모델은 재료만 빠짐없이 뽑고(content.py), 구성은 이 모듈이 재료를 보고 정한다 — 패키지 원칙
"LLM에게는 값만 받고 배치는 코드가 한다"와 같은 방향이다.

사양은 내부 값이다. 조율 계약에 싣지 않는다. 같은 재료면 같은 사양이 나온다. 새 구성(redesign)은 사용자가 고칠
문제 없이 인포그래픽 재작성을 고른 때만 쓴다 — 두 번째로 두드러진 관계로 바꾼다. 재수행 · 미달 사유가 있는
재작성은 문제된 곳만 고치고 잘 된 부분은 지킨다(기획서 5-6, 결정 0010).
"""
from __future__ import annotations

import re

from engineering_agent.infographic import themes
from engineering_agent.infographic.layout import parse_milestones

# 관계 이름 → 그 관계를 맨 앞에서 보여 주는 구역.
STEPS, COMPARE, NETWORK, DEAL, MARKET, STORY = "단계 흐름", "전후 비교", "주체 연결", "거래 흐름", "시장 규모", "문제 해결 이야기"
# 점수가 같으면 이 순서로 고른다. 단계 · 이야기는 다른 관계 재료가 없을 때의 기본값이라 뒤에 둔다.
_ORDER = (COMPARE, NETWORK, DEAL, MARKET, STEPS, STORY)
_NUMBER_RE = re.compile(r"\d")

# 소비자를 직접 상대하는 분야(색 테마 기준)는 평면 일러스트, 기업 · 산업 · 데이터 분야는 정밀한 선 아이콘.
_FLAT_THEMES = {"orange", "rose", "green"}
# 구역 틀 순서(design_kit.FRAME_STYLES와 같은 이름). 새 구성 요청이면 다음 것으로 넘긴다.
FRAME_ORDER = ("card", "panel", "open")


def _text(value) -> str:
    return str(value or "").strip()


def _rows(data: dict, key: str, first: str) -> list[dict]:
    return [r for r in data.get(key) or [] if isinstance(r, dict) and _text(r.get(first))]


def _steps(category: str, data: dict) -> list[str]:
    steps = data.get("solution_steps") if category == "원페이지" else data.get("flow_steps")
    return [s for s in steps or [] if _text(s)]


def parties(data: dict) -> set[str]:
    """돈을 내는 쪽 · 목표 고객 · 효과를 보는 대상 — 지면에 등장하는 서로 다른 주체."""
    flow = data.get("revenue_flow") if isinstance(data.get("revenue_flow"), dict) else {}
    found = {_text(r.get("who")) for r in _rows(data, "effects", "who")}
    found |= {_text(flow.get("payer")), _text(data.get("target_users"))}
    return {p for p in found if p and p not in ("정보 없음", "확인 필요")}


def relation_scores(category: str, data: dict) -> dict[str, int]:
    """관계마다 재료가 얼마나 뚜렷한지. 0이면 그 관계를 보여 줄 재료가 없다."""
    steps = _steps(category, data)
    flow = data.get("revenue_flow") if isinstance(data.get("revenue_flow"), dict) else {}
    comparison = data.get("comparison") if isinstance(data.get("comparison"), dict) else {}
    before_after = [r for r in _rows(data, "before_after", "label")
                    if _text(r.get("before")) and _text(r.get("after"))]
    scores = {
        # 단계는 기본값이다. 웹개발은 화면 흐름이 필수 재료라 늘 있고 원페이지도 절차를 자주 뽑아, 2점을 주었더니
        # 실제 예시 계획서 셋이 모두 '단계 흐름'으로 골라졌다. AI API는 맨 위 처리 단계 도식(hub)이 이미 단계를
        # 보여 주므로 0점 — 그다음 자리는 다른 관계가 앞세운다.
        STEPS: (0 if category == "AI_API" else 1 if len(steps) >= 2 else 0),
        COMPARE: (2 if len(before_after) >= 2 else 0) + (1 if len(_rows(comparison, "rows", "criterion")) >= 2 else 0),
        NETWORK: 0 if len(parties(data)) < 3 else 2 if len(parties(data)) == 3 else 3,
        DEAL: (1 if _text(flow.get("payer")) and _text(flow.get("payment")) else 0)
              + (1 if _NUMBER_RE.search(_text(flow.get("payment")) + _text(data.get("revenue_unit_price"))) else 0),
        MARKET: 0 if len(_rows(data, "market_levels", "label")) < 2 else len(_rows(data, "market_levels", "label")) - 1,
        STORY: 1 if _text(data.get("problem")) and _text(data.get("solution")) else 0,
    }
    if not _text(flow.get("payer")):
        scores[DEAL] = 0  # 내는 쪽이 없으면 흐름 도식을 그릴 수 없다
    return scores


def _ranked(category: str, data: dict) -> list[tuple[str, int]]:
    scores = relation_scores(category, data)
    return sorted(((r, s) for r, s in scores.items() if s > 0), key=lambda rs: (-rs[1], _ORDER.index(rs[0])))


def _block(block: str, variant: str, width: str = "full") -> dict:
    return {"block": block, "variant": variant, "width": width}


def _lead(relation: str, category: str, data: dict) -> list[dict]:
    """그 관계를 맨 앞에서 보여 주는 구역."""
    if relation == STEPS:
        return [] if category == "AI_API" else [_block("process", "steps")]  # AI API는 맨 위 처리 도식이 단계다
    if relation == COMPARE:
        if len([r for r in _rows(data, "before_after", "label") if _text(r.get("after"))]) >= 2:
            return [_block("problem_solution", "before_after")]
        return [_block("competition", "table")]
    if relation == NETWORK:
        return [_block("effects", "cards")]
    if relation == DEAL:
        return [_block("revenue", "flow")]
    if relation == MARKET:
        return [_block("market", "nested", "half"), _block("competition", "table", "half")
                if len(_rows(data.get("comparison") or {}, "rows", "criterion")) >= 2 else _block("metrics", "cards", "half")]
    if category == "AI_API":  # AI API 맨 위는 처리 단계 도식(hub)이 필수다. 이야기는 두 판으로 보인다.
        return [_block("problem_solution", "split")]
    return [_block("hero", "journey")]


def _available(category: str, data: dict) -> list[dict]:
    """재료가 있는 나머지 구역. 읽는 순서(문제 → 기능 → 과정 → 돈 · 시장 → 일정 → 성과 → 효과)대로."""
    out = []
    if _text(data.get("problem")) and _text(data.get("solution")):
        out.append(_block("problem_solution", "split"))
    features = data.get("features") or []
    out.append(_block("features", "band" if len(features) <= 4 else "grid"))
    if len(_steps(category, data)) >= 2:
        out.append(_block("process", "steps"))
    if _rows(data, "market_levels", "label")[1:]:
        out.append(_block("market", "nested", "half"))
    if len(_rows(data.get("comparison") or {}, "rows", "criterion")) >= 2:
        out.append(_block("competition", "table", "half"))
    flow = data.get("revenue_flow") if isinstance(data.get("revenue_flow"), dict) else {}
    if _text(flow.get("payer")):
        out.append(_block("revenue", "flow", "half"))
    elif _text(data.get("revenue_unit_price")) not in ("", "정보 없음"):
        out.append(_block("revenue", "card", "half"))
    stones = parse_milestones(_text(data.get("timeline_baseline")))
    if stones:
        out.append(_block("roadmap", "line", "full" if len(stones) >= 4 else "half"))
    metrics = [m for m in data.get("key_metrics") or [] if isinstance(m, dict) and _text(m.get("value"))]
    if metrics:
        bars = len([m for m in metrics if _text(m.get("before"))]) >= 2
        out.append(_block("metrics", "bars" if bars else "cards", "half" if bars else "full"))
    if len(_rows(data, "effects", "who")) >= 2:
        out.append(_block("effects", "cards"))
    return out


def decide(category: str, data: dict, redesign: bool = False) -> dict:
    """{relation, layout, hero, art_style, reasons}. layout은 composer.normalize_layout이 받는 모양이다."""
    ranked = _ranked(category, data) or [(STORY, 0)]
    pick = 1 if redesign and len(ranked) > 1 else 0
    relation, score = ranked[pick]
    reasons = [f"관계 '{relation}'(재료 점수 {score})" + (" — 새 구성 요청이라 두 번째 관계" if pick else "")]
    if redesign and len(ranked) == 1:
        reasons.append("새 구성 요청이지만 다른 관계 재료가 없어 구역 변형을 바꾼다")

    lead = _lead(relation, category, data)
    taken = {b["block"] for b in lead}
    rest = [b for b in _available(category, data) if b["block"] not in taken]
    if any(b["block"] == "hero" for b in lead):  # 이야기 도식이 문제 · 해결을 이미 보여 준다
        rest = [b for b in rest if b["block"] != "problem_solution"]
    if relation != STORY:  # 문제부터 읽히게 문제 판을 맨 앞에 둔다(관계 구역이 바로 뒤)
        problem = [b for b in rest if b["block"] == "problem_solution"]
        rest = [b for b in rest if b["block"] != "problem_solution"]
        lead = problem + lead
    layout = lead + rest + [_block("tagline", "band")]
    if redesign and len(ranked) == 1:
        for b in layout:
            if (b["block"], b["variant"]) == ("features", "band"):
                b["variant"] = "grid"
            elif (b["block"], b["variant"]) == ("features", "grid"):
                b["variant"] = "band"

    theme = themes.pick(data)
    art_style = "평면" if theme in _FLAT_THEMES else "선화"
    reasons.append(f"그림체 '{art_style}' — 색 테마 {theme}(" + ("소비자 대상 분야" if art_style == "평면"
                                                             else "기업 · 산업 · 데이터 분야") + ")")
    # 맨 위 그림도 같은 관계를 보여 준다. 단계는 단계 구역(또는 AI API 처리 도식)이 이미 보여 주므로
    # AI API가 아니면 대표 장면으로 둔다(같은 단계를 두 번 그리지 않는다).
    if category == "AI_API":
        hero = "steps"
    elif any(b["block"] == "hero" for b in layout):
        hero = "panorama"
    else:
        hero = {NETWORK: "hub"}.get(relation, "scene")
    # 구역 틀. 소비자 대상 분야는 부드러운 옅은 색 판, 제조 · 산업은 도면처럼 틀 없이 선과 여백, 그 밖(데이터 ·
    # 유통 · 공공 등)은 칸이 분명한 흰 카드. 새 구성 요청이면 다음 틀로 넘긴다.
    frame = "panel" if art_style == "평면" else "open" if theme == "steel" else "card"
    if redesign:
        frame = FRAME_ORDER[(FRAME_ORDER.index(frame) + 1) % len(FRAME_ORDER)]
    reasons.append(f"구역 틀 '{frame}'" + (" — 새 구성 요청이라 다음 틀" if redesign else f" — 색 테마 {theme}"))
    return {"relation": relation, "layout": layout, "hero": hero, "art_style": art_style, "frame": frame,
            "reasons": reasons}


def apply(category: str, data: dict, redesign: bool = False) -> dict:
    """사양을 정해 data에 싣는다. 모델이 적은 블록 제목은 같은 블록이면 살린다."""
    spec = decide(category, data, redesign)
    titles = {_text(b.get("block")): _text(b.get("title")) for b in data.get("layout") or [] if isinstance(b, dict)}
    layout = [dict(b, title=titles.get(b["block"], "")) for b in spec["layout"]]
    return dict(data, layout=layout, _design=spec)
