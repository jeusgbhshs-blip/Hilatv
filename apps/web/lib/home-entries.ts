/**
 * Homepage industry entries from the approved home motion (2026-10-31).
 * Sentences are starting points the user can edit. They are not submitted
 * until the user presses 生成, except 专家画布, which opens that project's
 * expert page.
 *
 * The six brand-kit industries stay in industries.ts. This list does not
 * replace them.
 */

export type HomeDestination = "compose" | "expert";

export type HomeEntry = {
  id: string;
  label: string;
  /** One line under the name (DESIGN.md §9.2). */
  hint: string;
  sentence: string;
  destination: HomeDestination;
};

export const HOME_ENTRIES: HomeEntry[] = [
  {
    id: "commerce",
    label: "电商带货",
    hint: "卖点口播，字幕后期加",
    sentence: "给这款商品做一条 30 秒带货短视频，口播卖点，价格用后期字幕",
    destination: "compose",
  },
  {
    id: "property",
    label: "房产案场",
    hint: "样板间，傍晚光线",
    sentence: "黑石公寓的奢华样板间，傍晚光线",
    destination: "compose",
  },
  {
    id: "dining",
    label: "餐饮探店",
    hint: "门店与菜品",
    sentence: "重庆火锅沸腾特写，门店探店 30 秒",
    destination: "compose",
  },
  {
    id: "beauty",
    label: "美妆种草",
    hint: "质感特写，画面不写字",
    sentence: "一瓶香水的高级感广告，夜色，丝绒质感",
    destination: "compose",
  },
  {
    id: "image-video",
    label: "图生视频",
    hint: "先上传产品图",
    sentence: "根据上传的产品图生成 30 秒展示视频，镜头缓慢推进，画面不要文字",
    destination: "compose",
  },
  {
    id: "edit",
    label: "智能剪辑",
    hint: "上传素材后生成",
    sentence: "把上传的图片和资料剪成一条 30 秒成片，配上口播",
    destination: "compose",
  },
  {
    id: "expert",
    label: "专家画布",
    hint: "进入项目的专家页",
    sentence: "逐镜查看候选、时长和评分，在专家画布里调整",
    destination: "expert",
  },
];

/** Placeholder lines. The caret walks through them until the user types. */
export const TYPEWRITER_LINES = [
  "黑石公寓的奢华样板间，傍晚光线",
  "一瓶香水的高级感广告",
  "重庆火锅沸腾特写",
  "新款跑鞋城市夜跑，慢镜头",
] as const;

export const FLOW_STEPS = [
  {
    title: "一句话",
    body: "“一瓶香水的高级感广告，夜色，丝绒质感”",
    note: "理解需求 · 生成脚本",
    kind: "sentence" as const,
  },
  {
    title: "分镜",
    body: "",
    note: "6 个镜头 · 评分 92",
    kind: "board" as const,
  },
  {
    title: "成片",
    body: "",
    note: "30 秒 · 1080p · 已配音",
    kind: "film" as const,
  },
];

/** Expert uses the typed sentence when there is one, otherwise its preset. */
export function sentenceFor(entry: HomeEntry, typed: string): string {
  const text = typed.trim();
  if (entry.destination === "expert") return text || entry.sentence;
  return entry.sentence;
}

export function homeEntry(id: string): HomeEntry | undefined {
  return HOME_ENTRIES.find((item) => item.id === id);
}
