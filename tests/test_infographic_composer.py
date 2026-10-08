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

    def test_long_summary_wraps_instead_of_being_cut(self):
        """한 줄 소개는 조율이 준 입력값이라 재수행으로 짧아지지 않는다. 한 줄을 넘으면 두 줄로 감고
        아래 내용을 내린다 — 원페이지 잘림(5번) · 넘침(6번) 감점이 없어야 한다."""
        from engineering_agent.infographic.layout import overflow_fields

        long = ("POS 판매 데이터를 학습해 품목별 적정 재고량과 발주 시점을 자동 산출하고, "
                "발주서를 거래처에 자동 전송하는 클라우드 서비스")
        cases = {"구역 틀(그림 있음)": dict(DATA, layout=EVERY_BLOCK, style="framed", item_summary=long),
                 "포스터(그림 없음)": dict(DATA, layout=EVERY_BLOCK, item_summary=long),
                 "기본 지면": dict(DATA, item_summary=long)}
        for name, data in cases.items():
            with self.subTest(name):
                self.assertNotIn("item_summary", overflow_fields("원페이지", data))
                saved = self._render(data)
                self.assertNotIn("…", saved["source_text"].split('data-field="item_summary"')[1].split("</text>")[0])
                checked = compute_infographic_check(saved["file_path"], saved["source_text"], "열람")
                self.assertEqual(checked["total"], 15, [(i["name"], i["evidence"]) for i in checked["items"]
                                                        if not i["passed"]])

    def test_overlong_input_values_are_not_rework_reasons(self):
        """두 줄로도 넘치는 입력값(아이템명 · 한 줄 소개 · 목표 고객)은 잘리지만, 재수행해도 같으므로
        자체 검사 실패로 올리지 않는다. LLM이 쓴 값의 넘침은 그대로 올린다."""
        data = dict(DATA, layout=EVERY_BLOCK, style="framed", item_summary="아주 긴 소개 문장입니다 " * 12,
                    target_users="아주 긴 목표 고객 설명입니다 " * 8)
        failures = _check_content("원페이지", data, PLAN)
        self.assertFalse([f for f in failures if f.startswith(("item_summary", "target_users"))], failures)
        long_problem = dict(data, problem="판매량 예측 실패로 반찬이 버려지는 문제가 매우 심각하다 " * 6)
        self.assertTrue([f for f in _check_content("원페이지", long_problem, PLAN) if f.startswith("problem")])

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

    def test_rework_keeps_the_layout_unless_the_user_asks_without_a_problem(self):
        """기획서 5-6: 재작성은 문제가 된 곳만 고치고 잘 된 부분은 지킨다. 재수행 · 미달 사유가 있는 재작성은
        구성을 지키고, 고칠 문제 없이 사용자가 고른 재작성(조율 기본 사유)만 새 구성(두 번째 관계)을 쓴다."""
        from engineering_agent.infographic.compose_guide import FIX_HINT, RETRY_HINT
        from tests import fake_sbrain

        patcher = fake_sbrain.install()
        self.addCleanup(patcher.stop)
        from engineering_agent import tasks
        from sbrain.contracts.tasks import TB2In
        from sbrain.models import ItemSpec, PlanDoc, PlanSection, ReworkInput, Sentence

        seen = {}

        def fake_generate(category, plan_text, tools):
            seen.setdefault("texts", []).append(plan_text)
            return dict(DATA, layout=[{"block": "features", "title": "주문 기능"}],
                        feature_details=[{"name": f, "detail": d}
                                         for f, d in zip(DATA["features"], DATA["feature_details"])])

        def fake_render(category, data):
            seen.setdefault("layouts", []).append([(b["block"], b["variant"]) for b in data["layout"]])
            seen.setdefault("titles", []).append({b["block"]: b["title"] for b in data["layout"]})
            return {"file_path": "x", "alt_text": "a"}

        doc = PlanDoc(sections=[PlanSection(section_code="1", title="t", sentences=[
            Sentence(sentence_id="s", text="본문", is_title=False, paragraph_no=1)])],
            feature_list=DATA["features"], charts=[], tables=[], protected_tokens=[])
        spec = ItemSpec(item_name="반찬온", one_line_summary="요약", target_customer="고객",
                        core_features=DATA["features"], category="원페이지", keywords=[])
        user_only = "사용자가 이 묶음의 재작성을 요청했습니다."  # 조율 sbrain_flow.REWORK_DEFAULT_REASON
        reworks = {
            "첫 생성": None,
            "재수행": ReworkInput(mode="재수행", previous_result_ref="p", issues=["수익모델 단가 누락"],
                               is_final_attempt=False),
            "미달 사유 재작성": ReworkInput(mode="재작성", previous_result_ref="p",
                                     issues=["핵심 정보 6항목 미달", "단가를 채워라"], is_final_attempt=False),
            "사유 없는 재작성": ReworkInput(mode="재작성", previous_result_ref="p", issues=[user_only, user_only],
                                     is_final_attempt=False),
        }
        with patch.object(tasks, "generate_infographic_content", fake_generate), \
             patch.object(tasks, "render_infographic", fake_render):
            for rework in reworks.values():
                tasks.run_tb2(TB2In(plan_doc=doc, item_spec=spec, category="원페이지", instruction="만들어라",
                                    rework_input=rework), tools=None)
        layout = dict(zip(reworks, seen["layouts"]))
        text = dict(zip(reworks, seen["texts"]))
        self.assertEqual(layout["재수행"], layout["첫 생성"])
        self.assertEqual(layout["미달 사유 재작성"], layout["첫 생성"])
        self.assertNotEqual(layout["사유 없는 재작성"], layout["첫 생성"])
        self.assertNotIn(RETRY_HINT, text["첫 생성"])
        self.assertNotIn(FIX_HINT, text["첫 생성"])
        self.assertIn(FIX_HINT, text["재수행"])
        self.assertIn(FIX_HINT, text["미달 사유 재작성"])
        self.assertIn(RETRY_HINT, text["사유 없는 재작성"])
        self.assertEqual(seen["titles"][0]["features"], "주문 기능")  # 모델이 쓴 제목은 같은 구역이면 살린다

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


