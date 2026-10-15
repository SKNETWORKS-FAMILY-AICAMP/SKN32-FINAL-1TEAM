"""원페이지 SVG 코드 점검 8항목.

기획서 5-4의 초기 배점표를 검증-2 담당이 재구성했다(2026-09-29, 이유는 아래
'판정 대상을 구조에서 내용으로 옮긴 이유'). 진입 파일과 열람 안내 문서는 정상 산출물이면 항상
통과하므로 점수에서 뺐다 — 진입 파일은 통과 필수 조건으로, 안내 문서(G-04가 만듦)는 점수 밖
경고로 옮겼다(rules/gates.py). 그 자리에 원페이지에서
실제로 자주 깨지는 두 가지, 값이 잘려 들어간 것과 지면 밖으로 밀려난 것을 따로 둔다.

| No | 항목 | 배점 |
|:-:|---|:-:|
| 1 | 대체 텍스트 | 2 |
| 2 | 핵심 정보 6항목 | 3 |
| 3 | 명도 대비 4.5:1 | 2 |
| 4 | 정보 계층 | 2 |
| 5 | 잘림 없음 | 2 |
| 6 | 지면 밖 넘침 없음 | 2 |
| 7 | 텍스트 실재성 | 1 |
| 8 | 최소 글자 크기 | 1 |

## 판정 대상을 구조에서 내용으로 옮긴 이유

기획서 5-4의 8항목은 "생성 모델이 SVG를 직접 그린다"는 전제로 설계됐다 — 6번 설명이
"생성 모델이 SVG 안에 텍스트를 이미지로 박아 넣으면"이라고 쓴 것이 그 근거다.
그러나 구현 Agent는 LLM에서 JSON만 받고 코드가 고정 템플릿에 채우는 방식이다
(engineering_agent/infographic). 그래서 구조를 보는 항목은 템플릿이 구조를 보장하는
탓에 전부 상시 통과가 되고, 실제 위험(LLM이 값을 부실하게 채우는 것)을 보는 항목이
3번 하나만 남았다. 측정 결과 15점 척도가 실제로 움직이는 폭이 1.67점이었고,
여섯 항목을 모두 "정보 없음"으로 채운 지면이 만점을 받았다.

그래서 각 항목의 판정 대상을 내용으로 옮겼다. 항목·배점·판정 방식은 검증-2 담당
범위다.

## 항목을 찾는 방법

산출물의 text 노드 순서에 의존하지 않는다. 구현 Agent가 값 노드에 붙이는
data-field / data-role 표식으로 찾는다. 순서에 의존하면 템플릿 머리말에 한 줄만
추가돼도 엉뚱한 노드를 값으로 읽으면서 **조용히 통과한다** — 틀렸을 때 틀렸다고
말하지 못하는 검사는 검사가 아니다.
"""
from __future__ import annotations

from xml.etree import ElementTree as ET

from verification_agent.rules.color import contrast_ratio, parse_color
from verification_agent.rules.items import banded, item

# 값이 실재하지 않는데 자리만 채운 문구. 구현 Agent가 빈 값에 적는 문구
# (engineering_agent/infographic/svg_parts.py의 EMPTY_VALUE_TEXT)를 포함하며,
# 이 문구가 들어간 항목은 충족으로 세지 않는다 — 세면 "정보 없음" 여섯 개가 만점을 받는다.
_PLACEHOLDER_VALUES = {"정보 없음", "미정", "해당 없음", "n/a", "na", "-", "tbd", "없음",
                       "확인 필요", "확인필요", "추후 확인", "추후 결정", "미입력"}

# 2번 필수 6항목. (data-field 이름, 화면 라벨)
_REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("item_name", "아이템명"),
    ("target_users", "목표 고객"),
    ("problem", "문제 정의"),
    ("solution", "해결 방안"),
    ("revenue_unit_price", "수익모델 단가"),
    ("timeline_baseline", "추진 일정 기준선"),
)

