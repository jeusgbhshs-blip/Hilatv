import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { SHOT_STATUS, shotStatus, stageIndex, stageProgress, STAGES, stageShort } from "./status-copy.ts";

describe("status copy", () => {
  it("has the five DESIGN.md stages in order", () => {
    assert.deepEqual([...STAGES], ["理解需求", "选方案", "看分镜", "生成中", "成片"]);
    assert.equal(stageIndex("看分镜"), 2);
    assert.equal(stageIndex("unknown"), 0);
    assert.equal(stageShort("看分镜"), "3/5");
    assert.equal(stageProgress("成片", "completed"), 1);
  });

  it("maps shot lines to the five tags", () => {
    assert.equal(shotStatus("即将开始"), "queued");
    assert.equal(shotStatus("第 1 镜：正在画关键帧"), "running");
    assert.equal(shotStatus("第 1 镜：已完成"), "done");
    assert.equal(shotStatus("第 2 镜：画面不合格，已用备选方案"), "fallback");
    assert.equal(shotStatus("第 3 镜：生成失败"), "failed");
    assert.equal(shotStatus("第 1 镜：正在合成", "completed"), "done");
  });

  it("never shows node numbers or model names", () => {
    for (const item of Object.values(SHOT_STATUS)) {
      assert.doesNotMatch(item.label, /N\d|n\d\d|seed|gpt|模型/i);
    }
  });
});
