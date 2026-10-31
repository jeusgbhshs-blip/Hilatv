"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { apiFetch, errorMessage } from "@/lib/api";

const LAST_PROJECT_KEY = "hilatv.lastProject";

/** 侧栏「专家画布」：有项目就打开它，没有就开一块空白画布，不跳回首页。 */
export function CanvasOpen() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      const last = window.localStorage.getItem(LAST_PROJECT_KEY);
      if (last) {
        router.replace(`/projects/${last}/expert`);
        return;
      }
      try {
        const response = await apiFetch("/v1/projects/blank", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sentence: "" }),
        });
        if (!response.ok) throw new Error(await errorMessage(response));
        const created = (await response.json()) as { project_id?: string };
        if (!created.project_id) throw new Error("没有拿到项目编号");
        window.localStorage.setItem(LAST_PROJECT_KEY, created.project_id);
        if (!cancelled) router.replace(`/projects/${created.project_id}/expert`);
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "打不开画布");
      }
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <div data-theme="dark" className="flex min-h-dvh items-center justify-center bg-stage text-small text-text-2">
      {error ? <p className="text-danger">{error}</p> : <p>正在打开画布</p>}
    </div>
  );
}
