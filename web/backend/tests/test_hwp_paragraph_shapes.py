"""hwp 문단 모양 — 본문 글머리 줄의 내어쓰기와 표 칸 목록의 왼쪽 정렬.

예전에는 ① 본문 문단이 양식 문단 모양을 물려받아 내어쓰기가 줄마다 달랐고(약 1.2cm · 2.1cm — 글머리 폭과 맞지 않음)
② 표 칸의 여러 줄 목록(산출물 등)이 양식 칸의 가운데 정렬 그대로 줄마다 가운데로 몰렸다. 지금은 문단마다 원래 문단 모양의 복사본에
정렬 · 왼쪽 여백 · 내어쓰기만 바꿔 붙인다(hwpx_rows.shape_paragraphs). rhwp 실제 확인은 실행 파일이 있을 때만 한다.

실행:
    pytest tests/test_hwp_paragraph_shapes.py -v
"""
import re
import subprocess
import zipfile

import pytest

from app import hwp_export, hwpx_rows
from tests.test_hwp_table_layout import _RHWP_AVAILABLE, _data

_HEADER = (
    '<hh:head><hh:charProperties itemCnt="2"><hh:charPr id="0" height="1400" textColor="#000000"/>'
    '<hh:charPr id="1" height="1000" textColor="#000000"/></hh:charProperties>'
    '<hh:paraProperties itemCnt="1"><hh:paraPr id="5" tabPrIDRef="0"><hh:align horizontal="CENTER" vertical="BASELINE"/>'
    '<hp:switch><hp:case hp:required-namespace="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar"><hh:margin>'
    '<hc:intent value="-3007" unit="HWPUNIT"/><hc:left value="0" unit="HWPUNIT"/></hh:margin></hp:case>'
    '<hp:default><hh:margin><hc:intent value="-6014" unit="HWPUNIT"/><hc:left value="0" unit="HWPUNIT"/></hh:margin></hp:default>'
    '</hp:switch></hh:paraPr></hh:paraProperties></hh:head>'
)


def _p(pid, text, char='0'):
    return f'<hp:p id="{pid}" paraPrIDRef="5" styleIDRef="0" pageBreak="0"><hp:run charPrIDRef="{char}"><hp:t>{text}</hp:t></hp:run></hp:p>'


def _section():
    cell = (f'<hp:tc name=""><hp:subList id="">{_p(10, "◦ 첫째", "1")}{_p(11, "- 둘째", "1")}</hp:subList>'
            '<hp:cellAddr colAddr="1" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/></hp:tc>')
    table = f'<hp:p id="3" paraPrIDRef="5"><hp:run charPrIDRef="0"><hp:tbl id="1" rowCnt="1"><hp:tr>{cell}</hp:tr></hp:tbl></hp:run></hp:p>'
    return f'<hs:sec>{_p(1, " ◦ 본문 줄")}{_p(2, "   - 하위 줄")}{table}{_p(4, "[소제목]")}</hs:sec>'


def _para_pr(header, pid):
    return re.search(rf'<hh:paraPr id="{pid}".*?</hh:paraPr>', header, re.S).group(0)


def _ref(xml, text):
    i = xml.index(text)
    return re.findall(r'paraPrIDRef="(\d+)"', xml[:i])[-1]


def test_top_level_paragraphs_skip_the_paragraphs_inside_table_cells():
    spans = hwpx_rows.top_level_paragraphs(_section())
    texts = [hwpx_rows.paragraph_text(_section()[s:e]) for s, e in spans]
    assert texts == [' ◦ 본문 줄', '   - 하위 줄', '◦ 첫째- 둘째', '[소제목]']


