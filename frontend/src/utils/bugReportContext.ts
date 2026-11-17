import type {
  BugReportContextPayload,
  FinalArtifactRef,
  OriginalImageRef,
  WorkshopBugReportContext,
} from "../api/feedback";
import { useActionHistoryStore } from "../stores/actionHistoryStore";
import {
  resolveBugReportOriginalImageFile,
  useConverterStore,
} from "../stores/converter";
import { useSettingsStore } from "../stores/settingsStore";
import { externalSpoolMaterial } from "../stores/converter/nativeMaterialSelection";
import { useSingleStageStore } from "../stores/singleStageStore";
import { useExtractorStore } from "../stores/extractorStore";
import { useCalibrationStore } from "../stores/calibrationStore";
import { useVectorizerStore } from "../stores/vectorizerStore";
import { useFiveColorStore } from "../stores/fiveColorStore";
import { useLutManagerStore } from "../stores/lutManagerStore";
import { useLutCompareStore } from "../stores/lutCompareStore";
import { useLutDetailsStore } from "../stores/lutDetailsStore";
import { useSlicerStore } from "../stores/slicerStore";
import { useEyedropperStore } from "../stores/eyedropperStore";
import { useTutorialStore } from "../stores/tutorialStore";
import { useErrorTicketPromptStore } from "../stores/errorTicketPromptStore";
import { useWidgetStore } from "../stores/widgetStore";
import { useWorkshopStore } from "../workshop/store";
import { buildAdvancedParams } from "./advancedParamsBuilder";
import { getRecentClientLogs, serializeDiagnosticValue } from "./clientLog";
import { resolveVectorPreviewRenderer } from "./vectorPreviewRenderer";
import { getFeedbackSources, resolveSourceFile } from "./sourceFileOrigins";

declare const __LUMINA_VERSION__: string | undefined;

/**
 * Best-effort shape of the converter generation artifact. The converter
 * store tracks ``downloadUrl`` (typically ``/api/files/<file_id>``) after a
 * successful ``convertGenerate``. The backend resolves this attachment
 * through FileRegistry; paths in the full state are diagnostic metadata.
 *
 * 最近一次生成的产物引用：converter store 在生成成功后写入 downloadUrl。
 * 后端通过 FileRegistry 解析附件；完整状态中的磁盘路径仅作为诊断信息。
 */
function deriveFinalArtifact(isConverterActive: boolean): FinalArtifactRef | null {
  if (!isConverterActive) {
    return null;
  }
  const converter = useConverterStore.getState();
  const downloadUrl = converter.downloadUrl ?? null;
  if (!downloadUrl) {
    return null;
  }
  const artifactType: FinalArtifactRef["artifact_type"] = converter.largeFormatEnabled
    || (converter.separate_backing && converter.backingOutput === "separate_project")
    ? "zip"
    : downloadUrl.toLowerCase().includes(".zip")
      ? "zip"
      : "3mf";
  return {
    session_id: converter.sessionId ?? null,
    download_url: downloadUrl,
    artifact_type: artifactType,
    source: "converter",
  };
}

/**
 * Reference to the source image the user uploaded in the currently active
 * workstream. The JSON contains identifying metadata only. Eligible
 * single-image Converter reports send exact bytes separately as multipart;
 * the backend retains FileRegistry/SessionStore lookup as a fallback.
 *
 * 指向当前活动工作流中用户上传的原图的引用；JSON 只带元信息。
 * 符合条件的单图 Converter 会用 multipart 另行发送原始字节，后端仍保留
 * FileRegistry/SessionStore 降级。
 */
function deriveOriginalImageRef(
  isConverterActive: boolean,
  converterSessionId: string | null,
  imageFile: File | null,
  batchMode: boolean,
  batchFileCount: number,
): OriginalImageRef | null {
  if (!isConverterActive) {
    return null;
  }
  if (!batchMode && batchFileCount === 0 && imageFile) {
    return {
      session_id: converterSessionId,
      filename: imageFile.name || null,
      source: "converter",
    };
  }
  return converterSessionId
    ? {
        session_id: converterSessionId,
        filename: null,
        source: "converter",
      }
    : null;
}

/** Return the exact source file for the active single-image Converter flow.
 *
 * 返回当前单图 Converter 工作流的原始 File；批处理或其他标签页返回 null。
 */
export function collectBugReportOriginalImage(): File | null {
  const widget = useWidgetStore.getState();
  const converter = useConverterStore.getState();
  if (
    widget.activeTab !== "converter" ||
    converter.batchMode ||
    converter.batchFiles.length > 0
  ) {
    return null;
  }
  return resolveBugReportOriginalImageFile(converter.imageFile);
}

/** Collect every source still held by the workflow stores, before session cleanup.
 * 在会话清理前收集工作流保留的全部源文件。
 */
