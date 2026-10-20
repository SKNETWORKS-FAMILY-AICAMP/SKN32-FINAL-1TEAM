"""hwp 한 쪽 맞춤 · 글자 통일 · 별첨 표시(app/hwpx_fit.py) 시험.

xml만 고치는 단위 시험은 rhwp 없이 돌고, 실제 .hwp를 만들어 쪽 · 글을 확인하는 시험은 rhwp 실행 파일이 있을 때만 돈다(RHWP_BIN).
"""
import dataclasses
import os
import re
import shutil
import struct
import subprocess
import zlib

import pytest

from app import hwp_export, hwpx_fit
from app.diagram_images import DiagramPicture
from tests.test_hwp_table_layout import _big_data, _data

_RHWP_AVAILABLE = shutil.which(hwp_export.RHWP_BIN) is not None or os.path.isfile(hwp_export.RHWP_BIN)


# ── xml 단위 시험(rhwp 없이) ───────────────────────────────────────────────────────
def _font_faces():
    langs = ''.join(
        f'<hh:fontface lang="{lang}" fontCnt="3"><hh:font id="0" face="돋움"/><hh:font id="1" face="휴먼명조"/><hh:font id="2" face="함초롬바탕"/></hh:fontface>'
        for lang in hwpx_fit.FACE_LANGS)
    return f'<hh:fontfaces itemCnt="7">{langs}</hh:fontfaces>'


def _header(*heights):
    chars = ''.join(
        f'<hh:charPr id="{i}" height="{h}" textColor="#000000"><hh:fontRef hangul="0" latin="1" hanja="0" japanese="0" other="1" symbol="0" user="1"/></hh:charPr>'
        for i, h in enumerate(heights))
    return f'<hh:head>{_font_faces()}<hh:charProperties itemCnt="{len(heights)}">{chars}</hh:charProperties></hh:head>'


def test_fonts_become_one_face_and_body_sizes_become_one_size():
    header = hwpx_fit._unify_header(_header(800, 1000, 1200, 1400, 1600, 2000), 900)

    heights = [int(height) for _, height in hwpx_fit._CHAR_PR.findall(header)]
    assert heights[:4] == [900, 900, 900, 900]   # 원래 8 ~ 14pt 본문은 한 크기로
    assert heights[4] == 1200 and heights[5] == 1500   # 제목은 900/1200 비율로(16pt → 12pt, 20pt → 15pt)
    refs = set(re.findall(r'<hh:fontRef ([^/]*)/>', header))
    assert refs == {'hangul="2" latin="2" hanja="2" japanese="2" other="2" symbol="2" user="2"'}   # 함초롬바탕(번호 2)만


def test_font_face_is_left_alone_when_the_form_has_no_such_font():
    header = _header(1000).replace('함초롬바탕', '바탕')
    assert hwpx_fit._unify_header(header, 900).count('hangul="0"') == 1   # 서체는 그대로, 크기만 바뀐다


def test_spacer_sizes_below_body_range_are_kept():
    header = hwpx_fit._unify_header(_header(500, 600), 900)
    assert [m[1] for m in hwpx_fit._CHAR_PR.findall(header)] == ['500', '600']


_PIC_SECTION = (
    '<hp:p id="1" paraPrIDRef="0" pageBreak="1"><hp:run charPrIDRef="7"><hp:pic><hp:pos treatAsChar="0" vertRelTo="PAPER" vertOffset="8504" horzOffset="100"/></hp:pic></hp:run></hp:p>'
    '<hp:p id="2" paraPrIDRef="0" pageBreak="1"><hp:run charPrIDRef="7"><hp:pic><hp:pos treatAsChar="0" vertRelTo="PAPER" vertOffset="8504" horzOffset="100"/></hp:pic></hp:run></hp:p>'
)


