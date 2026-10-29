from workers.nodes.n01_brief.accept import run_suite


def test_twenty_fixtures_are_legal_briefs(gateway) -> None:
    assert run_suite(gateway, strict=True) == []
