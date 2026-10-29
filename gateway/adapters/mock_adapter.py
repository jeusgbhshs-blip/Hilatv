"""In-process adapter used when no vendor key or budget is available."""

from __future__ import annotations

from gateway.adapters.base import ModelRequest, ModelResponse


class MockAdapter:
    name = "mock"
    model = "mock-v0"

    def invoke(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            provider=self.name,
            model=self.model,
            ok=True,
            output={
                "task": request.task,
                "echo": request.prompt,
                "mock": True,
            },
            cost_cny=0.0,
        )
