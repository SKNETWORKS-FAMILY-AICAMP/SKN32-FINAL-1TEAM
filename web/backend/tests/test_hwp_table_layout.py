"""hwp 표 채우기의 한계 해결 — 행이 모자랄 때 늘리기 · 칸 안 줄바꿈 · 사업비 비목 칸 나누기 · 체크 칸 알아보기 · docx와 같은 모양.

예전에는 ① 입력 줄이 양식의 고정 행(팀 구성 4 · 일정 5 · 사업비 5 등)보다 많으면 뒤가 잘렸고 ② 칸 값의 줄바꿈을 " / "로 이어 붙였고 ③ 사업비 둘째 항목은
비목 칸이 없어 "비목: 산출근거"로 합쳤고 ④ 업종 칸은 보기 문구와 글자 그대로 같을 때만 체크했다. rhwp 실제 확인은 실행 파일이 있을 때만 한다.

실행:
    pytest tests/test_hwp_table_layout.py -v
"""
import json
import os
import re
import shutil
import subprocess
import zipfile
from types import SimpleNamespace as NS

import pytest
from docx import Document

from app import hwp_export, hwpx_rows
from app.plan_document_export import (
    BudgetLineItem,
    PartnerRow,
    PlanDocumentData,
    ScheduleRow,
    TeamRow,
    render_plan_docx,
)
from app.routers.projects import _support_and_tech_field

_RHWP_AVAILABLE = shutil.which(hwp_export.RHWP_BIN) is not None or os.path.isfile(hwp_export.RHWP_BIN)


# ── 표 행 늘리기 · 칸 줄 나누기 계획(rhwp 없이) ───────────────────────────────────
def _steps():
    return hwp_export._Steps()


def test_rows_within_the_slots_do_not_add_rows():
    steps = _steps()
    hwp_export._fill_rows(steps, 10, 1, [0, 1], [('1', 'a'), ('2', 'b')], slot_count=5)

    assert steps.add_rows == []
    assert len([s for s in steps if s['row'] == 5]) == 2  # 남는 슬롯은 공란으로 쓴다


def test_rows_beyond_the_slots_add_rows_below_the_last_slot_and_all_rows_are_written():
    steps = _steps()
    rows = [(str(i), f'값{i}') for i in range(1, 9)]
    hwp_export._fill_rows(steps, 10, 1, [0, 1], rows, slot_count=5)

    assert steps.add_rows == [(10, 5, 3)]  # 표10의 5번 행을 기준으로 3행 늘림
    written = {(s['row'], s['col']): s['text'] for s in steps}
    assert [written[(r, 1)] for r in range(1, 9)] == [f'값{i}' for i in range(1, 9)]


def _item(i, phase=''):
    return BudgetLineItem(f'비목{i}', f'산출 근거 {i}', f'{i}00원', f'{i}00원', 단계=phase)


def test_preliminary_budget_over_five_items_adds_rows_and_pushes_the_total_row_down():
    steps = _steps()
    hwp_export._budget_steps(steps, 12, [_item(i) for i in range(1, 8)], '합계 7')

    cells = {(s['row'], s['col']): s['text'] for s in steps}
    assert steps.add_rows == [(12, 5, 2)] and steps.split_cells == [(12, 1, 0)]
    assert [cells[(r, 0)] for r in range(1, 8)] == [f'비목{i}' for i in range(1, 8)]  # 둘째 항목도 자기 비목 칸에 쓴다
    assert cells[(8, 2)] == '합계 7' and (6, 2) in cells


def test_preliminary_budget_up_to_five_items_keeps_the_total_row_at_six():
    steps = _steps()
    hwp_export._budget_steps(steps, 14, [_item(1), _item(2)], '합계')

    cells = {(s['row'], s['col']): s['text'] for s in steps}
    assert steps.add_rows == [] and cells[(6, 2)] == '합계' and cells[(2, 0)] == '비목2' and cells[(5, 0)] == ''


def test_early_budget_over_four_items_adds_rows_and_pushes_the_total_row_down():
    steps = _steps()
    data = NS(정부지원사업비='총 정부', 자기부담_현금='총 현금', 자기부담_현물='총 현물', 총사업비='총계')
    hwp_export._budget_steps_full(steps, 13, [_item(i) for i in range(1, 7)], data)

    cells = {(s['row'], s['col']): s['text'] for s in steps}
    assert steps.add_rows == [(13, 6, 2)] and steps.split_cells == [(13, 3, 0)]
    assert cells[(3, 0)] == '비목1' and cells[(4, 0)] == '비목2' and cells[(8, 0)] == '비목6'
    assert (cells[(9, 2)], cells[(9, 5)]) == ('총 정부', '총계')


