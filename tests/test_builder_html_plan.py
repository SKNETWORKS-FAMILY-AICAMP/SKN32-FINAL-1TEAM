"""T-B1이 사업계획서를 받으면 기능마다 계획서의 설명을 붙여 만든다(조율 요청 8, A안)."""
from unittest import TestCase

from engineering_agent.builder_html import _build_system_prompt, feature_notes

PLAN = ("점검콕은 설비 점검 일정과 고장 이력을 관리하는 웹서비스다.\n"
        "고장 신고 접수: 현장 작업자가 휴대폰으로 사진과 증상을 올리면 담당자에게 전달한다.\n"
        "부품 교체 이력: 설비마다 교체한 부품과 날짜, 비용을 기록해 검색할 수 있게 한다.")
FEATURES = ["고장 신고 접수", "부품 교체 이력", "월간 가동률 보고서"]


class PlanInPromptTests(TestCase):
    def test_notes_are_the_lines_that_define_each_feature(self):
        notes = feature_notes(FEATURES, PLAN)
        self.assertIn("사진과 증상", notes["고장 신고 접수"])
        self.assertNotIn("비용", notes["고장 신고 접수"])      # 다른 기능의 설명이 섞이지 않는다
        self.assertEqual(notes["월간 가동률 보고서"], "")        # 계획서가 정의하지 않은 기능

    def test_prompt_carries_the_plan_only_when_given(self):
        with_plan = _build_system_prompt(FEATURES, {"item_name": "점검콕"}, "웹개발", PLAN)
        self.assertIn("- 고장 신고 접수\n  계획서의 설명: 고장 신고 접수: 현장 작업자가", with_plan)
        self.assertIn("- 월간 가동률 보고서\n", with_plan)       # 설명이 없으면 이름만
        self.assertIn("14. 기능마다 '계획서의 설명'에 적힌 것을 화면에 빠짐없이", with_plan)
        self.assertIn("## 사업계획서 본문", with_plan)

        without = _build_system_prompt(FEATURES, {"item_name": "점검콕"}, "웹개발")
        for text in ("계획서의 설명", "14. 기능마다", "## 사업계획서 본문"):
            self.assertNotIn(text, without)

    def test_prompt_asks_for_one_line_wiring_and_a_sample_run(self):
        """메뉴 버튼을 id 배열 반복문으로 연결하면 채점(직접 연결)이 알아보지 못한다. 파일 입력만 있으면
        보는 사람이 시연을 시작할 수 없다. 두 카테고리 모두 지시한다."""
        for category in ("웹개발", "AI_API"):
            prompt = _build_system_prompt(FEATURES, {"item_name": "점검콕"}, category, PLAN)
            with self.subTest(category):
                self.assertIn("for · forEach 반복문으로 연결하는 것도", prompt)
                self.assertIn("'예시로 실행'", prompt)

    def test_run_tb1_passes_the_plan_when_the_contract_has_it(self):
        from unittest.mock import patch

        from tests import fake_sbrain

        patcher = fake_sbrain.install()
        self.addCleanup(patcher.stop)
        from engineering_agent import tasks
        from sbrain.contracts.tasks import TB1In
        from sbrain.models import ItemSpec, PlanDoc, PlanSection, Sentence

        seen = {}

        def fake_build(feature_list, item_spec, category, instruction, tools, plan_text="", previous_html=""):
            seen["plan_text"] = plan_text
            return {"status": "failed", "entryFilePath": None, "summary": "시험", "implementedFeatures": []}

        doc = PlanDoc(sections=[PlanSection(section_code="1", title="본문", sentences=[
            Sentence(sentence_id="s", text="고장 신고 접수: 사진과 증상을 올린다.", is_title=False, paragraph_no=1)])],
            feature_list=FEATURES, charts=[], tables=[], protected_tokens=[])
        spec = ItemSpec(item_name="점검콕", one_line_summary="요약", target_customer="고객",
                        core_features=FEATURES, category="웹개발", keywords=[])
        with patch.object(tasks, "build_prototype_html", fake_build):
            tasks.run_tb1(TB1In(feature_list=FEATURES, item_spec=spec, category="웹개발", instruction="만들어라",
                                plan_doc=doc), tools=None)
            self.assertIn("사진과 증상", seen["plan_text"])
            tasks.run_tb1(TB1In(feature_list=FEATURES, item_spec=spec, category="웹개발", instruction="만들어라"),
                          tools=None)
            self.assertEqual(seen["plan_text"], "")

    def test_rework_issues_are_not_appended_again(self):
        """조율이 문제 내용을 지시문 끝에 이미 붙여 넘긴다. 여기서 또 붙이면 두 번 들어간다."""
        from unittest.mock import patch

        from tests import fake_sbrain

        patcher = fake_sbrain.install()
        self.addCleanup(patcher.stop)
        from engineering_agent import tasks
        from sbrain.contracts.tasks import TB1In
        from sbrain.models import ItemSpec, ReworkInput

        seen = {}

        def fake_build(feature_list, item_spec, category, instruction, tools, plan_text="", previous_html=""):
            seen["instruction"] = instruction
            seen["previous_html"] = previous_html
            return {"status": "failed", "entryFilePath": None, "summary": "시험", "implementedFeatures": []}

        flow_instruction = "만들어라\n\n[재수행 — 문제가 된 내용]\n- E-B1-DEP: 외부 스크립트"
        spec = ItemSpec(item_name="점검콕", one_line_summary="요약", target_customer="고객",
                        core_features=FEATURES, category="웹개발", keywords=[])
        rework = ReworkInput(mode="재수행", previous_result_ref="prototype@1",
                             issues=["E-B1-DEP: 외부 스크립트"], is_final_attempt=False)
        with patch.object(tasks, "build_prototype_html", fake_build):
            tasks.run_tb1(TB1In(feature_list=FEATURES, item_spec=spec, category="웹개발",
                                instruction=flow_instruction, rework_input=rework), tools=None)
        self.assertEqual(seen["instruction"], flow_instruction)
        self.assertEqual(seen["previous_html"], "")  # 이전 원문이 오지 않으면 처음부터 만든다

        rework = ReworkInput(mode="재수행", previous_result_ref="prototype@1", issues=["E-B1-DEP: 외부 스크립트"],
                             is_final_attempt=False, previous_source_text="<html>이전</html>")
        with patch.object(tasks, "build_prototype_html", fake_build):
            tasks.run_tb1(TB1In(feature_list=FEATURES, item_spec=spec, category="웹개발",
                                instruction=flow_instruction, rework_input=rework), tools=None)
        self.assertEqual(seen["previous_html"], "<html>이전</html>")


