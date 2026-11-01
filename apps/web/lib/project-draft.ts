import { apiFetch, ensureSession, errorMessage } from "./api";
import type { DirectionCard } from "./selection";

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
  cards?: DirectionCard[];
  cards_sentence?: string;
  brand_applied?: boolean;
  start_operation_id?: string;
  create_snapshot?: {
    sentence: string;
    attachments: (UploadedDraftFile | { kind: string; uri: string })[];
    skip_storyboard: boolean;
    concept_selection: string | null;
  };
  started?: boolean;
  synced_fingerprint?: string;
};

export function newDraft(sentence = ""): ProjectDraft {
  return { operation_id: crypto.randomUUID(), sentence, files: [], links: [], skip_storyboard: false, concept_selection: null };
}

/** No file bytes or credentials enter a URL or JSON transport. File bytes live in IndexedDB. */
export function draftFingerprint(draft: ProjectDraft): string {
  return JSON.stringify({
    sentence: draft.sentence,
    files: draft.files.map((item) => [item.id, item.file.name, item.file.size, item.uploaded?.upload_id]),
    links: draft.links.map((item) => item.uri),
    skip_storyboard: draft.skip_storyboard,
    concept_selection: draft.concept_selection,
  });
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
        resolve({ ...doc, files: doc.files.map((item) => ({ ...item, preview: item.file.type.startsWith("image/") ? URL.createObjectURL(item.file) : null })) });
      };
      request.onerror = () => reject(new Error("未能恢复本地草稿，请从项目列表继续"));
    });
  } finally { db.close(); }
}

export async function writeLocalDraft(scope: string, draft: ProjectDraft): Promise<void> {
  const db = await database();
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction("drafts", "readwrite");
      const store = transaction.objectStore("drafts");
      const stored = { ...draft, files: draft.files.map((item) => ({ ...item, preview: null })) };
      store.put(stored, `${scope}:home`);
      if (draft.project_id) store.put(stored, `${scope}:${draft.project_id}`);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(new Error("本地草稿未能保存，请等待同步后再离开"));
      transaction.onabort = () => reject(new Error("本地草稿保存中断，请重试"));
    });
  } finally { db.close(); }
}

export async function loadServerDraft(projectId: string): Promise<ProjectDraft> {
  const response = await apiFetch(`/v1/projects/${encodeURIComponent(projectId)}`);
  if (!response.ok) throw new Error(await errorMessage(response));
  const body = await response.json();
  if (body.status !== "draft") throw new Error("这个项目已经开始制作，请从项目页继续");
  const draft = newDraft(body.sentence || "");
  draft.project_id = projectId;
  draft.draft_revision = body.draft_revision ?? 0;
  draft.skip_storyboard = body.skip_storyboard === true;
  draft.concept_selection = body.concept_selection || null;
  for (const item of body.attachments || []) {
    if (item.kind === "url" && item.uri) draft.links.push({ id: crypto.randomUUID(), uri: item.uri });
    if (item.upload_id) draft.files.push({ id: crypto.randomUUID(), file: new File([], item.filename || "素材"), preview: null, uploaded: item });
  }
  if (body.concept_preview_sentence === draft.sentence.trim() && Array.isArray(body.concept_preview?.directions)) {
    draft.cards = body.concept_preview.directions;
    draft.cards_sentence = body.concept_preview_sentence;
  }
  draft.synced_fingerprint = draftFingerprint(draft);
  return draft;
}

/** One serial save. The caller merges acknowledgements into the latest local text. */
export async function syncServerDraft(input: ProjectDraft, onProgress: (draft: ProjectDraft) => Promise<void>): Promise<ProjectDraft> {
  const draft = { ...input, files: input.files.map((item) => ({ ...item })) };
  for (const item of draft.files) {
    if (item.uploaded) continue;
    const form = new FormData();
    form.append("file", item.file, item.file.name);
    const response = await apiFetch("/v1/uploads", { method: "POST", body: form });
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
  };
  if (!draft.project_id) {
    draft.create_snapshot = draft.create_snapshot || body;
    await onProgress(draft);
    const response = await apiFetch("/v1/projects/drafts", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...draft.create_snapshot, operation_id: draft.operation_id }),
    });
    if (!response.ok) throw new Error(await errorMessage(response));
    const created = await response.json();
    if (!created.project_id || typeof created.draft_revision !== "number") throw new Error("未能确认草稿保存，请重试");
    draft.project_id = created.project_id;
    const changedElsewhere = response.status === 200 && created.draft_revision !== 1;
    draft.draft_revision = changedElsewhere ? 1 : created.draft_revision;
    await onProgress(draft);
    if (changedElsewhere) throw new Error("这份草稿已有新的保存记录。你的输入已保留，请从项目页核对后继续。");
  }
  const response = await apiFetch(`/v1/projects/${encodeURIComponent(draft.project_id!)}/draft`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, draft_revision: draft.draft_revision }),
  });
  if (response.status === 409) throw new Error("草稿有新的修改，未覆盖另一处的内容。你的输入仍保留，请从项目页核对后重试。");
  if (!response.ok) throw new Error(await errorMessage(response));
  const saved = await response.json();
  if (typeof saved.draft_revision !== "number") throw new Error("服务器尚未确认保存，请重试");
  draft.draft_revision = saved.draft_revision;
  draft.synced_fingerprint = draftFingerprint(draft);
  return draft;
}
