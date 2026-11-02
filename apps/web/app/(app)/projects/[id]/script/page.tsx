import type { Metadata } from "next";

import { StoryboardEditor } from "@/components/script/storyboard-editor";

export const metadata: Metadata = { title: "分镜表 · HiLatv" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <StoryboardEditor projectId={id} />;
}
