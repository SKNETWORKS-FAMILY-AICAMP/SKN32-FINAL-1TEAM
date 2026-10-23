from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException

from app import security
from app.database import SessionLocal
from app.models import RefreshToken


def test_stale_session_cannot_reuse_rotated_token(authed_client):
    raw = authed_client.cookies.get(security.REFRESH_COOKIE_NAME)
    first, second = SessionLocal(), SessionLocal()
    try:
        cached = second.query(RefreshToken).filter_by(token_hash=security._hash_token(raw)).one()
        assert cached.revoked_at is None
        security.rotate_refresh_token(first, raw)
        with pytest.raises(HTTPException) as exc:
            security.rotate_refresh_token(second, raw)
        assert exc.value.status_code == 401
        assert second.query(RefreshToken).count() == 2
    finally:
        first.close()
        second.close()


def test_two_concurrent_refreshes_have_only_one_winner(authed_client):
    raw = authed_client.cookies.get(security.REFRESH_COOKIE_NAME)
    barrier = Barrier(2)

    def rotate():
        with SessionLocal() as session:
            cached = session.query(RefreshToken).filter_by(token_hash=security._hash_token(raw)).one()
            assert cached.revoked_at is None
            barrier.wait(timeout=5)
            try:
                security.rotate_refresh_token(session, raw)
                return 200
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(rotate) for _ in range(2)]
        assert sorted(f.result(timeout=10) for f in futures) == [200, 401]
    with SessionLocal() as session:
        assert session.query(RefreshToken).count() == 2


def test_failed_issuance_rolls_back_token_consumption(authed_client, monkeypatch):
    raw = authed_client.cookies.get(security.REFRESH_COOKIE_NAME)
    real_issue = security.issue_refresh_token

    def fail(*args):
        raise RuntimeError('simulated issuance failure')

    with SessionLocal() as session:
        monkeypatch.setattr(security, 'issue_refresh_token', fail)
        with pytest.raises(RuntimeError):
            security.rotate_refresh_token(session, raw)
        row = session.query(RefreshToken).filter_by(token_hash=security._hash_token(raw)).one()
        assert row.revoked_at is None and row.rotated_to_id is None
        monkeypatch.setattr(security, 'issue_refresh_token', real_issue)
        security.rotate_refresh_token(session, raw)
