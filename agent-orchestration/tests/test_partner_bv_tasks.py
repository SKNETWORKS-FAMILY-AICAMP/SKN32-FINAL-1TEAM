"""구현 · 검증-2 실구현 Task 함수 — T-B1 · T-B2 · T-V2를 지금 계약(FileRef · tools.files)으로 직접 부른다 (impl-verify2
spec 4.2 · 4.3 · 4.4, 7절 3 ~ 5번). 가짜 호출처 · 가짜 이미지 · 메모리 파일 저장소만 쓴다(네트워크 · 디스크 없음).
흐름에 끼운 시험은 test_partner_bv_flow.py.
"""
from __future__ import annotations

import builtins
import io
import json
import os
import pathlib
from contextlib import contextmanager

import pytest
from bv_fake import CONTENT, ELEMENTS, HTML, MARK, VARIANTS, BvProvider, EchoImage, bv_tools
from conftest import TIMING

from sbrain.agents.partner_bv.engineering_agent import html_kit
from sbrain.agents.partner_bv.engineering_agent.infographic import artsheet, fonts, illustrations
from sbrain.agents.partner_bv.tasks import IMAGE_TASKS, IMPLEMENTED, IMPLEMENTED_TASKS, bind_partner_bv
from sbrain.agents.partner_bv.verification_agent import llm_judge
from sbrain.agents.partner_bv.verification_agent.tasks import plan_text_of
from sbrain.contracts import tasks as c
from sbrain.flow.catalog import build_registry
from sbrain.models import FileRef, Infographic, ItemSpec, PlanDoc, PlanSection, Prototype, ReworkInput, Sentence
from sbrain.orchestrator.errors import FileRejected, ToolCallExhausted

FEATURES = ["회원 등록·조회", "수업 예약"]
INSTRUCTION = "T-B 지시문"


def item(category: str = "웹개발") -> ItemSpec:
    return ItemSpec(item_name="헬스온", one_line_summary="헬스장 회원 관리", target_customer="헬스장",
                    core_features=FEATURES, category=category, keywords=["헬스장"])


def plan(features: list[str] = FEATURES, lines: list[str] | None = None) -> PlanDoc:
    texts = lines if lines is not None else [
        f"{FEATURES[0]}: 회원 정보를 입력하면 목록에 보여 준다.", f"{FEATURES[1]}: 수업을 고르면 예약을 확인한다."]
    sentences = [Sentence(sentence_id=f"s{i}", text=t, is_title=False, paragraph_no=i) for i, t in enumerate(texts, 1)]
    return PlanDoc(sections=[PlanSection(section_code="1-1", title="서비스 개요", sentences=sentences)],
                   feature_list=list(features), charts=[], tables=[], protected_tokens=[])


def tb1_in(rework: ReworkInput | None = None, category: str = "웹개발") -> c.TB1In:
    return c.TB1In(feature_list=FEATURES, item_spec=item(category), category=category, instruction=INSTRUCTION,
                   rework_input=rework, plan_doc=plan())


def tb2_in(category: str = "웹개발", features: list[str] = FEATURES) -> c.TB2In:
    return c.TB2In(plan_doc=plan(features), item_spec=item(category), category=category, instruction=INSTRUCTION)


def read(store, ref: FileRef) -> str:
    return store.read(ref.key).decode("utf-8")


def file_calls(sink, purpose: str | None = None) -> list:
    return [log for log in sink.drain() if log.call_type == "file" and (purpose is None or log.purpose == purpose)]


@contextmanager
def no_disk(monkeypatch):
    """블록 안에서 파일을 열거나 보거나 쓰거나 폴더를 만들면 AssertionError (test_partner_bv_vendored와 같은 방식)."""
    def boom(*a, **k):
        raise AssertionError("실행 중 디스크 접근")
    with monkeypatch.context() as m:
        for target, name in ((builtins, "open"), (io, "open"), (os, "open"), (os, "mkdir"), (os, "makedirs"),
                             (pathlib.Path, "open"), (pathlib.Path, "read_text"), (pathlib.Path, "read_bytes"),
                             (pathlib.Path, "write_text"), (pathlib.Path, "write_bytes"), (pathlib.Path, "mkdir"),
                             (pathlib.Path, "exists"), (pathlib.Path, "stat"), (pathlib.Path, "is_file")):
            m.setattr(target, name, boom)
        yield


