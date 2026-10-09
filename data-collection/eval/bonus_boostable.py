# -*- coding: utf-8 -*-
"""가산점 순위 반영(결정 0015) 전 확인 — 지금 열린 공고 중 **탐색한 신청자 입력 조합에서** 확인된 가산점이 양수로 나온 공고.

  .\\.venv\\Scripts\\python.exe -X utf8 -m eval.bonus_boostable
  (--old 파일.py 를 주면 같은 조합으로 예전 계산과도 비교한다 — 결정 0016)
  (--write-reviewed 공고ID … 를 주면 원문 대조 "맞음"인 그 공고들을 search/bonus_reviewed.json 에 쓴다 — 결정 0017.
   지문·승인 항목은 도구가 지금 DB 로 채운다. 결과에는 목록과 비교한 분류(목록 안 그대로·다시 대조 필요·새 후보)가 늘 붙는다.)

결과는 탐색한 조합에서 **관측한** 공고이고, 모든 신청자 조합의 전체 집합을 증명하지는 않는다(Codex 재재검수 R2-P2-2). 공고마다 점수가 나오는 예시 입력 조합, 해당 항목·근거 문장,
근거 주변 원문을 남겨 사람(또는 AI 참고 판정)이 공고 원문과 대조하게 한다. 계산은 서버와 같다 — search/bonus 의 load·score 를
지금 공고 내용 지문·추출기 버전으로 걸러 읽어 쓴다(eval/bonus_conservative_compare 와 같은 방식). 공용 DB SELECT 만, 유료 호출 없음.

조합 찾기: 가산점 계산이 보는 입력은 성별·인증(화면 목록 14종)·생년월일·시·도·시·군·구·첫 창업 여부다. 항목마다 그 항목을 맞히는
최소 입력(candidate_inputs)을 만들고, 공고마다 ① 최소 입력 하나씩 ② 둘씩 합친 것 ③ 전부 합친 것을 score 로 돌린다.
"다 가진 신청자 하나"로 대신하지 않는 이유: 속성이 많을수록 합계 한도를 넘어 null 이 될 수 있다.
한계: 세 개 이상을 동시에 맞혀야만(그리고 전부 합치면 한도를 넘는) 양수가 되는 공고는 놓칠 수 있다 — 결과에 시도 수를 적는다.
--old: found 인 열린 공고마다 같은 조합으로 예전·새 계산을 비교해 움직임(같음·양수→null·양수→더 작은 양수·그 밖)을 센다.
  "그 밖"(0 에서 바뀜, null → 0, 양수가 커짐)이 있으면 더 엄격하게만 움직인다는 원칙에 어긋난다. "모름→양수"(null → 양수)는
  따로 센다 — 결정 0019(표 배점 칸)처럼 일부러 푼 변경만 이 움직임을 낸다.
결과: reports/bonus_boostable_<UTC 시각>Z/ (results.json · summary.md)
"""
import itertools
import json
import os
import re
import sys
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from eval.bonus_conservative_compare import APPLICANTS, applicant, open_ids  # noqa: E402

# 10/8 시험 서버 가상 신청자 5명에게 점수가 나온 공고(빠뜨림 확인용, 결정 0015 측정)
TEST_SERVER_POSITIVE = ('120481', '122057', '117356', '126642', '126819', '125997', '117928')
CONTEXT = 300                                   # 근거 문장 앞뒤로 남길 원문 글자 수
MAX_PAIRS = 400                                 # 공고 하나에서 시도할 두 개 조합의 상한


def _birth_for_age(years, today):
    """만 years 세가 되는 생년월일(그해 1월 1일생 기준, 생일이 지났다)."""
    return date(today.year - years, 1, 1).isoformat()


