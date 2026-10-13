"""hwp 본문을 줄마다 문단으로 쓰고, 양식의 파란 예시 상자와 빈 글머리를 지운다.

예전에는 본문 줄을 ' / '로 이은 한 문단으로 넣어 읽기 어려웠고, 양식의 빈 "-" 글머리가 그대로 남았으며, 칸 안의 "※ 예시 …" 안내 상자(칸 안에 든
1x1 표)가 입력한 값과 겹쳐 값이 가려졌다. 지금은 ① 정리한 양식(`*_양식_정리.hwp`)을 쓰고 ② 절마다 줄을 " ◦ " 문단으로 쓰며 ③ 빈 뼈대 문단을 지운다.
rhwp 실제 확인은 실행 파일이 있을 때만 한다.

실행:
    pytest tests/test_hwp_body_paragraphs.py -v
"""
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

from app import hwp_export
from app.models import Project
from app.plan_texts import PlanTexts
from app.routers.projects import _build_plan_document_data

_RHWP_AVAILABLE = shutil.which(hwp_export.RHWP_BIN) is not None or os.path.isfile(hwp_export.RHWP_BIN)
_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'scripts' / 'clean_hwp_template.py'


def _load_script():
    spec = importlib.util.spec_from_file_location('clean_hwp_template', _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules['clean_hwp_template'] = module
    spec.loader.exec_module(module)
    return module


# ── 줄 목록 ─────────────────────────────────────────────────────────────────────
def _data(**fields):
    from types import SimpleNamespace as NS
    base = dict(실현가능성_본문='', 실현가능성_일정_서술='', 사업비_서술='', 사업비_2단계_서술='', 성장전략_본문='', 성장전략_일정_서술='')
    base.update(fields)
    return NS(**base)


def test_body_lines_split_the_body_and_the_table_narratives_into_paragraph_lines():
    data = _data(실현가능성_본문='본문 첫째\n본문 둘째', 실현가능성_일정_서술='1. 일정 서술', 사업비_서술='1. 사업비 서술')

    assert hwp_export._body_lines(data, '실현가능성_본문') == ['본문 첫째', '본문 둘째', '1. 일정 서술', '1. 사업비 서술']


def test_body_lines_label_the_two_phase_narratives_and_drop_blank_lines():
    data = _data(실현가능성_본문='본문\n\n  \n끝', 사업비_서술='1단계 서술', 사업비_2단계_서술='2단계 서술')

    assert hwp_export._body_lines(data, '실현가능성_본문') == ['본문', '끝', '[1단계] 1단계 서술', '[2단계] 2단계 서술']


def test_body_text_is_still_the_slash_joined_summary():
    data = _data(실현가능성_본문='본문 첫째\n본문 둘째', 사업비_서술='서술')

    assert hwp_export._body_text(data, '실현가능성_본문') == '본문 첫째 / 본문 둘째 / 서술'


# ── 문단 편집 순서(rhwp 없이) ────────────────────────────────────────────────────
def test_sections_are_edited_from_the_last_one_and_skeleton_paragraphs_go_before_the_text_goes_in(monkeypatch):
    commands = []
    monkeypatch.setattr(hwp_export, '_run_rhwp', lambda args: commands.append(args) or '')
    tmp = iter(f'/tmp/{i}.hwp' for i in range(500))
    data = _data(실현가능성_본문='가\n나\n다')
    data.문제인식_본문, data.팀구성_본문 = '문제', ''

    hwp_export._write_body_sections('/tmp/in.hwp', 'preliminary', data, lambda: next(tmp))

    def para(command):
        return int(command[command.index('--para') + 1])

    deletes = [para(c) for c in commands if c[1] == 'delete-paragraph']
    # 팀 구성(76 ~ 84) → 성장전략(50 ~ 68) → 실현가능성(27 ~ 35) → 문제인식(12 ~ 22), 각 절 안에서도 큰 번호부터
    assert deletes == [*range(84, 75, -1), *range(68, 49, -1), *range(35, 26, -1), *range(22, 11, -1)]
    section_two = [c for c in commands if c[1] != 'delete-paragraph' and 26 <= para(c) <= 27]
    assert [(c[1], para(c)) for c in section_two[:4]] == [('insert-paragraph', 27), ('insert-text', 27), ('insert-paragraph', 27), ('insert-text', 27)]
    texts = [c[c.index('--text') + 1] for c in section_two if c[1] == 'insert-text']
    assert texts == [' ◦ 다', ' ◦ 나', '가']  # 마지막 줄부터 넣어야 순서가 맞고, 첫 줄은 첫 불릿 문단에 마지막으로 들어간다
    last = section_two[-1]
    assert last[last.index('--offset') + 1] == '3'


def test_a_section_without_text_still_loses_its_skeleton_but_gets_no_insert(monkeypatch):
    commands = []
    monkeypatch.setattr(hwp_export, '_run_rhwp', lambda args: commands.append(args) or '')
    tmp = iter(f'/tmp/{i}.hwp' for i in range(500))
    data = _data()
    data.문제인식_본문 = data.팀구성_본문 = ''

    hwp_export._write_body_sections('/tmp/in.hwp', 'early_general', data, lambda: next(tmp))

    assert all(c[1] == 'delete-paragraph' for c in commands) and len(commands) == 11 + 5 + 19 + 9


# ── 정리한 양식 · 스크립트 ───────────────────────────────────────────────────────
def test_strip_removes_only_tables_inside_cells():
    module = _load_script()
    xml = ('<hp:tbl id="outer"><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:tbl id="guide"><hp:tr><hp:tc>'
           '<hp:subList><hp:p><hp:run><hp:t>※ 예시</hp:t></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p></hp:subList></hp:tc>'
           '<hp:tc><hp:subList><hp:p><hp:run><hp:t>값 칸</hp:t></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl>'
           '<hp:tbl id="second"><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:t>다른 표</hp:t></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl>')

    out, removed = module.strip_nested_tables(xml)

    assert removed == 1
    assert 'id="guide"' not in out and '※ 예시' not in out
    assert 'id="outer"' in out and 'id="second"' in out and '값 칸' in out and '다른 표' in out


def _rhwp(args):
    out = subprocess.run([hwp_export.RHWP_BIN, *args], capture_output=True, text=True, encoding='utf-8', check=True)
    return out.stdout


@pytest.mark.skipif(not _RHWP_AVAILABLE, reason='rhwp 실행 파일이 없다(RHWP_BIN)')
@pytest.mark.parametrize('template', ['preliminary', 'early_general'])
def test_cleaned_templates_have_no_guide_boxes_and_keep_the_original_structure(template):
    cleaned = pathlib.Path(hwp_export._HWP_TEMPLATE_DIR) / hwp_export._HWP_TEMPLATE_FILES[template]
    original = cleaned.with_name(cleaned.name.replace('_정리', ''))

    assert original.is_file() and cleaned.is_file()
    assert '내부표' not in _rhwp(['dump', str(cleaned)])
    old, new = (json.loads(_rhwp(['explain', str(p), '--json'])) for p in (original, cleaned))
    assert (new['pageCount'], new['paragraphCount'], len(new['tables'])) == (old['pageCount'], old['paragraphCount'], len(old['tables']))


def _create(client, applicant_type):
    payload = {'applicant_type': applicant_type, 'biz_type': '법인' if applicant_type == 'corp' else '개인', 'ceo_name': '박테스트',
               'description': 'AI 서비스', 'team_members': [], 'pricing_items': []}
    if applicant_type == 'corp':
        payload.update(founded_at='2024-01-01')
    r = client.post('/projects', data={'payload': json.dumps(payload)})
    assert r.status_code == 201, r.text
    return r.json()['project_id']


@pytest.mark.skipif(not _RHWP_AVAILABLE, reason='rhwp 실행 파일이 없다(RHWP_BIN)')
@pytest.mark.parametrize('applicant_type,template', [('preliminary', 'preliminary'), ('corp', 'early_general')])
def test_real_hwp_body_is_one_paragraph_per_line_without_guide_text_or_empty_dashes(authed_client, db_session, tmp_path, applicant_type, template):
    pid = _create(authed_client, applicant_type)
    texts = PlanTexts(문제인식_본문='문제 첫째 줄\n문제 둘째 줄', 실현가능성_본문='실현 첫째 줄\n실현 둘째 줄', 실현가능성_일정_서술='1. 일정 서술',
                      성장전략_본문='성장 첫째 줄\n성장 둘째 줄', 팀구성_본문='[대표자 보유 역량]\n대표자 역량')
    data, found = _build_plan_document_data(db_session, db_session.get(Project, pid), texts)
    assert found == template
    path = tmp_path / 'out.hwp'
    path.write_bytes(hwp_export.render_plan_hwp(data, template))

    pages = json.loads(_rhwp(['export-text', str(path), '--json']))['pages']
    lines = [line.strip() for page in pages for line in page['text'].split('\n')]

    for expected in ('문제 첫째 줄', '문제 둘째 줄', '실현 첫째 줄', '실현 둘째 줄', '1. 일정 서술', '성장 첫째 줄', '성장 둘째 줄', '[대표자 보유 역량]', '대표자 역량'):
        assert any(line.endswith(expected) for line in lines), expected
    assert '실현 첫째 줄 / 실현 둘째 줄' not in ' '.join(lines)  # 예전처럼 한 문단으로 이어 붙이지 않는다
    assert '-' not in lines  # 양식의 빈 "-" 글머리가 남지 않는다
    assert not any(line.startswith('※ 예시') or line.startswith('※ 개발하고자') for line in lines)  # 파란 예시 안내 상자가 없다
