import type { Metadata } from "next";

import { InputStudio } from "@/components/input-studio";

export const metadata: Metadata = {
  title: "一句成片 · HiLatv",
  description: "写一句话，附上图片或链接，生成一条可发布的商业短视频",
};

export default function HomePage() {
  return <InputStudio />;
}
