"""모델이 고른 블록 구성(composer.py)으로 지면을 조립하는 동작."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from engineering_agent.infographic import themes
from engineering_agent.infographic.composer import CATALOG, normalize_layout, truncated_fields
from engineering_agent.infographic.render import render_infographic
from engineering_agent.tasks import _check_content
from verification_agent.score import compute_infographic_check

DATA = {
    "item_name": "반찬온", "item_summary": "동네 반찬가게 사전주문·픽업 예약 서비스",
    "target_users": "동네 반찬가게 사장과 퇴근길 직장인",
    "features": ["반찬 사전주문", "픽업 시간 예약", "재고 알림", "주간 매출 리포트"],
    "feature_details": ["전날 밤까지 주문·결제", "30분 단위 방문 시간 예약", "남은 수량 5개 이하 알림",
                        "요일별 판매량·폐기량 정리"],
    "problem": "판매량 예측 실패로 반찬 18% 폐기, 퇴근길 대기 12분",
    "solution": "전날 주문으로 조리량을 정하고 픽업 시간을 나눈다",
    "outcome": "폐기 절반 · 대기 없는 픽업",
    "revenue_unit_price": "가게당 월 이용료 29000원, 첫 달 무료",
    "timeline_baseline": "2026년 11월~12월 기반 구축, 2027년 1월~3월 시범 운영, 2027년 4월~12월 확산",
    "key_metrics": [{"value": "9%", "before": "18%", "label": "가맹점 폐기율"},
                    {"value": "120곳", "label": "가입 반찬가게"}, {"value": "85%", "label": "가맹점 유지율"}],
    "before_after": [{"label": "반찬 폐기율", "before": "18%", "after": "9%"},
                     {"label": "퇴근길 대기", "before": "12분", "after": "0분에 가깝게"}],
    "market_levels": [{"label": "국내 반찬 시장", "value": "약 4조 원"},
                      {"label": "서울 반찬가게", "value": "약 3000곳"}, {"label": "마포구 1차 목표", "value": "210곳"}],
    "comparison": {"others": "배달앱", "rows": [
        {"criterion": "가게 비용", "others": "주문액 15% 이상 수수료", "ours": "월 이용료만"},
        {"criterion": "주문 방식", "others": "즉시 배달", "ours": "전날 사전주문·픽업"}]},
    "revenue_flow": {"payer": "반찬가게", "payment": "월 29000원", "value": "주문·재고·매출 관리"},
    "effects": [{"who": "반찬가게", "what": "월 약 42만 원 비용 절감"}, {"who": "퇴근길 손님", "what": "대기 없이 픽업"}],
    "tagline": "전날 주문으로 폐기는 줄이고, 픽업은 기다림 없이",
    "solution_steps": ["전날 밤 주문·결제", "주문량 확인", "조리량 결정", "예약 시간 픽업"],
}
PLAN = ("18% 12분 29000원 2026년 11월 12월 2027년 1월 3월 4월 30분 5개 9% 120곳 85% 4조 원 3000곳 210곳 "
        "15% 42만 원 0분")
EVERY_BLOCK = [
    {"block": "hero", "variant": "journey"},
    {"block": "problem_solution", "variant": "before_after", "width": "half"},
    {"block": "market", "variant": "nested", "width": "half"},
    {"block": "process", "variant": "steps"},
    {"block": "features", "variant": "grid"},
    {"block": "revenue", "variant": "flow", "width": "half"},
    {"block": "competition", "variant": "table", "width": "half"},
    {"block": "roadmap", "variant": "line"},
    {"block": "metrics", "variant": "bars", "width": "half"},
    {"block": "effects", "variant": "cards", "width": "half"},
    {"block": "tagline", "variant": "band"},
]


class ComposerTests(TestCase):
    def _render(self, data):
        directory = TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(directory.cleanup)
        with patch("engineering_agent.infographic.render._OUTPUT_DIR", Path(directory.name)):
            return render_infographic("원페이지", data)

    def test_every_block_is_gradable_in_every_theme(self):
        data = dict(DATA, layout=EVERY_BLOCK)
        self.assertEqual(truncated_fields("원페이지", data), [])
        for theme in themes.THEMES:
            with self.subTest(theme), patch.object(themes, "pick", return_value=theme):
                saved = self._render(data)
                checked = compute_infographic_check(saved["file_path"], saved["source_text"], "열람")
                self.assertEqual(checked["total"], 15, [(i["name"], i["evidence"]) for i in checked["items"]
                                                        if not i["passed"]])
        self.assertEqual(_check_content("원페이지", data, PLAN), [])

    def test_missing_required_blocks_are_filled(self):
        layout = normalize_layout("원페이지", {"layout": [{"block": "market", "variant": "nested"},
                                                          {"block": "tagline", "variant": "band"}]})
        blocks = [b["block"] for b in layout]
        for required in ("problem_solution", "features", "revenue", "roadmap"):
            self.assertIn(required, blocks)
        self.assertEqual(blocks[-1], "tagline")
        saved = self._render(dict(DATA, layout=[{"block": "market", "variant": "nested"}]))
        checked = compute_infographic_check(saved["file_path"], saved["source_text"], "열람")
        self.assertEqual(checked["items"][1]["earned"], 3)  # 필수 6정보가 모두 지면에

    def test_journey_hero_drops_duplicate_split_and_unknown_blocks(self):
        layout = normalize_layout("원페이지", {"layout": [
            {"block": "hero", "variant": "journey"}, {"block": "problem_solution", "variant": "split"},
            {"block": "radar", "variant": "chart"}, {"block": "features", "variant": "nope"}]})
        pairs = [(b["block"], b["variant"]) for b in layout]
        self.assertNotIn(("problem_solution", "split"), pairs)
        self.assertNotIn("radar", [b for b, _ in pairs])
        self.assertIn(("features", next(iter(CATALOG["features"]))), pairs)

    def test_different_layouts_make_different_pages(self):
        a = self._render(dict(DATA, layout=EVERY_BLOCK))["source_text"]
        b = self._render(dict(DATA, layout=[{"block": "hero", "variant": "hub"},
                                            {"block": "features", "variant": "band"}]))["source_text"]
        self.assertIn("시장 규모", a)
        self.assertNotIn("시장 규모", b)

    def test_retry_asks_for_a_different_layout(self):
        from engineering_agent.infographic.compose_guide import RETRY_HINT
        from tests import fake_sbrain

        patcher = fake_sbrain.install()
        self.addCleanup(patcher.stop)
        from engineering_agent import tasks
        from sbrain.contracts.tasks import TB2In
        from sbrain.models import ItemSpec, PlanDoc, PlanSection, ReworkInput, Sentence

        seen = {}

        def fake_generate(category, plan_text, tools, variation=0):
            seen.setdefault("texts", []).append(plan_text)
            seen.setdefault("variations", []).append(variation)
            return {"item_name": "반찬온", "features": ["반찬 사전주문"], "feature_details": []}

        doc = PlanDoc(sections=[PlanSection(section_code="1", title="t", sentences=[
            Sentence(sentence_id="s", text="본문", is_title=False, paragraph_no=1)])],
            feature_list=["반찬 사전주문"], charts=[], tables=[], protected_tokens=[])
        spec = ItemSpec(item_name="반찬온", one_line_summary="요약", target_customer="고객",
                        core_features=["반찬 사전주문"], category="원페이지", keywords=[])
        with patch.object(tasks, "generate_infographic_content", fake_generate), \
             patch.object(tasks, "render_infographic", return_value={"file_path": "x", "alt_text": "a"}):
            tasks.run_tb2(TB2In(plan_doc=doc, item_spec=spec, category="원페이지", instruction="만들어라",
                                rework_input=ReworkInput(mode="재수행", previous_result_ref="p", issues=[],
                                                         is_final_attempt=False)), tools=None)
            tasks.run_tb2(TB2In(plan_doc=doc, item_spec=spec, category="원페이지", instruction="만들어라"),
                          tools=None)
        retry, first = seen["variations"]
        self.assertIn(RETRY_HINT, seen["texts"][0])
        self.assertNotIn(RETRY_HINT, seen["texts"][1])
        from engineering_agent.infographic.compose_guide import SKELETONS
        self.assertNotEqual(retry % len(SKELETONS), first % len(SKELETONS))  # 다시 만들면 다른 뼈대를 준다

    def test_each_variation_hands_the_model_a_different_skeleton(self):
        """작은 모델은 예시를 따른다. 예시가 하나면 어떤 계획서든 같은 구성이 나온다."""
        from engineering_agent.infographic.compose_guide import SKELETONS, layout_example

        examples = [layout_example("원페이지", n) for n in range(len(SKELETONS))]
        self.assertEqual(len(set(examples)), len(SKELETONS))
        self.assertEqual(layout_example("원페이지", 0), layout_example("원페이지", len(SKELETONS)))
        self.assertGreaterEqual(len({e.split('"variant": "')[1].split('"')[0] for e in examples}), 2)
        for n in range(len(SKELETONS)):
            self.assertIn('"hero", "variant": "hub"', layout_example("AI_API", n))
            self.assertIn('"process"', layout_example("웹개발", n))

    def test_two_narrow_blocks_in_a_row_share_one_line(self):
        from engineering_agent.infographic.composer import normalize_layout

        layout = normalize_layout("원페이지", dict(DATA, layout=[
            {"block": "hero", "variant": "journey"}, {"block": "features", "variant": "band"},
            {"block": "market", "variant": "nested", "width": "full"},
            {"block": "revenue", "variant": "flow", "width": "full"},
            {"block": "roadmap", "variant": "line"}]))
        widths = {b["block"]: b["width"] for b in layout}
        self.assertEqual((widths["market"], widths["revenue"]), ("half", "half"))

    def test_lone_narrow_block_pairs_with_a_neighbour(self):
        """짝이던 블록이 빠져 좁은 도식이 혼자 남으면 한 줄을 다 차지해 옆이 빈다."""
        from engineering_agent.infographic.composer import normalize_layout

        layout = normalize_layout("원페이지", dict(DATA, layout=[
            {"block": "hero", "variant": "journey"}, {"block": "features", "variant": "band"},
            {"block": "roadmap", "variant": "line"}, {"block": "revenue", "variant": "card", "width": "half"},
            {"block": "metrics", "variant": "cards"},
            {"block": "market", "variant": "nested", "width": "half"},
            {"block": "effects", "variant": "cards"}]))
        widths = {b["block"]: b["width"] for b in layout}
        self.assertEqual((widths["market"], widths["effects"]), ("half", "half"))
        self.assertEqual(widths["features"], "full")
