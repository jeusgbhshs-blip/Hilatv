import type { Metadata } from "next";

import { CanvasOpen } from "@/components/canvas/canvas-open";

export const metadata: Metadata = {
  title: "专家画布 · HiLatv",
};

export default function CanvasPage() {
  return <CanvasOpen />;
}
