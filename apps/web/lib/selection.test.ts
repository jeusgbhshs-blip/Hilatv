import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { chooseCard, type DirectionCard } from "./selection.ts";

const cards: DirectionCard[] = [
  { direction_id: "spec_default", title: "产品宣传主结构", idea: "先谈问题" },
  { direction_id: "factory_tour", title: "工厂实力", idea: "从车间进入" },
  { direction_id: "spec_sheet", title: "参数说明", idea: "用工况数字打开" },
];

describe("concept card choice", () => {
  it("treats an empty choice as 你帮我选", () => {
    const choice = chooseCard(cards, null);
    assert.equal(choice.auto, true);
    assert.equal(choice.id, "你帮我选");
  });

  it("keeps a card the user picked", () => {
    const choice = chooseCard(cards, "factory_tour");
    assert.equal(choice.auto, false);
    assert.equal(choice.label, "工厂实力");
  });

  it("falls back when the id is not on the table", () => {
    const choice = chooseCard(cards, "missing");
    assert.equal(choice.auto, true);
  });
});