def test_multi_line_cell_writes_the_first_line_and_remembers_the_rest():
    steps = _steps()
    hwp_export._set_cell(steps, 5, 1, 1, '첫째\n\n둘째\r\n 셋째 ')

    assert steps == [{'action': 'set_cell', 'table': 5, 'row': 1, 'col': 1, 'text': '첫째'}]
    assert steps.cell_lines == [(5, 1, 1, ['첫째', '둘째', '셋째'])]
    assert steps.cell_texts == {(5, 1): {1: ['첫째', '둘째', '셋째']}}


def test_single_line_and_empty_cells_need_no_paragraph_split():
    steps = _steps()
    hwp_export._set_cell(steps, 5, 1, 1, '한 줄')
    hwp_export._set_cell(steps, 5, 2, 1, '')

    assert steps.cell_lines == [] and steps[1]['text'] == ''


def test_cell_lines_are_split_after_the_previous_line_then_filled(monkeypatch):
    commands = []
    monkeypatch.setattr(hwp_export, '_run_rhwp', lambda args: commands.append(args) or '')
    tmp = iter(f'/tmp/{i}.hwp' for i in range(50))

    hwp_export._write_cell_lines('/tmp/in.hwp', [(5, 1, 1, ['첫째 줄', '둘째', '셋째'])], lambda: next(tmp))

    def arg(command, name):
        return command[command.index(name) + 1]

    assert [c[1] for c in commands] == ['split-paragraph-in-cell', 'insert-text-in-cell'] * 2
    assert [(arg(c, '--cell-para'), arg(c, '--offset')) for c in commands[::2]] == [('0', str(len('첫째 줄'))), ('1', str(len('둘째')))]
    assert [(arg(c, '--cell-para'), arg(c, '--text')) for c in commands[1::2]] == [('1', '둘째'), ('2', '셋째')]


# ── 보기 칸(체크) 알아보기 ───────────────────────────────────────────────────────
@pytest.mark.parametrize('value,expected', [
    ('정보·통신', (3, 14)), ('정보 · 통신', (3, 14)), ('정보통신', (3, 14)), ('정보통신업', (3, 14)),
    ('바이오·의료·생명', (4, 8)), ('에너지자원', (4, 14)),
    ('○○·○○', None), ('', None), ('블록체인', None),
    ('전기·전자, 정보·통신', None),  # 둘을 가리키면 어느 쪽인지 알 수 없다
])
def test_tech_field_value_is_matched_to_one_option_or_nothing(value, expected):
    assert hwp_export._match_choice(value, hwp_export._TECH_FIELD_OPTIONS, hwp_export._TECH_FIELD_ALIASES) == expected


@pytest.mark.parametrize('value,expected', [
    ('특별지원 지역', (9, 3)), ('특별지원 지역(강원)', (9, 3)), ('우대지원', (9, 7)), ('일반지역', (9, 11)), ('비해당', (9, 15)),
    ('해당 없음', None),  # 입력이 없을 때 웹이 채우는 기본 문구라 사용자가 고른 것인지 알 수 없다
    ('', None),
])
def test_regional_priority_value_is_matched_by_option_name_inside_the_text(value, expected):
    assert hwp_export._match_choice(value, hwp_export._REGIONAL_PRIORITY_OPTIONS, hwp_export._REGIONAL_PRIORITY_ALIASES) == expected


@pytest.mark.parametrize('values,expected', [
    ((None, '제조', None), ('제조', '○○·○○')),
    ((None, '지식서비스', None), ('지식서비스', '○○·○○')),
    ((None, '정보·통신', None), ('○○', '정보·통신')),
    (('전기·전자', '제조', None), ('제조', '전기·전자')),  # tech_field는 기술분야, 업종은 지원 분야
    ((None, None, '제조업'), ('제조', '○○·○○')),
    ((None, None, '모바일 앱'), ('○○', '모바일 앱')),
    ((None, None, None), ('○○', '○○·○○')),
])
def test_industry_value_is_split_into_support_field_and_tech_field(values, expected):
    project = NS(tech_field=values[0])
    plan_input = NS(main_industry=values[1], main_industry_free=values[2])

    assert _support_and_tech_field(project, plan_input) == expected


