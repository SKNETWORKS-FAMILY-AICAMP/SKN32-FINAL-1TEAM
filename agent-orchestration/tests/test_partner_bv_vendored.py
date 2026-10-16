"""구현 · 검증-2 담당자 코드 옮기기 — 연결부.

옮긴 파일 목록이 원본(2026-10-08 판)과 같다, 금지 호출(OpenAI 직접 · os.getenv · datetime.now · .env · time.sleep ·
파일 쓰기 · 폴더 만들기)이 남지 않았다, 두 담당자 패키지가 서로 import하지 않는다, 자료(글꼴 · 그림 · 템플릿)를 불러올 때
한 번 읽고 실행 중에는 디스크에 닿지 않는다, 검증-2 진입 파일 문구에 이름 · 경로가 없다, 요소 목록은 넘겨받은 사전으로
읽고 더한다, 대조 LLM은 ToolCallExhausted만 받고 동시 3개까지 부른다, 담당자 고정 문구가 우리 문구와 같다.

담당자 tasks.py 두 개는 T3가 지금 계약(FileRef · tools.files)으로 고쳤다 — Task 함수 시험은 test_partner_bv_tasks.py ·
test_partner_bv_flow.py.
"""
from __future__ import annotations

import ast
import builtins
import io
import json
import os
import pathlib
import re
import sys
import threading
import tokenize
import tomllib
from contextlib import contextmanager

import pytest

import sbrain.agents.partner_bv as partner_bv
from sbrain.agents.partner_bv import resources
from sbrain.agents.partner_bv.engineering_agent import builder_html, file_writer, gates as eng_gates, html_kit
from sbrain.agents.partner_bv.engineering_agent.infographic import (artsheet, design, fonts, illustrations,
                                                                    generate_infographic_content, render_infographic)
from sbrain.agents.partner_bv.verification_agent import feature_match, llm_judge, score
from sbrain.agents.partner_bv.verification_agent.rules import gates as v_gates
from sbrain.flow.rework_map import REWORK_DEFAULT_REASON
from sbrain.models.clock import utc_now
from sbrain.orchestrator.errors import ToolCallExhausted
from sbrain.orchestrator.tools import CallSink, Tools, ToolsConfig, ToolsContext

BV_DIR = pathlib.Path(partner_bv.__file__).parent
ENG_DIR = BV_DIR / "engineering_agent"
VER_DIR = BV_DIR / "verification_agent"
CODE_DIR = BV_DIR.parent.parent.parent            # 저장소 폴더(agent-orchestration)

OUR_FILES = {"__init__.py", "resources.py", "tasks.py", "VENDORED.md",
             "engineering_agent/README.md", "verification_agent/README.md"}   # 담당자 README(2026-10-16 루트 원본에서 옮김)

_SCENES = ("ai", "city", "conversation", "cook", "delivery", "dev", "growth", "maintenance", "mobile", "monitor",
           "package", "presentation", "robot", "sales", "store", "video", "workers")
EXPECTED_VENDORED = {
    *(f"engineering_agent/{n}" for n in ("__init__.py", "builder_html.py", "file_writer.py", "gates.py",
                                         "html_kit.py", "tasks.py")),
    *(f"engineering_agent/infographic/{n}.py" for n in (
        "__init__", "artsheet", "compose_guide", "composer", "content", "design", "design_kit", "fonts", "icons",
        "illustrations", "layout", "poster", "render", "showcase", "style", "svg_parts", "themes")),
    "engineering_agent/infographic/assets/LICENSE-Pretendard.txt",
    "engineering_agent/infographic/assets/pretendard-ksx1001.woff2",
    "engineering_agent/infographic/assets/illustrations/LICENSE.txt",
    *(f"engineering_agent/infographic/assets/illustrations/{s}.svg" for s in _SCENES),
    *(f"engineering_agent/infographic_templates/{n}_template.svg" for n in ("ai_api", "onepage", "webdev")),
    *(f"verification_agent/{n}.py" for n in ("__init__", "feature_match", "llm_judge", "score", "tasks")),
    *(f"verification_agent/rules/{n}.py" for n in ("__init__", "color", "gates", "html_parser", "items", "r4",
                                                    "r4_onepage", "wiring")),
}


