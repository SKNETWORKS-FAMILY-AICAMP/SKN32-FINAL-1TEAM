# -*- coding: utf-8 -*-
"""LLM 1차 주제 관련도 판정. 사람 검수의 초안이지 정답이 아니다.

  python -X utf8 eval/judge_llm.py --plan          할 일·예상 토큰만
  python -X utf8 eval/judge_llm.py --limit 20      20쌍만 (프롬프트 시험)
  python -X utf8 eval/judge_llm.py                 전량 (두 번씩)

같은 쌍을 **두 번** 판정한다. A 는 신청자→공고 순, B 는 공고→신청자 순으로 제시한다.
temperature 0 에서 같은 프롬프트를 두 번 부르면 거의 같은 답이 나와 흔들림을 못 본다.
제시 순서만 바꿔 답이 달라지는 쌍은 경계 사례로 보고 사람 검수 대기열에 올린다.

판정 모델은 고정한다(JUDGE_MODEL). 나중에 LLM 리랭커를 비교한다면 같은 모델을
평가 대상으로 쓰지 않는다 — 채점자와 응시자가 같으면 순환이다.

이미 판정한 (qid, notice_id, run, prompt_sha) 는 다시 부르지 않는다.
"""
import argparse
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

# 기본은 gpt-4.1-mini. 2질의 55쌍 시험에서 A/B 일치 43/55 (gpt-4o-mini 39/55),
# 4o-mini 는 지역·업력 같은 자격 조건을 근거로 점수를 깎는 경우가 많았다.
# 4.1-mini 는 대신 후하게 주는 쪽으로 틀린다. 어느 쪽이 맞는지는 블라인드 표본으로 잰다.
JUDGE_MODEL = os.environ.get('JUDGE_MODEL', 'gpt-4.1-mini')
# 1M 토큰당 USD. 추정용이다. 실제 단가는 OpenAI 요금표로 확인한다.
PRICES = {'gpt-4o-mini': (0.15, 0.60), 'gpt-4.1-mini': (0.40, 1.60), 'gpt-4.1': (2.00, 8.00),
          'gpt-4o': (2.50, 10.00)}
PRICE_IN, PRICE_OUT = PRICES.get(JUDGE_MODEL, (0.15, 0.60))

