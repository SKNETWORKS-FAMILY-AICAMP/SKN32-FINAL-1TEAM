"""인포그래픽에 디자인 글꼴을 넣는 동작(fonts.py). 실행 때 추가 패키지를 쓰지 않는다."""
from unittest import TestCase
from unittest.mock import patch

from engineering_agent.infographic import fonts

SVG = ('<svg width="900" height="200" viewBox="0 0 900 200" xmlns="http://www.w3.org/2000/svg" '
       'font-family="\'Malgun Gothic\',sans-serif"><title>반찬온</title>'
       '<text x="10" y="40" data-field="item_name">반찬온 <tspan>18%</tspan></text></svg>')


class FontTests(TestCase):
    def test_embeds_font_and_keeps_text(self):
        self.assertTrue(fonts.FONT_FILE.is_file(), "글꼴 파일이 저장소에 있어야 한다")
        out = fonts.embed(SVG)
        self.assertIn("@font-face", out)
        self.assertIn("font-family=\"'Pretendard'", out)
        self.assertIn(">반찬온 <tspan>18%</tspan></text>", out)  # 글자는 그대로 <text>
        self.assertLess(len(out) - len(SVG), 700_000)

    def test_missing_font_leaves_svg_unchanged(self):
        with patch.object(fonts, "_style", return_value=""):
            self.assertEqual(fonts.embed(SVG), SVG)
