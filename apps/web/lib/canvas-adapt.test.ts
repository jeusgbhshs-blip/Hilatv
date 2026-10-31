import { describe, expect, it } from "vitest";

import { normalizeContractCanvas } from "./canvas-adapt";

/** R2 的 GET /canvas：节点带 kind/position，timeline 同时放老字段和结构化 edit。 */
function serverCanvas(edit: unknown, present = true) {
  return {
    project_id: "p1",
    sentence: "一句话",
    status: "completed",
    budget: { used: 0, limit: 0, remaining: 0 },
    layout_version: 4,
    viewport: { x: 0, y: 0, zoom: 1 },
    nodes: [
      {
        id: "shot:S01",
        kind: "shot",
        position: { x: 460, y: 0 },
        data: {
          shot_id: "S01",
          index: 1,
          duration_s: 4.2,
          verdict: "unreviewed",
          regen_count: 0,
          candidates: [{ candidate_id: "k1", kind: "keyframe", model: "m", verdict: "unreviewed" }],
          selected_candidate_id: "k1",
          narration: "旁白",
        },
      },
      {
        id: "shot:S02",
        kind: "shot",
        position: { x: 460, y: 180 },
        data: {
          shot_id: "S02",
          index: 2,
          duration_s: 0,
          verdict: "pass",
          regen_count: 1,
          candidates: [],
          narration: "",
        },
      },
    ],
    edges: [],
    timeline: {
      present,
      ai_label: true,
      duration_s: 18.4,
      clips: [{ clip_id: "S01", transition_out: "cut" }],
      overlays: [{ kind: "ai_label", text: "AI生成" }],
      edit: edit,
    },
  };
}

describe("normalizeContractCanvas", () => {
  it("没有结构化入点时按镜头时长补 0–时长，不会把老 clip_id 当成入出点", () => {
    const snapshot = normalizeContractCanvas(serverCanvas(null));
    if (!snapshot) throw new Error("should accept the R2 canvas");
    expect(snapshot.timeline.clips.map((clip) => clip.shot_id)).toEqual(["S01", "S02"]);
    expect(snapshot.timeline.clips[0]).toMatchObject({ in_s: 0, out_s: 4.2, candidate_id: "k1" });
    // 时长拿不到时给一个可用值，界面不会因为 undefined.toFixed 崩掉
    expect(snapshot.timeline.clips[1]?.out_s).toBe(4);
    expect(snapshot.timeline.ai_label).toBe(true);
    expect(snapshot.server_timeline?.overlays[0]?.text).toBe("AI生成");
    expect(snapshot.timeline.clips.every((clip) => Number.isFinite(clip.in_s) && Number.isFinite(clip.out_s))).toBe(true);
  });

  it("有结构化入点时用 edit，忽略老接口的 clip_id", () => {
    const snapshot = normalizeContractCanvas(
      serverCanvas({ ai_label: true, clips: [{ shot_id: "S01", candidate_id: "k1", in_s: 0.5, out_s: 3 }] }),
    );
    if (!snapshot) throw new Error("should accept the R2 canvas");
    expect(snapshot.timeline.clips).toEqual([{ shot_id: "S01", candidate_id: "k1", in_s: 0.5, out_s: 3 }]);
    expect(snapshot.timeline.duration_s).toBeCloseTo(2.5, 5);
  });

  it("rejects something that is not a contract canvas", () => {
    expect(normalizeContractCanvas({ nodes: [], shots: [] })).toBeNull();
  });
});
