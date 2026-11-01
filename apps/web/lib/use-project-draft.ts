"use client";

import { useCallback, useEffect, useRef, useState, type SetStateAction } from "react";

import {
  draftFingerprint, draftScope, loadServerDraft, newDraft, readLocalDraft,
  syncServerDraft, writeLocalDraft, type ProjectDraft,
} from "./project-draft";

export function useProjectDraft(initialSentence = "", projectId?: string) {
  const [draft, render] = useState<ProjectDraft>(() => newDraft(initialSentence));
  const current = useRef(draft);
  const scope = useRef("");
  const writes = useRef<Promise<void>>(Promise.resolve());
  const flight = useRef<Promise<ProjectDraft> | null>(null);
  const mounted = useRef(true);
  const blocked = useRef<string | null>(null);
  const [ready, setReady] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const persist = useCallback((value: ProjectDraft) => {
    const key = scope.current;
    if (!key) return Promise.resolve();
    const next = writes.current.catch(() => undefined).then(() => writeLocalDraft(key, value));
    writes.current = next;
    return next;
  }, []);

  const update = useCallback((patch: Partial<ProjectDraft>) => {
    const next = { ...current.current, ...patch };
    current.current = next;
    render(next);
    void persist(next).catch((caught: unknown) => {
      if (mounted.current) setError(caught instanceof Error ? caught.message : "本地草稿未保存");
    });
  }, [persist]);

  const field = useCallback(<K extends keyof ProjectDraft>(key: K, value: SetStateAction<ProjectDraft[K]>) => {
    update({ [key]: typeof value === "function" ? (value as (old: ProjectDraft[K]) => ProjectDraft[K])(current.current[key]) : value });
  }, [update]);

  useEffect(() => {
    let cancelled = false;
    mounted.current = true;
    void (async () => {
      try {
        const key = await draftScope();
        const local = await readLocalDraft(key, projectId);
        const restored = local || (projectId ? await loadServerDraft(projectId) : newDraft(initialSentence));
        if (cancelled) return;
        scope.current = key;
        current.current = restored;
        render(restored);
      } catch (caught) {
        if (projectId) blocked.current = caught instanceof Error ? caught.message : "项目读取失败";
        if (!cancelled) setError(caught instanceof Error ? caught.message : "恢复草稿失败");
      } finally { if (!cancelled) setReady(true); }
    })();
    return () => { cancelled = true; mounted.current = false; };
  }, [initialSentence, projectId]);

  const flush = useCallback((): Promise<ProjectDraft> => {
    if (flight.current) return flight.current;
    const run = (async () => {
      if (blocked.current) throw new Error(blocked.current);
      if (!scope.current) scope.current = await draftScope();
      if (mounted.current) { setSaving(true); setError(null); }
      try {
        // Merge only acknowledgements, never old text, if the user kept typing during an upload.
        async function acknowledge(saved: ProjectDraft) {
          const latest = current.current;
          const byId = new Map(saved.files.map((item) => [item.id, item.uploaded]));
          const merged = {
            ...latest, project_id: saved.project_id || latest.project_id,
            draft_revision: saved.draft_revision ?? latest.draft_revision,
            create_snapshot: saved.create_snapshot || latest.create_snapshot,
            files: latest.files.map((item) => ({ ...item, uploaded: byId.get(item.id) || item.uploaded })),
            synced_fingerprint: saved.synced_fingerprint || latest.synced_fingerprint,
          };
          current.current = merged;
          if (mounted.current) render(merged);
          await persist(merged);
        }
        while (!current.current.started && (!current.current.project_id || draftFingerprint(current.current) !== current.current.synced_fingerprint)) {
          const saved = await syncServerDraft(current.current, acknowledge);
          await acknowledge(saved);
        }
        await writes.current;
        return current.current;
      } catch (caught) {
        if (mounted.current) setError(caught instanceof Error ? caught.message : "草稿未同步，请重试");
        throw caught;
      } finally {
        flight.current = null;
        if (mounted.current) setSaving(false);
      }
    })();
    flight.current = run;
    return run;
  }, [persist]);

  const dirty = Boolean(draft.project_id || draft.sentence.trim() || draft.files.length || draft.links.length) && draftFingerprint(draft) !== draft.synced_fingerprint;
  useEffect(() => {
    if (!ready || !dirty || draft.started || (!draft.project_id && !draft.sentence.trim() && draft.files.length === 0 && draft.links.length === 0)) return;
    const timer = window.setTimeout(() => void flush().catch(() => undefined), 350);
    return () => window.clearTimeout(timer);
  }, [draft, dirty, ready, flush]);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      const latest = current.current;
      if (latest.started || (!latest.project_id && !latest.sentence.trim() && !latest.files.length && !latest.links.length) || draftFingerprint(latest) === latest.synced_fingerprint) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);

  return { draft, ready: ready && !blocked.current, saving, error, dirty, update, field, flush, persist };
}
