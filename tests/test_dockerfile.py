"""Dockerfile слушает порт из PORT (Serverless Containers), по умолчанию 8000 (локально, compose, смоук)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"


def cmd_port(env_port: str | None) -> str:
    """Выполнить CMD из Dockerfile, подменив uvicorn на echo, и вернуть значение --port."""
    line = next(ln for ln in DOCKERFILE.read_text(encoding="utf-8").splitlines() if ln.startswith("CMD "))
    argv = json.loads(line.removeprefix("CMD "))
    assert argv[:2] == ["sh", "-c"]
    script = argv[2].replace("exec uvicorn", "exec echo", 1)
    env = {k: v for k, v in os.environ.items() if k != "PORT"}
    if env_port is not None:
        env["PORT"] = env_port
    # Команда — из собственного Dockerfile репозитория, не внешний ввод.
    proc = subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True, check=True)  # noqa: S603, S607
    out = proc.stdout.split()
    return out[out.index("--port") + 1]


def test_port_defaults_to_8000() -> None:
    assert cmd_port(None) == "8000"


def test_port_from_env() -> None:
    assert cmd_port("8080") == "8080"
