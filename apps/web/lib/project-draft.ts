import { apiFetch, ensureSession, errorMessage } from "./api";
import type { DirectionCard } from "./selection";
import { conceptInputKey, generationSettings, settingsKey, type GenerationSettings } from "./generation-settings";

export type UploadedDraftFile = { kind: string; upload_id: string; filename: string };
export type DraftFile = { id: string; file: File; preview: string | null; uploaded?: UploadedDraftFile };
export type DraftLink = { id: string; uri: string };
export type ProjectDraft = {
  operation_id: string;
  project_id?: string;
  draft_revision?: number;
  sentence: string;
  files: DraftFile[];
  links: DraftLink[];
  skip_storyboard: boolean;
  concept_selection: string | null;
  generation_settings: GenerationSettings;
  cards?: DirectionCard[];
  cards_sentence?: string;
  cards_input_key?: string;
  brand_applied?: boolean;
  start_operation_id?: string;
  create_snapshot?: {
    sentence: string;
    attachments: (UploadedDraftFile | { kind: string; uri: string })[];
    skip_storyboard: boolean;
    concept_selection: string | null;
    generation_settings: GenerationSettings;
  };
  started?: boolean;
  submission_pending?: boolean;
  server_status?: string;
  synced_fingerprint?: string;
};

export type DraftBackup = { id: string; created_at: number; reason: string; draft: ProjectDraft };

export class DraftConflictError extends Error {
  constructor(message: string, readonly server: ProjectDraft) { super(message); }
}

export class StaleDraftSessionError extends Error {
  constructor() { super("已切换项目，旧操作已停止更新当前页面"); }
}

export function newDraft(sentence = ""): ProjectDraft {
  return { operation_id: crypto.randomUUID(), sentence, files: [], links: [], skip_storyboard: false, concept_selection: null, generation_settings: generationSettings() };
}

/** No file bytes or credentials enter a URL or JSON transport. File bytes live in IndexedDB. */
export function draftFingerprint(draft: ProjectDraft): string {
  return JSON.stringify({
    sentence: draft.sentence,
    files: draft.files.map((item) => [item.id, item.file.name, item.file.size, item.uploaded?.upload_id]),
    links: draft.links.map((item) => item.uri),
    skip_storyboard: draft.skip_storyboard,
    concept_selection: draft.concept_selection,
    generation_settings: generationSettings(draft.generation_settings),
  });
}

/** Migrate pre-settings local records without making an already saved draft dirty. */
function restoredDraft(draft: ProjectDraft): ProjectDraft {
  const migrated = { ...draft, generation_settings: generationSettings(draft.generation_settings) };
  if (!draft.generation_settings && draft.synced_fingerprint) {
    const legacy = JSON.parse(draftFingerprint(migrated)) as Record<string, unknown>;
    delete legacy.generation_settings;
    if (draft.synced_fingerprint === JSON.stringify(legacy)) migrated.synced_fingerprint = draftFingerprint(migrated);
  }
  return migrated;
}

export function currentConceptCards(draft: ProjectDraft): DirectionCard[] {
  const valid = draft.cards_input_key
    ? draft.cards_input_key === conceptInputKey(draft.sentence, draft.generation_settings)
    : draft.cards_sentence === draft.sentence.trim() && settingsKey(draft.generation_settings) === settingsKey();
  return valid ? draft.cards || [] : [];
}

export function isCompositionEnter(event: { key: string; isComposing?: boolean; keyCode?: number }): boolean {
  return event.key === "Enter" && (event.isComposing === true || event.keyCode === 229);
}

export async function draftScope(): Promise<string> {
  const token = await ensureSession();
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("hilatv-drafts", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("drafts");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(new Error("浏览器暂时无法保留本地草稿，请等待同步后再离开"));
  });
}

