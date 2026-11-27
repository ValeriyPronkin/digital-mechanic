"""Каркас отвечает: /health и страница. Проверка, что CI умеет падать: сломать assert → make check красный."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service.main import app

client = TestClient(app)


def test_health_ok() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_hides_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-test-value")
    body = client.get("/health").text
    assert "sk-test-value" not in body
    assert '"llm_key_present":true' in body


def test_index_page() -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Цифровой механик" in resp.text


def test_health_shows_build_from_image(monkeypatch: pytest.MonkeyPatch) -> None:
    from service import main

    sha = "0123456789abcdef0123456789abcdef01234567"
    monkeypatch.setenv("GIT_SHA", sha)
    monkeypatch.setenv("BUILD_TIME", "2026-11-27T10:30:00Z")
    main.build_info.cache_clear()
    try:
        b = client.get("/health").json()["build"]
        assert b == {"git_sha": sha, "git_sha_short": "0123456", "built_at": "2026-11-27T10:30:00Z", "source": "image"}
    finally:
        main.build_info.cache_clear()


def test_health_build_without_build_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Локально (сборка без --build-arg, ARG по умолчанию unknown) — коммит рабочей копии, если это git."""
    from service import main

    monkeypatch.setenv("GIT_SHA", "unknown")
    monkeypatch.setenv("BUILD_TIME", "unknown")
    main.build_info.cache_clear()
    try:
        b = main.build_info()
        assert b["built_at"] is None and b["source"] in ("git", "unknown")
        assert b["source"] == "unknown" or len(b["git_sha"]) == 40
    finally:
        main.build_info.cache_clear()


def test_git_head_loose_and_packed(tmp_path: Path) -> None:
    from service.main import _git_head

    sha = "89abcdef0123456789abcdef0123456789abcdef"
    (tmp_path / "HEAD").write_text("ref: refs/heads/main\n")
    (tmp_path / "packed-refs").write_text(f"# pack-refs\n{sha} refs/heads/main\n")
    assert _git_head(tmp_path) == sha  # ветка только в packed-refs
    (tmp_path / "refs" / "heads").mkdir(parents=True)
    (tmp_path / "refs" / "heads" / "main").write_text(sha.replace("8", "7") + "\n")
    assert _git_head(tmp_path) == sha.replace("8", "7")  # свежая ссылка важнее упакованной
    assert _git_head(tmp_path / "нет") == ""