def test_attachment_label_is_put_on_top_of_each_picture_page_and_the_picture_moves_down():
    out = hwpx_fit._label_attachments(_PIC_SECTION, ['<별첨> 하나', '<별첨> 둘'], '41')

    assert out.count('<hp:t>&lt;별첨&gt; 하나</hp:t>') == 1 and out.count('<hp:t>&lt;별첨&gt; 둘</hp:t>') == 1
    assert out.count(f'vertOffset="{8504 + hwpx_fit.ATTACHMENT_SHIFT}"') == 2
    assert out.index('별첨&gt; 하나') < out.index('<hp:pic>')   # 문구가 그림 앞에


def test_attachment_labels_are_skipped_when_the_picture_page_count_differs():
    assert hwpx_fit._label_attachments(_PIC_SECTION, ['<별첨> 하나'], '41') == _PIC_SECTION


def test_row_heights_follow_the_content_and_never_go_below_it():
    cell = ('<hp:tc name=""><hp:subList><hp:p id="1" paraPrIDRef="0"><hp:run charPrIDRef="0"><hp:t>{}</hp:t></hp:run></hp:p></hp:subList>'
            '<hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellSz width="10000" height="{}"/><hp:cellMargin left="510" right="510" top="141" bottom="141"/></hp:tc>')
    table = '<hp:tbl id="1"><hp:sz width="10000" widthRelTo="ABSOLUTE" height="30000" heightRelTo="ABSOLUTE"/>' + ''.join(
        f'<hp:tr>{cell.format(text, 15000)}</hp:tr>' for text in ('짧은 글', '긴 글 ' * 10)) + '</hp:tbl>'
    styles = hwpx_fit.hwpx_rows.Styles(_header(1000) + '<hh:paraPr id="0"><hh:lineSpacing type="PERCENT" value="130" unit="HWPUNIT"/></hh:paraPr>')

    heights = hwpx_fit._row_heights(table, styles, 0.8, True)

    assert heights[0] < 15000 and heights[1] < 15000          # 원래 높이가 커도 내용에 맞춰 줄인다
    assert heights[1] > heights[0] * 3                        # 긴 글 줄은 더 높다
    assert hwpx_fit._row_heights(table, styles, 0.8, False)[0] == 12000   # 내용 맞춤이 아니면 원래 × 비율(내용보다 낮지 않다)
    fixed = hwpx_fit._apply_heights(table, heights)
    assert f'height="{sum(heights)}" heightRelTo' in fixed


# ── 실제 .hwp 시험(rhwp 필요) ──────────────────────────────────────────────────────
def _png(width, height, rgb):
    def chunk(tag, body):
        return struct.pack('>I', len(body)) + tag + body + struct.pack('>I', zlib.crc32(tag + body))
    raw = b''.join(b'\x00' + bytes(rgb) * width for _ in range(height))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def _with_pictures(data):
    flow = DiagramPicture('서비스 흐름도', _png(600, 200, (40, 120, 100)), b'', 'userflow.svg')
    structure = DiagramPicture('서비스 구조도', _png(600, 200, (40, 60, 100)), b'', 'architecture.svg')
    infographic = DiagramPicture('인포그래픽', _png(500, 1000, (240, 150, 170)), b'', 'infographic.svg', True)
    return dataclasses.replace(data, 그림=[flow, structure], 인포그래픽=infographic)


def _rhwp(*args):
    out = subprocess.run([hwp_export.RHWP_BIN, *args], capture_output=True, text=True, encoding='utf-8', errors='replace')
    return out.stdout + out.stderr


def _render(tmp_path, data, template):
    path = tmp_path / 'plan.hwp'
    path.write_bytes(hwp_export.render_plan_hwp(data, template))
    return str(path)


@pytest.mark.skipif(not _RHWP_AVAILABLE, reason='rhwp 실행 파일이 없다(RHWP_BIN)')
@pytest.mark.parametrize('template', ['preliminary', 'early_general'])
def test_overview_table_stays_on_one_page_and_nothing_overflows(tmp_path, template):
    long_text = '개요 표 칸에 길게 들어가는 요약 글을 흉내 내기 위한 문장입니다. ' * 8
    data = _data(요약_문제인식='\n'.join([long_text] * 2), 요약_실현가능성=long_text, 요약_성장전략='\n'.join([long_text] * 2), 요약_팀구성=long_text, 아이템_개요=long_text)

    path = _render(tmp_path, data, template)

    assert 'LAYOUT_OVERFLOW' not in _rhwp('export-text', path, '--json')
    pages = _rhwp('dump-pages', path)
    overview_page = pages.split('=== 페이지 ')[2]   # 1쪽 일반현황 다음 쪽
    assert overview_page.count('Table ') == 1 and '창업 아이템 개요' in overview_page


