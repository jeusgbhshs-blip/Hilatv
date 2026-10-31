import type { Metadata } from "next";

import { UsagePage } from "@/components/usage/usage-page";

export const metadata: Metadata = { title: "用量与账单 · HiLatv" };

export default function Page() {
  return <UsagePage />;
}
