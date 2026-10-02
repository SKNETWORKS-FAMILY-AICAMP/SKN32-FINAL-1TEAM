# -*- coding: utf-8 -*-
"""Codex 판정(AI 참고 정답)과 LLM 추출을 대조한다. **표준 라이브러리만** 쓴다(FastAPI·DB 없이 돈다).

  python -X utf8 experiments/sql_semantic/label_score.py reports/label_pack_20260928

입력 (판정 꾸러미 폴더)
  answers_hidden.jsonl      LLM 답 (label_pack 이 만든다)
  applicant_labels.jsonl    Codex 판정 — 신청자 유형 (APPLICANT_TYPE_INDUSTRY_LABEL_TASK_20260928.md 형식)
  industry_labels.jsonl     Codex 판정 — 업종
출력  같은 폴더의 score.md · score.json

결정에 쓰는 숫자
  게이트 안전     LLM '예비 불가 strong'(varies 아님) 중 판정도 '불가'인 비율. 판정이 '가능'이면 **신청 가능한 공고를 뺀 오류**
  B 본문 우선     API 는 불가, LLM 은 가능인 공고 중 판정도 '가능'인 비율
  약한 불가       LLM '예비 불가 weak' 중 판정 '불가' 비율
  개인/법인 불가   LLM '불가 strong' 중 판정 '불가' 비율(유형별)
  불가 추정       LLM '불가 추정' 중 판정 '불가' 또는 '불가 추정' 비율
  놓침           LLM 이 세 유형 모두 '언급 없음'인데 판정에 '불가'가 있는 수
  업종 밀림       (공고, 신청자 대분류)마다 판정 ineligible(맞게 밀림) · eligible(잘못 밀림) · unclear
"""
import io
import json
import os
import sys
from collections import Counter

TYPES = ('pre_founder', 'sole_proprietor', 'corporation')
NO = ('not_allowed',)
NO_OR_GUESS = ('not_allowed', 'implied_no')


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with io.open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def rate(hit, total):
    return {'hit': hit, 'total': total, 'rate': round(hit / total, 3) if total else None}


def score(folder):
    hidden = {h['item_id']: h for h in read_jsonl(os.path.join(folder, 'answers_hidden.jsonl'))}
    app = {r['item_id']: r for r in read_jsonl(os.path.join(folder, 'applicant_labels.jsonl'))}
    ind = {r['item_id']: r for r in read_jsonl(os.path.join(folder, 'industry_labels.jsonl'))}
    out = {'applicant_labeled': len(app), 'industry_labeled': len(ind)}

    # ── 신청자 유형 ──
    pairs = [(hidden[i], app[i]) for i in sorted(app) if i in hidden and hidden[i]['group'] != 'industry']
    agree = {t: Counter() for t in TYPES}
    for h, lab in pairs:
        for t in TYPES:
            agree[t]['same' if h['llm'][t]['status'] == lab.get(t) else 'diff'] += 1
    out['agreement'] = {t: rate(agree[t]['same'], agree[t]['same'] + agree[t]['diff']) for t in TYPES}

    gate = [(h, lab) for h, lab in pairs if h['llm']['pre_founder']['status'] == 'not_allowed'
            and h['llm']['pre_founder']['strength'] == 'strong' and not h.get('varies')]
    out['gate_pre_strong'] = rate(sum(1 for _h, lab in gate if lab.get('pre_founder') in NO), len(gate))
    out['gate_pre_strong_wrong_allowed'] = [h['item_id'] for h, lab in gate if lab.get('pre_founder') == 'allowed']
    b = [(h, lab) for h, lab in pairs if h['group'] == 'B']
    out['b_text_over_api'] = rate(sum(1 for _h, lab in b if lab.get('pre_founder') == 'allowed'), len(b))
    weak = [(h, lab) for h, lab in pairs if h['llm']['pre_founder']['status'] == 'not_allowed'
            and h['llm']['pre_founder']['strength'] == 'weak']
    out['pre_weak'] = rate(sum(1 for _h, lab in weak if lab.get('pre_founder') in NO), len(weak))
    for t in ('sole_proprietor', 'corporation'):
        strong = [(h, lab) for h, lab in pairs if h['llm'][t]['status'] == 'not_allowed' and h['llm'][t]['strength'] == 'strong']
        out['%s_strong_no' % t] = rate(sum(1 for _h, lab in strong if lab.get(t) in NO), len(strong))
    guess = [(h, lab) for h, lab in pairs if h['llm']['pre_founder']['status'] == 'implied_no']
    out['pre_implied_no'] = rate(sum(1 for _h, lab in guess if lab.get('pre_founder') in NO_OR_GUESS), len(guess))
    out['pre_implied_no_but_allowed'] = [h['item_id'] for h, lab in guess if lab.get('pre_founder') == 'allowed']
    silent = [(h, lab) for h, lab in pairs if h['group'] == 'F']
    out['missed_in_F'] = [h['item_id'] for h, lab in silent if any(lab.get(t) in NO for t in TYPES)]

    # ── 업종 ──
    verdicts, wrong = Counter(), []
    weighted = Counter()
    for i in sorted(ind):
        h = hidden.get(i)
        if not h:
            continue
        for cell in ind[i].get('sections') or []:
            v = cell.get('verdict') or 'unclear'
            verdicts[v] += 1
            if v == 'eligible':
                wrong.append({'item_id': i, 'notice_id': h['notice_id'], 'section': cell.get('code')})
        weighted[ind[i].get('restricted')] += 1
    out['industry_section_verdicts'] = dict(verdicts)
    out['industry_wrong_push'] = wrong
    out['industry_restricted'] = {str(k): v for k, v in weighted.items()}
    return out


