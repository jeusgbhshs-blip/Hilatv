"""The edit set is hand-written. Expectations are not produced by the parser."""

from workers.nodes.n18_revision.corpus import evaluate


def test_self_built_set_does_not_silently_regenerate_everything() -> None:
    report = evaluate()
    assert report["self_made"] is True
    assert report["total"] >= 20
    assert report["blanket_regens"] == 0
