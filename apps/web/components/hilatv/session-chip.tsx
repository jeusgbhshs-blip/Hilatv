"use client";

import { useEffect, useState } from "react";

import { ensureSession } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Points and sign-in in the top bar.
 * There is no balance API. The pill stays at "—" instead of a made-up number.
 * Sign-in uses the existing session endpoint (mock registration when live is off).
 */
export function SessionChip({ className }: { className?: string }) {
  const [signedIn, setSignedIn] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setSignedIn(Boolean(window.localStorage.getItem("hilatv.session")));
  }, []);

  async function signIn() {
    setBusy(true);
    try {
      const token = await ensureSession();
      setSignedIn(Boolean(token));
    } catch {
      setSignedIn(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={cn("flex shrink-0 items-center gap-2", className)}>
      <span
        data-testid="credits-pill"
        className="tabular inline-flex h-8 shrink-0 items-center rounded-full border border-border px-2.5 text-caption whitespace-nowrap text-text-2 md:h-9 md:px-3 md:text-small"
        title="积分余额尚未开通"
      >
        积分 <span className="ml-1 font-medium text-text-1">—</span>
      </span>
      {signedIn ? (
        <span className="inline-flex h-8 items-center rounded-sm border border-border-strong bg-surface px-3 text-caption text-text-1 md:h-9 md:text-small">
          已登录
        </span>
      ) : (
        <button
          type="button"
          className="inline-flex h-11 items-center rounded-sm border border-border-strong bg-surface px-3 text-small text-text-1 hover:bg-hover disabled:text-text-disabled md:h-9"
          onClick={() => void signIn()}
          disabled={busy}
        >
          {busy ? "正在登录" : "登录"}
        </button>
      )}
    </div>
  );
}
