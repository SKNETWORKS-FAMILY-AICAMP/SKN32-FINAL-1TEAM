"""이미지 모델이 그린 '아이콘 모음판'을 지면에 끼워 넣는다.

계획서마다 그 내용에 맞는 아이콘을 새로 그린다. 미리 만들어 둔 아이콘(icons.py, 30여 개)에서
고르면 어떤 계획서든 같은 그림이 되풀이된다. 이미지 모델은 대표 도식 한 장과 항목별 아이콘
(기능 · 절차 · 지표 · 기대 효과 등)을 한 번의 호출로 한 장에 그리고, 코드가 칸을 잘라 제자리에 넣는다.

글자는 이미지 모델에 맡기지 않는다. 통짜 이미지로 뽑아 보니 한글 오타가 장당 1~3개 나왔고
("재고 알림" → "채고 알림"), LLM이 그림을 읽어서는 그 오타를 잡지 못했다(뜻이 통하는 쪽으로
고쳐 읽는다). 제목 · 숫자 · 설명은 지금처럼 코드가 <text>로 쓴다. 검증-2의 글자 기반 규칙도 그대로 선다.

흐름
1. 지면 구성(layout)을 보고 아이콘이 필요한 항목을 모은다(icon_items).
2. 회색 칸만 있는 뼈대 PNG를 만들어 이미지 모델에 넘긴다. 모델은 칸마다 아이콘을 채운다.
3. 모델이 칸 위치를 조금씩 다시 나누므로(실측), 흰 여백을 찾아 실제 칸 위치를 읽는다(find_cells).
4. 구역을 그리는 쪽(composer.py · showcase.py)이 icon()으로 칸 하나를 제 자리에 넣는다.

이미지 호출은 tools.image로만 한다(조율이 만든 통로, 2026-10-06):
    tools.image(prompt, *, image: bytes | None, size: str | None, quality: str | None, purpose: str) -> bytes(PNG)
통로가 없거나, 호출이 실패하거나(재시도를 다 쓴 ToolCallExhausted 포함), 칸 수가 맞지 않으면 None을
돌려주고 지면은 기본 아이콘으로 나간다. 이미지 실패를 받아 계속하는 것은 조율이 T-B2에만 허용한 예외다 —
T-B2의 글 호출(tools.llm) 실패는 받지 않고 올려 보낸다(content.py는 예외를 잡지 않는다).
PNG 읽기 · 쓰기는 표준 라이브러리(zlib)만 쓴다.
"""
from __future__ import annotations

import base64
import re
import struct
import zlib

from engineering_agent.infographic import themes

SHEET_W, SHEET_H = 1024, 1536
SIZE, QUALITY = "1024x1536", "medium"
_MARGIN, _GAP = 32, 24
_HERO_H = 380
_COLS, _MAX_ICONS = 4, 20
_GRAY = bytes((196, 196, 196))
_ATTEMPTS = 2

HERO = "hero"
_COLOR_WORD = {"teal": "청록", "orange": "주황", "steel": "파랑", "violet": "보라",
               "green": "초록", "rose": "장미색", "blue": "파랑"}
# 아이콘 설명에서 숫자를 뺀다. 숫자를 넘기면 모델이 아이콘 안에 그 숫자를 그려 넣는다(실측:
# "24개월" → 달력 위 24). 그림 속 숫자는 코드가 확인할 수 없으므로 애초에 주지 않는다.
_NUMBER_RE = re.compile(r"약?\s*\d[\d,.]*\s*(?:%p?|퍼센트|개월|만\s*원|억\s*원|조\s*원|원|곳|건|분|명|개|회|배|일|년|월)?")


def _plain(value) -> str:
    return re.sub(r"\s+", " ", _NUMBER_RE.sub(" ", str(value))).strip(" ·,/")


# ── 1. 아이콘이 필요한 항목 ───────────────────────────────────────


def key(kind: str, name: str = "") -> str:
    """아이콘 칸의 이름. 그리는 쪽과 넣는 쪽이 같은 이름으로 찾는다."""
    return f"{kind}:{str(name).strip()}" if name else kind


