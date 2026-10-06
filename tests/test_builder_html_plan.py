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
