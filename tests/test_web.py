from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from epubconv.web.server import create_app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_index_serves_html_with_engine_options(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "<title>epubconv</title>" in r.text
    assert "<option>opencc</option>" in r.text  # builtin registered via entry-point


def test_convert_roundtrips_epub(client: TestClient, sample_epub: Path) -> None:
    with sample_epub.open("rb") as fh:
        r = client.post(
            "/convert",
            files={"file": ("sample.epub", fh, "application/epub+zip")},
            data={"source_lang": "zh-CN", "target_lang": "zh-TW", "writing_mode": "preserve"},
        )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/epub+zip"
    assert r.content[:4] == b"PK\x03\x04"  # ZIP magic
    assert "sample.zh-TW.epub" in r.headers.get("content-disposition", "")


def test_convert_rejects_bad_writing_mode(client: TestClient, sample_epub: Path) -> None:
    with sample_epub.open("rb") as fh:
        r = client.post(
            "/convert",
            files={"file": ("sample.epub", fh, "application/epub+zip")},
            data={"writing_mode": "sideways"},
        )
    assert r.status_code == 400


def test_convert_rejects_unknown_engine(client: TestClient, sample_epub: Path) -> None:
    with sample_epub.open("rb") as fh:
        r = client.post(
            "/convert",
            files={"file": ("sample.epub", fh, "application/epub+zip")},
            data={"engine_name": "no-such-engine"},
        )
    assert r.status_code == 400


def test_diff_returns_html(client: TestClient, sample_epub: Path) -> None:
    with sample_epub.open("rb") as fh:
        r = client.post(
            "/diff",
            files={"file": ("sample.epub", fh, "application/epub+zip")},
            data={"source_lang": "zh-CN", "target_lang": "zh-TW"},
        )
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "epubconv diff" in r.text