def icon_items(category: str, data: dict) -> list[tuple[str, str]]:
    """(칸 이름, 무엇을 그릴지). 지면 구성에 실제로 나오는 항목만, 위에서 아래 순서로."""
    from engineering_agent.infographic.composer import normalize_layout

    layout = [(b["block"], b["variant"]) for b in normalize_layout(category, data)]
    blocks = {block for block, _ in layout}
    items: list[tuple[str, str]] = []

    def add(name: str, what) -> None:
        what = _plain(what)
        if what and name not in {n for n, _ in items}:
            items.append((name, what))

    # journey는 대표 도식 아래에 글만 붙는다(composer._journey). 두 판(split)만 판마다 아이콘을 쓴다.
    if ("problem_solution", "split") in layout and ("hero", "journey") not in layout:
        add(key("story", "problem"), data.get("problem", ""))
        add(key("story", "solution"), data.get("solution", ""))
    details = data.get("feature_details") or []
    for i, feature in enumerate(data.get("features") or []):
        detail = details[i] if i < len(details) else ""
        if isinstance(detail, dict):
            detail = detail.get("detail", "")
        add(key("feature", feature), f"{feature} — {detail}" if str(detail).strip() else feature)
    if "process" in blocks:
        steps = data.get("solution_steps") if category == "원페이지" else data.get("flow_steps")
        for step in steps or []:
            add(key("step", step), step)
    if "metrics" in blocks:
        for metric in data.get("key_metrics") or []:
            if isinstance(metric, dict) and str(metric.get("label", "")).strip():
                add(key("metric", metric["label"]), metric["label"])
    if "effects" in blocks:
        for row in data.get("effects") or []:
            if isinstance(row, dict) and str(row.get("who", "")).strip():
                add(key("effect", row["who"]), f'{row["who"]} — {row.get("what", "")}')
    if "revenue" in blocks or ("metrics", "with_revenue") in layout:
        flow = data.get("revenue_flow") or {}
        add(key("revenue", "payer"), f'돈을 내는 쪽: {flow.get("payer") or data.get("target_users", "")}')
        add(key("revenue", "service"), f'제공하는 서비스: {data.get("item_summary", "")}')
    if "roadmap" in blocks:
        add(key("timeline"), "추진 일정 달력과 깃발")
    return items[:_MAX_ICONS]


# ── 2. 뼈대 ───────────────────────────────────────────────────────


