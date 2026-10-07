"""tasks.py의 세 진입 함수를 계약 모델로 실제 실행하는 테스트.

`sbrain`이 이 저장소에 없어 지금까지 run_tb1 · run_tb2 · run_tv2가 한 번도 실행되지
않았다. 계약 경계에서 생기는 문제(점수 조립, 원페이지 분기, 파일 보존)가 전부 그
파일에 있으므로 대역 모듈(tests/fake_sbrain.py)을 꽂아 실행한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests import fake_sbrain  # noqa: E402

_PATCHER = None


def setUpModule():
    global _PATCHER
    _PATCHER = fake_sbrain.install()


def tearDownModule():
    if _PATCHER is not None:
        _PATCHER.stop()


def _json(**fields) -> str:
    """모델이 돌려주는 JSON 응답 문자열(인포그래픽 추출)."""
    return json.dumps(fields, ensure_ascii=False)


class _Tools:
    """tools.llm 계약 중 이 패키지가 쓰는 부분만 재현한다."""

    def __init__(self, response):
        self._response = response
        self.kwargs = None

    def llm(self, messages, *, schema=None, parse=None, purpose=""):
        self.kwargs = {"schema": schema, "parse": parse, "purpose": purpose}
        value = self._response(schema) if callable(self._response) else self._response
        return parse(value) if parse is not None else value


def _item_spec(**over):
    from sbrain.models import ItemSpec

    return ItemSpec(**{
        "item_name": "동네 주문", "one_line_summary": "동네 매장 주문 중개",
        "target_customer": "동네 매장", "core_features": ["주문 조회"],
        "category": "원페이지", "keywords": ["주문"], **over,
    })


def _plan_doc(sentences: list[str], feature_list: list[str]):
    from sbrain.models import PlanDoc, PlanSection, Sentence

    section = PlanSection(
        section_code="1-1", title="문제 인식",
        sentences=[Sentence(sentence_id=f"s{i}", text=t, is_title=False, paragraph_no=1)
                   for i, t in enumerate(sentences)],
    )
    return PlanDoc(sections=[section], feature_list=feature_list,
                   charts=[], tables=[], protected_tokens=[])


_HTML = """```html:index.html
<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<!-- IMPLEMENTED_FEATURES: 주문 조회 -->
<style>body{{color:#0F172A;background-color:#FFFFFF}}</style>
</head><body>
<h1>동네 주문</h1><h2>주문 조회</h2>
<label for="q">검색</label><input id="q" type="text">
<button id="b-order" data-feature="주문 조회">주문 조회</button>
<script>document.getElementById('b-order').addEventListener('click', () => {{}});</script>
</body></html>
```""".replace("{{", "{").replace("}}", "}")


class ContractTaskTests(TestCase):
    _OUTPUT = Path(__file__).resolve().parents[1] / "engineering_agent" / "output"

    def test_run_tb1_fills_contract_and_preserves_file(self):
        from engineering_agent.tasks import run_tb1
        from sbrain.contracts.tasks import TB1In

        inp = TB1In(feature_list=["주문 조회"], item_spec=_item_spec(category="웹개발"),
                    category="웹개발", instruction="만들어라")
        with TemporaryDirectory(dir=self._OUTPUT) as directory:
            with patch("engineering_agent.builder_html.save_files") as write:
                from engineering_agent.file_writer import save_files
                write.side_effect = lambda files, run_id: save_files(
                    files, run_id, Path(directory))
                out = run_tb1(inp, _Tools(_HTML))
            self.assertTrue(out.check.passed, out.check.failures)
            self.assertEqual(out.prototype.kind, "html")
            self.assertEqual(out.implemented_features, ["주문 조회"])
            self.assertEqual(Path(out.entry_file_path).read_text(encoding="utf-8"),
                             out.prototype.source_text)
            self.assertIsNone(out.prototype.readme_path)  # README는 G-04 몫

    def test_run_tb1_reports_gate_failure_without_losing_contract(self):
        from engineering_agent.tasks import run_tb1
        from sbrain.contracts.tasks import TB1In

        inp = TB1In(feature_list=["주문 조회"], item_spec=_item_spec(category="웹개발"),
                    category="웹개발", instruction="만들어라")
        out = run_tb1(inp, _Tools("```html:wrong.html\n<html lang=\"ko\"></html>\n```"))
        self.assertFalse(out.check.passed)
        self.assertIn("E-B1-ENTRY", out.check.failures[0])
        self.assertEqual(out.entry_file_path, "")

    def test_run_tb1_propagates_tool_exhaustion(self):
        """완전실패 — tools가 소진 예외를 올리면 Task가 삼키지 않고 그대로 올린다."""
        from engineering_agent.tasks import run_tb1
        from sbrain.contracts.tasks import TB1In
        from sbrain.orchestrator.errors import ToolCallExhausted

        class Exhausted:
            def llm(self, messages, **kwargs):
                raise ToolCallExhausted(error="응답지연", error_kind="일시", tries=3)

        inp = TB1In(feature_list=["주문 조회"], item_spec=_item_spec(category="웹개발"),
                    category="웹개발", instruction="만들어라")
        with self.assertRaises(ToolCallExhausted):
            run_tb1(inp, Exhausted())

    def test_run_tb2_passes_text_failure_up_but_not_image_failure(self):
        """조율 규칙: T-B2만 이미지 호출 실패를 받아 기본 아이콘으로 계속한다. 글 호출 실패는 올린다."""
        from engineering_agent.infographic import artsheet
        from engineering_agent.tasks import run_tb2
        from sbrain.contracts.tasks import TB2In
        from sbrain.orchestrator.errors import ToolCallExhausted

        class TextFails:
            def llm(self, messages, **kwargs):
                raise ToolCallExhausted(error="응답지연", error_kind="일시", tries=5)

            def image(self, prompt, **kwargs):
                raise AssertionError("글 호출이 실패하면 그림까지 가지 않는다")

        inp = TB2In(plan_doc=_plan_doc(["주문 조회는 매장별 주문 상태를 보여준다."], ["주문 조회"]),
                    item_spec=_item_spec(category="원페이지"), category="원페이지", instruction="만들어라")
        with self.assertRaises(ToolCallExhausted):
            run_tb2(inp, TextFails())

        class ImageFails:
            def image(self, prompt, **kwargs):
                raise ToolCallExhausted(error="호출실패", error_kind="운영", tries=1)

        self.assertIsNone(artsheet.generate("원페이지", {"features": ["주문 조회"]}, ImageFails()))

    def _run_tb2(self, category, extracted, sentences, feature_list=("주문 조회",)):
        from engineering_agent.infographic import render as infographic_render
        from engineering_agent.tasks import run_tb2
        from sbrain.contracts.tasks import TB2In

        inp = TB2In(plan_doc=_plan_doc(list(sentences), list(feature_list)),
                    item_spec=_item_spec(category=category), category=category,
                    instruction="만들어라")
        tools = _Tools(lambda _: _json(**extracted))
        directory = TemporaryDirectory(dir=self._OUTPUT)
        with patch.object(infographic_render, "_OUTPUT_DIR", Path(directory.name)):
            out = run_tb2(inp, tools)
        self.addCleanup(directory.cleanup)
        return out

    def test_run_tb2_onepage_emits_file_even_when_check_fails(self):
        """검사에 걸려도 산출물은 나온다 — 안 내보내면 산출물층 30점 전체를 잃는다."""
        out = self._run_tb2(
            "원페이지",
            {"item_name": "동네 주문", "features": ["주문 조회"], "problem": "주문 대기",
             "solution": "빠른 주문", "revenue_unit_price": "", "timeline_baseline": ""},
            ["주문 대기가 길다", "빠른 주문으로 줄인다"],
        )
        self.assertFalse(out.check.passed)
        self.assertIn("수익모델 단가 누락", out.check.failures)
        self.assertIn("추진 일정 기준선 누락", out.check.failures)
        self.assertTrue(Path(out.infographic.image_path).is_file())
        self.assertEqual(Path(out.infographic.image_path).name, "onepage.svg")
        self.assertTrue(out.infographic.alt_text)

    def test_run_tb2_flags_numbers_absent_from_plan(self):
        """도식 수치 불일치 — 계획서에 없는 숫자는 지어낸 값이다."""
        out = self._run_tb2(
            "원페이지",
            {"item_name": "동네 주문", "features": ["주문 조회"], "problem": "주문 대기 15분",
             "solution": "빠른 주문", "revenue_unit_price": "월 99000원",
             "timeline_baseline": "2026-12-01"},
            ["주문 대기가 15분이다", "2026-12-01 착수", "단가는 월 10000원"],
        )
        joined = " ".join(out.check.failures)
        self.assertIn("99000", joined)
        self.assertNotIn("15", joined.replace("99000", ""))

    def test_run_tb2_webdev_and_ai_api_check_their_own_shape(self):
        webdev = self._run_tb2(
            "웹개발", {"item_name": "동네 주문", "features": ["주문 조회"], "flow_steps": []},
            ["주문 흐름"],
        )
        self.assertIn("사용자 화면 흐름 누락", webdev.check.failures)

        ai = self._run_tb2(
            "AI_API",
            {"item_name": "동네 주문", "features": ["주문 조회"],
             "pipeline": {"input": "사진", "process": "", "output": "결과"}},
            ["사진을 넣으면 결과가 나온다"],
        )
        self.assertIn("처리 단계 누락", ai.check.failures)

    def test_run_tv2_assembles_artifact_score(self):
        from engineering_agent.infographic import render as infographic_render
        from engineering_agent.tasks import run_tb2
        from engineering_agent.file_writer import save_files
        from sbrain.contracts.tasks import TB2In, TV2In
        from sbrain.models import Prototype
        from verification_agent.tasks import run_tv2

        sentences = ["주문 대기가 길다", "빠른 주문으로 줄인다", "단가는 월 10000원",
                     "2026-12-01 착수", "동네 매장 대상"]
        with TemporaryDirectory(dir=self._OUTPUT) as directory:
            inp = TB2In(plan_doc=_plan_doc(sentences, ["주문 조회"]),
                        item_spec=_item_spec(category="웹개발"),
                        category="웹개발", instruction="만들어라")
            with patch.object(infographic_render, "_OUTPUT_DIR", Path(directory)):
                tb2 = run_tb2(inp, _Tools(lambda _: _json(
                    item_name="동네 주문", features=["주문 조회"],
                    flow_steps=["탐색", "주문"])))

            html = _HTML.split("\n", 1)[1].rsplit("```", 1)[0].rstrip("\n")
            saved = save_files({"index.html": html}, "tv2-run", Path(directory))
            readme = Path(directory) / "README.md"
            readme.write_text("# 실행 방법\n브라우저로 열어 확인하세요.", encoding="utf-8")

            prototype = Prototype(
                entry_file_path=saved["index.html"], kind="html", source_text=html,
                asset_paths=[], readme_path=str(readme), implemented_features=["주문 조회"],
            )
            out = run_tv2(TV2In(prototype=prototype, infographic=tb2.infographic,
                                feature_list=["주문 조회", "결제"]), _Tools(""))

        self.assertEqual(len(out.code_check.checks), 8)
        self.assertEqual(out.code_check.total, 15.0,
                         [(c.no, c.name, c.passed, c.detail) for c in out.code_check.checks])
        self.assertEqual(out.feature_match.judged_by, "htmlParse")
        self.assertEqual(out.feature_match.missing_features, ["결제"])
        self.assertEqual(out.feature_match.score, 7.5)  # 15 × 1/2
        self.assertAlmostEqual(out.artifact_score.total, 22.5)
        # README 있음 · 신고한 기능은 파싱으로 확인됨. 가짜 LLM이 빈 답을 내 판정 실패만 남는다.
        self.assertEqual(out.diagnostics, ["대조 LLM 판정 실패 1건 — 규칙 판정으로 대체: 주문 조회"])

    def _run_onepage_tv2(self, *, with_plan: bool, detail: str):
        from engineering_agent.infographic import render as infographic_render
        from engineering_agent.tasks import run_tb2
        from sbrain.contracts.tasks import TB2In, TV2In
        from sbrain.models import Prototype
        from verification_agent.tasks import run_tv2

        sentences = ["주문 대기가 길다", "빠른 주문으로 줄인다", "단가는 월 10000원",
                     "2026-12-01 착수", "주문 조회는 매장별 주문 상태를 한 화면에 보여준다"]
        plan = _plan_doc(sentences, ["주문 조회"])
        with TemporaryDirectory(dir=self._OUTPUT) as directory:
            inp = TB2In(plan_doc=plan, item_spec=_item_spec(), category="원페이지",
                        instruction="만들어라")
            with patch.object(infographic_render, "_OUTPUT_DIR", Path(directory)):
                tb2 = run_tb2(inp, _Tools(lambda _: _json(
                    item_name="동네 주문", features=["주문 조회"], target_users="동네 매장",
                    problem="주문 대기가 길다", solution="빠른 주문으로 줄인다",
                    revenue_unit_price="월 10000원", timeline_baseline="2026-12-01",
                    feature_details=[{"name": "주문 조회", "detail": detail}])))

            svg_path = Path(tb2.infographic.image_path)
            source = svg_path.read_text(encoding="utf-8")
            readme = Path(directory) / "README.md"
            readme.write_text("열람 방법과 인쇄 방법", encoding="utf-8")

            prototype = Prototype(
                entry_file_path=str(svg_path), kind="svg-onepage", source_text=source,
                asset_paths=[], readme_path=str(readme), implemented_features=[],
            )
            out = run_tv2(TV2In(prototype=prototype, infographic=tb2.infographic,
                                feature_list=["주문 조회"],
                                plan_doc=plan if with_plan else None), _Tools(""))
        return tb2, out

    def test_run_tv2_onepage_uses_svg_checklist(self):
        tb2, out = self._run_onepage_tv2(with_plan=True, detail="매장별 주문 상태를 한 화면에 보여준다")
        self.assertTrue(tb2.check.passed, tb2.check.failures)
        self.assertEqual(len(out.code_check.checks), 8)
        self.assertEqual(out.code_check.checks[1].name, "핵심 정보 6항목")
        self.assertEqual(out.code_check.total, 15.0,
                         [(c.no, c.name, c.passed, c.detail) for c in out.code_check.checks])
        self.assertEqual(out.feature_match.judged_by, "svgTextParse")
        self.assertEqual(out.feature_match.score, 15.0, out.feature_match.findings)
        self.assertEqual(out.artifact_score.total, 30.0)

    def test_run_tv2_onepage_without_plan_doc_is_not_self_graded(self):
        """지금의 실계약(TV2In에 plan_doc 없음) 그대로면 원페이지 대조는 0점이다.
        기능명은 T-B2가 목록을 옮겨 적은 것이라 이름만 보면 항상 만점이 난다."""
        _, out = self._run_onepage_tv2(with_plan=False, detail="매장별 주문 상태를 한 화면에 보여준다")
        self.assertEqual(out.code_check.total, 15.0)
        self.assertEqual(out.feature_match.score, 0.0)
        self.assertIn("plan_doc", out.feature_match.findings[0])

    def test_run_tb2_onepage_flags_missing_feature_detail(self):
        tb2, out = self._run_onepage_tv2(with_plan=True, detail="")
        self.assertIn("기능 설명(주문 조회) 누락", tb2.check.failures)
        self.assertEqual(out.feature_match.missing_features, ["주문 조회"])

    def test_run_tv2_fills_flow_fields(self):
        """조율이 흐름을 가르는 두 값(확장 필드)이 계약 결과에 문자열 밖으로 실린다."""
        from sbrain.contracts.tasks import TV2In
        from sbrain.models import Infographic, Prototype
        from verification_agent.tasks import run_tv2

        with TemporaryDirectory(dir=self._OUTPUT) as directory:
            svg = Path(directory) / "infographic.svg"
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><title>x</title></svg>',
                           encoding="utf-8")
            prototype = Prototype(entry_file_path=str(Path(directory) / "none.html"), kind="html",
                                  source_text="<html></html>", asset_paths=[],
                                  implemented_features=[])
            out = run_tv2(TV2In(prototype=prototype,
                                infographic=Infographic(image_path=str(svg), format="svg",
                                                        alt_text="다른 문장"),
                                feature_list=["주문 조회"]), _Tools(""))
        self.assertEqual(out.code_check.gate_failures, ["entry"])
        self.assertEqual(out.artifact_score.total, 0.0)

        with TemporaryDirectory(dir=self._OUTPUT) as directory:
            html = _HTML.split("\n", 1)[1].rsplit("```", 1)[0].rstrip("\n")
            entry = Path(directory) / "index.html"
            entry.write_text(html, encoding="utf-8")
            svg = Path(directory) / "infographic.svg"
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><title>x</title></svg>',
                           encoding="utf-8")
            prototype = Prototype(entry_file_path=str(entry), kind="html", source_text=html,
                                  asset_paths=[], implemented_features=[])
            out = run_tv2(TV2In(prototype=prototype,
                                infographic=Infographic(image_path=str(svg), format="svg",
                                                        alt_text="다른 문장"),
                                feature_list=["주문 조회"]), _Tools(""))
        alt = out.code_check.checks[1]
        self.assertEqual(out.code_check.gate_failures, [])
        self.assertFalse(alt.passed)
        self.assertEqual(alt.defect_sources, ["infographic"])


class CodeCheckDetailTests(TestCase):
    """계약에는 얻은 점수 칸이 없다. 부분 점수가 화면에 '미통과'로만 보이지 않게 근거 앞에 적는다."""

    def test_detail_starts_with_earned_points(self):
        from verification_agent.rules.items import item
        from verification_agent.tasks import _detail

        partial = item(1, "동작 연결", 3, False, "조작 요소 8/10개 연결", earned=2)
        self.assertEqual(_detail(partial), "2/3점 — 조작 요소 8/10개 연결")
        self.assertEqual(_detail(item(5, "제목 계층", 1, True, "h1 1개")), "1/1점 — h1 1개")
        self.assertEqual(_detail(item(4, "명도 대비", 2, False, "대비 3.1:1")), "0/2점 — 대비 3.1:1")
        na = item(3, "입력칸 label", 2, True, "입력칸 0개", applicable=False)
        self.assertTrue(_detail(na).startswith("해당 없음"))


class DiagnosticsTests(TestCase):
    """TV2Out.diagnostics(관리자 진단 기록): 통과 필수 조건 실패 사유 · README 확인 결과 · 대조 LLM 실패 ·
    자기 신고와 파싱 결과의 차이. 점수에는 쓰지 않는다."""

    def _raw(self, **kw):
        raw = {"passed": True, "gate_failures": [], "warnings": []}
        raw.update(kw)
        return raw

    def _feature(self, missing=(), withheld=False):
        return {"missing_features": list(missing), "withheld": withheld}

    def test_collects_the_four_kinds(self):
        from verification_agent.tasks import diagnostics_of

        out = diagnostics_of(
            self._raw(warnings=["실행 안내 문서(README) 없음 — G-04 재실행 필요"]),
            self._feature(missing=["결제"]), ["주문 조회", "핵심 칸 추진 일정"], ["주문 조회", "결 제"])
        self.assertEqual(out, [
            "README: 실행 안내 문서(README) 없음 — G-04 재실행 필요",
            "대조 LLM 판정 실패 1건 — 규칙 판정으로 대체: 주문 조회",
            "원페이지 핵심 칸 LLM 판정 실패 1건 — 감점하지 않음: 추진 일정",
            "자기 신고 2건 중 1건이 파싱 결과와 불일치: 결 제",   # 공백 차이는 무시하고 비교한다
        ])

    def test_nothing_to_report_is_an_empty_list(self):
        from verification_agent.tasks import diagnostics_of

        self.assertEqual(diagnostics_of(self._raw(), self._feature(), [], ["주문 조회"]), [])

    def test_gate_failure_reports_the_reason_but_not_self_report(self):
        """통과 필수 조건에 걸리면 대조를 하지 않아 전부 누락이다 — 자기 신고 차이는 적지 않는다."""
        from verification_agent.tasks import diagnostics_of

        out = diagnostics_of(self._raw(passed=False, gate_failures=["진입 파일 없음"]),
                             self._feature(missing=["주문 조회"]), [], ["주문 조회"])
        self.assertEqual(out, ["통과 필수 조건 실패: 진입 파일 없음"])
        withheld = diagnostics_of(self._raw(), self._feature(withheld=True), [], ["주문 조회"])
        self.assertEqual(withheld, [])

    def test_failed_llm_verdict_is_named(self):
        from verification_agent.feature_match import match_features

        html = ('<html lang="ko"><body><h1>t</h1><button id="a">검색</button><button id="b">결제</button>'
                "<script>document.getElementById('a').addEventListener('click', () => {});"
                "document.getElementById('b').addEventListener('click', () => {});</script></body></html>")

        def judge(features):
            return {f: (None if f == "결제" else (1.0, "있음")) for f in features}

        result = match_features(["검색", "결제"], html, "html", None, judge)
        self.assertEqual(result["llm_failed"], ["결제"])
        self.assertEqual(result["score"], 15.0)   # 실패한 기능은 규칙 결과(통과)를 그대로 쓴다
