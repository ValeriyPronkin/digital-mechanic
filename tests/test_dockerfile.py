"""Dockerfile слушает порт из PORT (Serverless Containers), по умолчанию 8000 (локально, compose, смоук)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
MOCK_DOCKERFILE = ROOT / "docker" / "mock.Dockerfile"


def cmd_argv(env_port: str | None, dockerfile: Path = DOCKERFILE, extra: dict[str, str] | None = None) -> list[str]:
    """Выполнить CMD из Dockerfile, подменив uvicorn на echo, и вернуть аргументы."""
    line = next(ln for ln in dockerfile.read_text(encoding="utf-8").splitlines() if ln.startswith("CMD "))
    argv = json.loads(line.removeprefix("CMD "))
    assert argv[:2] == ["sh", "-c"]
    script = argv[2].replace("exec uvicorn", "exec echo", 1)
    env = {k: v for k, v in os.environ.items() if k != "PORT"}
    env.update(extra or {})
    if env_port is not None:
        env["PORT"] = env_port
    # Команда — из собственного Dockerfile репозитория, не внешний ввод.
    proc = subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True, check=True)  # noqa: S603, S607
    return proc.stdout.split()


def cmd_port(env_port: str | None) -> str:
    out = cmd_argv(env_port)
    return out[out.index("--port") + 1]


def test_port_defaults_to_8000() -> None:
    assert cmd_port(None) == "8000"


def test_port_from_env() -> None:
    assert cmd_port("8080") == "8080"


def test_mock_image_port_and_app() -> None:
    """Заглушки на стенде: порт из PORT (Serverless Containers), приложение — из MOCK_APP."""
    out = cmd_argv("8080", MOCK_DOCKERFILE, {"MOCK_APP": "mock_toir.app:app"})
    assert out[0] == "mock_toir.app:app" and out[out.index("--port") + 1] == "8080"
    out = cmd_argv(None, MOCK_DOCKERFILE, {"MOCK_APP": "mock_ml.app:app"})
    assert out[out.index("--port") + 1] == "8001"
