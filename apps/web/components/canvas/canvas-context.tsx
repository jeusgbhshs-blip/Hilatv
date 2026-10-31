"use client";

import { createContext, useContext } from "react";

import type { CanvasSnapshot, RegenerateWrite } from "@/lib/canvas-contract";

export type CanvasActions = {
  doc: CanvasSnapshot;
  choosingId: string | null;
  setChoosing: (id: string | null) => void;
  regenerate: (shotId: string, copy?: RegenerateWrite) => void;
  editWords: (shotId: string) => void;
  choose: (shotId: string, candidateId: string) => void;
  uploadReference: (shotId: string, file: File) => void;
  showPrompt: (shotId: string) => void;
  changeBrief: (nodeId: string, text: string) => void;
  uploadRefNode: (nodeId: string, file: File) => void;
  derive: (nodeId: string, kind: "brief" | "ref_image") => void;
};

const CanvasActionsContext = createContext<CanvasActions | null>(null);

export function CanvasActionsProvider({
  value,
  children,
}: {
  value: CanvasActions;
  children: React.ReactNode;
}) {
  return <CanvasActionsContext.Provider value={value}>{children}</CanvasActionsContext.Provider>;
}

export function useCanvasActions(): CanvasActions {
  const value = useContext(CanvasActionsContext);
  if (!value) throw new Error("画布节点渲染在画布之外");
  return value;
}