SYSTEM = """너는 정부·지자체 창업/중소기업 지원사업 검색의 평가자다.
신청자 정보 하나와 지원사업 공고 하나를 보고 **주제 관련도**를 판정한다.

판정 기준은 "이 공고가 신청자의 사업 분야·단계·필요와 주제상 맞는가" 하나다.

## 주제로 보는 것
- 공고가 지원하는 **내용**: 자금(융자·보증·보조금), 설비·스마트공장, R&D·시제품,
  수출·해외판로, 국내판로·홍보, 인력·고용, 교육·멘토링, 입주공간, 인증 등
- 공고가 겨냥한 **업종·기술·산업 분야**: 제조, SW, 바이오, 농식품, 외식 등

## 자격이라서 판정에 쓰면 안 되는 것 — 이것 때문에 점수를 깎지 않는다
- 지역 제한 (예: "안산시 관내 기업만", "[경북] 칠곡군")
- 업력·매출·기업 규모 요건 (예: "1년 이상 영업", "업력 7년 이내", "상시근로자 20인 이하")
- 사업자 형태 (예비창업자 / 개인사업자 / 법인 / 중소기업 / 소상공인)
- 마감일, 모집 상태
예) 운전자금이 필요한 인테리어업자 ↔ "진안군 소상공인 운영자금 대출(1년 이상 사업자)"
    → 지역·업력은 무시한다. 운영자금 융자라는 **내용**이 맞으므로 2.

## 특정 대상 집단 한정은 자격이 아니라 주제로 본다 → 0
공고가 장애인·제대군인·체육인·재창업자·사회적기업·경력단절여성·연구자(출연연/대학)·
특정 산업 종사자 등 **특정 집단만** 대상으로 하고, 신청자 입력에 그 집단에 속한다는
근거가 없으면 0 이다. 입력에 근거가 있으면(예: 필라테스 강사 ↔ 체육인 창업) 집단은 맞는 것으로 본다.

## topic_rel
- 2: 신청자의 업종·기술·제품을 겨냥한 공고이고, 지원 내용도 신청자 입력에 드러난 필요와 맞는다.
- 1 또는 2 (borderline=true 로 표시): 업종을 가리지 않는 공고인데 지원 내용이 신청자 필요와
     정확히 맞는다(예: 조달 진입을 원하는 봉제공장 ↔ 공공조달 진출 컨설팅). 둘 중 더 가까운
     쪽을 고르되 반드시 borderline=true.
- 1: 한쪽만 맞는다.
     · 분야 키워드는 겹치지만 교육·강연·경진대회·데모데이·네트워킹·공모전 같은 범용
       프로그램이고 신청자가 입력한 필요와 직접 맞지 않는다(예: 의료 AI 기업 ↔ AI 창업
       경진대회, 에너지 관리 기업 ↔ 기후테크 아카데미).
     · 지원 내용은 맞지만 대상 분야가 신청자와 일부만 겹친다.
- 0: 지원 내용과 대상 분야 둘 다 신청자와 연결되지 않거나, 대상 업종이 신청자와 명백히
     다르거나(예: 음식점 방지시설 ↔ SW 기업, 농식품기업 스마트공장 ↔ 금형공장),
     위의 특정 대상 집단 한정에 해당한다. 신청자 입력이 일상 문장이면 0 이다.
- null: 공고 정보가 너무 부족해 판단할 수 없다. 추측으로 고르지 않는다.

"AI", "친환경", "창업" 같은 넓은 단어가 겹친다는 이유만으로 2 를 주지 않는다.

## 출력 순서
support 에 공고가 무엇을 누구(분야·대상 집단)에게 지원하는지, ignored 에 판정에서 뺀 자격
조건을 먼저 적고, 그다음 topic_rel 을 정한다. borderline 은 두 등급 사이에서 망설였으면 true.
reason 은 한국어 한 문장으로 **지원 내용·분야·대상 집단** 기준의 근거만 쓴다."""

SCHEMA = {
    'name': 'topic_judgment',
    'strict': True,
    'schema': {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'support': {'type': 'string'},
            'ignored': {'type': 'string'},
            'topic_rel': {'type': ['integer', 'null'], 'enum': [0, 1, 2, None]},
            'borderline': {'type': 'boolean'},
            'reason': {'type': 'string'},
        },
        'required': ['support', 'ignored', 'topic_rel', 'borderline', 'reason'],
    },
}


def prompt(run, persona, notice):
    a = '[신청자]\n%s' % persona
    b = '[공고]\n%s' % notice
    return '\n\n'.join((a, b) if run == 'A' else (b, a))


