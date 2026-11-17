/**
 * Bootstrap hook wiring the action-history store to existing Zustand stores.
 * 把操作历史 store 与现有 Zustand store 连线的启动 hook。
 *
 * Keeps the action-history store blissfully unaware of domain-specific
 * stores (converter / widget / settings) by installing a snapshot reader +
 * change subscriptions here, so the store itself stays a reusable neutral
 * module that test code can drive directly.
 *
 * 通过在这里注入 snapshotReader 与订阅回调，让操作历史 store 保持与具体
 * 业务 store（converter / widget / settings）的解耦，便于单测独立驱动。
 *
 * Injection points derived from `.kiro/specs/reproducible-bug-reports/
 * tasks.md` §1.4 (pushAction 触发点接入):
 *   - color_mode / lut_name / source_version changes → immediate push
 *   - selected_material_dir_names additions/removals → immediate push (one
 *     entry per diff; rapid back-to-back clicks coalesce at the flush layer)
 *   - material_layer_count / material_layer_height_mm commits → debounced
 *     180 ms to emulate slider ``onChangeCommitted`` semantics (we cannot
 *     touch every widget's slider component, so we observe the store value
 *     and only push after it has stopped changing)
 *   - active tab / sub-tab changes → immediate push
 *   - session id changes observed via useSessionLease (existing hook)
 *   - imageFile null→File (upload_image), previewImageUrl null→string
 *     (preview), downloadUrl null→string (generate) edge transitions →
 *     one push each (the explicit button onClick route would require
 *     editing many UI components; observing the state transition keeps
 *     the UI layer untouched while still recording the user-visible event)
 *   - explicit ``download`` button clicks are NOT tracked — the user can
 *     download the same artifact multiple times and we already record the
 *     upstream ``generate`` edge, so adding a per-click entry would add
 *     noise without improving reproducibility
 */

import { useEffect } from "react";

import { useConverterStore } from "../stores/converter";
import { externalSpoolMaterial } from "../stores/converter/nativeMaterialSelection";
import { useSettingsStore } from "../stores/settingsStore";
import { useWidgetStore } from "../stores/widgetStore";
import { useActionHistoryStore } from "../stores/actionHistoryStore";
import type { WorkflowSnapshot } from "../types/actionHistory";
import { buildAdvancedParams } from "../utils/advancedParamsBuilder";

const SLIDER_COMMIT_DEBOUNCE_MS = 180;

/**
 * Read the current workflow snapshot from the converter / widget / settings
 * stores. Called on every pushAction, so it must stay O(1) and allocation-light.
 * 每次 pushAction 都会被调用，必须保持 O(1)、少分配。
 */
function readSnapshot(): WorkflowSnapshot {
  const converter = useConverterStore.getState();
  const widget = useWidgetStore.getState();
  const settings = useSettingsStore.getState();
  const isConverterActive = widget.activeTab === "converter";
  const isMaterial =
    isConverterActive && converter.source_version === "material";
  const isNative =
    isConverterActive && converter.source_version === "native";

  return {
    color_mode: isConverterActive
      ? isMaterial
        ? null
        : (converter.color_mode ?? null)
      : (settings.lastColorMode ?? null),
    lut_name: isConverterActive
      ? isMaterial
        ? null
        : (converter.lut_name || null)
      : (settings.lastLutName ?? null),
    source_version: isConverterActive
      ? (converter.source_version ?? null)
      : null,
    selected_native_db_names: isNative
      ? [...(converter.selectedNativeDbNames ?? [])]
      : [],
    selected_material_dir_names: isMaterial
      ? [...(converter.selectedMaterialDirNames ?? [])]
      : [],
    material_layer_count: isMaterial
      ? (converter.materialLayerCount ?? null)
      : null,
    material_layer_height_mm: isMaterial
      ? (converter.materialLayerHeightMm ?? null)
      : null,
    material_backing_material_dir_name: isMaterial
      ? (converter.materialBackingMaterialDirName ?? null)
      : null,
    active_tab: widget.activeTab ?? "unknown",
    advanced_params: buildAdvancedParams(converter, widget.activeTab, {
      externalSpoolMaterial: isConverterActive ? externalSpoolMaterial(converter, settings) : undefined,
      maxBytes: Number.POSITIVE_INFINITY,
      svgPixelsPerMm: settings.svgPixelsPerMm,
      materialDeltaE00Tolerance: settings.materialDeltaE00Tolerance,
      enableWipeTowerAutoPlacement: settings.enableWipeTowerAutoPlacement,
    }),
  };
}