# ── hwpx xml 행 복제 · 높이 ──────────────────────────────────────────────────────
def _cell(col, row, width=5000, height=500, span=1, rowspan=1, text=''):
    return (f'<hp:tc><hp:subList><hp:p><hp:run><hp:t>{text}</hp:t></hp:run><hp:linesegarray>'
            f'<hp:lineseg textpos="0" vertpos="0" vertsize="1000" textheight="1000" baseline="850" spacing="300" horzpos="0" horzsize="900" flags="0"/>'
            f'</hp:linesegarray></hp:p></hp:subList><hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
            f'<hp:cellSpan colSpan="{span}" rowSpan="{rowspan}"/><hp:cellSz width="{width}" height="{height}"/>'
            f'<hp:cellMargin left="100" right="100" top="100" bottom="100"/></hp:tc>')


def _table(rows, row_height=500):
    body = ''.join('<hp:tr>' + ''.join(cells) + '</hp:tr>' for cells in rows)
    return (f'<hp:tbl id="1" rowCnt="{len(rows)}" colCnt="2"><hp:sz width="10000" widthRelTo="ABSOLUTE" height="{row_height * len(rows)}" protect="0"/>'
            f'{body}</hp:tbl>')


def test_top_level_tables_skips_tables_inside_other_tables():
    inner = _table([[_cell(0, 0)]])
    xml = '<p>' + _table([[_cell(0, 0, text=inner)]]) + '</p>' + _table([[_cell(0, 0)]])

    assert len(hwpx_rows.top_level_tables(xml)) == 2


def test_clone_rows_copies_the_row_blank_renumbers_and_shifts_the_rows_after_it():
    xml = _table([[_cell(0, 0, text='머리'), _cell(1, 0)], [_cell(0, 1, text='자료'), _cell(1, 1, span=1)], [_cell(0, 2, text='합계'), _cell(1, 2)]])

    out = hwpx_rows.clone_rows(xml, 0, 1, 2)

    assert out.count('<hp:tr>') == 5 and 'rowCnt="5"' in out
    assert [int(a) for a in re.findall(r'rowAddr="(\d+)"', out)][::2] == [0, 1, 2, 3, 4]
    assert out.count('자료') == 1 and out.count('합계') == 1  # 복제한 행의 글자는 비운다
    assert 'height="2500"' in out  # 표 높이: 5행 x 500


def test_clone_rows_refuses_a_table_with_a_table_inside_or_a_vertically_merged_row():
    nested = _table([[_cell(0, 0, text=_table([[_cell(0, 0)]]))]])
    merged = _table([[_cell(0, 0, rowspan=2), _cell(1, 0)], [_cell(1, 1)]])

    with pytest.raises(ValueError):
        hwpx_rows.clone_rows(nested, 0, 0, 1)
    with pytest.raises(ValueError):
        hwpx_rows.clone_rows(merged, 0, 0, 1)


def test_estimate_lines_counts_each_line_and_wraps_long_ones():
    assert hwpx_rows.estimate_lines(['가나다'], 5000, 1000) == 1
    assert hwpx_rows.estimate_lines(['가나다', '라마'], 5000, 1000) == 2
    assert hwpx_rows.estimate_lines(['가' * 12], 5000, 1000) == 3  # 12자 x 1000 = 12000 → 5000 폭에서 3줄
    assert hwpx_rows.estimate_lines([''], 5000, 1000) == 1


def test_fit_row_height_grows_the_row_for_more_lines_and_never_shrinks_it():
    rows = [[_cell(0, 0, height=2000), _cell(1, 0, height=2000)], [_cell(0, 1, height=2000), _cell(1, 1, height=2000)]]
    xml = _table(rows, row_height=2000)

    grown = hwpx_rows.fit_row_height(xml, 0, 1, {1: ['한', '두', '세']})
    same = hwpx_rows.fit_row_height(xml, 0, 1, {1: ['한 줄']})

    # 3줄 x (1000 + 300) + 위아래 여백 200 = 4100 — 그 행의 두 칸이 모두 같은 높이가 되고 표 높이도 그만큼 늘어난다(4000 + 2100)
    assert grown.count('height="4100"') == 2 and 'height="6100"' in grown and grown.count('height="2000"') == 2
    assert same == xml  # 한 줄은 이미 들어가므로 줄이거나 늘리지 않는다