_PAGE_WIDTH = 900.0
_MIN_FONT_PX = 12.0
# 7번: 래스터에 묻힌 비율 상한. 기획서 5-4가 "래스터 이미지에 묻힌 비율 검사"라고
# 쓴 것을 지면 면적 대비 보이는 그림 면적으로 구현한다. 일러스트(대표 그림 + 구역 그림)는
# 지면의 15~25%를 차지한다(실측). 그 이상이면 글자를 그림으로 대신한 지면으로 본다.
_MAX_IMAGE_AREA_RATIO = 0.35


def _parse_svg(source: str):
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        return None
    return root if root.tag.endswith("}svg") or root.tag == "svg" else None


def _nodes(root, name: str):
    return [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == name]


def _text_of(node) -> str:
    return "".join(node.itertext()).strip()


def _float(node, attr: str, default: float = 0.0) -> float:
    try:
        return float(node.get(attr, default))
    except (TypeError, ValueError):
        return default


def _is_placeholder(value: str) -> bool:
    """값이 비었거나 자리만 채운 문구인지. 말줄임표로 잘린 끝은 값 자체로 인정한다."""
    stripped = value.strip().rstrip("…").strip()
    return not stripped or stripped.casefold() in _PLACEHOLDER_VALUES


def _field_values(root) -> dict[str, list[str]]:
    """data-field별 값 목록. 같은 표식이 여러 번 나오는 항목(feature)도 있다."""
    values: dict[str, list[str]] = {}
    for node in _nodes(root, "text"):
        field = node.get("data-field")
        if field:
            values.setdefault(field, []).append(_text_of(node))
    return values


def _roled_sizes(root) -> dict[str, list[float]]:
    """data-role별 글자 크기 목록."""
    sizes: dict[str, list[float]] = {}
    for node in _nodes(root, "text"):
        role = node.get("data-role")
        if role:
            sizes.setdefault(role, []).append(_float(node, "font-size"))
    return sizes

# ── 1. 대체 텍스트 ──────────────────────────────────────────────


def check_alt_text(root) -> dict:
    """title·desc 존재 + desc가 title과 다른 문장 + desc가 지면 값을 실제로 담았는지.

    존재만 보면 같은 한 줄을 양쪽에 넣어도 통과해 스크린리더 사용자가 얻는 정보가
    늘지 않는다. 지면에 적힌 값 중 최소 2개를 desc가 담도록 요구한다.
    """
    titles = _nodes(root, "title")
    descs = _nodes(root, "desc")
    title = _text_of(titles[0]) if titles else ""
    desc = _text_of(descs[0]) if descs else ""

    if not title or not desc:
        missing = [name for name, text in (("title", title), ("desc", desc)) if not text]
        return item(1, "대체 텍스트", 2, False, f"{', '.join(missing)} 누락 또는 빈 문자열")
    if title == desc:
        return item(1, "대체 텍스트", 2, False,
                    "desc가 title과 같은 문장 — 대체 텍스트로 더해지는 정보가 없음")

    values = _field_values(root)
    real = [v for field, _ in _REQUIRED_FIELDS for v in values.get(field, [])
            if not _is_placeholder(v)]
    covered = [v for v in real if v.rstrip("…").strip() and v.rstrip("…").strip() in desc]
    needed = min(2, len(real))
    passed = len(covered) >= needed
    return item(1, "대체 텍스트", 2, passed,
                f"title·desc 존재, desc가 지면 값 {len(covered)}/{len(real)}개 포함"
                + ("" if passed else f" (최소 {needed}개 필요)"))


# ── 2. 핵심 정보 6항목 ─────────────────────────────────────────