def test_shape_paragraphs_copies_the_paragraph_shape_with_new_margins_in_em_of_the_font():
    section, header = hwpx_rows.shape_paragraphs(_section(), _HEADER, {
        0: (' ◦ 본문 줄', (None, 0, 1.9)), 1: ('   - 하위 줄', (None, 0, 2.75)), 3: ('[소제목]', (None, 0, 0))}, {})

    item, sub, heading = _ref(section, '본문 줄'), _ref(section, '하위 줄'), _ref(section, '[소제목]')
    assert len({item, sub, heading, '5'}) == 4   # 원래 모양(5)은 그대로 두고 복사본을 붙인다 — 양식의 다른 문단은 바뀌지 않는다
    block = _para_pr(header, item)
    assert 'horizontal="CENTER"' in block   # 정렬을 주지 않으면 그대로
    default = block.split('<hp:default>')[1]
    assert '<hc:intent value="-2660"' in default and '<hc:left value="0"' in default   # 1.9em × 글자 크기 1400
    assert '<hc:intent value="-1330"' in block.split('<hp:default>')[0]   # <hp:case> 쪽은 절반 값
    assert '<hc:intent value="-3850"' in _para_pr(header, sub)
    assert '<hc:intent value="0"' in _para_pr(header, heading).split('<hp:default>')[1]
    assert 'itemCnt="4"' in header


def test_shape_paragraphs_skips_a_paragraph_whose_text_is_not_the_expected_line():
    section, header = hwpx_rows.shape_paragraphs(_section(), _HEADER, {0: ('다른 글', (None, 0, 1.9))}, {})
    assert section == _section() and header == _HEADER


def test_shape_paragraphs_left_aligns_cell_lines_and_reuses_one_copy_per_shape():
    shapes = [('LEFT', 0, 1.5), ('LEFT', 1.5, 0.95)]
    section, header = hwpx_rows.shape_paragraphs(_section(), _HEADER, {}, {(0, 0, 1): shapes})

    item, sub = _ref(section, '첫째'), _ref(section, '둘째')
    assert 'horizontal="LEFT"' in _para_pr(header, item) and 'horizontal="LEFT"' in _para_pr(header, sub)
    sub_default = _para_pr(header, sub).split('<hp:default>')[1]
    assert '<hc:left value="1500"' in sub_default and '<hc:intent value="-950"' in sub_default   # 칸 글자 크기 1000
    again, again_header = hwpx_rows.shape_paragraphs(section, header, {}, {(0, 0, 1): shapes})
    assert again_header.count('horizontal="LEFT"') == header.count('horizontal="LEFT"') + 2   # 이미 바꾼 문단은 그 복사본에서 다시 복사


def test_shape_paragraphs_skips_a_cell_whose_paragraph_count_differs():
    section, _ = hwpx_rows.shape_paragraphs(_section(), _HEADER, {}, {(0, 0, 1): [('LEFT', 0, 0)]})
    assert section == _section()


# ── 어느 문단 · 칸에 어떤 모양을 주는가 ──────────────────────────────────────
def test_body_paragraph_shapes_follow_the_written_paragraph_numbers():
    data = _data(문제인식_본문='[소제목]\n◦ 줄\n- 하위', 실현가능성_본문='', 성장전략_본문='성장', 팀구성_본문='팀')
    data.실현가능성_일정_서술 = data.사업비_서술 = data.성장전략_일정_서술 = ''
    shapes = hwp_export._body_paragraph_shapes('preliminary', data)

    # preliminary: 문제인식 11(뼈대 12 ~ 22, 11개) → 3줄이라 뒤는 2 - 11 = -9, 실현가능성 26 - 9 = 17(비어도 양식 문단 하나 — 뼈대 27 ~ 35, 9개) → -9 - 9 = -18
    assert shapes[11] == ('[소제목]', (None, 0, 0))
    assert shapes[12] == (' ◦ 줄', (None, 0, 1.9))
    assert shapes[13] == ('   - 하위', (None, 0, 2.75))
    assert 17 not in shapes                                   # 본문이 빈 절은 건드리지 않는다
    assert shapes[49 - 18] == (' ◦ 성장', (None, 0, 1.9))      # 성장전략 49
    assert shapes[75 - 18 - 19] == (' ◦ 팀', (None, 0, 1.9))   # 팀구성 75 — 성장전략 뼈대 50 ~ 68(19개)를 지우고 1줄(0개 더함) → -19


