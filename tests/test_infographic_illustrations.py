"""대표 일러스트(illustrations.py)와 끼워 넣은 자원의 비밀값 오탐 방지."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from engineering_agent.infographic import illustrations
from engineering_agent.infographic.render import render_infographic
from tests.test_infographic_composer import DATA, EVERY_BLOCK
from verification_agent.rules.gates import find_secret
from verification_agent.score import compute_infographic_check


class IllustrationTests(TestCase):
    def test_every_scene_file_exists(self):
        for key, _ in illustrations.SCENES + ((illustrations.DEFAULT, ()),):
            self.assertTrue((illustrations.DIR / f"{key}.svg").is_file(), key)

    def test_scene_follows_business_words(self):
        self.assertEqual(illustrations.pick("원페이지", {"item_summary": "동네 반찬가게 사전주문"}), "store")
        self.assertEqual(illustrations.pick("원페이지", {"item_summary": "소규모 공장 설비 점검"}), "maintenance")
        self.assertEqual(illustrations.pick("AI_API", {"item_name": "민원요약AI"}), "ai")
        self.assertEqual(illustrations.pick("원페이지", {"item_name": "무명"}), illustrations.DEFAULT)

    def test_page_with_illustration_still_scores_full(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            with patch("engineering_agent.infographic.render._OUTPUT_DIR", Path(directory)):
                saved = render_infographic("원페이지", dict(DATA, layout=EVERY_BLOCK))
            checked = compute_infographic_check(saved["file_path"], saved["source_text"], "열람")
        self.assertIn("data:image/svg+xml;base64,", saved["source_text"])
        self.assertEqual(checked["total"], 15, [(i["name"], i["evidence"]) for i in checked["items"]
                                                if not i["passed"]])
        self.assertEqual(checked["gate_failures"], [])

    def test_embedded_base64_is_not_a_secret(self):
        blob = "AIza" + "A" * 30
        self.assertIsNone(find_secret(f'<image href="data:image/png;base64,{blob}"/>'))
        self.assertIsNotNone(find_secret(f'const key = "{blob}";'))
