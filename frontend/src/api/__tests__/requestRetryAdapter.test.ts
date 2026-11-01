import { afterEach, describe, expect, it, vi } from "vitest";
import axios, { AxiosError, type AxiosAdapter } from "axios";
import { createServer } from "node:http";
import { once } from "node:events";
import { createRequestRetryAdapter } from "../requestRetryAdapter";

const path = "/convert/replace-colors-batch";
const body = { session_id: "session", operation_id: "edit-1", replacements: [] };

function clientWith(statuses: number[], headers: Record<string, string> = {}) {
  const base: AxiosAdapter = vi.fn(async (config) => {
    const status = statuses.shift() ?? 500;
    const response = { status, statusText: "", data: {}, headers, config };
    if (status >= 400) throw new AxiosError("failed", "ERR_BAD_RESPONSE", config, undefined, response);
    return response;
  });
  return { client: axios.create({ adapter: createRequestRetryAdapter(base) }), base };
}

afterEach(() => vi.useRealTimers());

describe("batch editor request recovery", () => {
  it.each([502, 503, 504])("retries HTTP %s once with the identical operation", async (status) => {
    const { client, base } = clientWith([status, 200]);
    await expect(client.post(path, body)).resolves.toMatchObject({ status: 200 });
    expect(base).toHaveBeenCalledTimes(2);
    expect(vi.mocked(base).mock.calls[0][0].data).toBe(vi.mocked(base).mock.calls[1][0].data);
  });

  it.each([400, 404, 409, 422, 500])("does not replay HTTP %s", async (status) => {
    const { client, base } = clientWith([status]);
    await expect(client.post(path, body)).rejects.toMatchObject({ response: { status } });
    expect(base).toHaveBeenCalledOnce();
  });

  it.each([{}, { operation_id: "" }, { operation_id: "edit-1" }])("requires both session and operation identities: %j", async (data) => {
    const { client, base } = clientWith([502]);
    await expect(client.post(path, data)).rejects.toBeInstanceOf(AxiosError);
    expect(base).toHaveBeenCalledOnce();
  });

  it("leaves other writes alone and stops after a second failed attempt", async () => {
    const { client, base } = clientWith([502, 502, 502]);
    await expect(client.post("/convert/generate", body)).rejects.toBeInstanceOf(AxiosError);
    expect(base).toHaveBeenCalledOnce();
    await expect(client.post(path, body)).rejects.toBeInstanceOf(AxiosError);
    expect(base).toHaveBeenCalledTimes(3);
  });

  it("hands duplicate-commit responses back to the existing receipt reconciliation", async () => {
    const { client, base } = clientWith([502, 409]);
    await expect(client.post(path, body)).rejects.toMatchObject({ response: { status: 409 } });
    expect(base).toHaveBeenCalledTimes(2);
  });

  it("does not resend after cancellation during the retry delay", async () => {
    vi.useFakeTimers();
    const { client, base } = clientWith([502, 200]);
    const controller = new AbortController();
    const outcome = client.post(path, body, { signal: controller.signal }).catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(1);
    controller.abort();
    await vi.runAllTimersAsync();
    expect(axios.isCancel(await outcome)).toBe(true);
    expect(base).toHaveBeenCalledOnce();
  });

  it("recovers a real dropped HTTP connection without changing the JSON body", async () => {
    const bodies: string[] = [];
    const server = createServer((request, response) => {
      response.setHeader("Access-Control-Allow-Origin", "*");
      response.setHeader("Access-Control-Allow-Headers", "Content-Type");
      if (request.method === "OPTIONS") { response.writeHead(204).end(); return; }
      let content = "";
      request.on("data", (chunk) => { content += chunk.toString(); });
      request.on("end", () => {
        bodies.push(content);
        if (bodies.length === 1) { request.socket.destroy(); return; }
        response.setHeader("Content-Type", "application/json");
        response.end(JSON.stringify({ status: "ok" }));
      });
    });
    server.listen(0, "127.0.0.1");
    await once(server, "listening");
    const address = server.address() as { port: number };
    const client = axios.create({
      baseURL: `http://127.0.0.1:${address.port}`,
      adapter: createRequestRetryAdapter(axios.getAdapter("xhr")),
    });
    try {
      await expect(client.post(path, body)).resolves.toMatchObject({ data: { status: "ok" } });
      expect(bodies).toEqual([JSON.stringify(body), JSON.stringify(body)]);
    } finally {
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
});

describe("stateless request recovery", () => {
  it.each([
    "/system/printers",
    "/system/slicers",
    "/system/3mf-templates",
    "/extractor/gradient-card-materials",
  ])("recovers %s without changing query parameters or headers", async (url) => {
    const { client, base } = clientWith([502, 200]);
    await expect(client.get(url, {
      params: { include_file_urls: true }, headers: { "If-None-Match": "catalog-version" },
    })).resolves.toMatchObject({ status: 200 });
    expect(base).toHaveBeenCalledTimes(2);
    expect(vi.mocked(base).mock.calls[1][0]).toMatchObject({
      params: { include_file_urls: true }, headers: { "If-None-Match": "catalog-version" },
    });
  });

  it.each(["/convert/crop", "/convert/auto-detect-colors"])("recovers %s with the original upload", async (url) => {
    const { client, base } = clientWith([504, 200]);
    const upload = new FormData();
    upload.append("image", new File(["source pixels"], "source.png", { type: "image/png" }));
    upload.append("width", "42");
    await expect(client.post(url, upload)).resolves.toMatchObject({ status: 200 });
    expect(base).toHaveBeenCalledTimes(2);
    for (const [config] of vi.mocked(base).mock.calls) expect(config.data).toBe(upload);
  });

  it("resends complete multipart file bytes after the first response is lost", async () => {
    const bodies: string[] = [];
    const server = createServer((request, response) => {
      response.setHeader("Access-Control-Allow-Origin", "*");
      const chunks: Buffer[] = [];
      request.on("data", (chunk: Buffer) => chunks.push(chunk));
      request.on("end", () => {
        const boundary = request.headers["content-type"]?.split("boundary=")[1] ?? "";
        bodies.push(Buffer.concat(chunks).toString("latin1").replaceAll(boundary, "BOUNDARY"));
        if (bodies.length === 1) { request.socket.destroy(); return; }
        response.setHeader("Content-Type", "application/json");
        response.end(JSON.stringify({ status: "ok" }));
      });
    });
    server.listen(0, "127.0.0.1");
    await once(server, "listening");
    const address = server.address() as { port: number };
    const client = axios.create({
      baseURL: `http://127.0.0.1:${address.port}`,
      adapter: createRequestRetryAdapter(axios.getAdapter("xhr")),
    });
    const pixels = new Uint8Array([0, 1, 2, 128, 255]);
    const upload = new FormData();
    upload.append("image", new File([pixels], "source.png", { type: "image/png" }));
    upload.append("width", "42");
    try {
      await expect(client.post("/convert/crop", upload)).resolves.toMatchObject({ data: { status: "ok" } });
      expect(bodies).toHaveLength(2);
      expect(bodies[1]).toBe(bodies[0]);
      expect(bodies[1]).toContain(Buffer.from(pixels).toString("latin1"));
      expect(bodies[1]).toContain('name="width"\r\n\r\n42');
    } finally {
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it.each([
    ["post", "/system/printers"],
    ["get", "/convert/crop"],
    ["post", "/convert/preview"],
    ["post", "/convert/generate"],
    ["post", "/convert/replace-color"],
    ["get", "/jobs/job-1"],
    ["post", "/session/heartbeat"],
  ])("does not add retries to %s %s", async (method, url) => {
    const { client, base } = clientWith([502]);
    await expect(client.request({ method, url })).rejects.toMatchObject({ response: { status: 502 } });
    expect(base).toHaveBeenCalledOnce();
  });

  it.each([403, 422, 429, 500])("preserves HTTP %s errors from image analysis", async (status) => {
    const { client, base } = clientWith([status]);
    await expect(client.post("/convert/auto-detect-colors", new FormData()))
      .rejects.toMatchObject({ response: { status } });
    expect(base).toHaveBeenCalledOnce();
  });

  it("stops after a second catalog failure", async () => {
    const { client, base } = clientWith([502, 504, 200]);
    await expect(client.get("/system/printers")).rejects.toMatchObject({ response: { status: 504 } });
    expect(base).toHaveBeenCalledTimes(2);
  });

  it.each(["/system/printers", path])("respects Retry-After for %s", async (url) => {
    const { client, base } = clientWith([503, 200], { "Retry-After": "30" });
    await expect(client.request({ url, method: url === path ? "post" : "get", data: body }))
      .rejects.toMatchObject({ response: { status: 503 } });
    expect(base).toHaveBeenCalledOnce();
  });

  it("does not retry an aborted image upload", async () => {
    vi.useFakeTimers();
    const { client, base } = clientWith([502, 200]);
    const controller = new AbortController();
    const outcome = client.post("/convert/crop", new FormData(), { signal: controller.signal })
      .catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(1);
    controller.abort();
    await vi.runAllTimersAsync();
    expect(axios.isCancel(await outcome)).toBe(true);
    expect(base).toHaveBeenCalledOnce();
  });
});
