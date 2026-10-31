import type { Metadata } from "next";

import { ProjectsIndex } from "@/components/projects/projects-index";

export const metadata: Metadata = { title: "项目 · HiLatv" };

export default function ProjectsPage() {
  return <ProjectsIndex />;
}
