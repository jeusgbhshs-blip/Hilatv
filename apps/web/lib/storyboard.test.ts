import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { cardMedia, readCards } from "./storyboard.ts";

describe("storyboard cards", () => {
  it("does not treat a mock or a forced review flag as a preview", () => {
    const cards = readCards([
      {
        shot_id: "S01",
        order: 1,
        duration_s: 2,
        purpose: "钩子",
        voiceover: "先看这台泵",
        preview_status: "unavailable",
        visual_reviewed: true,
        preview_note: "未测",
        frame_url: "/v1/projects/p/storyboard/S01/frame",
      },
      {
        shot_id: "S02",
        order: 2,
        duration_s: 3,
        voiceover: "请来厂",
        preview_status: "ready",
        visual_reviewed: false,
        frame_url: "/v1/projects/p/storyboard/S02/frame",
      },
    ]);
    assert.equal(cards[0]?.preview_status, "unavailable");
    assert.equal(cards[0]?.visual_reviewed, false);
    assert.equal(cards[0]?.frame_url, null);
    assert.equal(cardMedia(cards[0]!).showImage, false);
    assert.equal(cardMedia(cards[0]!).note, "这一镜还没有可看的画面");
    assert.equal(cardMedia(cards[1]!).showImage, true);
    assert.equal(cardMedia(cards[1]!).reviewed, false);
    assert.equal(cardMedia(cards[1]!).note, "未评审");
  });
});
