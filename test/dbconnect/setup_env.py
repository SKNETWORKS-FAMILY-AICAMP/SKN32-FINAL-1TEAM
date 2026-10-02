"""Create the local root .env from the ignored DB sharing note."""

from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_FILE = PROJECT_ROOT / "docs" / "공유자료" / "이근준_db정보 공유.txt"
ENV_FILE = PROJECT_ROOT / ".env"

FIELD_MAP = {
    "Hostname": "SBRAIN_DB_HOST",
    "Port": "SBRAIN_DB_PORT",
    "Username": "SBRAIN_DB_USER",
    "Password": "SBRAIN_DB_PASSWORD",
    "Default Schema": "SBRAIN_DB_NAME",
}


def main() -> None:
    if not SOURCE_FILE.exists():
        raise FileNotFoundError(f"DB sharing note not found: {SOURCE_FILE}")

    source = SOURCE_FILE.read_text(encoding="utf-8")
    values: dict[str, str] = {}
    for source_name, env_name in FIELD_MAP.items():
        match = re.search(rf"^{re.escape(source_name)}:\s*(.+)$", source, re.MULTILINE)
        if not match:
            raise RuntimeError(f"Missing setting in DB sharing note: {source_name}")
        values[env_name] = match.group(1).strip()

    values["SBRAIN_DB_CONNECT_TIMEOUT"] = "10"
    ENV_FILE.write_text(
        "\n".join(f"{name}={value}" for name, value in values.items()) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote database settings to {ENV_FILE}")


if __name__ == "__main__":
    main()