def _files() -> set[str]:
    return {p.relative_to(BV_DIR).as_posix() for p in BV_DIR.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts}


# ── 옮긴 파일 목록 ─────────────────────────────────────────
def test_vendored_file_list_matches_original():
    assert len(EXPECTED_VENDORED) == 59
    assert _files() == EXPECTED_VENDORED | OUR_FILES


# ── 금지 호출 (소스 검사) ──────────────────────────────────
FORBIDDEN = {
    "OpenAI 직접 호출": r"\bfrom openai\b|\bimport openai\b|OpenAI\(",
    "os.getenv": r"os\.getenv",
    "os.environ": r"os\.environ",
    "datetime.now": r"datetime\.now|utcnow|date\.today",
    ".env 읽기": r"load_dotenv|dotenv",
    "time.sleep": r"time\.sleep|\bimport time\b",
    "직접 HTTP": r"\bimport (requests|httpx|urllib)\b|\bfrom (requests|httpx|urllib)\b",
    "파일 쓰기": r"write_text|write_bytes|\.open\(\s*[\"'][wxa]|\bopen\([^)\n]*,\s*[\"'][wxa]",
    "폴더 만들기": r"\.mkdir\(|makedirs",
    "시도 폴더(uuid)": r"\buuid\b",
}


def _py_files() -> list[pathlib.Path]:
    return sorted(BV_DIR.rglob("*.py"))


def _code(f: pathlib.Path) -> str:
    """주석을 뺀 소스 — 바꾼 줄의 [S-Brain] 주석이 지운 것을 적어도 검사에 걸리지 않게."""
    tokens = tokenize.generate_tokens(io.StringIO(f.read_text(encoding="utf-8")).readline)
    return tokenize.untokenize((t.type, t.string) for t in tokens if t.type != tokenize.COMMENT)


def test_vendored_code_has_no_forbidden_calls():
    files = _py_files()
    assert len(files) >= 34
    found = [(f.relative_to(BV_DIR).as_posix(), name) for f in files for name, pat in FORBIDDEN.items()
             if re.search(pat, _code(f))]
    assert found == []


def test_vendored_code_reads_no_files_except_resources():
    """자료는 resources.py만 읽는다. 담당자 tasks.py 둘도 경로로 읽지 않는다 — 산출물 파일은 tools.files로 (T3)."""
    allowed = {"resources.py"}
    found = [f.relative_to(BV_DIR).as_posix() for f in _py_files()
             if f.relative_to(BV_DIR).as_posix() not in allowed
             and re.search(r"read_text|read_bytes|is_file\(|\.exists\(|\bPath\b", _code(f))]
    assert found == []


def test_vendored_code_uses_package_relative_imports():
    for f in _py_files():
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import) (engineering_agent|verification_agent)\b", text, re.M), f.name


def test_two_partner_packages_do_not_import_each_other():
    pattern = {ENG_DIR: r"^\s*(from|import)\s+[.\w]*verification_agent",
               VER_DIR: r"^\s*(from|import)\s+[.\w]*engineering_agent"}
    for folder, pat in pattern.items():
        for f in folder.rglob("*.py"):
            assert not re.search(pat, f.read_text(encoding="utf-8"), re.M), f.name
    # 검증-2는 우리 자료 모듈(엔지니어링 자료)도 쓰지 않는다
    for f in VER_DIR.rglob("*.py"):
        assert "resources" not in f.read_text(encoding="utf-8"), f.name


