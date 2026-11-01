import { describe, expect, it, vi } from "vitest";
import axios, { AxiosHeaders, type AxiosAdapter, type AxiosResponse } from "axios";
import { createAsyncJobAdapter } from "../asyncJobAdapter";
import { createServer } from "node:http";
import { once } from "node:events";

function res(status: number, data: unknown, headers: Record<string, string> = {}): AxiosResponse {
  return { status, statusText: "", data, headers, config: {} as never, request: {} };
}

function clientWith(responses: AxiosResponse[]) {
  const calls: { method?: string; url?: string; async?: unknown }[] = [];
  const base: AxiosAdapter = vi.fn(async (config) => {
    calls.push({
      method: config.method,
      url: config.url,
      async: AxiosHeaders.from(config.headers).get("X-Lumina-Async"),
    });
    const next = responses.shift();
    if (!next) throw new Error("unexpected request");
    return { ...next, config };
  });
  const client = axios.create({ baseURL: "/api", adapter: createAsyncJobAdapter(base) });
  return { client, calls };
}

describe("async job adapter", () => {
  it("passes quick responses straight through", async () => {
    const { client, calls } = clientWith([res(200, { ok: true })]);
    const r = await client.post("/convert/preview", { a: 1 });
    expect(r.data).toEqual({ ok: true });
    expect(calls).toEqual([{ method: "post", url: "/convert/preview", async: "1" }]);
  });

  it("polls a 202 job until the original response arrives", async () => {
    const { client, calls } = clientWith([
      res(202, { status: "running", job_id: "j1" }, { "x-lumina-job": "j1" }),
      res(202, { status: "running", job_id: "j1" }, { "x-lumina-job": "j1" }),
      res(200, { session_id: "s" }),
    ]);
    const r = await client.post("/convert/generate", {});
    expect(r.data).toEqual({ session_id: "s" });
    expect(r.config.url).toBe("/convert/generate");
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "post /convert/generate",
      "get /jobs/j1",
      "get /jobs/j1",
    ]);
  });

  it("rejects with the original config when the job ends in an error", async () => {
    const { client } = clientWith([
      res(202, '{"status":"running","job_id":"j2"}'),
      res(422, { detail: "bad" }),
    ]);
    const error = await client.post("/convert/generate", {}).catch((e) => e);
    expect(axios.isAxiosError(error)).toBe(true);
    expect(error.response.status).toBe(422);
    expect(error.config.url).toBe("/convert/generate");
  });

  it("leaves GET requests alone", async () => {
    const { client, calls } = clientWith([res(200, [])]);
    await client.get("/lut/list");
    expect(calls[0].async).toBeUndefined();
  });

  it.each([
    ["post", "/settings"],
    ["put", "/materials/one"],
    ["patch", "/materials/one"],
    ["delete", "/sessions/one"],
    ["post", "/convert/export-materials"],
  ])("leaves unrelated %s %s requests on the original transport", async (method, url) => {
    const { client, calls } = clientWith([res(200, { ok: true })]);
    await client.request({ method, url });
    expect(calls).toEqual([{ method, url, async: undefined }]);
  });

  it.each(["signal", "cancelToken"])("sends cancellation over real XHR after %s is cancelled", async (kind) => {
    const methods: string[] = [];
    let polling!: () => void;
    const pollStarted = new Promise<void>((resolve) => { polling = resolve; });
    const server = createServer((request, response) => {
      response.setHeader("Access-Control-Allow-Origin", "*");
      response.setHeader("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS");
      response.setHeader("Access-Control-Allow-Headers", "Content-Type, X-Lumina-Async");
      if (request.method === "OPTIONS") {
        response.writeHead(204).end();
        return;
      }
      methods.push(request.method!);
      if (request.method === "GET") {
        polling();
        return; // Keep the poll open until the client cancels it.
      }
      response.setHeader("Content-Type", "application/json");
      if (request.method === "POST") {
        response.writeHead(202).end(JSON.stringify({ job_id: "j1" }));
      } else {
        response.end(JSON.stringify({ status: "cancelled" }));
      }
    });
    server.listen(0, "127.0.0.1");
    await once(server, "listening");
    const address = server.address() as { port: number };
    const client = axios.create({
      baseURL: `http://127.0.0.1:${address.port}/api`,
      adapter: createAsyncJobAdapter(axios.getAdapter("xhr")),
    });
    const controller = new AbortController();
    const source = axios.CancelToken.source();
    try {
      const outcome = client.post("/convert/preview", {}, {
        ...(kind === "signal" ? { signal: controller.signal } : { cancelToken: source.token }),
      }).catch((error: unknown) => error);
      await pollStarted;
      if (kind === "signal") controller.abort();
      else source.cancel();
      expect(axios.isCancel(await outcome)).toBe(true);
      await vi.waitFor(() => expect(methods).toContain("DELETE"), { timeout: 1000 });
      expect(methods.filter((method) => method === "POST")).toHaveLength(1);
    } finally {
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
});