def check_six_fields(root) -> dict:
    """필수 6항목이 data-field 표식을 달고 실재하는지. 충족 개수로 구간 점수(items.banded).

    "정보 없음" 같은 자리 채우기 문구는 충족으로 세지 않는다 — 세면 지면에 아무 사실도
    없는데 만점이 나온다. 지면 한 장이 산출물 전체라 가장 무거운 3점을 준다.
    """
    values = _field_values(root)
    met: list[str] = []
    missing: list[str] = []
    for field, label in _REQUIRED_FIELDS:
        found = [v for v in values.get(field, []) if not _is_placeholder(v)]
        (met if found else missing).append(label)

    detail = f"충족 {len(met)}/{len(_REQUIRED_FIELDS)}"
    if missing:
        detail += f" — 누락: {', '.join(missing)}"
    return item(2, "핵심 정보 6항목", 3, not missing, detail,
                earned=banded(3, len(met), len(_REQUIRED_FIELDS)))


# ── 3. 명도 대비 ────────────────────────────────────────────────


def check_contrast(root) -> dict:
    rects = []
    for node in _nodes(root, "rect"):
        try:
            rects.append((float(node.get("x", "0")), float(node.get("y", "0")),
                          float(node.get("width", "0")), float(node.get("height", "0")),
                          node.get("fill", "")))
        except ValueError:
            continue
    checked, failures = 0, 0
    worst: list[str] = []
    for node in _nodes(root, "text"):
        try:
            x, y = float(node.get("x", "0")), float(node.get("y", "0"))
        except ValueError:
            continue
        backgrounds = [r for r in rects if r[0] <= x <= r[0] + r[2]
                       and r[1] <= y <= r[1] + r[3]]
        if not backgrounds:
            continue
        bg = min(backgrounds, key=lambda r: r[2] * r[3])[4]
        fg_rgb, bg_rgb = parse_color(node.get("fill", "")), parse_color(bg)
        if fg_rgb is None or bg_rgb is None:
            failures += 1
            continue
        checked += 1
        ratio = contrast_ratio(fg_rgb, bg_rgb)
        if ratio < 4.5:
            failures += 1
            if len(worst) < 3:
                worst.append(f"{_text_of(node)[:12]!r} {ratio:.2f}")
    passed = checked > 0 and failures == 0
    detail = f"판정 {checked}건, 실패 {failures}건"
    if worst:
        detail += f" — {', '.join(worst)}"
    return item(3, "명도 대비 4.5:1", 2, passed, detail)


# ── 4. 정보 계층 ────────────────────────────────────────────────


def check_hierarchy(root) -> dict:
    """제목 > 라벨 >= 값 순서가 지켜지는지 + 크기 단계가 3단 이상인지.

    서로 다른 글자 크기 개수만 세면 템플릿이 크기를 고정해 둔 탓에 항상 통과한다.
    역할(data-role) 사이의 크기 관계를 보면 계층이 뒤집히는 회귀를 실제로 잡아낸다.
    """
    sizes = _roled_sizes(root)
    title, label, value = (sizes.get("title", []), sizes.get("label", []),
                           sizes.get("value", []))
    missing = [name for name, got in (("title", title), ("label", label), ("value", value))
               if not got]
    if missing:
        return item(4, "정보 계층", 2, False, f"역할 표식 없는 지면 — 누락: {', '.join(missing)}")

    distinct = {round(s, 1) for s in title + label + value}
    order_ok = min(title) > max(label) and min(label) >= max(value)
    passed = order_ok and len(distinct) >= 3
    detail = (f"제목 {min(title):.0f}px > 라벨 {max(label):.0f}px >= 값 {max(value):.0f}px "
              f"({'준수' if order_ok else '역전'}), 크기 단계 {len(distinct)}단")
    return item(4, "정보 계층", 2, passed, detail)


# ── 5. 잘림 없음 ────────────────────────────────────────────────


def check_truncation(root) -> dict:
    """값이 지면 폭에 맞춰 말줄임표(…)로 잘려 들어간 곳이 없는지.

    잘린 값은 읽는 사람에게 문장이 끊긴 채로 전달된다. 구현 Agent는 폭을 넘는 값을
    자체 검사에서 실패로 올리고 재수행에서 더 짧은 문장을 받는다 — 재수행 상한을 넘겨
    잘린 채로 나온 지면은 여기서 점수를 잃는다.
    """
    cut = [f"{node.get('data-field')}: {_text_of(node)[:14]!r}"
           for node in _nodes(root, "text")
           if node.get("data-field") and _text_of(node).endswith("…")]
    return item(5, "잘림 없음", 2, not cut,
                "잘린 값 없음" if not cut else f"잘린 값 {len(cut)}건 — {', '.join(cut[:3])}")