class PreviousHtmlTests(TestCase):
    """재실행에 이전 HTML이 오면 처음부터 새로 만들지 않고 그 HTML의 문제만 고치게 한다."""

    def test_previous_html_is_handed_over_as_the_thing_to_fix(self):
        from engineering_agent.builder_html import user_message

        self.assertEqual(user_message("만들어라"), "만들어라")
        self.assertEqual(user_message("만들어라", "   "), "만들어라")
        message = user_message("만들어라\n\n[재수행 — 문제가 된 내용]\n- 버튼 연결 없음", "<html>이전</html>")
        self.assertTrue(message.startswith("만들어라\n\n[재수행 — 문제가 된 내용]"))
        self.assertIn("문제 내용만 고쳐라", message)
        self.assertIn("<이전HTML>\n<html>이전</html>\n</이전HTML>", message)
        # 이전 HTML을 파일 이름 없는 ```html 블록으로 보여 주지 않는다(모델이 그 꼴을 따라 쓰면 형식 오류).
        self.assertNotIn("```html\n", message)

    def test_failed_self_check_still_returns_the_html(self):
        """자체 검사에 걸려도 원문은 돌려준다 — 조율이 재수행 때 previous_source_text로 다시 넘긴다.
        파일은 저장하지 않는다."""
        from engineering_agent.builder_html import build_prototype_html

        class _Tools:
            def __init__(self, reply):
                self.reply = reply

            def llm(self, messages, *, parse=None, **kwargs):
                return parse(self.reply)

        html = '<html lang="ko"><head><script src="https://cdn.example.com/x.js"></script></head></html>'
        result = build_prototype_html(["조회"], {"item_name": "t"}, "웹개발", "생성",
                                      _Tools(f"```html:index.html\n{html}\n```"))
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["entryFilePath"])
        self.assertEqual(result["sourceText"].strip(), html)


