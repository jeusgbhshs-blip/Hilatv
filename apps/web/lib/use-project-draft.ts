"use client";

import { useEffect, useRef, useSyncExternalStore, type SetStateAction } from "react";

import { ProjectDraftSession, type ProjectDraft } from "./project-draft";

export function useProjectDraft(initialSentence = "", projectId?: string) {
  const route = useRef<{ sentence: string; projectId?: string; session: ProjectDraftSession } | null>(null);
  if (!route.current || route.current.sentence !== initialSentence || route.current.projectId !== projectId) {
    // Invalidate in the props-changing render, before an old promise can ACK.
    route.current?.session.invalidate();
    route.current = { sentence: initialSentence, projectId, session: new ProjectDraftSession(initialSentence, projectId) };
  }
  const session = route.current.session;
  const state = useSyncExternalStore(session.subscribe, session.snapshot, session.snapshot);

  useEffect(() => {
    void session.restore();
    return () => session.close();
  }, [session]);

  useEffect(() => {
    if (!state.ready || state.conflict || state.resolving || state.draft.started || state.draft.submission_pending || !session.dirty) return;
    const ticket = session.ticket();
    const timer = window.setTimeout(() => { if (ticket()) void session.flush().catch(() => undefined); }, 350);
    return () => window.clearTimeout(timer);
  }, [session, state.draft, state.ready, state.conflict, state.resolving]);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (!session.isCurrent() || session.snapshot().draft.started || (!session.dirty && !session.snapshot().resolving)) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [session]);

  function field<K extends keyof ProjectDraft>(key: K, value: SetStateAction<ProjectDraft[K]>) {
    const current = session.snapshot().draft[key];
    session.update({ [key]: typeof value === "function" ? (value as (old: ProjectDraft[K]) => ProjectDraft[K])(current) : value });
  }

  return { ...state, identity: session.id, dirty: session.dirty, editable: session.editable,
    update: session.update, field, flush: session.flush, persist: session.persist,
    ticket: session.ticket, isCurrent: session.isCurrent, retryRestore: () => session.restore(),
    inspectServer: session.inspectServer, resolveConflict: session.resolveConflict,
    restoreBackup: session.restoreBackup, stageSubmission: session.stageSubmission,
    confirmSubmission: session.confirmSubmission };
}
