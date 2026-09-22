# -*- coding: utf-8 -*-
"""정규식·v1·v2·v3 업종 추출을 Codex 판정(AI 참고 정답)과 대조한다. LLM·DB 호출 없음 — 저장된 파일만 읽는다.

  python -X utf8 reports/industry_llm_sample_20260922T050255Z/compare_codex_labels.py

**Codex 판정은 사람 정답이 아니다.** 여기 숫자는 "두 AI 가 얼마나 같게 읽는가"이다.
Codex 는 판정 전에 Claude 의 v3 요약 일부가 도구 출력에 노출됐다고 기록했다(완전한 블라인드 아님).

값 대조 규칙: 공백·가운뎃점(·ㆍ・‧)을 빼고, 한쪽이 다른 쪽을 포함하면 같은 값으로 본다.
v1·v2 의 어휘 라벨(제조업 등)은 두 글자 이상 어간(제조)이 Codex 원문 표현에 있어도 같은 값으로 본다.
"""
import csv
import io
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from experiments.sql_semantic import industry_llm_sample as s  # noqa: E402

RUNS = {'v1': 'industry_llm_sample_20260922T022756Z', 'v2': 'industry_llm_sample_20260922T023053Z',
        'v3': 'industry_llm_sample_20260922T050255Z',
        # 2026-09-22 사용자 요청 — 같은 v3 프롬프트·같은 30건을 gpt-5.6-luna(reasoning medium)로
        'luna': 'industry_llm_sample_20260922T060314Z',
        # 2026-09-22 luna 전량 원답을 검사만 다시 적용(LLM 호출 없음) — 30건은 전량 결과에서 같은 ID 를 꺼내 쓴다
        'full_strict': 'industry_llm_full_luna_20260922_strict',
        'full_rough': 'industry_llm_full_luna_20260922_rough'}
SYSTEMS = ('regex', 'v1', 'v2', 'v3', 'luna', 'full_strict', 'full_rough')
V3_SCHEMA = ('v3', 'luna', 'full_strict', 'full_rough')      # 원문 표현(allowed[].text)으로 답하는 실행
LOW = '낮음'
# 규모·형태 표현 — 업종이 아니다(지시서 기준). 값 전체가 이 말이면 규모 오답으로 센다
SIZE_WORDS = {'중소기업', '소상공인', '기업', '중견기업', '중소중견기업', '스타트업', '벤처기업', '사회적기업',
              '연구소기업', '기업부설연구소', '농가'}


def norm(x):
    return ''.join((x or '').split()).replace('·', '').replace('ㆍ', '').replace('・', '').replace('‧', '').lower()


