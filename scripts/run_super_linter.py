"""Run GitHub Super Linter locally via Docker.

Usage:
    poetry run python scripts/run_super_linter.py

Requires Docker Desktop/Engine with access to the repository directory.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

IMAGE = os.environ.get("SUPER_LINTER_IMAGE", "ghcr.io/github/super-linter:slim-latest")
DEFAULT_BRANCH = os.environ.get("DEFAULT_BRANCH", "main")
PYTHON_VERSION = os.environ.get("SUPER_LINTER_PYTHON", "3.11")


def ensure_docker() -> None:
    if shutil.which("docker") is None:
        sys.exit("Docker is required to run GitHub Super Linter locally. Install Docker Desktop/Engine and ensure 'docker' is on your PATH.")


def docker_volume_path(path: Path) -> str:
    resolved = path.resolve()
    if os.name == "nt":
        # Convert Windows paths (e.g., C:/repo) to /c/repo for Docker compatibility
        drive = resolved.drive.rstrip(":").lower()
        tail = resolved.as_posix()[2:]
        return f"/{drive}/{tail}" if tail else f"/{drive}"
    return resolved.as_posix()


def main() -> None:
    ensure_docker()
    repo_root = Path(__file__).resolve().parents[1]
    docker_path = docker_volume_path(repo_root)

    env = os.environ.copy()
    env.setdefault("RUN_LOCAL", "true")
    env.setdefault("VALIDATE_ALL_CODEBASE", "true")
    env.setdefault("DEFAULT_BRANCH", DEFAULT_BRANCH)
    env.setdefault("PYTHON_VERSION", PYTHON_VERSION)

    cmd = [
        "docker",
        "run",
        "--rm",
        "-e",
        f"RUN_LOCAL={env['RUN_LOCAL']}",
        "-e",
        f"VALIDATE_ALL_CODEBASE={env['VALIDATE_ALL_CODEBASE']}",
        "-e",
        f"DEFAULT_BRANCH={env['DEFAULT_BRANCH']}",
        "-e",
        f"PYTHON_VERSION={env['PYTHON_VERSION']}",
        "-v",
        f"{docker_path}:/tmp/lint",
        "-w",
        "/tmp/lint",
        IMAGE,
    ]

    # Only pass GITHUB_TOKEN if the user provided one
    if token := env.get("GITHUB_TOKEN"):
        cmd[4:4] = ["-e", f"GITHUB_TOKEN={token}"]

    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)