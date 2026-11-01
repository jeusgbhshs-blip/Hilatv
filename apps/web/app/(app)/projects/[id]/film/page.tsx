import type { Metadata } from "next";

import { FilmStage } from "@/components/film-stage";

export const metadata: Metadata = {
  title: "成片 · HiLatv",
};

export default async function FilmPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <FilmStage key={id} projectId={id} />;
}
