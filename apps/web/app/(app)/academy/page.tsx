import type { Metadata } from "next";

import { BuildingPage } from "@/components/hilatv/building-page";

export const metadata: Metadata = { title: "学院 · HiLatv" };

export default function AcademyPage() {
  return <BuildingPage title="学院" note="学院还在建设。这里以后放教程，现在没有课程。" />;
}