def candidate_inputs(item, today=None):
    """항목 하나를 True 로 만들 수 있는 최소 입력들 — [{입력 칸: 값}]. 맞힐 수 없는 종류(고용·수출 등)는 []."""
    from search import bonus
    from shared import region as region_mod
    today = today or date.today()
    kind = item.get('kind')
    certs = set(item.get('certs') or [])
    out = []
    if kind == '여성':
        out += [{'gender': '여성'}, {'certifications': ['여성기업']}]
    elif kind == '장애인':
        out.append({'certifications': ['장애인기업']})
    elif kind == '인증':
        out += [{'certifications': [c]} for c in sorted(certs & bonus.KNOWN_CERTS)]
    elif kind == '지역':
        need = sorted(c for c in bonus._extra_requirements(item) if c in bonus.KNOWN_CERTS)
        text = bonus._text(item)
        for raw in item.get('regions') or []:
            sido = region_mod.canonical(raw)
            if not sido or sido == region_mod.NATIONWIDE:
                continue
            districts = [''] + sorted(region_mod.districts_in_title(text, sido))
            if sido == '전남광주':
                districts += ['광주 광산구', '목포시']          # '광주만'·'전남만' 항목(_gwangju_side)
            for d in dict.fromkeys(districts):
                one = {'region': sido, 'district': d}
                if need:
                    one['certifications'] = need
                out.append(one)
    elif kind == '청년':
        m = bonus._AGE_LIMIT.search(bonus._text(item))
        if m:
            limit = int(m.group(1))
            out.append({'birth_date': _birth_for_age(limit - 5 if limit > 25 else limit - 1, today)})
    elif kind == '재창업':
        out.append({'first_startup': False})
    return out


def merge_inputs(parts):
    """최소 입력 여러 개 → 신청자 하나. 인증은 합치고, 지역·성별 등 값이 둘로 갈리면 None(같은 사람이 될 수 없다)."""
    merged, certs = {}, set()
    for p in parts:
        for k, v in p.items():
            if k == 'certifications':
                certs |= set(v)
            elif k in merged and merged[k] != v:
                return None
            else:
                merged[k] = v
    if certs:
        merged['certifications'] = sorted(certs)
    return merged