def test_changed_lines_are_marked():
    marked = {f.relative_to(BV_DIR).as_posix() for f in _py_files() if "[S-Brain]" in f.read_text(encoding="utf-8")}
    for name in ("engineering_agent/builder_html.py", "engineering_agent/file_writer.py",
                 "engineering_agent/html_kit.py", "engineering_agent/infographic/fonts.py",
                 "engineering_agent/infographic/illustrations.py", "engineering_agent/infographic/render.py",
                 "engineering_agent/infographic/artsheet.py",
                 "engineering_agent/tasks.py", "verification_agent/tasks.py",
                 "verification_agent/llm_judge.py", "verification_agent/rules/gates.py", "verification_agent/score.py"):
        assert name in marked, name


# ── 미리 불러오기 ──────────────────────────────────────────
def test_package_import_preloads_lazy_modules_and_tasks():
    base = "sbrain.agents.partner_bv."
    for name in ("engineering_agent.builder_html", "engineering_agent.html_kit", "engineering_agent.gates",
                 "engineering_agent.file_writer", "engineering_agent.infographic.poster",
                 "engineering_agent.infographic.composer", "engineering_agent.infographic.showcase",
                 "engineering_agent.infographic.svg_parts", "engineering_agent.infographic.layout",
                 "engineering_agent.infographic.themes", "engineering_agent.infographic.artsheet",
                 "engineering_agent.infographic.design", "engineering_agent.infographic.render",
                 "verification_agent.score", "verification_agent.llm_judge", "verification_agent.feature_match",
                 "resources"):
        assert base + name in sys.modules, name
    assert "sbrain.orchestrator.errors" in sys.modules
    # 담당자 tasks.py 둘은 등록 모듈(partner_bv/tasks.py — 조립이 부른다)이 불러온다. Task 함수 안의 늦은 import
    # (sbrain.contracts.tasks · sbrain.models)는 그 전에 이미 불러와져 있다
    import sbrain.agents.partner_bv.tasks  # noqa: F401
    for name in ("tasks", "engineering_agent.tasks", "verification_agent.tasks"):
        assert base + name in sys.modules, name
    assert "sbrain.contracts.tasks" in sys.modules and "sbrain.models" in sys.modules


# ── 자료 상수 ──────────────────────────────────────────────
def test_resources_are_loaded_once_and_not_empty():
    assert resources.FONT[:4] == b"wOF2" and len(resources.FONT) > 100_000
    assert set(resources.ILLUSTRATIONS) == set(_SCENES)
    assert all(v.lstrip().startswith((b"<svg", b"<?xml")) for v in resources.ILLUSTRATIONS.values())
    assert set(resources.TEMPLATES) == {"ai_api_template.svg", "onepage_template.svg", "webdev_template.svg"}
    assert all("<svg" in t for t in resources.TEMPLATES.values())
    assert resources.template("onepage_template.svg") == resources.TEMPLATES["onepage_template.svg"]
    with pytest.raises(FileNotFoundError) as e:
        resources.template("없는_template.svg")
    assert "없는" not in str(e.value)
    assert fonts._style() and illustrations._uri("growth").startswith("data:image/svg+xml;base64,")
    assert illustrations._uri("없는장면") == ""                 # 없는 그림은 빈 값(담당자 동작)


def test_missing_font_means_default_font(monkeypatch):
    monkeypatch.setattr(resources, "FONT", b"")
    fonts._style.cache_clear()
    html_kit.font_style.cache_clear()
    try:
        assert fonts.embed("<svg>x</svg>") == "<svg>x</svg>"
        assert html_kit.font_style() == ""
    finally:
        fonts._style.cache_clear()
        html_kit.font_style.cache_clear()


# ── 가짜 호출처 (네트워크 없음) ─────────────────────────────
PLAN = ("점검콕 사업계획서\n"
        "고장 신고 접수: 사진과 증상을 올리면 담당자에게 바로 전달한다.\n"
        "점검 일정 알림: 점검 날짜를 3일 전에 알린다.\n"
        "수익모델: 단지당 월 50,000원 구독.\n"
        "추진 일정: 2026년 12월 개발, 2027년 3월 출시.\n"
        "기대 효과: 처리 시간 30% 단축.")
