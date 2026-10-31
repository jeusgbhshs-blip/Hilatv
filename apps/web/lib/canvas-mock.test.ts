import { describe, expect, it } from "vitest";

import { finalFrame, productFrame, shotFrame } from "./canvas-frames";
import {
  explainConnection,
  reorderClips,
  shotVerdictFromLegacy,
  shotVerdictLabel,
  trimClip,
  type TimelineClip,
} from "./canvas-contract";
import type { Verdict } from "./expert";
import { CanvasMockStore, CanvasRequestError, seedCanvas, type KeyValueStore } from "./canvas-mock";

const unreviewed: Verdict = {
  visual_reviewed: false,
  qa_passed: true,
  hard_fail: ["not_reviewed"],
  total: 8,
  notes: "",
  blocked: false,
};

function memory(): KeyValueStore {
  const map = new Map<string, string>();
  return {
    getItem: (key) => (map.has(key) ? map.get(key)! : null),
    setItem: (key, value) => map.set(key, value),
    removeItem: (key) => map.delete(key),
  };
}

function decodeFrame(url: string): string {
  const comma = url.indexOf(",");
  return decodeURIComponent(url.slice(comma + 1));
}

describe("verdict", () => {
  it("does not call an unreviewed result a pass", () => {
    expect(shotVerdictFromLegacy(unreviewed)).toBe("unreviewed");
    expect(shotVerdictLabel("unreviewed")).toBe("未评审");
    expect(shotVerdictLabel("unreviewed")).not.toBe("通过");
    expect(shotVerdictLabel("pass")).toBe("通过");
    expect(shotVerdictLabel("hard_fail")).toBe("硬伤");
  });
});

describe("frames", () => {
  it("draws geometry only", () => {
    for (const url of [productFrame(), shotFrame(1), shotFrame(2), shotFrame(3), finalFrame()]) {
      const markup = decodeFrame(url);
      expect(markup).not.toContain("<text");
      expect(markup).not.toContain("gradient");
      expect(markup).not.toContain("补拍");
      expect(markup.toLowerCase()).not.toContain("prompt");
    }
  });
});

describe("connections", () => {
  const nodes = [
    { id: "b", kind: "brief" },
    { id: "r", kind: "ref_image" },
    { id: "s", kind: "shot" },
    { id: "f", kind: "final" },
  ];

  it("allows reference, text, and final edges", () => {
    expect(explainConnection(nodes, [], "r", "s")).toBeNull();
    expect(explainConnection(nodes, [], "b", "s")).toBeNull();
    expect(explainConnection(nodes, [], "s", "f")).toBeNull();
  });

  it("rejects a mismatched pair, a duplicate, and a cycle", () => {
    expect(explainConnection(nodes, [], "b", "f")).toMatch(/只能把参考图或需求文本/);
    expect(explainConnection(nodes, [], "s", "s")).toMatch(/自己/);
    expect(explainConnection(nodes, [{ source: "r", target: "s" }], "r", "s")).toMatch(/已经连过/);
    expect(
      explainConnection(
        nodes,
        [{ source: "s", target: "b" }],
        "b",
        "s",
      ),
    ).toMatch(/绕回/);
  });
});