# ── docx도 hwp와 같은 모양 ───────────────────────────────────────────────────────
def _data(**override):
    team = [TeamRow('1', '대표', '개발', '경력 5년', '완료')]
    base = dict(
        기업명='샘플', 개업연월일='2024.01.01', 사업자_구분='법인사업자', 대표자_유형='단독', 사업자등록번호='000', 사업자_소재지='서울',
        창업아이템명='아이템', 산출물='앱', 지원분야='제조', 전문기술분야='정보·통신', 정부지원사업비='1원', 자기부담_현금='0원', 자기부담_현물='0원',
        총사업비='1원', 지방우대_지역_해당여부='해당 없음', 팀구성현황=team, 아이템_명칭='명칭', 아이템_범주='범주', 아이템_개요='개요',
        요약_문제인식='요약1', 요약_실현가능성='요약2', 요약_성장전략='요약3', 요약_팀구성='요약4',
        문제인식_본문='문제 첫째\n문제 둘째', 실현가능성_본문='실현', 실현가능성_일정=[ScheduleRow('1', '내용', '2026.01', '세부')],
        사업비_집행계획=[BudgetLineItem('재료비', '부품', '1원', '1원')], 성장전략_본문='성장', 성장전략_일정=[ScheduleRow('1', '내용', '2026.01', '세부')],
        팀구성_본문='팀', 팀구성_안=team, 협력기관=[PartnerRow('1', '협력사', '역량', '방안', '시기')],
    )
    base.update(override)
    return PlanDocumentData(**base)


@pytest.mark.parametrize('template', ['preliminary', 'early_general'])
def test_docx_has_no_blue_guide_notes_and_writes_the_body_one_bullet_per_line(template, tmp_path):
    path = tmp_path / 'out.docx'
    path.write_bytes(render_plan_docx(_data(), template=template))
    texts = [p.text for p in Document(str(path)).paragraphs]

    assert not any(t.startswith('※') for t in texts)  # hwp는 양식의 파란 안내를 모두 지운다
    assert '◦\t문제 첫째' in texts and '◦\t문제 둘째' in texts   # 글머리 뒤 탭 · 내어쓰기(test_plan_body_lines)
    assert '문제 첫째\n문제 둘째' not in texts


# ── rhwp 실제 확인 ──────────────────────────────────────────────────────────────
def _rhwp(args):
    out = subprocess.run([hwp_export.RHWP_BIN, *args], capture_output=True, text=True, encoding='utf-8', check=True)
    return out.stdout


def _tables(path):
    return json.loads(_rhwp(['export-tables', str(path), '--json']))['tables']


def _big_data(template):
    team = [TeamRow(str(i + 1), f'팀원{i + 1}', f'업무{i + 1}', f'경력 {i + 1}년\n수행 {i + 1}건', '완료') for i in range(7)]
    schedule = [ScheduleRow(str(i + 1), f'내용{i + 1}', f'2026.{i + 1:02d}', f'세부{i + 1}\n산출물') for i in range(8)]
    partners = [PartnerRow(str(i + 1), f'협력사{i + 1}', '역량', '방안', '시기') for i in range(6)]
    budget = [BudgetLineItem(f'비목{i + 1}', f'근거{i + 1}', f'{i + 1}00원', f'{i + 1}00원', '0원', '0원', '1단계' if i < 7 else '2단계') for i in range(9)]
    return _data(팀구성현황=team, 팀구성_안=team, 실현가능성_일정=schedule, 성장전략_일정=schedule, 협력기관=partners, 사업비_집행계획=budget,
                 아이템_개요='개요 첫째\n개요 둘째', 정부지원사업비_1단계='1단계 합', 정부지원사업비_2단계='2단계 합', 총사업비='총계 합',
                 지원분야='지식서비스', 전문기술분야='정보통신업', 지방우대_지역_해당여부='특별지원 지역(강원)')


def _cells(table, row):
    return {c['col']: c for c in table['cells'] if c['row'] == row}


