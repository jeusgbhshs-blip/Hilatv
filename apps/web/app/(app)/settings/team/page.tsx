import type { Metadata } from "next";

import { TeamSettings } from "@/components/team/team-settings";

export const metadata: Metadata = { title: "团队设置 · HiLatv" };

export default function Page() {
  return <TeamSettings />;
}
