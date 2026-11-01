import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./api";
import { createCanvasClient } from "./canvas-client";
import { seedCanvas, type KeyValueStore } from "./canvas-mock";

vi.mock("./api", () => ({
  apiFetch: vi.fn(),
  errorMessage: async (response: Response) => `读取或保存失败 (${response.status})`,
}));

function memory(): KeyValueStore {
  const entries = new Map<string, string>();
  return {
    getItem: (key) => entries.get(key) ?? null,
    setItem: (key, value) => { entries.set(key, value); },
    removeItem: (key) => { entries.delete(key); },
  };
}

const request = vi.mocked(apiFetch);
beforeEach(() => request.mockReset());

describe("project transport must not replace a failed project with a demo", () => {
  it.each([401, 404, 405, 500])("preserves HTTP %i as an error without seeding local content", async (status) => {
    request.mockResolvedValue(new Response("", { status }));
    const storage = memory();
    await expect(createCanvasClient("real-project", storage).load()).rejects.toMatchObject({ status });
    expect(storage.getItem("hilatv.canvas.v0.real-project")).toBeNull();
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("reports a broken connection and invalid successful payloads", async () => {
    request.mockRejectedValueOnce(new TypeError("offline"));
    await expect(createCanvasClient("real-project", memory()).load()).rejects.toMatchObject({ status: 0 });
    request.mockResolvedValueOnce(Response.json({ unexpected: true }));
    await expect(createCanvasClient("real-project", memory()).load()).rejects.toMatchObject({ status: 502 });
  });

  it("opens an explicit local demo without touching the API", async () => {
    const client = createCanvasClient("demo-canvas", memory(), { demo: true });
    expect((await client.load()).origin).toBe("mock");
    await client.deleteNode("absent").catch(() => undefined);
    await expect(client.startFilm("new film")).rejects.toMatchObject({ status: 422 });
    expect(request).not.toHaveBeenCalled();
  });

  it("does not turn an unsupported create into a local success", async () => {
    request.mockResolvedValueOnce(Response.json(seedCanvas("real-project")));
    request.mockResolvedValueOnce(new Response("", { status: 404 }));
    const client = createCanvasClient("real-project", memory());
    await client.load();
    await expect(client.createNode({ kind: "brief", position: { x: 0, y: 0 }, data: { text: "draft" } }))
      .rejects.toMatchObject({ status: 404 });
  });

  it("never retries a conflicting layout by replacing its revision", async () => {
    request.mockResolvedValueOnce(Response.json(seedCanvas("real-project")));
    request.mockResolvedValueOnce(new Response("", { status: 409 }));
    const client = createCanvasClient("real-project", memory());
    const doc = await client.load();
    await expect(client.saveLayout({ layout_version: doc.layout_version, positions: {}, viewport: doc.viewport }))
      .rejects.toMatchObject({ status: 409 });
    expect(request).toHaveBeenCalledTimes(2);
  });

  it("rejects failed upload instead of returning a made-up upload identifier", async () => {
    request.mockResolvedValueOnce(new Response("", { status: 413 }));
    const client = createCanvasClient("real-project", memory());
    await expect(client.uploadImage(new File(["bytes"], "picture.png", { type: "image/png" })))
      .rejects.toMatchObject({ status: 413 });
  });
  it("backs up every typed shot draft and restores it after a failed PATCH and a reload", async () => {
    const storage = memory();
    request.mockResolvedValueOnce(Response.json(seedCanvas("real-project")));
    const client = createCanvasClient("real-project", storage);
    await client.load();
    const staged = client.stageNodeData("shot-1", { kind: "shot", narration: "刚输入、尚未离开输入框" });
    expect(staged.pending_edits).toBe(true);
    expect(request).toHaveBeenCalledTimes(1);
    request.mockResolvedValueOnce(new Response("", { status: 500 }));
    await expect(client.flushNodeData()).rejects.toMatchObject({ status: 500 });
    request.mockResolvedValueOnce(Response.json(seedCanvas("real-project")));
    const restored = await createCanvasClient("real-project", storage).load();
    expect(restored.pending_edits).toBe(true);
    expect(restored.nodes.find((node) => node.id === "shot-1")?.data).toMatchObject({ narration: "刚输入、尚未离开输入框" });
  });

  it("keeps edits made during an in-flight acknowledgement and sends the latest text", async () => {
    const storage = memory();
    request.mockResolvedValueOnce(Response.json(seedCanvas("real-project")));
    const client = createCanvasClient("real-project", storage);
    await client.load();
    client.stageNodeData("shot-1", { kind: "shot", narration: "第一句" });
    let acknowledge!: (response: Response) => void;
    request.mockImplementationOnce(() => new Promise((resolve) => { acknowledge = resolve; }));
    const saving = client.flushNodeData();
    client.stageNodeData("shot-1", { kind: "shot", narration: "最后输入的完整句子" });
    request.mockResolvedValueOnce(Response.json({ layout_version: 3 }));
    const remote = seedCanvas("real-project");
    const shot = remote.nodes.find((node) => node.id === "shot-1")!;
    shot.data = { ...shot.data, narration: "最后输入的完整句子" };
    request.mockResolvedValueOnce(Response.json(remote));
    acknowledge(Response.json({ layout_version: 2 }));
    const result = await saving;
    const writes = request.mock.calls.filter(([, init]) => init?.method === "PATCH");
    expect(writes.map(([, init]) => JSON.parse(String(init?.body)).data.narration)).toEqual(["第一句", "最后输入的完整句子"]);
    expect(result.pending_edits).toBe(false);
    expect(result.nodes.find((node) => node.id === "shot-1")?.data).toMatchObject({ narration: "最后输入的完整句子" });
  });

  it("restores a failed layout but never silently rebases its server revision", async () => {
    const storage = memory();
    request.mockResolvedValueOnce(Response.json(seedCanvas("real-project")));
    const client = createCanvasClient("real-project", storage);
    const doc = await client.load();
    const layout = { layout_version: doc.layout_version, positions: { "shot-1": { x: 920, y: 50 } }, viewport: doc.viewport };
    client.stageLayout(layout);
    request.mockResolvedValueOnce(Response.json({ ...seedCanvas("real-project"), layout_version: 90 }));
    const restored = createCanvasClient("real-project", storage);
    expect((await restored.load()).nodes.find((node) => node.id === "shot-1")?.position.x).toBe(920);
    request.mockResolvedValueOnce(new Response("", { status: 409 }));
    await expect(restored.flushNodeData()).rejects.toMatchObject({ status: 409 });
    const write = request.mock.calls.find(([, init]) => init?.method === "PUT")!;
    expect(JSON.parse(String(write[1]?.body)).layout_version).toBe(layout.layout_version);
  });

});
