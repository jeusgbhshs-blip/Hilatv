/** Labels for an expert-mode candidate. Unreviewed output is never "passed". */

export type Verdict = {
  visual_reviewed: boolean;
  qa_passed: boolean;
  hard_fail: string[];
  total: number | null;
  notes: string;
  blocked: boolean;
};

export type ExpertCandidate = {
  candidate_id: string;
  shot_id: string;
  node: string;
  model: string;
  seed: number | null;
  frame: string | null;
  prompt: string;
  selected: boolean;
  verdict: Verdict;
  media_url: string | null;
  media_note: string;
};

export type ExpertShot = {
  shot_id: string;
  order: number;
  purpose: string;
  keyframes: ExpertCandidate[];
  videos: ExpertCandidate[];
};

export type ExpertNode = {
  id: string;
  label: string;
  completed: boolean;
  generative: boolean;
};

export type ExpertCanvas = {
  project_id: string;
  sentence: string;
  status: string;
  budget: { used: number; limit: number; remaining: number };
  nodes: ExpertNode[];
  edges: { source: string; target: string }[];
  shots: ExpertShot[];
  timeline: {
    present: boolean;
    ai_label: boolean | null;
    duration_s: number | null;
    clips: { clip_id: string; transition_out: string }[];
    overlays: { kind: string; text: string }[];
  };
  master: { ready: boolean; qa_passed: boolean; blocked: boolean; reason: string };
};

export function verdictLabel(verdict: Verdict): string {
  if (verdict.blocked || verdict.hard_fail.includes("sensitive")) return "内容安全硬伤";
  if (verdict.visual_reviewed !== true) return "未评审";
  if (verdict.qa_passed === true) return "质检通过";
  return "未通过";
}

export function candidatesFor(nodeId: string, shot: ExpertShot): ExpertCandidate[] {
  if (nodeId === "n08_keyframe") return shot.keyframes;
  if (nodeId === "n10_video") return shot.videos;
  return [];
}

export function candidateCount(nodeId: string, shots: ExpertShot[]): number {
  return shots.reduce((sum, shot) => sum + candidatesFor(nodeId, shot).length, 0);
}
