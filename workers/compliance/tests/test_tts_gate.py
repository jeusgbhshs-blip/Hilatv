"""Gateway.tts refuses a caller that did not pass through consent_gate."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from gateway.errors import GatewayError
from gateway.tests.conftest import build_gateway, mock_llm_routes
from workers.brand_kit.people import ConsentError
from workers.compliance.consent_gate import issue_tts_consent

_ROOT = Path(__file__).resolve().parents[3]
_TTS_ALLOW = {
    "gateway/service.py",
    "gateway/accept_media.py",
    "workers/compliance/consent_gate.py",
    "workers/compliance/tests/test_tts_gate.py",
}
_MINT_ALLOW = {
    "workers/compliance/voice_token.py",
    "workers/compliance/consent_gate.py",
}


def test_direct_tts_is_rejected(tmp_path: Path) -> None:
    gateway = build_gateway(tmp_path, routes=mock_llm_routes())
    with pytest.raises(GatewayError, match="授权门"):
        gateway.tts("你好", voice="zh_male_steady", seed=1)
    with pytest.raises(GatewayError, match="授权门"):
        gateway.execute("tts", "你好", params={"voice": "zh_male_steady"})


def test_gate_token_is_bound_to_the_voice(tmp_path: Path) -> None:
    gateway = build_gateway(tmp_path, routes=mock_llm_routes())
    token = issue_tts_consent("zh_male_steady", None)
    spoken = gateway.tts("你好", voice="zh_male_steady", seed=1, consent_token=token)
    assert spoken["voice"] == "zh_male_steady"
    with pytest.raises(GatewayError, match="不一致"):
        gateway.tts("你好", voice="zh_female_steady", seed=1, consent_token=token)


def test_unarchived_clone_cannot_mint_a_token() -> None:
    with pytest.raises(ConsentError, match="未归档声音授权"):
        issue_tts_consent("clone-not-in-archive", None)


def test_production_code_cannot_call_tts_directly() -> None:
    callers = _calls("tts")
    mint = _calls("issue_voice_token")
    assert callers == []
    assert mint == []


def _calls(name: str) -> list[str]:
    found: list[str] = []
    for path in _ROOT.rglob("*.py"):
        if any(part in {".venv", "node_modules", ".git"} for part in path.parts):
            continue
        relative = path.relative_to(_ROOT).as_posix()
        if relative.startswith("gateway/tests/"):
            continue
        if name == "tts" and relative in _TTS_ALLOW:
            continue
        if name == "issue_voice_token" and relative in _MINT_ALLOW:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = node.func
            if isinstance(called, ast.Attribute) and called.attr == name:
                found.append(f"{relative}:{node.lineno}")
            elif isinstance(called, ast.Name) and called.id == name:
                found.append(f"{relative}:{node.lineno}")
    return found
