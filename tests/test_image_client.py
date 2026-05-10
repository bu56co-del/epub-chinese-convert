"""Tests for the OpenAI-compatible image client.

We don't hit the real network; we monkey-patch ``urlopen`` and assert on
the request shape (URL, headers, body) and the back-off / fatal-error
handling logic.
"""
from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import pytest

from epubconv.image import client as imgclient


class FakeResp:
    def __init__(self, body: bytes) -> None:
        self._body = body
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def read(self) -> bytes: return self._body


def _mk_response(png_bytes: bytes) -> bytes:
    payload = {"data": [{"b64_json": base64.b64encode(png_bytes).decode()}]}
    return json.dumps(payload).encode()


def test_generate_image_posts_to_correct_url_with_oaisdk_ua(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_urlopen(req, timeout=None, context=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = req.data
        return FakeResp(_mk_response(b"\x89PNG-fake"))

    monkeypatch.setattr(imgclient, "urlopen", fake_urlopen)

    out = imgclient.generate_image(
        prompt="a castle",
        api_key="sk-test",
        model="dall-e-3",
        size="1024x1024",
    )
    assert out == b"\x89PNG-fake"
    assert captured["url"] == "https://api.banana2556.com/v1/images/generations"
    # User-Agent must spoof OpenAI SDK to bypass Cloudflare.
    ua = next(v for k, v in captured["headers"].items() if k.lower() == "user-agent")
    assert "OpenAI" in ua
    body = json.loads(captured["body"])
    assert body["model"] == "dall-e-3"
    assert body["prompt"] == "a castle"
    assert body["size"] == "1024x1024"
    assert body["quality"] == "standard"  # added because dall-e-3
    assert body["response_format"] == "b64_json"


def test_generate_image_strips_quality_for_non_dalle3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    def fake_urlopen(req, timeout=None, context=None):
        captured["body"] = json.loads(req.data)
        return FakeResp(_mk_response(b"x"))
    monkeypatch.setattr(imgclient, "urlopen", fake_urlopen)
    imgclient.generate_image(prompt="x", api_key="sk", model="gpt-image-1")
    assert "quality" not in captured["body"]


def test_edit_image_posts_multipart_with_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    def fake_urlopen(req, timeout=None, context=None):
        captured["body"] = req.data
        captured["headers"] = dict(req.header_items())
        return FakeResp(_mk_response(b"edited"))
    monkeypatch.setattr(imgclient, "urlopen", fake_urlopen)

    out = imgclient.edit_image(
        prompt="add a sword",
        reference_image=b"\x89PNG-ref",
        reference_filename="hero.png",
        api_key="sk-test",
        model="gpt-image-1",
    )
    assert out == b"edited"

    ct = next(v for k, v in captured["headers"].items() if k.lower() == "content-type")
    assert ct.startswith("multipart/form-data; boundary=")
    body = captured["body"]
    assert b"name=\"prompt\"" in body
    assert b"add a sword" in body
    assert b"name=\"image\"; filename=\"hero.png\"" in body
    assert b"\x89PNG-ref" in body
    assert b"name=\"model\"" in body and b"gpt-image-1" in body


def test_edit_image_accepts_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    p = tmp_path / "ref.png"
    p.write_bytes(b"\x89PNG-on-disk")
    def fake_urlopen(req, timeout=None, context=None):
        assert b"\x89PNG-on-disk" in req.data
        assert b"filename=\"ref.png\"" in req.data
        return FakeResp(_mk_response(b"ok"))
    monkeypatch.setattr(imgclient, "urlopen", fake_urlopen)
    out = imgclient.edit_image(prompt="x", reference_image=p, api_key="sk")
    assert out == b"ok"


def test_fatal_model_error_raises_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = {"n": 0}
    def fake_urlopen(req, timeout=None, context=None):
        attempts["n"] += 1
        raise HTTPError(req.full_url, 400, "Bad", {},
                        BytesIO(b'{"error": {"code": "model_not_found"}}'))
    monkeypatch.setattr(imgclient, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="Fatal model error"):
        imgclient.generate_image(prompt="x", api_key="sk", model="bad-model")
    assert attempts["n"] == 1  # no retry on fatal


def test_cloudflare_1010_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req, timeout=None, context=None):
        raise HTTPError(req.full_url, 403, "Forbidden", {},
                        BytesIO(b"<html>Error 1010 ... bot</html>"))
    monkeypatch.setattr(imgclient, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="Cloudflare 1010"):
        imgclient.generate_image(prompt="x", api_key="sk")


def test_429_triggers_retry_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    def fake_urlopen(req, timeout=None, context=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise HTTPError(req.full_url, 429, "Rate limited", {},
                            BytesIO(b'{"error": {"code": "rate_limit"}}'))
        return FakeResp(_mk_response(b"ok"))
    monkeypatch.setattr(imgclient, "urlopen", fake_urlopen)
    monkeypatch.setattr(imgclient.time, "sleep", lambda s: None)  # don't actually wait

    out = imgclient.generate_image(prompt="x", api_key="sk")
    assert out == b"ok"
    assert calls["n"] == 2


def test_url_fallback_when_no_b64(monkeypatch: pytest.MonkeyPatch) -> None:
    """Some providers return image URL instead of b64_json — ``edit_image`` should fetch it."""
    fetched: dict = {}
    fake_url = "https://example.com/image.png"
    def fake_urlopen(req, timeout=None, context=None):
        url = getattr(req, "full_url", req)
        if isinstance(url, str) and url == fake_url:
            fetched["got"] = True
            return FakeResp(b"PNG-from-url")
        payload = {"data": [{"url": fake_url}]}
        return FakeResp(json.dumps(payload).encode())
    monkeypatch.setattr(imgclient, "urlopen", fake_urlopen)
    out = imgclient.edit_image(prompt="x", reference_image=b"r", api_key="sk")
    assert out == b"PNG-from-url"
    assert fetched.get("got") is True
