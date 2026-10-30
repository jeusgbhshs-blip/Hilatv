"""The edit set is hand-written. Expectations are not produced by the parser."""

from workers.nodes.n18_revision.corpus import evaluate


def test_edit_success_rate_clears_the_spec_line() -> None:
    report = evaluate()
    assert report["self_made"] is True
    assert report["total"] >= 20
    assert report["rate"] >= 0.85
    assert report["failures"] == []
