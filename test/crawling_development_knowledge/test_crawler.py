import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from crawler import CATEGORIES, knowledge, write


class KnowledgeTests(unittest.TestCase):
    def test_coverage_and_agent_fields(self):
        items = knowledge()
        self.assertEqual(len(items), 40)
        self.assertEqual(len({x["id"] for x in items}), 40)
        self.assertEqual(len({x["knowledgeName"] for x in items}), 40)
        for category in CATEGORIES:
            rows = [x for x in items if x["category"] == category]
            self.assertEqual([x["rank"] for x in rows], list(range(1, 11)))
        for item in items:
            for key in ("definition", "whenToUse", "howToApply", "benefits", "cautions", "agentPromptHint"):
                self.assertTrue(item[key])
            self.assertTrue(item["source"]["url"].startswith("https://"))

    def test_output(self):
        with TemporaryDirectory() as directory:
            write(directory)
            root = Path(directory)
            data = json.loads((root / "development_knowledge.json").read_text(encoding="utf-8"))
            self.assertEqual(len(data["items"]), 40)
            self.assertIn(data["items"][0]["knowledgeName"],
                          (root / "development_knowledge.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
