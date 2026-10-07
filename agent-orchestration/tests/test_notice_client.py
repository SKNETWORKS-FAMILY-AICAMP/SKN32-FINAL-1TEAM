"""공고 서버 HTTP 클라이언트 (spec 3.3) — 127.0.0.1 임시 HTTP 서버(표준 라이브러리)로만 시험한다.

- 오류 변환: 시간 초과 TimeoutError, 연결 실패 ConnectionError, HTTP 오류 코드 ProviderError(status),
  JSON 아님 FormatError. 404 + NOTICE_NOT_FOUND(상세 · 판정)는 예외가 아닌 NOT_FOUND 값, 코드 없는 404는 일반 오류.
- 공고 ID 퍼센트 인코딩, 예외 메시지에 주소 · 본문 없음, 호출을 하나씩 보내는 프로세스 공용 잠금.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from conftest import TIMING

from sbrain.agents.notice import NOT_FOUND, NoticeClient, UrllibTransport
from sbrain.orchestrator.errors import FormatError, ProviderError

NOT_FOUND_BODY = json.dumps({"code": "NOTICE_NOT_FOUND"}).encode()
REQUEST_MARK = "요청본문표식"
RESPONSE_MARK = "응답본문표식"


class TempServer:
    """127.0.0.1 임시 공고 서버. 경로별 응답(상태 · 본문 · 지연)을 정하고, 받은 요청과 동시에 처리 중인 요청 수를 남긴다."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], tuple[int, bytes, float, dict[str, str]]] = {}
        self.requests: list[dict] = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        # 끌 때(shutdown) 기다리는 시간 = 반복 확인 간격. 기본 0.5초 → 0.01초 (테스트마다 서버를 따로 띄운다)
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    def set(self, method: str, path: str, status: int = 200, body: bytes | dict | list = b"{}",
            delay: float = 0.0, headers: dict[str, str] | None = None) -> None:
        raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.routes[(method, path)] = (status, raw, delay, headers or {})

    def reset_counts(self) -> None:
        with self._lock:
            self.active = self.max_active = 0

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def _serve(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                with server._lock:
                    server.requests.append({"method": self.command, "path": self.path,
                                            "headers": dict(self.headers), "body": body})
                    server.active += 1
                    server.max_active = max(server.max_active, server.active)
                status, raw, delay, headers = server.routes.get((self.command, self.path), (404, b"", 0.0, {}))
                try:
                    time.sleep(delay)
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(raw)))
                    for k, v in headers.items():
                        self.send_header(k, v)
                    self.end_headers()
                    self.wfile.write(raw)
                except OSError:
                    pass                                   # 클라이언트가 먼저 끊음 (시간 초과 시험)
                finally:
                    with server._lock:
                        server.active -= 1

            do_GET = do_POST = _serve

            def log_message(self, *args) -> None:
                pass

        return Handler


@pytest.fixture
def server():
    srv = TempServer()
    yield srv
    srv.close()


def caught(fn) -> Exception:
    with pytest.raises(Exception) as e:
        fn()
    return e.value


def assert_clean(exc: Exception, server: TempServer) -> None:
    """예외 메시지 · 추적 출력에 주소 · 포트 · 요청 · 응답 본문이 없다."""
    text = str(exc) + repr(exc) + "".join(traceback.format_exception(exc))
    for secret in ("127.0.0.1", str(server.port), REQUEST_MARK, RESPONSE_MARK):
        assert secret not in text, secret
    assert exc.__cause__ is None and (exc.__context__ is None or exc.__suppress_context__)


# ── 정상 호출 ──────────────────────────────────────────
def test_get_and_post_json(server):
    server.set("GET", "/api/collection_status", body={"status": "정상"})
    server.set("POST", "/api/match", body={"results": [], "filtered_count": 0, "fallback_used": False})
    client = NoticeClient(server.url)
    assert client.collection_status(5) == {"status": "정상"}
    sent = {"idea": "헬스장 회원 관리", "top": 10, "offset": 0}
    assert client.match(sent, 5) == {"results": [], "filtered_count": 0, "fallback_used": False}
    post = server.requests[-1]
    assert post["method"] == "POST" and json.loads(post["body"].decode("utf-8")) == sent
    assert post["headers"]["Content-Type"].startswith("application/json")
    assert "헬스장".encode() in post["body"]                                      # 한글을 그대로 UTF-8로 보낸다