export async function readLocalDraft(scope: string, projectId?: string): Promise<ProjectDraft | null> {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const request = db.transaction("drafts").objectStore("drafts").get(`${scope}:${projectId || "home"}`);
      request.onsuccess = () => {
        const doc = request.result as ProjectDraft | undefined;
        if (!doc || doc.started) return resolve(null);
      resolve({ ...restoredDraft(doc), files: doc.files.map((item) => ({ ...item, preview: item.file.type.startsWith("image/") ? URL.createObjectURL(item.file) : null })) });
      };
      request.onerror = () => reject(new Error("未能恢复本地草稿，请从项目列表继续"));
    });
  } finally { db.close(); }
}

export async function writeLocalDraft(scope: string, draft: ProjectDraft, isCurrent: () => boolean = () => true, backupId: string = crypto.randomUUID()): Promise<void> {
  const db = await database();
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction("drafts", "readwrite");
      const store = transaction.objectStore("drafts");
      const stored = { ...draft, files: draft.files.map((item) => ({ ...item, preview: null })) };
      if (isCurrent()) {
        store.put(stored, `${scope}:home`);
        if (draft.project_id) store.put(stored, `${scope}:${draft.project_id}`);
      } else {
        store.put({ id: backupId, created_at: Date.now(), reason: "离开页面前的本地输入", draft: stored }, `${scope}:backup:${backupId}`);
      }
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(new Error("本地草稿未能保存，请等待同步后再离开"));
      transaction.onabort = () => reject(new Error("本地草稿保存中断，请重试"));
    });
  } finally { db.close(); }
}

export async function writeDraftBackup(scope: string, draft: ProjectDraft, reason: string, id: string = crypto.randomUUID()): Promise<DraftBackup> {
  const backup = { id, created_at: Date.now(), reason, draft: { ...draft, files: draft.files.map((file) => ({ ...file, preview: null })) } };
  const db = await database();
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction("drafts", "readwrite");
      transaction.objectStore("drafts").put(backup, `${scope}:backup:${id}`);
      transaction.oncomplete = () => resolve();
      transaction.onerror = transaction.onabort = () => reject(new Error("未能保留本地副本，已停止替换草稿，请重试"));
    });
  } finally { db.close(); }
  return backup;
}

export async function readDraftBackups(scope: string, projectId?: string): Promise<DraftBackup[]> {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const rows: DraftBackup[] = [];
      const request = db.transaction("drafts").objectStore("drafts").openCursor();
      request.onsuccess = () => {
        const cursor = request.result;
        if (!cursor) return resolve(rows.sort((a, b) => b.created_at - a.created_at));
        if (String(cursor.key).startsWith(`${scope}:backup:`)) {
          const backup = cursor.value as DraftBackup;
            if (backup?.draft && backup.draft.project_id === projectId) rows.push({ ...backup, draft: restoredDraft(backup.draft) });
        }
        cursor.continue();
      };
      request.onerror = () => reject(new Error("本地副本列表读取失败，请重试"));
    });
  } finally { db.close(); }
}

export function withDraftPreviews(draft: ProjectDraft): ProjectDraft {
  return { ...restoredDraft(draft), files: draft.files.map((item) => ({ ...item, preview: item.file.type.startsWith("image/") ? URL.createObjectURL(item.file) : null })) };
}

function releaseDraftPreviews(draft: ProjectDraft) {
  for (const item of draft.files) if (item.preview?.startsWith("blob:")) URL.revokeObjectURL(item.preview);
}

export function draftFromServer(body: Record<string, unknown>, projectId: string): ProjectDraft {
  const draft = newDraft(typeof body.sentence === "string" ? body.sentence : "");
  draft.project_id = projectId;
  draft.draft_revision = typeof body.draft_revision === "number" ? body.draft_revision : 0;
  draft.skip_storyboard = body.skip_storyboard === true;
  draft.concept_selection = typeof body.concept_selection === "string" ? body.concept_selection : null;
  draft.generation_settings = generationSettings(body.generation_settings);
  draft.server_status = typeof body.status === "string" ? body.status : "draft";
  draft.submission_pending = draft.server_status !== "draft" || body.submission_state === "pending" || body.submission_state === "unknown_external_result";
  if (typeof body.submission_operation_id === "string") draft.start_operation_id = body.submission_operation_id;
  for (const item of (Array.isArray(body.attachments) ? body.attachments : [])) {
    if (item.kind === "url" && item.uri) draft.links.push({ id: crypto.randomUUID(), uri: item.uri });
    if (item.upload_id) draft.files.push({ id: crypto.randomUUID(), file: new File([], item.filename || "素材"), preview: null, uploaded: item });
  }
  const preview = body.concept_preview as { directions?: DirectionCard[] } | undefined;
  if (body.concept_preview_sentence === draft.sentence.trim() && Array.isArray(preview?.directions)) {
    draft.cards = preview.directions;
    draft.cards_sentence = String(body.concept_preview_sentence);
    draft.cards_input_key = conceptInputKey(draft.sentence, body.concept_preview_generation_settings);
  }
  draft.synced_fingerprint = draftFingerprint(draft);
  return draft;
}

