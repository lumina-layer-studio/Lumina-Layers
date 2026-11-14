import {
  GLB_STATUS_TIMEOUT_MS,
  fetchLayerImages as apiFetchLayerImages,
  getGlbStatus as apiGetGlbStatus,
  rebuildVectorPreviewRenderer as apiRebuildVectorPreviewRenderer,
} from "../../api/converter";
import axios from "axios";
import { postClientLog, summarizeErrorForLog } from "../../utils/clientLog";
import { normalizeResourceUrl } from "../../utils/resourceUrl";
import { resolveVectorPreviewRenderer } from "../../utils/vectorPreviewRenderer";
import { useSettingsStore } from "../settingsStore";
import type { ConverterActions, ConverterState } from "./types";

const DEFAULT_PUZZLE_LAYOUT_SEED = 0;

export function buildLayerImagesSourceKey(
  state: Pick<
    ConverterState,
    "sessionId" | "previewGlbUrl" | "previewBaseImageUrl" | "previewImageUrl"
  >,
): string | null {
  if (!state.sessionId) {
    return null;
  }

  return [
    state.sessionId,
    state.previewGlbUrl ?? "",
    state.previewBaseImageUrl ?? state.previewImageUrl ?? "",
  ].join("|");
}

export function buildPuzzlePreviewSourceKey(
  state: Pick<
    ConverterState,
    | "sessionId"
    | "previewGlbUrl"
    | "previewBaseImageUrl"
    | "previewImageUrl"
    | "previewPixelWidth"
    | "previewPixelHeight"
  >,
): string | null {
  if (!state.sessionId) {
    return null;
  }

  return [
    state.sessionId,
    state.previewGlbUrl ?? "",
    state.previewBaseImageUrl ?? state.previewImageUrl ?? "",
    state.previewPixelWidth ?? "",
    state.previewPixelHeight ?? "",
  ].join("|");
}

export const DEFAULT_LAYER_IMAGES_STATE = {
  layerImages: [] as { layer_index: number; name: string; url: string }[],
  layerImagesLoading: false,
  layerImagesOpen: false,
  layerImagesSourceKey: null as string | null,
};

export const DEFAULT_PUZZLE_PREVIEW_STATE = {
  puzzleOverlayUrl: null,
  puzzleWarnings: [] as string[],
  puzzleResolvedRows: null,
  puzzleResolvedCols: null,
  puzzleResolvedPieceCount: null,
  puzzleDerivedPieceWidthMm: null,
  puzzleDerivedPieceHeightMm: null,
};

export function buildPuzzlePreviewParams(
  state: Pick<
    ConverterState,
    | "target_height_mm"
    | "puzzleStyle"
    | "puzzleSizingMode"
    | "pieceWidthMm"
    | "pieceHeightMm"
    | "puzzleRows"
    | "puzzleCols"
    | "targetPieceCount"
    | "connectorStyle"
    | "labelsEnabled"
    | "engraveBackLabels"
    | "irregularityStrength"
    | "minNeckWidthMm"
  >,
) {
  return {
    target_height_mm: state.target_height_mm,
    puzzle_style: state.puzzleStyle,
    sizing_mode: state.puzzleSizingMode,
    piece_width_mm: state.pieceWidthMm,
    piece_height_mm: state.pieceHeightMm,
    rows: state.puzzleRows,
    cols: state.puzzleCols,
    target_piece_count: state.targetPieceCount,
    seed: DEFAULT_PUZZLE_LAYOUT_SEED,
    connector_style: state.connectorStyle,
    labels_enabled: state.labelsEnabled,
    engrave_back_labels: false,
    irregularity_strength: state.irregularityStrength,
    min_neck_width_mm: state.minNeckWidthMm,
  } as const;
}

// ========== Async segmented-GLB polling ==========
//
// The backend replace endpoints (replace-color, region-replace and their
// batch variants, apply-recipe-override, reset-replacements) now return
// ``preview_glb_url: null`` immediately and rebuild the segmented GLB on
// a background thread — this dropped the typical ``/region-replace``
// latency from ~45 s to ~10 s for 6 Mpix images. The frontend therefore
// has to poll ``/api/convert/glb-status/{sid}`` after every replace to
// pick up the new GLB URL once the worker finishes.
// 由于 replace 端点改为异步生成 GLB，前端需要在每次 replace 后轮询
// /glb-status，拿到新 URL 后再刷新 3D 预览（previewGlbUrl）。
const GLB_POLL_INTERVAL_MS = 500;

