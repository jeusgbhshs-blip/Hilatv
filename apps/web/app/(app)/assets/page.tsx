import type { Metadata } from "next";

import { BuildingPage } from "@/components/hilatv/building-page";

export const metadata: Metadata = { title: "素材库 · HiLatv" };

export default function AssetsPage() {
  return <BuildingPage title="素材库" note="素材库还在建设。首页仍可上传图片、PDF 和链接，不会使用真实客户图片。" />;
}
