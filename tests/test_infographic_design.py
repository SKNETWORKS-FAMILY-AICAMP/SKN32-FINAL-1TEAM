"""인포그래픽 디자인 사양(design.py) — 지면 구성 · 대표 그림 · 그림체를 이름이 아니라 재료의 관계로 고른다."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from engineering_agent.infographic import artsheet, design
from engineering_agent.infographic.composer import normalize_layout
from engineering_agent.infographic.render import render_infographic
from tests.test_infographic_composer import DATA
from verification_agent.score import compute_infographic_check

# 관계 하나만 두드러지게 남긴 재료. DATA에서 다른 관계의 재료를 뺀다.
BARE = dict(DATA, before_after=[], market_levels=[], comparison={}, revenue_flow={}, effects=[],
            solution_steps=[], key_metrics=[], layout=[])
CASES = {
    design.COMPARE: dict(BARE, before_after=DATA["before_after"]),
    design.NETWORK: dict(BARE, effects=[{"who": "반찬가게", "what": "비용 절감"}, {"who": "퇴근길 손님", "what": "대기 없음"},
                                        {"who": "구청", "what": "음식물 쓰레기 감소"}]),
    design.DEAL: dict(BARE, revenue_flow=DATA["revenue_flow"]),
    design.STEPS: dict(BARE, solution_steps=DATA["solution_steps"]),
    design.MARKET: dict(BARE, market_levels=DATA["market_levels"]),
    design.STORY: BARE,
}
# 그 관계를 보여 주는 구역. 이야기가 아니면 문제 판이 먼저 오고 이 구역이 바로 뒤에 온다.
LEAD = {design.COMPARE: ("problem_solution", "before_after"), design.NETWORK: ("effects", "cards"),
        design.DEAL: ("revenue", "flow"), design.STEPS: ("process", "steps"), design.MARKET: ("market", "nested"),
        design.STORY: ("hero", "journey")}


def _blocks(spec):
    return [(b["block"], b["variant"]) for b in spec["layout"]]


class RelationTests(TestCase):
    def test_the_standout_relation_leads_the_page(self):
        for relation, data in CASES.items():
            with self.subTest(relation):
                spec = design.decide("원페이지", data)
                self.assertEqual(spec["relation"], relation, spec["reasons"])
                blocks = [b for b in _blocks(spec) if b != ("problem_solution", "split")]
                self.assertEqual(blocks[0], LEAD[relation])

    def test_different_relations_make_different_layouts(self):
        layouts = {tuple(_blocks(design.decide("원페이지", data))) for data in CASES.values()}
        self.assertEqual(len(layouts), len(CASES))

    def test_the_item_name_does_not_choose_the_layout(self):
        """예전에는 이름 해시로 뼈대를 골랐다. 내용이 같으면 이름이 달라도 같은 구성이다."""
        for data in CASES.values():
            a = design.decide("원페이지", dict(data, item_name="가나다"))
            b = design.decide("원페이지", dict(data, item_name="라마바"))
            self.assertEqual((a["relation"], a["layout"]), (b["relation"], b["layout"]))

    def test_redesign_moves_to_the_next_relation(self):
        first = design.decide("원페이지", DATA)
        again = design.decide("원페이지", DATA, redesign=True)
        self.assertNotEqual(first["relation"], again["relation"])
        self.assertNotEqual(_blocks(first), _blocks(again))
        # 관계가 하나뿐이어도 새 구성 요청이면 구성이 달라진다(구역 변형을 바꾼다)
        self.assertNotEqual(_blocks(design.decide("원페이지", BARE)),
                            _blocks(design.decide("원페이지", BARE, redesign=True)))

    def test_no_block_without_material(self):
        """재료가 없는 구역을 넣으면 '정보 없음'이 찍히거나 빈 도표가 된다."""
        blocks = {b for b, _ in _blocks(design.decide("원페이지", BARE))}
        for empty in ("market", "competition", "effects", "metrics"):
            self.assertNotIn(empty, blocks)

    def test_placeholder_target_is_not_a_party(self):
        """목표 고객 '확인 필요'는 주체가 아니다(실제 예시 계획서 셋의 목표 고객 입력값)."""
        self.assertNotIn("확인 필요", design.parties(dict(BARE, target_users="확인 필요")))

    def test_ai_api_keeps_the_processing_diagram_on_top(self):
        for data in CASES.values():
            spec = design.decide("AI_API", dict(data, pipeline={"input": "사진", "process": "분석", "output": "결과"}))
            placed = dict(data, layout=spec["layout"], _design=spec)
            self.assertEqual(normalize_layout("AI_API", placed)[0]["block"], "hero")
            self.assertNotIn(("hero", "journey"), _blocks(spec))
            self.assertEqual(artsheet.hero_kind("AI_API", placed)[0], "steps")


class HeroAndStyleTests(TestCase):
    def _hero(self, data, category="원페이지"):
        return artsheet.hero_kind(category, design.apply(category, data))[0]

    def test_hero_tells_the_same_relation_as_the_layout(self):
        self.assertEqual(self._hero(CASES[design.NETWORK]), "hub")
        self.assertEqual(self._hero(CASES[design.STORY]), "panorama")
        self.assertEqual(self._hero(CASES[design.STEPS]), "scene")  # 단계는 단계 구역이 이미 보여 준다

    def test_consumer_fields_get_a_flat_style_and_industry_a_line_style(self):
        def prompt(item_name, summary, features, target):
            data = design.apply("원페이지", dict(DATA, item_name=item_name, item_summary=summary,
                                                features=features, target_users=target))
            return artsheet.sheet_prompt(data, artsheet.icon_items("원페이지", data), "초록", "원페이지")

        flat = prompt("반려동물 피부 AI 앱", "반려동물 피부 사진을 AI로 분석", ["피부 사진 AI 분석"], "반려동물 보호자")
        line = prompt("AI 비전 결함 검사", "제조 공정 카메라 영상 분석", ["결함 분류 모델"], "제조 공장")
        self.assertIn("평면 일러스트", flat)
        self.assertIn("선 아이콘", line)
        for p in (flat, line):  # 그림체가 달라도 칸 · 흰 여백 지시는 그대로(find_cells의 근거)
            self.assertIn("칸 사이와 가장자리는 흰색으로 둔다", p)


class GradableTests(TestCase):
    def test_every_decided_layout_renders_and_keeps_full_code_score(self):
        """사양이 고른 어떤 구성도 원페이지 코드 점검 8항목을 깎지 않는다."""
        for relation, data in CASES.items():
            for redesign in (False, True):
                with self.subTest(relation=relation, redesign=redesign), TemporaryDirectory(
                        dir=Path(__file__).resolve().parents[1]) as directory, \
                        patch("engineering_agent.infographic.render._OUTPUT_DIR", Path(directory)):
                    saved = render_infographic("원페이지", design.apply("원페이지", data, redesign))
                    checked = compute_infographic_check(saved["file_path"], saved["source_text"], "열람")
                    self.assertEqual(checked["total"], 15, [(i["name"], i["evidence"]) for i in checked["items"]
                                                            if not i["passed"]])

    def test_prompt_no_longer_tells_the_model_to_follow_a_skeleton(self):
        from engineering_agent.infographic.compose_guide import COMPOSE_GUIDE

        self.assertNotIn("뼈대", COMPOSE_GUIDE)
        self.assertIn("빠짐없이", COMPOSE_GUIDE)


class FrameStyleTests(TestCase):
    """구역 틀(card · panel · open). 모든 구역을 같은 흰 카드에 담으면 색 · 그림 · 구성이 달라도 같은 양식으로 보인다."""

    def test_every_block_in_every_frame_and_theme_keeps_full_code_score(self):
        from engineering_agent.infographic import themes
        from engineering_agent.infographic.design_kit import FRAME_STYLES
        from tests.test_infographic_composer import EVERY_BLOCK

        for frame in FRAME_STYLES:
            for theme in themes.THEMES:
                data = dict(DATA, layout=EVERY_BLOCK, style="framed",
                            _design={"frame": frame, "hero": "scene", "art_style": "선화"})
                with self.subTest(frame=frame, theme=theme), TemporaryDirectory(
                        dir=Path(__file__).resolve().parents[1]) as directory, \
                        patch("engineering_agent.infographic.render._OUTPUT_DIR", Path(directory)), \
                        patch.object(themes, "pick", return_value=theme):
                    saved = render_infographic("원페이지", data)
                    checked = compute_infographic_check(saved["file_path"], saved["source_text"], "열람")
                    self.assertEqual(checked["total"], 15, [(i["name"], i["evidence"]) for i in checked["items"]
                                                            if not i["passed"]])

    def test_frames_look_different(self):
        from engineering_agent.infographic.composer import compose
        from tests.test_infographic_composer import EVERY_BLOCK

        pages = {frame: compose("원페이지", dict(DATA, layout=EVERY_BLOCK, style="framed", _design={"frame": frame}),
                                DATA["features"])[0]
                 for frame in ("card", "panel", "open")}
        self.assertEqual(len(set(pages.values())), 3)
        self.assertIn('stroke="#D5E5E1"/><rect', pages["card"])  # 흰 카드 + 탭
        # 지면 한 장을 다 그리면 틀 설정이 원래대로 돌아간다(다른 스레드 · 다음 지면에 새지 않는다)
        from engineering_agent.infographic.design_kit import FRAME_STYLE
        self.assertEqual(FRAME_STYLE.get(), "card")

    def test_frame_follows_the_field_and_moves_on_redesign(self):
        def frame(item_name, summary, features, target, redesign=False):
            return design.decide("원페이지", dict(DATA, item_name=item_name, item_summary=summary, features=features,
                                                target_users=target), redesign)["frame"]

        self.assertEqual(frame("반려동물 피부 AI 앱", "반려동물 사진 분석", ["피부 사진 분석"], "보호자"), "panel")
        self.assertEqual(frame("AI 비전 결함 검사", "제조 공정 카메라", ["결함 분류"], "제조 공장"), "open")
        self.assertEqual(frame("재고 자동발주 SaaS", "POS 판매 데이터로 발주", ["발주 자동화"], "매장"), "card")
        self.assertNotEqual(frame("재고 자동발주 SaaS", "POS 판매 데이터로 발주", ["발주 자동화"], "매장", True), "card")


class RequiredMaterialPromptTests(TestCase):
    """구성을 코드가 정하면서 프롬프트에 단계 구역이 보이지 않게 됐다. 카테고리 필수 재료는 따로 적어야 한다
    (실측: 웹개발에서 flow_steps를 비워 '사용자 화면 흐름 누락')."""

    def _prompt(self, category):
        from engineering_agent.infographic.content import generate_infographic_content

        seen = {}

        class Tools:
            def llm(self, messages, *, schema=None, parse=None, purpose=""):
                seen["system"] = messages[0]["content"]
                return parse('{"item_name": "x", "features": ["a"]}')

        generate_infographic_content(category, "본문", Tools())
        return seen["system"]

    def test_each_category_names_its_required_material(self):
        self.assertIn("flow_steps는 반드시 채운다", self._prompt("웹개발"))
        self.assertIn("pipeline의 input · process · output은 반드시 모두 채운다", self._prompt("AI_API"))
        self.assertNotIn("flow_steps는 반드시", self._prompt("원페이지"))


class HeaderStyleTests(TestCase):
    """맨 윗부분(제목 · 한 줄 소개 · 목표 고객)도 구역 틀과 짝을 맞춰 바꾼다. 모든 지면이 가운데 정렬 제목 +
    알약 모양 대상이라 색 · 그림 · 구성이 달라도 첫인상이 같았다."""

    def test_header_follows_the_frame_and_keeps_markers(self):
        import re

        from engineering_agent.infographic.composer import compose

        heads = {}
        for frame in ("card", "panel", "open"):
            svg = compose("원페이지", dict(DATA, layout=[{"block": "features", "variant": "band"}], style="framed",
                                         _design={"frame": frame}), DATA["features"])[0]
            head = svg.split('data-field="target_users"')[0]
            heads[frame] = head
            for field in ('data-field="item_name" data-role="title"', 'data-field="item_summary"',
                          'data-field="target_users" data-role="value"'):
                self.assertIn(field, svg, frame)
        self.assertEqual(len(set(heads.values())), 3)
        self.assertRegex(heads["open"], r'data-field="item_name"[^>]*|text-anchor="start"')
        self.assertIn('width="900"', heads["card"])  # 머리 띠
        self.assertNotIn('width="900"', heads["panel"])


class StepsIsTheDefaultTests(TestCase):
    """단계 흐름에 2점을 주었더니 실제 예시 계획서 셋이 모두 '단계 흐름'으로 골라졌다. 단계는 다른 관계 재료가 없을 때의 기본값이다."""

    def test_other_relations_lead_over_steps(self):
        steps = {"flow_steps": ["주문", "확인", "픽업"], "solution_steps": ["주문", "확인", "픽업"]}
        for relation in (design.COMPARE, design.NETWORK, design.DEAL, design.MARKET):
            with self.subTest(relation):
                for category in ("웹개발", "원페이지"):
                    self.assertEqual(design.decide(category, dict(CASES[relation], **steps))["relation"], relation)
        self.assertEqual(design.decide("웹개발", dict(BARE, **steps))["relation"], design.STEPS)

    def test_ai_api_lets_another_relation_follow_the_processing_diagram(self):
        pipe = {"pipeline": {"input": "사진", "process": "분석", "output": "결과"}}
        self.assertEqual(design.decide("AI_API", dict(CASES[design.DEAL], **pipe))["relation"], design.DEAL)
        self.assertNotEqual(design.decide("AI_API", dict(BARE, **pipe))["relation"], design.STEPS)