/**
 * Install the snapshot reader and wire subscriptions. Idempotent: safe to
 * call multiple times; the returned cleanup removes subscriptions.
 * 安装快照读取器并挂订阅；幂等，返回的 cleanup 会解除订阅。
 */
function installActionHistoryBridge(): () => void {
  const { setSnapshotReader, pushAction, loadPersistedHistory } =
    useActionHistoryStore.getState();
  setSnapshotReader(readSnapshot);
  // Pull any persisted history eagerly so a crash-induced refresh keeps the
  // pre-crash action log available for the next bug report submission.
  // 立即拉取持久化历史，避免崩溃刷新后丢失现场。
  loadPersistedHistory();

  // --- Converter store subscriptions ---
  // 订阅 converter 关键字段的变化；Zustand v4 subscribe 第三参数传 equalityFn。
  const unsubColor = useConverterStore.subscribe(
    (s) => s.color_mode,
    (next, prev) => {
      if (next === prev) return;
      pushAction({
        action_type: "color_mode_change",
        changed_fields: { color_mode: { from: prev, to: next } },
      });
    },
  );
  const unsubLut = useConverterStore.subscribe(
    (s) => s.lut_name,
    (next, prev) => {
      if (next === prev) return;
      pushAction({
        action_type: "lut_change",
        changed_fields: { lut_name: { from: prev, to: next } },
      });
    },
  );
  const unsubSource = useConverterStore.subscribe(
    (s) => s.source_version,
    (next, prev) => {
      if (next === prev) return;
      pushAction({
        action_type: "source_version_change",
        changed_fields: { source_version: { from: prev, to: next } },
      });
    },
  );
  const unsubMaterials = useConverterStore.subscribe(
    (s) => s.selectedMaterialDirNames,
    (next, prev) => {
      if (arraysShallowEqual(next, prev)) return;
      pushAction({
        action_type: "material_selection_change",
        changed_fields: {
          selected_material_dir_names: { from: prev ?? [], to: next ?? [] },
        },
      });
    },
  );

  // --- Advanced-param subscriptions ---
  // Track feature toggles and source-SVG settings that change the generation
  // output (relief / outline / cloisonne / fridge magnet / puzzle / large
  // format). Each toggle flip is recorded as its own ``advanced_param_change``
  // entry so a bug report can show the exact sequence of feature enables
  // and disables. Batched updates (e.g. recipe import) naturally produce one
  // entry per changed field because Zustand's subscribeWithSelector fires
  // once per selector whose value actually changed.
  // 订阅会改变生成结果的开关和 SVG 参数；每次修改独立成一条 advanced_param_change
  // 记录，批量更新（如预设导入）按字段各自产生一条。
  const TRACKED_ADVANCED_PARAMS = [
    "enable_relief",
    "enable_outline",
    "enable_cloisonne",
    "enable_fridge_magnet",
    "high_precision_3d_preview",
    "puzzleEnabled",
    "largeFormatEnabled",
    "svg_hole_compensation_enabled",
    "svg_hole_max_area_mm2",
    "svg_hole_max_width_mm",
  ] as const;
  const unsubToggles = TRACKED_ADVANCED_PARAMS.map((field) =>
    useConverterStore.subscribe(
      (s) => s[field],
      (next, prev) => {
        if (next === prev) return;
        pushAction({
          action_type: "advanced_param_change",
          changed_fields: { [field]: { from: prev, to: next } },
        });
      },
    ),
  );

  // --- Slider commit emulation ---
  // Slider widgets emit ``onChange`` every frame; the spec wants commits
  // only. We observe the store value and push after a short quiescent
  // window. During the quiescent window rapid value changes collapse into
  // one entry carrying the final value.
  // 滑条每帧都会 onChange；此处通过静默窗口模拟 onChangeCommitted，
  // 快速拖动会合并为一条记录、记录最终值。
  let layerCountTimer: number | null = null;
  let layerCountInitial: number | null = null;
  const unsubLayerCount = useConverterStore.subscribe(
    (s) => s.materialLayerCount,
    (next, prev) => {
      if (next === prev) return;
      if (layerCountTimer == null) {
        layerCountInitial = prev;
      } else {
        window.clearTimeout(layerCountTimer);
      }
      layerCountTimer = window.setTimeout(() => {
        pushAction({
          action_type: "material_param_commit",
          changed_fields: {
            material_layer_count: { from: layerCountInitial, to: next },
          },
        });
        layerCountTimer = null;
        layerCountInitial = null;
      }, SLIDER_COMMIT_DEBOUNCE_MS);
    },
  );

  let layerHeightTimer: number | null = null;
  let layerHeightInitial: number | null = null;
  const unsubLayerHeight = useConverterStore.subscribe(
    (s) => s.materialLayerHeightMm,
    (next, prev) => {
      if (next === prev) return;
      if (layerHeightTimer == null) {
        layerHeightInitial = prev;
      } else {
        window.clearTimeout(layerHeightTimer);
      }
      layerHeightTimer = window.setTimeout(() => {
        pushAction({
          action_type: "material_param_commit",
          changed_fields: {
            material_layer_height_mm: { from: layerHeightInitial, to: next },
          },
        });
        layerHeightTimer = null;
        layerHeightInitial = null;
      }, SLIDER_COMMIT_DEBOUNCE_MS);
    },
  );

  // --- Widget store (tab / sub-tab) ---
  const unsubTab = useWidgetStore.subscribe(
    (s) => s.activeTab,
    (next, prev) => {
      if (next === prev) return;
      pushAction({
        action_type: "switch_tab",
        changed_fields: { active_tab: { from: prev, to: next } },
      });
    },
  );
  const unsubSubTab = useWidgetStore.subscribe(
    (s) => s.activeConverterSubTab,
    (next, prev) => {
      if (next === prev) return;
      pushAction({
        action_type: "switch_subtab",
        changed_fields: {
          active_converter_sub_tab: { from: prev, to: next },
        },
      });
    },
  );

  // --- Upload / preview / generate transitions ---
  // We observe state transitions (null -> populated) instead of hooking
  // button onClicks so the UI layer stays untouched (SLO: "仅改 store
  // action 或拦截器，不改 UI 组件"). Each transition represents the
  // user-visible completion of the corresponding action:
  //   - imageFile null -> File: the user just uploaded an image.
  //   - previewImageUrl null -> string: a preview render completed.
  //   - downloadUrl null -> string: a generate run just produced a
  //     downloadable artifact (3MF / ZIP).
  //
  // 通过观察 state 从空到有的转变而不是挂按钮 onClick，保证 UI 层零改动。
  // 三个跃迁分别对应用户感知到的上传、预览、生成完成事件。
  const unsubImageFile = useConverterStore.subscribe(
    (s) => s.imageFile,
    (next, prev) => {
      if (next == null || prev === next) return;
      // null -> File or different File -> push upload_image. Replacing an
      // existing image (swap upload) also counts as a fresh upload entry.
      pushAction({
        action_type: "upload_image",
        changed_fields: {
          image_file: {
            from: prev == null ? null : (prev as File).name ?? null,
            to: (next as File).name ?? null,
          },
        },
      });
    },
  );
  const unsubPreviewUrl = useConverterStore.subscribe(
    (s) => s.previewImageUrl,
    (next, prev) => {
      if (!next || next === prev) return;
      // Only the falsy -> truthy edge counts as a preview completion; a
      // truthy -> truthy replacement means we already logged the original.
      if (prev) return;
      pushAction({ action_type: "preview" });
    },
  );
  const unsubDownloadUrl = useConverterStore.subscribe(
    (s) => s.downloadUrl,
    (next, prev) => {
      if (!next || next === prev) return;
      if (prev) return;
      pushAction({ action_type: "generate" });
    },
  );

  return () => {
    unsubColor();
    unsubLut();
    unsubSource();
    unsubMaterials();
    unsubToggles.forEach((unsub) => unsub());
    unsubLayerCount();
    unsubLayerHeight();
    unsubTab();
    unsubSubTab();
    unsubImageFile();
    unsubPreviewUrl();
    unsubDownloadUrl();
    if (layerCountTimer != null) window.clearTimeout(layerCountTimer);
    if (layerHeightTimer != null) window.clearTimeout(layerHeightTimer);
  };
}

function arraysShallowEqual<T>(
  a: readonly T[] | null | undefined,
  b: readonly T[] | null | undefined,
): boolean {
  if (a === b) return true;
  if (a == null || b == null) return false;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

/**
 * Mount effect hook that installs the action-history bridge for the life
 * of the component tree (typically the top-level ``<AppContent />``).
 * 在组件生命周期内安装操作历史桥接；通常挂在顶层 AppContent。
 */
export function useActionHistoryBootstrap(): void {
  useEffect(() => {
    const cleanup = installActionHistoryBridge();
    return () => {
      cleanup();
    };
  }, []);
}