export async function loadServerDraft(projectId: string, allowSubmitted = false): Promise<ProjectDraft> {
  const response = await apiFetch(`/v1/projects/${encodeURIComponent(projectId)}`);
  if (!response.ok) throw new Error(await errorMessage(response));
  const body = await response.json();
  if (!allowSubmitted && body.status !== "draft") throw new Error("这个项目已经开始制作，请从项目页继续");
  return draftFromServer(body, projectId);
}

/** One serial save. The caller merges acknowledgements into the latest local text. */
export async function syncServerDraft(input: ProjectDraft, onProgress: (draft: ProjectDraft) => Promise<void>, guard: () => void = () => undefined): Promise<ProjectDraft> {
  guard();
  const draft = { ...input, files: input.files.map((item) => ({ ...item })) };
  for (const item of draft.files) {
    if (item.uploaded) continue;
    guard();
    const form = new FormData();
    form.append("file", item.file, item.file.name);
    const response = await apiFetch("/v1/uploads", { method: "POST", body: form });
    guard();
    if (!response.ok) throw new Error(await errorMessage(response));
    const upload = await response.json() as UploadedDraftFile;
    if (!upload.upload_id || !upload.kind) throw new Error("上传结果不完整，请重试");
    item.uploaded = upload;
    await onProgress(draft);
  }
  const body = {
    sentence: draft.sentence,
    attachments: [...draft.files.map((item) => item.uploaded!), ...draft.links.map((item) => ({ kind: "url", uri: item.uri }))],
    skip_storyboard: draft.skip_storyboard,
    concept_selection: draft.concept_selection,
    generation_settings: generationSettings(draft.generation_settings),
  };
  if (!draft.project_id) {
    draft.create_snapshot = draft.create_snapshot || body;
    await onProgress(draft);
    guard();
    const response = await apiFetch("/v1/projects/drafts", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...draft.create_snapshot, operation_id: draft.operation_id }),
    });
    guard();
    if (!response.ok) throw new Error(await errorMessage(response));
    const created = await response.json();
    if (!created.project_id || typeof created.draft_revision !== "number") throw new Error("未能确认草稿保存，请重试");
    draft.project_id = created.project_id;
    const changedElsewhere = response.status === 200 && created.draft_revision !== 1;
    draft.draft_revision = changedElsewhere ? 1 : created.draft_revision;
    await onProgress(draft);
    if (changedElsewhere) {
      const server = created.snapshot ? draftFromServer(created.snapshot, draft.project_id!) : await loadServerDraft(draft.project_id!, true);
      guard();
      throw new DraftConflictError("这份草稿已有新的保存记录，请核对两个版本。", server);
    }
  }
  guard();
  const response = await apiFetch(`/v1/projects/${encodeURIComponent(draft.project_id!)}/draft`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, draft_revision: draft.draft_revision }),
  });
  guard();
  if (response.status === 409) {
    const body = await response.json().catch(() => ({}));
    const snapshot = body.detail?.snapshot;
    if (snapshot && draft.project_id) throw new DraftConflictError(body.detail.message || "草稿有新的修改，未覆盖另一处的内容。请核对两个版本。", draftFromServer(snapshot, draft.project_id));
    throw new Error("草稿有新的修改，未覆盖另一处的内容。请重新读取服务器版本后核对。");
  }
  if (!response.ok) throw new Error(await errorMessage(response));
  const saved = await response.json();
  if (typeof saved.draft_revision !== "number") throw new Error("服务器尚未确认保存，请重试");
  draft.draft_revision = saved.draft_revision;
  draft.synced_fingerprint = draftFingerprint(draft);
  return draft;
}

