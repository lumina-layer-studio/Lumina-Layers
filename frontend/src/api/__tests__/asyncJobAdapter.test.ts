import { describe, expect, it, vi } from "vitest";
import axios, { AxiosHeaders, type AxiosAdapter, type AxiosResponse } from "axios";
import { createAsyncJobAdapter } from "../asyncJobAdapter";

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
});
