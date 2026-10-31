import type { Metadata } from "next";

import { BuildingPage } from "@/components/hilatv/building-page";

export const metadata: Metadata = { title: "项目 · HiLatv" };

export default function ProjectsPage() {
  return (
    <BuildingPage
      title="项目"
      note="项目列表还在建设。从首页生成后会进入该项目的进度页，可再打开成片或专家画布。"
    />
  );
}
