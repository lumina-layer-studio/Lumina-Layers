// @vitest-environment jsdom

import { AxiosError } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const postClientLog = vi.hoisted(() => vi.fn());
vi.mock("../utils/clientLog", () => ({
  postClientLog,
  summarizeErrorForLog: () => ({}),
}));

import apiClient from "../api/client";
import { heartbeatSession } from "../api/session";
import { useActionHistoryStore } from "../stores/actionHistoryStore";
import { useErrorTicketPromptStore } from "../stores/errorTicketPromptStore";

const originalAdapter = apiClient.defaults.adapter;

describe("background session renewal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useErrorTicketPromptStore.getState()._resetForTests();
    apiClient.defaults.adapter = async (config) => {
      throw new AxiosError("Bad Gateway", "ERR_BAD_RESPONSE", config, undefined, {
        status: 502,
        statusText: "Bad Gateway",
        data: "",
        headers: { "x-request-id": "heartbeat-proxy-failure" },
        config,
      });
    };
  });

  afterEach(() => {
    apiClient.defaults.adapter = originalAdapter;
  });

  it("records a failed heartbeat without interrupting the user with a ticket prompt", async () => {
    const pushAction = vi.spyOn(useActionHistoryStore.getState(), "pushAction");
    await expect(heartbeatSession("active-session")).rejects.toBeInstanceOf(AxiosError);
    expect(postClientLog).toHaveBeenCalledWith("api: request failed", expect.anything());
    expect(pushAction).toHaveBeenCalledWith(expect.objectContaining({
      action_type: "api_error",
      error: expect.objectContaining({ path: "/session/heartbeat", status_code: 502 }),
    }));
    expect(useErrorTicketPromptStore.getState().pending).toBeNull();
    pushAction.mockRestore();
  });

  it("still offers a ticket when a user operation fails", async () => {
    await expect(apiClient.post("/convert/replace-colors-batch", {})).rejects.toBeInstanceOf(AxiosError);
    expect(useErrorTicketPromptStore.getState().pending?.path).toBe("/convert/replace-colors-batch");
  });

  it("bounds renewal requests and forwards cancellation", async () => {
    const controller = new AbortController();
    const adapter = vi.fn(async (config) => ({ status: 200, statusText: "OK", data: {}, headers: {}, config }));
    apiClient.defaults.adapter = adapter;
    await heartbeatSession("active-session", controller.signal);
    expect(adapter.mock.calls[0][0]).toMatchObject({ timeout: 15_000, signal: controller.signal });
  });
});
