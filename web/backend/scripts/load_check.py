"""부하 · 타임아웃 점검 (SB-266) — 워커가 응답하지 않을 때 대기하는 요청이 쌓이면 다른 요청이 막히는지 실제 HTTP로 본다.

    python scripts/load_check.py --url mysql+pymysql://root:sbrain-test@127.0.0.1:3307/sbrain_e2e?charset=utf8mb4

워커를 띄우지 않는다(떠 있으면 끈다). 후보 · 자격 확인 같은 조회는 워커가 끝내길 최대 ORCH_WAIT_TIMEOUT_SEC(운영 25초) 기다린 뒤 pending으로
답한다. 이 대기 동안 요청 하나가 DB 세션(연결)과 서버 작업 스레드를 하나씩 붙잡는다 — 워커가 느리거나 멈추면 이런 요청이 쌓인다.
  · 웹 DB 연결 풀: SQLAlchemy 기본(5개 + 초과 10개 = 15개), 연결을 못 얻으면 pool_timeout(30초) 뒤 오류
  · 서버 작업 스레드: FastAPI(anyio) 기본 40개
이 스크립트는 같은 대기 요청을 단계별 개수(--levels)로 동시에 보내 놓고, 그동안 DB를 쓰는 가벼운 요청(/auth/me)과 DB를 안 쓰는 요청(/docs)의
응답 시간 · 오류를 잰다. 서버는 이 프로세스 안에서 uvicorn으로 띄워 실제 HTTP로 부른다(구글 로그인은 가짜로 바꿔 끼운다).

결과를 표로 찍고 DB 연결 풀 기본값(15개)을 넘는 단계에서 가벼운 요청이 느려지는지(--slow-sec)를 알려 준다. 문제가 없으면 종료 코드 0, 있으면 1.
"""
import argparse
import os
import statistics
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e2e_worker_flow import DEFAULT_URL, FULL_INPUT, PROFILE, configure_env  # noqa: E402

if hasattr(sys.stdout, 'reconfigure'):  # 콘솔 인코딩(cp949 등)에 없는 문자(— 등)가 있어도 출력이 죽지 않게
    sys.stdout.reconfigure(errors='replace')

PORT = 8765


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', default=DEFAULT_URL)
    parser.add_argument('--levels', default='5,15,30,60', help='동시에 대기시킬 요청 개수(쉼표로 구분)')
    parser.add_argument('--timeout', type=float, default=6.0, help='대기 요청이 기다리는 시간(초). 운영 값은 25 — 점검 시간을 줄이려고 짧게 쓴다')
    parser.add_argument('--slow-sec', type=float, default=2.0, help='가벼운 요청이 이 시간보다 오래 걸리면 느린 것으로 본다')
    args = parser.parse_args()

    configure_env(args.url)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    import requests
    import uvicorn

    import app.routers.auth as auth_router
    import app.routers.projects as projects
    import app.security as security
    from app.database import engine
    from app.main import app

    security.verify_google_id_token = lambda t: {'sub': 'e2e-sub', 'email': 'e2e@example.com', 'name': 'E2E'}
    auth_router.verify_google_id_token = security.verify_google_id_token
    projects.ORCH_WAIT_TIMEOUT_SEC = args.timeout

    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=PORT, log_level='warning'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{PORT}'
    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        time.sleep(0.1)
    if not server.started:
        print('서버가 시작되지 않음')
        return 1

    pool = engine.pool
    print(f'웹 DB 연결 풀: {pool.size()}개 + 초과 {getattr(pool, "_max_overflow", "?")}개, 연결 대기 {getattr(pool, "_timeout", "?")}초 / 대기 요청 시간 {args.timeout}초(운영 25초)')

    def new_session() -> requests.Session:
        s = requests.Session()
        return s

    main_session = new_session()
    res = main_session.post(f'{base}/auth/google', json={'id_token': 'x', 'aiTrainingAgreed': True, 'notifyAgreed': True})
    assert res.status_code == 200, res.text
    main_session.patch(f'{base}/auth/consent', json={'termsAgreed': True, 'privacyAgreed': True, 'ageConfirmed': True})
    main_session.post(f'{base}/profile', json=PROFILE)
    created = main_session.post(f'{base}/projects', data={'payload': __import__('json').dumps(FULL_INPUT)})
    assert created.status_code == 201, created.text
    pid = created.json()['project_id']
    cookies = main_session.cookies.get_dict()
    print(f'프로젝트 {pid} 생성(워커가 없어 시작 요청이 처리되지 않는 상태)\n')

    def timed(session: requests.Session, path: str, timeout: float = 120) -> tuple[float, int | str]:
        started = time.monotonic()
        try:
            r = session.get(f'{base}{path}', timeout=timeout)
            return time.monotonic() - started, r.status_code
        except requests.RequestException as exc:
            return time.monotonic() - started, type(exc).__name__

    rows = []
    for level in [int(x) for x in args.levels.split(',')]:
        stop = threading.Event()
        light: list[tuple[float, int | str]] = []
        no_db: list[tuple[float, int | str]] = []
        waits: list[tuple[float, int | str]] = []

        def prober(path: str, sink: list, stop=stop):
            s = new_session()
            s.cookies.update(cookies)
            while not stop.is_set():
                sink.append(timed(s, path))
                time.sleep(0.3)

        def waiter(waits=waits):
            s = new_session()
            s.cookies.update(cookies)
            waits.append(timed(s, f'/projects/{pid}/match-candidates'))

        waiters = [threading.Thread(target=waiter) for _ in range(level)]
        probes = [threading.Thread(target=prober, args=('/auth/me', light)), threading.Thread(target=prober, args=('/docs', no_db))]
        for t in waiters:
            t.start()
        time.sleep(0.5)  # 대기 요청이 자리를 잡은 뒤에 가벼운 요청을 보낸다
        for t in probes:
            t.start()
        for t in waiters:
            t.join(timeout=120)
        time.sleep(1.0)
        stop.set()
        for t in probes:
            t.join(timeout=120)

        def worst(sink):
            return max((lat for lat, _ in sink), default=0.0)

        light_bad = [code for _, code in light if code != 200]
        rows.append((level, len(waits), sum(1 for _, c in waits if c == 200), worst(light), light_bad, worst(no_db),
                     sorted({c for _, c in no_db if c != 200}, key=str), statistics.median([lat for lat, _ in light]) if light else 0.0))
        time.sleep(1.0)

    print(f"{'대기 요청':>8} | {'끝남':>4} {'200':>4} | {'/auth/me 최대(초)':>16} {'중앙값':>7} {'오류':>10} | {'/docs 최대(초)':>13} {'오류':>6}")
    problems = []
    for level, done, ok200, light_max, light_bad, docs_max, docs_bad, light_median in rows:
        print(f'{level:>8} | {done:>4} {ok200:>4} | {light_max:>16.2f} {light_median:>7.2f} {str(light_bad[:3]) if light_bad else "-":>10} | {docs_max:>13.2f} {str(docs_bad) if docs_bad else "-":>6}')
        if light_max > args.slow_sec or light_bad:
            problems.append(f'대기 요청 {level}개에서 DB를 쓰는 가벼운 요청(/auth/me)이 최대 {light_max:.1f}초 · 오류 {light_bad[:3]}')
    print()
    if problems:
        print('문제:')
        for line in problems:
            print(f'  - {line}')
    else:
        print('모든 단계에서 가벼운 요청이 빠르게 끝남')

    server.should_exit = True
    thread.join(timeout=10)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