def render(folder, s):
    def pct(r):
        return '—' if r['rate'] is None else '%d/%d (%.0f%%)' % (r['hit'], r['total'], r['rate'] * 100)
    lines = ['# Codex 판정 대조 — %s' % os.path.basename(os.path.normpath(folder)), '',
             '판정은 **AI 참고 정답**(Codex)이다. 사람 정답이 아니다.', '',
             '- 판정 수: 신청자 유형 %d · 업종 %d' % (s['applicant_labeled'], s['industry_labeled']), '',
             '| 확인 | 결과 | 쓰임 |', '|---|---|---|',
             '| 예비 불가 strong → 판정도 불가 | %s | 게이트 필터 사용 여부 |' % pct(s['gate_pre_strong']),
             '| └ 판정은 "가능"(신청 가능한 공고를 뺄 오류) | %s | 0이어야 한다 |' % (', '.join(s['gate_pre_strong_wrong_allowed']) or '없음'),
             '| B: API 불가·본문 가능 → 판정 가능 | %s | 본문을 API 보다 우선 |' % pct(s['b_text_over_api']),
             '| 예비 불가 weak → 판정 불가 | %s | 약한 근거 사용 여부 |' % pct(s['pre_weak']),
             '| 개인사업자 불가 strong → 판정 불가 | %s | 개인/법인 게이트 |' % pct(s['sole_proprietor_strong_no']),
             '| 법인 불가 strong → 판정 불가 | %s | 개인/법인 게이트 |' % pct(s['corporation_strong_no']),
             '| 예비 불가 추정 → 판정 불가·추정 | %s | 순위 신호 사용 여부 |' % pct(s['pre_implied_no']),
             '| └ 판정은 "가능" | %s | |' % (', '.join(s['pre_implied_no_but_allowed']) or '없음'),
             '| F: LLM 모두 언급 없음인데 판정 불가 | %s | 놓침 |' % (', '.join(s['missed_in_F']) or '없음'), '',
             '유형별 전체 일치: ' + ' · '.join('%s %s' % (t, pct(s['agreement'][t])) for t in TYPES), '',
             '업종 (공고×신청자 대분류): ' + ' · '.join('%s %d' % kv for kv in sorted(s['industry_section_verdicts'].items())),
             '잘못 밀림(eligible): ' + (', '.join('%s(%s)' % (w['notice_id'], w['section']) for w in s['industry_wrong_push']) or '없음')]
    return '\n'.join(lines) + '\n'


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        raise SystemExit('사용법: label_score.py <판정 꾸러미 폴더>')
    folder = argv[0]
    s = score(folder)
    with io.open(os.path.join(folder, 'score.json'), 'w', encoding='utf-8') as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    text = render(folder, s)
    with io.open(os.path.join(folder, 'score.md'), 'w', encoding='utf-8') as f:
        f.write(text)
    print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