# ── 등록 ──────────────────────────────────────────────────
def test_registration_shape_matches_partner_sw():
    assert IMPLEMENTED_TASKS == {"T-B1", "T-B2", "T-V2"} and IMAGE_TASKS == {"T-B2"}
    registry = build_registry()
    bind_partner_bv(registry)
    assert all(registry.get(t).fn is fn for t, fn in IMPLEMENTED.items())
    assert {fn.__module__ for fn in IMPLEMENTED.values()} == {
        "sbrain.agents.partner_bv.engineering_agent.tasks", "sbrain.agents.partner_bv.verification_agent.tasks"}


# ── T-B1 ──────────────────────────────────────────────────
def test_tb1_pass_puts_decorated_index_html():
    p = BvProvider()
    tools, sink, store = bv_tools(p, "T-B1")
    out = IMPLEMENTED["T-B1"](tb1_in(), tools)
    assert out.check.passed and out.check.failures == []
    ref = out.entry_file
    assert ref is not None and (ref.name, ref.media_type) == ("index.html", "text/html")
    assert out.prototype.entry_file == ref and out.prototype.kind == "html"
    assert out.prototype.asset_files == [] and out.prototype.readme_file is None
    html = read(store, ref)
    assert 'data-kit="font"' in html and 'data-kit="icons"' in html and MARK in html     # 끼워 넣었다
    assert out.implemented_features == out.prototype.implemented_features == FEATURES   # 머리 주석에서
    [req] = p.requests
    assert req.metadata["purpose"] == "T-B1 HTML 생성"
    assert [log.purpose for log in file_calls(sink)] == ["put"]


@pytest.mark.parametrize("variant,code", [("dependency", "E-B1-DEP"), ("halting", "E-B1-SANDBOX"),
                                          ("ignored", "E-B1-SANDBOX"), ("secret", "E-B1-SECRET")])
def test_tb1_gate_failure_still_puts_decorated_entry(variant, code):
    tools, _, store = bv_tools(BvProvider(html=VARIANTS[variant]), "T-B1")
    out = IMPLEMENTED["T-B1"](tb1_in(), tools)
    assert not out.check.passed and len(out.check.failures) == 1
    assert out.check.failures[0].startswith(f"{code} 게이트 실패")                     # 담당자 요약 문구
    assert out.entry_file is not None and out.entry_file.name == "index.html"
    assert out.prototype.entry_file == out.entry_file
    html = read(store, out.entry_file)
    assert 'data-kit="font"' in html and 'data-kit="icons"' in html                    # 통과 때와 똑같이 끼워 넣었다
    assert html_kit.strip(html).count(MARK) == 1
    assert out.implemented_features == FEATURES                                        # 통과 때와 같은 방식으로 뽑음


def test_tb1_entry_failure_has_no_entry_file():
    reply = f"```html:main.html\n{HTML}\n```"
    p = BvProvider()
    p.scripts["T-B1 HTML 생성"] = [reply]
    tools, sink, store = bv_tools(p, "T-B1")
    out = IMPLEMENTED["T-B1"](tb1_in(), tools)
    assert not out.check.passed and out.check.failures[0].startswith("E-B1-ENTRY 게이트 실패")
    assert out.entry_file is None and out.prototype.entry_file is None
    assert out.implemented_features == [] and file_calls(sink) == []


def test_tb1_rework_reads_previous_source_and_sends_it_without_embedded_kit():
    p = BvProvider()
    tools, sink, store = bv_tools(p, "T-B1")
    previous = html_kit.decorate(HTML.replace("<h1>헬스온</h1>", "<h1>헬스온</h1><p>이전판표시</p>"))
    ref = tools.files.put("index.html", previous.encode("utf-8"), "text/html")
    rework = ReworkInput(mode="재수행", previous_result_ref="prototype@1", issues=["문제"], is_final_attempt=False,
                         previous_source_file=ref)
    IMPLEMENTED["T-B1"](tb1_in(rework), tools)
    [req] = p.requests
    user = req.messages[-1]["content"]
    assert "<이전HTML>" in user and "이전판표시" in user
    assert "data:font/woff2" not in user and 'data-kit="icons"' not in user          # 끼워 넣은 것은 뺐다
    assert [log.purpose for log in file_calls(sink)] == ["put", "get", "put"]


