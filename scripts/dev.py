"""Start and test the project without needing Python application packages on the host."""

import argparse
import os
import shutil
import subprocess
from pathlib import Path

from configure import main as configure

ROOT = Path(__file__).resolve().parents[1]


def docker_command() -> str:
    command = shutil.which("docker")
    if command:
        return command
    if os.name == "nt":
        candidate = (
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Programs/DockerDesktop/resources/bin/docker.exe"
        )
        if candidate.is_file():
            return str(candidate)
    raise SystemExit("Docker was not found. Install/start Docker, then run this command again.")


def main():
    parser = argparse.ArgumentParser(
        description="Run the OmniSport application and its isolated database tests."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser(
        "start", help="Build/start the app and database; preserve existing data."
    )
    start.add_argument(
        "--demo", action="store_true", help="Also add the two fictional demonstration complexes."
    )
    commands.add_parser("test", help="Run tests against SQLite and a disposable MySQL database.")
    access = commands.add_parser(
        "access", help="Run the trusted role-assignment CLI in the app container."
    )
    access.add_argument("arguments", nargs=argparse.REMAINDER)
    commands.add_parser(
        "stop", help="Stop this project's services without deleting its database volume."
    )
    args = parser.parse_args()
    docker = docker_command()

    def run(*parts):
        subprocess.run([docker, "compose", *parts], cwd=ROOT, check=True)

    try:
        if args.command == "stop":
            if not (ROOT / ".env").exists():
                print("No local setup found; nothing to stop.")
                return
            run("--profile", "test", "stop", "app", "db", "migrate", "test-db")
            return
        configure()
        if args.command == "access":
            run("exec", "-T", "app", "python", "-m", "backend.app.accounts", *args.arguments)
            return
        if args.command == "start":
            run("up", "-d", "--build", "--wait", "--wait-timeout", "180", "app")
            if args.demo:
                run("--profile", "tools", "run", "--rm", "seed")
            print("Application ready at http://127.0.0.1:8000 (unless OMNI_HTTP_PORT was changed).")
        else:
            try:
                run(
                    "--profile",
                    "test",
                    "up",
                    "--build",
                    "--abort-on-container-exit",
                    "--exit-code-from",
                    "test",
                    "test",
                )
            finally:
                run("--profile", "test", "stop", "test-db")
    except subprocess.CalledProcessError as failure:
        raise SystemExit(failure.returncode) from None


if __name__ == "__main__":
    main()