def trial_inputs(entry, today=None, stats=None):
    """공고 가점 한 건 → 시도할 신청자 입력 목록(하나씩·둘씩·전부, 겹침 없음).
    stats(dict)를 주면 두 개 조합을 MAX_PAIRS 에서 자른 공고 수를 'pairs_truncated' 에 센다."""
    singles = []
    for it in (entry or {}).get('items') or []:
        for c in candidate_inputs(it, today):
            if c not in singles:
                singles.append(c)
    trials = [[s] for s in singles]
    pairs = list(itertools.combinations(singles, 2))
    if len(pairs) > MAX_PAIRS and stats is not None:
        stats['pairs_truncated'] = stats.get('pairs_truncated', 0) + 1
    pairs = pairs[:MAX_PAIRS]
    trials += [list(p) for p in pairs]
    if len(singles) > 2:
        trials.append(singles)
    out, seen = [], set()
    for parts in trials:
        kw = merge_inputs(parts)
        if kw is None:
            continue
        key = json.dumps(kw, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            out.append(kw)
    return out


def find_positive(entry, today=None, stats=None):
    """공고 가점 한 건 → (양수가 나온 조합 목록 [{'input','score','items'}], 시도한 조합 수)."""
    from search import bonus
    tried = trial_inputs(entry, today, stats)
    found = []
    for kw in tried:
        value, items = bonus.score(entry, applicant(**kw))
        if value:
            found.append({'input': kw, 'score': value, 'items': items})
    return found, len(tried)


def movement(old, new):
    """예전 → 새 가산점의 움직임 이름. 더 엄격하게만 움직이면 '같음'·'양수→null'·'양수→더 작은 양수', 아니면 '그 밖'."""
    if old == new:
        return '같음'
    if old and new is None:
        return '양수→null'
    if old and new is not None and 0 < new < old:
        return '양수→더 작은 양수'
    return '그 밖'


def movement_detail(old, new):
    """movement 에 '모름→양수'(예전 null, 새 양수)를 따로 떼어 낸 이름 — 결정 0019 표 배점 칸처럼 일부러 푼 변경을
    '그 밖'(0 → 양수, 양수가 커짐 등)과 섞지 않고 센다."""
    if old is None and new is not None and new > 0:
        return '모름→양수'
    return movement(old, new)


def compare_old(table_new, table_old, old_mod, ids, today):
    """found 열린 공고 × 조합마다 예전·새 계산 비교 → ({움직임: 건수}, 예 목록)."""
    from search import bonus
    counts, examples = {}, []
    for nid in ids:
        entry = table_new.get(nid)
        if not entry or entry.get('status') != 'found':
            continue
        for kw in trial_inputs(entry, today):
            req = applicant(**kw)
            old, new = old_mod.score(table_old.get(nid), req)[0], bonus.score(entry, req)[0]
            kind = movement_detail(old, new)
            counts[kind] = counts.get(kind, 0) + 1
            if kind != '같음' and len(examples) < 200:
                examples.append({'notice_id': nid, 'input': kw, 'old': old, 'new': new, 'movement': kind})
    return counts, examples


def approved_items(combos):
    """양수 조합들에서 나온 항목(이름·배점) 전부 — 원문 대조 "맞음"이면 목록의 승인 항목이 된다."""
    seen = {}
    for c in combos:
        for i in c['items']:
            seen[(str(i['name']), float(i['points']))] = {'name': i['name'], 'points': float(i['points'])}
    return [seen[k] for k in sorted(seen)]


def review_status(reviewed, nid, entry, content_version, combos):
    """목록과 비교 — 'listed'(목록 안, 지문 같고 관측 항목이 모두 승인 안) · 'recheck'(목록 안인데 내용·가점 행이 바뀌었거나
    승인 밖 항목이 관측됨 — 다시 대조 필요) · 'new'(목록 밖 새 후보)."""
    from search import bonus
    if nid not in (reviewed or {}):
        return 'new'
    ok = all(bonus.reviewed_ok(reviewed, nid, entry, content_version, c['items']) for c in combos)
    return 'listed' if ok else 'recheck'


def write_reviewed(path, ids, table, versions, boostable, extractor_version, today, note=''):
    """원문 대조 "맞음"인 공고를 목록 파일에 쓴다(있으면 바꿈). 지문·승인 항목은 지금 DB 값. 양수가 관측되지 않은 공고는 거부."""
    data = {'version': 1, 'notices': {}}
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    for nid in ids:
        if nid not in boostable:
            raise ValueError('양수가 관측되지 않은 공고는 목록에 넣지 않는다: %s' % nid)
        entry = table[nid]
        data['notices'][nid] = {'content_version': versions.get(nid), 'row_fingerprint': entry.get('row_fingerprint'),
                                'evidence_fingerprint': entry.get('evidence_fingerprint'),
                                'extractor_version': extractor_version, 'approved_items': approved_items(boostable[nid]),
                                'reviewed_at': today.isoformat(), 'reviewed_by': 'Claude 원문 대조(AI 참고)', 'note': note}
    data['updated_at'] = today.isoformat()
    data['notices'] = dict(sorted(data['notices'].items()))
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write('\n')
    return data


def _raw_context(raw, quote):
    """원문(공백 그대로)에서 근거 문장(공백 무시)을 찾아 앞뒤 CONTEXT 글자를 돌려준다. 못 찾으면 None."""
    compact_chars, index = [], []
    for i, ch in enumerate(raw):
        if not ch.isspace():
            compact_chars.append(ch)
            index.append(i)
    q = re.sub(r'\s+', '', str(quote or ''))
    pos = ''.join(compact_chars).find(q) if q else -1
    if pos < 0:
        return None
    start, end = index[pos], index[pos + len(q) - 1] + 1
    return raw[max(0, start - CONTEXT):end + CONTEXT]


def raw_documents(connection, notice_ids):
    """{notice_id: 공고 원문(본문 + 지원대상 + 지금 달린 추출 성공 첨부, 공백 그대로)} — bonus.documents 와 같은 범위."""
    ids = sorted(notice_ids)
    if not ids:
        return {}
    marks = ','.join(['%s'] * len(ids))
    parts = {}
    with connection.cursor() as cursor:
        cursor.execute('SELECT notice_id, body, target_text FROM notices WHERE notice_id IN (%s)' % marks, tuple(ids))
        for nid, body, target in cursor.fetchall():
            parts.setdefault(nid, []).extend([body, target])
        cursor.execute('SELECT n.notice_id, at.extracted_text FROM notices n '
                       'JOIN notice_attachments na ON na.notice_fk = n.id AND na.active '
                       'JOIN attachment_texts at ON at.attachment_fk = na.id '
                       "WHERE at.last_status = 'ok' AND at.extracted_text IS NOT NULL AND n.notice_id IN (%s)" % marks,
                       tuple(ids))
        for nid, text in cursor.fetchall():
            parts.setdefault(nid, []).append(text)
    return {nid: '\n\n'.join(str(t) for t in texts if t) for nid, texts in parts.items()}


def titles(connection, notice_ids):
    ids = sorted(notice_ids)
    if not ids:
        return {}
    with connection.cursor() as cursor:
        cursor.execute('SELECT notice_id, title FROM notices WHERE notice_id IN (%s)' % ','.join(['%s'] * len(ids)),
                       tuple(ids))
        return dict(cursor.fetchall())


def run(say=print, old_path=None, write_ids=None, note=''):
    from collect.extract_bonus import EXTRACTOR_VERSION
    from search import bonus, content_version
    from shared import store_mysql
    today = date.today()
    conn = store_mysql.connect()
    try:
        versions = content_version.load(conn)
        table = bonus.load(conn, versions=versions, extractor_version=EXTRACTOR_VERSION)
        ids = open_ids(conn, today)
        boostable, tried, stats = {}, 0, {}
        for nid in ids:
            entry = table.get(nid)
            if not entry or entry.get('status') != 'found':
                continue
            combos, n = find_positive(entry, today, stats)
            tried += n
            if combos:
                boostable[nid] = combos
        names = titles(conn, boostable)
        raws = raw_documents(conn, boostable)
        old_counts = old_examples = None
        if old_path:
            from eval.bonus_conservative_compare import legacy_bonus
            old_mod = legacy_bonus(old_path)
            table_old = old_mod.load(conn, versions=versions, extractor_version=EXTRACTOR_VERSION)
            old_counts, old_examples = compare_old(table, table_old, old_mod, ids, today)
    finally:
        conn.close()

    # 원문 대조를 마친 공고 목록(결정 0017)과 비교 — 쓰기를 주면 먼저 쓰고 그 목록으로 분류한다
    reviewed_error = None
    if write_ids:
        write_reviewed(bonus.REVIEWED_PATH, write_ids, table, versions, boostable, EXTRACTOR_VERSION, today, note)
    try:
        reviewed = bonus.load_reviewed()
    except FileNotFoundError:
        reviewed = {}
    except Exception as exc:
        reviewed, reviewed_error = {}, '%s: %s' % (type(exc).__name__, exc)
    status = {nid: review_status(reviewed, nid, table[nid], versions.get(nid), combos) for nid, combos in boostable.items()}
    listed_gone = sorted(n for n in reviewed if n not in boostable)

    # 빠뜨림 확인 — 전후 비교 도구의 가상 신청자 4명(지금 DB로 다시 계산)과 10/8 시험 서버 가상 신청자 5명의 양수 공고
    persona_positive = {}
    for label, kw in APPLICANTS.items():
        req = applicant(**kw)
        persona_positive[label] = sorted(nid for nid in ids if bonus.score(table.get(nid), req)[0])
    expected = sorted({n for v in persona_positive.values() for n in v}
                      | {nid for nid in ids if nid.split('_')[-1].lstrip('0') in TEST_SERVER_POSITIVE})
    missing = [n for n in expected if n not in boostable]
    test_server_closed = [t for t in TEST_SERVER_POSITIVE if not any(nid.split('_')[-1].lstrip('0') == t for nid in ids)]

    notices = []
    for nid, combos in sorted(boostable.items()):
        entry = table[nid]
        raw = raws.get(nid, '')
        items = []
        for it in entry['items']:
            items.append({k: it.get(k) for k in ('name', 'kind', 'points', 'group', 'program', 'certs', 'regions',
                                                 'detail', 'extra_conditions', 'quote', 'in_document')}
                         | {'context': _raw_context(raw, it.get('quote'))})
        notices.append({'notice_id': nid, 'title': names.get(nid), 'source': nid.split(':')[0],
                        'max_total_points': entry.get('max_total_points'), 'bonus_info': entry.get('bonus_info'),
                        'positive_inputs': combos, 'items': items, 'review_status': status[nid],
                        'approved_items_if_added': approved_items(combos)})
    by_source = {}
    for n in notices:
        by_source[n['source']] = by_source.get(n['source'], 0) + 1
    summary = {'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'today': today.isoformat(),
               'open_notices': len(ids), 'bonus_rows': len(table), 'extractor_version': EXTRACTOR_VERSION,
               'found_open': sum(1 for nid in ids if (table.get(nid) or {}).get('status') == 'found'),
               'boostable': len(notices), 'by_source': by_source, 'combinations_tried': tried,
               'persona_positive': persona_positive, 'expected': expected, 'missing': missing,
               'test_server_positive_closed': test_server_closed,
               'method': '항목별 최소 입력 하나씩 · 둘씩(공고당 최대 %d) · 전부 합침' % MAX_PAIRS,
               'pairs_truncated_notices': stats.get('pairs_truncated', 0),
               'old': os.path.basename(old_path) if old_path else None, 'old_movements': old_counts,
               'reviewed_counts': {k: sum(1 for v in status.values() if v == k) for k in ('listed', 'recheck', 'new')},
               'reviewed_listed_not_observed': listed_gone, 'reviewed_error': reviewed_error,
               'written': list(write_ids or []),
               'openai_calls': 0, 'db_writes': 0}
    out = os.path.join(ROOT, 'reports', 'bonus_boostable_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    os.makedirs(out)
    with open(os.path.join(out, 'results.json'), 'w', encoding='utf-8') as f:
        json.dump({'summary': summary, 'notices': notices, 'old_examples': old_examples}, f, ensure_ascii=False, indent=1,
                  default=str)
    md = summary_md(summary, notices)
    with open(os.path.join(out, 'summary.md'), 'w', encoding='utf-8') as f:
        f.write(md)
    say(md)
    say('→ ' + out)
    return summary, out


def summary_md(s, notices):
    lines = ['# 탐색한 입력 조합에서 가산점이 양수로 나온 열린 공고', '',
             '- 만든 시각 %s · 기준일 %s · 열린 공고 %d건 · 가점 찾음(found) %d건 · 가점 행 %d건(%s) · 공용 DB SELECT 만'
             % (s['made_at'], s['today'], s['open_notices'], s['found_open'], s['bonus_rows'], s['extractor_version']),
             '- 조합 찾기: %s · 시도한 조합 %d개 · 두 개 조합을 상한에서 자른 공고 %d건' % (
                 s['method'], s['combinations_tried'], s.get('pairs_truncated_notices', 0)),
             '- **탐색에서 양수가 관측된 공고 %d건** (출처별 %s, 전체 집합 증명은 아님)' % (s['boostable'], ', '.join('%s %d' % kv for kv in sorted(s['by_source'].items()))),
             '- 빠뜨림 확인: 기대 %d건 중 빠진 것 %s%s' % (
                 len(s['expected']), ', '.join(s['missing']) or '없음',
                 (' · 10/8 시험 서버 양수 공고 중 지금 열린 공고가 아님: ' + ', '.join(s['test_server_positive_closed']))
                 if s['test_server_positive_closed'] else ''),
             '- 원문 대조 목록(결정 0017): 목록 안 그대로 %d · 다시 대조 필요 %d · 새 후보 %d · 목록에 있는데 이번에 양수 관측 안 됨 %s%s' % (
                 s['reviewed_counts']['listed'], s['reviewed_counts']['recheck'], s['reviewed_counts']['new'],
                 ', '.join(s['reviewed_listed_not_observed']) or '없음',
                 (' · 목록 읽기 오류 ' + s['reviewed_error']) if s.get('reviewed_error') else ''),
             '- 예전 계산 비교(%s): %s' % (s.get('old') or '안 함', ', '.join('%s %d' % kv for kv in sorted((s.get('old_movements') or {}).items())) or '-'), '',
             '| 공고 | 제목 | 예시 입력 | 가산점 | 목록 |', '|---|---|---|---|---|']
    for n in notices:
        first = n['positive_inputs'][0]
        lines.append('| %s | %s | %s | %s | %s |' % (n['notice_id'], (n['title'] or '').replace('|', '/'),
                                                     json.dumps(first['input'], ensure_ascii=False),
                                                     ' + '.join('%s %g' % (i['name'], i['points']) for i in first['items']),
                                                     {'listed': '목록 안', 'recheck': '다시 대조 필요', 'new': '새 후보'}[n['review_status']]))
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='탐색한 입력 조합에서 가산점이 양수로 나온 열린 공고(공용 DB SELECT 만)')
    ap.add_argument('--old', help='같은 조합으로 비교할 예전 bonus.py 파일')
    ap.add_argument('--write-reviewed', nargs='+', metavar='공고ID', help='원문 대조 "맞음"인 공고를 목록 파일에 쓴다(결정 0017)')
    ap.add_argument('--note', default='', help='--write-reviewed 와 함께 남길 메모')
    a = ap.parse_args()
    run(old_path=a.old, write_ids=a.write_reviewed, note=a.note)