@pytest.mark.skipif(not _RHWP_AVAILABLE, reason='rhwp 실행 파일이 없다(RHWP_BIN)')
@pytest.mark.parametrize('template', ['preliminary', 'early_general'])
def test_overview_table_too_long_for_one_page_continues_on_the_next_page(tmp_path, template):
    """가장 작은 글자로도 한 쪽을 넘는 개요 표는 쪽 아래로 넘치지 않고 다음 쪽으로 이어진다('글자처럼 취급'을 풀어 행 단위로 나눈다)."""
    long_text = '개요 표 칸에 길게 들어가는 요약 글을 흉내 내기 위한 문장입니다. ' * 40
    data = _data(요약_문제인식='\n'.join([long_text] * 2), 요약_실현가능성=long_text, 요약_성장전략='\n'.join([long_text] * 2), 요약_팀구성=long_text, 아이템_개요=long_text)

    path = _render(tmp_path, data, template)

    assert 'LAYOUT_OVERFLOW' not in _rhwp('export-text', path, '--json')


def test_allow_page_split_makes_the_table_splittable_and_keeps_other_tables():
    table = '<hp:tbl id="1" pageBreak="NONE" repeatHeader="1"><hp:pos treatAsChar="1" vertRelTo="PARA"/></hp:tbl>'

    out = hwpx_fit._allow_page_split(table)

    assert 'pageBreak="CELL"' in out and 'treatAsChar="0"' in out
    assert hwpx_fit._allow_page_split(out) == out   # 두 번 해도 같다


@pytest.mark.skipif(not _RHWP_AVAILABLE, reason='rhwp 실행 파일이 없다(RHWP_BIN)')
def test_pictures_get_attachment_labels_and_overview_image_cells_point_to_them(tmp_path):
    path = _render(tmp_path, _with_pictures(_big_data('preliminary')), 'preliminary')

    text = _rhwp('export-text', path, '--json')
    assert 'LAYOUT_OVERFLOW' not in text
    assert text.count('<별첨> 서비스 흐름도 · 서비스 구조도') == 1 and text.count('<별첨> 인포그래픽') == 1
    assert text.count('<별첨 참고>') == 2   # 개요 표 이미지 칸 둘


@pytest.mark.skipif(not _RHWP_AVAILABLE, reason='rhwp 실행 파일이 없다(RHWP_BIN)')
def test_without_pictures_no_attachment_text_is_added(tmp_path):
    path = _render(tmp_path, _data(), 'preliminary')

    text = _rhwp('export-text', path, '--json')
    assert '별첨' not in text


@pytest.mark.skipif(not _RHWP_AVAILABLE, reason='rhwp 실행 파일이 없다(RHWP_BIN)')
def test_one_typeface_and_a_few_sizes_are_used_in_the_whole_document(tmp_path):
    import zipfile

    path = _render(tmp_path, _big_data('preliminary'), 'preliminary')
    hwpx = tmp_path / 'plan.hwpx'
    _rhwp('export-hwpx', path, str(hwpx))
    with zipfile.ZipFile(hwpx) as z:
        header = z.read('Contents/header.xml').decode('utf-8')
        section = z.read('Contents/section0.xml').decode('utf-8')

    assert len(set(re.findall(r'<hh:fontRef ([^/]*)/>', header))) == 1
    used = set(re.findall(r'charPrIDRef="(\d+)"', section))
    sizes = {int(h) for i, h in hwpx_fit._CHAR_PR.findall(header) if i in used}
    assert len([s for s in sizes if 800 <= s <= 1050]) == 1   # 본문 · 표 글자는 한 크기