// Monotonic token used by every poll loop; starting a new poll or
// changing sessionId bumps this so any older loop exits on its next tick.
// 单调递增的 token：新轮询/切换 session 都会自增，旧循环下一轮检测到 token
// 变了就退出，避免多路 polling 互相覆盖 previewGlbUrl。
let _glbPollSequence = 0;

let _vectorRendererRequestSequence = 0;

let _vectorRendererRequestQueue: Promise<void> = Promise.resolve();

function glbPollRetryDelay(error: unknown, delayMs: number): number | null {
  if (!axios.isAxiosError(error) || axios.isCancel(error)) return null;
  const status = error.response?.status;
  if (status != null && ![408, 429, 502, 503, 504].includes(status)) return null;
  if (status == null && !["ERR_NETWORK", "ECONNRESET", "ECONNABORTED", "ETIMEDOUT"].includes(error.code ?? "")) return null;
  const headers = error.response?.headers ?? {};
  const value = Object.entries(headers).find(([name]) => name.toLowerCase() === "retry-after")?.[1];
  if (value != null) {
    const seconds = Number(value);
    const requestedDelay = Number.isFinite(seconds) ? seconds * 1000 : Date.parse(String(value)) - Date.now();
    // Browser timers overflow beyond a signed 32-bit delay and fire immediately.
    if (Number.isFinite(requestedDelay)) return Math.max(delayMs, Math.min(requestedDelay, 2_147_483_647));
  }
  return delayMs;
}

function _startGlbStatusPolling(
  sessionId: string,
  applyGlbResult: (
    url: string,
    colorContours?: Record<string, number[][][]> | null,
  ) => void,
  getCurrentSessionId: () => string | null,
): void {
  _glbPollSequence += 1;
  const mySeq = _glbPollSequence;
  let retryDelayMs = GLB_POLL_INTERVAL_MS;
  let retrying = false;
  const tick = async (): Promise<void> => {
    // Lost-focus guard: if a newer poll started or the user switched sessions,
    // exit silently. A local build remains pending until it completes, fails,
    // or the user starts a newer request.
    // 仅在新轮询或 session 切换时退出；本地计算持续到完成、失败或被新请求替代。
    if (_glbPollSequence !== mySeq) return;
    if (getCurrentSessionId() !== sessionId) return;

    try {
      const status = await apiGetGlbStatus(sessionId);
      // Re-check all guards after the awaited round-trip: another replace
      // may have scheduled a newer build while we waited, and its token
      // will surface via the next poll started by that replace — we must
      // not race it by writing stale state here.
      // 网络往返后再次校验，避免把中途被覆盖的旧 URL 写进 state。
      if (_glbPollSequence !== mySeq) return;
      if (getCurrentSessionId() !== sessionId) return;
      retryDelayMs = GLB_POLL_INTERVAL_MS;
      retrying = false;

      if (status.status === "ready" && status.glb_url) {
        const normalized = normalizeResourceUrl(status.glb_url);
        if (normalized) {
          applyGlbResult(normalized, status.color_contours ?? null);
        }
        return;
      }
      if (status.status === "error") {
        // GLB build failed but the 2D preview already updated; keep the
        // old 3D preview rather than surfacing a modal — the user can
        // retry via any replace action to re-trigger a build.
        // GLB 生成失败时不弹错；2D 已可用，旧 3D 继续显示，再次替换即重试。
        postClientLog("converter: glb async build failed", {
          scope: "converter",
          phase: "glb-error",
          details: { session_id: sessionId, error: status.error },
        });
        return;
      }
      // idle / pending — continue polling on next tick.
      // idle / pending 继续轮询下一轮。
      window.setTimeout(() => {
        void tick();
      }, GLB_POLL_INTERVAL_MS);
    } catch (err) {
      if (_glbPollSequence !== mySeq || getCurrentSessionId() !== sessionId) return;
      const delay = glbPollRetryDelay(err, retryDelayMs);
      if (!retrying) {
        postClientLog("converter: glb poll network error", {
          scope: "converter",
          phase: "glb-poll-error",
          details: { session_id: sessionId, error: summarizeErrorForLog(err) },
        });
      }
      // A transport interruption does not cancel the existing backend job.
      // Keep observing it; only terminal errors or owner changes end the poll.
      if (delay != null) {
        retrying = true;
        retryDelayMs = Math.min(retryDelayMs * 2, GLB_STATUS_TIMEOUT_MS);
        window.setTimeout(() => { void tick(); }, delay);
      }
    }
  };

  window.setTimeout(() => {
    void tick();
  }, GLB_POLL_INTERVAL_MS);
}

export function cancelDerivedPreviewWork(): void {
  _glbPollSequence += 1;
  _vectorRendererRequestSequence += 1;
}

