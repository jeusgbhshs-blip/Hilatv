"""Mock gateway with the content-safety route."""

from __future__ import annotations

from pathlib import Path

import pytest

from gateway.service import Gateway
from workers.nodes.n17_deliver.support import build_gateway


@pytest.fixture
def gateway(tmp_path: Path) -> Gateway:
    return build_gateway(tmp_path)