@pytest.mark.skipif(not _RHWP_AVAILABLE, reason='rhwp 실행 파일이 없다(RHWP_BIN)')
@pytest.mark.parametrize('template', ['preliminary', 'early_general'])
def test_real_hwp_keeps_every_row_in_every_table_and_keeps_the_merges_of_new_rows(template, tmp_path):
    path = tmp_path / 'out.hwp'
    path.write_bytes(hwp_export.render_plan_hwp(_big_data(template), template))
    tables = _tables(path)
    all_text = '\n'.join(c['text'] for t in tables for c in t['cells'])

    for needle in ('팀원7', '업무7', '내용8', '세부8', '협력사6', '비목7', '비목9', '개요 둘째'):
        assert needle in all_text, needle
    # 팀 구성 표: 새 행도 양식 행과 같은 칸 구성(담당 업무 · 보유 역량이 가로로 병합)
    team = next(t for t in tables if t['cols'] in (8, 20) and any('팀원7' in c['text'] for c in t['cells']))
    rows = sorted({c['row'] for c in team['cells'] if '팀원' in c['text'] or c['text'].startswith('업무')})
    first_row = [(c['col'], c['colSpan']) for c in sorted(_cells(team, rows[0]).values(), key=lambda c: c['col'])]
    last_row = [(c['col'], c['colSpan']) for c in sorted(_cells(team, rows[-1]).values(), key=lambda c: c['col'])]
    assert first_row == last_row


@pytest.mark.skipif(not _RHWP_AVAILABLE, reason='rhwp 실행 파일이 없다(RHWP_BIN)')
@pytest.mark.parametrize('template', ['preliminary', 'early_general'])
def test_real_hwp_budget_rows_each_have_their_own_label_and_the_total_row_comes_last(template, tmp_path):
    path = tmp_path / 'out.hwp'
    path.write_bytes(hwp_export.render_plan_hwp(_big_data(template), template))
    tables = _tables(path)
    budget = next(t for t in tables if any(c['text'] == '비목7' for c in t['cells']))

    labels = [_cells(budget, r).get(0) for r in range(budget['rows'])]
    texts = [c['text'] for c in labels if c is not None]
    assert [f'비목{i}' for i in range(1, 8)] == [t for t in texts if t.startswith('비목')][:7]  # 첫 두 행에 걸쳤던 비목 칸이 나뉘어 둘째 항목도 비목이 보인다
    total = _cells(budget, budget['rows'] - 1)
    assert total[0]['colSpan'] >= 2 and total[0]['text'].replace(' ', '') == '합계'


@pytest.mark.skipif(not _RHWP_AVAILABLE, reason='rhwp 실행 파일이 없다(RHWP_BIN)')
def test_real_hwp_cell_lines_become_paragraphs_not_a_slash_joined_line(tmp_path):
    path = tmp_path / 'out.hwp'
    path.write_bytes(hwp_export.render_plan_hwp(_big_data('preliminary'), 'preliminary'))
    all_text = '\n'.join(c['text'] for t in _tables(path) for c in t['cells'])

    assert '개요 첫째\n개요 둘째' in all_text and '경력 1년\n수행 1건' in all_text
    assert '개요 첫째 / 개요 둘째' not in all_text


def _bullet_chars(path, table_text, cells):
    """hwp를 hwpx로 내보내 `table_text`가 든 표의 (행, 열) 칸들 문단의 글머리 글자를 읽는다."""
    out = os.path.join(os.path.dirname(str(path)), 'check.hwpx')
    _rhwp(['export-hwpx', str(path), out])
    with zipfile.ZipFile(out) as z:
        section, header = z.read('Contents/section0.xml').decode('utf-8'), z.read('Contents/header.xml').decode('utf-8')
    bullets = {m.group(1): re.search(r'char="([^"]*)"', m.group(0)).group(1) for m in re.finditer(r'<hh:bullet id="(\d+)".*?</hh:bullet>', header, re.S)}
    paras = {m.group(1): re.search(r'<hh:heading type="(\w+)" idRef="(\d+)"', m.group(0)).groups() for m in re.finditer(r'<hh:paraPr id="(\d+)".*?</hh:paraPr>', header, re.S)}
    start, end = next((s, e) for s, e in hwpx_rows.top_level_tables(section) if table_text in section[s:e])
    chars = {}
    for row, col in cells:
        row_xml = list(re.finditer(r'<hp:tr>.*?</hp:tr>', section[start:end], re.S))[row].group(0)
        cell = next(c.group(0) for c in re.finditer(r'<hp:tc\b.*?</hp:tc>', row_xml, re.S) if f'colAddr="{col}"' in c.group(0))
        kind, ref = paras[re.search(r'paraPrIDRef="(\d+)"', cell).group(1)]
        chars[(row, col)] = bullets[ref] if kind == 'BULLET' else None
    return chars


