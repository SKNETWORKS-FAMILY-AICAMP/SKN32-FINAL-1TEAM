import json
import sys
import types
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from xml.etree import ElementTree as ET

from engineering_agent import gates, infographic
from engineering_agent.infographic import render as infographic_render
from engineering_agent.builder_html import build_prototype_html
from engineering_agent.file_writer import save_files
from verification_agent.feature_match import match_features
from verification_agent.rules.html_parser import parse_page
from verification_agent.rules.r4 import check_contrast, check_html
from verification_agent.rules.items import total as items_total
from verification_agent.score import compute_code_check, compute_infographic_check

_ONEPAGE_PLAN = ("동네 매장 대상. 주문 대기가 길다. 빠른 주문으로 줄인다. 단가는 월 10000원. "
                 "2026-12-01 착수. 주문 조회 기능은 매장별 주문 상태를 한 화면에 보여준다.")

_ONEPAGE_DATA = {
    "item_name": "동네 주문", "target_users": "동네 매장",
    "problem": "주문 대기", "solution": "빠른 주문",
    "revenue_unit_price": "월 10000원", "timeline_baseline": "2026-12-01",
    "features": ["주문 조회"], "feature_details": ["매장별 주문 상태를 한 화면에 보여준다"],
}


def _page(body: str, style: str = "body{color:#0F172A;background-color:#FFFFFF}") -> str:
    return (f'<!doctype html><html lang="ko"><head><style>{style}</style></head>'
            f"<body><h1>동네 주문</h1>{body}</body></html>")


class _FakeFormatError(Exception):
    """Orchestration의 sbrain.orchestrator.errors.FormatError 대역."""


def _stub_sbrain_errors():
    """sbrain이 설치되지 않은 곳에서도 R2 경로를 검사하기 위한 모듈 대역.

    구현 Agent는 FormatError를 실패 시점에만 import하므로, 정상 경로 테스트는 이
    대역 없이도 돌아간다. 여기서 꽂는 것은 예외 경로 검사용이다.
    """
    errors = types.ModuleType("sbrain.orchestrator.errors")
    errors.FormatError = _FakeFormatError
    orchestrator = types.ModuleType("sbrain.orchestrator")
    orchestrator.errors = errors
    sbrain = types.ModuleType("sbrain")
    sbrain.orchestrator = orchestrator
    return patch.dict(sys.modules, {
        "sbrain": sbrain,
        "sbrain.orchestrator": orchestrator,
        "sbrain.orchestrator.errors": errors,
    })


def _json(**fields) -> str:
    """모델이 돌려주는 JSON 응답 문자열(인포그래픽 추출)."""
    return json.dumps(fields, ensure_ascii=False)


class _Tools:
    """tools.llm의 계약 중 이 패키지가 쓰는 부분만 재현한다 — schema로 검사한 뒤
    parse에 넘기고, parse의 반환값을 그대로 돌려준다."""

    def __init__(self, response):
        self._response = response
        self.messages = None
        self.kwargs = None

    def llm(self, messages, *, schema=None, parse=None, purpose=""):
        self.messages = messages
        self.kwargs = {"schema": schema, "parse": parse, "purpose": purpose}
        value = self._response(schema) if callable(self._response) else self._response
        return parse(value) if parse is not None else value