export type DraftSessionState = {
  draft: ProjectDraft;
  ready: boolean;
  saving: boolean;
  resolving: boolean;
  error: string | null;
  conflict: ProjectDraft | null;
  backups: DraftBackup[];
};

export type DraftSessionIO = {
  scope: typeof draftScope;
  read: typeof readLocalDraft;
  write: typeof writeLocalDraft;
  archive: typeof writeDraftBackup;
  backups: typeof readDraftBackups;
  load: typeof loadServerDraft;
  sync: typeof syncServerDraft;
};

const draftIO: DraftSessionIO = { scope: draftScope, read: readLocalDraft, write: writeLocalDraft,
  archive: writeDraftBackup, backups: readDraftBackups, load: loadServerDraft, sync: syncServerDraft };

/** A route owns its references, queue and acknowledgements. React only subscribes. */
export class ProjectDraftSession {
  readonly id = crypto.randomUUID();
  private active = true;
  private epoch = 0;
  private scope = "";
  private listeners = new Set<() => void>();
  private writes: Promise<void> = Promise.resolve();
  private flight: Promise<ProjectDraft> | null = null;
  private state: DraftSessionState;

  constructor(readonly initialSentence = "", readonly projectId?: string, private io = draftIO) {
    this.state = { draft: newDraft(initialSentence), ready: false, saving: false, resolving: false, error: null, conflict: null, backups: [] };
  }

  snapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  isCurrent = () => this.active;
  ticket = () => { const epoch = this.epoch; return () => this.active && this.epoch === epoch; };

  invalidate() { this.active = false; this.epoch += 1; }
  close() {
    this.invalidate();
    if (this.scope && this.hasContent()) void this.persist(this.state.draft).catch(() => undefined);
    releaseDraftPreviews(this.state.draft);
  }

  private hasContent() { const doc = this.state.draft; return Boolean(doc.project_id || doc.sentence.trim() || doc.files.length || doc.links.length || settingsKey(doc.generation_settings) !== settingsKey()); }
  private emit(patch: Partial<DraftSessionState>) {
    this.state = { ...this.state, ...patch };
    if (this.active) this.listeners.forEach((listener) => listener());
  }
  private assert(ticket = this.isCurrent) { if (!ticket()) throw new StaleDraftSessionError(); }
  get dirty() { return this.hasContent() && draftFingerprint(this.state.draft) !== this.state.draft.synced_fingerprint; }
  get editable() { return this.active && this.state.ready && !this.state.resolving && !this.state.draft.submission_pending && !this.state.draft.started; }

  async restore() {
    this.active = true;
    this.epoch += 1;
    const ticket = this.ticket();
    this.emit({ ready: false, error: null, conflict: null, saving: false, resolving: false });
    try {
      const scope = await this.io.scope();
      this.assert(ticket);
      if (this.scope && this.scope !== scope) {
        const previousScope = this.scope;
        const previousDraft = this.state.draft;
        this.scope = "";
        this.emit({ draft: newDraft(this.initialSentence) });
        releaseDraftPreviews(previousDraft);
        if (previousDraft.project_id || previousDraft.sentence || previousDraft.files.length || previousDraft.links.length) {
          await this.io.archive(previousScope, previousDraft, "会话切换前保留的本地输入", `route-${this.id}`);
          this.assert(ticket);
        }
      }
      const local = await this.io.read(scope, this.projectId);
      this.assert(ticket);
      this.scope = scope;
      if (local) this.emit({ draft: local });
      const target = this.projectId || local?.project_id;
      const server = target ? await this.io.load(target, true) : null;
      this.assert(ticket);
      // A local record never grants authorization to an existing project.
      let restored = { ...(local || server || newDraft(this.initialSentence)) };
      if (target && restored.project_id !== target) throw new Error("本地草稿与当前项目不一致，已停止恢复");
      if (server?.submission_pending) {
        restored.submission_pending = true;
        restored.server_status = server.server_status;
        const sameSubmittedInput = local?.start_operation_id && local.start_operation_id === server.start_operation_id
          && draftFingerprint(local) === local.synced_fingerprint;
        if (local && !sameSubmittedInput) {
          restored.start_operation_id = undefined;
          this.emit({ conflict: server, error: "原项目已提交，但这份本地修改尚未确认提交。请核对两个版本，原输入不会清空。" });
        }
      } else if (server && local && draftFingerprint(local) === local.synced_fingerprint && server.draft_revision !== local.draft_revision) {
        // No local edit is pending; show the newer server document rather than resaving an old one.
        await this.io.archive(scope, local, "恢复时发现服务器新版本，保留的本地记录");
        this.assert(ticket);
        releaseDraftPreviews(local);
        restored = server;
      }
      const backups = await this.io.backups(scope, restored.project_id);
      this.assert(ticket);
      this.emit({ draft: restored, backups, ready: true });
    } catch (caught) {
      if (ticket()) this.emit({ ready: false, error: caught instanceof Error ? caught.message : "恢复草稿失败" });
    }
  }

