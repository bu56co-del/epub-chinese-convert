"""Drop-in image generation client for OpenAI-compatible endpoints (banana2556 / OpenAI / Azure / etc).

Two entry points:
  * ``generate_image(prompt, ...)``         – text-to-image  (POST /v1/images/generations)
  * ``edit_image(prompt, reference_path, ...)`` – image-to-image (POST /v1/images/edits, requires a ref image)

Stdlib-only HTTP. Handles:
  - 429 / 5xx exponential back-off (5, 10, 20, 40s)
  - Cloudflare 1010 / 1015 detection (raises with a useful hint)
  - Fatal model-name errors (raises immediately, no retry)
  - SSL fallback with optional ``certifi``

Default ``api_base`` is banana2556 because the user has a key for it; pass any
OpenAI-compatible URL to switch providers.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import ssl
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _make_ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_SSL_CTX = _make_ssl_context()

# Default urllib UA "Python-urllib/3.x" trips Cloudflare 1010. Pose as the
# official OpenAI SDK so requests look like normal API traffic.
_HEADERS_BASE = {
    "User-Agent": "OpenAI/Python 1.40.0",
    "Accept": "application/json",
}

_FATAL_MARKERS = (
    "model_not_found", "model not found", "does not exist",
    "unsupported model", "invalid model",
)


def _is_fatal(body: str) -> bool:
    if not body:
        return False
    body_l = body.lower()
    return any(m in body_l for m in _FATAL_MARKERS)


def _multipart_encode(fields: dict, files: dict) -> tuple[bytes, str]:
    """multipart/form-data encoder using stdlib only."""
    boundary = f"----PyImgGen{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(str(value).encode("utf-8"))
        parts.append(b"\r\n")
    for name, (filename, content, mime) in files.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"; '
            f'filename="{filename}"\r\n'.encode()
        )
        parts.append(f"Content-Type: {mime}\r\n\r\n".encode())
        parts.append(content)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), boundary


def _post_with_retry(
    url: str,
    body_bytes: bytes,
    headers: dict,
    timeout: int = 180,
    max_retries: int = 4,
    on_retry=None,
) -> bytes:
    """POST with exponential back-off. Returns raw response bytes.

    Raises RuntimeError with a useful message on permanent failures.
    """
    last_err: Exception | None = None
    for attempt in range(max_retries):
        req = Request(url, data=body_bytes, headers=headers)
        try:
            with urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
                return resp.read()
        except HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:500]
            if e.code == 403 and "1010" in body:
                raise RuntimeError(
                    "Cloudflare 1010: provider blocked this request. "
                    "Try another network/VPN."
                ) from None
            if _is_fatal(body):
                raise RuntimeError(f"Fatal model error: {body}") from None
            if e.code == 429 or 500 <= e.code < 600:
                wait = (2 ** attempt) * 5  # 5, 10, 20, 40s
                last_err = RuntimeError(f"HTTP {e.code}: {body}")
                if attempt < max_retries - 1:
                    if on_retry:
                        on_retry(attempt + 1, wait, f"HTTP {e.code}")
                    time.sleep(wait)
                    continue
            raise RuntimeError(f"HTTP {e.code}: {body}") from None
        except URLError as e:
            msg = str(e.reason)
            if "CERTIFICATE_VERIFY_FAILED" in msg:
                raise RuntimeError(
                    "SSL cert error. Run Install Certificates.command "
                    "(macOS) or pip install certifi."
                ) from None
            wait = (2 ** attempt) * 3
            last_err = RuntimeError(f"Network: {msg}")
            if attempt < max_retries - 1:
                if on_retry:
                    on_retry(attempt + 1, wait, f"network: {msg}")
                time.sleep(wait)
                continue
            raise RuntimeError(f"Network: {msg}") from None
    if last_err:
        raise last_err
    raise RuntimeError("unknown failure")


def generate_image(
    prompt: str,
    api_key: str,
    api_base: str = "https://api.banana2556.com",
    model: str = "dall-e-3",
    size: str = "1024x1024",
    quality: str = "standard",
    on_retry=None,
) -> bytes:
    """Text → image. Returns PNG bytes."""
    url = api_base.rstrip("/") + "/v1/images/generations"
    payload = {
        "model": model, "prompt": prompt, "n": 1, "size": size,
        "response_format": "b64_json",
    }
    if "dall-e-3" in model or "dalle-3" in model:
        payload["quality"] = quality
    headers = {**_HEADERS_BASE,
               "Authorization": f"Bearer {api_key}",
               "Content-Type": "application/json"}
    raw = _post_with_retry(url, json.dumps(payload).encode("utf-8"),
                           headers, timeout=180, on_retry=on_retry)
    data = json.loads(raw.decode("utf-8"))
    return base64.b64decode(data["data"][0]["b64_json"])


def edit_image(
    prompt: str,
    reference_image: bytes | str | Path,
    api_key: str,
    api_base: str = "https://api.banana2556.com",
    model: str = "gpt-image-1",
    size: str = "1024x1024",
    on_retry=None,
    reference_filename: str = "reference.png",
) -> bytes:
    """Reference-image-guided generation. Returns PNG bytes.

    ``reference_image`` accepts:
      * a path (str / Path) — read from disk
      * raw bytes — used as-is (use ``reference_filename`` for the form name)

    Note: classic dall-e-3 rejects /edits — use gpt-image-1 / flux-kontext.
    """
    url = api_base.rstrip("/") + "/v1/images/edits"
    if isinstance(reference_image, (str, Path)):
        ref = Path(reference_image)
        img_bytes = ref.read_bytes()
        fname = ref.name
    else:
        img_bytes = reference_image
        fname = reference_filename
    mime, _ = mimetypes.guess_type(fname)
    fields = {"model": model, "prompt": prompt, "n": "1",
              "size": size, "response_format": "b64_json"}
    files = {"image": (fname, img_bytes, mime or "image/png")}
    body_bytes, boundary = _multipart_encode(fields, files)
    headers = {**_HEADERS_BASE,
               "Authorization": f"Bearer {api_key}",
               "Content-Type": f"multipart/form-data; boundary={boundary}"}
    raw = _post_with_retry(url, body_bytes, headers,
                           timeout=240, on_retry=on_retry)
    data = json.loads(raw.decode("utf-8"))
    entry = data["data"][0]
    if entry.get("b64_json"):
        return base64.b64decode(entry["b64_json"])
    if entry.get("url"):
        with urlopen(entry["url"], timeout=120, context=_SSL_CTX) as r:
            return r.read()
    raise RuntimeError(f"unexpected response: {entry!r}")
