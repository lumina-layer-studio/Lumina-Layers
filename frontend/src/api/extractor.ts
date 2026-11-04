import apiClient from "./client";
import {
  createPreviewResource,
  type PreviewResourceUploadProgress,
} from "./system";
import type {
  ConfirmPaletteRequest,
  ExtractResponse,
  GradientCardMaterialBulkExportResponse,
  GradientCardMaterialBulkImportResponse,
  GradientCardMaterialDeleteResponse,
  GradientCardMaterialLibraryResponse,
  GradientCardMaterialSaveResponse,
  GradientCardMaterialUpdateResponse,
  GradientCardStageAExtractResponse,
  LutPreviewResolvedCell,
  ManualFixResponse,
  ManualOrientationLabel,
  MaterialRecipePreviewRequest,
  MaterialRecipePreviewResponse,
  MaterialRecipeSwatchRequest,
  MaterialRecipeSwatchResponse,
  SingleStageExtractResponse,
  StageAFitResponse,
} from "./types";

const COLORCHECKER_SOURCE_PREVIEW_TIMEOUT_MS = 3_600_000;

/** 提取颜色 - multipart/form-data */
export async function extractColors(
  image: File | null,
  params: {
    workspaceSessionId?: string;
    corner_points: Array<[number, number]>;
    color_mode: string;
    page: string;
    eight_color_full_export: boolean;
    offset_x: number;
    offset_y: number;
    zoom: number;
    distortion: number;
    vignette_correction: boolean;
    auto_wb: boolean;
    colorcheckerCalibratedFileId?: string | null;
    cornerPointsWidth?: number | null;
    cornerPointsHeight?: number | null;
  },
): Promise<ExtractResponse> {
  const fd = new FormData();
  if (image) {
    fd.append("image", image);
  }
  fd.append("corner_points", JSON.stringify(params.corner_points));
  if (params.workspaceSessionId) fd.append("workspace_session_id", params.workspaceSessionId);
  fd.append("color_mode", params.color_mode);
  fd.append("page", params.page);
  fd.append("eight_color_full_export", String(params.eight_color_full_export));
  fd.append("offset_x", String(params.offset_x));
  fd.append("offset_y", String(params.offset_y));
  fd.append("zoom", String(params.zoom));
  fd.append("distortion", String(params.distortion));
  fd.append("vignette_correction", String(params.vignette_correction));
  fd.append("auto_wb", String(params.auto_wb));
  if (params.colorcheckerCalibratedFileId) {
    fd.append("colorchecker_calibrated_file_id", params.colorcheckerCalibratedFileId);
  }
  if (params.cornerPointsWidth && params.cornerPointsHeight) {
    fd.append("corner_points_width", String(params.cornerPointsWidth));
    fd.append("corner_points_height", String(params.cornerPointsHeight));
  }

  const response = await apiClient.post<ExtractResponse>(
    "/extractor/extract",
    fd,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** Warp preview response (step 1) */
export interface ColorcheckerPoint {
  x: number;
  y: number;
}

export interface ColorcheckerDeltaSummary {
  mean: number | null;
  median: number | null;
  p95: number | null;
  max: number | null;
}

export interface ColorcheckerWorstPatch {
  index: number;
  label: string;
  deltaE00: number;
  referenceSrgb?: number[] | null;
  correctedSrgb?: number[] | null;
}

export interface ColorcheckerLuminancePoint {
  index: number;
  label: string;
  reference: number | null;
  captured: number | null;
  normalized: number | null;
  corrected: number | null;
  fitUsed: boolean;
  grayPatch: boolean;
}

export interface ColorcheckerReferencePatch {
  index: number;
  label?: string;
  sRGB?: number[] | null;
  Lab_d50?: number[] | null;
  Lab_d65?: number[] | null;
}

export interface ColorcheckerReferenceSource {
  sourceType?: string | null;
  sourceName?: string | null;
  serialNumber?: string | null;
  patchCount?: number | null;
  labWhitePoint?: string | null;
}

export interface ColorcheckerReferenceSummary {
  id: string;
  name: string;
  description?: string | null;
  source?: ColorcheckerReferenceSource | null;
  patchCount: number;
  labWhitePoint?: string | null;
  serialNumber?: string | null;
}

export interface ColorcheckerReferencesResponse {
  defaultReferenceId: string;
  references: ColorcheckerReferenceSummary[];
}

export interface ColorcheckerReferenceNormalizeResponse {
  patches: ColorcheckerReferencePatch[];
  source: ColorcheckerReferenceSource;
  warnings: string[];
}

export type ColorcheckerReferenceSelection =
  | {
      kind: "server";
      referenceId: string;
    }
  | {
      kind: "custom";
      referencePatches: ColorcheckerReferencePatch[];
      referenceSource: ColorcheckerReferenceSource;
    };

export interface ColorcheckerDisplaySummary {
  deltaE00: ColorcheckerDeltaSummary;
  worstPatch: ColorcheckerWorstPatch | null;
  luminanceCurve: ColorcheckerLuminancePoint[];
  reference?: ColorcheckerReferenceSource | null;
  settings?: {
    method?: string | null;
    calibrationMode?: string | null;
    grayAffineMode?: string | null;
    sampleRadius?: number | null;
    blurRadius?: number | null;
  } | null;
  warnings: string[];
}

export interface ColorcheckerDetectResponse {
  detected: boolean;
  corners: ColorcheckerPoint[];
  patchOrientation: string;
  confidence: number;
  score: number | null;
  mode: string;
  reason: string;
  candidateCount: number;
  full_width?: number;
  full_height?: number;
  preview_width?: number;
  preview_height?: number;
}

export interface ColorcheckerWarpPreviewResponse {
  preview_url: string;
  preview_width: number;
  preview_height: number;
  auto_patch_points: ColorcheckerPoint[];
}

export interface ColorcheckerSourceResponse {
  colorchecker_source_file_id: string;
  source_preview_file_id?: string | null;
  source_preview_url: string;
  full_width: number;
  full_height: number;
  preview_width: number;
  preview_height: number;
  source_type?: string | null;
}

function appendColorcheckerReference(
  fd: FormData,
  reference: ColorcheckerReferenceSelection | null | undefined,
) {
  if (!reference) return;
  if (reference.kind === "server") {
    fd.append("reference_id", reference.referenceId);
    return;
  }
  fd.append("reference_patches", JSON.stringify(reference.referencePatches));
  fd.append("reference_source", JSON.stringify(reference.referenceSource));
}

export async function colorcheckerListReferences(): Promise<ColorcheckerReferencesResponse> {
  const response = await apiClient.get<ColorcheckerReferencesResponse>(
    "/extractor/colorchecker-references",
    { timeout: 30_000 },
  );
  return response.data;
}

export async function colorcheckerNormalizeReference(params: {
  patches: ColorcheckerReferencePatch[];
  source?: Partial<ColorcheckerReferenceSource> | null;
}): Promise<ColorcheckerReferenceNormalizeResponse> {
  const response = await apiClient.post<ColorcheckerReferenceNormalizeResponse>(
    "/extractor/colorchecker-reference-normalize",
    params,
    { timeout: 120_000 },
  );
  return response.data;
}

/** Upload the ColorChecker source image once and receive a bounded preview. */
export async function colorcheckerPrepareSource(
  image: File,
  options: {
    onUploadProgress?: (progress: PreviewResourceUploadProgress) => void;
  } = {},
): Promise<ColorcheckerSourceResponse> {
  const response = await createPreviewResource(image, "colorchecker", {
    timeoutMs: COLORCHECKER_SOURCE_PREVIEW_TIMEOUT_MS,
    onUploadProgress: options.onUploadProgress,
  });
  return {
    colorchecker_source_file_id: response.resource_id,
    source_preview_file_id: response.preview_id,
    source_preview_url: response.preview_url,
    full_width: response.full_width,
    full_height: response.full_height,
    preview_width: response.preview_width,
    preview_height: response.preview_height,
    source_type: response.source_type ?? null,
  };
}

/** Automatically locate the ColorChecker chart corners */
export async function colorcheckerDetectChart(
  sourceFileId: string,
  patchLayout: string = "4x6",
  assistPoint: ColorcheckerPoint | null = null,
  reference: ColorcheckerReferenceSelection | null = null,
): Promise<ColorcheckerDetectResponse> {
  const fd = new FormData();
  fd.append("colorchecker_source_file_id", sourceFileId);
  fd.append("patch_layout", patchLayout);
  if (assistPoint) {
    fd.append("assist_point", JSON.stringify(assistPoint));
  }
  appendColorcheckerReference(fd, reference);
  const response = await apiClient.post<ColorcheckerDetectResponse>(
    "/extractor/colorchecker-detect-chart",
    fd,
    { timeout: 120_000 },
  );
  return response.data;
}

/** Warp the ColorChecker region and return preview + auto 24 patch points */
export async function colorcheckerWarpPreview(
  sourceFileId: string,
  cornerPoints: Array<[number, number]>,
  cornerPointsSize: { width: number; height: number },
  patchLayout: string = "4x6",
  patchOrientation: string = "normal",
): Promise<ColorcheckerWarpPreviewResponse> {
  const fd = new FormData();
  fd.append("colorchecker_source_file_id", sourceFileId);
  fd.append("corner_points", JSON.stringify(cornerPoints));
  fd.append("corner_points_width", String(cornerPointsSize.width));
  fd.append("corner_points_height", String(cornerPointsSize.height));
  fd.append("patch_layout", patchLayout);
  fd.append("patch_orientation", patchOrientation);
  const response = await apiClient.post<ColorcheckerWarpPreviewResponse>(
    "/extractor/colorchecker-warp-preview",
    fd,
    { timeout: 120_000 },
  );
  return response.data;
}

/** Calibration response (step 2) */
export interface ColorcheckerCalibrateResponse {
  calibrated_preview_url: string;
  calibrated_preview_file_id?: string | null;
  calibrated_full_file_id: string;
  overlay_url: string;
  overlay_preview_file_id?: string | null;
  full_width: number;
  full_height: number;
  preview_width: number;
  preview_height: number;
  patch_points: ColorcheckerPoint[];
  display_summary: ColorcheckerDisplaySummary;
}

export interface ColorcheckerCalibrateOptions {
  sampleRadius?: number;
  method?: "mean" | "median";
  calibrationMode?: "matrix_3x3" | "matrix_3x4" | "root_polynomial" | "auto";
  grayAffineMode?: "auto" | "enabled" | "fallback";
  blurRadius?: number;
}

/** Compute CCM and return calibrated image + overlay */
export async function colorcheckerCalibrate(
  sourceFileId: string,
  cornerPoints: Array<[number, number]>,
  cornerPointsSize: { width: number; height: number },
  patchPoints: ColorcheckerPoint[] | null = null,
  patchLayout: string = "4x6",
  options: ColorcheckerCalibrateOptions | null = null,
  patchOrientation: string = "normal",
  reference: ColorcheckerReferenceSelection | null = null,
): Promise<ColorcheckerCalibrateResponse> {
  const fd = new FormData();
  fd.append("colorchecker_source_file_id", sourceFileId);
  fd.append("corner_points", JSON.stringify(cornerPoints));
  fd.append("corner_points_width", String(cornerPointsSize.width));
  fd.append("corner_points_height", String(cornerPointsSize.height));
  if (patchPoints) {
    fd.append("patch_points", JSON.stringify(patchPoints));
  }
  fd.append("patch_layout", patchLayout);
  fd.append("patch_orientation", patchOrientation);
  if (options) {
    if (options.sampleRadius !== undefined) {
      fd.append("sample_radius", String(options.sampleRadius));
    }
    if (options.method) {
      fd.append("method", options.method);
    }
    if (options.calibrationMode) {
      fd.append("calibration_mode", options.calibrationMode);
    }
    if (options.grayAffineMode) {
      fd.append("gray_affine_mode", options.grayAffineMode);
    }
    if (options.blurRadius !== undefined) {
      fd.append("blur_radius", String(options.blurRadius));
    }
  }
  appendColorcheckerReference(fd, reference);
  const response = await apiClient.post<ColorcheckerCalibrateResponse>(
    "/extractor/colorchecker-calibrate",
    fd,
    { timeout: 120_000 },
  );
  return response.data;
}

export async function colorcheckerRelease(fileId: string): Promise<void> {
  const fd = new FormData();
  fd.append("file_id", fileId);
  await apiClient.post("/extractor/colorchecker-release", fd, {
    timeout: 30_000,
  });
}

export interface ColorcheckerConfirmResponse {
  status: string;
  confirmed: boolean;
  calibrated_preview_url?: string | null;
  preview_width?: number | null;
  preview_height?: number | null;
  source_preview_url?: string | null;
  source_preview_width?: number | null;
  source_preview_height?: number | null;
}

export interface ColorcheckerConfirmOptions {
  sourceFileId?: string | null;
  sourcePreviewUrl?: string | null;
}

function fileIdFromApiFilesUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  const extract = (pathname: string): string | null => {
    const prefix = "/api/files/";
    if (!pathname.startsWith(prefix)) return null;
    return decodeURIComponent(pathname.slice(prefix.length).split("/")[0] ?? "");
  };
  if (url.startsWith("/api/files/")) {
    return extract(url);
  }
  try {
    const parsed = new URL(url, window.location.origin);
    if (parsed.origin !== window.location.origin) return null;
    return extract(parsed.pathname);
  } catch {
    return null;
  }
}

export async function colorcheckerConfirm(
  fileId: string,
  previewUrl?: string | null,
  options?: ColorcheckerConfirmOptions | null,
): Promise<ColorcheckerConfirmResponse | undefined> {
  const fd = new FormData();
  fd.append("file_id", fileId);
  const previewFileId = fileIdFromApiFilesUrl(previewUrl);
  if (previewFileId) {
    fd.append("preview_file_id", previewFileId);
  }
  const sourcePreviewFileId = fileIdFromApiFilesUrl(options?.sourcePreviewUrl);
  if (options?.sourceFileId && sourcePreviewFileId) {
    fd.append("source_file_id", options.sourceFileId);
    fd.append("source_preview_file_id", sourcePreviewFileId);
  }
  const response = await apiClient.post<ColorcheckerConfirmResponse>(
    "/extractor/colorchecker-confirm",
    fd,
    { timeout: 30_000 },
  );
  return response.data;
}

export async function colorcheckerTouch(fileId: string): Promise<void> {
  const fd = new FormData();
  fd.append("file_id", fileId);
  await apiClient.post("/extractor/colorchecker-touch", fd, {
    timeout: 30_000,
  });
}

/** Capture-origin tag forwarded as the ``image_source`` form field.
 * 上传给后端的输入图像来源标签。
 */
export type GradientCardImageSourceLabel = "raw" | "restored";

export async function extractGradientCardStageA(params: {
  datasetZip: File;
  whiteImage: File | null;
  blackImage: File | null;
  whiteCornerPoints: Array<[number, number]>;
  blackCornerPoints: Array<[number, number]>;
  whiteColorcheckerFileId?: string | null;
  blackColorcheckerFileId?: string | null;
  whiteCornerPointsWidth?: number | null;
  whiteCornerPointsHeight?: number | null;
  blackCornerPointsWidth?: number | null;
  blackCornerPointsHeight?: number | null;
  manualWhiteOrientation?: ManualOrientationLabel | null;
  manualBlackOrientation?: ManualOrientationLabel | null;
  imageSource?: GradientCardImageSourceLabel | null;
}): Promise<GradientCardStageAExtractResponse> {
  const fd = new FormData();
  fd.append("dataset_zip", params.datasetZip);
  if (!params.whiteColorcheckerFileId && params.whiteImage) {
    fd.append("white_image", params.whiteImage);
  }
  if (!params.blackColorcheckerFileId && params.blackImage) {
    fd.append("black_image", params.blackImage);
  }
  fd.append("white_corner_points", JSON.stringify(params.whiteCornerPoints));
  fd.append("black_corner_points", JSON.stringify(params.blackCornerPoints));
  if (params.whiteColorcheckerFileId) {
    fd.append("white_colorchecker_file_id", params.whiteColorcheckerFileId);
  }
  if (params.blackColorcheckerFileId) {
    fd.append("black_colorchecker_file_id", params.blackColorcheckerFileId);
  }
  if (params.whiteCornerPointsWidth && params.whiteCornerPointsHeight) {
    fd.append("white_corner_points_width", String(params.whiteCornerPointsWidth));
    fd.append("white_corner_points_height", String(params.whiteCornerPointsHeight));
  }
  if (params.blackCornerPointsWidth && params.blackCornerPointsHeight) {
    fd.append("black_corner_points_width", String(params.blackCornerPointsWidth));
    fd.append("black_corner_points_height", String(params.blackCornerPointsHeight));
  }
  if (params.manualWhiteOrientation) {
    fd.append("manual_white_orientation", params.manualWhiteOrientation);
  }
  if (params.manualBlackOrientation) {
    fd.append("manual_black_orientation", params.manualBlackOrientation);
  }
  if (params.imageSource) {
    fd.append("image_source", params.imageSource);
  }
  const response = await apiClient.post<GradientCardStageAExtractResponse>(
    "/extractor/extract-gradient-card-stage-a",
    fd,
    { timeout: 3_600_000 },
  );
  return response.data;
}

export async function saveGradientCardMaterial(params: {
  sessionId: string;
  materialName: string;
  targetDirectoryName?: string | null;
  saveMode?: "merge" | "override";
  brand?: string | null;
}): Promise<GradientCardMaterialSaveResponse> {
  const fd = new FormData();
  fd.append("session_id", params.sessionId);
  fd.append("material_name", params.materialName);
  if (params.targetDirectoryName) {
    fd.append("target_directory_name", params.targetDirectoryName);
  }
  if (params.saveMode) {
    fd.append("save_mode", params.saveMode);
  }
  if (params.brand && params.brand.trim()) {
    fd.append("brand", params.brand.trim());
  }
  const response = await apiClient.post<GradientCardMaterialSaveResponse>(
    "/extractor/save-gradient-card-material",
    fd,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/**
 * Encode each ``/``-separated segment of a saved-material directory_name so
 * the multi-segment path survives URL routing while still escaping spaces
 * and non-ASCII characters.
 * 对多段相对路径 directory_name 按 "/" 分段编码，保留分隔符。
 */
function encodeDirectoryNameForPath(directoryName: string): string {
  return directoryName
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

export async function deleteGradientCardMaterial(
  directoryName: string,
): Promise<GradientCardMaterialDeleteResponse> {
  const response = await apiClient.delete<GradientCardMaterialDeleteResponse>(
    `/extractor/gradient-card-materials/${encodeDirectoryNameForPath(directoryName)}`,
    { timeout: 3_600_000 },
  );
  return response.data;
}

export async function updateGradientCardMaterial(
  directoryName: string,
  payload: {
    materialName: string;
    brand?: string | null;
    estimatedRgb?: [number, number, number] | null;
  },
): Promise<GradientCardMaterialUpdateResponse> {
  const body: {
    material_name: string;
    brand: string | null;
    estimated_rgb?: [number, number, number];
  } = {
    material_name: payload.materialName.trim(),
    brand: payload.brand?.trim() || null,
  };
  if (Array.isArray(payload.estimatedRgb) && payload.estimatedRgb.length === 3) {
    body.estimated_rgb = [
      Math.max(0, Math.min(255, Math.round(payload.estimatedRgb[0]))),
      Math.max(0, Math.min(255, Math.round(payload.estimatedRgb[1]))),
      Math.max(0, Math.min(255, Math.round(payload.estimatedRgb[2]))),
    ];
  }
  const response = await apiClient.patch<GradientCardMaterialUpdateResponse>(
    `/extractor/gradient-card-materials/${encodeDirectoryNameForPath(directoryName)}`,
    body,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** Forward-simulate a stacked material recipe. 正向模拟叠层耗材的预测颜色。 */
export async function previewMaterialRecipe(
  payload: MaterialRecipePreviewRequest,
): Promise<MaterialRecipePreviewResponse> {
  const response = await apiClient.post<MaterialRecipePreviewResponse>(
    "/extractor/material-recipe-preview",
    payload,
  );
  return response.data;
}

export async function listGradientCardMaterials(options?: {
  includeFileUrls?: boolean;
  signal?: AbortSignal;
}): Promise<GradientCardMaterialLibraryResponse> {
  const response = await apiClient.get<GradientCardMaterialLibraryResponse>(
    "/extractor/gradient-card-materials",
    {
      params: options?.includeFileUrls ? { include_file_urls: true } : undefined,
      timeout: 3_600_000,
      ...(options?.signal ? { signal: options.signal } : {}),
    },
  );
  return response.data;
}

export async function exportGradientCardMaterials(
  directoryNames: string[],
): Promise<GradientCardMaterialBulkExportResponse> {
  const response = await apiClient.post<GradientCardMaterialBulkExportResponse>(
    "/extractor/gradient-card-materials/export",
    { directory_names: directoryNames },
    { timeout: 3_600_000 },
  );
  return response.data;
}

export async function importGradientCardMaterials(
  archives: File[],
): Promise<GradientCardMaterialBulkImportResponse> {
  const fd = new FormData();
  archives.forEach((archive) => {
    fd.append("archives", archive);
  });
  const response = await apiClient.post<GradientCardMaterialBulkImportResponse>(
    "/extractor/gradient-card-materials/import",
    fd,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** 手动修正 LUT 单元格 - JSON */
export async function manualFixCell(
  sessionId: string,
  rowIndex: number,
  overrideColor: string,
): Promise<ManualFixResponse> {
  const response = await apiClient.post<ManualFixResponse>(
    "/extractor/manual-fix",
    {
      session_id: sessionId,
      row_index: rowIndex,
      override_color: overrideColor,
    },
  );
  return response.data;
}

export async function resolveLutPreviewCell(
  sessionId: string,
  x: number,
  y: number,
  cardIndex = 0,
): Promise<LutPreviewResolvedCell> {
  const response = await apiClient.post<LutPreviewResolvedCell>(
    "/extractor/resolve-cell",
    {
      session_id: sessionId,
      x,
      y,
      card_index: cardIndex,
    },
  );
  return response.data;
}

/** 合并 8 色分页 LUT */
export async function mergeEightColor(
  eightColorFullExport: boolean,
  workspaceSessionId?: string | null,
): Promise<ExtractResponse> {
  const response = await apiClient.post<ExtractResponse>(
    "/extractor/merge-8color",
    { eight_color_full_export: eightColorFullExport },
    { timeout: 3_600_000, params: workspaceSessionId ? { workspace_session_id: workspaceSessionId } : undefined },
  );
  return response.data;
}

/** 合并 5 色扩展双页 LUT */
export async function mergeFiveColorExtended(workspaceSessionId?: string | null): Promise<ExtractResponse> {
  const response = await apiClient.post<ExtractResponse>(
    "/extractor/merge-5color-extended",
    {},
    { timeout: 3_600_000, params: workspaceSessionId ? { workspace_session_id: workspaceSessionId } : undefined },
  );
  return response.data;
}

/** 自动白平衡预览（后端处理） */
export async function previewAutoWb(
  image: File | Blob,
  filename: string = "image.png",
): Promise<{ preview_url: string; width: number; height: number }> {
  const fd = new FormData();
  fd.append("image", image, filename);
  const response = await apiClient.post<{
    preview_url: string;
    width: number;
    height: number;
  }>("/extractor/preview-wb", fd, { timeout: 3_600_000 });
  return response.data;
}

export type ExtractorRotationDirection = "cw" | "ccw";

/**
 * 旋转图片 90°（后端处理）。
 * Rotate the supplied image by 90 degrees on the backend.
 *
 * @param image    File or Blob to rotate. (待旋转图片)
 * @param filename Display name for the upload payload. (上传时的文件名)
 * @param direction "cw" for clockwise or "ccw" for counter-clockwise; defaults
 *                  to "ccw" for backwards compatibility with existing callers.
 *                  ("cw" 顺时针 / "ccw" 逆时针；缺省 "ccw" 保持兼容)
 */
export async function rotateExtractorImage(
  image: File | Blob,
  filename: string = "image.png",
  direction: ExtractorRotationDirection = "ccw",
): Promise<{ preview_url: string; width: number; height: number }> {
  const fd = new FormData();
  fd.append("image", image, filename);
  const response = await apiClient.post<{
    preview_url: string;
    width: number;
    height: number;
  }>("/extractor/rotate", fd, {
    timeout: 3_600_000,
    params: { direction },
  });
  return response.data;
}

/** 确认调色板 */
export async function confirmPalette(
  payload: ConfirmPaletteRequest,
): Promise<{ status: string; message: string }> {
  const response = await apiClient.post<{ status: string; message: string }>(
    "/extractor/confirm-palette",
    payload,
  );
  return response.data;
}

/** Extract a single-stage dataset zip into 1_single_stage.json */
export async function extractSingleStageDataset(
  datasetZip: File,
): Promise<SingleStageExtractResponse> {
  const fd = new FormData();
  fd.append("dataset_zip", datasetZip);
  const response = await apiClient.post<SingleStageExtractResponse>(
    "/extractor/extract-single-stage",
    fd,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** Fit Stage A from either an extraction session or a raw stage JSON file. */
export async function fitStageA(params: {
  sessionId?: string | null;
  stageJsonFile?: File | null;
}): Promise<StageAFitResponse> {
  const fd = new FormData();
  if (params.sessionId) {
    fd.append("session_id", params.sessionId);
  }
  if (params.stageJsonFile) {
    fd.append("stage_json", params.stageJsonFile);
  }
  const response = await apiClient.post<StageAFitResponse>(
    "/extractor/fit-stage-a",
    fd,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** Generate a 3MF swatch file from collected material-archive recipes. */
export async function generateMaterialRecipeSwatch(
  request: MaterialRecipeSwatchRequest,
): Promise<MaterialRecipeSwatchResponse> {
  const response = await apiClient.post<MaterialRecipeSwatchResponse>(
    "/extractor/generate-material-swatch",
    request,
    { timeout: 3_600_000 },
  );
  return response.data;
}