FEATURES = ["고장 신고 접수", "점검 일정 알림"]

HTML = ("<!DOCTYPE html><html lang=\"ko\"><head><meta charset=\"utf-8\"><title>점검콕</title>\n"
        "<!-- IMPLEMENTED_FEATURES: 고장 신고 접수 | 점검 일정 알림 -->\n"
        "<style>body { color: #0F172A; background-color: #FFFFFF; }</style></head><body><h1>점검콕</h1>\n"
        "<button id=\"btn-report\" data-feature=\"고장 신고 접수\"><svg class=\"icon\"><use href=\"#i-alert\"/></svg>"
        "고장 신고 접수</button>\n"
        "<button id=\"btn-alarm\" data-feature=\"점검 일정 알림\">점검 일정 알림</button><div id=\"out\"></div>\n"
        "<script>document.getElementById('btn-report').addEventListener('click', function(){"
        "document.getElementById('out').textContent='접수됨';});\n"
        "document.getElementById('btn-alarm').addEventListener('click', function(){"
        "document.getElementById('out').textContent='3일 전 알림';});</script>\n</body></html>")

CONTENT = {
    "item_name": "점검콕", "features": FEATURES, "target_users": "아파트 관리소",
    "problem": "설비 고장 신고가 늦게 전달된다", "solution": "사진과 증상을 받아 담당자에게 바로 전달한다",
    "revenue_unit_price": "단지당 월 50,000원", "timeline_baseline": "2026년 12월 개발, 2027년 3월 출시",
    "feature_details": [{"name": "고장 신고 접수", "detail": "사진과 증상을 올리면 담당자에게 전달"},
                        {"name": "점검 일정 알림", "detail": "점검 날짜를 3일 전에 알린다"}],
    "key_metrics": [{"value": "30%", "label": "처리 시간 단축"}],
    "solution_steps": ["사진 올리기", "담당자 전달", "점검 알림"],
}


