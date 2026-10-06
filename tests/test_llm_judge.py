"""계획서 대조의 LLM 판정(llm_judge.py)과 규칙 → LLM 두 단계 합산(feature_match.py)."""
import threading
from unittest import TestCase

from verification_agent.feature_match import match_features
from verification_agent.llm_judge import (build_messages, make_judge, onepage_view, parse_verdict,
                                          plan_excerpt, settle)
from verification_agent.rules.items import banded

HTML = """<!doctype html><html lang="ko"><head><style>body{color:#000}</style></head><body>
<h1>반찬온</h1>
<button id="order" data-feature="반찬 사전주문">반찬 사전주문</button>
<button id="pickup" data-feature="픽업 시간 예약">픽업 시간 예약</button>
<button id="stock" data-feature="재고 알림">재고 알림</button>
<p id="out"></p>
<script>
document.getElementById('order').addEventListener('click', () => { out.textContent = '주문 완료'; });
document.getElementById('pickup').addEventListener('click', () => {});
</script></body></html>"""
FEATURES = ["반찬 사전주문", "픽업 시간 예약", "재고 알림"]
PLAN = ("반찬 사전주문은 손님이 전날 밤까지 다음 날 반찬을 골라 주문하는 기능이다.\n"
        "픽업 시간 예약은 30분 단위로 방문 시간을 정한다.\n"
        "가게당 월 이용료는 29000원이다.")


class _Tools:
    """기능마다 정해 둔 답을 돌려준다. 호출된 기능과 스레드를 기록한다."""

    def __init__(self, answers):
        self.answers = answers
        self.asked = []
        self.threads = set()
        self._lock = threading.Lock()

    def llm(self, messages, *, schema=None, parse=None, purpose=""):
        feature = messages[1]["content"].split("[판정할 기능]\n", 1)[1].split("\n", 1)[0]
        with self._lock:
            self.asked.append(feature)
            self.threads.add(threading.get_ident())
        answer = self.answers[feature]
        if isinstance(answer, Exception):
            raise answer
        return parse(answer)


class ParseVerdictTests(TestCase):
    def test_reads_fenced_json_and_three_levels(self):
        self.assertEqual(parse_verdict('```json\n{"reason": "핸들러가 비어 있음", "verdict": "미충족"}\n```'),
                         (0.0, "핸들러가 비어 있음"))
        self.assertEqual(parse_verdict('{"reason": "사진 첨부 없음", "verdict": " 부분 "}'), (0.5, "사진 첨부 없음"))
        self.assertEqual(parse_verdict('{"reason": "목록에 추가됨", "verdict": "충족"}'), (1.0, "목록에 추가됨"))

    def test_missing_reason_is_a_format_error(self):
        for text in ("", "됨", '{"verdict": "충족"}', '{"reason": "", "verdict": "충족"}',
                     '{"reason": "x", "verdict": "됨"}', '{"reason": "x", "implemented": true}'):
            with self.assertRaises(Exception, msg=text):
                parse_verdict(text)


class MaterialTests(TestCase):
    def test_plan_excerpt_keeps_only_lines_about_the_feature(self):
        excerpt = plan_excerpt("픽업 시간 예약", PLAN)
        self.assertIn("30분 단위", excerpt)
        self.assertNotIn("29000원", excerpt)
        self.assertIn("전달되지 않음", plan_excerpt("픽업 시간 예약", None))

    def test_onepage_view_lists_marked_text_without_embedded_assets(self):
        svg = ('<svg xmlns="http://www.w3.org/2000/svg"><style>@font-face{src:url(data:font/woff2;base64,AAAA)}</style>'
               '<text data-field="feature_detail" data-feature="재고 알림">5개 이하면 알린다</text>'
               '<text>표식 없음</text></svg>')
        view = onepage_view(svg)
        self.assertEqual(view, "[feature_detail · 재고 알림] 5개 이하면 알린다\n표식 없음")

    def test_messages_hold_one_feature_and_ask_reason_first(self):
        system, user = build_messages("재고 알림", "- 설명", "<html>", "html")
        self.assertIn("reason을 먼저", system["content"])
        self.assertIn("한 파일로 도는 프로토타입", system["content"])
        # 산출물이 앞, 기능이 뒤 — 같은 산출물의 호출끼리 앞부분이 같다.
        self.assertTrue(user["content"].startswith("[산출물: HTML"))
        self.assertIn("[판정할 기능]\n재고 알림\n", user["content"])

    def test_html_view_drops_styling_but_keeps_handles(self):
        from verification_agent.llm_judge import html_view

        view = html_view(HTML.replace('<button id="order"', '<!-- 메모 --><button class="btn big" '
                                      'style="color:red" aria-pressed="false" aria-label="주문" id="order"'))
        for gone in ("<style", "<head", "메모", "class=", "aria-pressed", "color:red"):
            self.assertNotIn(gone, view)
        for kept in ('id="order"', 'data-feature="반찬 사전주문"', 'aria-label="주문"', "addEventListener"):
            self.assertIn(kept, view)