describe("store", () => {
  it("keeps positions and viewport after a new store reads the same storage", () => {
    const storage = memory();
    const first = new CanvasMockStore(storage, "p1");
    const saved = first.saveLayout({
      layout_version: first.load().layout_version,
      positions: { "shot-2": { x: 640, y: 88 } },
      viewport: { x: 12, y: 4, zoom: 1.1 },
    });
    expect(saved.layout_version).toBe(2);
    const again = new CanvasMockStore(storage, "p1").load();
    expect(again.nodes.find((node) => node.id === "shot-2")?.position).toEqual({ x: 640, y: 88 });
    expect(again.viewport).toEqual({ x: 12, y: 4, zoom: 1.1 });
  });

  it("returns 409 when the layout version is stale", () => {
    const store = new CanvasMockStore(memory(), "p1");
    const version = store.load().layout_version;
    store.saveLayout({
      layout_version: version,
      positions: {},
      viewport: { x: 0, y: 0, zoom: 1 },
    });
    expect(() =>
      store.saveLayout({
        layout_version: version,
        positions: {},
        viewport: { x: 0, y: 0, zoom: 1 },
      }),
    ).toThrow(CanvasRequestError);
    try {
      store.saveLayout({
        layout_version: version,
        positions: {},
        viewport: { x: 0, y: 0, zoom: 1 },
      });
    } catch (error) {
      expect(error).toBeInstanceOf(CanvasRequestError);
      expect((error as CanvasRequestError).status).toBe(409);
    }
  });

  it("connects a product image into shot 2 and reads it on regenerate", () => {
    const store = new CanvasMockStore(memory(), "p1");
    const linked = store.createEdge({ source: "ref-product", target: "shot-2" });
    expect(linked.edges.some((edge) => edge.source === "ref-product" && edge.target === "shot-2" && edge.role === "reference")).toBe(true);
    const regenerated = store.regenerate("shot-2", { narration: "改成单手特写" });
    const shot = regenerated.nodes.find((node) => node.id === "shot-2");
    if (!shot || !("candidates" in shot.data)) throw new Error("missing shot");
    const newest = shot.data.candidates[shot.data.candidates.length - 1];
    expect(newest.verdict).toBe("unreviewed");
    expect(shotVerdictLabel(newest.verdict)).toBe("未评审");
    expect(shot.data.verdict).toBe("unreviewed");
    expect(shot.data.reference_upload_ids).toContain("up-product");
    expect(shot.data.narration).toBe("改成单手特写");
    expect(shot.data.selected_candidate_id).toBe(newest.candidate_id);
    expect(regenerated.budget.used).toBe(2);
  });

  it("selects another candidate without turning an unreviewed score into a pass", () => {
    const store = new CanvasMockStore(memory(), "p1");
    const before = store.load().nodes.find((node) => node.id === "shot-2");
    if (!before || !("verdict" in before.data)) throw new Error("missing shot");
    expect(before.data.verdict).toBe("unreviewed");
    const picked = store.selectCandidate({ shot_id: "shot-2", candidate_id: "shot2-b" });
    const shot = picked.nodes.find((node) => node.id === "shot-2");
    if (!shot || !("verdict" in shot.data)) throw new Error("missing shot");
    expect(shot.data.verdict).toBe("pass");
    expect(shot.data.selected_candidate_id).toBe("shot2-b");
    const clip = picked.timeline.clips.find((item) => item.shot_id === "shot-2");
    expect(clip?.candidate_id).toBe("shot2-b");
  });

  it("refuses to turn the AI label off and keeps in and out inside the shot", () => {
    const store = new CanvasMockStore(memory(), "p1");
    const doc = store.load();
    expect(doc.timeline.ai_label).toBe(true);
    expect(doc.nodes.find((node) => node.kind === "final")?.data).toMatchObject({ ai_label: true });
    expect(() =>
      store.saveTimeline({
        clips: doc.timeline.clips,
        ai_label: false,
      }),
    ).toThrow(/不能关闭/);
    expect(store.load().timeline.ai_label).toBe(true);
    expect(() =>
      store.saveTimeline({
        clips: [{ shot_id: "shot-2", candidate_id: "shot2-a", in_s: 0, out_s: 9 }],
      }),
    ).toThrow(/时长/);
    const trimmed = store.saveTimeline({
      clips: [
        doc.timeline.clips[0],
        { shot_id: "shot-2", candidate_id: "shot2-a", in_s: 0.7, out_s: 6 },
      ],
    });
    expect(trimmed.timeline.clips[1]).toMatchObject({ in_s: 0.7, out_s: 6 });
    expect(trimmed.timeline.ai_label).toBe(true);
  });

  it("deletes only nodes the user created", () => {
    const store = new CanvasMockStore(memory(), "p1");
    expect(() => store.deleteNode("shot-1")).toThrow(/只能删除/);
    const created = store.createNode({ kind: "brief", position: { x: 8, y: 8 }, data: { text: "补充一句" } });
    const added = created.nodes.find((node) => node.user_created);
    expect(added?.kind).toBe("brief");
    const removed = store.deleteNode(added!.id);
    expect(removed.nodes.some((node) => node.id === added!.id)).toBe(false);
  });

  it("rejects an illegal edge from the store", () => {
    const store = new CanvasMockStore(memory(), "p1");
    expect(() => store.createEdge({ source: "brief-1", target: "final-1" })).toThrow(CanvasRequestError);
  });

  it("forces the AI label back on when storage was edited", () => {
    const storage = memory();
    const store = new CanvasMockStore(storage, "p1");
    store.saveLayout({
      layout_version: 1,
      positions: {},
      viewport: store.load().viewport,
    });
    const key = "hilatv.canvas.v0.p1";
    const parsed = JSON.parse(storage.getItem(key)!) as { timeline: { ai_label: boolean } };
    parsed.timeline.ai_label = false;
    storage.setItem(key, JSON.stringify(parsed));
    expect(new CanvasMockStore(storage, "p1").load().timeline.ai_label).toBe(true);
  });
});

describe("timeline math", () => {
  const clips: TimelineClip[] = [
    { shot_id: "shot-1", candidate_id: "a", in_s: 0, out_s: 4 },
    { shot_id: "shot-2", candidate_id: "b", in_s: 0, out_s: 6 },
  ];

  it("reorders and trims inside the shot duration", () => {
    expect(reorderClips(clips, 0, 1).map((clip) => clip.shot_id)).toEqual(["shot-2", "shot-1"]);
    expect(trimClip(clips[1], "in", 0.74, 6).in_s).toBe(0.7);
    expect(trimClip(clips[1], "out", 12, 6).out_s).toBe(6);
    expect(trimClip(clips[1], "in", -2, 6).in_s).toBe(0);
  });
});

describe("seed", () => {
  it("lays out five nodes and does not mark the unreviewed shot as passed", () => {
    const doc = seedCanvas("demo");
    expect(doc.nodes.map((node) => node.kind)).toEqual(["brief", "ref_image", "shot", "shot", "final"]);
    const shot2 = doc.nodes.find((node) => node.id === "shot-2");
    if (!shot2 || !("verdict" in shot2.data)) throw new Error("missing shot");
    expect(shot2.data.verdict).toBe("unreviewed");
    expect(shotVerdictLabel(shot2.data.verdict)).not.toBe("通过");
    expect(JSON.stringify(doc)).not.toContain("补拍");
    expect(doc.edges.some((edge) => edge.source === "ref-product" && edge.target === "shot-2")).toBe(false);
  });
});
