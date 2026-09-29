"""웹 백엔드 진입점 테스트. 입력은 백엔드(back/app/routers/projects.py
_build_implement_agent_kwargs)가 실제로 만드는 모양 그대로 쓴다."""
from __future__ import annotations

import sys
from decimal import Decimal
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


class _Tools:
    def __init__(self, response):
        self._response = response
        self.messages = None

    def llm(self, messages, *, schema=None, parse=None, purpose=""):
        self.messages = messages
        value = self._response(schema) if callable(self._response) else self._response
        return parse(value) if parse is not None else value


_DESCRIPTION = "동네 매장 주문 중개"
_FEATURES = ["주문 조회", "결제"]

# 백엔드 모양: item_spec의 이름·요약·고객이 모두 description, 문장은 글자 목록
_ITEM_SPEC = {"item_name": _DESCRIPTION, "one_line_summary": _DESCRIPTION,
              "target_customer": _DESCRIPTION, "core_features": _FEATURES,
              "category": "웹개발", "keywords": []}
_PLAN_DOC = {
    "sections": [
        {"section_code": "1-1", "title": "문제 인식",
         "sentences": ["주문 대기가 길다. 빠른 주문으로 줄인다."]},
        {"section_code": "2-1", "title": "기능",
         "sentences": ["주문 조회는 매장별 주문 상태를 한 화면에 보여준다.",
                       "결제는 카드와 간편결제를 지원한다. 단가는 월 10000원. 2026-12-01 착수."]},
    ],
    "feature_list": _FEATURES, "charts": [], "tables": [], "protected_tokens": [],
}

_HTML = """```html:index.html
<!doctype html><html lang="ko"><head>
<style>body{color:#0F172A;background-color:#FFFFFF}</style></head><body>
<h1>동네 주문</h1>
<button id="q" data-feature="주문 조회">주문 조회</button>
<button id="p" data-feature="결제">결제</button>
<script>
document.getElementById('q').addEventListener('click', () => {});
document.getElementById('p').addEventListener('click', () => {});
</script></body></html>
```"""


