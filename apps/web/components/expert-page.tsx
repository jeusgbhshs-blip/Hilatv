"use client";

import dynamic from "next/dynamic";

const ExpertCanvas = dynamic(
  () => import("@/components/expert-canvas").then((mod) => mod.ExpertCanvas),
  {
    ssr: false,
    loading: () => <p className="text-small text-text-2">正在读取节点</p>,
  },
);

export function ExpertPage({ projectId }: { projectId: string }) {
  return <ExpertCanvas key={projectId} projectId={projectId} />;
}
