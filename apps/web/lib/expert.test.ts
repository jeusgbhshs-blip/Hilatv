import assert from "node:assert/strict";
import test from "node:test";

import { candidateCount, verdictLabel, type ExpertShot, type Verdict } from "./expert.ts";

const unreviewed: Verdict = {
  visual_reviewed: false,
  qa_passed: false,
  hard_fail: ["not_reviewed"],
  total: null,
  notes: "not_reviewed",
  blocked: false,
};

test("an unreviewed score is not labeled as a pass", () => {
  assert.equal(verdictLabel(unreviewed), "未评审");
  assert.equal(
    verdictLabel({ ...unreviewed, qa_passed: true, total: 8 }),
    "未评审",
  );
});

test("a content-safety fail is named, and a real pass is named", () => {
  assert.equal(
    verdictLabel({
      visual_reviewed: true,
      qa_passed: false,
      hard_fail: ["sensitive"],
      total: 1,
      notes: "",
      blocked: true,
    }),
    "内容安全硬伤",
  );
  assert.equal(
    verdictLabel({
      visual_reviewed: true,
      qa_passed: true,
      hard_fail: [],
      total: 8.5,
      notes: "",
      blocked: false,
    }),
    "质检通过",
  );
});

test("candidate counts stay on the node that produced them", () => {
  const shots: ExpertShot[] = [
    {
      shot_id: "S01",
      order: 1,
      purpose: "",
      keyframes: [
        {
          candidate_id: "a",
          shot_id: "S01",
          node: "N8",
          model: "mock",
          seed: 1,
          frame: "first",
          prompt: "",
          selected: true,
          verdict: unreviewed,
          media_url: null,
          media_note: "",
        },
      ],
      videos: [],
    },
  ];
  assert.equal(candidateCount("n08_keyframe", shots), 1);
  assert.equal(candidateCount("n10_video", shots), 0);
});
