"""Fail if a vendor SDK is imported anywhere in this repository.

Adapters may call vendor HTTP APIs. They must not import a vendor SDK, and
business code must not call vendors directly.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", ".venv", "node_modules", ".next", "__pycache__"}
FORBIDDEN_ROOTS = {
    "openai",
    "anthropic",
    "boto3",
    "botocore",
    "dashscope",
    "volcengine",
    "volcenginesdkarkruntime",
    "minio",
    "elevenlabs",
    "vertexai",
    "google.generativeai",
}
IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([a-zA-Z0-9_\.]+)", re.MULTILINE)


def test_no_vendor_sdk_imports() -> None:
    offenders: list[str] = []
    for path in REPO_ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        for match in IMPORT_RE.finditer(text):
            module = match.group(1)
            root = module.split(".", 1)[0]
            if root in FORBIDDEN_ROOTS or module in FORBIDDEN_ROOTS:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {module}")
    assert offenders == []


def test_business_code_does_not_call_vendors() -> None:
    needles = (
        "api.deepseek.com",
        "dashscope.aliyuncs.com",
        "volces.com",
        "openspeech.bytedance.com",
        "api.openai.com",
    )
    roots = [REPO_ROOT / "apps", REPO_ROOT / "workers", REPO_ROOT / "eval"]
    offenders: list[str] = []
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix not in {".py", ".ts", ".tsx", ".js"}:
                continue
            text = path.read_text(encoding="utf-8")
            for needle in needles:
                if needle in text:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {needle}")
    assert offenders == []