class BackendEntryTests(TestCase):
    _OUTPUT = Path(__file__).resolve().parents[1] / "engineering_agent" / "output"

    def _dir(self) -> Path:
        directory = TemporaryDirectory(dir=self._OUTPUT)
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def _prototype(self, tools, **over):
        from engineering_agent.backend_entry import implement_artifact
        from engineering_agent.file_writer import save_files

        root = self._dir()
        with patch("engineering_agent.builder_html.save_files") as write:
            write.side_effect = lambda files, run_id: save_files(files, run_id, root)
            return implement_artifact(
                artifact_kind="prototype", category="웹개발", feature_list=_FEATURES,
                item_spec=_ITEM_SPEC, plan_doc=_PLAN_DOC, tools=tools, **over)

    def _infographic(self, category, extracted, **over):
        from engineering_agent.backend_entry import implement_artifact
        from engineering_agent.infographic import render as infographic_render

        with patch.object(infographic_render, "_OUTPUT_DIR", self._dir()):
            return implement_artifact(
                artifact_kind="infographic", category=category, feature_list=_FEATURES,
                item_spec={**_ITEM_SPEC, "category": category}, plan_doc=_PLAN_DOC,
                tools=_Tools(lambda schema: schema(**extracted)), **over)

    # ── 구현 ──────────────────────────────────────────────────

    def test_prototype_from_backend_shape(self):
        result = self._prototype(_Tools(_HTML))
        self.assertTrue(result["passed"], result["failures"])
        self.assertEqual(result["file_ext"], ".html")
        self.assertEqual(result["file_bytes"], Path(result["file_path"]).read_bytes())
        self.assertIn(b"<h1>", result["file_bytes"])

    def test_prototype_gate_failure_returns_no_bytes(self):
        result = self._prototype(_Tools("```html:main.html\n<html lang=\"ko\"></html>\n```"))
        self.assertFalse(result["passed"])
        self.assertIsNone(result["file_bytes"])
        self.assertIn("E-B1-ENTRY", result["failures"][0])

    def test_rework_issues_reach_the_model(self):
        tools = _Tools(_HTML)
        self._prototype(tools, rework_issues=["명도 대비 4.5 미달"])
        self.assertIn("명도 대비 4.5 미달", tools.messages[1]["content"])

    def test_onepage_has_no_prototype(self):
        from engineering_agent.backend_entry import implement_artifact

        with self.assertRaises(ValueError):
            implement_artifact(artifact_kind="prototype", category="원페이지",
                               feature_list=_FEATURES, item_spec=_ITEM_SPEC, tools=_Tools(""))

    def test_infographic_accepts_plan_doc_with_plain_sentences(self):
        """백엔드는 문장을 글자 목록으로 보낸다. 계약 PlanDoc은 Sentence 객체를 요구하므로
        진입점이 채워 넣어야 한다. 이 변환이 없으면 PlanDoc 검증에서 바로 실패한다."""
        result = self._infographic("원페이지", {
            "item_name": "x", "features": _FEATURES, "problem": "주문 대기가 길다",
            "solution": "빠른 주문으로 줄인다", "revenue_unit_price": "월 10000원",
            "timeline_baseline": "2026-12-01",
            "feature_details": [
                {"name": "주문 조회", "detail": "매장별 주문 상태를 한 화면에 보여준다"},
                {"name": "결제", "detail": "카드와 간편결제를 지원한다"}]})
        self.assertEqual(result["file_ext"], ".svg")
        self.assertTrue(result["file_bytes"].startswith(b"<svg"))
        self.assertTrue(result["alt_text"])
        self.assertEqual(Path(result["file_path"]).name, "onepage.svg")

    # ── 검증-2 ────────────────────────────────────────────────

    def test_verify_rows_add_up_to_totals(self):
        from verification_agent.backend_entry import ITEM_CODES, verify_artifact

        proto = self._prototype(_Tools(_HTML))
        info = self._infographic("웹개발", {"item_name": "x", "features": _FEATURES,
                                          "flow_steps": ["탐색", "주문"]})
        result = verify_artifact(category="웹개발", prototype_path=proto["file_path"],
                                 infographic_path=info["file_path"], feature_list=_FEATURES,
                                 plan_doc=_PLAN_DOC, infographic_alt_text=info["alt_text"])

        code_rows = result["rows"][:8]
        self.assertEqual([r["item_code"] for r in code_rows], list(ITEM_CODES["html"].values()))
        self.assertEqual(sum(r["score"] for r in code_rows), result["code_total"])
        self.assertEqual(sum(r["max_score"] for r in code_rows), Decimal("15.00"))
        # input이 없어 3번은 해당 없음 — 행은 남기되 0/0
        label = next(r for r in code_rows if r["item_code"] == "CHECK-INPUT-LABEL")
        self.assertEqual((label["applicable"], label["score"], label["max_score"]),
                         (False, Decimal("0.00"), Decimal("0.00")))
        self.assertEqual(result["rows"][8]["item_code"], "FEATURE-MATCH")
        self.assertEqual(result["feature_score"], Decimal("15.00"))
        self.assertEqual(result["artifact_total"], result["code_total"] + result["feature_score"])
        self.assertEqual(result["warnings"], ["실행 안내 문서(README) 없음 — G-04 재실행 필요"])

    def test_verify_onepage_uses_plan_doc_from_backend(self):
        from verification_agent.backend_entry import verify_artifact

        info = self._infographic("원페이지", {
            "item_name": "x", "features": _FEATURES, "problem": "주문 대기가 길다",
            "solution": "빠른 주문으로 줄인다", "revenue_unit_price": "월 10000원",
            "timeline_baseline": "2026-12-01",
            "feature_details": [
                {"name": "주문 조회", "detail": "매장별 주문 상태를 한 화면에 보여준다"},
                {"name": "결제", "detail": "카드와 간편결제를 지원한다"}]})
        common = dict(category="원페이지", prototype_path=None,
                      infographic_path=info["file_path"], feature_list=_FEATURES)
        with_plan = verify_artifact(plan_doc=_PLAN_DOC, **common)
        self.assertEqual(with_plan["feature_score"], Decimal("15.00"), with_plan["rows"][-1])
        # 대체 텍스트를 안 넘겨도 SVG <title>로 대신해 대체 텍스트 칸이 통과한다
        self.assertTrue(with_plan["rows"][0]["passed"], with_plan["rows"][0])
        without = verify_artifact(plan_doc=None, **common)
        self.assertEqual(without["feature_score"], Decimal("0.00"))
        self.assertIn("plan_doc", without["rows"][-1]["reason_text"])

    def test_verify_gate_failure_zeroes_everything(self):
        from verification_agent.backend_entry import verify_artifact

        info = self._infographic("웹개발", {"item_name": "x", "features": _FEATURES,
                                          "flow_steps": ["탐색"]})
        result = verify_artifact(category="웹개발", prototype_path=None,
                                 infographic_path=info["file_path"], feature_list=_FEATURES)
        self.assertEqual(result["artifact_total"], Decimal("0.00"))
        self.assertIn("진입 파일 없음", result["gate_failures"][0])
