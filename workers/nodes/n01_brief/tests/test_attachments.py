from workers.nodes.n01_brief.accept import fixture_fetch
from workers.nodes.n01_brief.node import run
from workers.nodes.n01_brief.qa import check

ASSETS = "workers/nodes/n01_brief/tests/fixtures/assets"


def test_pdf_brochure_adds_product_facts(gateway) -> None:
    result = run(
        {
            "project_id": "pdf-1",
            "payload": {
                "raw_input": "根据机床画册做一条产品宣传片",
                "attachments": [
                    {"kind": "pdf", "uri": f"{ASSETS}/brochure.pdf", "filename": "brochure.pdf"}
                ],
            },
        },
        gateway=gateway,
    )
    brief = check(result)
    parsed = result.payload["attachments"][0]
    assert parsed["products"] == ["数控机床 XK-200"]
    assert "0.01mm" in parsed["specs"]
    assert any("数控机床 XK-200" in item for item in brief.assumptions)
    assert any("0.01mm" in item for item in brief.must_include)


def test_image_filenames_classify_without_a_model(gateway) -> None:
    names = {
        "logo.png": "logo",
        "product-front.png": "product",
        "person-boss.png": "person",
        "scene-workshop.png": "scene",
    }
    result = run(
        {
            "project_id": "img-1",
            "payload": {
                "raw_input": "给柱塞泵做产品宣传片",
                "attachments": [{"kind": "image", "uri": f"{ASSETS}/{name}"} for name in names],
            },
        },
        gateway=gateway,
    )
    check(result)
    found = [item["image_class"] for item in result.payload["attachments"]]
    assert found == list(names.values())
    assert all(item["classifier"] == "metadata" for item in result.payload["attachments"])
    assert gateway.store.list_logs(project_id="img-1")
    assert len(gateway.store.list_logs(project_id="img-1")) == 1


def test_unknown_image_asks_the_gateway(gateway) -> None:
    result = run(
        {
            "project_id": "img-2",
            "payload": {
                "raw_input": "给柱塞泵做产品宣传片",
                "attachments": [{"kind": "image", "uri": f"{ASSETS}/photo.png"}],
            },
        },
        gateway=gateway,
    )
    parsed = result.payload["attachments"][0]
    assert parsed["image_class"] == "product"
    assert parsed["classifier"] == "model"
    assert len(gateway.store.list_logs(project_id="img-2")) == 2


def test_url_brochure_fetches_text_and_images(gateway) -> None:
    with fixture_fetch():
        result = run(
            {
                "project_id": "url-1",
                "payload": {
                    "raw_input": "参考这个网页做外贸英文产品视频，30秒，YouTube",
                    "attachments": [
                        {"kind": "url", "uri": "http://assets.hilatv.test/brochure.html"}
                    ],
                },
            },
            gateway=gateway,
        )
    brief = check(result)
    page = result.payload["attachments"][0]
    assert "高压柱塞泵" in page["text_excerpt"]
    assert [item["image_class"] for item in page["images"]] == ["product", "logo"]
    assert all(item["bytes"] > 0 for item in page["images"])
    assert any("30MPa" in item for item in brief.must_include)


def test_failed_url_still_returns_a_brief(gateway) -> None:
    result = run(
        {
            "project_id": "url-2",
            "payload": {
                "raw_input": "给数控机床做一条产品宣传片",
                "attachments": [{"kind": "url", "uri": "http://127.0.0.1:1/missing"}],
            },
        },
        gateway=gateway,
    )
    brief = check(result)
    assert result.payload["attachments"][0]["error"]
    assert any("附件抓取失败" in item for item in brief.assumptions)
