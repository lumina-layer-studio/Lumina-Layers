/**
 * Regression tests for the async segmented-GLB polling in the converter
 * store (``_pollAsyncGlb``).
 *
 * The replace-* endpoints now return ``preview_glb_url: null``; the store
 * polls ``/api/convert/glb-status/{sid}`` and writes the returned URL
 * into ``previewGlbUrl`` when the backend worker finishes. These tests
 * exercise the happy path, the error path, session swapping (older poll
 * must not overwrite the newer session) and the re-entrant token guard
 * (newer poll supersedes older one).
 * 异步 GLB 轮询的前端回归：覆盖就绪 / 失败 / 会话切换 / 新任务覆盖旧任务。
 */

import { afterEach, describe, expect, it, vi, beforeEach } from "vitest";

const { getGlbStatusMock } = vi.hoisted(() => ({
  getGlbStatusMock: vi.fn(),
}));

vi.mock("../api/converter", async () => {
  const actual =
    await vi.importActual<typeof import("../api/converter")>(
      "../api/converter",
    );
  return {
    ...actual,
    getGlbStatus: getGlbStatusMock,
  };
});

// Silence the structured client-log POST so tests don't print noise.
vi.mock("../utils/clientLog", () => ({
  postClientLog: vi.fn(),
  summarizeErrorForLog: (err: unknown) =>
    err instanceof Error ? err.message : String(err),
  summarizeFileForLog: vi.fn(),
}));

import { useConverterStore } from "../stores/converter/store";

function flushAsync(timerStep = 600): Promise<void> {
  // Advance any scheduled setTimeout by one interval and drain the
  // microtask queue so the tick's async work can complete.
  // 推进一次 setTimeout 间隔并 drain microtask，触发下一轮 tick。
  vi.advanceTimersByTime(timerStep);
  return Promise.resolve().then(() => Promise.resolve());
}

