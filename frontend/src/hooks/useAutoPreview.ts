import { useEffect, useRef } from "react";
import {
  fetchMaterialSolverCacheStatus,
  type MaterialSolverCacheKey,
} from "../api/materialCache";
import {
  resolveConverterSourceSelection,
  type ConverterState,
  useConverterStore,
} from "../stores/converter";
import { useSettingsStore } from "../stores/settingsStore";
import { resolveConverterSettings } from "../stores/converter/project";

type AutoPreviewSnapshot = {
  imageFile: File;
  inputKey: string;
  settingsKey: string;
};

type MaterialCacheState = Pick<
  ConverterState,
  | "source_version"
  | "selectedMaterialDirNames"
  | "materialLayerCount"
  | "materialLayerHeightMm"
>;

function resolveMaterialCacheIdentity(
  state: MaterialCacheState,
): string | null {
  if (
    state.source_version !== "material" ||
    state.selectedMaterialDirNames.length === 0
  ) {
    return null;
  }
  return JSON.stringify([
    state.selectedMaterialDirNames,
    state.materialLayerCount,
    state.materialLayerHeightMm,
    "white",
  ]);
}

function resolveMaterialCacheKey(
  state: MaterialCacheState,
): MaterialSolverCacheKey | null {
  if (resolveMaterialCacheIdentity(state) === null) {
    return null;
  }
  return {
    materialDirectoryNames: state.selectedMaterialDirNames,
    layerCount: state.materialLayerCount,
    layerHeightMm: state.materialLayerHeightMm,
    substrate: "white",
  };
}

function sameSnapshot(
  left: AutoPreviewSnapshot,
  right: AutoPreviewSnapshot,
): boolean {
  return (
    left.imageFile === right.imageFile &&
    left.inputKey === right.inputKey &&
    left.settingsKey === right.settingsKey
  );
}

/**
 * Auto-trigger preview when preconditions are met.
 * 当图片已上传、颜色来源已就绪、裁剪模态框已关闭、且当前图片已手动预览过时，
 * 后续所有会改变预览请求的参数变化都会先失效旧结果，再自动触发预览（300ms 防抖）。
 * 耗材组合、层数或层高变化后会先确认持久缓存存在；未命中时等待用户手动预览。
 *
 * 新上传的图片必须先手动点击"预览"按钮，之后参数变化才会自动触发。
 */
