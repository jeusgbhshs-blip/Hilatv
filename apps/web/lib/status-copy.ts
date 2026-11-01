/**
 * User-facing stage and status words. DESIGN.md §10.2 is the source; this file
 * is the only place components read them from. No node numbers, model names,
 * prompts or costs here: this copy is for the ordinary user interface.
 */

export const STAGES = ["理解需求", "选方案", "看分镜", "生成中", "成片"] as const;

export type Stage = (typeof STAGES)[number];

/** What the user reads under each stage while it runs (DESIGN.md §10.2). */
export const STAGE_COPY: Record<Stage, readonly string[]> = {
  理解需求: ["正在理解你的需求", "需要确认 2 个问题"],
  选方案: ["正在套用品牌资料", "已准备 3 个方案"],
  看分镜: ["正在写脚本", "正在拆分镜头", "正在配音并确定每镜时长"],
  生成中: [
    "正在准备产品素材",
    "正在画关键帧",
    "正在挑选最佳画面",
    "正在生成视频",
    "正在检查画面",
    "正在配乐和字幕",
    "正在合成",
    "正在终审",
  ],
  成片: ["成片已完成", "正在导出 9:16 版本", "正在按你的意见修改"],
};

export function stageIndex(stage: string | null | undefined): number {
  const index = STAGES.indexOf((stage ?? "") as Stage);
  return index < 0 ? 0 : index;
}

/** "3/5 看分镜" on phone widths (DESIGN.md §8.2). */
export function stageShort(stage: string | null | undefined): string {
  const index = stageIndex(stage);
  return `${index + 1}/${STAGES.length}`;
}

export type Tone = "neutral" | "blue" | "success" | "warning" | "danger";

export type ShotStatus = "queued" | "running" | "done" | "fallback" | "failed";

/** Shot status tags (DESIGN.md §10.2): label and the colour that carries it. */
export const SHOT_STATUS: Record<ShotStatus, { label: string; tone: Tone }> = {
  queued: { label: "排队中", tone: "neutral" },
  running: { label: "生成中", tone: "blue" },
  done: { label: "已完成", tone: "success" },
  fallback: { label: "已用备选方案", tone: "warning" },
  failed: { label: "失败，可重做", tone: "danger" },
};

/** The stage text a shot shows before any event reaches it. */
export const SHOT_WAITING = "即将开始";

/**
 * Pick a shot's tag from the line the backend sent for it and the project status.
 * The backend only sends text per shot, so this reads the words it uses.
 */
export function shotStatus(stage: string, projectStatus?: string | null): ShotStatus {
  const text = stage.trim();
  if (/失败/.test(text)) return "failed";
  if (/备选|降级/.test(text)) return "fallback";
  if (projectStatus === "completed") return "done";
  if (!text || text === SHOT_WAITING || /排队/.test(text)) return "queued";
  if (/完成|已通过|通过质检/.test(text)) return "done";
  return "running";
}

/** Project level words that are not backend messages. */
export const PROJECT_COPY = {
  queued: "正在排队",
  missing: "项目不存在",
  backHome: "返回输入",
  filmNotReady: "成片还没好",
  filmNotReadyHint: "生成结束后再来播放和下载。",
  backToProgress: "返回进度",
  loadingFilm: "正在载入成片",
  reconnecting: "正在重新连接",
  shotsLater: "镜头会在分镜排好后逐条出现在这里。",
} as const;

/** Position in the five-stage journey, not an estimate of generation completion. */
export function stageProgress(stage: string | null | undefined, status?: string | null): number {
  if (status === "draft" || status === "queued" || !status) return 0;
  if (status === "completed") return 1;
  return stageIndex(stage) / STAGES.length;
}

/** A render finishing does not establish quality, provenance, or release approval. */
export function filmConclusion(value: {
  quality_pass?: boolean;
  delivery_status?: string;
  media_provenance?: string;
} | null, version?: { qa_status?: string; quality_pass?: boolean } | null): {
  title: string; detail: string; tone: Tone;
} {
  const source = value?.media_provenance;
  if (source === "mock" || source === "mixed") {
    return { title: "模拟成片，可预览", detail: "这版包含模拟素材，请完成真实生成和审核后再交付。", tone: "warning" };
  }
  if (version && (version.quality_pass !== true || version.qa_status !== "passed")) {
    return { title: "已生成，待核验", detail: "当前导出版本尚未通过完整审核，请先检查画面与声音。", tone: "warning" };
  }
  if (value?.quality_pass === false) {
    return { title: "已生成，待处理", detail: "当前版本尚未通过质检，请查看问题并修改。", tone: "warning" };
  }
  if (value?.delivery_status === "ready" && value.quality_pass === true && source === "live") {
    return { title: "成片已通过审核", detail: "当前版本已完成审核，可以按授权交付。", tone: "success" };
  }
  return { title: "已生成，待核验", detail: "审核或素材来源证据尚不完整，可先预览和继续修改。", tone: "warning" };
}