def test_base_url_with_trailing_slash_or_path_prefix(server):
    server.set("GET", "/api/collection_status", body={"status": "정상"})
    server.set("GET", "/notice/api/collection_status", body={"status": "지연"})
    assert NoticeClient(server.url + "/").collection_status(5) == {"status": "정상"}
    assert NoticeClient(server.url + "/notice/").collection_status(5) == {"status": "지연"}


def test_notice_id_is_percent_encoded(server):
    nid = "kstartup:PBLN 1/2·가"
    enc = urllib.parse.quote(nid, safe="")
    server.set("GET", f"/api/notices/{enc}", body={"notice_id": nid})
    server.set("POST", f"/api/notices/{enc}/eligibility", body={"passed": True})
    client = NoticeClient(server.url)
    assert client.notice(nid, 5) == {"notice_id": nid}
    assert client.eligibility(nid, {"applicant_type": "법인"}, 5) == {"passed": True}
    paths = [r["path"] for r in server.requests]
    assert paths == [f"/api/notices/{enc}", f"/api/notices/{enc}/eligibility"]
    assert all("%3A" in p and ":" not in p and "%2F" in p for p in paths)       # ':' · '/'도 경로 한 칸 안에


# ── 오류 변환 (spec 3.3) ────────────────────────────────
@pytest.mark.parametrize("status", [400, 401, 403, 409, 422, 429, 500, 502, 503])
def test_http_error_status_becomes_provider_error(server, status):
    server.set("GET", "/api/collection_status", status=status, body={"detail": RESPONSE_MARK})
    server.set("POST", "/api/match", status=status, body={"detail": RESPONSE_MARK})
    client = NoticeClient(server.url)
    for call in (lambda: client.collection_status(5), lambda: client.match({"idea": REQUEST_MARK}, 5)):
        e = caught(call)
        assert isinstance(e, ProviderError) and e.status == status
        assert_clean(e, server)


def test_redirect_is_not_followed(server):
    server.set("POST", "/api/match", status=302, headers={"Location": "http://example.invalid/x"})
    e = caught(lambda: NoticeClient(server.url).match({"idea": REQUEST_MARK}, 5))
    assert isinstance(e, ProviderError) and e.status == 302
    assert len(server.requests) == 1                                              # 다른 곳으로 다시 보내지 않는다


def test_404_with_not_found_code_is_a_value_for_detail_and_gate(server):
    server.set("GET", "/api/notices/k%3A1", status=404, body=NOT_FOUND_BODY)
    server.set("POST", "/api/notices/k%3A1/eligibility", status=404, body=NOT_FOUND_BODY)
    client = NoticeClient(server.url)
    assert client.notice("k:1", 5) is NOT_FOUND
    assert client.eligibility("k:1", {"applicant_type": "법인"}, 5) is NOT_FOUND


@pytest.mark.parametrize("body", [b"", b"not json", json.dumps({"code": "OTHER"}).encode(),
                                  json.dumps({"detail": "Not Found"}).encode(), json.dumps(["NOTICE_NOT_FOUND"]).encode()])
def test_404_without_not_found_code_is_provider_error(server, body):
    """본문 코드가 없는 404(경로가 아직 없는 경우 등)는 일반 오류다 — 공고 없음으로 보지 않는다."""
    server.set("GET", "/api/notices/k%3A1", status=404, body=body)
    server.set("POST", "/api/notices/k%3A1/eligibility", status=404, body=body)
    client = NoticeClient(server.url)
    for call in (lambda: client.notice("k:1", 5), lambda: client.eligibility("k:1", {}, 5)):
        e = caught(call)
        assert isinstance(e, ProviderError) and e.status == 404


def test_not_found_code_only_counts_for_detail_and_gate(server):
    server.set("GET", "/api/collection_status", status=404, body=NOT_FOUND_BODY)
    server.set("POST", "/api/match", status=404, body=NOT_FOUND_BODY)
    client = NoticeClient(server.url)
    for call in (lambda: client.collection_status(5), lambda: client.match({}, 5)):
        e = caught(call)
        assert isinstance(e, ProviderError) and e.status == 404


@TIMING
def test_timeout_becomes_timeout_error(server):
    server.set("GET", "/api/collection_status", body={"status": "정상"}, delay=1.5)
    e = caught(lambda: NoticeClient(server.url).collection_status(0.3))
    assert type(e) is TimeoutError
    assert_clean(e, server)


