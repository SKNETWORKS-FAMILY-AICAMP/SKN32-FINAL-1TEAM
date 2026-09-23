import json, tempfile, unittest
from pathlib import Path
from crawler import trends, write
class TestTrendDeliverables(unittest.TestCase):
    def test_schema_evidence_and_ranks(self):
        items=trends(); self.assertEqual(len(items),30); self.assertEqual([x["rank"] for x in items],list(range(1,31))); self.assertEqual(len({x["trendId"] for x in items}),30)
        for x in items: self.assertTrue(x["keywords"] and x["evidence"][0]["sourceUrl"] and x["evidence"][0]["supportingText"])
    def test_written_json_and_markdown_match(self):
        with tempfile.TemporaryDirectory() as d:
            write(d); root=Path(d); items=json.loads((root/"web_design_trends_2026.json").read_text(encoding="utf-8")); md=(root/"web_design_trends_2026.md").read_text(encoding="utf-8")
            for x in items: self.assertIn(x["trendId"],md); self.assertIn(x["evidence"][0]["supportingText"],md)
if __name__=="__main__": unittest.main()
