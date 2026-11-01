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
});
