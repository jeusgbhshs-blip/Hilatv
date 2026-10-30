import type { Metadata } from "next";

import { ProgressBoard } from "@/components/progress-board";

export const metadata: Metadata = {
  title: "生成进度 · HiLatv",
};

export default async function ProgressPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ProgressBoard projectId={id} />;
}
