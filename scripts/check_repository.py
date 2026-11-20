"""Fail CI if private documents or local environment files enter Git tracking."""

import subprocess
from pathlib import PurePosixPath


def main():
    result = subprocess.run(["git", "ls-files", "-z"], check=True, capture_output=True)
    forbidden = []
    for name in result.stdout.decode().split("\0"):
        if not name:
            continue
        path = PurePosixPath(name)
        if path.suffix.lower() in {".md", ".markdown", ".pdf"}:
            forbidden.append(name)
        if path.name.startswith(".env") and path.name not in {
            ".env.example",
            ".env.sample",
            ".env.template",
        }:
            forbidden.append(name)
    if forbidden:
        raise SystemExit("Private files must not be tracked: " + ", ".join(forbidden))
    print("Repository privacy check passed.")


if __name__ == "__main__":
    main()
