import type { Metadata } from "next";

import { AppearanceSettings } from "@/components/hilatv/appearance-settings";

export const metadata: Metadata = {
  title: "外观 · HiLatv",
  description: "主题：自动、跟随系统、浅色或深色",
};

export default function AppearancePage() {
  return <AppearanceSettings />;
}