class RealPlanTimelineTests(TestCase):
    """실제 계획서(재고 자동발주 SaaS · 반려동물 피부 AI 앱)의 추진 일정은 점 꼴 기간이 4~5개다.
    기간을 두 단계로 쪼개거나('~'만 남은 단계) 반 칸에 넣어 할 일 글이 잘리던 문제."""

    TIMELINES = (
        "2026.04~2026.06 수요예측 모델 고도화 2026.07~2026.08 발주 자동화 기능 개발 "
        "2026.09~2026.11 POS 연동 확대 2026.12~2027.01 유료 전환 프로모션 2027.02~2027.03 매장 확장",
        "2026.05~07 AI 고도화 2026.06~08 수의사 제휴 2026.09~11 앱 출시·사용자 확보 "
        "2027.01~06 펫보험사 제휴·연계 2027.07~12 모델 확장",
    )

    def test_dotted_ranges_stay_one_milestone(self):
        from engineering_agent.infographic.layout import parse_milestones

        first = parse_milestones(self.TIMELINES[0])
        self.assertEqual(first[0], ("2026.04~2026.06", "수요예측 모델 고도화"))
        self.assertEqual(len(first), 5)
        second = parse_milestones(self.TIMELINES[1])
        self.assertEqual(second[0], ("2026.05~07", "AI 고도화"))
        self.assertTrue(all(not event.startswith("~") for _, event in first + second))
        # 원래 꼴은 그대로
        self.assertEqual(parse_milestones("2026-04 착수 2026-09 출시"), [("2026-04", "착수"), ("2026-09", "출시")])

    def test_many_milestones_take_the_full_row_and_are_not_cut(self):
        half = [{"block": "features", "variant": "band"},
                {"block": "roadmap", "variant": "line", "width": "half"},
                {"block": "metrics", "variant": "cards", "width": "half"},
                {"block": "tagline", "variant": "band"}]
        for timeline in self.TIMELINES:
            with self.subTest(timeline[:20]):
                data = dict(DATA, layout=half, timeline_baseline=timeline)
                roadmap = next(b for b in normalize_layout("웹개발", data) if b["block"] == "roadmap")
                self.assertEqual(roadmap["width"], "full")
                self.assertNotIn("timeline_baseline", truncated_fields("웹개발", data))