export function useAutoPreview(): void {
  const imageFile = useConverterStore((state) => state.imageFile);
  const cropModalOpen = useConverterStore((state) => state.cropModalOpen);
  const hasManualPreview = useConverterStore((state) => state.hasManualPreview);
  const isLoading = useConverterStore((state) => state.isLoading);
  const refreshPending = useConverterStore(
    (state) => state.previewAutoRefreshPending,
  );
  const submissionSequence = useConverterStore(
    (state) => state.previewSubmissionSequence,
  );
  const submitPreview = useConverterStore((state) => state.submitPreview);
  const invalidatePreview = useConverterStore(
    (state) => state.invalidatePreviewForAutoRefresh,
  );
  const isSourceReady = useConverterStore(
    (state) => resolveConverterSourceSelection(state).isReady,
  );
  const materialCacheIdentity = useConverterStore(
    resolveMaterialCacheIdentity,
  );
  const inputKey = useConverterStore((state) =>
    JSON.stringify([
      state.source_version,
      state.lut_name,
      state.lut_names,
      state.selectedNativeBrandKey,
      state.selectedNativeDbNames,
      state.source_version === "material" ? null : state.color_layers,
      state.source_version === "material" ? null : state.layer_height_mm,
      state.model_enable,
      state.model_only,
      state.model_threshold,
      state.model_margin,
      state.selectedMaterialDirNames,
      state.materialLayerCount,
      state.materialLayerHeightMm,
      state.materialBackingMaterialDirName,
      state.largeFormatEnabled || state.svg_hole_compensation_enabled
        ? [state.target_width_mm, state.target_height_mm]
        : null,
      state.color_mode,
      state.modeling_mode,
      state.svg_hole_compensation_enabled,
      state.svg_hole_max_area_mm2,
      state.svg_hole_max_width_mm,
      state.quantize_colors,
      state.high_precision_3d_preview,
      state.enable_cleanup,
      state.enable_outline,
      state.outline_width,
      state.hue_enable,
      state.chroma_gate,
      state.use_lut_constrained,
      state.auto_dynamic_range,
      state.largeFormatEnabled,
    ]),
  );
  const projectSettings = useConverterStore((state) => state.projectSettings);
  const settingsKey = useSettingsStore((state) => {
    const settings = resolveConverterSettings({ projectSettings }, state);
    return JSON.stringify([settings.svgPixelsPerMm, settings.theme, settings.enableSolverCacheGridSelection, settings.solverCacheGridResolution]);
  });

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastTriggeredRef = useRef<AutoPreviewSnapshot | null>(null);
  const lastSubmissionSequenceRef = useRef(submissionSequence);

  useEffect(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }

    if (!imageFile || cropModalOpen) {
      return;
    }

    const currentSnapshot: AutoPreviewSnapshot = {
      imageFile,
      inputKey,
      settingsKey,
    };
    const previousSnapshot = lastTriggeredRef.current;
    const submissionStarted =
      lastSubmissionSequenceRef.current !== submissionSequence;
    lastSubmissionSequenceRef.current = submissionSequence;
    const scheduleRefresh = (requiresMaterialCachePreflight = false) => {
      let cancelled = false;
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        void (async () => {
          const scheduledState = useConverterStore.getState();
          if (
            !scheduledState.previewAutoRefreshPending ||
            scheduledState.isLoading
          ) {
            return;
          }
          const scheduledRevision = scheduledState.previewRequestRevision;

          if (requiresMaterialCachePreflight) {
            const cacheKey = resolveMaterialCacheKey(scheduledState);
            if (
              cacheKey === null ||
              resolveMaterialCacheIdentity(scheduledState) !==
                materialCacheIdentity
            ) {
              return;
            }
            const settings = resolveConverterSettings(scheduledState, useSettingsStore.getState());
            const gridResolution = settings.enableSolverCacheGridSelection
              ? settings.solverCacheGridResolution
              : undefined;
            let cacheAvailable = false;
            try {
              const status = await fetchMaterialSolverCacheStatus(cacheKey, {
                gridResolution,
              });
              cacheAvailable = status.cached;
            } catch {
              cacheAvailable = false;
            }

            const latest = useConverterStore.getState();
            if (
              cancelled ||
              latest.imageFile !== currentSnapshot.imageFile ||
              latest.previewRequestRevision !== scheduledRevision ||
              latest.isLoading ||
              !latest.previewAutoRefreshPending ||
              resolveMaterialCacheIdentity(latest) !== materialCacheIdentity
            ) {
              return;
            }
            if (!cacheAvailable) {
              // The new cache key has no persisted cache, so stop this
              // refresh without discarding the preview baseline. Keeping the
              // baseline lets a later cache-key change run its own preflight.
              // 新缓存键未命中时只阻止本次刷新；保留预览基线，后续切换到
              // 其他缓存键时仍会重新检查，而不是永久失去自动预览资格。
              lastTriggeredRef.current = currentSnapshot;
              useConverterStore.setState({
                hasManualPreview: true,
                previewAutoRefreshPending: false,
              });
              return;
            }
          }

          const latest = useConverterStore.getState();
          if (
            cancelled ||
            !latest.previewAutoRefreshPending ||
            latest.isLoading
          ) {
            return;
          }
          lastTriggeredRef.current = currentSnapshot;
          void submitPreview();
        })();
      }, 300);

      return () => {
        cancelled = true;
        if (timerRef.current !== null) {
          clearTimeout(timerRef.current);
          timerRef.current = null;
        }
      };
    };

    // A manual click (or the auto timer itself) owns the current snapshot.
    // Seed it even when a mocked/fast response finishes before this effect.
    // 手动点击或自动定时器已认领当前参数；即使响应极快也不能再重复提交。
    if (submissionStarted || isLoading) {
      lastTriggeredRef.current = currentSnapshot;
      return;
    }

    // A store-owned pending refresh survives A→B→A and hook remounts. It is
    // intentionally checked before sameSnapshot: identical parameters do not
    // make an already-cleared result valid again.
    // pending 先于参数相等判断：参数改回 A，不代表被清空的 A 结果仍然有效。
    if (refreshPending) {
      if (!isSourceReady) {
        return;
      }
      // Material cache-key setters clear the manual baseline while preserving
      // refresh ownership. Gate only that path; ordinary input changes keep
      // the established baseline and retain the existing automatic behavior.
      // 耗材缓存键 setter 会清除手动基线但保留刷新资格；仅该路径先查持久缓存。
      return scheduleRefresh(
        !hasManualPreview && materialCacheIdentity !== null,
      );
    }

    if (!hasManualPreview) {
      return;
    }

    // Seed an already-established result on initial mount without submitting.
    if (previousSnapshot === null) {
      lastTriggeredRef.current = currentSnapshot;
      return;
    }

    if (sameSnapshot(previousSnapshot, currentSnapshot)) {
      return;
    }

    // Do this before the debounce so an old 2D/3D/session can never appear
    // to represent the newly-selected parameters while regeneration waits.
    // 防抖等待期间立即隐藏旧 2D/3D/session，避免旧结果冒充新参数结果。
    invalidatePreview();

    if (!isSourceReady) {
      return;
    }

    return scheduleRefresh();
  }, [
    cropModalOpen,
    hasManualPreview,
    imageFile,
    inputKey,
    invalidatePreview,
    isLoading,
    isSourceReady,
    materialCacheIdentity,
    refreshPending,
    settingsKey,
    submissionSequence,
    submitPreview,
  ]);
}
