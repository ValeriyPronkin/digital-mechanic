"""Индекс в бакете (D-9, #6): выкладка по статическому ключу, стенд читает по IAM-токену из метаданных."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from service import kb_store
from service.kb_store import Bucket, KbError, fetch_index, iam_auth, publish_index, sigv4_auth

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "t1.iam-token-from-metadata"  # noqa: S105 — не секрет, значение теста


class FakeS3:
    """Бакет в памяти за httpx.MockTransport + сервис метаданных. Запоминает запросы."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.requests: list[httpx.Request] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if req.url.host == "169.254.169.254":
            assert req.headers["Metadata-Flavor"] == "Google"
            return httpx.Response(200, json={"access_token": TOKEN, "expires_in": 3600, "token_type": "Bearer"})
        key = req.url.path.removeprefix("/kb/")
        if req.method == "PUT":
            assert req.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKID/")
            assert req.headers["x-amz-content-sha256"] == hashlib.sha256(req.content).hexdigest()
            self.objects[key] = req.content
            return httpx.Response(200)
        if req.headers.get("X-YaCloud-SubjectToken") != TOKEN and "authorization" not in req.headers:
            return httpx.Response(403)
        return httpx.Response(200, content=self.objects[key]) if key in self.objects else httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def make_index(path: Path) -> Path:
    (path / "cache").mkdir(parents=True)
    (path / "passport.json").write_text('{"documents": []}', encoding="utf-8")
    (path / "fragments.jsonl").write_text('{"id": "a"}\n{"id": "b"}\n', encoding="utf-8")
    (path / "vectors.npy").write_bytes(b"\x93NUMPY fake")
    (path / "cache" / "embeddings.jsonl").write_text("{}\n", encoding="utf-8")
    (path / "cache" / "extract").mkdir()
    (path / "cache" / "extract" / "big.json").write_text("не выкладывается", encoding="utf-8")
    return path


