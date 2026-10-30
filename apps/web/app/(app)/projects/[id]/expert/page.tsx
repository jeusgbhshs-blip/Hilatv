import type { Metadata } from "next";

import { ExpertPage } from "@/components/expert-page";

export const metadata: Metadata = {
  title: "专家模式 · HiLatv",
};

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ExpertPage projectId={id} />;
}