describe("converter store: async GLB polling", () => {
  beforeEach(() => {
    getGlbStatusMock.mockReset();
    // Reset only the bits we touch so neighbouring tests running in
    // parallel don't get surprised by leftover state.
    // 只重置我们读写的字段，避免影响并行用例。
    useConverterStore.setState({
      sessionId: "sid-test",
      previewGlbUrl: "/api/files/stale.glb",
    });
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
  });

  it("writes the ready glb_url into previewGlbUrl and stops polling", async () => {
    getGlbStatusMock.mockResolvedValueOnce({
      session_id: "sid-test",
      status: "ready",
      glb_url: "/api/files/fresh.glb",
      job_token: "token-1",
      error: null,
      color_contours: {
        ff0000: [[[0, 0], [1, 0], [1, 1]]],
      },
    });

    useConverterStore.getState()._pollAsyncGlb();
    await flushAsync();
    // microtask drain once more to let the resolved mock chain settle
    // 再 drain 一次让 resolved mock 的链式 then 完成。
    await flushAsync(0);

    expect(getGlbStatusMock).toHaveBeenCalledWith("sid-test");
    expect(useConverterStore.getState().previewGlbUrl).toBe(
      "/api/files/fresh.glb",
    );
    expect(useConverterStore.getState().colorContours).toEqual({
      ff0000: [[[0, 0], [1, 0], [1, 1]]],
    });

    // Second advance: should not trigger another poll since we're done.
    // 再推进一次间隔，不应再发生新的请求。
    getGlbStatusMock.mockClear();
    await flushAsync();
    expect(getGlbStatusMock).not.toHaveBeenCalled();
  });

  it("keeps polling while status is pending and updates only on ready", async () => {
    getGlbStatusMock
      .mockResolvedValueOnce({
        session_id: "sid-test",
        status: "pending",
        glb_url: null,
        job_token: "token-1",
        error: null,
      })
      .mockResolvedValueOnce({
        session_id: "sid-test",
        status: "ready",
        glb_url: "/api/files/fresh.glb",
        job_token: "token-1",
        error: null,
      });

    useConverterStore.getState()._pollAsyncGlb();

    await flushAsync();
    await flushAsync(0);
    // Still stale after first pending response.
    // 第一次 pending 响应后仍是旧 URL。
    expect(useConverterStore.getState().previewGlbUrl).toBe(
      "/api/files/stale.glb",
    );

    await flushAsync();
    await flushAsync(0);
    expect(useConverterStore.getState().previewGlbUrl).toBe(
      "/api/files/fresh.glb",
    );
    expect(getGlbStatusMock).toHaveBeenCalledTimes(2);
  });

  it("stops polling when the session changes mid-flight", async () => {
    let resolveFirst: (
      value: Awaited<ReturnType<typeof getGlbStatusMock>>,
    ) => void = () => {};
    getGlbStatusMock.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveFirst = resolve;
        }),
    );

    useConverterStore.getState()._pollAsyncGlb();
    await flushAsync();
    // Simulate user loading a new image — session changes before the
    // first poll resolves.
    // 用户切换图片导致 sessionId 变动，此时 polling 已在等第一次响应。
    useConverterStore.setState({ sessionId: "sid-other" });

    resolveFirst({
      session_id: "sid-test",
      status: "ready",
      glb_url: "/api/files/should-not-apply.glb",
      job_token: "token-1",
      error: null,
    });
    await flushAsync(0);

    // previewGlbUrl must not be overwritten — it belongs to an old session.
    // 旧会话的结果不得污染新状态。
    expect(useConverterStore.getState().previewGlbUrl).toBe(
      "/api/files/stale.glb",
    );
  });

  it("logs and stops when status is error", async () => {
    getGlbStatusMock.mockResolvedValueOnce({
      session_id: "sid-test",
      status: "error",
      glb_url: null,
      job_token: "token-1",
      error: "simulated failure",
    });

    useConverterStore.getState()._pollAsyncGlb();
    await flushAsync();
    await flushAsync(0);

    expect(useConverterStore.getState().previewGlbUrl).toBe(
      "/api/files/stale.glb",
    );

    getGlbStatusMock.mockClear();
    await flushAsync();
    expect(getGlbStatusMock).not.toHaveBeenCalled();
  });

  it("newer poll supersedes the older one (re-entrant guard)", async () => {
    let resolveFirst: (
      value: Awaited<ReturnType<typeof getGlbStatusMock>>,
    ) => void = () => {};
    getGlbStatusMock
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFirst = resolve;
          }),
      )
      .mockResolvedValueOnce({
        session_id: "sid-test",
        status: "ready",
        glb_url: "/api/files/from-second-poll.glb",
        job_token: "token-2",
        error: null,
      });

    // First poll hangs on the pending promise.
    // 首次 polling 悬挂在 pending 状态。
    useConverterStore.getState()._pollAsyncGlb();
    await flushAsync();

    // Newer replace → newer poll kicks in while the old one is still
    // awaiting. The second poll resolves with a URL; the first resolves
    // later with a different URL that must be ignored by the token guard.
    // 新任务覆盖旧任务：新 polling 拿到第二个 URL 写入；旧 polling 延后
    // 才 resolve，携带的 URL 必须被 token 守护丢弃。
    useConverterStore.getState()._pollAsyncGlb();
    await flushAsync();
    await flushAsync(0);

    expect(useConverterStore.getState().previewGlbUrl).toBe(
      "/api/files/from-second-poll.glb",
    );

    // Late resolution of the older poll must NOT overwrite the newer URL.
    // 旧 polling 的迟到结果不得覆盖新的 URL。
    resolveFirst({
      session_id: "sid-test",
      status: "ready",
      glb_url: "/api/files/from-first-poll.glb",
      job_token: "token-1",
      error: null,
    });
    await flushAsync(0);

    expect(useConverterStore.getState().previewGlbUrl).toBe(
      "/api/files/from-second-poll.glb",
    );
  });

  it("recovers the existing GLB job after transient transport failures", async () => {
    vi.useFakeTimers();
    getGlbStatusMock.mockReset();
    useConverterStore.setState({ sessionId: "sid-recovery", previewGlbUrl: null });
    const unavailable = Object.assign(new Error("Backend unavailable"), {
      isAxiosError: true, code: "ERR_BAD_RESPONSE", response: { status: 502, headers: {} },
    });
    getGlbStatusMock.mockRejectedValueOnce(unavailable).mockRejectedValueOnce(unavailable)
      .mockResolvedValueOnce({ session_id: "sid-recovery", status: "pending", job_token: "same-job", glb_url: null, error: null })
      .mockResolvedValueOnce({ session_id: "sid-recovery", status: "ready", job_token: "same-job", glb_url: "/api/files/recovered.glb", error: null });
    useConverterStore.getState()._pollAsyncGlb();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(getGlbStatusMock).toHaveBeenCalledTimes(4);
    expect(getGlbStatusMock.mock.calls.every(([sid]) => sid === "sid-recovery")).toBe(true);
    expect(useConverterStore.getState().previewGlbUrl).toBe("/api/files/recovered.glb");
    vi.useRealTimers();
  });

  it("honors Retry-After before polling the same job again", async () => {
    vi.useFakeTimers();
    getGlbStatusMock.mockReset();
    useConverterStore.setState({ sessionId: "sid-rate-limited", previewGlbUrl: null });
    getGlbStatusMock.mockRejectedValueOnce(Object.assign(new Error("Retry later"), {
      isAxiosError: true, response: { status: 503, headers: { "retry-after": "3" } },
    })).mockResolvedValueOnce({ session_id: "sid-rate-limited", status: "ready", glb_url: "/api/files/recovered.glb", error: null });
    useConverterStore.getState()._pollAsyncGlb();
    await vi.advanceTimersByTimeAsync(500);
    await vi.advanceTimersByTimeAsync(2_999);
    expect(getGlbStatusMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(useConverterStore.getState().previewGlbUrl).toBe("/api/files/recovered.glb");
    vi.useRealTimers();
  });

  it("does not overflow the browser timer for a long Retry-After", async () => {
    useConverterStore.setState({ sessionId: "sid-long-retry", previewGlbUrl: null });
    getGlbStatusMock.mockRejectedValue(Object.assign(new Error("Retry later"), {
      isAxiosError: true, response: { status: 503, headers: { "Retry-After": "3000000" } },
    }));
    useConverterStore.getState()._pollAsyncGlb();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(getGlbStatusMock).toHaveBeenCalledTimes(1);
  });

  it.each([404, 401, 500])("stops status polling on terminal HTTP %s", async (status) => {
    vi.useFakeTimers();
    getGlbStatusMock.mockReset();
    useConverterStore.setState({ sessionId: "sid-terminal", previewGlbUrl: null });
    getGlbStatusMock.mockRejectedValueOnce(Object.assign(new Error("Terminal error"), {
      isAxiosError: true, response: { status, headers: {} },
    }));
    useConverterStore.getState()._pollAsyncGlb();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(getGlbStatusMock).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it("does not restart an old poll after a delayed transport error", async () => {
    vi.useFakeTimers();
    getGlbStatusMock.mockReset();
    useConverterStore.setState({ sessionId: "sid-old-poll", previewGlbUrl: null });
    let rejectOld: (error: unknown) => void = () => {};
    getGlbStatusMock.mockImplementationOnce(() => new Promise((_, reject) => { rejectOld = reject; }));
    useConverterStore.getState()._pollAsyncGlb();
    await vi.advanceTimersByTimeAsync(500);
    useConverterStore.setState({ sessionId: "sid-new-poll", previewGlbUrl: "/api/files/new.glb" });
    rejectOld(Object.assign(new Error("late network error"), { isAxiosError: true, code: "ERR_NETWORK" }));
    await vi.advanceTimersByTimeAsync(60_000);
    expect(getGlbStatusMock).toHaveBeenCalledTimes(1);
    expect(useConverterStore.getState().previewGlbUrl).toBe("/api/files/new.glb");
    vi.useRealTimers();
  });

  it("recovers a disconnected read but does not retry a cancelled one", async () => {
    vi.useFakeTimers();
    getGlbStatusMock.mockReset();
    useConverterStore.setState({ sessionId: "sid-network", previewGlbUrl: null });
    getGlbStatusMock.mockRejectedValueOnce(Object.assign(new Error("Network Error"), {
      isAxiosError: true, code: "ERR_NETWORK",
    })).mockResolvedValueOnce({ session_id: "sid-network", status: "ready", glb_url: "/api/files/network.glb", error: null });
    useConverterStore.getState()._pollAsyncGlb();
    await vi.advanceTimersByTimeAsync(2_000);
    expect(useConverterStore.getState().previewGlbUrl).toBe("/api/files/network.glb");
    getGlbStatusMock.mockReset();
    getGlbStatusMock.mockRejectedValueOnce({ isAxiosError: true, code: "ERR_CANCELED", __CANCEL__: true });
    useConverterStore.getState()._pollAsyncGlb();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(getGlbStatusMock).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });
});
