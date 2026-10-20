"""지시문 공용 부품 — Orchestrator 규칙(재량 없음). 작업 분해(T-C3, 조율)와 재작성 · 재수행 지시문 경로(흐름)가 함께 쓴다.

지시 대상(instruction 입력을 가진 Task)의 지시문은 두 부분을 이 순서로 잇는다.

    [작업 틀]                ← 틀: 코드가 쓰는 고정 문구 (역할 · 기준 문서 규칙)
    <틀>

    [작업 안내]              ← 안내: 조율 LLM이 이 아이템 · 공고에 맞춰 쓴 글 (TaskInstruction.guidance와 같은 글자)
    <안내>

- 첨부 문서 추출(R-8)이 흐름에서 빠져 참조 자료 부분은 없다.
- 부분은 머리말 경계로 나눈다(문자열 일치가 아님). 틀은 코드 문구라 머리말이 없고, 안내는 정리(sanitize_guidance)를 거쳐
  머리말을 흉내 내지 못한다. 그래서 앞에서부터 찾은 첫 안내 머리말이 진짜 경계다.
- 재작성 · 재수행 때는 저장된 지시문에서 안내 부분만 바꾸고(replace_guidance — 틀 부분의 바이트는 그대로),
  문제 내용 원문을 Agent 연동 규격 형식 그대로 끝에 덧붙인다(append_problems).
- 머리말 표기는 잠정이다.
- 예외 메시지에 지시문 · 안내 내용을 넣지 않는다.
"""
from __future__ import annotations

from typing import NamedTuple

from ..models import ReworkInput, ReworkOrder

# 부분 머리말 (잠정)
FRAME_HEADER = "[작업 틀]"
GUIDANCE_HEADER = "[작업 안내]"
PART_HEADERS: tuple[str, ...] = (FRAME_HEADER, GUIDANCE_HEADER)
# 문제 내용 덧붙임 머리말 — Agent 연동 규격에 적힌 형식
REWORK_ORDER_MARK = "[재작성]"
ISSUES_MARK = "[{mode} — 문제가 된 내용]"

_PART_SEP = "\n\n"
_FRAME_START = f"{FRAME_HEADER}\n"
_GUIDANCE_START = f"{_PART_SEP}{GUIDANCE_HEADER}\n"

# 안내가 흉내 내면 안 되는 표기 → 같은 길이의 바꾼 표기. 지시문 부분 머리말과 덧붙임 머리말
_GUIDANCE_MARKERS: tuple[tuple[str, str], ...] = tuple(
    (m, "(" + m[1:-1] + ")") for m in (
        *PART_HEADERS, REWORK_ORDER_MARK, ISSUES_MARK.format(mode="재수행"), ISSUES_MARK.format(mode="재작성"),
    ))


class InstructionParts(NamedTuple):
    frame: str
    guidance: str


# ── 격리 ─────────────────────────────────────────────
def neutralize(tag: str, text: str) -> str:
    """데이터 안의 닫는 태그 흉내(</tag>)를 [/tag]로 바꾼다 — 데이터가 격리 표기를 닫지 못하게."""
    return text.replace(f"</{tag}>", f"[/{tag}]")


def isolate(tag: str, text: str) -> str:
    """표시 태그로 감싼 데이터 — <tag>\\n본문\\n</tag>. 본문의 닫는 태그 흉내는 바꿔 싣는다."""
    return f"<{tag}>\n{neutralize(tag, text)}\n</{tag}>"


# ── 안내 정리 ──────────────────────────────────────────
def sanitize_guidance(text: str) -> str:
    """앞뒤 공백을 지우고, 지시문 부분 머리말 · 덧붙임 머리말과 같은 글자를 같은 길이의 다른 표기로
    바꾼다. 여러 번 해도 결과가 같다."""
    out = text.strip()
    for marker, replacement in _GUIDANCE_MARKERS:
        out = out.replace(marker, replacement)
    return out


# ── 두 부분 ────────────────────────────────────────────
def compose_instruction(frame: str, guidance: str) -> str:
    """틀 · 안내를 잇는다. 안내는 정리해서 싣는다."""
    return f"{_FRAME_START}{frame}{_GUIDANCE_START}{sanitize_guidance(guidance)}"


