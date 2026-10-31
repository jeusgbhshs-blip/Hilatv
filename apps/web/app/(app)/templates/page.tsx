import type { Metadata } from "next";

import { BuildingPage } from "@/components/hilatv/building-page";

export const metadata: Metadata = { title: "模板 · HiLatv" };

export default function TemplatesPage() {
  return <BuildingPage title="模板" note="模板还在建设。首页的行业入口会先填入对应的预设句，可以再改。" />;
}
