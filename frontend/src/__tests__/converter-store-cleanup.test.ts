import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const cleanupSessionFilesMock = vi.hoisted(() => vi.fn());
const fetchLayerImagesMock = vi.hoisted(() => vi.fn());
const beaconCleanupSessionFilesMock = vi.hoisted(() => vi.fn());
const convertPuzzleLayoutPreviewMock = vi.hoisted(() => vi.fn());
const closeSessionMock = vi.hoisted(() => vi.fn());

vi.mock("../api/converter", async () => {
  const actual = await vi.importActual<typeof import("../api/converter")>("../api/converter");
  return {
    ...actual,
    cleanupSessionFiles: cleanupSessionFilesMock,
    fetchLayerImages: fetchLayerImagesMock,
    beaconCleanupSessionFiles: beaconCleanupSessionFilesMock,
    convertPuzzleLayoutPreview: convertPuzzleLayoutPreviewMock,
  };
});

vi.mock("../api/session", () => ({
  closeSession: closeSessionMock,
}));

async function loadStore() {
  const mod = await import("../stores/converter");
  return mod.useConverterStore;
}

async function loadPuzzlePreviewHook() {
  const mod = await import("../hooks/usePuzzleLayoutPreview");
  return mod.usePuzzleLayoutPreview;
}

