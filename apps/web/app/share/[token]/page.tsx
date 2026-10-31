import type { Metadata } from "next";

import { ShareView } from "@/components/share/share-view";

export const metadata: Metadata = { title: "只读分享 · HiLatv" };

export default async function SharePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <ShareView token={token} />;
}
