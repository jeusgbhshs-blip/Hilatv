import type { Metadata } from "next";

import { BrandDesk } from "@/components/brand-desk";

export const metadata: Metadata = {
  title: "品牌资料 · HiLatv",
  description: "一次录入企业 Logo、色彩、卖点和肖像授权，之后的片子自动套用",
};

export default function BrandPage() {
  return <BrandDesk />;
}
