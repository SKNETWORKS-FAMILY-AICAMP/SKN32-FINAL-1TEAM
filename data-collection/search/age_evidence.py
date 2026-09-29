# -*- coding: utf-8 -*-
"""공고문에서 LLM 이 읽은 업력 조건을 자격 확인 화면에 **근거로만** 보여 준다 (2026-09-28, 사용자 요청 B).

왜: 기업마당 공고 2,041건은 API 에 업력 칸이 없어 자격 확인의 업력이 늘 "알 수 없음"이었다. 매일 배치 10단계
(collect/extract_conditions.py)가 첨부에서 업력을 읽어 두었지만 서비스는 그 결과를 쓰지 않았다.

어디서 읽나
  공용 DB notice_conditions 의 업력 값(검사를 통과한 것, SELECT 만)
  + 업력 재추출 결과 reports/age_rerun_luna_*/results.jsonl 에서 '살아남' 은 그 값으로 덮는다
    (공용 DB 에 아직 반영하지 않았다 — WORKLOG 2026-09-28 C-2). 환경 변수 AGE_RERUN_RESULTS 로 바꿀 수 있다

**판정에 쓰지 않는다.** 값은 LLM 추출이라 세부사업 둘이 섞이거나("3~3년"), "창업 5년 이내 **또는** 수출실적 …" 같은
또는 조건을 한 숫자로 담기도 한다(재추출 77건 중 약 11건). 그래서 판정은 '확인 필요'로 두고, 요구 칸에 "공고문 추출(추정)"
과 근거 문장을, 설명에 신청자 업력과의 참고 비교를 적는다. 결과 파일·DB 가 없으면 이 기능은 꺼지고 예전과 같다.
"""
import glob
import io
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENV = 'AGE_RERUN_RESULTS'


def rerun_path():
    if os.environ.get(ENV):
        return os.environ[ENV]
    # 버린 공고 재추출 결과만 고른다. 표본 실험(age_rerun_luna_missing_*)은 서비스 근거가 아니다 —
    # 이름순 정렬에서 'missing_' 이 날짜보다 뒤라 그냥 마지막을 고르면 표본 폴더가 잡힌다(2026-09-28)
    runs = sorted(p for p in glob.glob(os.path.join(ROOT, 'reports', 'age_rerun_luna_2*', 'results.jsonl')))
    return runs[-1] if runs else None


def _has_age(d):
    # 하한 0년만 있는 값("6개월 이상 운영" 을 0 으로 읽음)은 보여 줄 게 없다 — "업력 0년 이상" 이 된다
    return bool(d.get('age_years_min')) or d.get('age_years_max') is not None