class DesignDirectionTests(TestCase):
    """규칙 8의 고정 예시 색만 주었더니 모든 사업이 남색 · 파랑 대시보드로 나왔다(실측: 실제 예시 계획서 셋)."""

    SPECS = {
        "반려동물 피부 AI 앱": ({"itemName": "반려동물 피부 AI 앱", "oneLineSummary": "보호자가 찍은 피부 사진을 AI로 분석",
                             "targetCustomer": "확인 필요"}, ["피부 사진 AI 분석", "위험도 안내"]),
        "재고 자동발주 SaaS": ({"itemName": "재고 자동발주 SaaS", "oneLineSummary": "POS 판매 데이터를 학습해 발주",
                             "targetCustomer": "확인 필요"}, ["수요예측 모델 고도화", "발주 자동화 기능"]),
    }

    def test_prototype_uses_the_same_theme_as_the_infographic(self):
        from engineering_agent.builder_html import palette
        from engineering_agent.infographic import themes

        for spec, features in self.SPECS.values():
            infographic = themes.pick({"item_name": spec["itemName"], "item_summary": spec["oneLineSummary"],
                                       "target_users": spec["targetCustomer"], "features": features})
            self.assertEqual(palette(features, spec)["name"], infographic)
        self.assertNotEqual(*[palette(f, s)["name"] for s, f in self.SPECS.values()])

    def test_prompt_carries_the_palette_and_a_task_first_screen(self):
        spec, features = self.SPECS["반려동물 피부 AI 앱"]
        prompt = _build_system_prompt(features, spec, "AI_API")
        from engineering_agent.builder_html import palette

        p = palette(features, spec)
        for role in ("ink", "accent", "tint", "bg"):
            self.assertIn(p[role], prompt)
        self.assertIn("'피부 사진 AI 분석'을(를) 바로 해 볼 수 있는 작업 화면", prompt)
        self.assertNotIn("#1D4ED8", prompt)  # 예전 고정 예시 버튼 색
        self.assertIn("`<h1>`은 문서 전체에 하나", prompt)  # 화면을 나눠도 h1 하나(실측: 화면마다 h1 → 제목 계층 0점)
        self.assertNotIn("color:#0F172A; background-color:#FFFFFF", prompt)


