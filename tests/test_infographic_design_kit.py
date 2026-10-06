"""Regression checks for content-aware SVG composition and extraction safeguards."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from xml.etree import ElementTree as ET

from engineering_agent.infographic import themes
from engineering_agent.infographic.layout import overflow_fields
from engineering_agent.infographic.render import render_infographic
from tests.preview_infographics import SAMPLES
from engineering_agent.tasks import _check_content
from verification_agent.score import compute_infographic_check


class DesignKitTests(TestCase):
    def test_showcase_is_the_default_without_a_layout(self):
        data = SAMPLES[0][1]
        with TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            with patch("engineering_agent.infographic.render._OUTPUT_DIR", Path(directory)):
                saved = render_infographic("원페이지", data)
                self.assertIn("결과 화면 구성", saved["source_text"])
                result = compute_infographic_check(saved["file_path"], saved["source_text"], "열람")
                self.assertEqual(result["total"], 15, result["items"])

    def test_web_flow_keeps_stages_beyond_the_first_row(self):
        data = dict(SAMPLES[3][1], flow_steps=["탐색", "선택", "확인", "예약", "결제", "완료"])
        with TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            with patch("engineering_agent.infographic.render._OUTPUT_DIR", Path(directory)):
                saved = render_infographic("웹개발", data)
        root = ET.fromstring(saved["source_text"])
        shown = ["".join(node.itertext()).strip() for node in root.iter()
                 if node.get("data-field") == "flow_steps"]
        self.assertEqual(shown, data["flow_steps"])

    def test_rich_onepage_is_readable_in_every_theme(self):
        data = SAMPLES[0][1]
        with TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            for theme in themes.THEMES:
                with self.subTest(theme=theme), \
                     patch("engineering_agent.infographic.render._OUTPUT_DIR", Path(directory)), \
                     patch.object(themes, "pick", return_value=theme):
                    saved = render_infographic("원페이지", data)
                    checked = compute_infographic_check(saved["file_path"], saved["source_text"],
                                                        "열람하고 인쇄하세요")
                    self.assertEqual(checked["total"], 15, checked["items"])
                    self.assertEqual(overflow_fields("원페이지", data), [])

    def test_optional_flow_preserves_order_and_is_omitted_without_evidence(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            with patch("engineering_agent.infographic.render._OUTPUT_DIR", Path(directory)):
                data = dict(SAMPLES[0][1])
                saved = render_infographic("원페이지", data)
                root = ET.fromstring(saved["source_text"])
                steps = ["".join(node.itertext()) for node in root.iter()
                         if node.get("data-field") == "solution_steps"]
                self.assertEqual(steps, data["solution_steps"])
                data["solution_steps"] = []
                saved = render_infographic("원페이지", data)
                self.assertNotIn('data-field="solution_steps"', saved["source_text"])
                self.assertNotIn("서비스 제공 과정", saved["source_text"])

    def test_new_flow_numbers_and_large_text_are_checked(self):
        data = dict(SAMPLES[0][1])
        data["solution_steps"] = ["999초 이내 주문", "매장 준비"]
        failures = _check_content("원페이지", data, "18% 10곳 29,000원 2026년 12월 2027년 3월")
        self.assertTrue(any("해결 절차" in failure and "999" in failure for failure in failures))
        # 천 단위 쉼표는 있든 없든 같은 값이다(검증-2 계획서 대조와 같은 규칙).
        data["solution_steps"] = ["월 29000원 구독", "매장 준비"]
        self.assertFalse(any("해결 절차" in failure for failure in
                             _check_content("원페이지", data, "18% 10곳 29,000원 2026년 12월 2027년 3월")))
        data["key_metrics"] = [{"value": "123456789012345678901234567890원", "label": "요금"}] * 3
        data["item_name"] = "가" * 24  # Fits at 30px, overflows at the actual 36px title size.
        fields = overflow_fields("원페이지", data)
        self.assertIn("key_metric", fields)
        self.assertIn("item_name", fields)