def load(connection=None, rerun=None):
    """{'notices': {공고 ID: {min, max, quote, pre_allowed, source}}, 'sources': [...], 'error'}. **예외를 내지 않는다.**

    DB 와 파일을 따로 읽고, 한쪽이 실패하면 그쪽만 비운 채 error 에 적는다(2026-09-28 Codex 검수 P1 — 손상된
    결과 파일 한 줄이 서버 시작을 막았다). 파일은 한 줄이라도 못 읽으면 파일 전체를 쓰지 않는다(일부만 섞지 않는다).
    파일의 값은 저장된 'new' 가 아니라 원답(raw)에 **지금의** 업력 검사(extract_conditions.verify_age)를 다시 적용해 쓴다.
    """
    out = {'notices': {}, 'sources': [], 'error': None, 'hidden': 0, 'file_skipped': 0}
    errors = []
    db_sha = {}
    db_read = False       # DB 를 실제로 읽었나(연결 없음·실패면 False — 그때만 파일을 해시 대조 없이 쓴다)
    if connection is not None:
        try:
            from collect import extract_conditions as ec
            with connection.cursor() as cur:
                cur.execute('SELECT notice_id, age_years_min, age_years_max, age_source_quote, pre_startup_allowed, '
                            'input_sha256 FROM notice_conditions')
                rows = cur.fetchall()
            for nid, lo, hi, quote, pre, sha in rows:
                db_sha[nid] = sha
                if not lo and hi is None:
                    continue
                # DB 값에도 **지금의** 업력 검사를 적용한다(2026-09-28 Codex 재검수 P2 — 우대·지원금 구간 등).
                # 걸린 행은 보여 주지 않는다. DB 자체를 고치는 것은 별도 작업이다(공용 DB 쓰기)
                if ec.age_quote_problem(quote, [lo, hi]):
                    out['hidden'] += 1
                    continue
                out['notices'][nid] = {'min': lo, 'max': hi, 'quote': quote,
                                       'pre_allowed': None if pre is None else bool(pre),
                                       'source': '자격요건 추출(10단계)'}
            out['sources'].append('notice_conditions')
            db_read = True
        except Exception as exc:
            errors.append('notice_conditions: %s: %s' % (type(exc).__name__, str(exc)[:120]))
    path = rerun if rerun is not None else rerun_path()
    if path and os.path.exists(path):
        try:
            from collect import extract_conditions as ec
            found = {}
            with io.open(path, encoding='utf-8') as f:
                for line in f:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    # 파일 값은 **DB 가 업력을 갖지 않고, 지금 공고문이 재추출 때와 같을 때만** 쓴다(Codex 재검수 P2 —
                    # 옛 원답이 갱신된 DB 업력을 덮던 문제). DB 에 읽은 행이 없으면(연결 실패) 파일 값을 쓴다
                    nid = row['notice_id']
                    # DB 를 읽었는데 표가 비어 있으면(db_read) 해시를 대조할 수 없으니 파일 값을 쓰지 않는다(Codex 검수)
                    if nid in out['notices'] or (db_read and db_sha.get(nid) != row.get('document_sha256')):
                        out['file_skipped'] += 1
                        continue
                    raw = row.get('raw') or row.get('new') or {}
                    new, _ = ec.verify_age(json.loads(json.dumps(raw)))
                    if _has_age(new):
                        found[row['notice_id']] = {
                            'min': new.get('age_years_min'), 'max': new.get('age_years_max'),
                            'quote': new.get('age_source_quote'), 'pre_allowed': new.get('pre_startup_allowed'),
                            'source': '업력 재추출(luna)'}
            out['notices'].update(found)
            out['sources'].append(os.path.basename(os.path.dirname(path)))
        except Exception as exc:
            errors.append('%s: %s: %s' % (os.path.basename(os.path.dirname(path)), type(exc).__name__, str(exc)[:120]))
    out['error'] = ' · '.join(errors) or None
    return out


def range_text(ev):
    # '이내'와 '미만'을 구분하지 않는다(추출 값이 정수 하나라). 정확한 경계는 근거 문장을 본다
    lo, hi = ev.get('min'), ev.get('max')
    if lo is not None and hi is not None:
        return '%d~%d년' % (lo, hi) if lo != hi else '%d년' % lo
    if lo is not None:
        return '%d년 이상' % lo
    return '최대 %d년' % hi


def compare(ev, age_months):
    """신청자 업력(개월)과 참고 비교 한 문장. 모르면 빈 문자열.

    추출 값은 정수 하나라 원문이 "10년 미만"인지 "10년 이내"인지 모른다(2026-09-28 Codex 검수 P2 — "10년 미만"에
    업력 10년 0개월을 "범위 안"이라고 안내했다). 경계 근처(상한 N년 ~ N+1년 미만, 하한은 정확히 N년 0개월)는
    안/밖을 말하지 않고 원문 확인을 안내한다.
    """
    if not isinstance(age_months, int):
        return ''
    years = age_months / 12.0
    lo, hi = ev.get('min'), ev.get('max')
    mine = '내 업력 %d년 %d개월' % (age_months // 12, age_months % 12)
    if (hi is not None and hi <= years < hi + 1) or (lo is not None and age_months == lo * 12):
        return '%s은 경계에 걸려 있어 원문의 "이상·이하·미만·초과"를 확인해야 합니다(참고).' % mine
    inside = (lo is None or years >= lo) and (hi is None or years < hi)
    return '%s은 이 범위 %s(참고).' % (mine, '안으로 보입니다' if inside else '밖으로 보입니다')


def evidence_check(table, notice_id, age_months):
    """자격 확인의 업력 줄을 바꿀 값. (요구, 설명) 또는 None."""
    ev = ((table or {}).get('notices') or {}).get(notice_id)
    if not ev:
        return None
    need = '공고문 추출(추정): 업력 %s' % range_text(ev)
    why = ' '.join(x for x in (
        compare(ev, age_months),
        '근거: "%s"' % (ev.get('quote') or ''),
        '— LLM 이 공고문에서 읽은 값이라 자동 판정하지 않습니다. 세부사업별 조건이나 "또는" 조건이 있을 수 있으니 원문을 확인하세요.')
        if x)
    return need, why
