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
