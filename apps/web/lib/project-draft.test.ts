import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./api";
import { DraftConflictError, ProjectDraftSession, StaleDraftSessionError, draftFingerprint, isCompositionEnter,
  newDraft, syncServerDraft, writeLocalDraft, type DraftBackup, type DraftSessionIO, type ProjectDraft } from "./project-draft";

vi.mock("./api", () => ({
  apiFetch: vi.fn(), ensureSession: vi.fn(),
  errorMessage: async (response: Response) => `save failed (${response.status})`,
}));

const request = vi.mocked(apiFetch);
beforeEach(() => { request.mockReset(); });
afterEach(() => vi.unstubAllGlobals());

describe("persistent draft transport", () => {
  it("recognizes composition Enter including the legacy 229 event", () => {
    expect(isCompositionEnter({ key: "Enter", isComposing: true })).toBe(true);
    expect(isCompositionEnter({ key: "Enter", keyCode: 229 })).toBe(true);
    expect(isCompositionEnter({ key: "Enter", isComposing: false, keyCode: 13 })).toBe(false);
    expect(isCompositionEnter({ key: "a", isComposing: true })).toBe(false);
  });

  it("keeps the uploaded attachment and the same project when a later save fails", async () => {
    let latest = newDraft("最新旁白与素材");
    latest.files.push({ id: "file-1", file: new File(["image"], "产品.png", { type: "image/png" }), preview: null });
    latest.links.push({ id: "link-1", uri: "https://example.test/product" });
    const operationId = latest.operation_id;
    request.mockResolvedValueOnce(Response.json({ kind: "image", upload_id: "upload-1", filename: "产品.png" }));
    request.mockResolvedValueOnce(Response.json({ project_id: "project-1", draft_revision: 1 }, { status: 201 }));
    request.mockResolvedValueOnce(new Response("", { status: 500 }));
    await expect(syncServerDraft(latest, async (saved) => { latest = saved; })).rejects.toThrow("500");
    expect(latest.project_id).toBe("project-1");
    expect(latest.operation_id).toBe(operationId);
    expect(latest.files[0].uploaded?.upload_id).toBe("upload-1");
    expect(latest.synced_fingerprint).toBeUndefined();
    request.mockResolvedValueOnce(Response.json({ project_id: "project-1", draft_revision: 2 }));
    const result = await syncServerDraft(latest, async (saved) => { latest = saved; });
    expect(result.synced_fingerprint).toBe(draftFingerprint(result));
    expect(request.mock.calls.map(([path]) => path)).toEqual([
      "/v1/uploads", "/v1/projects/drafts", "/v1/projects/project-1/draft", "/v1/projects/project-1/draft",
    ]);
    const body = JSON.parse(String(request.mock.calls[3][1]?.body));
    expect(body.attachments).toEqual([
      { kind: "image", upload_id: "upload-1", filename: "产品.png" },
      { kind: "url", uri: "https://example.test/product" },
    ]);
    expect(body.sentence).toBe("最新旁白与素材");
  });

  it("retains the original revision and input on a conflict without resending", async () => {
    const draft = { ...newDraft("我的未同步文字"), project_id: "project-1", draft_revision: 2 };
    request.mockResolvedValueOnce(new Response("", { status: 409 }));
    await expect(syncServerDraft(draft, async () => undefined)).rejects.toThrow("未覆盖");
    expect(request).toHaveBeenCalledTimes(1);
    expect(draft.sentence).toBe("我的未同步文字");
    expect(draft.draft_revision).toBe(2);
    expect(draft.synced_fingerprint).toBeUndefined();
  });
  it("retries a lost creation acknowledgement with its frozen payload while retaining newer input", async () => {
    let latest = newDraft("首次创建内容");
    const operation = latest.operation_id;
    request.mockRejectedValueOnce(new TypeError("lost response"));
    await expect(syncServerDraft(latest, async (saved) => { latest = saved; })).rejects.toThrow("lost response");
    latest = { ...latest, sentence: "连接中断期间继续输入的内容" };
    request.mockResolvedValueOnce(Response.json({ project_id: "same-project", draft_revision: 1 }));
    request.mockResolvedValueOnce(Response.json({ project_id: "same-project", draft_revision: 2 }));
    const result = await syncServerDraft(latest, async (saved) => { latest = saved; });
    const bodies = request.mock.calls.map(([, init]) => JSON.parse(String(init?.body)));
    expect(bodies[0].operation_id).toBe(operation);
    expect(bodies[1]).toEqual(bodies[0]);
    expect(bodies[1].sentence).toBe("首次创建内容");
    expect(bodies[2].sentence).toBe("连接中断期间继续输入的内容");
    expect(result.project_id).toBe("same-project");
  });

});

