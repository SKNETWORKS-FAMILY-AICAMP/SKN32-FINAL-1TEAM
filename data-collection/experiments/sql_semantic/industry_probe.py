# -*- coding: utf-8 -*-
"""업종(main_industry) 강조가 **지금 실제 데이터**에서 어떻게 보이는지 눈으로 확인하는 화면 전용 모듈.

배경: `eval/industry_weight_probe.py` 로 새 질의 6개를 만들어 재 본 결과, 검색어에서 업종을
반복하거나 앞으로 옮겨도 통계적으로 유의미한 차이가 없었다(95% 구간이 0을 포함). 이 모듈은 그
결론을 다시 재는 게 아니라, **사용자가 직접 아무 입력이나 넣어서 네 변형의 결과를 눈으로
비교**할 수 있게 하는 화면용 도구다.

기존 서비스(`search/app.py`)는 파일을 고치지 않는다. 이 프로세스(뷰어, 8010 포트) 안에서만
`app.build_query` 를 요청 처리 동안 잠깐 바꿔치기했다가 즉시 되돌린다. 8000 포트에서 도는
실제 서비스 프로세스에는 영향이 없다 — 이 모듈은 **자기 프로세스 안에 서비스를 별도로
한 번 더 부팅**해서 쓴다(같은 Chroma·BM25·MySQL 을 읽기 전용으로 다시 연다).

읽기 전용: MySQL 은 SELECT 만, Chroma 는 열기만 한다. 색인·DB 를 바꾸지 않는다.
첫 요청은 모델·색인을 새로 불러오느라 시간이 걸린다(서비스 부팅과 같은 시간, 대략 1~2분).
"""
import threading

_lock = threading.Lock()

VARIANTS = ('그대로', '업종 없음', '업종 반복', '업종 앞배치')


def _industry_clause(main_industry):
    main_industry = (main_industry or '').strip()
    return ('업종: ' + main_industry) if main_industry else ''


def _make_build_fn(original, variant):
    if variant == '그대로':
        return lambda req: original(req)
    if variant == '업종 없음':
        return lambda req: original(req.model_copy(update={'main_industry': ''}))
    if variant == '업종 반복':
        def build(req):
            text = original(req)
            clause = _industry_clause(req.main_industry)
            return (text + '. ' + clause) if clause else text
        return build
    if variant == '업종 앞배치':
        def build(req):
            text = original(req.model_copy(update={'main_industry': ''}))
            clause = _industry_clause(req.main_industry)
            return (clause + '. ' + text) if clause else text
        return build
    raise ValueError(variant)


def _ensure_booted():
    """search.app 을 이 프로세스 안에서 한 번만 부팅한다. 8000 번 서비스 프로세스와는 별개다."""
    from search import app
    if app.STATE.get('collection') is None:
        app.boot()
    return app


def run(payload, top=5):
    """payload: MatchRequest 와 같은 칸(idea·applicant_type·founded_at·main_industry 등, dict).

    돌려주는 것: {변형이름: {'query': 실제 쓴 문장, 'results': [...]}}.
    main_industry 가 비어 있으면 네 변형의 문장이 전부 같아진다 — 화면에서 그 사실을 알려준다.
    """
    with _lock:                      # app.build_query 를 잠깐 공유해서 바꾸므로 한 번에 하나씩
        app = _ensure_booted()
        original_build_query = app.build_query
        req_base = app.MatchRequest(**dict(payload, top=top, search='hybrid'))
        out = {}
        try:
            for variant in VARIANTS:
                app.build_query = _make_build_fn(original_build_query, variant)
                result = app.match(req_base)
                out[variant] = {
                    'query': result['query'],
                    'results': [{'notice_id': r['notice_id'], 'title': r['title'], 'url': r['url'],
                                'score': r.get('score'), 'band': r.get('band'),
                                'apply_end': r.get('apply_end'), 'region': r.get('region')}
                               for r in result['results']],
                }
        finally:
            app.build_query = original_build_query
    return {'industry_given': bool((payload.get('main_industry') or '').strip()), 'variants': out}