# ── 6. 지면 밖 넘침 ─────────────────────────────────────────────


def _page_size(root) -> tuple[float, float]:
    return (_float(root, "width", _PAGE_WIDTH) or _PAGE_WIDTH, _float(root, "height", 0.0))


def check_overflow(root) -> dict:
    """글자의 시작점이 지면 밖에 있는지. 지면 한 장이 산출물 전체라 안 보이는 글자는
    빠진 글자와 같다."""
    page_w, page_h = _page_size(root)
    outside = [_text_of(node)[:12] for node in _nodes(root, "text") if _text_of(node)
               and (_float(node, "x") < 0 or _float(node, "x") > page_w
                    or (page_h and _float(node, "y") > page_h))]
    return item(6, "지면 밖 넘침 없음", 2, not outside,
                "지면 밖 글자 0건" if not outside
                else f"지면 밖 글자 {len(outside)}건: {', '.join(outside[:3])}")


# ── 7. 텍스트 실재성 ───────────────────────────────────────────


def check_text_real(root) -> dict:
    """지면 문자열이 text 요소로 있는지 + 래스터 이미지에 묻힌 면적 비율."""
    texts = [node for node in _nodes(root, "text") if _text_of(node)]
    # 지면에 실제로 보이는 그림만 센다. <defs> 안의 그림은 원본을 한 번 실어 둔 것이고,
    # 지면에는 그것을 잘라 쓰는 자리(data-role="art")만큼만 보인다.
    stored = {id(n) for d in _nodes(root, "defs") for n in d.iter()}
    images = [n for n in _nodes(root, "image") if id(n) not in stored]
    images += [n for n in _nodes(root, "svg") if n is not root and n.get("data-role") == "art"]
    page_w, page_h = _page_size(root)
    image_area = sum(_float(n, "width") * _float(n, "height") for n in images)
    ratio = (image_area / (page_w * page_h)) if page_h else 0.0

    reasons = []
    if not texts:
        reasons.append("text 요소 없음")
    if ratio > _MAX_IMAGE_AREA_RATIO:
        reasons.append(f"래스터 면적 비율 {ratio:.1%} > {_MAX_IMAGE_AREA_RATIO:.0%}")
    detail = (f"text {len(texts)}개, 래스터 {len(images)}개(면적 {ratio:.1%})"
              if not reasons else "; ".join(reasons))
    return item(7, "텍스트 실재성", 1, not reasons, detail)


# ── 8. 최소 글자 크기 ──────────────────────────────────────────


def check_min_font(root) -> dict:
    sizes = [_float(node, "font-size") for node in _nodes(root, "text")]
    passed = bool(sizes) and min(sizes) >= _MIN_FONT_PX
    return item(8, "최소 글자 크기", 1, passed,
                f"최솟값 {min(sizes) if sizes else 0}px, 하한 {_MIN_FONT_PX:.0f}px")


ITEM_DEFS: tuple[tuple[int, str, float], ...] = (
    (1, "대체 텍스트", 2), (2, "핵심 정보 6항목", 3), (3, "명도 대비 4.5:1", 2),
    (4, "정보 계층", 2), (5, "잘림 없음", 2), (6, "지면 밖 넘침 없음", 2),
    (7, "텍스트 실재성", 1), (8, "최소 글자 크기", 1),
)


def check_onepage(source: str) -> list[dict]:
    """통과 필수 조건(rules/gates.svg_gates)을 넘긴 SVG만 받는다."""
    root = _parse_svg(source)
    return [check_alt_text(root), check_six_fields(root), check_contrast(root),
            check_hierarchy(root), check_truncation(root), check_overflow(root),
            check_text_real(root), check_min_font(root)]