@pytest.mark.skipif(not _RHWP_AVAILABLE, reason='rhwp 실행 파일이 없다(RHWP_BIN)')
def test_real_hwp_checks_the_matching_choice_boxes_and_leaves_the_others_empty(tmp_path):
    path = tmp_path / 'out.hwp'
    path.write_bytes(hwp_export.render_plan_hwp(_big_data('early_general'), 'early_general'))

    chars = _bullet_chars(path, '창업아이템명', [(2, 3), (2, 8), (3, 3), (3, 14), (9, 3), (9, 7)])

    assert chars[(2, 8)] == '☑'   # 지식서비스
    assert chars[(3, 14)] == '☑'  # 정보 · 통신(업종 이름 '정보통신업'에서)
    assert chars[(9, 3)] == '☑'   # 특별지원 지역(글 안의 보기 이름으로)
    assert chars[(2, 3)] == '☐' and chars[(3, 3)] == '☐' and chars[(9, 7)] == '☐'  # 고르지 않은 칸은 빈 칸 그대로


def test_check_cells_clones_the_bullet_and_the_paragraph_shape_once_per_source():
    header = ('<hh:bullets itemCnt="1"><hh:bullet id="1" char="☐" checkedChar="x" useImage="0"></hh:bullet></hh:bullets>'
              '<hh:paraProperties itemCnt="2"><hh:paraPr id="0" checked="0"><hh:heading type="NONE" idRef="0" level="0"/></hh:paraPr>'
              '<hh:paraPr id="1" checked="0"><hh:heading type="BULLET" idRef="1" level="0"/></hh:paraPr></hh:paraProperties>')
    cell = lambda col: (f'<hp:tc><hp:subList><hp:p id="{col}" paraPrIDRef="1"><hp:run><hp:t></hp:t></hp:run></hp:p></hp:subList>'  # noqa: E731
                        f'<hp:cellAddr colAddr="{col}" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/></hp:tc>')
    section = _table([[cell(0), cell(1), cell(2)]])

    new_section, new_header = hwpx_rows.check_cells(section, header, [(0, 0, 0), (0, 0, 2)])

    assert new_section.count('paraPrIDRef="2"') == 2 and new_section.count('paraPrIDRef="1"') == 1  # 고른 두 칸만 ☑ 문단 모양
    assert new_header.count('char="☑"') == 1 and 'bullets itemCnt="2"' in new_header and 'paraProperties itemCnt="3"' in new_header
    with pytest.raises(ValueError):
        hwpx_rows.check_cells(section.replace('paraPrIDRef="1"', 'paraPrIDRef="0"'), header, [(0, 0, 0)])


# ── 쪽 밖으로 나가는 표 · 빈 쪽 ──────────────────────────────────────────────────
def _layout_warnings(path):
    out = subprocess.run([hwp_export.RHWP_BIN, 'export-text', str(path), '--json'], capture_output=True, text=True, encoding='utf-8', errors='replace')
    return [line for line in (out.stderr + out.stdout).splitlines() if 'OVERFLOW' in line]


def _normal_data(template):
    team = [TeamRow(str(i + 1), f'팀원{i + 1}', f'업무{i + 1}', f'경력 {i + 1}년\n수행 {i + 1}건', '완료') for i in range(4)]
    return _data(팀구성현황=team, 팀구성_안=team[:3], 아이템_개요='개요 첫째\n개요 둘째\n개요 셋째', 요약_문제인식='문제 첫째\n문제 둘째')


@pytest.mark.skipif(not _RHWP_AVAILABLE, reason='rhwp 실행 파일이 없다(RHWP_BIN)')
@pytest.mark.parametrize('template', ['preliminary', 'early_general'])
def test_real_hwp_with_normal_amounts_has_no_table_running_off_the_page(template, tmp_path):
    path = tmp_path / 'out.hwp'
    path.write_bytes(hwp_export.render_plan_hwp(_normal_data(template), template))

    assert _layout_warnings(path) == []  # 양식 행 수 안의 입력은 칸 높이를 내용에 맞춰 표가 쪽 안에 들어간다