def test_tb1_without_previous_reference_sends_instruction_only():
    p = BvProvider()
    tools, _, _ = bv_tools(p, "T-B1")
    rework = ReworkInput(mode="재수행", previous_result_ref="prototype@1", issues=["문제"], is_final_attempt=False)
    IMPLEMENTED["T-B1"](tb1_in(rework), tools)
    assert p.requests[0].messages[-1]["content"] == INSTRUCTION


def test_tb1_file_failures_are_not_caught():
    tools, _, _ = bv_tools(BvProvider(), "T-B1")
    missing = FileRef(key="run-1/e/u/index.html", name="index.html", media_type="text/html", size=1, sha256="0" * 64)
    other = FileRef(key="run-2/e/u/index.html", name="index.html", media_type="text/html", size=1, sha256="0" * 64)
    for ref, error in ((missing, ToolCallExhausted), (other, FileRejected)):
        rework = ReworkInput(mode="재작성", previous_result_ref="prototype@1", issues=[], is_final_attempt=False,
                             previous_source_file=ref)
        with pytest.raises(error):
            IMPLEMENTED["T-B1"](tb1_in(rework), tools)


def test_tb1_empty_response_is_format_error_then_exhausted():
    p = BvProvider()
    p.scripts["T-B1 HTML 생성"] = ["", "코드블록 없음"]
    tools, sink, _ = bv_tools(p, "T-B1", retry=1)
    with pytest.raises(ToolCallExhausted):
        IMPLEMENTED["T-B1"](tb1_in(), tools)
    [log] = sink.drain()
    assert [t.outcome for t in log.tries] == ["형식오류", "형식오류"]
    assert all(MARK not in (t.detail or "") for t in log.tries)


# ── T-B2 ──────────────────────────────────────────────────
@pytest.mark.parametrize("category,name", [("웹개발", "infographic.svg"), ("AI_API", "infographic.svg"),
                                           ("원페이지", "onepage.svg")])
def test_tb2_puts_svg_for_every_category(category, name):
    image = EchoImage()
    tools, sink, store = bv_tools(BvProvider(), "T-B2", image=image)
    out = IMPLEMENTED["T-B2"](tb2_in(category), tools)
    info = out.infographic
    assert (info.format, info.image_file.name, info.image_file.media_type) == ("svg", name, "image/svg+xml")
    svg = read(store, info.image_file)
    assert svg.lstrip().startswith("<svg") and info.alt_text and info.alt_text in svg
    assert info.icon_fallback is False                                                # 맞춤 아이콘판을 썼다
    [img] = image.requests
    assert (img.metadata["purpose"], img.size, img.quality) == ("인포그래픽 아이콘", "1024x1536", "medium")
    assert img.image and img.image.startswith(b"\x89PNG")                            # 회색 칸 뼈대 그림


def test_tb2_failed_self_check_still_puts_file():
    content = dict(CONTENT, flow_steps=[f"회원 등록 99건 {MARK}", "수업 고르기"])     # 계획서에 없는 수치
    tools, _, store = bv_tools(BvProvider(content=content), "T-B2", image=EchoImage())
    out = IMPLEMENTED["T-B2"](tb2_in("웹개발"), tools)
    assert not out.check.passed and any("계획서에 없는 수치" in f for f in out.check.failures)
    assert read(store, out.infographic.image_file).lstrip().startswith("<svg")


@pytest.mark.parametrize("outcome", ["tiny", "garbage", "timeout"])
def test_tb2_custom_icons_unusable_means_default_icons(outcome):
    """칸 수 불일치(두 번 그려도) · 그림 해석 오류 · 이미지 호출 재시도 소진 → 기본 아이콘, iconFallback 참. 실패하지 않는다."""
    image = EchoImage(default=outcome)
    tools, sink, store = bv_tools(BvProvider(), "T-B2", image=image)
    out = IMPLEMENTED["T-B2"](tb2_in("웹개발"), tools)
    assert out.infographic.icon_fallback is True
    assert read(store, out.infographic.image_file).lstrip().startswith("<svg")
    images = [log for log in sink.drain() if log.call_type == "image"]
    if outcome == "timeout":
        assert [log.final_outcome for log in images] == ["소진"]
    else:
        assert len(images) == (2 if outcome == "tiny" else 1) and {log.final_outcome for log in images} == {"성공"}


