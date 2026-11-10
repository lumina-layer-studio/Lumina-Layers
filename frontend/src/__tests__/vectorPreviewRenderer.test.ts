import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { rebuildRendererMock } = vi.hoisted(() => ({
  rebuildRendererMock: vi.fn(),
}));

vi.mock("../api/converter", async () => {
  const actual = await vi.importActual<typeof import("../api/converter")>(
    "../api/converter",
  );
  return {
    ...actual,
    rebuildVectorPreviewRenderer: rebuildRendererMock,
  };
});

vi.mock("../utils/clientLog", () => ({
  postClientLog: vi.fn(),
  summarizeErrorForLog: (error: unknown) => String(error),
  summarizeFileForLog: vi.fn(),
}));

import { ModelingMode } from "../api/types";
import { useVectorPreviewRenderer } from "../hooks/useVectorPreviewRenderer";
import { converterDocumentHistory, DEFAULT_STATE, useConverterStore } from "../stores/converter";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function seedEligibleSession() {
  const pollAsyncGlb = vi.fn();
  const submitPreview = vi.fn();
  useConverterStore.setState({
    ...DEFAULT_STATE,
    imageFile: new File(["<svg/>"], "smooth.svg", {
      type: "image/svg+xml",
    }),
    modeling_mode: ModelingMode.VECTOR,
    sessionId: "vector-session",
    previewImageUrl: "/api/files/preview.png",
    previewBaseImageUrl: "/api/files/preview-clean.png",
    previewGlbUrl: "/api/files/current.glb",
    modelSurfaceEnabled: false,
    largeFormatEnabled: false,
    batchPreviewItems: [],
    _pollAsyncGlb: pollAsyncGlb,
    submitPreview,
  } as never);
  converterDocumentHistory.reset();
  useConverterStore.getState().setTargetWidthMm(useConverterStore.getState().target_width_mm + 1);
  return { pollAsyncGlb, submitPreview };
}

async function flushEffects(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("useVectorPreviewRenderer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    rebuildRendererMock.mockResolvedValue({
      session_id: "vector-session",
      status: "pending",
      job_token: "renderer-token",
      glb_url: null,
      renderer: "segmented",
    });
    useConverterStore.setState({ ...DEFAULT_STATE } as never);
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
  });

  it("switches renderer in place without rebuilding the preview session", async () => {
    const { pollAsyncGlb, submitPreview } = seedEligibleSession();
    const historyBefore = converterDocumentHistory.store.getState();
    expect(historyBefore.canUndo).toBe(true);
    renderHook(() => useVectorPreviewRenderer());

    act(() => {
      useSettingsStore.getState().setEnableSmoothVectorPreview(false);
    });
    await flushEffects();

    expect(rebuildRendererMock).toHaveBeenCalledWith("vector-session", false);
    expect(pollAsyncGlb).toHaveBeenCalledTimes(1);
    expect(submitPreview).not.toHaveBeenCalled();
    expect(useConverterStore.getState()).toMatchObject({
      sessionId: "vector-session",
      previewImageUrl: "/api/files/preview.png",
      previewBaseImageUrl: "/api/files/preview-clean.png",
      previewGlbUrl: "/api/files/current.glb",
    });
    expect(converterDocumentHistory.store.getState()).toMatchObject({ position: historyBefore.position, canUndo: true });
  });

  it("accepts only the final response during rapid on-off-on changes", async () => {
    const first = deferred<{
      session_id: string;
      status: "pending";
      job_token: string;
      glb_url: null;
      renderer: "segmented";
    }>();
    rebuildRendererMock
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce({
        session_id: "vector-session",
        status: "pending",
        job_token: "new-token",
        glb_url: null,
        renderer: "vector_analytic",
      });
    const { pollAsyncGlb } = seedEligibleSession();
    renderHook(() => useVectorPreviewRenderer());

    act(() => {
      useSettingsStore.getState().setEnableSmoothVectorPreview(false);
    });
    await flushEffects();
    act(() => {
      useSettingsStore.getState().setEnableSmoothVectorPreview(true);
    });
    await flushEffects();

    expect(rebuildRendererMock).toHaveBeenCalledTimes(1);
    expect(pollAsyncGlb).not.toHaveBeenCalled();

    first.resolve({
      session_id: "vector-session",
      status: "pending",
      job_token: "old-token",
      glb_url: null,
      renderer: "segmented",
    });
    await flushEffects();

    expect(rebuildRendererMock).toHaveBeenCalledTimes(2);
    expect(rebuildRendererMock).toHaveBeenLastCalledWith(
      "vector-session",
      true,
    );
    expect(pollAsyncGlb).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["no session", { sessionId: null }],
    ["raster", {
      imageFile: new File(["png"], "raster.png", { type: "image/png" }),
      modeling_mode: ModelingMode.HIGH_FIDELITY,
    }],
    ["model surface", { modelSurfaceEnabled: true }],
    ["large format", { largeFormatEnabled: true }],
    ["batch", { batchPreviewItems: [{ url: "/api/files/batch.png" }] }],
  ])("does not rebuild for %s state", async (_label, patch) => {
    seedEligibleSession();
    useConverterStore.setState(patch as never);
    renderHook(() => useVectorPreviewRenderer());

    act(() => {
      useSettingsStore.getState().setEnableSmoothVectorPreview(false);
    });
    await flushEffects();

    expect(rebuildRendererMock).not.toHaveBeenCalled();
  });
});