@pytest.mark.skipif(not _RHWP_AVAILABLE, reason='rhwp 실행 파일이 없다(RHWP_BIN)')
@pytest.mark.parametrize('template', ['preliminary', 'early_general'])
def test_real_hwp_has_no_page_without_text_or_pictures(template, tmp_path):
    path = tmp_path / 'out.hwp'
    path.write_bytes(hwp_export.render_plan_hwp(_normal_data(template), template))
    pages = json.loads(_rhwp(['export-text', str(path), '--json']))['pages']

    # 쪽 번호 한 줄뿐인 쪽(그림 쪽은 글이 없지만 그림이 있다)이 없다 — 첫 쪽이 고지 한 줄만 남는 빈 쪽이 되지 않는다
    assert all(len(page['text'].strip().splitlines()) > 2 for page in pages)
    assert '본 문서는' in pages[0]['text'] and ('사업계획서' in pages[0]['text'])


@pytest.mark.parametrize('template', ['preliminary', 'early_general'])
def test_tables_that_are_filled_may_continue_on_the_next_page(template):
    steps = hwp_export._STEPS_BY_TEMPLATE[template](_big_data(template))

    filled_tables = {table for table, _ in steps.cell_texts}
    assert filled_tables  # 채우는 표는 행 단위로 쪽을 넘길 수 있게 xml에서 바꾼다(hwpx_rows.allow_row_page_break)


def test_allow_row_page_break_and_remove_first_page_break_edit_only_what_they_name():
    table = _table([[_cell(0, 0)]]).replace('<hp:tbl id="1"', '<hp:tbl id="1" pageBreak="NONE"')
    xml = ('<hp:p id="1" paraPrIDRef="1" styleIDRef="0" pageBreak="0"/><hp:p id="2" paraPrIDRef="1" styleIDRef="0" pageBreak="1"/>'
           '<hp:p id="3" paraPrIDRef="1" styleIDRef="0" pageBreak="1"/>' + table)

    assert 'pageBreak="CELL"' in hwpx_rows.allow_row_page_break(xml, 0)
    out = hwpx_rows.remove_first_page_break(xml)
    assert out.count('pageBreak="1"') == 1 and 'id="2" paraPrIDRef="1" styleIDRef="0" pageBreak="0"' in out


def test_trim_cell_paragraphs_keeps_only_the_first_paragraph_of_the_named_cells():
    cell = lambda col, paras: (  # noqa: E731
        '<hp:tc><hp:subList>' + ''.join(f'<hp:p id="{i}"><hp:run><hp:t>{t}</hp:t></hp:run></hp:p>' for i, t in enumerate(paras))
        + f'</hp:subList><hp:cellAddr colAddr="{col}" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
          f'<hp:cellSz width="5000" height="500"/><hp:cellMargin left="1" right="1" top="1" bottom="1"/></hp:tc>')
    xml = _table([[cell(0, ['라벨', '남음']), cell(1, ['값', '', '', ''])]])

    out = hwpx_rows.trim_cell_paragraphs(xml, 0, 0, [1])

    assert out.count('<hp:p ') == 3 and '남음' in out  # 값 칸(열 1)만 첫 문단만 남는다


# ── 소제목 줄 · 긴 아이템 이름 (웹 프론트 확인 2026-10-13) ───────────────────────────
@pytest.mark.parametrize('line,expected', [
    ('[대표자 보유 역량]', True), ('  [협력기관 협업 시 보유 예정 기술 · 역량]  ', True),
    ('[앞]과 [뒤]', False), ('본문 [참고]', False), ('[]', False), ('◦ 본문', False),
])
def test_subheading_lines_are_square_bracket_titles_only(line, expected):
    assert hwp_export._is_subheading(line) is expected


def test_subheading_lines_are_written_without_the_bullet(monkeypatch):
    commands = []
    monkeypatch.setattr(hwp_export, '_run_rhwp', lambda args: commands.append(args) or '')
    tmp = iter(f'/tmp/{i}.hwp' for i in range(500))
    data = _data(실현가능성_본문='[소제목]\n본문 줄\n[둘째 소제목]\n본문 둘째')
    data.문제인식_본문 = data.팀구성_본문 = ''

    hwp_export._write_body_sections('/tmp/in.hwp', 'preliminary', data, lambda: next(tmp))

    texts = [c[c.index('--text') + 1] for c in commands if c[1] == 'insert-text' and 26 <= int(c[c.index('--para') + 1]) <= 27]
    # 마지막 줄부터 넣는다 — 소제목은 " ◦ " 없이, 본문 줄은 " ◦ "와 함께
    assert texts == [' ◦ 본문 둘째', '[둘째 소제목]', ' ◦ 본문 줄', '[소제목]']
    deletes = [c for c in commands if c[1] == 'delete-text']
    assert len(deletes) == 1 and deletes[0][deletes[0].index('--count') + 1] == '3'  # 첫 줄이 소제목이면 첫 문단의 " ◦ "를 지운다