  persist = (value: ProjectDraft): Promise<void> => {
    const scope = this.scope;
    const ticket = this.ticket();
    if (!scope) return Promise.resolve();
    const next = this.writes.catch(() => undefined).then(async () => {
      if (!ticket()) {
        await this.io.archive(scope, value, "离开页面前的本地输入", `route-${this.id}`);
      } else await this.io.write(scope, value, ticket, `route-${this.id}`);
    });
    this.writes = next;
    return next;
  };

  update = (patch: Partial<ProjectDraft>): boolean => {
    if (!this.editable) return false;
    const draft = { ...this.state.draft, ...patch };
    draft.generation_settings = generationSettings(draft.generation_settings);
    if (conceptInputKey(draft.sentence, draft.generation_settings) !== conceptInputKey(this.state.draft.sentence, this.state.draft.generation_settings)) {
      draft.cards = undefined;
      draft.cards_sentence = undefined;
      draft.cards_input_key = undefined;
      draft.concept_selection = null;
    }
    this.emit({ draft });
    const ticket = this.ticket();
    void this.persist(draft).catch((caught: unknown) => { if (ticket()) this.emit({ error: caught instanceof Error ? caught.message : "本地草稿未保存" }); });
    return true;
  };

  flush = (): Promise<ProjectDraft> => {
    if (this.flight) return this.flight;
    const ticket = this.ticket();
    const run = Promise.resolve().then(async () => {
      this.assert(ticket);
      if (!this.state.ready) throw new Error(this.state.error || "请先等待草稿恢复");
      if (this.state.conflict) throw new DraftConflictError("请先核对两个版本，再选择如何保存", this.state.conflict);
      if (this.state.draft.submission_pending || this.state.draft.started) return this.state.draft;
      this.emit({ saving: true, error: null });
      const acknowledge = async (saved: ProjectDraft) => {
        this.assert(ticket);
        const latest = this.state.draft;
        if (latest.project_id && saved.project_id && latest.project_id !== saved.project_id) throw new StaleDraftSessionError();
        const byId = new Map(saved.files.map((item) => [item.id, item.uploaded]));
        const merged = { ...latest, project_id: saved.project_id || latest.project_id,
          draft_revision: saved.draft_revision ?? latest.draft_revision,
          create_snapshot: saved.create_snapshot || latest.create_snapshot,
          files: latest.files.map((item) => ({ ...item, uploaded: byId.get(item.id) || item.uploaded })),
          synced_fingerprint: saved.synced_fingerprint || latest.synced_fingerprint };
        this.emit({ draft: merged });
        await this.persist(merged);
        this.assert(ticket);
      };
      while (!this.state.draft.started && (!this.state.draft.project_id || this.dirty)) {
        this.assert(ticket);
        const saved = await this.io.sync(this.state.draft, acknowledge, () => this.assert(ticket));
        await acknowledge(saved);
      }
      await this.writes;
      this.assert(ticket);
      return this.state.draft;
    }).catch((caught: unknown) => {
      if (ticket()) this.emit({ error: caught instanceof Error ? caught.message : "草稿未同步，请重试",
        ...(caught instanceof DraftConflictError ? { conflict: caught.server } : {}) });
      throw caught;
    }).finally(() => {
      if (this.flight === run) this.flight = null;
      if (ticket()) this.emit({ saving: false });
    });
    this.flight = run;
    return run;
  };