class TwoStageMatchTests(TestCase):
    def test_llm_only_rejudges_features_the_rules_passed(self):
        tools = _Tools({
            "반찬 사전주문": '{"reason": "클릭하면 주문 완료 문구를 보여 줌", "verdict": "충족"}',
            "픽업 시간 예약": '{"reason": "핸들러가 비어 있어 시간을 고를 수 없음", "verdict": "미충족"}',
        })
        # 재고 알림 버튼은 연결이 없어 규칙에서 떨어진다 → LLM에 묻지 않는다.
        result = match_features(FEATURES, HTML, "html", PLAN, make_judge(tools, "html", HTML, PLAN))
        self.assertEqual(sorted(set(tools.asked)), ["반찬 사전주문", "픽업 시간 예약"])
        self.assertEqual(len(tools.asked), 6)  # 기능마다 세 번
        self.assertEqual(result["missing_features"], ["픽업 시간 예약", "재고 알림"])
        self.assertEqual(result["score"], 5.0)  # 15 × 1/3
        self.assertIn("픽업 시간 예약: 핸들러가 비어 있어 시간을 고를 수 없음", result["findings"])
        self.assertIn("LLM 확인 2건: 충족 1 · 부분 0 · 미충족 1", result["findings"][0])
        self.assertEqual(result["judged_by"], "htmlParse")

    def test_failed_call_keeps_the_rule_verdict(self):
        tools = _Tools({"반찬 사전주문": RuntimeError("소진"),
                        "픽업 시간 예약": '{"reason": "예약 동작", "verdict": "충족"}'})
        result = match_features(FEATURES, HTML, "html", PLAN, make_judge(tools, "html", HTML, PLAN))
        self.assertEqual(result["missing_features"], ["재고 알림"])
        self.assertIn("LLM 판정 실패 1건은 규칙 결과로 대체", result["findings"][0])

    def test_partial_counts_half_and_is_not_a_missing_feature(self):
        tools = _Tools({"반찬 사전주문": '{"reason": "결제 단계 없음", "verdict": "부분"}',
                        "픽업 시간 예약": '{"reason": "예약 동작", "verdict": "충족"}'})
        result = match_features(FEATURES, HTML, "html", PLAN, make_judge(tools, "html", HTML, PLAN))
        self.assertEqual(result["missing_features"], ["재고 알림"])
        self.assertEqual(result["score"], 7.5)  # 15 × 1.5/3
        self.assertIn("반찬 사전주문: 부분 인정 — 결제 단계 없음", result["findings"])
        self.assertTrue(result["findings"][0].startswith("인정 1.5/3개"))
        # 조율은 findings 문구가 아니라 이 칸으로 재작성 사유를 만든다. 누락 목록과 겹치지 않는다.
        self.assertEqual(result["partial_features"], ["반찬 사전주문"])
        self.assertFalse(result["withheld"])

    def test_empty_feature_list_is_withheld_not_scored(self):
        result = match_features([], HTML, "html", PLAN, None)
        self.assertEqual(result["score"], 0.0)
        self.assertTrue(result["withheld"])
        self.assertEqual(result["withheld_reason"], "E-V2-NOFEATURE")
        self.assertEqual((result["missing_features"], result["partial_features"]), ([], []))

    def test_without_tools_the_rules_decide_alone(self):
        self.assertIsNone(make_judge(None, "html", HTML, PLAN))
        result = match_features(FEATURES, HTML, "html", PLAN, None)
        self.assertEqual(result["missing_features"], ["재고 알림"])

    def test_features_are_judged_in_parallel(self):
        barrier = threading.Barrier(2, timeout=5)

        class _Waiting(_Tools):
            def llm(self, messages, **kwargs):
                barrier.wait()  # 두 호출이 동시에 떠 있어야 통과한다
                return super().llm(messages, **kwargs)

        tools = _Waiting({f: '{"reason": "동작", "verdict": "충족"}' for f in FEATURES[:2]})
        make_judge(tools, "html", HTML, PLAN)(FEATURES[:2])
        self.assertGreaterEqual(len(tools.threads), 2)


