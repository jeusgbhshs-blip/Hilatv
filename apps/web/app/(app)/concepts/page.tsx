import type { Metadata } from "next";

import { ConceptBoard } from "@/components/concept-board";

export const metadata: Metadata = {
  title: "方案卡 · HiLatv",
  description: "三个不同的创意方向，选一张，或让系统选",
};

export default async function ConceptsPage({
  searchParams,
}: {
  searchParams: Promise<{ sentence?: string; project?: string }>;
}) {
  const params = await searchParams;
  const sentence = typeof params.sentence === "string" ? params.sentence : "";
  return <ConceptBoard initialSentence={sentence} initialProjectId={typeof params.project === "string" ? params.project : undefined} />;
}
