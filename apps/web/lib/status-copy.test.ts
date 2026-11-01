import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { filmConclusion, SHOT_STATUS, shotStatus, stageIndex, stageProgress, STAGES, stageShort } from "./status-copy.ts";

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


describe("truthful film and progress conclusions", () => {
  it("does not invent running progress for drafts or missing state", () => {
    assert.equal(stageProgress("理解需求", "draft"), 0);
    assert.equal(stageProgress("理解需求", "queued"), 0);
    assert.equal(stageProgress("生成中", undefined), 0);
  });
  it("requires review and provenance evidence before claiming release readiness", () => {
    assert.equal(filmConclusion(null).title, "已生成，待核验");
    assert.equal(filmConclusion({ quality_pass: true }).tone, "warning");
    assert.equal(filmConclusion({ quality_pass: false }).title, "已生成，待处理");
    for (const media_provenance of ["mock", "mixed"]) {
      assert.equal(filmConclusion({ media_provenance, quality_pass: true, delivery_status: "ready" }).title, "模拟成片，可预览");
    }
    assert.equal(filmConclusion({ quality_pass: true, delivery_status: "ready", media_provenance: "live" }).tone, "success");
    assert.equal(filmConclusion({ quality_pass: true, delivery_status: "ready", media_provenance: "live" }, { qa_status: "needs_review" }).tone, "warning");
  });
});


describe("selected file readiness", () => {
  const released = { quality_pass: true, delivery_status: "ready", media_provenance: "live" };
  it("never inherits the master approval or provenance for another export", () => {
    assert.equal(filmConclusion(released, { quality_pass: true, qa_status: "passed" }).tone, "warning");
    assert.equal(filmConclusion(released, { ...released, qa_status: "passed", media_provenance: "mock" }).title, "模拟成片，可预览");
    assert.equal(filmConclusion(released, { ...released, qa_status: "passed", delivery_status: "needs_verification" }).tone, "warning");
    assert.equal(filmConclusion({ media_provenance: "mock" }, { ...released, qa_status: "passed" }).tone, "success");
    assert.equal(filmConclusion(released, { ...released, qa_status: "needs_review" }).tone, "success");
  });
});
