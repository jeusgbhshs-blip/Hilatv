import { describe, expect, it } from "vitest";

import { FLOW_STEPS, HOME_ENTRIES, TYPEWRITER_LINES, sentenceFor } from "./home-entries";

describe("home entries", () => {
  it("lists the seven approved presets in order", () => {
    expect(HOME_ENTRIES.map((item) => item.label)).toEqual([
      "电商带货",
      "房产案场",
      "餐饮探店",
      "美妆种草",
      "图生视频",
      "智能剪辑",
      "专家画布",
    ]);
    expect(new Set(HOME_ENTRIES.map((item) => item.id)).size).toBe(7);
  });

  it("gives every entry a sentence and keeps 专家画布 on the expert page", () => {
    for (const item of HOME_ENTRIES) {
      expect(item.sentence.trim().length).toBeGreaterThan(0);
      expect(item.hint.trim().length).toBeGreaterThan(0);
    }
    expect(HOME_ENTRIES.filter((item) => item.destination === "expert").map((item) => item.id)).toEqual([
      "expert",
    ]);
    expect(HOME_ENTRIES.filter((item) => item.destination === "compose")).toHaveLength(6);
  });

  it("fills a compose preset as-is and keeps a typed sentence for expert", () => {
    const commerce = HOME_ENTRIES[0];
    const expert = HOME_ENTRIES[6];
    expect(sentenceFor(commerce, "已经写好的一句")).toBe(commerce.sentence);
    expect(sentenceFor(expert, "  已经写好的一句  ")).toBe("已经写好的一句");
    expect(sentenceFor(expert, "   ")).toBe(expert.sentence);
  });

  it("does not use the word 补拍 in home copy", () => {
    const blob = JSON.stringify({ HOME_ENTRIES, FLOW_STEPS, TYPEWRITER_LINES });
    expect(blob).not.toContain("补拍");
    expect(TYPEWRITER_LINES.length).toBeGreaterThan(1);
    expect(FLOW_STEPS.map((step) => step.title)).toEqual(["一句话", "分镜", "成片"]);
  });
});