def test_tb2_no_icon_items_means_no_fallback_and_no_image_call(monkeypatch):
    monkeypatch.setattr(artsheet, "icon_items", lambda category, data: [])
    image = EchoImage(default="timeout")
    tools, _, _ = bv_tools(BvProvider(), "T-B2", image=image)
    out = IMPLEMENTED["T-B2"](tb2_in("웹개발"), tools)
    assert out.infographic.icon_fallback is False and image.requests == []


def test_tb2_text_call_failure_is_raised():
    p = BvProvider()
    p.scripts["T-B2 인포그래픽 정보 추출"] = ["timeout", "timeout"]
    tools, _, _ = bv_tools(p, "T-B2", image=EchoImage())
    with pytest.raises(ToolCallExhausted):
        IMPLEMENTED["T-B2"](tb2_in("웹개발"), tools)


def test_tb2_requests_carry_plan_and_item_and_icon_prompt_has_no_numbers():
    content = dict(CONTENT, feature_details=[{"name": FEATURES[0], "detail": "회원 정보를 4567초 안에 입력한다"},
                                             {"name": FEATURES[1], "detail": "수업을 고르면 예약을 확인한다"}])
    p, image = BvProvider(content=content), EchoImage()
    tools, _, _ = bv_tools(p, "T-B2", image=image)
    IMPLEMENTED["T-B2"](tb2_in("웹개발"), tools)
    [req] = p.requests
    user = req.messages[-1]["content"]
    assert "아이템명: 헬스온" in user and "목표 고객: 헬스장" in user and INSTRUCTION in user
    assert "회원 정보를 입력하면 목록에 보여 준다" in user                            # 계획서 본문
    [img] = image.requests
    assert "아이콘 모음판" in img.prompt and "4567" not in img.prompt                 # 아이콘판 지시문은 숫자를 지운다


# ── T-V2 ──────────────────────────────────────────────────
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="헬스온 인포그래픽">'
       '<title>헬스온 인포그래픽</title><text>헬스온</text></svg>')
README = "실행 방법: 내려받은 파일을 연다."


def tv2_case(html: str | None = HTML, *, elements=None, kind: str = "html", provider: BvProvider | None = None,
             readme: str | None = README, features: list[str] = FEATURES):
    """파일을 넣고 T-V2 입력을 만든다 — (입력, tools, 호출 기록 모음, 저장소, 호출처)."""
    p = provider or BvProvider()
    tools, sink, store = bv_tools(p, "T-V2")
    image = tools.files.put("onepage.svg" if kind == "svg-onepage" else "infographic.svg", SVG.encode(),
                            "image/svg+xml")
    if kind == "svg-onepage":
        entry = image
    else:
        entry = tools.files.put("index.html", html.encode("utf-8"), "text/html") if html is not None else None
    readme_ref = tools.files.put("README.md", readme.encode("utf-8"), "text/markdown") if readme else None
    sink.drain()
    proto = Prototype(entry_file=entry, kind=kind, asset_files=[], readme_file=readme_ref,
                      implemented_features=list(features))
    info = Infographic(image_file=image, format="svg", alt_text="헬스온 인포그래픽")
    inp = c.TV2In(prototype=proto, infographic=info, feature_list=list(features), plan_doc=plan(features),
                  feature_elements=elements)
    return inp, tools, sink, store, p


