"""아이콘 모음판(artsheet.py): 항목 모으기 · 뼈대 · 칸 찾기 · 지면에 넣기 · 이미지 통로가 없을 때의 대체."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from engineering_agent.infographic import artsheet
from engineering_agent.infographic.render import render_infographic
from tests.test_infographic_composer import DATA, EVERY_BLOCK
from verification_agent.score import compute_infographic_check

PAGE = dict(DATA, layout=EVERY_BLOCK)


def _drawn(wire: bytes, blank: tuple[int, ...] = ()) -> bytes:
    """뼈대의 칸마다 가운데에 진한 네모(아이콘 선)를 그린 그림. blank 번째 칸은 비워 둔다."""
    cells = artsheet.find_cells(wire)
    marks = [(x + w // 3, y + h // 3, w // 3, h // 3, (20, 60, 40))
             for n, (x, y, w, h) in enumerate(cells) if n not in blank]
    return artsheet.wire_png(dict(enumerate(cells)), marks)


class _Tools:
    """tools.image는 받은 뼈대의 칸마다 아이콘을 그려 돌려준다."""

    def __init__(self, reply=None, blank=()):
        self.prompts, self.reply, self.blank = [], reply, blank

    def image(self, prompt, *, image=None, size="", quality="", purpose=""):
        self.prompts.append(prompt)
        return self.reply if self.reply is not None else _drawn(image, self.blank)


class ItemTests(TestCase):
    def test_items_follow_the_page_content(self):
        items = dict(artsheet.icon_items("원페이지", PAGE))
        for feature in PAGE["features"]:
            self.assertIn(artsheet.key("feature", feature), items)
        self.assertLessEqual(len(items), 20)

    def test_numbers_are_not_handed_to_the_image_model(self):
        """숫자를 넘기면 아이콘 안에 그 숫자가 그려진다. 그림 속 숫자는 확인할 수 없다."""
        data = dict(PAGE, key_metrics=[{"value": "40곳", "label": "24개월 계약 지자체"}],
                    problem="하루 평균 60건, 7분씩 걸린다")
        prompt = artsheet.sheet_prompt(data, artsheet.icon_items("원페이지", data), "초록")
        self.assertNotRegex(prompt.split("그림체")[1], r"\d")
        self.assertIn("계약 지자체", prompt)

    def test_hero_composition_follows_the_plan_relations_not_the_name(self):
        """모든 지면 맨 위가 '세 칸 + 화살표'면 계획서가 달라도 첫인상이 같다. 구도는 계획서 재료가
        보여 주는 관계로 고른다. 그림 아래에 세 구역 글이 붙는 지면(journey · AI API)은 세 구역을 지킨다."""
        journey = [{"block": "hero", "variant": "journey"}, {"block": "features", "variant": "band"}]
        free = [{"block": "problem_solution", "variant": "split"}, {"block": "features", "variant": "band"}]

        def kind(category, **over):
            return artsheet.hero_kind(category, dict(PAGE, **over))[0]

        self.assertEqual(kind("AI_API", layout=free), "steps")
        self.assertEqual(kind("원페이지", layout=journey), "panorama")
        parties = dict(target_users="동네 매장", revenue_flow={"payer": "본사"},
                       effects=[{"who": "손님", "what": "대기 없음"}])
        self.assertEqual(kind("원페이지", layout=free, **parties), "hub")
        self.assertEqual(kind("원페이지", layout=free, effects=[], revenue_flow={},
                              solution_steps=["접수", "분석", "안내"]), "steps")
        self.assertEqual(kind("원페이지", layout=free + [{"block": "process", "variant": "steps"}], effects=[],
                              revenue_flow={}, solution_steps=["접수", "분석", "안내"]), "scene")
        # 이름만 다르고 내용이 같으면 같은 구도(이름 해시로 고르지 않는다)
        self.assertEqual(kind("원페이지", layout=free, item_name="가", **parties),
                         kind("원페이지", layout=free, item_name="나", **parties))

        def hero(category, layout, **over):
            data = dict(PAGE, layout=layout, **over)
            prompt = artsheet.sheet_prompt(data, artsheet.icon_items(category, data), "초록", category)
            return prompt.split("맨 위 넓은 칸: ")[1].split("\n")[0]

        self.assertIn("3분의 1", hero("원페이지", journey))
        self.assertIn("허브", hero("원페이지", free, **parties))
        self.assertIn("대표 장면", hero("원페이지", free, effects=[], revenue_flow={}, solution_steps=[]))


class WireAndCellsTests(TestCase):
    def test_cells_are_read_back_from_the_wireframe(self):
        names = ["hero"] + [f"i{n}" for n in range(11)]
        cells = artsheet.wire_cells(names)
        self.assertEqual(artsheet.find_cells(artsheet.wire_png(cells)), [cells[n] for n in names])

    def test_cells_follow_the_image_not_the_wireframe(self):
        """이미지 모델은 칸을 조금씩 다시 나눈다. 자리는 받은 그림에서 읽는다."""
        moved = {"hero": (40, 50, 940, 300), "a": (40, 400, 440, 250), "b": (520, 400, 460, 250)}
        self.assertEqual(artsheet.find_cells(artsheet.wire_png(moved)), list(moved.values()))


class GenerateTests(TestCase):
    def test_no_image_tool_means_no_art(self):
        self.assertIsNone(artsheet.generate("원페이지", PAGE, object()))

    def test_cell_count_mismatch_falls_back(self):
        tools = _Tools(reply=artsheet.wire_png({"hero": (32, 32, 960, 400)}))
        self.assertIsNone(artsheet.generate("원페이지", PAGE, tools))
        self.assertEqual(len(tools.prompts), 2)  # 한 번 더 그려 보고 포기한다

    def test_blank_tile_is_left_to_the_default_icon(self):
        """모델이 칸 하나를 타일만 칠하고 비워 두면 그 자리는 기본 아이콘으로 나간다."""
        names = [artsheet.HERO] + [name for name, _ in artsheet.icon_items("원페이지", PAGE)]
        art = artsheet.generate("원페이지", PAGE, _Tools(blank=(2,)))
        self.assertNotIn(names[2], art["cells"])
        self.assertEqual(len(art["cells"]), len(names) - 1)
        self.assertEqual(artsheet.icon({"_art": art}, names[2], 100, 100, 60), "")

    def test_failed_call_falls_back(self):
        class Broken:
            def image(self, *a, **k):
                raise TimeoutError

        self.assertIsNone(artsheet.generate("원페이지", PAGE, Broken()))

    def test_prompt_forbids_text_and_lists_every_item(self):
        tools = _Tools()
        art = artsheet.generate("원페이지", PAGE, tools)
        self.assertIn("글자, 숫자, 글자 비슷한 무늬", tools.prompts[0])
        self.assertEqual(list(art["cells"])[0], artsheet.HERO)
        self.assertEqual(len(art["cells"]), 1 + len(artsheet.icon_items("원페이지", PAGE)))


class PageTests(TestCase):
    def _render(self, with_art: bool):
        data = dict(PAGE)
        if with_art:
            data["_art"] = artsheet.generate("원페이지", data, _Tools())
        with TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            with patch("engineering_agent.infographic.render._OUTPUT_DIR", Path(directory)):
                saved = render_infographic("원페이지", data)
            return saved, compute_infographic_check(saved["file_path"], saved["source_text"], "열람")

    def test_page_with_icons_keeps_text_rules_and_full_score(self):
        saved, checked = self._render(with_art=True)
        source = saved["source_text"]
        self.assertEqual(source.count('id="art-sheet"'), 1)          # 그림 원본은 한 번만 싣는다
        self.assertGreaterEqual(source.count('data-role="art"'), 6)  # 대표 도식 + 항목 아이콘
        self.assertEqual(checked["total"], 15, [(i["name"], i["evidence"]) for i in checked["items"]
                                                if not i["passed"]])
        self.assertEqual(checked["gate_failures"], [])

    def test_raster_rule_counts_only_what_is_shown(self):
        _, checked = self._render(with_art=True)
        evidence = next(i["evidence"] for i in checked["items"] if i["id"] == 7)
        ratio = float(evidence.split("면적 ")[1].split("%")[0])
        self.assertLess(ratio, 35.0, evidence)   # 모음판 전체(지면보다 큼)가 아니라 보이는 자리만

    def test_page_without_art_is_unchanged(self):
        saved, checked = self._render(with_art=False)
        self.assertNotIn("art-sheet", saved["source_text"])
        self.assertEqual(checked["total"], 15)
