import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  attachmentLabel,
  latestMessage,
  latestPhase,
  mergeEvents,
  projectStatus,
  readShots,
  shotViews,
} from "./progress.ts";

describe("shot progress", () => {
  it("keeps the latest stage for every shot and the storyboard purpose", () => {
    const shots = readShots([
      { shot_id: "b", order: 2, purpose: "工厂" },
      { shot_id: "a", order: 1, purpose: "产品特写" },
      { order: 0, purpose: "丢掉" },
    ]);
    const events = mergeEvents(
      [],
      [
        { message: "正在理解需求", phase: "理解需求", status: "running", ts: 1 },
        { message: "第 2 镜：正在配音", phase: "生成中", shot_index: 2, shot_id: "b", ts: 2 },
        { message: "第 1 镜：正在配音", phase: "生成中", shot_index: 1, shot_id: "a", ts: 3 },
        { message: "第 1 镜：正在生成画面", phase: "生成中", shot_index: 1, shot_id: "a", ts: 4 },
      ],
    );
    const rows = shotViews(shots, events);
    assert.deepEqual(
      rows.map((row) => [row.order, row.purpose, row.stage]),
      [
        [1, "产品特写", "第 1 镜：正在生成画面"],
        [2, "工厂", "第 2 镜：正在配音"],
      ],
    );
    assert.equal(latestPhase(events), "生成中");
    assert.equal(latestMessage(events, "正在排队"), "第 1 镜：正在生成画面");
  });

  it("builds rows from events before the snapshot lists shots", () => {
    const rows = shotViews([], [{ message: "第 3 镜：正在生成画面", shot_index: 3, ts: 1 }]);
    assert.equal(rows.length, 1);
    assert.equal(rows[0]?.stage, "第 3 镜：正在生成画面");
    assert.equal(rows[0]?.order, 3);
  });

  it("dedupes a replay and lets the terminal status win", () => {
    const once = { message: "成片已就绪", phase: "成片", status: "completed", ts: 9 };
    const merged = mergeEvents([once], [once, { type: "error", message: "项目不存在" }]);
    assert.equal(merged.length, 1);
    assert.equal(projectStatus("running", merged), "completed");
    assert.equal(latestPhase(merged), "成片");
  });

  it("labels a link by its address and a picture by its file name", () => {
    assert.equal(
      attachmentLabel({ kind: "url", uri: "https://example.com/a", filename: "" }),
      "https://example.com/a",
    );
    assert.equal(
      attachmentLabel({ kind: "image", uri: "/tmp/a.png", filename: "产品图.png" }),
      "产品图.png",
    );
    assert.equal(attachmentLabel({ kind: "image", uri: "/etc/passwd", filename: "" }), "图片");
    assert.equal(attachmentLabel({ kind: "image", uri: "/tmp/product.png", filename: "/tmp/product.png" }), "图片");
    assert.equal(attachmentLabel({ kind: "url", uri: "/etc/passwd", filename: "" }), "链接");
    assert.equal(attachmentLabel({ kind: "pdf", uri: "/tmp/a.pdf", filename: "a.pdf" }), "a.pdf");
  });
});
