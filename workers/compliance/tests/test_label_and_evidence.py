"""The AI label cannot be removed, and licence URLs use the SSRF guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from workers.compliance.evidence import EvidenceError, screen_evidence
from workers.nodes.n01_brief.ssrf import UnsafeURL, assert_public_url
from workers.schemas.label_lock import LabelLocked, refuse_label_removal, walk_label_edits


def test_remove_instruction_is_rejected() -> None:
    with pytest.raises(LabelLocked, match="固定层"):
        refuse_label_removal("去掉 AI 标识")
    with pytest.raises(LabelLocked):
        walk_label_edits({"omit_ai_label": True, "note": "keep the picture"})
    walk_label_edits({"show_ai_label": True, "voiceover": "先看这台柱塞泵"})


def test_private_proof_url_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(EvidenceError):
        screen_evidence("http://127.0.0.1/licence.pdf", root=tmp_path)
    with pytest.raises(EvidenceError):
        screen_evidence("/etc/passwd", root=tmp_path)
    screen_evidence("docs/licenses.md#noto-sans-cjk-sc", root=tmp_path)


def test_proof_fetch_goes_through_the_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, str] = {}

    def fake(url: str, *, timeout: float, max_bytes: int) -> tuple[bytes, str]:
        seen["url"] = url
        assert timeout > 0 and max_bytes > 0
        return b"proof", "text/plain"

    monkeypatch.setattr("workers.compliance.evidence.fetch_bytes", fake)
    monkeypatch.setenv("HILATV_FETCH_LICENCE_PROOF", "1")
    screen_evidence("https://example.com/proof.pdf", root=tmp_path)
    assert seen["url"] == "https://example.com/proof.pdf"


def test_assert_public_url_rejects_loopback() -> None:
    with pytest.raises(UnsafeURL):
        assert_public_url("http://127.0.0.1/secret")