class FakeProvider:
    """목적별로 답하는 가짜 LLM 호출처. 받은 요청을 모은다."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests: list = []

    def complete(self, request):
        with self.lock:
            self.requests.append(request)
        purpose = request.metadata["purpose"]
        user = request.messages[-1]["content"]
        if purpose == "T-B1 HTML 생성":
            return f"```html:index.html\n{HTML}\n```"
        if purpose == "T-B2 인포그래픽 정보 추출":
            return json.dumps(CONTENT, ensure_ascii=False)
        if purpose.startswith("계획서 대조 요소: "):
            return json.dumps({"elements": ["사진", "증상"]}, ensure_ascii=False)
        if "[확인할 요소]" in user:
            count = len(user.split("[확인할 요소]\n", 1)[1].splitlines())
            return json.dumps({"checks": [{"element": "e", "reason": "있음", "present": True}] * count},
                              ensure_ascii=False)
        return json.dumps({"reason": "계획서와 같다", "verdict": "충족"}, ensure_ascii=False)


def make_tools(provider, retry=1) -> Tools:
    cfg = ToolsConfig(agent="구현", provider="p", model="m", temperature=None, timeout_sec=10,
                      retry_count=retry, retry_interval_sec=0)
    ctx = ToolsContext(run_id="r", execution_id="e", task_id="T-B1", providers={"p": provider}, sink=CallSink(),
                       now=utc_now, sleep=lambda s: None)
    return Tools(cfg, ctx)


@contextmanager
def no_disk(monkeypatch):
    """블록 안에서 파일을 열거나 보거나 쓰거나 폴더를 만들면 AssertionError. 나갈 때 되돌린다."""
    def boom(*a, **k):
        raise AssertionError("실행 중 디스크 접근")
    with monkeypatch.context() as m:
        for target, name in ((builtins, "open"), (io, "open"), (os, "open"), (os, "mkdir"), (os, "makedirs"),
                             (pathlib.Path, "open"), (pathlib.Path, "read_text"), (pathlib.Path, "read_bytes"),
                             (pathlib.Path, "write_text"), (pathlib.Path, "write_bytes"), (pathlib.Path, "mkdir"),
                             (pathlib.Path, "exists"), (pathlib.Path, "stat"), (pathlib.Path, "is_file"),
                             (pathlib.Path, "is_dir")):
            m.setattr(target, name, boom)
        yield


# ── 실행 중 디스크에 닿지 않음 ──────────────────────────────
def test_tb1_build_check_decorate_do_not_touch_disk(monkeypatch):
    fake = FakeProvider()
    fonts._style.cache_clear()
    html_kit.font_style.cache_clear()
    html_kit.icon_sprite.cache_clear()
    with no_disk(monkeypatch):
        result = builder_html.build_prototype_html(
            FEATURES, {"itemName": "점검콕", "oneLineSummary": "설비 점검", "targetCustomer": "관리소"},
            "웹개발", "지시문", make_tools(fake), plan_text=PLAN, previous_html="")
        decorated = result["sourceText"]
        again = html_kit.decorate(decorated)                       # 이미 넣었으면 다시 넣지 않는다
        stripped = html_kit.strip(decorated)
        message = builder_html.user_message("지시문", decorated)    # 이전 HTML은 끼워 넣은 것을 빼고 싣는다
    assert result["status"] == "success" and result["entryFileName"] == "index.html"
    assert "entryFilePath" not in result and "readmePath" not in result
    assert "run_id" not in result["summary"]
    assert result["implementedFeatures"] == FEATURES
    assert 'data-kit="font"' in decorated and "data:font/woff2;base64," in decorated
    assert 'data-kit="icons"' in decorated
    assert again == decorated
    assert 'data-kit="font"' not in stripped and 'data-kit="icons"' not in stripped
    assert "data:font/woff2" not in message and "<이전HTML>" in message
    (req,) = fake.requests
    assert req.metadata["purpose"] == "T-B1 HTML 생성"


def test_tb1_gate_failure_still_returns_decorated_entry_without_saving(monkeypatch):
    bad = HTML.replace("<head>", '<head><script src="https://cdn.example.com/x.js"></script>')

    class Reply(FakeProvider):
        def complete(self, request):
            return f"```html:index.html\n{bad}\n```"

    with no_disk(monkeypatch):
        result = builder_html.build_prototype_html(FEATURES, {}, "AI_API", "지시문", make_tools(Reply()))
    # 담당자 10-12 판: 자체 검사에 걸려도 끼워 넣은 HTML을 진입 파일로 돌려주고 status만 불통과다
    assert result["status"] == "failed" and result["entryFileName"] == "index.html"
    assert result["sourceText"] == html_kit.decorate(bad)        # 통과 때와 똑같이 끼워 넣었다
    assert 'data-kit="icons"' in result["sourceText"] and "cdn.example.com/x.js" in result["sourceText"]
    assert result["implementedFeatures"] == FEATURES
    assert result["gate_failures"]["dependency"]
    assert result["summary"].startswith("E-B1-DEP")


def test_tb1_plan_text_keeps_head_and_tail_over_limit():
    short = "가" * 100
    assert builder_html._plan_for_prompt(f"  {short}  ") == short
    long = "앞" * 15000 + "가운데" * 3000 + "끝" * 5000
    cut = builder_html._plan_for_prompt(long)
    assert cut.startswith("앞" * 15000) and cut.endswith("끝" * 4000) and "…(중략)…" in cut
    assert len(cut) == builder_html._PLAN_CHARS + len("\n…(중략)…\n")


@pytest.mark.parametrize("snippet,external", [
    ('<script src="https://cdn.example.com/x.js"></script>', True),
    ('<link rel="stylesheet" href="style.css">', True),
    ('<img src="./logo.png" alt="로고">', True),
    ("<style>@import url('https://fonts.example.com/a.css');</style>", True),
    ('<div style="background:url(bg.png)"></div>', True),
    ('<img src="data:image/png;base64,AAAA" alt="그림">', False),
    ("<style>.a{background:url(#grad)}</style>", False),
    ("<p>https://example.com 은 글자일 뿐</p>", False),
])
def test_verify2_external_refs_matches_tb1_dependency_gate(snippet, external):
    """검증-2 7번 외부 의존과 T-B1 E-B1-DEP는 같은 기준이다(담당자 10-12 — 서로 import하지 않으므로 함께 고친다)."""
    html = f"<html lang=\"ko\"><head></head><body>{snippet}</body></html>"
    dep_ok, _ = eng_gates.check_external_dependency_gate(html)
    assert bool(v_gates.external_refs(html)) is external
    assert dep_ok is not external


def test_file_writer_keeps_only_code_block_parsing():
    assert not hasattr(file_writer, "save_files")
    assert file_writer.parse_code_blocks("```html:index.html\n<p>a</p>\n```") == {"index.html": "<p>a</p>"}


def test_tb2_content_design_art_render_do_not_touch_disk(monkeypatch):
    fake = FakeProvider()
    tools = make_tools(fake)                    # 이미지 모델 설정 없음 → tools.image 실패 → 기본 아이콘(담당자 동작)
    fonts._style.cache_clear()
    illustrations._uri.cache_clear()
    with no_disk(monkeypatch):
        content = generate_infographic_content("원페이지", PLAN, tools,
                                               feature_notes=builder_html.feature_notes(FEATURES, PLAN))
        content["features"] = FEATURES
        content["feature_details"] = [d["detail"] for d in CONTENT["feature_details"]]
        content = design.apply("원페이지", content)
        content["_art"] = artsheet.generate("원페이지", content, tools)
        out = render_infographic("원페이지", content)
        web = render_infographic("웹개발", dict(content, flow_steps=["사진 올리기", "담당자 전달", "점검 알림"]))
    assert content["_art"] is None
    assert set(out) == {"file_name", "alt_text", "source_text"}
    assert out["file_name"] == "onepage.svg" and web["file_name"] == "infographic.svg"
    svg = out["source_text"]
    assert svg.lstrip().startswith("<svg") and "data:font/woff2;base64," in svg      # 글꼴 상수가 들어갔다
    assert out["alt_text"] and out["alt_text"] in svg


def test_tv2_scoring_and_judges_do_not_touch_disk(monkeypatch):
    fake = FakeProvider()
    tools = make_tools(fake)
    svg = render_infographic("원페이지", design.apply("원페이지", dict(
        CONTENT, feature_details=[d["detail"] for d in CONTENT["feature_details"]])))["source_text"]
    store: dict[str, list[str]] = {}
    with no_disk(monkeypatch):
        code = score.compute_code_check("index.html", HTML, "실행 방법: index.html을 연다", svg)
        html_feat = feature_match.match_features(
            FEATURES, HTML, "html", PLAN, llm_judge.make_judge(tools, "html", HTML, PLAN, store))
        onepage = score.compute_infographic_check("onepage.svg", svg, "열람 · 인쇄 안내")
        one_feat = feature_match.match_features(
            FEATURES, svg, "svg-onepage", PLAN, llm_judge.make_judge(tools, "svg-onepage", svg, PLAN, store),
            llm_judge.make_field_judge(tools, PLAN))
    assert code["passed"] and code["gate_codes"] == []
    assert onepage["passed"], onepage["gate_failures"]
    assert html_feat["missing_features"] == [] and html_feat["llm_failed"] == []
    assert one_feat["llm_failed"] == []
    assert len(store) == 4                                        # 두 종류 × 기능 둘의 요소 목록이 사전에 더해졌다
    assert all(v == ["사진", "증상"] for v in store.values())


# ── 검증-2 진입 파일 문구 (경로 · 이름 없음) ─────────────────
@pytest.mark.parametrize("gate,suffix", [(v_gates.html_gates, ".html"), (v_gates.svg_gates, ".svg")])
def test_entry_gate_messages_have_no_name_or_path(gate, suffix):
    missing = gate(None, "<svg/>")
    assert ("entry", "진입 파일 없음") in missing
    assert ("entry", "진입 파일 없음") in gate("", "<svg/>")
    wrong = gate("secret_dir_name/entry.txt", "<svg/>")
    entry = [m for c, m in wrong if c == "entry"]
    assert entry == [f"진입 파일 확장자가 {suffix}가 아님"]
    assert all("secret_dir_name" not in m and "entry.txt" not in m for _, m in wrong)
    assert ("entry", "진입 파일 원문이 비어 있음") in gate(f"index{suffix}", "  ")


def test_entry_gate_passes_by_name_and_content_only():
    assert v_gates.html_gates("index.html", HTML) == []
    assert v_gates.html_gates("INDEX.HTML", HTML) == []           # 확장자는 대소문자 무시(담당자 동작)
    assert v_gates.svg_gates("onepage.svg", '<svg xmlns="http://www.w3.org/2000/svg"></svg>') == []
    assert score.compute_code_check(None, HTML, None)["gate_codes"] == ["entry"]


# ── llm_judge: 요소 사전 · 예외 · 동시 수 ───────────────────
class ScriptTools:
    """작은 가짜 tools — llm(messages, parse=, purpose=)를 behave(purpose, messages)로 답한다. 최대 동시 수를 잰다."""

    def __init__(self, behave, hold: float = 0.0) -> None:
        self.behave, self.hold = behave, hold
        self.lock = threading.Lock()
        self.active = self.peak = 0
        self.purposes: list[str] = []
        self.items: list[str] = []
        self.release = threading.Event()

    def for_item(self, key):
        with self.lock:
            self.items.append(key)
        return self

    def llm(self, messages, *, parse=None, purpose="", **_):
        with self.lock:
            self.purposes.append(purpose)
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            if self.hold:
                self.release.wait(self.hold)
            reply = self.behave(purpose, messages)
            return parse(reply) if parse else reply
        finally:
            with self.lock:
                self.active -= 1


def good(purpose, messages):
    return FakeProvider().complete(type("R", (), {"metadata": {"purpose": purpose}, "messages": messages})())


def exhausted():
    return ToolCallExhausted(error="호출실패", error_kind="일시", tries=2, call_id="c")


def test_known_key_skips_element_extraction_and_new_ones_are_added():
    known = llm_judge._store_key("html", FEATURES[0], llm_judge.definition(FEATURES[0], PLAN))
    store = {known: ["이미 뽑은 요소"], "다른 산출물 열쇠": ["x"]}
    tools = ScriptTools(good)
    out = llm_judge.make_judge(tools, "html", HTML, PLAN, store)(FEATURES)
    element_calls = [p for p in tools.purposes if p.startswith("계획서 대조 요소: ")]
    assert element_calls == [f"계획서 대조 요소: {FEATURES[1]}"]           # 사전에 있는 기능은 뽑지 않는다
    new_key = llm_judge._store_key("html", FEATURES[1], llm_judge.definition(FEATURES[1], PLAN))
    assert store == {known: ["이미 뽑은 요소"], "다른 산출물 열쇠": ["x"], new_key: ["사진", "증상"]}   # 입력 ∪ 새 것
    assert out[FEATURES[0]][0] == 1.0 and "이미 뽑은 요소" in out[FEATURES[0]][1]
    assert f"{FEATURES[0]}#요소" in tools.items and f"{FEATURES[0]}#0" in tools.items   # 항목 키는 담당자 문구 그대로


def test_none_store_is_empty_dict():
    tools = ScriptTools(good)
    out = llm_judge.make_judge(tools, "html", HTML, PLAN)(FEATURES)
    assert all(v[0] == 1.0 for v in out.values())
    assert len([p for p in tools.purposes if p.startswith("계획서 대조 요소: ")]) == 2


def test_element_extraction_exhausted_is_not_stored_and_asks_whole_feature():
    def behave(purpose, messages):
        if purpose.startswith("계획서 대조 요소: "):
            raise exhausted()
        return good(purpose, messages)
    store: dict = {}
    out = llm_judge.make_judge(ScriptTools(behave), "html", HTML, PLAN, store)(FEATURES)
    assert store == {}
    assert all(v == (1.0, "계획서와 같다") for v in out.values())        # 통째로 묻는 판정(담당자 동작)


def test_check_exhausted_falls_back_to_rule_and_is_reported():
    def behave(purpose, messages):
        if purpose.startswith("계획서 대조: "):
            raise exhausted()
        return good(purpose, messages)
    result = feature_match.match_features(FEATURES, HTML, "html", PLAN,
                                          llm_judge.make_judge(ScriptTools(behave), "html", HTML, PLAN, {}))
    assert result["llm_failed"] == FEATURES and result["missing_features"] == []


def test_field_judge_exhausted_is_none_other_errors_raise():
    def tired(purpose, messages):
        raise exhausted()
    assert llm_judge.make_field_judge(ScriptTools(tired), PLAN)({"문제 정의": "고장 신고"}) == {"문제 정의": None}

    def broken(purpose, messages):
        raise ValueError("호출처 버그")
    with pytest.raises(ValueError):
        llm_judge.make_field_judge(ScriptTools(broken), PLAN)({"문제 정의": "고장 신고"})


@pytest.mark.parametrize("stage", ["요소", "대조"])
def test_other_exceptions_are_not_swallowed(stage):
    def behave(purpose, messages):
        if (stage == "요소") == purpose.startswith("계획서 대조 요소: "):
            raise ValueError("호출처 버그")
        return good(purpose, messages)
    with pytest.raises(ValueError):
        llm_judge.make_judge(ScriptTools(behave), "html", HTML, PLAN, {})(FEATURES)


def test_concurrency_is_at_most_three():
    assert llm_judge._MAX_WORKERS == 3 and llm_judge._VOTES == 3
    features = [f"기능{i}" for i in range(4)]
    plan = "\n".join(f"{f}: 입력을 받아 결과를 보여 준다." for f in features)
    tools = ScriptTools(good, hold=0.05)
    out = llm_judge.make_judge(tools, "html", HTML, plan, {})(features)
    assert len(out) == 4
    assert len(tools.purposes) == 4 + 4 * 3
    assert tools.peak == 3

    field_tools = ScriptTools(good, hold=0.05)
    llm_judge.make_field_judge(field_tools, PLAN)({"문제 정의": "a", "해결 방안": "b"})
    assert field_tools.peak == 3


def test_judge_module_has_no_file_store():
    assert not hasattr(llm_judge, "ELEMENT_STORE")


# ── 담당자 고정 문구 ───────────────────────────────────────
def test_user_only_reason_matches_rework_default_reason():
    """담당자 engineering_agent/tasks.py의 _USER_ONLY_REASON — 소스에 한 번만 있고 import한 값도 같다."""
    from sbrain.agents.partner_bv.engineering_agent.tasks import _USER_ONLY_REASON

    tree = ast.parse((ENG_DIR / "tasks.py").read_text(encoding="utf-8"))
    values = [node.value.value for node in ast.walk(tree)
              if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "_USER_ONLY_REASON"
                                                      for t in node.targets)]
    assert values == [REWORK_DEFAULT_REASON] == [_USER_ONLY_REASON]


# ── 설치본 패키지 자료 ─────────────────────────────────────
def test_pyproject_ships_partner_bv_assets():
    data = tomllib.loads((CODE_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = data["tool"]["setuptools"]["package-data"]
    assets = [p for p in BV_DIR.rglob("*") if p.is_file() and p.suffix in (".woff2", ".svg", ".txt")]
    assert len(assets) == 2 + 18 + 3
    shipped = {p.resolve() for pkg, globs in package_data.items() for g in globs
               for p in (CODE_DIR / pathlib.Path(*pkg.split("."))).glob(g)}
    for asset in assets:
        assert asset.resolve() in shipped, asset.name
