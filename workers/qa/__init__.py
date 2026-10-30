"""N9/N11 quality service. Nodes call this package; they do not talk to vendors."""

from __future__ import annotations

__all__ = ["review_shot"]


def __getattr__(name: str):
    if name == "review_shot":
        from workers.qa.service import review_shot

        return review_shot
    raise AttributeError(name)
