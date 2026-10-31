"use client";

import { usePathname } from "next/navigation";

import { AppShell } from "@/components/hilatv/app-shell";

/** 专家画布是独立工作台（LibTV 式无限画布），不套应用侧栏。 */
export function ShellGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (pathname && /^\/projects\/[^/]+\/expert\/?$/.test(pathname)) {
    return <>{children}</>;
  }
  return <AppShell>{children}</AppShell>;
}