def vmatch(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    if a in s.VOCAB and a.endswith('업') and len(a) >= 3 and norm(a[:-1]) in nb:
        return True
    return False


def split_values(text):
    return [v.strip() for v in (text or '').split(';') if v.strip()]


def load_codex(path):
    out = {}
    with io.open(path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            out[r['notice_id']] = {
                'no': int(r['번호']), 'title': r['제목'], 'sha': r['document_sha256'],
                'status': r['정답_상태(known/no_limit/unknown)'].strip(),
                'allowed': split_values(r['정답_허용업종(원문 표현, ; 로 구분)']),
                'excluded': split_values(r['정답_제외업종(원문 표현, ; 로 구분)']),
                'complete': r['정답_목록완전(Y/N/모름)'].strip(), 'confidence': r['확신도'].strip(),
                'memo': r['메모'].strip()}
    return out


def system_view(name, row):
    """(상태, 허용 값 목록, list_complete 또는 None)."""
    if name == 'regex':
        rx = row.get('regex') or {}
        vals = [v.strip() for v in (rx.get('value') or '').split(',') if v.strip()] if rx.get('status') == 'known' else []
        return rx.get('status') or 'unknown', vals, None
    llm = row.get('llm') or {}
    status = llm.get('status') or 'unknown'
    if name in V3_SCHEMA:
        vals = [a['text'] for a in llm.get('allowed') or []]
        return status, (vals if status == 'known' else []), llm.get('list_complete')
    vals = (llm.get('industries') or []) + (llm.get('other_industries') or [])
    return status, (vals if status == 'known' else []), None


def main():
    base = os.path.join(ROOT, 'reports')
    codex = load_codex(os.path.join(HERE, 'label_sheet_codex.csv'))
    runs = {k: {r['notice_id']: r for r in s.read_jsonl(os.path.join(base, v, 'results.jsonl'))} for k, v in RUNS.items()}
    v3rows = runs['v3']
    bad = [n for n, c in codex.items() if v3rows[n]['document_sha256'] != c['sha']]
    if bad:
        raise SystemExit('Codex 판정과 v3 입력 문서가 다르다: %s' % bad)
    order = sorted(codex, key=lambda n: codex[n]['no'])
    low = [n for n in order if codex[n]['confidence'] == LOW]

    def summarize(ids):
        out = {}
        for name in SYSTEMS:
            src = runs['v3'] if name == 'regex' else runs[name]
            agree, conf = 0, Counter()
            tp = fp = fn = 0
            sys_vals = sys_hit = cod_vals = cod_hit = 0
            size_wrong = []
            comp = Counter()
            for n in ids:
                c = codex[n]
                st, vals, complete = system_view(name, src[n])
                conf[(c['status'], st)] += 1
                agree += (st == c['status'])
                if st == 'known' and c['status'] == 'known':
                    tp += 1
                    sys_vals += len(vals)
                    sys_hit += sum(1 for v in vals if any(vmatch(v, cv) for cv in c['allowed']))
                    cod_vals += len(c['allowed'])
                    cod_hit += sum(1 for cv in c['allowed'] if any(vmatch(v, cv) for v in vals))
                    if complete is not None and c['complete'] in ('Y', 'N'):
                        comp[('Y' if complete else 'N', c['complete'])] += 1
                elif st == 'known':
                    fp += 1
                elif c['status'] == 'known':
                    fn += 1
                size_wrong += [(n, v) for v in vals if norm(v) in SIZE_WORDS]
            out[name] = {
                'n': len(ids), 'status_agree': agree,
                'known_both': tp, 'known_only_system': fp, 'known_only_codex': fn,
                'value_precision': round(sys_hit / sys_vals, 3) if sys_vals else None,
                'value_recall': round(cod_hit / cod_vals, 3) if cod_vals else None,
                'values_system': sys_vals, 'values_codex': cod_vals,
                'size_word_values': len(size_wrong), 'size_word_examples': size_wrong,
                'list_complete_vs_codex': {'%s→%s' % k: v for k, v in sorted(comp.items())},
                'confusion': {'%s→%s' % k: v for k, v in sorted(conf.items())}}
        return out

    all_ids, high_ids = order, [n for n in order if n not in low]
    result = {'all': summarize(all_ids), 'high_confidence_only': summarize(high_ids),
              'low_confidence_ids': low,
              'caveat': 'Codex 판정(AI 참고 정답)이며 사람 정답이 아니다. Codex 는 판정 전 v3 요약 일부 노출을 기록했다.'}

    def fmt(x):
        return '-' if x is None else ('%.2f' % x if isinstance(x, float) else str(x))

    lines = ['# 업종 추출 대조 — Codex 판정 기준 (사람 정답 아님)', '',
             '- 기준: `label_sheet_codex.csv` 30건(known 13 · unknown 17 · no_limit 0, 확신도 낮음 %d건). **AI 참고 정답이다.**' % len(low),
             '- Codex 는 판정 전에 Claude 의 v3 요약 일부가 도구 출력에 노출됐다고 기록했다 — 완전한 블라인드가 아니다.',
             '- 값 대조: 공백·가운뎃점 제거 후 포함 관계. 어휘 라벨(제조업)은 어간(제조) 포함도 같은 값.', '']
    for key, title in (('all', '전체 30건'), ('high_confidence_only', 'Codex 확신도 높음만 (%d건)' % len(high_ids))):
        lines += ['## %s' % title, '',
                  '| 방식 | 상태 일치 | 둘 다 known | 방식만 known | Codex 만 known | 값 정밀도 | 값 재현율 | 규모 표현 값 |',
                  '|---|---:|---:|---:|---:|---:|---:|---:|']
        for name in SYSTEMS:
            m = result[key][name]
            lines.append('| %s | %d/%d | %d | %d | %d | %s | %s | %d |' % (
                name, m['status_agree'], m['n'], m['known_both'], m['known_only_system'], m['known_only_codex'],
                fmt(m['value_precision']), fmt(m['value_recall']), m['size_word_values']))
        lines.append('')
    for name in V3_SCHEMA:
        lc = result['all'][name]['list_complete_vs_codex']
        lines.append('%s 목록완전 대조(둘 다 known, 방식→Codex): %s' % (name, ', '.join('%s %d' % kv for kv in lc.items()) or '-'))
    lines += ['',
              '## 공고별', '',
              '| # | 공고 | Codex | v2 | v3 | luna | 전량 엄격 | 전량 러프 | 러프 허용 값 | Codex 허용 값 |',
              '|---|---|---|---|---|---|---|---|---|---|']
    for n in order:
        c = codex[n]
        st2, _v2, _ = system_view('v2', runs['v2'][n])
        st3, _v3v, _ = system_view('v3', runs['v3'][n])
        stl, _lv, _ = system_view('luna', runs['luna'][n])
        sfs, _fsv, _ = system_view('full_strict', runs['full_strict'][n])
        sfr, frv, _ = system_view('full_rough', runs['full_rough'][n])
        mark = lambda st: st + ('' if st == c['status'] else ' ✗')  # noqa: E731
        lines.append('| %d | %s | %s%s | %s | %s | %s | %s | %s | %s | %s |' % (
            c['no'], n.split(':')[-1][-6:], c['status'], ' (낮음)' if c['confidence'] == LOW else '',
            mark(st2), mark(st3), mark(stl), mark(sfs), mark(sfr), '; '.join(frv)[:50].replace('|', '/'),
            '; '.join(c['allowed'])[:50].replace('|', '/')))
    with io.open(os.path.join(HERE, 'codex_comparison.md'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    with io.open(os.path.join(HERE, 'codex_comparison.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