function copyDraft(draft: ProjectDraft): ProjectDraft {
  return { ...draft, files: draft.files.map((item) => ({ ...item })), links: draft.links.map((item) => ({ ...item })) };
}

function document(projectId: string, sentence: string, revision = 1): ProjectDraft {
  const draft = { ...newDraft(sentence), project_id: projectId, draft_revision: revision, server_status: "draft" };
  draft.synced_fingerprint = draftFingerprint(draft);
  return draft;
}

function harness(documents: ProjectDraft[]) {
  const local = new Map(documents.map((draft) => [draft.project_id || "home", copyDraft(draft)]));
  const server = new Map(documents.map((draft) => [draft.project_id!, copyDraft(draft)]));
  const writes: { project?: string; home: boolean; draft: ProjectDraft }[] = [];
  const archives: DraftBackup[] = [];
  const io: DraftSessionIO = {
    scope: vi.fn(async () => "account-scope"),
    read: vi.fn(async (_scope, projectId) => local.get(projectId || "home") ? copyDraft(local.get(projectId || "home")!) : null),
    write: vi.fn(async (_scope, draft, isCurrent = () => true) => {
      const home = isCurrent();
      writes.push({ project: draft.project_id, home, draft: copyDraft(draft) });
      if (!home) return;
      if (home) local.set("home", copyDraft(draft));
      if (draft.project_id) local.set(draft.project_id, copyDraft(draft));
    }),
    archive: vi.fn(async (_scope, draft, reason, id = crypto.randomUUID()) => {
      const backup = { id, created_at: Date.now(), reason, draft: copyDraft(draft) };
      archives.push(backup); return backup;
    }),
    backups: vi.fn(async (_scope, projectId) => archives.filter((item) => item.draft.project_id === projectId)),
    load: vi.fn(async (projectId) => {
      if (!server.has(projectId)) throw new Error("没有访问这个项目的权限");
      return copyDraft(server.get(projectId)!);
    }),
    sync: vi.fn(async (input, _progress, guard) => {
      guard?.();
      const projectId = input.project_id || "created-home";
      const remote = server.get(projectId);
      if (remote && input.draft_revision !== remote.draft_revision) throw new DraftConflictError("草稿有新的修改，未覆盖另一处内容", copyDraft(remote));
      const saved = { ...copyDraft(input), project_id: projectId, draft_revision: (remote?.draft_revision || 1) + 1 };
      saved.files = saved.files.map((item) => ({ ...item, uploaded: item.uploaded || { upload_id: `upload-${item.id}`, kind: "image", filename: item.file.name } }));
      saved.synced_fingerprint = draftFingerprint(saved); server.set(projectId, saved);
      return saved;
    }),
  };
  return { io, local, server, writes, archives };
}

const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

