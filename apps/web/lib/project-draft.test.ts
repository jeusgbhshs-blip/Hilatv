import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./api";
import { draftFingerprint, isCompositionEnter, newDraft, syncServerDraft } from "./project-draft";

vi.mock("./api", () => ({
  apiFetch: vi.fn(), ensureSession: vi.fn(),
  errorMessage: async (response: Response) => `save failed (${response.status})`,
}));

const request = vi.mocked(apiFetch);
beforeEach(() => request.mockReset());

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
