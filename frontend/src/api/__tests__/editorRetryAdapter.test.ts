import { afterEach, describe, expect, it, vi } from "vitest";
import axios, { AxiosError, type AxiosAdapter } from "axios";
import { createServer } from "node:http";
import { once } from "node:events";
import { createEditorRetryAdapter } from "../editorRetryAdapter";

const path = "/convert/replace-colors-batch";
const body = { session_id: "session", operation_id: "edit-1", replacements: [] };

function clientWith(statuses: number[]) {
  const base: AxiosAdapter = vi.fn(async (config) => {
    const status = statuses.shift() ?? 500;
    const response = { status, statusText: "", data: {}, headers: {}, config };
    if (status >= 400) throw new AxiosError("failed", "ERR_BAD_RESPONSE", config, undefined, response);
    return response;
  });
  return { client: axios.create({ adapter: createEditorRetryAdapter(base) }), base };
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
      adapter: createEditorRetryAdapter(axios.getAdapter("xhr")),
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