PROMPT_SHA = hashlib.sha256((JUDGE_MODEL + SYSTEM + json.dumps(SCHEMA, ensure_ascii=False))
                            .encode()).hexdigest()[:12]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--limit', type=int, help='쌍 기준 상한')
    ap.add_argument('--qids', nargs='*')
    ap.add_argument('--pairs', help='이 JSONL 의 (qid, notice_id) 쌍만. 새 검색 방식 상위 결과만 채점할 때')
    ap.add_argument('--blind', action='store_true', help='블라인드 표본 쌍만 (기준을 바꾼 뒤 일치율부터 볼 때)')
    ap.add_argument('--workers', type=int, default=8)
    args = ap.parse_args()

    queries = common.load_queries()
    snap = common.load_snapshot()
    pool = [p for p in common.read_jsonl(common.POOL)
            if not args.qids or p['qid'] in args.qids]
    if args.pairs:
        want = {(r['qid'], r['notice_id']) for r in common.read_jsonl(args.pairs)}
        pool = [p for p in pool if (p['qid'], p['notice_id']) in want]
    if args.blind:
        blind = common.blind_sample(common.read_jsonl(common.POOL))
        pool = [p for p in pool if (p['qid'], p['notice_id']) in blind]
    done = {(j['qid'], j['notice_id'], j['run']) for j in common.read_jsonl(common.LLM)
            if j.get('prompt_sha') == PROMPT_SHA and j.get('topic_rel', 'err') != 'err'}

    pairs = sorted(pool, key=lambda p: (p['qid'], p['order']))
    if args.limit:
        pairs = pairs[:args.limit]
    todo = [(p, run) for p in pairs for run in ('A', 'B')
            if (p['qid'], p['notice_id'], run) not in done]
    missing = [p for p in pairs if p['notice_id'] not in snap]
    if missing:
        raise SystemExit('스냅샷에 없는 공고 %d건. build_pool.py 를 다시 돌린다.' % len(missing))

    est_in = sum(len(common.persona_text(queries[p['qid']]['payload'])) +
                 len(common.notice_text(snap[p['notice_id']])) + len(SYSTEM)
                 for p, _ in todo) * 0.9            # 한국어는 대략 글자당 0.9토큰 안팎
    print('쌍 %d · 호출 %d (이미 %d) · 모델 %s · prompt %s'
          % (len(pairs), len(todo), len(done), JUDGE_MODEL, PROMPT_SHA))
    print('예상 입력 약 %.2fM 토큰 · 약 $%.2f (추정)' % (est_in / 1e6, est_in / 1e6 * PRICE_IN * 1.1))
    if args.plan or not todo:
        return 0

    import openai
    import config
    key = config.get('OPENAI_API_KEY')
    if not key:
        print('OPENAI_API_KEY 가 .env 에 없다')
        return 1
    client = openai.OpenAI(api_key=key)

    lock = threading.Lock()
    stats = {'in': 0, 'out': 0, 'ok': 0, 'fail': 0}

    def one(p, run):
        q = queries[p['qid']]
        text = prompt(run, common.persona_text(q['payload']), common.notice_text(snap[p['notice_id']]))
        for attempt in range(6):
            try:
                r = client.chat.completions.create(
                    model=JUDGE_MODEL, temperature=0,
                    messages=[{'role': 'system', 'content': SYSTEM},
                              {'role': 'user', 'content': text}],
                    response_format={'type': 'json_schema', 'json_schema': SCHEMA})
                data = json.loads(r.choices[0].message.content)
                return {'qid': p['qid'], 'notice_id': p['notice_id'], 'run': run,
                        'topic_rel': data['topic_rel'], 'borderline': data['borderline'],
                        'support': data['support'], 'ignored': data['ignored'],
                        'reason': data['reason'], 'judge': 'llm', 'model': JUDGE_MODEL,
                        'prompt_sha': PROMPT_SHA, 'label_version': common.LABEL_VERSION,
                        'at': datetime.now(timezone.utc).isoformat(timespec='seconds')}, r.usage
            except Exception as exc:        # 한 건 실패로 전체를 멈추지 않는다
                err = '%s: %s' % (type(exc).__name__, str(exc)[:200])
                # 분당 토큰 한도(429)는 짧게 기다리면 연달아 실패한다
                time.sleep((10 if 'RateLimit' in err else 1) * 2 ** attempt)
        return {'qid': p['qid'], 'notice_id': p['notice_id'], 'run': run,
                'topic_rel': 'err', 'error': err, 'prompt_sha': PROMPT_SHA}, None

    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool_exec:
        futures = [pool_exec.submit(one, p, run) for p, run in todo]
        for i, fut in enumerate(as_completed(futures), 1):
            row, usage = fut.result()
            with lock:
                common.append_jsonl(common.LLM, [row])
                if usage:
                    stats['in'] += usage.prompt_tokens
                    stats['out'] += usage.completion_tokens
                    stats['ok'] += 1
                else:
                    stats['fail'] += 1
            if i % 100 == 0 or i == len(futures):
                print('  %d/%d · 실패 %d · %.0f초' % (i, len(futures), stats['fail'], time.time() - started))

    cost = stats['in'] / 1e6 * PRICE_IN + stats['out'] / 1e6 * PRICE_OUT
    print('완료 %d · 실패 %d · 입력 %d · 출력 %d 토큰 · 약 $%.3f'
          % (stats['ok'], stats['fail'], stats['in'], stats['out'], cost))
    if stats['fail']:
        print('실패분은 다시 실행하면 그것만 재시도한다.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