  inspectServer = async () => {
    const ticket = this.ticket();
    const projectId = this.state.draft.project_id;
    if (!projectId) return;
    try {
      const server = await this.io.load(projectId, true);
      this.assert(ticket);
      this.emit({ conflict: server, error: "请核对服务器版本和本地修改，再选择如何继续" });
    } catch (caught) { if (ticket()) this.emit({ error: caught instanceof Error ? caught.message : "读取失败" }); }
  };

  resolveConflict = async (choice: "server" | "mine") => {
    const ticket = this.ticket();
    const server = this.state.conflict;
    if (!server || !this.state.ready || this.state.saving) return;
    if (server.project_id !== this.state.draft.project_id || server.submission_pending) throw new Error("项目已经提交或发生变化，请打开原项目核对");
    this.emit({ saving: true, resolving: true, error: null });
    try {
      const backup = await this.io.archive(this.scope, this.state.draft, choice === "server" ? "采用服务器版本前保留的本地修改" : "确认保留本地修改前的副本");
      this.assert(ticket);
      const mine = this.state.draft;
      const draft = choice === "server" ? server : { ...mine, draft_revision: server.draft_revision, synced_fingerprint: undefined,
        submission_pending: false, start_operation_id: undefined };
      this.emit({ draft, conflict: null, backups: [backup, ...this.state.backups] });
      if (choice === "server") releaseDraftPreviews(mine);
      await this.persist(draft);
      this.assert(ticket);
      this.emit({ saving: false, resolving: false });
      if (choice === "mine") await this.flush();
    } catch (caught) {
      if (ticket()) this.emit({ saving: false, resolving: false, error: caught instanceof Error ? caught.message : "未能保留本地副本，未替换草稿" });
      throw caught;
    }
  };

  restoreBackup = async (backup: DraftBackup) => {
    const ticket = this.ticket();
    this.assert(ticket);
    const target = this.state.draft.project_id;
    if (backup.draft.project_id !== target || !this.editable) return;
    this.emit({ resolving: true });
    try {
      const previous = await this.io.archive(this.scope, this.state.draft, "恢复旧副本前保留的当前输入");
      this.assert(ticket);
      const server = target ? await this.io.load(target, true) : null;
      this.assert(ticket);
      const draft = withDraftPreviews(backup.draft);
      const previousDraft = this.state.draft;
      this.emit({ draft, conflict: server, backups: [previous, ...this.state.backups], error: server ? "本地副本已恢复，请先核对服务器版本" : null });
      releaseDraftPreviews(previousDraft);
      await this.persist(draft);
    } finally { if (ticket()) this.emit({ resolving: false }); }
  };

  stageSubmission = async (): Promise<ProjectDraft> => {
    const ticket = this.ticket();
    const saved = await this.flush();
    this.assert(ticket);
    if (saved.submission_pending && !saved.start_operation_id) throw new Error("原项目已经提交，请打开项目核对；本地输入未清空");
    const draft = { ...saved, start_operation_id: saved.start_operation_id || crypto.randomUUID(), submission_pending: true };
    this.emit({ draft });
    await this.persist(draft);
    this.assert(ticket);
    return draft;
  };

  confirmSubmission = async (saved: ProjectDraft) => {
    const ticket = this.ticket();
    this.assert(ticket);
    if (!saved.start_operation_id || saved.project_id !== this.state.draft.project_id || saved.start_operation_id !== this.state.draft.start_operation_id) throw new StaleDraftSessionError();
    const draft = { ...this.state.draft, started: true, submission_pending: false };
    await this.persist(draft);
    this.assert(ticket);
    this.emit({ draft });
  };
}
