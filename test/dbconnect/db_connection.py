"""Minimal S-Brain MySQL connection utilities."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import mysql.connector
from dotenv import load_dotenv
from mysql.connector import MySQLConnection


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required database setting is missing: {name}")
    return value


def get_connection() -> MySQLConnection:
    """Open a new connection using environment variables only."""
    return mysql.connector.connect(
        host=_required_env("SBRAIN_DB_HOST"),
        port=int(os.getenv("SBRAIN_DB_PORT", "3306")),
        user=_required_env("SBRAIN_DB_USER"),
        password=_required_env("SBRAIN_DB_PASSWORD"),
        database=os.getenv("SBRAIN_DB_NAME", "s_brain"),
        connection_timeout=int(os.getenv("SBRAIN_DB_CONNECT_TIMEOUT", "10")),
    )


@contextmanager
def connection_scope() -> Iterator[MySQLConnection]:
    connection = get_connection()
    try:
        yield connection
    finally:
        if connection.is_connected():
            connection.close()


def check_connection() -> tuple[str, str]:
    """Return the selected schema and server version after a connectivity check."""
    with connection_scope() as connection:
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT DATABASE(), VERSION()")
            schema, version = cursor.fetchone()
            return str(schema), str(version)
        finally:
            cursor.close()


if __name__ == "__main__":
    schema, version = check_connection()
    print(f"Connected to schema={schema}, server_version={version}")