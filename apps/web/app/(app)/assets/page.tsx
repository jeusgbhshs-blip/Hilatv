import type { Metadata } from "next";

import { AssetsLibrary } from "@/components/assets/assets-library";

export const metadata: Metadata = { title: "素材库 · HiLatv" };

export default function AssetsPage() {
  return <AssetsLibrary />;
}