@pytest.mark.skipif(not _RHWP_AVAILABLE, reason='rhwp 실행 파일이 없다(RHWP_BIN)')
@pytest.mark.parametrize('template', ['preliminary', 'early_general'])
def test_real_hwp_long_item_name_is_not_cut_off_and_subheading_has_no_bullet(template, tmp_path):
    long_name = '해외 반려동물 보호자를 위한 AI 기반 건강 관리와 병원 예약 연결 통합 모바일 앱 서비스'
    data = _data(아이템_명칭=long_name, 팀구성_본문='[대표자 보유 역량]\n백엔드 5년 경력')
    path = tmp_path / 'out.hwp'
    path.write_bytes(hwp_export.render_plan_hwp(data, template))

    dump = _rhwp(['dump', str(path)])
    name_cell = next(line for line in dump.splitlines() if long_name[:12] in line and '셀[' in line)  # dump는 칸 글을 앞부분만 보여 준다
    height = int(re.search(r' h=(\d+) ', name_cell).group(1))
    assert height > hwpx_rows.MIN_ROW  # 이름이 여러 줄로 줄바꿈될 만큼 칸이 커져 잘리지 않는다(짧은 이름이면 MIN_ROW)
    lines = [ln.strip() for page in json.loads(_rhwp(['export-text', str(path), '--json']))['pages'] for ln in page['text'].split('\n')]
    assert '[대표자 보유 역량]' in lines and '◦ [대표자 보유 역량]' not in lines


@pytest.mark.parametrize('description,expected', [
    ('E2E 아이템 — AI 반려동물 건강관리 앱', 'E2E 아이템 — AI 반려동물 건강관리 앱'),
    ('반려견 산책 도우미 서비스를 진행하고싶어요', '반려견 산책 도우미 서비스를 진행하고싶어요'),
    ('첫 줄 이름\n둘째 줄은 이름이 아니다', '첫 줄 이름'),
    ('\n\n  앞의 빈 줄은 건너뜀  ', '앞의 빈 줄은 건너뜀'),
    ('가' * 100, '가' * 60), ('', ''), (None, ''),
])
def test_item_name_is_the_first_line_up_to_sixty_characters_not_cut_at_twenty(description, expected):
    from app.routers.projects import _item_name

    assert _item_name(description) == expected


def _data_for_description(authed_client, db_session, description):
    import json

    from app.models import Project
    from app.plan_texts import PlanTexts
    from app.routers.projects import _build_plan_document_data

    payload = {'applicant_type': 'individual', 'biz_type': '개인', 'ceo_name': '박테스트', 'founded_at': '2024-01-01',
               'description': description, 'team_members': [], 'pricing_items': []}
    r = authed_client.post('/projects', data={'payload': json.dumps(payload)})
    assert r.status_code == 201, r.text
    return _build_plan_document_data(db_session, db_session.get(Project, r.json()['project_id']), PlanTexts())[0]


def test_general_status_item_name_and_overview_name_are_the_same_value(authed_client, db_session):
    """창업아이템명(일반현황)과 개요 표 명칭은 아이디어 설명의 첫 줄(60자까지)로 같다 — 여러 줄 설명에서도 두 이름이 갈라지지 않는다."""
    data = _data_for_description(authed_client, db_session, '동네 헬스장 회원 관리 서비스\n수업 예약과 출석을 한 화면에서 처리합니다')

    assert data.창업아이템명 == data.아이템_명칭 == '동네 헬스장 회원 관리 서비스'


def test_general_status_item_name_is_cut_at_sixty_characters_like_the_overview_name(authed_client, db_session):
    data = _data_for_description(authed_client, db_session, '가' * 100)

    assert data.창업아이템명 == data.아이템_명칭 == '가' * 60


def test_general_status_item_name_keeps_the_placeholder_when_the_description_is_blank(authed_client, db_session):
    data = _data_for_description(authed_client, db_session, ' \n ')

    assert data.창업아이템명 == '○○기술이 적용된 ○○제품·서비스' and data.아이템_명칭 == '○○'