export function createDerivedPreviewActions(
  set: (partial: Partial<ConverterState>) => void,
  _get: () => ConverterState & ConverterActions,
): Pick<ConverterActions, "setPreviewGlbUrl" | "_pollAsyncGlb" | "rebuildVectorPreviewRenderer" | "fetchLayerImages" | "resetLayerImages" | "setLayerImagesOpen"> {
  return {
    // --- GLB 预览 ---
    setPreviewGlbUrl: (url: string | null) => set({ previewGlbUrl: url }),
    _pollAsyncGlb: () => {
      const sid = _get().sessionId;
      if (!sid) return;
      _startGlbStatusPolling(
        sid,
        (url, colorContours) =>
          set({
            previewGlbUrl: url,
            modelUrl: null,
            ...(colorContours ? { colorContours } : {}),
          }),
        () => _get().sessionId,
      );
    },
    rebuildVectorPreviewRenderer: async (
      enableSmoothVectorPreview: boolean,
    ) => {
      const requested = _get();
      if (
        !requested.sessionId ||
        resolveVectorPreviewRenderer(
          requested,
          enableSmoothVectorPreview,
        ) === null
      ) {
        return;
      }

      const sessionId = requested.sessionId;
      const previewRevision = requested.previewRequestRevision;
      const sequence = ++_vectorRendererRequestSequence;
      const runRequest = async (): Promise<void> => {
        const beforeRequest = _get();
        if (
          sequence !== _vectorRendererRequestSequence ||
          beforeRequest.sessionId !== sessionId ||
          beforeRequest.previewRequestRevision !== previewRevision ||
          useSettingsStore.getState().enableSmoothVectorPreview !==
          enableSmoothVectorPreview
        ) {
          return;
        }
        try {
          const response = await apiRebuildVectorPreviewRenderer(
            sessionId,
            enableSmoothVectorPreview,
          );
          const latest = _get();
          if (
            sequence !== _vectorRendererRequestSequence ||
            latest.sessionId !== sessionId ||
            latest.previewRequestRevision !== previewRevision ||
            response.session_id !== sessionId ||
            useSettingsStore.getState().enableSmoothVectorPreview !==
            enableSmoothVectorPreview
          ) {
            return;
          }
          latest._pollAsyncGlb();
        } catch (error) {
          const latest = _get();
          if (
            sequence !== _vectorRendererRequestSequence ||
            latest.sessionId !== sessionId ||
            latest.previewRequestRevision !== previewRevision
          ) {
            return;
          }
          postClientLog("converter: vector renderer rebuild failed", {
            scope: "converter",
            phase: "vector-renderer-rebuild",
            details: {
              session_id: sessionId,
              error: summarizeErrorForLog(error),
            },
          });
        }
      };

      const queuedRequest = _vectorRendererRequestQueue.then(
        runRequest,
        runRequest,
      );
      _vectorRendererRequestQueue = queuedRequest.catch(() => undefined);
      await queuedRequest;
    },
    // --- 分层预览 ---
    fetchLayerImages: async (previewSourceKey) => {
      const currentState = _get();
      const requestedSourceKey =
        previewSourceKey ?? buildLayerImagesSourceKey(currentState);
      if (!currentState.sessionId || !requestedSourceKey) return;
      const requestedSessionId = currentState.sessionId;
      const shouldClearStaleLayers =
        currentState.layerImages.length > 0 &&
        currentState.layerImagesSourceKey !== requestedSourceKey;

      set({
        ...(shouldClearStaleLayers ? DEFAULT_LAYER_IMAGES_STATE : {}),
        layerImagesLoading: true,
      });
      try {
        const res = await apiFetchLayerImages(requestedSessionId);
        const latestState = _get();
        if (
          latestState.sessionId !== requestedSessionId ||
          res.session_id !== requestedSessionId ||
          buildLayerImagesSourceKey(latestState) !== requestedSourceKey
        ) {
          set({ layerImagesLoading: false });
          return;
        }
        set({
          layerImages: res.layers,
          layerImagesLoading: false,
          layerImagesOpen: true,
          layerImagesSourceKey: requestedSourceKey,
        });
      } catch (e) {
        console.error("fetchLayerImages failed:", e);
        set({ layerImagesLoading: false });
      }
    },
    resetLayerImages: () =>
      set({
        ...DEFAULT_LAYER_IMAGES_STATE,
      }),
    setLayerImagesOpen: (open: boolean) => set({ layerImagesOpen: open }),
  };
}

export function normalizeStoreResourceUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  return normalizeResourceUrl(url) ?? url ?? null;
}