class SettleTests(TestCase):
    def test_median_of_votes_with_its_reason(self):
        self.assertEqual(settle([(0.0, "없음"), (0.5, "일부"), (1.0, "다 됨")]), (0.5, "일부"))
        self.assertEqual(settle([(0.5, "일부"), (0.0, "없음"), (0.5, "일부2")]), (0.5, "일부"))
        self.assertEqual(settle([(1.0, "다 됨"), None, (0.0, "없음")]), (0.0, "없음"))  # 둘이면 낮은 쪽
        self.assertIsNone(settle([None, None, None]))


class FieldWiringTests(TestCase):
    """입력칸은 자기 이벤트가 없어도 버튼 핸들러가 값을 읽어 가면 동작에 쓰이는 것이다."""

    PAGE = """<html lang="ko"><body><h1>신고</h1>
<label for="title">제목</label><input id="title" data-feature="신고 접수">
<label for="memo">메모</label><input id="memo" data-feature="신고 접수">
<button id="send">접수</button><button id="dead">취소</button><ul id="list"></ul>
<script>
document.getElementById('send').addEventListener('click', function () {
  var li = document.createElement('li');
  li.textContent = document.getElementById('title').value;
  document.getElementById('list').appendChild(li);
});
</script></body></html>"""

    def test_field_read_by_a_handler_counts_but_unread_field_and_dead_button_do_not(self):
        from verification_agent.rules.r4 import check_html

        wiring = check_html(self.PAGE, None)[0]
        self.assertIn("2/4개 연결", wiring["evidence"])   # title 입력칸 + send 버튼
        self.assertIn("'취소'", wiring["evidence"])
        self.assertEqual(wiring["earned"], 1.0)          # 50% 구간


class RuleAccuracyTests(TestCase):
    def test_helper_written_as_a_function_expression_counts_as_direct_wiring(self):
        """모델이 도우미를 `const $ = function (id) {...}`로 쓰기도 한다. 화살표 · 선언문과 같은 것이다."""
        from verification_agent.rules.wiring import wired_ids

        for helper in ("const $ = function (id) { return document.getElementById(id); };",
                       "const $ = id => document.getElementById(id);",
                       "function $(id) { return document.getElementById(id); }"):
            self.assertEqual(wired_ids(helper + '\n$("send").addEventListener("click", go);'), {"send"}, helper)

    def test_nested_svg_is_part_of_the_outer_image(self):
        """svg 안의 svg(그림 조각 자리)는 따로 대체 텍스트를 요구하지 않는다."""
        from verification_agent.rules.r4 import check_html

        page = '<html lang="ko"><body><h1>x</h1></body></html>'
        inner = '<svg data-role="art" x="0" y="0" width="10" height="10"><use href="#a"/></svg>'
        with_title = f'<svg xmlns="http://www.w3.org/2000/svg"><title>인포그래픽</title>{inner}{inner}</svg>'
        without = f'<svg xmlns="http://www.w3.org/2000/svg">{inner}</svg>'
        self.assertTrue(check_html(page, with_title)[1]["passed"])
        self.assertFalse(check_html(page, without)[1]["passed"])

    def test_important_flag_is_not_part_of_the_colour(self):
        from verification_agent.rules.color import parse_color

        self.assertEqual(parse_color("#8A4A00 !important"), parse_color("#8A4A00"))
        self.assertIsNotNone(parse_color("#FFF1D6 !important"))


class BandTests(TestCase):
    def test_partial_credit_steps_down_by_band(self):
        self.assertEqual([round(banded(3, ok, 6), 4) for ok in range(7)], [0, 0, 0, 1, 1, 2, 3])
        self.assertEqual(banded(3, 0, 0), 0.0)