describe("converter store cleanup behavior", () => {
  type LayerImagesPayload = {
    session_id: string;
    layers: { layer_index: number; name: string; url: string }[];
  };

  type PuzzlePreviewPayload = {
    overlay_url: string;
    warnings: string[];
    grid_rows: number;
    grid_cols: number;
    piece_count: number;
    derived_piece_width_mm: number;
    derived_piece_height_mm: number;
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("expires stale previews while preserving the source, settings and final download", async () => {
    const useConverterStore = await loadStore();
    const image = new File(["original source"], "source.png", { type: "image/png" });
    useConverterStore.setState({
      sessionId: "expired", imageFile: image, imagePreviewUrl: "blob:original",
      target_width_mm: 121, hasManualPreview: true,
      previewGlbUrl: "/api/files/stale-glb", modelUrl: "/api/files/stale-model",
      previewImageUrl: "/api/files/stale-preview", previewBaseImageUrl: "/api/files/stale-base",
      originalPreviewUrl: "/api/files/stale-original",
      layerImages: [{ layer_index: 0, name: "L0", url: "/api/files/stale-layer" }],
      gradientGroupsSessionId: "expired", gradientGroups: null,
      downloadUrl: "/api/files/final-3mf", threemfDiskPath: "/output/final.3mf",
      replacement_regions: [{ quantized_hex: "112233", matched_hex: "112233", replacement_hex: "445566" }],
    });
    const revision = useConverterStore.getState().previewRequestRevision;
    useConverterStore.getState().expireSession("expired");
    expect(useConverterStore.getState()).toMatchObject({
      sessionId: null, imageFile: image, imagePreviewUrl: "blob:original", target_width_mm: 121,
      previewGlbUrl: null, modelUrl: null, previewImageUrl: null, previewBaseImageUrl: null,
      originalPreviewUrl: null, layerImages: [], gradientGroupsSessionId: null,
      downloadUrl: "/api/files/final-3mf", threemfDiskPath: "/output/final.3mf",
      previewAutoRefreshPending: false, hasManualPreview: false,
      previewRequestRevision: revision + 1,
      replacement_regions: [{ quantized_hex: "112233", matched_hex: "112233", replacement_hex: "445566" }],
    });
    expect(useConverterStore.getState().error).toBeTruthy();
    expect(closeSessionMock).not.toHaveBeenCalled();
  });

  it("ignores an expiration notification for a session already replaced", async () => {
    const useConverterStore = await loadStore();
    useConverterStore.setState({ sessionId: "new", previewGlbUrl: "/api/files/new-glb" });
    const before = useConverterStore.getState();
    before.expireSession("old");
    expect(useConverterStore.getState()).toBe(before);
  });

  it("preserves layer preview files during cleanup after download", async () => {
    const useConverterStore = await loadStore();

    useConverterStore.setState({
      sessionId: "sess-keep",
      downloadUrl: "/api/files/download-1",
      previewImageUrl: "/api/files/preview-1",
      previewBaseImageUrl: "/api/files/preview-base-1",
      originalPreviewUrl: "/api/files/original-1",
      previewGlbUrl: "/api/files/glb-1",
      puzzleOverlayUrl: "/api/files/puzzle-overlay-1",
      regionData: {
        regionId: "region-a",
        colorHex: "FF0000",
        pixelCount: 12,
        previewUrl: "/api/files/region-preview-1",
      },
      selectedRegions: [
        {
          regionId: "region-b",
          colorHex: "00FF00",
          pixelCount: 8,
          previewUrl: "/api/files/region-preview-2",
        },
      ],
      layerImages: [
        { layer_index: 0, name: "Layer 1", url: "/api/files/layer-1" },
        { layer_index: 1, name: "Layer 2", url: "/api/files/layer-2" },
      ],
    });

    useConverterStore.getState().cleanupAfterDownload();

    expect(cleanupSessionFilesMock).toHaveBeenCalledOnce();
    expect(cleanupSessionFilesMock).toHaveBeenCalledWith(
      "sess-keep",
      expect.arrayContaining([
        "download-1",
        "preview-1",
        "preview-base-1",
        "original-1",
        "glb-1",
        "puzzle-overlay-1",
        "region-preview-1",
        "region-preview-2",
        "layer-1",
        "layer-2",
      ]),
    );
  });

  it("keeps the backend session after download cleanup so color edits can continue", async () => {
    const useConverterStore = await loadStore();

    useConverterStore.setState({
      sessionId: "sess-close",
      downloadUrl: "/api/files/download-close",
      previewImageUrl: "/api/files/preview-close",
      previewBaseImageUrl: "/api/files/preview-base-close",
      originalPreviewUrl: "/api/files/original-close",
      previewGlbUrl: "/api/files/glb-close",
    });

    useConverterStore.getState().cleanupAfterDownload();

    expect(cleanupSessionFilesMock).toHaveBeenCalledWith(
      "sess-close",
      expect.arrayContaining([
        "download-close",
        "preview-close",
        "preview-base-close",
        "original-close",
        "glb-close",
      ]),
    );
    expect(closeSessionMock).not.toHaveBeenCalled();
    expect(useConverterStore.getState().sessionId).toBe("sess-close");
    expect(useConverterStore.getState().downloadUrl).toBe("/api/files/download-close");
  });

  it("preserves generated modelUrl during cleanup after slicer launch", async () => {
    const useConverterStore = await loadStore();

    useConverterStore.setState({
      sessionId: "sess-generated-glb",
      downloadUrl: "/api/files/download-generated",
      modelUrl: "/api/files/generated-glb",
      previewGlbUrl: null,
    });

    useConverterStore.getState().cleanupAfterDownload();

    expect(cleanupSessionFilesMock).toHaveBeenCalledWith(
      "sess-generated-glb",
      expect.arrayContaining(["download-generated", "generated-glb"]),
    );
    expect(closeSessionMock).not.toHaveBeenCalled();
  });

  it("ignores stale layer image responses after the session changes", async () => {
    const useConverterStore = await loadStore();
    let resolveFetch: ((value: LayerImagesPayload) => void) | undefined;

    fetchLayerImagesMock.mockImplementationOnce(
      () =>
        new Promise<LayerImagesPayload>((resolve) => {
          resolveFetch = resolve as (value: LayerImagesPayload) => void;
        }),
    );

    useConverterStore.setState({
      sessionId: "session-a",
      previewGlbUrl: "/api/files/preview-a.glb",
      layerImages: [],
      layerImagesLoading: false,
      layerImagesOpen: false,
    });

    const fetchPromise = useConverterStore.getState().fetchLayerImages();

    await Promise.resolve();
    expect(fetchLayerImagesMock).toHaveBeenCalledWith("session-a");

    useConverterStore.setState({
      sessionId: "session-b",
      previewGlbUrl: "/api/files/preview-b.glb",
      layerImages: [],
      layerImagesLoading: false,
      layerImagesOpen: false,
    });

    const fetchResolver = resolveFetch as (value: LayerImagesPayload) => void;
    if (fetchResolver) {
      fetchResolver({
        session_id: "session-a",
        layers: [{ layer_index: 0, name: "Layer stale", url: "/api/files/stale-layer" }],
      });
    }

    await fetchPromise;

    const state = useConverterStore.getState();
    expect(state.sessionId).toBe("session-b");
    expect(state.layerImages).toEqual([]);
    expect(state.layerImagesLoading).toBe(false);
    expect(state.layerImagesOpen).toBe(false);
  });

  it("ignores stale layer image responses after the preview source changes within the same session", async () => {
    const { buildLayerImagesSourceKey, useConverterStore } = await import("../stores/converter");
    let resolveFetch: ((value: LayerImagesPayload) => void) | undefined;

    fetchLayerImagesMock.mockImplementationOnce(
      () =>
        new Promise<LayerImagesPayload>((resolve) => {
          resolveFetch = resolve as (value: LayerImagesPayload) => void;
        }),
    );

    useConverterStore.setState({
      sessionId: "session-a",
      previewGlbUrl: "/api/files/preview-a.glb",
      previewImageUrl: "/api/files/preview-a.png",
      previewBaseImageUrl: "/api/files/preview-a.png",
      layerImages: [{ layer_index: 0, name: "Layer A", url: "/api/files/layer-a" }],
      layerImagesLoading: false,
      layerImagesOpen: true,
    });
    useConverterStore.setState({
      layerImagesSourceKey: buildLayerImagesSourceKey(useConverterStore.getState()),
    });

    const fetchPromise = useConverterStore.getState().fetchLayerImages();

    await Promise.resolve();
    expect(fetchLayerImagesMock).toHaveBeenCalledWith("session-a");

    useConverterStore.setState({
      previewGlbUrl: "/api/files/preview-b.glb",
    });

    const fetchResolver = resolveFetch as (value: LayerImagesPayload) => void;
    if (fetchResolver) {
      fetchResolver({
        session_id: "session-a",
        layers: [{ layer_index: 1, name: "Layer stale", url: "/api/files/stale-layer" }],
      });
    }

    await fetchPromise;

    const state = useConverterStore.getState();
    expect(state.previewGlbUrl).toBe("/api/files/preview-b.glb");
    expect(state.layerImages).toEqual([
      { layer_index: 0, name: "Layer A", url: "/api/files/layer-a" },
    ]);
    expect(state.layerImagesSourceKey).not.toBe(
      buildLayerImagesSourceKey(state),
    );
    expect(state.layerImagesLoading).toBe(false);
  });

  it("ignores stale layer image responses after the preview GLB changes within the same session", async () => {
    const useConverterStore = await loadStore();
    let resolveFetch: ((value: LayerImagesPayload) => void) | undefined;

    fetchLayerImagesMock.mockImplementationOnce(
      () =>
        new Promise<LayerImagesPayload>((resolve) => {
          resolveFetch = resolve as (value: LayerImagesPayload) => void;
        }),
    );

    useConverterStore.setState({
      sessionId: "session-a",
      previewGlbUrl: "/api/files/preview-a.glb",
      layerImages: [],
      layerImagesLoading: false,
      layerImagesOpen: false,
    });

    const fetchPromise = useConverterStore.getState().fetchLayerImages("/api/files/preview-a.glb");

    await Promise.resolve();
    expect(fetchLayerImagesMock).toHaveBeenCalledWith("session-a");

    useConverterStore.setState({
      sessionId: "session-a",
      previewGlbUrl: "/api/files/preview-b.glb",
      layerImages: [],
      layerImagesLoading: false,
      layerImagesOpen: false,
    });

    const fetchResolver = resolveFetch as (value: LayerImagesPayload) => void;
    if (fetchResolver) {
      fetchResolver({
        session_id: "session-a",
        layers: [{ layer_index: 0, name: "Layer stale", url: "/api/files/stale-layer" }],
      });
    }

    await fetchPromise;

    const state = useConverterStore.getState();
    expect(state.previewGlbUrl).toBe("/api/files/preview-b.glb");
    expect(state.layerImages).toEqual([]);
    expect(state.layerImagesLoading).toBe(false);
    expect(state.layerImagesOpen).toBe(false);
  });

  it("ignores stale puzzle overlay responses after the session changes", async () => {
    const useConverterStore = await loadStore();
    let resolvePreview: ((value: PuzzlePreviewPayload) => void) | undefined;

    convertPuzzleLayoutPreviewMock.mockImplementationOnce(
      () =>
        new Promise<PuzzlePreviewPayload>((resolve) => {
          resolvePreview = resolve as (value: PuzzlePreviewPayload) => void;
        }),
    );

    useConverterStore.setState({
      sessionId: "session-a",
      puzzleEnabled: true,
      target_height_mm: 60,
      puzzleStyle: "regular",
      puzzleSizingMode: "grid",
      pieceWidthMm: 20,
      pieceHeightMm: 20,
      puzzleRows: 2,
      puzzleCols: 3,
      targetPieceCount: 6,
      connectorStyle: "classic",
      labelsEnabled: false,
      engraveBackLabels: false,
      irregularityStrength: 0.35,
      minNeckWidthMm: 1.2,
      puzzleOverlayUrl: null,
      puzzleWarnings: [],
      puzzleResolvedRows: null,
      puzzleResolvedCols: null,
      puzzleResolvedPieceCount: null,
      puzzleDerivedPieceWidthMm: null,
      puzzleDerivedPieceHeightMm: null,
    });

    const previewPromise = useConverterStore.getState().submitPuzzleLayoutPreview();

    expect(convertPuzzleLayoutPreviewMock).toHaveBeenCalledWith(
      "session-a",
      expect.objectContaining({
        puzzle_style: "regular",
        sizing_mode: "grid",
        rows: 2,
        cols: 3,
      }),
    );

    useConverterStore.setState({
      sessionId: "session-b",
      puzzleEnabled: true,
      puzzleOverlayUrl: null,
      puzzleWarnings: [],
      puzzleResolvedRows: null,
      puzzleResolvedCols: null,
      puzzleResolvedPieceCount: null,
      puzzleDerivedPieceWidthMm: null,
      puzzleDerivedPieceHeightMm: null,
    });

    const previewResolver = resolvePreview as (value: PuzzlePreviewPayload) => void;
    if (previewResolver) {
      previewResolver({
        overlay_url: "/api/files/stale-puzzle-overlay",
        warnings: ["stale"],
        grid_rows: 2,
        grid_cols: 3,
        piece_count: 6,
        derived_piece_width_mm: 20,
        derived_piece_height_mm: 30,
      });
    }

    await previewPromise;

    const state = useConverterStore.getState();
    expect(state.sessionId).toBe("session-b");
    expect(state.puzzleOverlayUrl).toBeNull();
    expect(state.puzzleWarnings).toEqual([]);
    expect(state.puzzleResolvedRows).toBeNull();
  });

  it("does not let a stale failed puzzle request clear a newer successful overlay", async () => {
    const useConverterStore = await loadStore();
    let rejectFirst: ((reason?: unknown) => void) | undefined;
    let resolveSecond: ((value: PuzzlePreviewPayload) => void) | undefined;

    convertPuzzleLayoutPreviewMock
      .mockImplementationOnce(
        () =>
          new Promise<PuzzlePreviewPayload>((_, reject) => {
            rejectFirst = reject as (reason?: unknown) => void;
          }),
      )
      .mockImplementationOnce(
        () =>
          new Promise<PuzzlePreviewPayload>((resolve) => {
            resolveSecond = resolve as (value: PuzzlePreviewPayload) => void;
          }),
      );

    useConverterStore.setState({
      sessionId: "session-a",
      error: null,
      puzzleEnabled: true,
      target_height_mm: 60,
      puzzleStyle: "regular",
      puzzleSizingMode: "grid",
      pieceWidthMm: 20,
      pieceHeightMm: 20,
      puzzleRows: 2,
      puzzleCols: 3,
      targetPieceCount: 6,
      connectorStyle: "classic",
      labelsEnabled: false,
      engraveBackLabels: false,
      irregularityStrength: 0.35,
      minNeckWidthMm: 1.2,
      puzzleOverlayUrl: null,
      puzzleWarnings: [],
      puzzleResolvedRows: null,
      puzzleResolvedCols: null,
      puzzleResolvedPieceCount: null,
      puzzleDerivedPieceWidthMm: null,
      puzzleDerivedPieceHeightMm: null,
    });

    const firstPromise = useConverterStore.getState().submitPuzzleLayoutPreview();

    useConverterStore.setState({
      puzzleCols: 4,
    });
    const secondPromise = useConverterStore.getState().submitPuzzleLayoutPreview();

    const secondResolver = resolveSecond as (value: PuzzlePreviewPayload) => void;
    if (secondResolver) {
      secondResolver({
        overlay_url: "/api/files/fresh-puzzle-overlay",
        warnings: ["fresh"],
        grid_rows: 2,
        grid_cols: 4,
        piece_count: 8,
        derived_piece_width_mm: 15,
        derived_piece_height_mm: 30,
      });
    }
    await secondPromise;

    const firstRejecter = rejectFirst as (reason?: unknown) => void;
    if (firstRejecter) {
      firstRejecter(new Error("stale failure"));
    }
    await firstPromise;

    const state = useConverterStore.getState();
    expect(state.puzzleOverlayUrl).toBe("/api/files/fresh-puzzle-overlay");
    expect(state.puzzleWarnings).toEqual(["fresh"]);
    expect(state.puzzleResolvedCols).toBe(4);
    expect(state.error).toBeNull();
  });

  it("ignores stale puzzle overlay responses after the preview source changes", async () => {
    const useConverterStore = await loadStore();
    let resolveFirst: ((value: PuzzlePreviewPayload) => void) | undefined;
    let resolveSecond: ((value: PuzzlePreviewPayload) => void) | undefined;

    convertPuzzleLayoutPreviewMock
      .mockImplementationOnce(
        () =>
          new Promise<PuzzlePreviewPayload>((resolve) => {
            resolveFirst = resolve as (value: PuzzlePreviewPayload) => void;
          }),
      )
      .mockImplementationOnce(
        () =>
          new Promise<PuzzlePreviewPayload>((resolve) => {
            resolveSecond = resolve as (value: PuzzlePreviewPayload) => void;
          }),
      );

    useConverterStore.setState({
      sessionId: "session-source",
      previewGlbUrl: "/api/files/preview-old.glb",
      previewImageUrl: "/api/files/preview-old.png",
      previewBaseImageUrl: "/api/files/preview-old.png",
      previewPixelWidth: 600,
      previewPixelHeight: 451,
      puzzleEnabled: true,
      target_height_mm: 138.4375,
      puzzleStyle: "regular",
      puzzleSizingMode: "grid",
      pieceWidthMm: 20,
      pieceHeightMm: 20,
      puzzleRows: 3,
      puzzleCols: 3,
      targetPieceCount: 9,
      connectorStyle: "classic",
      labelsEnabled: false,
      engraveBackLabels: false,
      irregularityStrength: 0.35,
      minNeckWidthMm: 1.2,
      puzzleOverlayUrl: null,
      puzzleWarnings: [],
      puzzleResolvedRows: null,
      puzzleResolvedCols: null,
      puzzleResolvedPieceCount: null,
      puzzleDerivedPieceWidthMm: null,
      puzzleDerivedPieceHeightMm: null,
    });

    const firstPromise = useConverterStore.getState().submitPuzzleLayoutPreview();

    useConverterStore.setState({
      previewGlbUrl: "/api/files/preview-fresh.glb",
      previewImageUrl: "/api/files/preview-fresh.png",
      previewBaseImageUrl: "/api/files/preview-fresh.png",
      previewPixelWidth: 1600,
      previewPixelHeight: 887,
    });
    const secondPromise = useConverterStore.getState().submitPuzzleLayoutPreview();

    const secondResolver = resolveSecond as (value: PuzzlePreviewPayload) => void;
    if (secondResolver) {
      secondResolver({
        overlay_url: "/api/files/fresh-puzzle-overlay",
        warnings: ["fresh"],
        grid_rows: 3,
        grid_cols: 3,
        piece_count: 9,
        derived_piece_width_mm: 83.3333,
        derived_piece_height_mm: 46.1458,
      });
    }
    await secondPromise;

    const firstResolver = resolveFirst as (value: PuzzlePreviewPayload) => void;
    if (firstResolver) {
      firstResolver({
        overlay_url: "/api/files/stale-puzzle-overlay",
        warnings: ["stale"],
        grid_rows: 3,
        grid_cols: 3,
        piece_count: 9,
        derived_piece_width_mm: 20,
        derived_piece_height_mm: 20,
      });
    }
    await firstPromise;

    const state = useConverterStore.getState();
    expect(state.previewGlbUrl).toBe("/api/files/preview-fresh.glb");
    expect(state.puzzleOverlayUrl).toBe("/api/files/fresh-puzzle-overlay");
    expect(state.puzzleWarnings).toEqual(["fresh"]);
  });

  it("retries one failed puzzle preview request for the same params", async () => {
    vi.useFakeTimers();
    const useConverterStore = await loadStore();
    const usePuzzleLayoutPreview = await loadPuzzlePreviewHook();

    convertPuzzleLayoutPreviewMock
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockResolvedValueOnce({
        overlay_url: "/api/files/retried-puzzle-overlay",
        warnings: [],
        grid_rows: 2,
        grid_cols: 3,
        piece_count: 6,
        derived_piece_width_mm: 20,
        derived_piece_height_mm: 30,
      });

    useConverterStore.setState({
      sessionId: "session-retry",
      puzzleEnabled: true,
      target_height_mm: 60,
      puzzleStyle: "regular",
      puzzleSizingMode: "grid",
      pieceWidthMm: 20,
      pieceHeightMm: 20,
      puzzleRows: 2,
      puzzleCols: 3,
      targetPieceCount: 6,
      connectorStyle: "classic",
      labelsEnabled: false,
      engraveBackLabels: false,
      irregularityStrength: 0.35,
      minNeckWidthMm: 1.2,
      puzzleOverlayUrl: null,
      puzzleWarnings: [],
      puzzleResolvedRows: null,
      puzzleResolvedCols: null,
      puzzleResolvedPieceCount: null,
      puzzleDerivedPieceWidthMm: null,
      puzzleDerivedPieceHeightMm: null,
    });

    renderHook(() => usePuzzleLayoutPreview());

    await act(async () => {
      vi.advanceTimersByTime(250);
      await Promise.resolve();
    });
    expect(convertPuzzleLayoutPreviewMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(250);
      await Promise.resolve();
    });
    expect(convertPuzzleLayoutPreviewMock).toHaveBeenCalledTimes(2);

    const state = useConverterStore.getState();
    expect(state.puzzleOverlayUrl).toBe("/api/files/retried-puzzle-overlay");
    expect(state.error).toBeNull();
  });

  it("refreshes puzzle overlay when the preview GLB source changes in the same session", async () => {
    vi.useFakeTimers();
    const useConverterStore = await loadStore();
    const usePuzzleLayoutPreview = await loadPuzzlePreviewHook();

    convertPuzzleLayoutPreviewMock
      .mockResolvedValueOnce({
        overlay_url: "/api/files/old-puzzle-overlay",
        warnings: [],
        grid_rows: 3,
        grid_cols: 3,
        piece_count: 9,
        derived_piece_width_mm: 20,
        derived_piece_height_mm: 20,
      })
      .mockResolvedValueOnce({
        overlay_url: "/api/files/fresh-puzzle-overlay",
        warnings: [],
        grid_rows: 3,
        grid_cols: 3,
        piece_count: 9,
        derived_piece_width_mm: 83.3333,
        derived_piece_height_mm: 46.1458,
      });

    useConverterStore.setState({
      sessionId: "session-same",
      previewGlbUrl: "/api/files/preview-old.glb",
      previewImageUrl: "/api/files/preview-old.png",
      previewBaseImageUrl: "/api/files/preview-old.png",
      previewPixelWidth: 600,
      previewPixelHeight: 451,
      puzzleEnabled: true,
      target_height_mm: 138.4375,
      puzzleStyle: "regular",
      puzzleSizingMode: "grid",
      pieceWidthMm: 20,
      pieceHeightMm: 20,
      puzzleRows: 3,
      puzzleCols: 3,
      targetPieceCount: 9,
      connectorStyle: "classic",
      labelsEnabled: false,
      engraveBackLabels: false,
      irregularityStrength: 0.35,
      minNeckWidthMm: 1.2,
      puzzleOverlayUrl: null,
      puzzleWarnings: [],
      puzzleResolvedRows: null,
      puzzleResolvedCols: null,
      puzzleResolvedPieceCount: null,
      puzzleDerivedPieceWidthMm: null,
      puzzleDerivedPieceHeightMm: null,
    });

    renderHook(() => usePuzzleLayoutPreview());

    await act(async () => {
      vi.advanceTimersByTime(250);
      await Promise.resolve();
    });
    expect(convertPuzzleLayoutPreviewMock).toHaveBeenCalledTimes(1);
    expect(useConverterStore.getState().puzzleOverlayUrl).toBe(
      "/api/files/old-puzzle-overlay",
    );

    await act(async () => {
      useConverterStore.setState({
        previewGlbUrl: "/api/files/preview-fresh.glb",
        previewImageUrl: "/api/files/preview-fresh.png",
        previewBaseImageUrl: "/api/files/preview-fresh.png",
        previewPixelWidth: 1600,
        previewPixelHeight: 887,
      });
      await Promise.resolve();
    });

    await act(async () => {
      vi.advanceTimersByTime(250);
      await Promise.resolve();
    });

    expect(convertPuzzleLayoutPreviewMock).toHaveBeenCalledTimes(2);
    expect(useConverterStore.getState().puzzleOverlayUrl).toBe(
      "/api/files/fresh-puzzle-overlay",
    );
  });

  it("clears back-label engraving when piece labels are turned off", async () => {
    const useConverterStore = await loadStore();

    useConverterStore.setState({
      labelsEnabled: true,
      engraveBackLabels: true,
    });

    useConverterStore.getState().setLabelsEnabled(false);

    const state = useConverterStore.getState();
    expect(state.labelsEnabled).toBe(false);
    expect(state.engraveBackLabels).toBe(false);
  });

  it("keeps back-label engraving disabled even when toggled directly", async () => {
    const useConverterStore = await loadStore();

    useConverterStore.setState({
      engraveBackLabels: false,
    });

    useConverterStore.getState().setEngraveBackLabels(true);

    expect(useConverterStore.getState().engraveBackLabels).toBe(false);
  });
});
