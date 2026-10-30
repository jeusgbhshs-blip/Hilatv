"""Compliance gates for the visible AI label, consent, and delivery."""

from workers.schemas.label_lock import LabelLocked, refuse_label_removal

__all__ = ["LabelLocked", "refuse_label_removal"]