class OnepageKeyFieldTests(TestCase):
    """원페이지는 기능 설명에 더해 문제 · 해결 · 수익모델 · 일정 네 칸도 계획서와 대조한다."""

    PLAN = ("폐기가 많고 대기가 길다.\n전날 주문을 받아 조리량을 정한다.\n"
            "반찬 사전주문은 손님이 전날 밤까지 다음 날 반찬을 골라 주문하는 기능이다.\n"
            "가게당 월 이용료는 29000원이다.\n2026년 11월 개발에 착수한다.")
    SVG = ('<svg xmlns="http://www.w3.org/2000/svg">'
           '<text data-field="feature_detail" data-feature="반찬 사전주문">손님이 전날 밤까지 다음 날 반찬을 골라 주문</text>'
           '<text data-field="problem">폐기가 많고 대기가 길다</text>'
           '<text data-field="solution">드론으로 반찬을 배달한다</text>'
           '<text data-field="revenue_unit_price">29000원</text>'
           '<text data-field="revenue_unit_price">가게당 월 이용료 29000원</text>'
           '<text data-field="timeline_baseline">2026년 11월 개발 착수</text></svg>')

    class Tools:
        def __init__(self, answers):
            self.answers, self.asked = answers, []
            self._lock = threading.Lock()

        def llm(self, messages, *, schema=None, parse=None, purpose=""):
            label = messages[1]["content"].split("[판정할 칸]\n", 1)[1].split(" — ", 1)[0]
            with self._lock:
                self.asked.append((label, messages[1]["content"].split("[지면에 적힌 내용]\n", 1)[1]))
            answer = self.answers[label]
            if isinstance(answer, Exception):
                raise answer
            return parse(answer)

    OK = '{"reason": "계획서와 같은 뜻", "verdict": "충족"}'

    def _match(self, answers, svg=None):
        from verification_agent.llm_judge import make_field_judge

        tools = self.Tools(answers)
        result = match_features(["반찬 사전주문"], svg or self.SVG, "svg-onepage", self.PLAN, None,
                                make_field_judge(tools, self.PLAN))
        return tools, result

    def test_wrong_summary_loses_points_but_is_not_a_missing_feature(self):
        tools, result = self._match({
            "문제 정의": self.OK, "수익모델 단가": self.OK, "추진 일정": self.OK,
            "해결 방안": '{"reason": "계획서에 드론 배달이 없음", "verdict": "미충족"}'})
        self.assertEqual(result["score"], 12.0)                 # 15 × (기능 1 + 칸 3) / (1 + 4)
        self.assertEqual(result["missing_features"], [])        # 칸 이름은 누락 기능 목록에 넣지 않는다
        self.assertIn("해결 방안: 계획서에 드론 배달이 없음", result["findings"])
        self.assertIn("핵심 칸 3/4", result["findings"][0])
        self.assertEqual(len(tools.asked), 12)                  # 칸 4개 × 3번
        revenue = next(text for label, text in tools.asked if label == "수익모델 단가")
        self.assertEqual(revenue, "29000원 / 가게당 월 이용료 29000원")   # 나뉜 글자 노드를 이어 붙인다

    def test_partial_counts_half(self):
        _, result = self._match({"문제 정의": self.OK, "수익모델 단가": self.OK, "추진 일정": self.OK,
                                 "해결 방안": '{"reason": "핵심이 빠짐", "verdict": "부분"}'})
        self.assertEqual(result["score"], 13.5)                 # 15 × 4.5 / 5
        self.assertIn("해결 방안: 부분 인정 — 핵심이 빠짐", result["findings"])

    def test_failed_call_is_not_penalised(self):
        _, result = self._match({"문제 정의": self.OK, "수익모델 단가": self.OK, "추진 일정": self.OK,
                                 "해결 방안": RuntimeError("소진")})
        self.assertEqual(result["score"], 15.0)
        self.assertIn("LLM 판정 실패 1건은 감점하지 않음", result["findings"][0])

    def test_missing_field_on_the_page_gets_no_credit(self):
        svg = self.SVG.replace('<text data-field="solution">드론으로 반찬을 배달한다</text>', "")
        tools, result = self._match({"문제 정의": self.OK, "수익모델 단가": self.OK, "추진 일정": self.OK}, svg)
        self.assertEqual(result["score"], 12.0)
        self.assertIn("해결 방안: 지면에 없거나 자리 채움 문구", result["findings"])
        self.assertNotIn("해결 방안", [label for label, _ in tools.asked])

    def test_without_llm_the_four_fields_are_left_out(self):
        from verification_agent.llm_judge import make_field_judge

        self.assertIsNone(make_field_judge(None, self.PLAN))
        self.assertIsNone(make_field_judge(self.Tools({}), None))
        result = match_features(["반찬 사전주문"], self.SVG, "svg-onepage", self.PLAN)
        self.assertEqual(result["score"], 15.0)                 # 분모는 기능 수 그대로
        self.assertNotIn("핵심 칸", result["findings"][0])