def test_sigv4_matches_aws_reference() -> None:
    """Пример GET Object из документации AWS SigV4 (подпись заголовком)."""
    sign = sigv4_auth(
        "AKIAIOSFODNN7EXAMPLE",
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        region="us-east-1",
        now=lambda: dt.datetime(2013, 5, 24, tzinfo=dt.UTC),
    )
    headers = sign(
        "GET", "https://examplebucket.s3.amazonaws.com/test.txt", {"Range": "bytes=0-9"}, hashlib.sha256().hexdigest()
    )
    assert headers["authorization"].endswith(
        "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date,"
        " Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    )


def test_publish_then_fetch_by_iam(tmp_path: Path) -> None:
    s3 = FakeS3()
    with s3.client() as http:
        version = publish_index(Bucket("kb", sigv4_auth("AKID", "secret"), http), make_index(tmp_path / "src"))
    put_keys = [r.url.path.removeprefix("/kb/") for r in s3.requests]
    assert put_keys[-1] == "index/LATEST", "LATEST пишется последним — не указывает на неполную версию"
    assert not any("extract" in k for k in put_keys), "кэш извлечения в бакет не уходит"
    assert s3.objects["index/LATEST"].decode() == version

    s3.requests.clear()
    dest = tmp_path / "index"
    with s3.client() as http:
        token = kb_store.metadata_token(http)
        assert fetch_index(Bucket("kb", iam_auth(token), http), dest) == version
    assert (dest / "fragments.jsonl").read_text(encoding="utf-8").count("\n") == 2
    assert (dest / "cache" / "embeddings.jsonl").is_file()
    assert kb_store.installed_version(dest) == version
    gets = [r for r in s3.requests if r.url.host != "169.254.169.254"]
    assert all(r.headers["X-YaCloud-SubjectToken"] == TOKEN and "authorization" not in r.headers for r in gets)

    s3.requests.clear()
    with s3.client() as http:
        fetch_index(Bucket("kb", iam_auth(TOKEN), http), dest)
    assert len(s3.requests) == 1, "та же версия повторно не качается"


def test_fetch_rejects_corrupted_file_and_keeps_old(tmp_path: Path) -> None:
    s3 = FakeS3()
    with s3.client() as http:
        version = publish_index(Bucket("kb", sigv4_auth("AKID", "secret"), http), make_index(tmp_path / "src"))
    s3.objects[f"index/{version}/fragments.jsonl"] += b"x"
    dest = tmp_path / "index"
    dest.mkdir()
    (dest / "fragments.jsonl").write_text("старый\n", encoding="utf-8")
    with s3.client() as http, pytest.raises(KbError, match="не совпал"):
        fetch_index(Bucket("kb", iam_auth(TOKEN), http), dest)
    assert (dest / "fragments.jsonl").read_text(encoding="utf-8") == "старый\n"
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []


@pytest.mark.parametrize(
    ("latest", "manifest", "error"),
    [
        ("../etc", None, "номер версии"),
        ("v1", {"files": {"../../app/x.py": {"sha256": "0", "size": 1}}}, "недопустимые файлы"),
        ("v1", {"files": {"vectors.npy": {"sha256": "0", "size": 1}}}, "нет"),
    ],
)
def test_fetch_rejects_bad_bucket_content(tmp_path: Path, latest: str, manifest: dict | None, error: str) -> None:
    s3 = FakeS3()
    s3.objects["index/LATEST"] = latest.encode()
    if manifest is not None:
        s3.objects[f"index/{latest}/MANIFEST.json"] = json.dumps(manifest).encode()
    with s3.client() as http, pytest.raises(KbError, match=error):
        fetch_index(Bucket("kb", iam_auth(TOKEN), http), tmp_path / "index")


def test_startup_reads_by_iam_even_with_static_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """На стенде статический ключ не используется, даже если попал в окружение: только IAM из метаданных."""
    s3 = FakeS3()
    with s3.client() as http:
        version = publish_index(Bucket("kb", sigv4_auth("AKID", "secret"), http), make_index(tmp_path / "src"))
    s3.requests.clear()
    monkeypatch.setenv("S3_BUCKET", "kb")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "AKID")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("INDEX_DIR", str(tmp_path / "index"))
    with s3.client() as http:
        assert kb_store.ensure_index_from_env(http) == version
    assert s3.requests[0].url.host == "169.254.169.254"
    assert not any("authorization" in r.headers for r in s3.requests)


def test_startup_without_bucket_or_token_keeps_service_up(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("S3_BUCKET", raising=False)
    assert kb_store.ensure_index_from_env(httpx.Client(transport=httpx.MockTransport(lambda r: 1 / 0))) is None

    monkeypatch.setenv("S3_BUCKET", "kb")
    monkeypatch.setenv("INDEX_DIR", str(tmp_path / "index"))
    no_metadata = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    assert kb_store.ensure_index_from_env(no_metadata) is None

    from service.main import app

    with TestClient(app) as client:  # lifespan: без метаданных сервис всё равно поднимается
        body = client.get("/health").json()
    assert body["status"] == "ok" and body["manuals_index"] == {"present": False}


def test_health_reports_index_version(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dest = make_index(tmp_path / "index")
    (dest / kb_store.VERSION_FILE).write_text("v7", encoding="utf-8")
    monkeypatch.setenv("INDEX_DIR", str(dest))
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.delenv("YANDEX_API_KEY", raising=False)
    from service.main import app

    body = TestClient(app).get("/health").json()
    assert body["manuals_index"] == {"present": True, "version": "v7", "fragments": 2, "semantic": False}


def test_stand_never_passes_static_key_to_container() -> None:
    wf = (ROOT / ".github" / "workflows" / "stand.yml").read_text(encoding="utf-8")
    assert "S3_ACCESS_KEY_ID=*|S3_SECRET_ACCESS_KEY=*" in wf, "строки статического ключа из APP_ENV отбрасываются"
    assert "secrets.S3_" not in wf
    assert '"S3_BUCKET=${S3_BUCKET}"' in wf
