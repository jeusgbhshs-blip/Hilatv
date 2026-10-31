import type { Metadata } from "next";

import { AcademyIndex } from "@/components/learning/academy-index";

export const metadata: Metadata = { title: "学院 · HiLatv" };

export default function AcademyPage() {
  return <AcademyIndex />;
}