describe("route-owned draft recovery", () => {
  it("rejects early input while restore is pending instead of displaying then discarding attachments", async () => {
    const h = harness([]);
    let ready!: (scope: string) => void;
    h.io.scope = () => new Promise((resolve) => { ready = resolve; });
    const session = new ProjectDraftSession("", undefined, h.io);
    const restoring = session.restore();
    expect(session.snapshot().ready).toBe(false);
    expect(session.update({ files: [{ id: "early", file: new File(["bytes"], "early.png"), preview: null }] })).toBe(false);
    ready("scope"); await restoring;
    expect(session.snapshot().draft.files).toEqual([]);
    expect(h.io.sync).not.toHaveBeenCalled();
  });

  it("stops an old project's ACK before it can replace the next project's identity or send its text", async () => {
    const h = harness([document("A", "项目A"), document("B", "项目B", 10)]);
    let finish!: (draft: ProjectDraft) => void;
    const sync = vi.fn<DraftSessionIO["sync"]>().mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    h.io.sync = sync;
    const a = new ProjectDraftSession("", "A", h.io);
    await a.restore(); a.update({ sentence: "A的新输入" });
    const oldTicket = a.ticket();
    const saving = a.flush();
    const rejected = expect(saving).rejects.toBeInstanceOf(StaleDraftSessionError);
    await tick();
    const sent = copyDraft(sync.mock.calls[0][0]);
    a.invalidate();
    const b = new ProjectDraftSession("", "B", h.io);
    expect(b.snapshot().ready).toBe(false);
    await b.restore(); b.update({ sentence: "B的新输入" });
    const saved = { ...sent, draft_revision: 2, synced_fingerprint: draftFingerprint(sent) };
    finish(saved); await rejected;
    expect(oldTicket()).toBe(false);
    expect(sync).toHaveBeenCalledTimes(1);
    expect(b.snapshot().draft).toMatchObject({ project_id: "B", sentence: "B的新输入" });
  });

  it("evaluates home-write ownership after asynchronous storage opening", async () => {
    const h = harness([document("A", "A"), document("B", "B")]);
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    h.io.write = async (_scope, draft, isCurrent = () => true) => {
      await gate; h.writes.push({ project: draft.project_id, home: isCurrent(), draft });
    };
    const a = new ProjectDraftSession("", "A", h.io); await a.restore();
    a.update({ sentence: "A保存中" }); await tick();
    a.invalidate();
    const b = new ProjectDraftSession("", "B", h.io); await b.restore();
    b.update({ sentence: "B当前输入" }); await tick();
    release(); await tick();
    expect(h.writes.find((item) => item.project === "A")?.home).toBe(false);
    expect(h.writes.find((item) => item.project === "B")?.home).toBe(true);
  });

  it("keeps typing that happened during an older save and acknowledges the latest text next", async () => {
    const h = harness([document("A", "旧内容")]);
    let finish!: (draft: ProjectDraft) => void;
    const real = h.io.sync;
    const sync = vi.fn<DraftSessionIO["sync"]>().mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; })).mockImplementation(real);
    h.io.sync = sync;
    const session = new ProjectDraftSession("", "A", h.io); await session.restore();
    session.update({ sentence: "第一段" }); const saving = session.flush(); await tick();
    const first = copyDraft(sync.mock.calls[0][0]);
    session.update({ sentence: "继续输入的完整内容" });
    const saved = { ...first, draft_revision: 2, synced_fingerprint: draftFingerprint(first) };
    h.server.set("A", saved); finish(saved); await saving;
    expect(sync.mock.calls.map(([input]) => input.sentence)).toEqual(["第一段", "继续输入的完整内容"]);
    expect(session.snapshot().draft.sentence).toBe("继续输入的完整内容");
    expect(session.dirty).toBe(false);
  });

  it("retains the pinned POST snapshot when the route changes during its creation ACK", async () => {
    let active = true;
    const draft = newDraft("首次创建输入");
    let ack!: (response: Response) => void;
    request.mockImplementationOnce(() => new Promise((resolve) => { ack = resolve; }));
    let captured = draft;
    const running = syncServerDraft(draft, async (saved) => { captured = saved; }, () => { if (!active) throw new StaleDraftSessionError(); });
    const rejected = expect(running).rejects.toBeInstanceOf(StaleDraftSessionError);
    await tick(); active = false;
    ack(Response.json({ project_id: "old-project", draft_revision: 1 }, { status: 201 })); await rejected;
    expect(captured.create_snapshot?.sentence).toBe("首次创建输入");
    expect(captured.project_id).toBeUndefined();
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("retries a transient restoration failure without a permanently rejected flight", async () => {
    const h = harness([document("A", "保留输入")]);
    h.io.scope = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue("scope");
    const session = new ProjectDraftSession("", "A", h.io);
    await session.restore(); expect(session.snapshot().ready).toBe(false);
    await expect(session.flush()).rejects.toThrow("offline");
    await session.restore(); expect(session.snapshot().ready).toBe(true);
    session.update({ sentence: "网络恢复后的输入" }); await session.flush();
    expect(session.dirty).toBe(false);
  });

  it("never replaces an unauthorized existing project with a new draft", async () => {
    const h = harness([document("A", "本机保留的文字")]); h.server.delete("A");
    const session = new ProjectDraftSession("", "A", h.io); await session.restore();
    expect(session.snapshot()).toMatchObject({ ready: false, draft: { project_id: "A", sentence: "本机保留的文字" } });
    await expect(session.flush()).rejects.toThrow("权限");
    expect(h.io.sync).not.toHaveBeenCalled();
  });

  it("does not rebase or resend a real conflict until the user chooses after comparing both inputs", async () => {
    const mine = document("A", "我的修改", 1); mine.synced_fingerprint = "old";
    const h = harness([mine]); h.server.set("A", document("A", "服务器另一处的修改", 3));
    const session = new ProjectDraftSession("", "A", h.io); await session.restore();
    await expect(session.flush()).rejects.toBeInstanceOf(DraftConflictError);
    expect(session.snapshot().draft).toMatchObject({ sentence: "我的修改", draft_revision: 1 });
    expect(session.snapshot().conflict?.sentence).toBe("服务器另一处的修改");
    await expect(session.flush()).rejects.toBeInstanceOf(DraftConflictError);
    expect(h.io.sync).toHaveBeenCalledTimes(1);
    await session.resolveConflict("mine");
    expect(h.io.sync).toHaveBeenCalledTimes(2);
    expect(session.snapshot().draft).toMatchObject({ sentence: "我的修改", draft_revision: 4 });
    expect(h.archives[0].draft.sentence).toBe("我的修改");
  });

  it("archives actual local attachment bytes before adoption and can restore them after reloading", async () => {
    const mine = document("A", "我的修改", 1); mine.synced_fingerprint = "old";
    mine.files = [{ id: "mine-file", file: new File(["original image bytes"], "我的产品.png", { type: "image/png" }), preview: null }];
    mine.links = [{ id: "mine-link", uri: "https://example.test/mine" }];
    const h = harness([mine]);
    const server = document("A", "服务器文字", 2);
    server.files = [{ id: "server-file", file: new File([], "服务器品牌.pdf"), preview: null, uploaded: { kind: "pdf", upload_id: "remote-file", filename: "服务器品牌.pdf" } }];
    server.synced_fingerprint = draftFingerprint(server); h.server.set("A", server);
    const session = new ProjectDraftSession("", "A", h.io); await session.restore();
    await expect(session.flush()).rejects.toBeInstanceOf(DraftConflictError);
    await session.resolveConflict("server");
    expect(session.snapshot().draft.sentence).toBe("服务器文字");
    expect(await h.archives[0].draft.files[0].file.text()).toBe("original image bytes");
    const reloaded = new ProjectDraftSession("", "A", h.io); await reloaded.restore();
    expect(reloaded.snapshot().backups.length).toBe(1);
    await reloaded.restoreBackup(reloaded.snapshot().backups[0]);
    expect(reloaded.snapshot().draft.sentence).toBe("我的修改");
    expect(reloaded.snapshot().draft.links[0].uri).toBe("https://example.test/mine");
    expect(await reloaded.snapshot().draft.files[0].file.text()).toBe("original image bytes");
    expect(reloaded.snapshot().conflict?.sentence).toBe("服务器文字");
    expect(h.io.sync).toHaveBeenCalledTimes(1);
  });

  it("refuses to adopt the server version when the recoverable backup failed", async () => {
    const mine = document("A", "必须保留的本地输入", 1); mine.synced_fingerprint = "old";
    const h = harness([mine]); h.server.set("A", document("A", "服务器内容", 2));
    h.io.archive = vi.fn().mockRejectedValue(new Error("backup quota exceeded"));
    const session = new ProjectDraftSession("", "A", h.io); await session.restore();
    await expect(session.flush()).rejects.toBeInstanceOf(DraftConflictError);
    await expect(session.resolveConflict("server")).rejects.toThrow("backup quota");
    expect(session.snapshot().draft.sentence).toBe("必须保留的本地输入");
    expect(session.snapshot().conflict?.sentence).toBe("服务器内容");
  });

  it("keeps a second server conflict visible instead of silently advancing the chosen revision again", async () => {
    const mine = document("A", "我的输入", 1); mine.synced_fingerprint = "old";
    const h = harness([mine]); h.server.set("A", document("A", "服务器第二版", 2));
    const session = new ProjectDraftSession("", "A", h.io); await session.restore();
    await expect(session.flush()).rejects.toBeInstanceOf(DraftConflictError);
    h.server.set("A", document("A", "服务器又有新修改", 3));
    await expect(session.resolveConflict("mine")).rejects.toBeInstanceOf(DraftConflictError);
    expect(session.snapshot().draft).toMatchObject({ sentence: "我的输入", draft_revision: 2 });
    expect(session.snapshot().conflict).toMatchObject({ sentence: "服务器又有新修改", draft_revision: 3 });
    expect(h.io.sync).toHaveBeenCalledTimes(2);
  });

  it("recovers a committed PUT whose acknowledgement was lost without changing the sent input or revision", async () => {
    const h = harness([document("A", "最初内容")]); h.io.sync = syncServerDraft;
    let remoteRevision = 1; let acceptedBody = "";
    request.mockImplementation(async (_path, init) => {
      if (init?.method !== "PUT") throw new Error(`unexpected request ${_path} ${init?.method}`);
      const serialized = String(init?.body); const body = JSON.parse(serialized);
      if (!acceptedBody) { acceptedBody = serialized; remoteRevision += 1; throw new TypeError("ACK lost after commit"); }
      expect(serialized).toBe(acceptedBody); expect(body.draft_revision).toBe(1);
      return Response.json({ project_id: "A", draft_revision: remoteRevision });
    });
    const session = new ProjectDraftSession("", "A", h.io); await session.restore(); session.update({ sentence: "已提交但回执丢失的内容" });
    await expect(session.flush()).rejects.toThrow("ACK lost");
    await session.flush();
    expect(request).toHaveBeenCalledTimes(2);
    expect(session.snapshot().draft).toMatchObject({ sentence: "已提交但回执丢失的内容", draft_revision: 2 });
    expect(session.dirty).toBe(false);
  });

  it("retains a pending film submission and freezes input across reload and retry", async () => {
    const draft = document("A", "不能丢失的原始提交");
    draft.files = [{ id: "picture", file: new File(["bytes"], "产品.png"), preview: null, uploaded: { kind: "image", upload_id: "owned", filename: "产品.png" } }];
    draft.synced_fingerprint = draftFingerprint(draft);
    const h = harness([draft]); const session = new ProjectDraftSession("", "A", h.io); await session.restore();
    const first = await session.stageSubmission();
    expect(first.submission_pending).toBe(true);
    expect(session.update({ sentence: "保存期间不应接受的改动" })).toBe(false);
    session.close(); await tick();
    h.server.set("A", { ...draft, server_status: "submitting", submission_pending: true, start_operation_id: first.start_operation_id });
    const restored = new ProjectDraftSession("", "A", h.io); await restored.restore();
    const retry = await restored.stageSubmission();
    expect(retry.start_operation_id).toBe(first.start_operation_id);
    expect(retry.sentence).toBe(first.sentence);
    expect(retry.files[0].uploaded?.upload_id).toBe("owned");
    expect(h.io.sync).not.toHaveBeenCalled();
    restored.invalidate();
    await expect(restored.confirmSubmission(retry)).rejects.toBeInstanceOf(StaleDraftSessionError);
    expect(restored.snapshot().draft.started).not.toBe(true);
  });

  it("keeps the pending submission if its final local confirmation cannot be persisted", async () => {
    const h = harness([document("A", "原提交输入")]);
    const session = new ProjectDraftSession("", "A", h.io); await session.restore();
    const pending = await session.stageSubmission();
    h.io.write = vi.fn().mockRejectedValue(new Error("browser storage failed"));
    await expect(session.confirmSubmission(pending)).rejects.toThrow("browser storage");
    expect(session.snapshot().draft).toMatchObject({ submission_pending: true, start_operation_id: pending.start_operation_id });
    expect(session.snapshot().draft.started).not.toBe(true);
  });

  it("does not mark unsent local edits as submitted by borrowing a different server submission", async () => {
    const mine = document("A", "尚未提交的本地新输入"); mine.synced_fingerprint = "older-input";
    const h = harness([mine]);
    h.server.set("A", { ...document("A", "另一处已提交的旧内容"), submission_pending: true, server_status: "running", start_operation_id: "different-submission" });
    const session = new ProjectDraftSession("", "A", h.io); await session.restore();
    expect(session.snapshot().draft.sentence).toBe("尚未提交的本地新输入");
    expect(session.snapshot().draft.start_operation_id).toBeUndefined();
    expect(session.snapshot().conflict?.sentence).toBe("另一处已提交的旧内容");
    await expect(session.stageSubmission()).rejects.toBeInstanceOf(DraftConflictError);
    expect(h.io.sync).not.toHaveBeenCalled();
    expect(session.snapshot().draft.started).not.toBe(true);
  });

  it("writes only an isolated backup when IndexedDB opens after its route was invalidated", async () => {
    const puts: string[] = []; let opened!: () => void;
    const transaction = { objectStore: () => ({ put: (_value: unknown, key: string) => puts.push(key) }), oncomplete: null as (() => void) | null };
    vi.stubGlobal("indexedDB", { open: () => {
      const request = { result: { transaction: () => { queueMicrotask(() => transaction.oncomplete?.()); return transaction; }, close: () => undefined }, onsuccess: null as (() => void) | null };
      opened = () => request.onsuccess?.(); return request;
    } });
    let active = true;
    const saved = writeLocalDraft("scope", document("A", "只属于旧项目"), () => active, "old-route");
    active = false; opened(); await saved;
    expect(puts).toEqual(["scope:backup:old-route"]);
  });
});
