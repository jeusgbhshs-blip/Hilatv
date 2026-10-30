"""Licence proof references. Remote proofs go through the SEC-01 guard.

A citation such as ``docs/licenses.md#noto`` is stored and not opened.
An absolute path or a ``..`` segment must resolve inside the project directory.
An http(s) URL is classified by the SSRF guard. The body is downloaded only when
``HILATV_FETCH_LICENCE_PROOF`` is on, and that download uses ``fetch_bytes``.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from workers.nodes.n01_brief.ssrf import UnsafeURL, assert_public_url, fetch_bytes


class EvidenceError(ValueError):
    retryable = False


def _fetch_enabled() -> bool:
    return os.getenv("HILATV_FETCH_LICENCE_PROOF", "").strip().lower() in {"1", "true", "yes"}


def screen_evidence(ref: str, *, root: Path) -> None:
    text = ref.strip()
    if not text:
        return
    if text.startswith(("http://", "https://")):
        try:
            if _fetch_enabled():
                fetch_bytes(text, timeout=5, max_bytes=200_000)
            else:
                assert_public_url(text)
        except (UnsafeURL, ValueError) as exc:
            raise EvidenceError(f"licence proof URL is not allowed: {exc}") from exc
        return
    if text.startswith("file:"):
        path = Path(urlparse(text).path)
        _inside(path, root)
        return
    if "://" in text:
        return
    parts = Path(text).parts
    if text.startswith("/") or text.startswith("~") or ".." in parts:
        _inside(Path(text).expanduser(), root)


def _inside(path: Path, root: Path) -> None:
    base = root.resolve()
    candidate = path if path.is_absolute() else base / path
    resolved = candidate.resolve()
    if not resolved.is_relative_to(base):
        raise EvidenceError("licence proof path must stay inside the project directory")