class ArtifactAgentTests(TestCase):
    _TEMP_ROOT = Path(__file__).resolve().parents[1] / "engineering_agent" / "output"

    def test_attempt_files_cannot_overwrite_or_escape(self):
        with TemporaryDirectory(dir=self._TEMP_ROOT) as directory:
            root = Path(directory)
            first = save_files({"index.html": "first"}, "attempt-1", root)
            self.assertEqual(Path(first["index.html"]).read_text(encoding="utf-8"), "first")
            with self.assertRaises(FileExistsError):
                save_files({"index.html": "second"}, "attempt-1", root)
            with self.assertRaises(ValueError):
                save_files({"../other.html": "escape"}, "attempt-2", root)
            with self.assertRaises(ValueError):
                save_files({"index.html": "escape"}, "../other", root)
            second = save_files({"index.html": "second"}, "attempt-2", root)
            self.assertEqual(Path(first["index.html"]).read_text(encoding="utf-8"), "first")
            self.assertEqual(Path(second["index.html"]).read_text(encoding="utf-8"), "second")

    def _render_onepage(self, **over):
        data = {**_ONEPAGE_DATA, **over}
        directory = TemporaryDirectory(dir=self._TEMP_ROOT)
        self.addCleanup(directory.cleanup)
        with patch.object(infographic_render, "_OUTPUT_DIR", Path(directory.name)):
            return infographic.render_infographic("원페이지", data)

    def test_every_theme_keeps_onepage_readable(self):
        """사업 분야마다 색 테마가 바뀌어도 명도 대비 등 원페이지 8항목이 모두 통과한다."""
        from engineering_agent.infographic import themes
        for name in themes.THEMES:
            with self.subTest(name), patch.object(themes, "pick", return_value=name):
                saved = self._render_onepage()
                checked = compute_infographic_check(saved["file_path"], saved["source_text"], "열람")
                self.assertEqual(checked["total"], 15, [(i["name"], i["evidence"]) for i in checked["items"]
                                                        if not i["passed"]])
                if name != themes.BASE:
                    self.assertIn(themes.THEMES[name]["accent_deep"], saved["source_text"])
                    self.assertNotIn(themes.THEMES[themes.BASE]["accent_deep"], saved["source_text"])

    def test_theme_follows_business_words(self):
        from engineering_agent.infographic import themes
        self.assertEqual(themes.pick({"item_name": "반찬온", "item_summary": "동네 반찬가게"}), "orange")
        self.assertEqual(themes.pick({"item_name": "점검콕", "features": ["설비 점검"]}), "steel")
        self.assertEqual(themes.pick({"item_name": "민원요약AI"}), "violet")
        # 맞는 낱말이 없으면 아이템명으로 정해 다시 만들어도 같은 색
        self.assertEqual(themes.pick({"item_name": "무명"}), themes.pick({"item_name": "무명"}))

    def test_onepage_code_score_and_missing_fields(self):
        saved = self._render_onepage()
        checked = compute_infographic_check(
            saved["file_path"], saved["source_text"], "열람하고 인쇄하세요"
        )
        self.assertEqual(len(checked["items"]), 8)
        six = checked["items"][1]
        self.assertEqual((six["name"], six["passed"], six["earned"]), ("핵심 정보 6항목", True, 3))
        self.assertEqual(checked["total"], 15, checked["items"])
        # 파일과 원문이 어긋나면 통과 필수 조건 실패 — 30점 전체가 0
        altered = saved["source_text"].replace("월 10000원", "")
        broken = compute_infographic_check(saved["file_path"], altered, "열람하고 인쇄하세요")
        self.assertEqual(broken["total"], 0)
        self.assertIn("원문 불일치", broken["gate_failures"][0])

    def test_onepage_truncated_value_loses_points(self):
        saved = self._render_onepage(problem="주문 대기 " * 40)
        items = compute_infographic_check(saved["file_path"], saved["source_text"],
                                          "열람하고 인쇄하세요")["items"]
        self.assertFalse(items[4]["passed"])
        self.assertIn("problem", items[4]["evidence"])

    def test_feature_match_needs_handler_on_that_element(self):
        """화면 문구 + 그 요소에 직접 붙은 핸들러가 있어야 기능을 인정한다."""
        base = """<html><body><!-- IMPLEMENTED_FEATURES: 주문 조회 -->
        {body}<script>{script}</script></body></html>"""
        button = '<button id="order" data-feature="주문 조회">주문 조회</button>'
        other = '<button id="help">도움말</button>'
        cases = {
            "주석 자기 신고와 화면 문구만": ("<p>주문 조회</p>", "console.log('ready')", False),
            "버튼은 있는데 핸들러 없음": (button, "console.log('ready')", False),
            # 예전 판정은 이 경우를 통과시켰다: id가 스크립트에 문자열로 있고
            # addEventListener가 어딘가에 한 번 있으면 연결로 쳤다.
            "리스너가 다른 버튼에 붙음": (
                button + other,
                "const ids = ['order']; document.getElementById('help')"
                ".addEventListener('click', () => {})", False),
            "직접 연결": (button, "document.getElementById('order')"
                                 ".addEventListener('click', () => {})", True),
            "변수로 받아 연결": (button, "const b = document.getElementById('order');"
                                       " b.addEventListener('click', () => {})", True),
            "인라인 onclick": ('<button onclick="run()">주문 조회</button>', "", True),
            # getElementById를 감싸기만 한 도우미 함수는 직접 연결과 같다.
            "화살표 도우미 $": (button, "const $ = id => document.getElementById(id);"
                                     " $('order').addEventListener('click', () => {})", True),
            "function 도우미를 변수로": (
                button, "function byId(id) { return document.getElementById(id); }"
                        " const b = byId('order'); b.onclick = () => {};", True),
            "도우미가 다른 버튼에 붙음": (
                button + other, "const $ = id => document.getElementById(id);"
                                " $('help').addEventListener('click', () => {})", False),
            # 인자를 그대로 넘기지 않는 함수는 도우미로 보지 않는다.
            "도우미 아닌 함수": (button, "const $ = id => document.getElementById('help');"
                                        " $('order').addEventListener('click', () => {})", False),
        }
        for label, (body, script, expected) in cases.items():
            with self.subTest(label):
                result = match_features(["주문 조회"], base.format(body=body, script=script), "html")
                self.assertEqual(result["score"], 15.0 if expected else 0.0, result["findings"])

    def test_html_items_catch_dead_buttons_broken_refs_and_placeholders(self):
        page = _page(
            '<button id="a">주문</button><button id="b">취소</button>'
            "<p>Lorem ipsum dolor</p>"
            "<script>document.getElementById('a').addEventListener('click', () => {"
            " document.getElementById('result').textContent = 'ok'; });</script>")
        items = {i["id"]: i for i in check_html(page)}
        self.assertAlmostEqual(items[1]["earned"], 1.0)  # 버튼 2개 중 1개만 연결 — 50% 구간
        self.assertIn("취소", items[1]["evidence"])
        self.assertFalse(items[7]["passed"])             # #result 는 문서에 없음
        self.assertIn("result", items[7]["evidence"])
        self.assertFalse(items[8]["passed"])             # lorem ipsum

        # 도우미 함수로 찾는 id도 끊어진 참조 검사 대상이다.
        helper = _page('<button id="a">주문</button>'
                       "<script>const $ = id => document.getElementById(id);"
                       " $('a').addEventListener('click', () => { $('gone').textContent = 'ok'; });"
                       "</script>")
        items = {i["id"]: i for i in check_html(helper)}
        self.assertTrue(items[1]["passed"])
        self.assertFalse(items[7]["passed"])
        self.assertIn("gone", items[7]["evidence"])

    def test_html_width_over_1440_fails(self):
        wide = check_html(_page("<p>x</p>", "body{color:#000;background-color:#fff}"
                                            ".wrap{min-width:1920px;max-width:3000px}"))
        self.assertFalse(wide[5]["passed"])
        self.assertIn("1920", wide[5]["evidence"])
        narrow = check_html(_page("<p>x</p>", "body{color:#000;background-color:#fff}"
                                              ".wrap{width:1200px;max-width:3000px}"))
        self.assertTrue(narrow[5]["passed"], narrow[5]["evidence"])

    def test_items_without_targets_are_excluded_not_free(self):
        """input·이미지가 없는 페이지는 그 항목을 빼고 환산한다. 만점으로 치면
        아무것도 안 만들수록 점수가 오른다."""
        page = _page('<button id="go">시작</button>'
                     "<script>document.getElementById('go').addEventListener('click', () => {});"
                     "</script>")
        items = check_html(page)
        excluded = {i["id"] for i in items if not i["applicable"]}
        self.assertEqual(excluded, {2, 3})
        self.assertEqual(items_total(items), 15.0)
        items[0].update(earned=0.0, passed=False)          # 동작 연결 3점을 잃으면
        self.assertAlmostEqual(items_total(items), 15 * 8 / 11, places=2)  # 11점 만점 중 8

    def test_gate_failure_zeroes_code_check(self):
        with TemporaryDirectory(dir=self._TEMP_ROOT) as directory:
            page = _page('<script>const apiKey = "sk-abcdefghijklmnopqrstuvwxyz123456";</script>')
            path = Path(directory) / "index.html"
            path.write_text(page, encoding="utf-8")
            result = compute_code_check(str(path), page, "# 실행 방법")
            self.assertEqual(result["total"], 0.0)
            self.assertFalse(result["passed"])
            self.assertIn("비밀값", result["gate_failures"][0])

    def test_sandbox_split_halting_is_gate_ignored_is_deduction(self):
        """스크립트 전체를 멈추는 스토리지 API만 필수 조건(30점 0)이다. alert() 등
        무시되는 API는 그 동작 하나만 안 되므로 7번 항목에서 감점한다(조율 회신 5-3)."""
        with TemporaryDirectory(dir=self._TEMP_ROOT) as directory:
            path = Path(directory) / "index.html"
            wired = ('<button id="go">시작</button><script>'
                     "document.getElementById('go').addEventListener('click', () => {%s});"
                     "</script>")

            halting = _page(wired % "localStorage.setItem('a', 1)")
            path.write_text(halting, encoding="utf-8")
            result = compute_code_check(str(path), halting, "# 실행 방법")
            self.assertEqual((result["total"], result["gate_codes"]), (0.0, ["sandbox"]))

            ignored = _page(wired % "alert('저장')")
            path.write_text(ignored, encoding="utf-8")
            result = compute_code_check(str(path), ignored, "# 실행 방법")
            self.assertTrue(result["passed"])
            self.assertEqual(result["gate_codes"], [])
            script_item = result["items"][6]
            self.assertEqual(script_item["name"], "스크립트 동작 오류 없음")
            self.assertFalse(script_item["passed"])
            self.assertIn("alert()", script_item["evidence"])
            self.assertLess(result["total"], 15.0)

    def test_gate_codes_are_separate_from_messages(self):
        with TemporaryDirectory(dir=self._TEMP_ROOT) as directory:
            page = _page('<script>const apiKey = "sk-abcdefghijklmnopqrstuvwxyz123456";</script>')
            missing = str(Path(directory) / "none.html")
            result = compute_code_check(missing, page, "# 실행 방법")
            self.assertEqual(result["gate_codes"], ["entry", "secret"])
            self.assertEqual(len(result["gate_failures"]), 2)

    def test_alt_text_reports_which_artifact_is_defective(self):
        """HTML 2번은 index.html과 인포그래픽을 함께 본다. 조율이 재수행 대상을 사유
        문구가 아니라 defect_sources로 가르게 한다(조율 회신 2-2)."""
        good_svg = '<svg xmlns="http://www.w3.org/2000/svg"><title>인포그래픽</title></svg>'
        bad_svg = '<svg xmlns="http://www.w3.org/2000/svg"></svg>'
        good_html, bad_html = _page('<img src="data:," alt="로고">'), _page('<img src="data:,">')
        cases = {
            "둘 다 정상": (good_html, good_svg, []),
            "index.html 결함": (bad_html, good_svg, ["prototype"]),
            "인포그래픽 결함": (good_html, bad_svg, ["infographic"]),
            "둘 다 결함": (bad_html, bad_svg, ["prototype", "infographic"]),
        }
        for label, (html, svg, expected) in cases.items():
            with self.subTest(label):
                self.assertEqual(check_html(html, svg)[1]["defect_sources"], expected)

    def test_missing_readme_warns_without_touching_score(self):
        """README는 조율의 G-04(R-10)가 만든다. R-10은 생성 실패 시 파이프라인을 계속
        진행하게 하므로, README 결함이 산출물 점수를 흔들면 안 된다."""
        with TemporaryDirectory(dir=self._TEMP_ROOT) as directory:
            page = _page('<button id="go">시작</button>'
                         "<script>document.getElementById('go').addEventListener('click', () => {});"
                         "</script>")
            path = Path(directory) / "index.html"
            path.write_text(page, encoding="utf-8")
            with_readme = compute_code_check(str(path), page, "# 실행 방법")
            without = compute_code_check(str(path), page, None)
            self.assertTrue(without["passed"])
            self.assertEqual(without["gate_failures"], [])
            self.assertEqual(without["total"], with_readme["total"])
            self.assertIn("README", without["warnings"][0])
            self.assertEqual(with_readme["warnings"], [])
            # README 안의 문자열은 산출물이 아니므로 비밀값 검사 대상도 아니다
            leaked = compute_code_check(str(path), page, 'token = "sk-abcdefghijklmnopqrstuvwxyz1234"')
            self.assertTrue(leaked["passed"])

    def test_onepage_feature_match_is_judged_against_plan(self):
        source = self._render_onepage()["source_text"]
        ok = match_features(["주문 조회"], source, "svg-onepage", _ONEPAGE_PLAN)
        self.assertEqual(ok["score"], 15.0, ok["findings"])

        # 계획서 원문이 없으면 기능명 비교로 되돌아가지 않는다(자기 채점 방지).
        withheld = match_features(["주문 조회"], source, "svg-onepage", None)
        self.assertEqual(withheld["score"], 0.0)
        self.assertIn("plan_doc", withheld["findings"][0])

        cases = {
            "설명 없음": ([""], "비어 있거나"),
            "기능명 되풀이": (["주문 조회"], "되풀이"),
            "계획서에 없는 내용": (["드론으로 배달 경로를 최적화한다"], "계획서에서 확인"),
            "계획서에 없는 수치": (["주문 상태를 30초마다 보여준다"], "30"),
        }
        for label, (details, reason) in cases.items():
            with self.subTest(label):
                src = self._render_onepage(feature_details=details)["source_text"]
                result = match_features(["주문 조회"], src, "svg-onepage", _ONEPAGE_PLAN)
                self.assertEqual(result["missing_features"], ["주문 조회"])
                self.assertIn(reason, " ".join(result["findings"]))

    def test_onepage_invented_numbers_cost_points(self):
        source = self._render_onepage(revenue_unit_price="월 99000원")["source_text"]
        result = match_features(["주문 조회"], source, "svg-onepage", _ONEPAGE_PLAN)
        self.assertEqual(result["score"], 14.0)
        self.assertIn("99000", result["findings"][-1])

    def test_html_generation_uses_tools_and_returns_source(self):
        tools = _Tools(
            "```html:index.html\n<!doctype html><html lang=\"ko\"><body>작동</body></html>\n```"
        )
        with TemporaryDirectory(dir=self._TEMP_ROOT) as directory:
            with patch("engineering_agent.builder_html.save_files") as write:
                write.side_effect = lambda files, run_id: save_files(files, run_id, Path(directory))
                result = build_prototype_html(["조회"], {"item_name": "테스트"},
                                              "웹개발", "생성", tools)
            self.assertEqual(result["status"], "success")
            self.assertIsNone(result["readmePath"])
            self.assertEqual(Path(result["entryFilePath"]).read_text(encoding="utf-8"),
                             result["sourceText"])
            self.assertEqual(result["implementedFeatures"], [])
            self.assertEqual(tools.kwargs["purpose"], "T-B1 HTML 생성")

    def test_infographic_extraction_reads_wrapped_json(self):
        """실제 tools는 schema=를 받으면 응답 전체를 순수 JSON으로 검사한다. 모델이
        코드블록이나 설명을 붙여도 산출물이 나오도록 추출은 parse=로 직접 읽는다."""
        body = _json(item_name="테스트", features=["조회"])
        for label, reply in (("순수 JSON", body),
                             ("코드블록", f"```json\n{body}\n```"),
                             ("앞뒤 설명", f"추출 결과입니다.\n{body}\n이상입니다.")):
            with self.subTest(label):
                tools = _Tools(reply)
                result = infographic.generate_infographic_content("웹개발", "본문", tools)
                self.assertEqual(result["features"], ["조회"])
                self.assertIsNone(tools.kwargs["schema"])
        # 읽을 수 없는 응답은 tools가 재시도하도록 FormatError를 올린다.
        for label, reply in (("JSON 없음", "죄송합니다"), ("잘린 JSON", '{"item_name": "t"'),
                             ("필수 값 없음", '{"features": ["조회"]}')):
            with self.subTest(label), _stub_sbrain_errors():
                with self.assertRaises(_FakeFormatError):
                    infographic.generate_infographic_content("웹개발", "본문", _Tools(reply))

    def test_unusable_llm_response_raises_instead_of_reporting_failure(self):
        """빈 응답·코드블록 0개는 품질 실패가 아니라
        호출 실패이므로 FormatError를 올려 tools가 재시도하게 한다."""
        for label, response in (("빈 응답", ""), ("코드블록 없음", "죄송합니다. 만들 수 없습니다."),
                                ("공백만", "   \n  ")):
            with self.subTest(label), _stub_sbrain_errors():
                with self.assertRaises(_FakeFormatError):
                    build_prototype_html(["조회"], {"item_name": "t"}, "웹개발", "생성",
                                         _Tools(response))

    def test_gate_violation_reports_failure_without_raising(self):
        """코드는 왔는데 게이트를 위반한 경우는 예외가 아니라 status='failed'다
        (재수행은 Supervisor 몫)."""
        wrong_name = _Tools("```html:main.html\n<html lang=\"ko\"></html>\n```")
        result = build_prototype_html(["조회"], {"item_name": "t"}, "웹개발", "생성", wrong_name)
        self.assertEqual(result["status"], "failed")
        self.assertIn("E-B1-ENTRY", result["summary"])

        external = _Tools(
            '```html:index.html\n<html lang="ko"><head>'
            '<script src="https://cdn.example.com/x.js"></script></head></html>\n```'
        )
        result = build_prototype_html(["조회"], {"item_name": "t"}, "웹개발", "생성", external)
        self.assertEqual(result["status"], "failed")
        self.assertIn("E-B1-DEP", result["summary"])

    def test_dependency_gate_sees_css_urls_and_quoted_imports(self):
        """CSS 안에서 외부 파일을 불러오는 꼴도 막는다. data: 주소 · 상대 경로 · 본문 글은 걸리지 않는다."""
        for html in ('<style>@import "https://fonts.example.com/a.css";</style>',
                     "<style>@import url('//cdn.example.com/b.css');</style>",
                     "<style>.hero{background:url(https://img.example.com/c.png) no-repeat}</style>",
                     '<style>@font-face{font-family:X;src:url("https://f.example.com/x.woff2")}</style>',
                     '<div style="background-image:url(\'https://img.example.com/d.png\')"></div>'):
            with self.subTest(html=html[:40]):
                ok, violations = gates.check_external_dependency_gate(html)
                self.assertFalse(ok)
                self.assertEqual(len(violations), 1, violations)
        for html in ("<style>.a{background:url(data:image/png;base64,AAAA)}</style>",
                     "<style>.a{background:url('./bg.png')}</style>",
                     '<div style="color:#111">url(https://example.com)는 본문 글이다</div>',
                     "<p>@import \"https://x.example.com/a.css\"</p>"):
            with self.subTest(html=html[:40]):
                self.assertEqual(gates.check_external_dependency_gate(html), (True, []))

    def test_sandbox_gate_blocks_apis_that_die_in_iframe(self):
        """프론트가 sandbox="allow-scripts" iframe에 띄우므로 스토리지·모달·submit은
        동작을 깨뜨린다. 프롬프트 지시만으로 두지 않고 게이트로 막는다."""
        cases = {
            "localStorage": "<script>localStorage.setItem('a', 1);</script>",
            "sessionStorage": "<script>window.sessionStorage.clear();</script>",
            "document.cookie": "<script>document.cookie = 'a=1';</script>",
            "alert()": "<script>alert('저장했습니다');</script>",
            "confirm()": '<button onclick="confirm(\'삭제할까요\')">삭제</button>',
            "window.open()": "<script>window.open('/next');</script>",
            "페이지 이동(location)": "<script>location.href = '/next';</script>",
            "form.submit()": "<script>document.forms[0].submit();</script>",
        }
        for label, snippet in cases.items():
            with self.subTest(label):
                ok, violations = gates.check_sandbox_api_gate(
                    f'<html lang="ko"><body>{snippet}</body></html>')
                self.assertFalse(ok)
                self.assertIn(label, violations)

        # 본문 글에 같은 낱말이 섞여도 오탐하지 않는다 (script 블록·on* 속성만 본다)
        prose = ('<html lang="ko"><body><p>저장 버튼을 누르면 alert(경고) 없이 '
                 'localStorage 대신 메모리에 담깁니다</p>'
                 '<script>const state = {};</script></body></html>')
        ok, violations = gates.check_sandbox_api_gate(prose)
        self.assertTrue(ok, violations)

    def test_sandbox_gate_ignores_same_named_properties_and_declarations(self):
        """전역 함수 · 전역 location만 막는다. 민원 '위치'를 담는 summary.location = …,
        모달 객체의 modal.open(), 같은 이름의 함수 · 메서드 정의는 sandbox와 무관하다.
        생성 쪽(E-B1-SANDBOX)과 채점 쪽(코드 점검 7번)이 같은 기준인지도 함께 본다."""
        from verification_agent.rules.gates import ignored_apis

        allowed = [
            "summary.location = '서울시 중구';",
            "const location = form.value;",
            "let location = '';",
            "if (location == null) {}",
            "modal.open();",
            "this.confirm('예');",
            "function open(id) { show(id); }",
            "const ui = { open() { show(); } };",
            "class Dialog { alert(msg) { this.msg = msg; } }",
            "buildPrompt('질문');",
        ]
        for code in allowed:
            with self.subTest(code=code):
                html = f'<html lang="ko"><body><script>{code}</script></body></html>'
                self.assertEqual(gates.check_sandbox_api_gate(html), (True, []))
                self.assertEqual(ignored_apis(html), [])

        blocked = {
            "location = '/next';": "페이지 이동(location)",
            "window.location.href = '/next';": "페이지 이동(location)",
            "document.location = '/next';": "페이지 이동(location)",
            "window.open('/next');": "window.open()",
            "open('/next');": "window.open()",
            "if (confirm('삭제할까요')) { remove(); }": "confirm()",
            "prompt('이름');": "prompt()",
        }
        for code, label in blocked.items():
            with self.subTest(code=code):
                html = f'<html lang="ko"><body><script>{code}</script></body></html>'
                ok, violations = gates.check_sandbox_api_gate(html)
                self.assertFalse(ok)
                self.assertIn(label, violations)
                self.assertIn(label, ignored_apis(html))

    def test_secret_gate_matches_the_scoring_rule(self):
        """하드코딩된 비밀값은 검증-2의 통과 필수 조건(산출물층 0)이다. 넘기기 전에 같은 기준으로 거른다."""
        from verification_agent.rules.gates import find_secret

        key = "sk-proj-" + "Ab3dEf6hIj9kLm2nOp5q"
        caught = [f'const OPENAI_KEY = "{key}";',
                  "const user = { id: 'demo', password: 'demo1234' };",
                  'headers: { apiKey: "q9w8e7r6t5y4" }']
        for code in caught:
            with self.subTest(code=code[:30]):
                ok, found = gates.check_secret_gate(f"<script>{code}</script>")
                self.assertFalse(ok)
                self.assertIsNotNone(find_secret(f"<script>{code}</script>"))
                # 실패 사유에는 앞 8자만 — 값 전체가 지시문 · 로그로 새지 않는다
                self.assertLessEqual(len(found), 9)
                self.assertNotIn(key, found)

        passed = ['const API_KEY = "your_api_key";', "password: 'dummy-pass'", "token: '{{TOKEN}}'",
                  '<img alt="그림" src="data:image/png;base64,' + "A" * 200 + '">',
                  "<p>비밀번호를 입력하세요</p>"]
        for code in passed:
            with self.subTest(code=code[:30]):
                self.assertEqual(gates.check_secret_gate(code), (True, ""))
                self.assertIsNone(find_secret(code))

    def test_secret_reported_as_gate_failure_without_saving(self):
        tools = _Tools('```html:index.html\n<html lang="ko"><body>'
                       "<script>const login = { password: 'demo1234' };</script>"
                       "</body></html>\n```")
        result = build_prototype_html(["조회"], {"item_name": "t"}, "웹개발", "생성", tools)
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["entryFilePath"])
        self.assertIn("E-B1-SECRET", result["summary"])
        self.assertNotIn("demo1234", result["summary"])
        self.assertIn("demo1234", result["sourceText"])   # 재수행 때 고칠 원문은 돌려준다

    def test_sandbox_violation_reported_as_gate_failure(self):
        tools = _Tools('```html:index.html\n<html lang="ko"><body>'
                       "<script>localStorage.setItem('x', 1);</script>"
                       "</body></html>\n```")
        result = build_prototype_html(["조회"], {"item_name": "t"}, "웹개발", "생성", tools)
        self.assertEqual(result["status"], "failed")
        self.assertIn("E-B1-SANDBOX", result["summary"])
        self.assertEqual(result["gate_failures"]["sandbox"], ["localStorage"])

    def test_file_save_failure_propagates(self):
        """R3 — 우리 코드 문제(저장 실패)는 None이나 빈 경로가 아니라 예외로 올린다."""
        tools = _Tools('```html:index.html\n<html lang="ko"><body>x</body></html>\n```')
        with patch("engineering_agent.builder_html.save_files") as write:
            write.side_effect = OSError("디스크 쓰기 실패")
            with self.assertRaises(OSError):
                build_prototype_html(["조회"], {"item_name": "t"}, "웹개발", "생성", tools)

    def test_feature_match_score_is_proportional(self):
        """15 × 인정/전체. 예전 max(0, 15 - 4 × 누락)은 기능 1개를 안 만들면 11점,
        10개 중 6개를 만들면 0점으로 뒤집혔다."""
        html = """<html lang="ko"><body>
        <button id="a" data-feature="주문 조회">주문 조회</button>
        <button id="b" data-feature="주문 등록">주문 등록</button>
        <script>
        document.getElementById('a').addEventListener('click', () => {});
        document.getElementById('b').addEventListener('click', () => {});
        </script></body></html>"""
        result = match_features(["주문 조회", "주문 등록", "결제", "배송"], html, "html")
        self.assertEqual(result["missing_features"], ["결제", "배송"])
        self.assertEqual(result["score"], 7.5)
        self.assertEqual(match_features(["결제"], html, "html")["score"], 0.0)
        many = [f"기능{i}" for i in range(4)] + ["주문 조회", "주문 등록"]
        self.assertEqual(match_features(many, html, "html")["score"], 5.0)

    def test_contrast_skips_transparent_background(self):
        """투명 배경 짝은 대비를 계산할 수 없어 판정 대상에서 빠진다(감점하지 않는다)."""
        def contrast(css):
            return check_contrast(parse_page(f"<html><head><style>{css}</style></head></html>"))
        mixed = contrast("body{color:#0f172a;background-color:#fff}"
                         ".tag{color:#fff;background-color:transparent}"
                         ".chip{color:#fff;background-color:rgba(0,0,0,0)}")
        self.assertTrue(mixed["passed"], mixed["evidence"])
        self.assertIn("1쌍", mixed["evidence"])
        # 투명 짝만 있으면 판정 대상 0개 → 미충족
        self.assertFalse(contrast(".tag{color:#fff;background-color:transparent}")["passed"])

    def test_contrast_reads_background_shorthand(self):
        """background 단축 속성만 쓴 산출물이 '판정 대상 0개'로 미통과가 되지 않는다."""
        def contrast(css):
            return check_contrast(parse_page(f"<html><head><style>{css}</style></head></html>"))
        passing = contrast("body{background:#fff;color:#0f172a}")
        self.assertTrue(passing["passed"], passing["evidence"])
        self.assertFalse(contrast("body{background:#fff;color:#cccccc}")["passed"])
        # 색 하나로 환원되지 않는 배경은 판정 밖에 둔다
        gradient = contrast("body{background:linear-gradient(#fff,#eee);color:#111}")
        self.assertIn("판정 대상 0개", gradient["evidence"])

    def test_onepage_partial_credit_is_reachable(self):
        """6항목 중 하나가 비어도 SVG는 렌더링되고 2번이 부분 점수를 받는다 —
        파일을 안 만들면 통과 필수 조건 실패로 30점 전체가 0이 된다."""
        saved = self._render_onepage(revenue_unit_price="")
        checked = compute_infographic_check(
            saved["file_path"], saved["source_text"], "열람하고 인쇄하세요"
        )
        self.assertTrue(checked["passed"])
        self.assertFalse(checked["items"][1]["passed"])
        self.assertAlmostEqual(checked["items"][1]["earned"], 2.0, places=3)  # 5/6 — 80% 구간
        self.assertAlmostEqual(checked["total"], 14.0)

    def test_webdev_flow_stays_inside_svg(self):
        data = {"item_name": "테스트", "features": ["조회"],
                "flow_steps": ["탐색", "선택", "결제", "확인"]}
        with TemporaryDirectory(dir=self._TEMP_ROOT) as directory:
            with patch.object(infographic_render, "_OUTPUT_DIR", Path(directory)):
                saved = infographic.render_infographic("웹개발", data)
        root = ET.fromstring(saved["source_text"])
        widths = [float(node.get("x", 0)) + float(node.get("width", 0))
                  for node in root.iter() if node.tag.endswith("}rect")]
        self.assertLessEqual(max(widths), 900)