def test_connection_refused_becomes_connection_error(server):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()                                                                  # 아무도 듣지 않는 포트
    client = NoticeClient(f"http://127.0.0.1:{port}")
    e = caught(lambda: client.collection_status(10))
    assert type(e) is ConnectionError
    text = str(e) + repr(e) + "".join(traceback.format_exception(e))           # 추적 출력에도 원래 예외(주소)가 없다
    assert "127.0.0.1" not in text and str(port) not in text
    assert e.__cause__ is None and e.__suppress_context__


@TIMING
def test_dropped_connection_becomes_connection_error():
    """연결은 됐지만 응답 없이 끊긴 경우도 연결 실패다."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def drop() -> None:
        conn, _ = listener.accept()
        conn.recv(65536)
        conn.close()
    t = threading.Thread(target=drop, daemon=True)
    t.start()
    try:
        e = caught(lambda: NoticeClient(f"http://127.0.0.1:{port}").match({"idea": REQUEST_MARK}, 10))
    finally:
        t.join(timeout=5)
        listener.close()
    assert type(e) is ConnectionError
    assert REQUEST_MARK not in str(e) and str(port) not in str(e)


@pytest.mark.parametrize("body", [b"not json", b"", b"\xff\xfe\x00", b"NaN", b'{"bonus_score": Infinity}',
                                  f'{{"detail": "{RESPONSE_MARK}"'.encode()])
def test_non_json_success_body_is_format_error(server, body):
    server.set("GET", "/api/collection_status", body=body)
    e = caught(lambda: NoticeClient(server.url).collection_status(5))
    assert isinstance(e, FormatError)
    assert_clean(e, server)


def test_error_messages_carry_no_address_or_body(server):
    server.set("POST", "/api/match", status=500, body=RESPONSE_MARK.encode())
    server.set("GET", f"/api/notices/{urllib.parse.quote(REQUEST_MARK, safe='')}", status=503, body=b"")
    client = NoticeClient(server.url)
    errors = [caught(lambda: client.match({"idea": REQUEST_MARK}, 5)),
              caught(lambda: client.notice(REQUEST_MARK, 5))]
    for e in errors:
        assert isinstance(e, ProviderError)
        assert_clean(e, server)
    assert "500" in str(errors[0])                                                # 상태 코드는 남긴다


# ── 주소 검사 ──────────────────────────────────────────
@pytest.mark.parametrize("bad", ["", "example.invalid:8000", "ftp://example.invalid", "http://",
                                 "http://exa mple.invalid", "http://example.invalid:8000/?q=1",
                                 "http://example.invalid:99999", "http://[::1"])
def test_bad_base_url_is_refused_without_echo(bad):
    with pytest.raises(ValueError) as e:
        NoticeClient(bad)
    if bad:
        assert bad not in str(e.value) and "example.invalid" not in str(e.value)


def test_client_repr_hides_address():
    client = NoticeClient("http://example.invalid:8000")
    assert "example.invalid" not in repr(client) and "8000" not in repr(client)


# ── 하나씩 보내기 (프로세스 공용 잠금) ──────────────────────
@TIMING
def test_one_call_at_a_time_across_clients_and_apis(server):
    for method, path in (("GET", "/api/collection_status"), ("POST", "/api/match"),
                         ("GET", "/api/notices/k%3A1"), ("POST", "/api/notices/k%3A1/eligibility")):
        server.set(method, path, body={"ok": True}, delay=0.25)
    a, b = NoticeClient(server.url), NoticeClient(server.url)                     # 클라이언트가 달라도 같은 잠금
    calls = [lambda: a.collection_status(5), lambda: b.match({}, 5),
             lambda: a.notice("k:1", 5), lambda: b.eligibility("k:1", {}, 5)] * 2
    results: list = []
    gate = threading.Barrier(len(calls))

    def go(call) -> None:
        gate.wait()
        results.append(call())
    threads = [threading.Thread(target=go, args=(call,)) for call in calls]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert results == [{"ok": True}] * len(calls) and len(server.requests) == len(calls)
    assert server.max_active == 1

    # 대조: 잠금 없이 전송을 바로 부르면 임시 서버는 동시에 받는다 — 위 시험이 겹침을 잡을 수 있다
    server.reset_counts()
    transport = UrllibTransport()
    raw = threading.Barrier(3)

    def direct() -> None:
        raw.wait()
        transport("GET", server.url + "/api/collection_status", None, 5)
    threads = [threading.Thread(target=direct) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert server.max_active >= 2