class ElementJudgeTests(TestCase):
    """기능의 정의 문장을 요소로 나눠 요소마다 있음/없음을 받는다. 요소 목록은 한 번 뽑아 저장한다."""

    def setUp(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        from verification_agent import llm_judge

        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = patch.object(llm_judge, "ELEMENT_STORE", Path(folder.name) / "elements.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    class Tools:
        """요소 뽑기에는 정해 둔 목록을, 요소 판정에는 정해 둔 있음/없음을 답한다."""

        def __init__(self, elements, present):
            self.elements, self.present = elements, present
            self.extractions, self.checks = [], []
            self._lock = threading.Lock()

        def llm(self, messages, *, schema=None, parse=None, purpose=""):
            import json

            user = messages[1]["content"]
            if "[이 기능의 정의]" in user:
                feature = user.split("[기능]\n", 1)[1].split("\n", 1)[0]
                with self._lock:
                    self.extractions.append(feature)
                return parse(json.dumps({"elements": self.elements[feature]}, ensure_ascii=False))
            feature = user.split("[판정할 기능]\n", 1)[1].split("\n", 1)[0]
            with self._lock:
                self.checks.append(feature)
            listed = [line.split(". ", 1)[1] for line in user.split("[확인할 요소]\n", 1)[1].splitlines()]
            return parse(json.dumps({"checks": [
                {"element": e, "reason": "확인", "present": self.present[e]} for e in listed]}, ensure_ascii=False))

    ELEMENTS = {"반찬 사전주문": ["다음 날 반찬 선택", "주문"], "픽업 시간 예약": ["30분 단위", "방문 시간"]}
    PRESENT = {"다음 날 반찬 선택": True, "주문": True, "30분 단위": False, "방문 시간": True}

    def test_definition_is_only_the_lines_naming_the_feature(self):
        from verification_agent.llm_judge import definition

        self.assertEqual(definition("픽업 시간 예약", PLAN), "- 픽업 시간 예약은 30분 단위로 방문 시간을 정한다.")
        self.assertEqual(definition("재고 알림", PLAN), "")   # 계획서가 정의하지 않은 기능
        self.assertEqual(definition("픽업 시간 예약", None), "")

    def test_credit_is_the_share_of_elements_present(self):
        tools = self.Tools(self.ELEMENTS, self.PRESENT)
        result = match_features(FEATURES, HTML, "html", PLAN, make_judge(tools, "html", HTML, PLAN))
        self.assertEqual(result["missing_features"], ["재고 알림"])       # 규칙에서 떨어진 기능만 누락
        self.assertEqual(result["score"], 7.5)                            # 15 × (1 + 0.5 + 0) / 3
        self.assertIn("픽업 시간 예약: 부분 인정 — 요소 2개 중 1개 있음 — 빠진 요소: 30분 단위", result["findings"])
        self.assertEqual(len(tools.checks), 6)                            # 기능 2개 × 3번

    def test_elements_are_extracted_once_and_reused(self):
        tools = self.Tools(self.ELEMENTS, self.PRESENT)
        make_judge(tools, "html", HTML, PLAN)(FEATURES[:2])
        self.assertEqual(sorted(tools.extractions), sorted(FEATURES[:2]))
        again = self.Tools({}, self.PRESENT)    # 다시 뽑으려 하면 KeyError가 난다
        verdicts = make_judge(again, "html", HTML, PLAN)(FEATURES[:2])
        self.assertEqual(again.extractions, [])
        self.assertEqual({f: v[0] for f, v in verdicts.items()}, {"반찬 사전주문": 1.0, "픽업 시간 예약": 0.5})

    def test_votes_are_settled_per_element_by_majority(self):
        from verification_agent.llm_judge import settle_elements

        credit, reason = settle_elements(["사진", "증상"], [[True, True], [False, True], [False, True]])
        self.assertEqual(credit, 0.5)
        self.assertIn("빠진 요소: 사진", reason)
        self.assertEqual(settle_elements(["사진"], [[True], None, [True]])[0], 1.0)
        self.assertIsNone(settle_elements(["사진"], [None, None, None]))

    def test_answer_must_cover_every_element(self):
        from verification_agent.llm_judge import parse_checks

        with self.assertRaises(Exception):
            parse_checks(2)('{"checks": [{"element": "사진", "reason": "x", "present": true}]}')
        self.assertEqual(parse_checks(1)('{"checks": [{"element": "사진", "reason": "x", "present": false}]}'), [False])
