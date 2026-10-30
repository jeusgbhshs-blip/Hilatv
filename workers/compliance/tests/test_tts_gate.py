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


def test_gate_token_is_bound_to_the_voice_and_enterprise(tmp_path: Path) -> None:
    gateway = build_gateway(tmp_path, routes=mock_llm_routes())
    token = issue_tts_consent("zh_male_steady", "11111111-1111-4111-8111-111111111111")
    with pytest.raises(GatewayError, match="声音"):
        gateway.tts("你好", voice="zh_female_steady", seed=1, consent_token=token)
    with pytest.raises(GatewayError, match="企业"):
        gateway.tts(
            "你好",
            voice="zh_male_steady",
            seed=1,
            consent_token=token,
            enterprise_id="22222222-2222-4222-8222-222222222222",
        )
    spoken = gateway.tts(
        "你好",
        voice="zh_male_steady",
        seed=1,
        consent_token=token,
        enterprise_id="11111111-1111-4111-8111-111111111111",
    )
    assert spoken["voice"] == "zh_male_steady"
    with pytest.raises(GatewayError, match="已使用"):
        gateway.tts(
            "你好",
            voice="zh_male_steady",
            seed=1,
            consent_token=token,
            enterprise_id="11111111-1111-4111-8111-111111111111",
        )


def test_unarchived_clone_cannot_mint_a_token() -> None:
    with pytest.raises(ConsentError, match="未归档声音授权"):
        issue_tts_consent("clone-not-in-archive", None)


def test_production_code_cannot_call_tts_directly() -> None:
    callers = _calls("tts")
    mint = _calls("issue_voice_token")
    assert callers == []
    assert mint == []


def test_getattr_tts_is_treated_as_a_call() -> None:
    tree = ast.parse('result = getattr(gateway, "tts")("你好")')
    assert any(_is_tts_call(node) for node in ast.walk(tree) if isinstance(node, ast.Call))


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
            if name == "tts" and _is_tts_call(node):
                found.append(f"{relative}:{node.lineno}")
                continue
            called = node.func
            if isinstance(called, ast.Attribute) and called.attr == name:
                found.append(f"{relative}:{node.lineno}")
            elif isinstance(called, ast.Name) and called.id == name:
                found.append(f"{relative}:{node.lineno}")
    return found


def _is_tts_call(node: ast.Call) -> bool:
    called = node.func
    if isinstance(called, ast.Attribute) and called.attr == "tts":
        return True
    if isinstance(called, ast.Name) and called.id == "tts":
        return True
    if isinstance(called, ast.Call) and _is_getattr_tts(called):
        return True
    return _is_getattr_tts(node)


def _is_getattr_tts(node: ast.Call) -> bool:
    called = node.func
    is_getattr = (isinstance(called, ast.Name) and called.id == "getattr") or (
        isinstance(called, ast.Attribute) and called.attr == "getattr"
    )
    if not is_getattr or len(node.args) < 2:
        return False
    argument = node.args[1]
    return isinstance(argument, ast.Constant) and argument.value == "tts"
