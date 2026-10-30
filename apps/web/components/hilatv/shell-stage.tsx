"use client";

import { createContext, useContext, useEffect, useState } from "react";

/** The stage a project page reports to the top bar's StageStepper. */
export type ShellStage = { stage: string; complete?: boolean } | null;

type ShellStageState = {
  current: ShellStage;
  set: (value: ShellStage) => void;
};

const ShellStageContext = createContext<ShellStageState>({ current: null, set: () => {} });

export function ShellStageProvider({ children }: { children: React.ReactNode }) {
  const [current, set] = useState<ShellStage>(null);
  return <ShellStageContext.Provider value={{ current, set }}>{children}</ShellStageContext.Provider>;
}

export function useShellStageValue(): ShellStage {
  return useContext(ShellStageContext).current;
}

/** Show `stage` in the top bar while this page is on screen. */
export function useShellStage(stage: string | null, complete = false) {
  const { set } = useContext(ShellStageContext);
  useEffect(() => {
    set(stage ? { stage, complete } : null);
  }, [set, stage, complete]);
  useEffect(() => () => set(null), [set]);
}