def test_tv2_reads_files_and_fills_contract():
    inp, tools, sink, _, p = tv2_case()
    out = IMPLEMENTED["T-V2"](inp, tools)
    assert sorted(log.purpose for log in file_calls(sink)) == ["get", "get", "get"]   # 진입 파일 · 안내 문서 · 인포그래픽
    cc = out.code_check
    assert cc.gate_failures == [] and len(cc.checks) == 8
    for check in cc.checks:
        assert check.earned is not None and 0 <= check.earned <= check.weight
        if check.applicable:                                                          # 담당자 '얻은/배점점 — 근거'
            assert check.detail.startswith(f"{check.earned:g}/{check.weight:g}점 — ")
    assert any(not ch.applicable for ch in cc.checks)                                 # 입력칸 없음 → 3번 해당 없음
    fm = out.feature_match
    assert fm.missing_features == [] and fm.partial_features == [] and fm.judged_by == "htmlParse"
    assert out.artifact_score.total == pytest.approx(cc.total + fm.score)
    assert len(out.feature_elements) == 2 and all(v == ELEMENTS for v in out.feature_elements.values())
    purposes = p.purposes()
    assert sorted(x for x in purposes if x.startswith("계획서 대조 요소: ")) == sorted(
        f"계획서 대조 요소: {f}" for f in FEATURES)
    assert sorted(x for x in purposes if x.startswith("계획서 대조: ")) == sorted(
        [f"계획서 대조: {f}" for f in FEATURES] * 3)                                     # 기능마다 3번
    items = {r.metadata["item_key"] for r in p.requests}
    assert {f"{f}#요소" for f in FEATURES} | {f"{f}#{n}" for f in FEATURES for n in range(3)} == items


def test_tv2_partial_feature():
    p = BvProvider()
    half = json.dumps({"checks": [{"element": "a", "reason": "r", "present": True},
                                  {"element": "b", "reason": "r", "present": False}]}, ensure_ascii=False)
    p.scripts[f"계획서 대조: {FEATURES[1]}"] = [half] * 3
    inp, tools, _, _, _ = tv2_case(provider=p)
    fm = IMPLEMENTED["T-V2"](inp, tools).feature_match
    assert fm.partial_features == [FEATURES[1]] and fm.missing_features == []


def test_tv2_known_elements_skip_extraction_and_output_is_union():
    text = plan_text_of(plan())
    known = llm_judge._store_key("html", FEATURES[0], llm_judge.definition(FEATURES[0], text))
    given = {known: ["이미 뽑은 요소"], "다른 열쇠": ["x"]}
    inp, tools, _, _, p = tv2_case(elements=given)
    out = IMPLEMENTED["T-V2"](inp, tools)
    assert [x for x in p.purposes() if x.startswith("계획서 대조 요소: ")] == [f"계획서 대조 요소: {FEATURES[1]}"]
    new = llm_judge._store_key("html", FEATURES[1], llm_judge.definition(FEATURES[1], text))
    assert out.feature_elements == {known: ["이미 뽑은 요소"], "다른 열쇠": ["x"], new: ELEMENTS}
    assert given == {known: ["이미 뽑은 요소"], "다른 열쇠": ["x"]}                     # 입력은 그대로
    assert out.dump()["featureElements"] == out.feature_elements


def test_tv2_judge_exhausted_falls_back_to_rule_and_reports():
    p = BvProvider()
    p.prefix["계획서 대조: "] = ["timeout"] * 100
    inp, tools, _, _, _ = tv2_case(provider=p)
    out = IMPLEMENTED["T-V2"](inp, tools)
    assert out.feature_match.missing_features == []                                   # 규칙 판정(통과)으로 대신
    assert any(d.startswith("대조 LLM 판정 실패 2건") for d in out.diagnostics)


def test_tv2_element_extraction_exhausted_is_not_stored():
    p = BvProvider()
    p.prefix["계획서 대조 요소: "] = ["timeout"] * 100
    inp, tools, _, _, _ = tv2_case(provider=p)
    out = IMPLEMENTED["T-V2"](inp, tools)
    assert out.feature_elements == {} and out.feature_match.missing_features == []


@pytest.mark.parametrize("prefix", ["계획서 대조: ", "계획서 대조 요소: "])
def test_tv2_other_judge_errors_are_raised(prefix):
    p = BvProvider()
    p.prefix[prefix] = ["boom"] * 100
    inp, tools, _, _, _ = tv2_case(provider=p)
    with pytest.raises(RuntimeError):
        IMPLEMENTED["T-V2"](inp, tools)


def test_tv2_file_failure_is_raised_not_scored_zero():
    inp, tools, _, store, _ = tv2_case()
    store.delete_prefix(inp.prototype.entry_file.key.rsplit("/", 1)[0])
    with pytest.raises(ToolCallExhausted):
        IMPLEMENTED["T-V2"](inp, tools)


