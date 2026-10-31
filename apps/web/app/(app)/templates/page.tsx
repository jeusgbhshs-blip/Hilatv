import type { Metadata } from "next";

import { TemplatesIndex } from "@/components/templates/templates-index";

export const metadata: Metadata = { title: "模板 · HiLatv" };

export default function TemplatesPage() {
  return <TemplatesIndex />;
}