class BaseCssTests(TestCase):
    """말로만 디자인을 지시하면 버튼 · 카드 · 글꼴이 매번 평범한 기본 모양이고, 모델이 색을 새로 만들다 대비를 어겼다.
    검증된 기본 CSS를 그대로 넣게 한다. 이 CSS는 모든 색 테마에서 검증-2 4번(대비) · 6번(폭)을 통과해야 한다."""

    def test_base_css_passes_contrast_and_width_in_every_theme(self):
        from engineering_agent.html_kit import base_css
        from engineering_agent.infographic.themes import THEMES
        from verification_agent.rules.r4 import check_html

        for name, colors in THEMES.items():
            with self.subTest(name):
                page = f'<!doctype html><html lang="ko"><head><style>{base_css(colors)}</style></head><body><h1>x</h1></body></html>'
                items = {i["id"]: i for i in check_html(page)}
                self.assertTrue(items[4]["passed"], items[4]["evidence"])
                self.assertTrue(items[6]["passed"], items[6]["evidence"])
                self.assertNotIn("var(--", base_css(colors))  # 규칙 8: CSS 변수로 흘리지 않는다

    def test_prompt_carries_the_base_css_frames_and_state_rules(self):
        from engineering_agent.builder_html import palette
        from engineering_agent.html_kit import FRAMES, base_css

        spec, features = DesignDirectionTests.SPECS["재고 자동발주 SaaS"]
        prompt = _build_system_prompt(features, spec, "웹개발")
        self.assertIn(base_css(palette(features, spec)), prompt)
        self.assertIn("`app-side`", prompt)  # 앱 틀은 오른쪽 설명 패널과 함께(데스크톱 폭을 비우지 않는다)
        for cls in FRAMES:
            self.assertIn(f"`{cls}`", prompt)
        for part in ('class="loading"', "`toast`", "`empty`", "`field-error`", "`steps`", "innerHTML)로"):
            self.assertIn(part, prompt)


class FontAndIconKitTests(TestCase):
    """글꼴(Pretendard) · 아이콘 묶음은 모델이 옮겨 쓸 수 없어 저장 직전에 코드가 넣는다."""

    PAGE = ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>{css}</style></head><body>'
            '<h1>재고</h1><button id="b" class="btn"><svg class="icon"><use href="#i-cart"/></svg>주문</button>'
            '<svg class="icon icon-lg" aria-label="알림"><use href="#i-bell"/></svg>'
            '<script>document.getElementById("b").addEventListener("click", () => {});</script></body></html>')

    def _page(self):
        from engineering_agent.builder_html import palette
        from engineering_agent.html_kit import base_css

        spec, features = DesignDirectionTests.SPECS["재고 자동발주 SaaS"]
        return self.PAGE.replace("{css}", base_css(palette(features, spec)))

    def test_decorated_page_keeps_full_code_score_and_passes_self_checks(self):
        from engineering_agent import gates
        from engineering_agent.html_kit import decorate
        from verification_agent.rules.gates import find_secret
        from verification_agent.rules.r4 import check_html

        page = decorate(self._page())
        self.assertIn('<style data-kit="font">', page)
        self.assertIn('<symbol id="i-cart"', page)
        self.assertIn('aria-label="주문"', page)          # 대체 텍스트가 없던 아이콘에 뜻을 붙임
        self.assertIn('aria-label="알림"', page)          # 있던 것은 그대로
        failed = [(i["id"], i["evidence"]) for i in check_html(page) if not i["passed"] and i["id"] in (2, 4, 6, 7)]
        self.assertEqual(failed, [])
        self.assertEqual(gates.check_external_dependency_gate(page), (True, []))  # data: 글꼴은 외부가 아님
        self.assertIsNone(find_secret(page))  # 글꼴 base64가 비밀값으로 잡히지 않음

    def test_strip_removes_the_kit_for_rework_prompts_and_decorate_is_idempotent(self):
        from engineering_agent.builder_html import user_message
        from engineering_agent.html_kit import decorate, strip

        page = self._page()
        once = decorate(page)
        self.assertEqual(decorate(once), once)
        self.assertNotIn("data-kit", strip(once))
        message = user_message("고쳐라", once)
        self.assertNotIn("base64", message)
        self.assertLess(len(message), len(once) // 10)  # 글꼴 약 580KB가 프롬프트에 실리지 않음

    def test_prompt_lists_icons_without_asking_the_model_to_draw_them(self):
        spec, features = DesignDirectionTests.SPECS["반려동물 피부 AI 앱"]
        prompt = _build_system_prompt(features, spec, "AI_API")
        self.assertIn('<use href="#i-이름"/>', prompt)
        self.assertIn("cart(주문 · 장바구니)", prompt)
        self.assertNotIn("base64", prompt)
