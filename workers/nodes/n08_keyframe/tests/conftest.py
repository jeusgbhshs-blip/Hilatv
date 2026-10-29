"""Gateway that stays on the mock adapter and keeps image bytes in memory."""

from __future__ import annotations

from pathlib import Path

import pytest

from workers.nodes.media_gateway import build_media_gateway


@pytest.fixture
def gateway(tmp_path: Path):
    return build_media_gateway(tmp_path)