def wire_cells(names: list[str]) -> dict[str, tuple[int, int, int, int]]:
    """뼈대의 칸 자리. 맨 위 넓은 칸(대표 도식) + 네 줄 세로 격자(아이콘)."""
    inner = SHEET_W - 2 * _MARGIN
    cells = {names[0]: (_MARGIN, _MARGIN, inner, _HERO_H)}
    rest = names[1:]
    rows = max(1, -(-len(rest) // _COLS))
    top = _MARGIN + _HERO_H + _GAP
    col_w = (inner - _GAP * (_COLS - 1)) // _COLS
    row_h = min(col_w, (SHEET_H - _MARGIN - top - _GAP * (rows - 1)) // rows)
    for n, name in enumerate(rest):
        cells[name] = (_MARGIN + (n % _COLS) * (col_w + _GAP), top + (n // _COLS) * (row_h + _GAP), col_w, row_h)
    return cells


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def wire_png(cells: dict[str, tuple[int, int, int, int]], marks: tuple = ()) -> bytes:
    """흰 바탕에 회색 칸만 있는 PNG. marks: 그 위에 덧칠할 (x, y, w, h, (r, g, b)) 목록."""
    white = b"\xff" * (3 * SHEET_W)
    boxes = [(*box, _GRAY) for box in cells.values()] + [(*m[:4], bytes(m[4])) for m in marks]
    rows = []
    for y in range(SHEET_H):
        row = bytearray(white)
        for cx, cy, cw, ch, color in boxes:
            if cy <= y < cy + ch:
                row[3 * cx:3 * (cx + cw)] = color * cw
        rows.append(b"\x00" + bytes(row))
    header = struct.pack(">IIBBBBB", SHEET_W, SHEET_H, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(b"".join(rows), 6)) + _chunk(b"IEND", b""))


def hero_kind(category: str, data: dict) -> tuple[str, str]:
    """맨 위 대표 그림의 구도와 그 근거. 모든 지면에 "세 칸 + 화살표"를 그렸더니 계획서가 달라도
    첫인상이 같았다(실측: 예시 계획서 셋 모두 같은 가로 세 칸). 구도는 아이템 이름이 아니라 계획서에서
    뽑은 재료가 보여 주는 **관계**로 고른다 — 같은 계획서면 같은 구도, 관계가 다르면 다른 구도.

    그림 아래에 글이 세 구역으로 붙는 지면(AI API 처리 단계, 대표 도식 journey)은 세 구역을 지킨다
    (composer._pipeline_captions · _journey가 그림을 3등분한 자리에 글을 놓는다).
      steps    입력 → 처리 → 출력처럼 끊긴 단계: AI API 처리 단계, 또는 단계 재료가 있는데 단계 구역이 없을 때
      panorama 문제 상황 → 서비스 사용 → 결과로 이어지는 이야기(journey)
      hub      돈을 내는 쪽 · 효과를 보는 대상 등 서로 다른 주체가 셋 이상 얽힌 사업
      scene    그 밖 — 서비스를 쓰는 대표 장면 하나
    """
    from engineering_agent.infographic.composer import normalize_layout

    layout = {(b["block"], b["variant"]) for b in normalize_layout(category, data)}
    if category == "AI_API":
        return "steps", "AI API 처리 단계(입력 → 처리 → 출력)를 그림 아래에 붙인다"
    if ("hero", "journey") in layout:
        return "panorama", "문제 → 해결 → 효과 이야기를 그림 아래에 붙인다"
    design = data.get("_design") if isinstance(data.get("_design"), dict) else {}
    if design.get("hero") in ("hub", "scene"):  # 디자인 사양(design.py)이 지면 구성과 같은 관계로 골랐다
        return design["hero"], f"디자인 사양: 관계 '{design.get('relation', '')}'"
    flow = data.get("revenue_flow") if isinstance(data.get("revenue_flow"), dict) else {}
    parties = {_plain(row.get("who", "")) for row in data.get("effects") or [] if isinstance(row, dict)}
    parties |= {_plain(flow.get("payer", "")), _plain(data.get("target_users", ""))}
    parties.discard("")
    if len(parties) >= 3:
        return "hub", f"주체 {len(parties)}곳이 얽힌다({', '.join(sorted(parties))})"
    steps = data.get("solution_steps") if category == "원페이지" else data.get("flow_steps")
    if len([s for s in steps or [] if str(s).strip()]) >= 3 and not any(b == "process" for b, _ in layout):
        return "steps", "단계 재료가 있는데 단계 구역이 지면에 없다"
    return "scene", "단계 · 여러 주체 관계가 두드러지지 않는다"


def _style_lines(data: dict, color: str) -> str:
    """그림체. 모든 사업에 같은 두 톤 선 아이콘을 쓰면 그림 표현이 같아 보인다. 디자인 사양(design.py)이
    소비자 대상 분야는 평면 일러스트, 기업 · 산업 · 데이터 분야는 정밀한 선 아이콘으로 고른다.
    칸 배치 · 흰 여백(find_cells가 칸을 읽는 근거)은 그림체와 상관없이 그대로다."""
    design = data.get("_design") if isinstance(data.get("_design"), dict) else {}
    if design.get("art_style") == "평면":
        return (f"- 친근한 평면 일러스트. 굵은 외곽선 없이 옅은 {color}부터 진한 {color}까지 서너 단계의 면으로 형태를 "
                "나누고, 둥근 모서리의 단순한 모양으로 그린다.\n"
                "- 사람 · 동물 · 물건의 특징이 한눈에 보이게 하되 세부는 줄인다.\n")
    return (f"- 고급 컨설팅 보고서 인포그래픽에 쓰는 정교한 선 아이콘. 진한 {color} 선에 옅은 {color} 채움을 곁들인 두 톤.\n"
            "- 선 굵기를 통일하고, 대상의 특징이 한눈에 보이게 세부를 넣는다.\n")


def _hero_instruction(data: dict, story: str, color: str, category: str) -> str:
    summary = _plain(data.get("item_summary", ""))
    kind, _ = hero_kind(category, data)
    if kind == "steps":
        return (f"{summary}의 흐름을 보여 주는 가로 도식. 작은 칸과 같은 그림체로, "
                f"왼쪽에서 오른쪽으로 {story}를 화살표로 잇는다.")
    if kind == "panorama":
        return (f"{summary}의 흐름을 끊김 없는 한 장의 가로 파노라마로 그린다. 작은 칸과 같은 그림체로, "
                f"왼쪽 3분의 1 · 가운데 3분의 1 · 오른쪽 3분의 1에 차례로 {story}를 놓고, 칸을 나누거나 "
                "화살표를 쓰지 않고 길 · 바닥 · 배경이 자연스럽게 이어지게 한다.")
    if kind == "hub":
        return (f"{summary}의 구조를 허브 도식으로 그린다. 작은 칸과 같은 그림체로, 가운데에 서비스(화면 · 기기)를 "
                "크게 두고 둘레에 이용자 · 돈을 내는 쪽 · 효과를 보는 대상을 작은 그림으로 배치해 가는 선으로 잇는다.")
    return (f"{summary}을(를) 실제로 쓰는 대표 장면 하나를 넓게 그린다. 작은 칸과 같은 그림체로, "
            "이용하는 사람과 장소 · 도구가 한눈에 보이게 하고, 화살표나 단계 나눔은 쓰지 않는다.")


def sheet_prompt(data: dict, items: list[tuple[str, str]], color: str, category: str = "") -> str:
    problem, outcome = _plain(data.get("problem", "")), _plain(data.get("outcome", ""))
    story = " → ".join(filter(None, (f"'{problem}' 상황" if problem else "", "이 서비스를 쓰는 장면",
                                     f"'{outcome}' 결과" if outcome else "좋아진 결과")))
    pipeline = data.get("pipeline") or {}
    if category == "AI_API" and all(_plain(pipeline.get(k, "")) for k in ("input", "process", "output")):
        # AI API 지면은 대표 도식이 곧 처리 단계 도식이다(composer._pipeline_captions가 아래에 글을 붙인다).
        story = (f"'{_plain(pipeline['input'])}' 입력 → AI가 '{_plain(pipeline['process'])}' 처리 → "
                 f"'{_plain(pipeline['output'])}' 출력")
    hero = _hero_instruction(data, story, color, category)
    return (
        "이 그림은 아이콘 모음판의 뼈대다. 흰 바탕 위에 회색 칸이 있다. 맨 위 넓은 칸 하나와 그 아래 작은 칸 "
        f"{len(items)}개다.\n\n"
        "지킬 것\n"
        "- 칸의 개수와 배치를 그대로 지킨다. 칸 사이와 가장자리는 흰색으로 둔다.\n"
        f"- 칸마다 아주 옅은 {color} 바탕의 둥근 타일로 바꾸고, 작은 칸은 타일 가운데에 아이콘 하나를 크게 그린다.\n"
        "- 글자, 숫자, 글자 비슷한 무늬를 어디에도 넣지 않는다. 문서 · 화면 · 달력 · 동전 안에도 숫자나 글자를 쓰지 않고 "
        "줄이나 점으로만 나타낸다.\n\n"
        "그림체 (모든 칸 통일)\n"
        + _style_lines(data, color) +
        "- 사진 같은 음영 · 그림자 · 다른 색은 쓰지 않는다. 그림이 타일 밖 흰 여백으로 넘어가지 않게 한다.\n\n"
        f"맨 위 넓은 칸: {hero}\n\n"
        "작은 칸에 그릴 아이콘 (왼쪽 위부터 오른쪽으로, 줄마다)\n"
        + "\n".join(f"- {n + 1}번 칸: {what}" for n, (_, what) in enumerate(items)))


# ── 3. 칸 찾기 ────────────────────────────────────────────────────

_WHITE = 244      # 이보다 밝으면 흰색. 옅은 타일(가장 어두운 채널 230~240)이 여백으로 읽히지 않게 한다.
_GUTTER = 0.985   # 한 줄에서 흰 픽셀이 이 비율 이상이면 여백
_MIN_CELL = 60    # 이보다 얇은 띠는 칸이 아니다


def _darkest_rows(png: bytes) -> tuple[int, list[bytes]]:
    """(폭, 줄마다 픽셀의 R · G · B 중 가장 어두운 값). 8비트 RGB · RGBA, 인터레이스 없는 PNG만."""
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("PNG가 아님")
    pos, idat, width, height, bpp = 8, [], 0, 0, 3
    while pos < len(png):
        length, kind = struct.unpack(">I4s", png[pos:pos + 8])
        body = png[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or color not in (2, 6) or interlace:
                raise ValueError("지원하지 않는 PNG 형식")
            bpp = 3 if color == 2 else 4
        elif kind == b"IDAT":
            idat.append(body)
        pos += 12 + length
    data = zlib.decompress(b"".join(idat))
    stride = width * bpp
    rows: list[bytes] = []
    prev = bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        ftype, line = data[start], bytearray(data[start + 1:start + 1 + stride])
        if ftype == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif ftype == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif ftype == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
        rows.append(bytes(min(t) for t in zip(line[0::bpp], line[1::bpp], line[2::bpp])))
    return width, rows


def _bands(gutter: list[bool]) -> list[tuple[int, int]]:
    out, start = [], None
    for i, is_gutter in enumerate(gutter + [True]):
        if not is_gutter and start is None:
            start = i
        elif is_gutter and start is not None:
            if i - start >= _MIN_CELL:
                out.append((start, i))
            start = None
    return out


_INK = 150          # 이보다 어두우면 아이콘의 선
_BLANK_RATIO = 0.004  # 칸 안쪽에서 선이 차지하는 비율이 이보다 작으면 빈 타일


def is_blank(rows: list[bytes], cell: tuple[int, int, int, int]) -> bool:
    """아이콘이 그려지지 않은 빈 타일인지. 모델이 가끔 칸 하나를 타일만 칠하고 비워 둔다(실측)."""
    x, y, w, h = cell
    inner = [row[x + w // 6:x + w - w // 6] for row in rows[y + h // 6:y + h - h // 6]]
    area = sum(len(row) for row in inner)
    return not area or sum(sum(v < _INK for v in row) for row in inner) < area * _BLANK_RATIO


def find_cells(png: bytes) -> list[tuple[int, int, int, int]]:
    """칸의 (x, y, w, h)를 위 → 아래, 왼 → 오른 순서로."""
    return _scan(png)[0]


def _scan(png: bytes) -> tuple[list[tuple[int, int, int, int]], list[bytes]]:
    width, rows = _darkest_rows(png)
    white_rows = [sum(v > _WHITE for v in row) >= width * _GUTTER for row in rows]
    cells = []
    for top, bottom in _bands(white_rows):
        band = rows[top:bottom]
        white_cols = [sum(row[x] > _WHITE for row in band) >= len(band) * _GUTTER for x in range(width)]
        for left, right in _bands(white_cols):
            cells.append((left, top, right - left, bottom - top))
    return cells, rows


# ── 전체 ──────────────────────────────────────────────────────────


def generate(category: str, data: dict, tools) -> dict | None:
    """아이콘 모음판을 만든다. 만들 수 없으면 None(지면은 기본 아이콘으로 나간다)."""
    if not callable(getattr(tools, "image", None)):
        return None
    try:
        items = icon_items(category, data)
        if not items:
            return None
        names = [HERO] + [name for name, _ in items]
        prompt = sheet_prompt(data, items, _COLOR_WORD.get(themes.pick(data), "초록"), category)
        wire = wire_png(wire_cells(names))
        for _ in range(_ATTEMPTS):
            png = tools.image(prompt, image=wire, size=SIZE, quality=QUALITY, purpose="인포그래픽 아이콘")
            cells, rows = _scan(png)
            if len(cells) == len(names):
                # 빈 타일은 싣지 않는다 — 그 자리는 기본 아이콘으로 나간다.
                found = {name: cell for name, cell in zip(names, cells) if not is_blank(rows, cell)}
                return {"png": base64.b64encode(png).decode("ascii"), "cells": found}
    except Exception:  # noqa: BLE001 — 그림은 선택 재료다. 실패해도 지면은 나가야 한다.
        return None
    return None


# ── 4. 지면에 넣기 ────────────────────────────────────────────────


def defs(data: dict) -> str:
    art = data.get("_art")
    if not art:
        return ""
    return (f'<defs><image id="art-sheet" width="{SHEET_W}" height="{SHEET_H}" '
            f'href="data:image/png;base64,{art["png"]}"/></defs>')


def has(data: dict, name: str) -> bool:
    return bool(data.get("_art")) and name in data["_art"]["cells"]


def slot(data: dict, name: str, x: float, y: float, w: float, h: float, radius: float = 10,
         inset: int = 6) -> str:
    """모음판의 칸 하나를 (x, y, w, h) 자리에 꽉 채워 넣는다. 그림이 없으면 빈 문자열.
    inset: 칸 가장자리(둥근 모서리 · 번짐)를 피해 안쪽에서 자르는 폭."""
    if not has(data, name):
        return ""
    cx, cy, cw, ch = data["_art"]["cells"][name]
    cx, cy, cw, ch = cx + inset, cy + inset, cw - 2 * inset, ch - 2 * inset
    clip = "art-" + f"{zlib.crc32(name.encode('utf-8')):08x}-{int(x)}-{int(y)}"
    return (f'<clipPath id="{clip}"><rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'rx="{radius:.1f}"/></clipPath>'
            f'<g clip-path="url(#{clip})"><svg data-role="art" aria-hidden="true" x="{x:.1f}" y="{y:.1f}" '
            f'width="{w:.1f}" height="{h:.1f}" viewBox="{cx} {cy} {cw} {ch}" '
            f'preserveAspectRatio="xMidYMid slice"><use href="#art-sheet"/></svg></g>')


def icon(data: dict, name: str, cx: float, cy: float, size: float) -> str:
    """맞춤 아이콘을 (cx, cy) 가운데에 지름 size의 원으로. 없으면 빈 문자열(기본 아이콘을 쓴다)."""
    return slot(data, name, cx - size / 2, cy - size / 2, size, size, radius=size / 2, inset=14)
