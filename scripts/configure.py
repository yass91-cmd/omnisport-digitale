"""Create an ignored local environment without replacing an existing one."""

import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    path = ROOT / ".env"
    if path.exists():
        print("Existing .env preserved.")
        return
    content = (
        "OMNI_ENVIRONMENT=development\n"
        "OMNI_HTTP_PORT=8000\n"
        "OMNI_DB_HOST=127.0.0.1\n"
        "OMNI_DB_PORT=3307\n"
        "OMNI_DB_NAME=omnisport\n"
        "OMNI_DB_USER=omnisport\n"
        f"OMNI_DB_PASSWORD={secrets.token_urlsafe(30)}\n"
        f"OMNI_DB_ROOT_PASSWORD={secrets.token_urlsafe(36)}\n"
    )
    with path.open("x", encoding="utf-8") as file:
        file.write(content)
    print("Created ignored .env with separate random database passwords. Values were not printed.")


if __name__ == "__main__":
    main()