def test_cell_lines_get_one_kind_of_mark_only_when_the_cell_has_marked_lines():
    assert hwp_export._cell_lines_marked('• 첫째\n–  둘째\n셋째') == ['◦ 첫째', '- 둘째', '셋째']
    assert hwp_export._cell_lines_marked('경력 5년\n수행 5건') == ['경력 5년', '수행 5건']


def test_cell_paragraph_shapes_use_the_table_numbers_after_the_deleted_tables():
    steps = hwp_export._Steps()
    hwp_export._set_cell(steps, 5, 7, 1, '◦ 산출물\n- 기능')
    hwp_export._set_cell(steps, 5, 8, 1, '한 줄')
    cells = hwp_export._cell_paragraph_shapes('early_general', steps)
    # early_general은 표 0 · 1 · 3을 지운다 — 표 5는 2로 당겨진다. 글머리 없는 칸은 그대로
    assert cells == {(2, 7, 1): [('LEFT', 0, 1.5), ('LEFT', 1.5, 0.95)]}


# ── rhwp 실제 확인 ──────────────────────────────────────────────────────────
def _shapes_of(path, tmp_path):
    hwpx = tmp_path / 'out.hwpx'
    subprocess.run([hwp_export.RHWP_BIN, 'export-hwpx', str(path), str(hwpx)], capture_output=True, check=True)
    with zipfile.ZipFile(hwpx) as z:
        section, header = z.read('Contents/section0.xml').decode('utf-8'), z.read('Contents/header.xml').decode('utf-8')

    def shape(paragraph_xml):
        block = _para_pr(header, re.search(r'paraPrIDRef="(\d+)"', paragraph_xml).group(1))
        default = block.split('<hp:default>')[-1]
        return (re.search(r'horizontal="(\w+)"', block).group(1), int(re.search(r'<hc:left value="(-?\d+)"', default).group(1)),
                int(re.search(r'<hc:intent value="(-?\d+)"', default).group(1)))

    body = {hwpx_rows.paragraph_text(section[s:e]).strip(): shape(section[s:e]) for s, e in hwpx_rows.top_level_paragraphs(section)}
    cell = {hwpx_rows.paragraph_text(m.group(0)).strip(): shape(m.group(0))
            for m in re.finditer(r'<hp:p id="\d+" paraPrIDRef="\d+".*?</hp:p>', section, re.S) if '산출 목표' in m.group(0) or '기능 하나' in m.group(0)}
    return body, cell


@pytest.mark.skipif(not _RHWP_AVAILABLE, reason='rhwp 실행 파일이 없다(RHWP_BIN)')
@pytest.mark.parametrize('template', ['preliminary', 'early_general'])
def test_real_hwp_body_lines_hang_by_the_mark_width_and_cell_lists_are_left_aligned(template, tmp_path):
    data = _data(팀구성_본문='[대표자 보유 역량]\n◦ 대표 줄\n- 하위 줄\n① 번호 줄', 산출물='◦ 산출 목표\n- 기능 하나')
    path = tmp_path / 'out.hwp'
    path.write_bytes(hwp_export.render_plan_hwp(data, template))
    body, cell = _shapes_of(path, tmp_path)

    font = 1400   # 양식 본문 글자 크기(휴먼명조 14pt)
    assert body['[대표자 보유 역량]'][1:] == (0, 0)
    assert body['◦ 대표 줄'][1:] == (0, -round(1.9 * font))
    assert body['- 하위 줄'][1:] == (0, -round(2.75 * font))
    assert body['① 번호 줄'][1:] == (0, -round(1.9 * font))
    assert body['◦ 문제 첫째'][1:] == (0, -round(1.9 * font))   # 맨 앞 절의 첫 줄(양식의 첫 불릿 문단)도
    assert cell['◦ 산출 목표'] == ('LEFT', 0, -1500)
    assert cell['- 기능 하나'] == ('LEFT', 1500, -950)
