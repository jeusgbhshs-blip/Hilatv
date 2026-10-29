"""Quality check for the N1 skeleton."""

from __future__ import annotations

from workers.nodes.n01_brief.schema import NodeResult

NO_DRAWN_TEXT = "Do not render any on-screen text, logos, prices, or phone numbers."


class QAError(Exception):
    """The node result failed this node's quality check."""


def check(result: NodeResult) -> None:
    if result.node != "n01_brief":
        raise QAError(f"unexpected node {result.node}")
    if not result.ok:
        raise QAError("n01_brief result is not ok")
    if result.payload.get("status") != "stub":
        raise QAError("n01_brief payload is missing the stub status")
    prompt = result.payload.get("prompt")
    if not isinstance(prompt, str) or NO_DRAWN_TEXT not in prompt:
        raise QAError("n01_brief prompt is missing the no-drawn-text constraint")
