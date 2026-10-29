"""Vendor HTTP adapters and the mock adapter. Business code must not import these."""

from gateway.adapters.mock_adapter import MockAdapter
from gateway.adapters.openai_compat import OpenAICompatAdapter

__all__ = ["MockAdapter", "OpenAICompatAdapter"]