def split_instruction(text: str) -> InstructionParts:
    """'[작업 틀]\\n' 시작과 첫 '\\n\\n[작업 안내]\\n'으로 두 부분을 나눈다. 지시 대상의 지시문 모양이 아니면
    ValueError(내용 없이)."""
    g = text.find(_GUIDANCE_START)
    if not text.startswith(_FRAME_START) or g < 0:
        raise ValueError("지시문 부분 머리말 없음")
    return InstructionParts(text[len(_FRAME_START):g], text[g + len(_GUIDANCE_START):])


def extract_frame(text: str) -> str:
    """저장된 지시문의 틀 부분 — 흐름이 다시 쓰기 함수에 틀 문구를 넘길 때 쓴다 (흐름은 agents/를 import하지 않는다)."""
    return split_instruction(text).frame


def extract_guidance(text: str) -> str:
    return split_instruction(text).guidance


def replace_guidance(text: str, new_guidance: str) -> str:
    """저장된 지시문에서 안내 부분만 새 안내(정리해서)로 바꾼다 — 틀 부분은 한 글자도 바꾸지 않는다."""
    parts = split_instruction(text)
    start = len(_FRAME_START) + len(parts.frame) + len(_GUIDANCE_START)
    return text[:start] + sanitize_guidance(new_guidance)


# ── 문제 내용 덧붙임 ─────────────────────────
def order_block(order: ReworkOrder) -> str:
    """재작성 지시 — '\\n\\n[재작성] {reason}', 보완 지시가 비어 있지 않고 사유와 다르면 '\\n{instructionDelta}'."""
    delta = order.instruction_delta
    return f"{_PART_SEP}{REWORK_ORDER_MARK} {order.reason}" + (f"\n{delta}" if delta and delta != order.reason else "")


def issues_block(mode: str, issues: list[str]) -> str:
    """문제 내용 목록 — '\\n\\n[{mode} — 문제가 된 내용]\\n- ' 뒤에 issues를 '\\n- '로 잇는다.
    mode '재수행'은 재수행 문제, '재작성'은 화면 9 계획서 재작성 반영 실행(T-B1)의 반영 블록이다."""
    return f"{_PART_SEP}{ISSUES_MARK.format(mode=mode)}\n- " + "\n- ".join(issues)


def problem_appendix(rework_input: ReworkInput | None, *, cycle_order: ReworkOrder | None = None,
                     reflect_issues: list[str] | None = None) -> str:
    """지시문 끝에 붙일 문제 내용 원문.

    - 입력 없음(첫 실행): 없음
    - 재작성 대상(order 있음): 재작성 블록
    - 재작성 사이클 안의 재수행(cycle_order — 그 사이클의 그 Task 재작성 지시, 5.4): 재작성 블록 → 재수행 블록
    - 반영 실행 중 재수행(reflect_issues — 반영 실행 때의 issues): 반영 블록 → 재수행 블록
    - 그 밖(검사 불통과 재수행 · 반영 실행): 입력의 mode 블록
    어느 경우를 쓸지는 부르는 쪽(흐름)이 정한다.
    """
    if rework_input is None:
        return ""
    if rework_input.order is not None:
        return order_block(rework_input.order)
    blocks = ""
    if rework_input.mode == "재수행" and cycle_order is not None:
        blocks = order_block(cycle_order)
    elif rework_input.mode == "재수행" and reflect_issues:
        blocks = issues_block("재작성", reflect_issues)
    return blocks + issues_block(rework_input.mode, rework_input.issues)


def append_problems(base: str, rework_input: ReworkInput | None, *, cycle_order: ReworkOrder | None = None,
                    reflect_issues: list[str] | None = None) -> str:
    """지시문 + 문제 내용 원문 (problem_appendix). cycle_order · reflect_issues가 없으면 지금 덧붙이기
    (sbrain_flow.default_instruction_builder)와 같은 글자다."""
    return base + problem_appendix(rework_input, cycle_order=cycle_order, reflect_issues=reflect_issues)