export function collectBugReportSourceFiles(): File[] {
  const converter = useConverterStore.getState();
  const singleStage = useSingleStageStore.getState();
  const files = [
    ...getFeedbackSources(), converter.imageFile, converter.modelSurfaceFile,
    converter.heightmapFile, ...converter.batchFiles,
    singleStage.datasetFile, singleStage.whiteImageFile, singleStage.blackImageFile,
    useExtractorStore.getState().imageFile, useVectorizerStore.getState().imageFile,
  ];
  const available = files.filter((file): file is File => file instanceof File);
  return [...new Set(available.flatMap((file) => [resolveSourceFile(file)!, file]))];
}

function captureWorkflowState(state: object): unknown {
  return serializeDiagnosticValue(Object.fromEntries(Object.entries(state).filter(([, value]) => typeof value !== "function")));
}

function deriveWorkshopContext(
  isWorkshopActive: boolean,
): WorkshopBugReportContext | null {
  if (!isWorkshopActive) {
    return null;
  }
  const workshop = useWorkshopStore.getState();
  const diagnostics = workshop.diagnostics;
  if (!workshop.activeModule) {
    return null;
  }
  const rawErrorCode = diagnostics?.errorCode ?? null;
  const errorCode =
    rawErrorCode === null ||
    /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(rawErrorCode)
      ? rawErrorCode
      : null;
  return {
    module_id: workshop.activeModule.moduleId,
    module_version: workshop.activeModule.version,
    install_source:
      workshop.activeRuntimeContext?.installSource ?? "unknown",
    audit_status:
      workshop.activeRuntimeContext?.auditStatus ?? "unknown",
    runtime_mode: workshop.runtimeMode,
    error_code: errorCode,
  };
}

