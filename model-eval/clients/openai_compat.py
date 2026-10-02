"""OpenAI 호환 호출 어댑터 — OpenAI API와 로컬 서버(Ollama·LM Studio·vLLM)를 같은 코드로 부른다.

후보(candidates.json 한 줄)만 바꾸면 모델이 바뀐다.
  reasoning=true   추론 모델. temperature 를 보내지 않고 reasoning_effort 를 보낸다.
  reasoning=false  temperature 를 보낸다(기본 0).
  base_url         로컬 서버 주소. 없으면 OpenAI.
  json_mode        "schema"(기본, JSON 스키마 강제) | "object"(스키마를 지원하지 않는 서버용)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = ROOT / '.env') -> None:
    """model-eval/.env 를 읽어 환경 변수에 넣는다. 이미 있는 값은 덮어쓰지 않는다."""
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        if value.strip():
            os.environ.setdefault(key.strip(), value.strip())


def merge_candidates(outdir, cands: list[dict]) -> list[dict]:
    """이어서(--resume) 새 후보를 추가 실행할 때 meta.json 의 기존 후보를 지우지 않고 합친다(기존 먼저, 새 후보는 뒤에)."""
    path = Path(outdir) / 'meta.json'
    old = json.loads(path.read_text(encoding='utf-8')).get('candidates', []) if path.exists() else []
    seen = {c['id'] for c in old}
    return old + [c for c in cands if c['id'] not in seen]


def load_candidates(ids: list[str] | None = None, path: Path = ROOT / 'candidates.json') -> list[dict]:
    data = json.loads(path.read_text(encoding='utf-8'))
    found = {c['id']: c for c in data['candidates']}
    if not ids:
        return list(found.values())
    missing = [i for i in ids if i not in found]
    if missing:
        raise SystemExit('candidates.json 에 없는 후보: %s (있는 후보: %s)' % (', '.join(missing), ', '.join(found)))
    return [found[i] for i in ids]


def request_options(cand: dict) -> dict:
    if cand.get('reasoning'):
        effort = cand.get('reasoning_effort')
        return {'reasoning_effort': effort} if effort else {}
    return {'temperature': cand.get('temperature', 0)}


def make_client(cand: dict):
    """후보에 맞는 openai 클라이언트를 만든다. API 키 값은 출력하지 않는다."""
    import openai
    load_dotenv()
    base_url = cand.get('base_url')
    key = cand.get('api_key') if base_url else os.environ.get('OPENAI_API_KEY')
    if not key:
        raise SystemExit('OPENAI_API_KEY 가 없다. 환경 변수로 주거나 model-eval/.env 에 넣는다(.env.example 참고).')
    return openai.OpenAI(api_key=key, base_url=base_url) if base_url else openai.OpenAI(api_key=key)


def call(client, cand: dict, messages: list[dict], schema: dict, timeout: float = 300, tries: int = 3):
    """호출 한 건. (파싱된 JSON, 사용량) 을 돌려준다. 일시 오류는 tries 번까지 다시 보낸다.

    사용량: in/out 토큰, reasoning(추론 토큰, 출력에 포함), ms, model.
    """
    if cand.get('json_mode', 'schema') == 'object':
        response_format = {'type': 'json_object'}
    else:
        response_format = {'type': 'json_schema', 'json_schema': schema}
    last = None
    for attempt in range(tries):
        started = time.time()
        try:
            response = client.chat.completions.create(
                model=cand['model'], messages=messages, response_format=response_format,
                timeout=timeout, **request_options(cand))
            text = response.choices[0].message.content
            data = json.loads(text)
            usage = response.usage
            details = getattr(usage, 'completion_tokens_details', None)
            reasoning = getattr(details, 'reasoning_tokens', None) if details is not None else None
            return data, {'in': usage.prompt_tokens, 'out': usage.completion_tokens, 'reasoning': reasoning,
                          'ms': round((time.time() - started) * 1000), 'model': getattr(response, 'model', None),
                          'tries': attempt + 1}
        except json.JSONDecodeError as exc:       # 형식 오류도 재시도 대상(오케스트레이터 규격과 같다)
            last = exc
        except Exception as exc:                  # noqa: BLE001 — 일시 오류 여부는 아래에서 가른다
            status = getattr(exc, 'status_code', None)
            if status in (400, 401, 403, 404, 413, 422):
                raise
            last = exc
        time.sleep(2 * (attempt + 1))
    raise RuntimeError('호출 실패(%d회 시도): %s: %s' % (tries, type(last).__name__, last))


def call_text(client, cand: dict, messages: list[dict], timeout: float = 600, tries: int = 3, max_tokens: int = 32000):
    """JSON 스키마 없이 글(코드)을 그대로 받는 호출. (텍스트, 사용량)을 돌려준다.
    후보에 "api": "responses" 가 있으면 Responses API(gpt-5.x-codex 계열은 이쪽만 된다), 아니면 chat completions."""
    last = None
    for attempt in range(tries):
        started = time.time()
        try:
            if cand.get('api') == 'responses':
                kw = {'reasoning': {'effort': cand['reasoning_effort']}} if cand.get('reasoning') and cand.get('reasoning_effort') else {}
                r = client.responses.create(model=cand['model'], input=messages, max_output_tokens=max_tokens, timeout=timeout, **kw)
                text = r.output_text
                u = r.usage
                details = getattr(u, 'output_tokens_details', None)
                usage = {'in': u.input_tokens, 'out': u.output_tokens, 'reasoning': getattr(details, 'reasoning_tokens', None),
                         'ms': round((time.time() - started) * 1000), 'model': getattr(r, 'model', None), 'tries': attempt + 1}
            else:
                r = client.chat.completions.create(model=cand['model'], messages=messages, timeout=timeout,
                                                   max_completion_tokens=max_tokens, **request_options(cand))
                text = r.choices[0].message.content
                u = r.usage
                details = getattr(u, 'completion_tokens_details', None)
                usage = {'in': u.prompt_tokens, 'out': u.completion_tokens, 'reasoning': getattr(details, 'reasoning_tokens', None) if details is not None else None,
                         'ms': round((time.time() - started) * 1000), 'model': getattr(r, 'model', None), 'tries': attempt + 1}
            if not text or not text.strip():
                raise ValueError('빈 응답')
            return text, usage
        except Exception as exc:                  # noqa: BLE001
            status = getattr(exc, 'status_code', None)
            if status in (400, 401, 403, 404, 413, 422):
                raise
            last = exc
        time.sleep(2 * (attempt + 1))
    raise RuntimeError('호출 실패(%d회 시도): %s: %s' % (tries, type(last).__name__, last))


def cost_usd(cand: dict, usage: dict) -> float:
    price_in, price_out = cand['price']
    return usage['in'] / 1e6 * price_in + usage['out'] / 1e6 * price_out
