import json
from pathlib import Path
import tempfile
import unittest

from market_crawler import (
    add_keyword,
    build_market_report,
    is_relevant_result,
    keyword_rows,
    keyword_terms,
    parse_open_summary,
    query_variants,
)


class MarketCrawlingTests(unittest.TestCase):
    def test_open_summary_call_is_parsed(self):
        parsed = parse_open_summary("openSummary('주제별 분석', '002001002', '1');")
        self.assertEqual(parsed, {"menuName": "주제별 분석", "menuCode": "002001002", "contentNo": "1"})

    def test_user_keyword_variants_skip_generic_single_word(self):
        variants = query_variants("기업용 AI 문서 검색", True)
        self.assertIn("AI 문서 검색", variants)
        self.assertNotIn("기업용", variants)
        self.assertNotIn("AI", variants)

    def test_user_keyword_result_requires_two_core_terms(self):
        terms = keyword_terms("기업용 AI 문서 검색")
        accepted, matched = is_relevant_result({"title": "AI 문서 검색 산업 동향", "summaryText": "문서 검색과 인공지능 활용"}, terms)
        rejected, _ = is_relevant_result({"title": "기업용 서비스 시장", "summaryText": "기업 업무지원 솔루션 동향"}, terms)
        self.assertTrue(accepted)
        self.assertIn("AI", matched)
        self.assertFalse(rejected)

    def test_listing_field_count_includes_user_keywords(self):
        listing = json.loads(Path("output/keyword_list.json").read_text(encoding="utf-8"))
        fields = keyword_rows(listing)
        self.assertGreaterEqual(len(fields), 12)
        self.assertTrue(any(field["industryName"] == "정보·통신" for field in fields))

    def test_market_research_uses_kiet_summary_pop_schema(self):
        with tempfile.TemporaryDirectory(dir=".") as tmp:
            output = Path(tmp) / "results.json"
            result = build_market_report(output=output)
            saved = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result["researchMode"], "kiet_summary_pop")
        self.assertEqual(len(result["reports"]), len(saved["reports"]))
        body = json.dumps(saved, ensure_ascii=False)
        self.assertNotIn("example.com", body)
        self.assertNotIn("bing.com", body)

    def test_user_keyword_prompt_is_not_written_as_industry_field(self):
        result = build_market_report()
        user_reports = [report for report in result["reports"] if report["category"].get("classificationType") == "user_keyword"]
        self.assertTrue(user_reports)
        for report in user_reports:
            text = report["promptBrief"] + " " + " ".join(section["promptBrief"] for section in report["sections"].values())
            self.assertIn("검색 주제", text)
            self.assertNotIn("분야의", text)

    def test_keyword_add_is_deduplicated_with_fake_crawler(self):
        import market_crawler as module

        def fake_crawl_kiet(listing):
            return {"categories": [{"industryName": "기업용 AI 문서 검색", "resultCount": 1, "status": "collected", "results": [], "queryVariants": [], "requiredTerms": []}], "summary": {"categoryCount": 1, "collectedCategoryCount": 1, "totalResultCount": 1}}

        def fake_build_market_report(listing):
            return {"summary": {"reportCount": 1}}

        original_crawl = module.crawl_kiet
        original_build = module.build_market_report
        module.crawl_kiet = fake_crawl_kiet
        module.build_market_report = fake_build_market_report
        try:
            with tempfile.TemporaryDirectory(dir=".") as tmp:
                tmpdir = Path(tmp)
                listing = tmpdir / "keyword_list.json"
                history = tmpdir / "keyword_history.json"
                listing.write_text(json.dumps({"programs": [], "userKeywords": []}, ensure_ascii=False), encoding="utf-8")
                add_keyword("기업용 AI 문서 검색", listing=listing, history=history)
                add_keyword("기업용 AI 문서 검색", listing=listing, history=history)
                data = json.loads(listing.read_text(encoding="utf-8"))
                history_data = json.loads(history.read_text(encoding="utf-8"))
        finally:
            module.crawl_kiet = original_crawl
            module.build_market_report = original_build
        self.assertEqual(len(data["userKeywords"]), 1)
        self.assertEqual(len(history_data["searches"]), 1)


if __name__ == "__main__":
    unittest.main()