export function collectBugReportContext(): BugReportContextPayload {
  const converter = useConverterStore.getState();
  const singleStage = useSingleStageStore.getState();
  const settings = useSettingsStore.getState();
  const widget = useWidgetStore.getState();

  // Eagerly merge any sessionStorage-persisted entries so a page refresh
  // between the bug happening and the user clicking "Report" still ships the
  // complete action history. ``loadPersistedHistory`` is idempotent and
  // swallow-safe so calling it here is zero-risk.
  // 在合并上下文前显式加载持久化的历史，确保刷新页面后仍能保留现场。
  useActionHistoryStore.getState().loadPersistedHistory();
  const actionExport = useActionHistoryStore.getState().exportForReport();

  // Prefer the active workstream's live store value over the persisted
  // ``settings.lastColorMode`` / ``settings.lastLutName`` preference.
  // The settings fields only change on explicit persist events, so they
  // lag in-session switches (e.g. user is working in 8-Color Max on the
  // converter tab while settings still hold the 4-Color RYBW default,
  // making the bug report misleading). For ``activeTab === "converter"``
  // we read directly from the converter store; the single-stage
  // workstream does not own these fields, so we fall back to the
  // settings preference there for backwards compatibility.
  // 优先读取当前激活工作流 store 中的实时值，而不是仅在显式持久化时才更新
  // 的 settings.lastColorMode / lastLutName。后者会滞后于会话内切换
  // （例如用户在 converter tab 切到 8-Color Max，但 settings 仍是默认的
  // 4-Color RYBW，导致 bug 反馈里 color_mode 误导）。当 activeTab 为
  // "converter" 时直接读 converter store；单阶段工作流不维护这两个字段，
  // 回落到 settings 偏好以保持向后兼容。
  const isConverterActive = widget.activeTab === "converter";
  const spool = isConverterActive ? externalSpoolMaterial(converter, settings) : undefined;
  const isWorkshopActive = widget.activeTab === "workshop";
  const sourceVersion = isConverterActive ? converter.source_version ?? null : null;
  const isMaterialSource = sourceVersion === "material";
  const isNativeSource = sourceVersion === "native";
  const colorMode = isConverterActive
    ? (isMaterialSource ? null : converter.color_mode || null)
    : settings.lastColorMode || null;
  const lutName = isConverterActive
    ? (isMaterialSource ? null : converter.lut_name || null)
    : settings.lastLutName || null;
  const lutNames =
    isConverterActive && sourceVersion === "legacy"
      ? [...converter.lut_names]
      : null;
  const vectorPreviewRenderer = isConverterActive
    ? resolveVectorPreviewRenderer(
        converter,
        settings.enableSmoothVectorPreview,
      )
    : null;
  const originalImageFile = resolveBugReportOriginalImageFile(converter.imageFile);

  return {
    url: typeof window !== "undefined" ? window.location.href : "",
    user_agent: typeof navigator !== "undefined" ? navigator.userAgent : "",
    screen_width: typeof window !== "undefined" ? window.innerWidth : 0,
    screen_height: typeof window !== "undefined" ? window.innerHeight : 0,
    device_pixel_ratio: typeof window !== "undefined" ? window.devicePixelRatio : 1,
    app_version: typeof __LUMINA_VERSION__ === "string" ? __LUMINA_VERSION__ : "unknown",
    language: settings.language,
    theme: settings.theme,
    active_tab: widget.activeTab,
    active_session_ids: {
      converter: converter.sessionId ?? null,
      single_stage: singleStage.sessionId ?? null,
      extractor: useExtractorStore.getState().session_id ?? null,
    },
    printer_id: settings.printerModel,
    slicer: settings.slicerSoftware,
    nozzle_size: settings.nozzleSize,
    device_profile_id: settings.deviceProfileId,
    build_plate_id: settings.buildPlateId,
    ...(spool ? { external_spool_material: spool } : {}),
    custom_3mf_template_id: settings.custom3mfTemplateId,
    color_mode: colorMode,
    lut_name: lutName,
    ...(lutNames ? { lut_names: lutNames } : {}),
    source_version: sourceVersion,
    selected_native_brand_key: isNativeSource ? converter.selectedNativeBrandKey || null : null,
    selected_native_db_names: isNativeSource ? converter.selectedNativeDbNames : [],
    selected_material_dir_names: isMaterialSource ? converter.selectedMaterialDirNames : [],
    material_layer_count: isMaterialSource ? converter.materialLayerCount : null,
    material_dynamic_layer_count_enabled: isMaterialSource
      ? converter.materialDynamicLayerCountEnabled
      : null,
    material_min_layer_count: isMaterialSource
      ? converter.materialMinLayerCount
      : null,
    material_max_layer_count: isMaterialSource
      ? converter.materialMaxLayerCount
      : null,
    material_delta_e00_tolerance: isMaterialSource
      ? settings.materialDeltaE00Tolerance
      : null,
    material_layer_height_mm: isMaterialSource ? converter.materialLayerHeightMm : null,
    material_backing_material_dir_name: isMaterialSource ? converter.materialBackingMaterialDirName : null,
    preserve_upload_filename_for_3mf:
      settings.preserveUploadFilenameFor3mf,
    enable_wipe_tower_auto_placement:
      settings.enableWipeTowerAutoPlacement,
    enable_smooth_vector_preview: settings.enableSmoothVectorPreview,
    vector_preview_renderer: vectorPreviewRenderer,
    recent_client_logs: getRecentClientLogs(),
    action_history: actionExport.history,
    session_history: actionExport.session_history,
    active_original_image_ref: deriveOriginalImageRef(
      isConverterActive,
      converter.sessionId ?? null,
      originalImageFile,
      converter.batchMode,
      converter.batchFiles.length,
    ),
    active_final_artifact_ref: deriveFinalArtifact(isConverterActive),
    advanced_params: buildAdvancedParams(converter, widget.activeTab, {
      externalSpoolMaterial: spool,
      maxBytes: Number.POSITIVE_INFINITY,
      svgPixelsPerMm: settings.svgPixelsPerMm,
      materialDeltaE00Tolerance: settings.materialDeltaE00Tolerance,
      enableWipeTowerAutoPlacement: settings.enableWipeTowerAutoPlacement,
    }),
    workshop: deriveWorkshopContext(isWorkshopActive),
    source_file_ids: [...new Set([
      converter.modelSurfaceModelFileId,
      useExtractorStore.getState().calibratedFullFileId,
      useExtractorStore.getState().previousCalibratedFullFileId,
      singleStage.whiteColorcheckerFileId, singleStage.blackColorcheckerFileId,
      singleStage.pendingColorcheckerFileId,
    ].filter((value): value is string => typeof value === "string" && value.length > 0))],
    source_lut_names: [...new Set([
      converter.lut_name, ...converter.lut_names, settings.lastLutName,
      useFiveColorStore.getState().lutName,
      useLutManagerStore.getState().primaryName, ...useLutManagerStore.getState().secondaryNames,
      useLutCompareStore.getState().lutAName, useLutCompareStore.getState().lutBName,
      useLutDetailsStore.getState().selectedLutName, useLutDetailsStore.getState().loadedLutName,
    ].filter((value) => value.length > 0))],
    source_material_dir_names: [...new Set([
      ...converter.selectedMaterialDirNames, converter.materialBackingMaterialDirName,
    ].filter((value): value is string => typeof value === "string" && value.length > 0))],
    workflow_state: {
      converter: captureWorkflowState(converter), single_stage: captureWorkflowState(singleStage),
      settings: captureWorkflowState(settings), extractor: captureWorkflowState(useExtractorStore.getState()),
      calibration: captureWorkflowState(useCalibrationStore.getState()), vectorizer: captureWorkflowState(useVectorizerStore.getState()),
      workshop: captureWorkflowState(useWorkshopStore.getState()),
      five_color: captureWorkflowState(useFiveColorStore.getState()),
      lut_manager: captureWorkflowState(useLutManagerStore.getState()),
      lut_compare: captureWorkflowState(useLutCompareStore.getState()),
      lut_details: captureWorkflowState(useLutDetailsStore.getState()),
      slicer: captureWorkflowState(useSlicerStore.getState()),
      widget: captureWorkflowState(widget),
      eyedropper: captureWorkflowState(useEyedropperStore.getState()),
      tutorial: captureWorkflowState(useTutorialStore.getState()),
      error_prompt: captureWorkflowState(useErrorTicketPromptStore.getState()),
    },
  };
}