@pytest.mark.parametrize("html,code", [(None, "entry"), (VARIANTS["halting"], "sandbox"),
                                       (VARIANTS["secret"], "secret")])
def test_tv2_gate_failure_zeroes_layer_and_diagnostics_have_no_file_names(html, code):
    inp, tools, _, _, p = tv2_case(html)
    out = IMPLEMENTED["T-V2"](inp, tools)
    assert out.code_check.gate_failures == [code]
    assert out.code_check.total == 0 and out.feature_match.score == 0 and out.artifact_score.total == 0
    assert out.feature_match.missing_features == FEATURES
    assert all(ch.earned == 0 and not ch.passed for ch in out.code_check.checks)
    assert out.diagnostics[0].startswith("통과 필수 조건 실패: ")
    refs = [r for r in (inp.prototype.entry_file, inp.prototype.readme_file, inp.infographic.image_file) if r]
    text = " ".join(out.diagnostics)
    for ref in refs:
        assert ref.key not in text and ref.name not in text and ref.key.split("/")[2] not in text
    assert "index.html" not in text and "abcd1234efgh5678" not in text                 # 비밀값은 앞 8자만
    assert not [x for x in p.purposes() if x.startswith("계획서 대조")]                  # 대조 LLM을 부르지 않는다


def test_tv2_ignored_sandbox_api_only_deducts_item_7():
    inp, tools, _, _, _ = tv2_case(VARIANTS["ignored"])
    out = IMPLEMENTED["T-V2"](inp, tools)
    assert out.code_check.gate_failures == []
    [seventh] = [ch for ch in out.code_check.checks if ch.no == 7]
    assert not seventh.passed and seventh.earned < seventh.weight
    assert out.artifact_score.total > 0


def test_tv2_onepage_reads_shared_entry_once():
    inp, tools, sink, _, _ = tv2_case(kind="svg-onepage", readme="열람 · 인쇄 안내")
    out = IMPLEMENTED["T-V2"](inp, tools)
    assert sorted(log.purpose for log in file_calls(sink)) == ["get", "get"]           # 진입 파일(= 인포그래픽) · 안내 문서
    assert out.feature_match.judged_by == "svgTextParse"


@TIMING
def test_tv2_judge_concurrency_is_at_most_three():
    features = [f"기능{n}" for n in "가나다라"]
    lines = [f"{f}: 입력을 받아 결과를 보여 준다." for f in features]
    html = HTML.replace('<div id="out">', "".join(
        f'<button id="b{n}" data-feature="{f}">{f}</button>' for n, f in enumerate(features)) + '<div id="out">')
    html = html.replace("</script>", "".join(
        f"document.getElementById('b{n}').addEventListener('click', function(){{}});" for n in range(4))
        + "</script>", 1)
    p = BvProvider(html=html, hold=0.05)
    inp, tools, _, _, _ = tv2_case(html, provider=p, features=features)
    inp = inp.model_copy(update={"plan_doc": plan(features, lines)})
    IMPLEMENTED["T-V2"](inp, tools)
    assert len(p.requests) == 4 + 4 * 3 and p.peak == 3


# ── 실행 중 디스크에 닿지 않음 ────────────────────────────
def test_three_tasks_do_not_touch_disk(monkeypatch):
    fonts._style.cache_clear()
    illustrations._uri.cache_clear()
    html_kit.font_style.cache_clear()
    html_kit.icon_sprite.cache_clear()
    with no_disk(monkeypatch):
        t1, _, store = bv_tools(BvProvider(), "T-B1")
        b1 = IMPLEMENTED["T-B1"](tb1_in(), t1)
        t2, _, _ = bv_tools(BvProvider(), "T-B2", image=EchoImage(), files=store)
        b2 = IMPLEMENTED["T-B2"](tb2_in(), t2)
        t3, _, _ = bv_tools(BvProvider(), "T-V2", files=store)
        proto = b1.prototype
        v2 = IMPLEMENTED["T-V2"](c.TV2In(prototype=proto, infographic=b2.infographic, feature_list=FEATURES,
                                         plan_doc=plan()), t3)
    assert b1.check.passed and v2.code_check.gate_failures == []
