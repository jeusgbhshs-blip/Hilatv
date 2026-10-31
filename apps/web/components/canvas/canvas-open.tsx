"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

const LAST_PROJECT_KEY = "hilatv.lastProject";

/**
 * 侧栏「专家画布」入口：画布跟着项目走。
 * 有当前项目就打开它，没有就回项目列表挑一个（不在这里凭空新建项目）。
 */
export function CanvasOpen() {
  const router = useRouter();

  useEffect(() => {
    const last = window.localStorage.getItem(LAST_PROJECT_KEY);
    router.replace(last ? `/projects/${last}/expert` : "/projects");
  }, [router]);

  return (
    <div data-theme="dark" className="flex min-h-dvh items-center justify-center bg-stage text-small text-text-2">
      <p>正在打开画布</p>
    </div>
  );
}
