"use client";

import { CanvasStage } from "@/components/canvas/canvas-stage";

/** 专家模式整页画布。页面仍从这里进入，避免改路由。 */
export function ExpertCanvas({ projectId }: { projectId: string }) {
  return <CanvasStage projectId={projectId} />;
}
