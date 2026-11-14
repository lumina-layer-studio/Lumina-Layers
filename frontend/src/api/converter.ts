import apiClient, { type ApiRequestOptions } from "./client";
import type {
  ConvertPreviewRequest,
  ConvertGenerateRequest,
  ExportMaterialSelection,
  PreviewResponse,
  GenerateResponse,
  LargeFormatGenerateRequest,
  LargeFormatGenerateResponse,
  PuzzleGenerateRequest,
  PuzzleGenerateResponse,
  PuzzleLayoutPreviewRequest,
  PuzzleLayoutPreviewResponse,
  LutListResponse,
  BedSizeListResponse,
  HeightmapUploadResponse,
  LutColorsResponse,
  BatchConvertParams,
  BatchResponse,
  ColorReplaceResponse,
  SourceColorPickResponse,
  ColorHighlightResponse,
  GradientGroupsResponse,
  RegionDetectResponse,
  RegionReplaceResponse,
  FreeColorMutationResponse,
  RecipePredictRequest,
  RecipePredictResponse,
  RecipeOverrideApplyRequest,
  RecipeOverrideApplyResponse,
  RegionRecipeRequest,
  RegionRecipeResponse,
  ResetReplacementsResponse,
  ReplacementHistoryResponse,
  SelectionDocumentResponse,
  SelectionMutationRequest,
  SimilarRecipesRequest,
  SimilarRecipesResponse,
  EditorCommitStatusResponse,
  AutoDetectColorsResponse,
  ModelSurfaceHitTriangle,
  ModelSurfaceModelTransform,
  ModelSurfaceSelectResponse,
  ModelSurfaceUploadResponse,
  VectorPreviewRendererResponse,
} from "./types";

/** 上传图片 + 参数，获取 2D 预览（返回 JSON，含 session_id 和 preview_url） */
export async function convertPreview(
  image: File,
  params: ConvertPreviewRequest,
  signal?: AbortSignal,
  resources?: { lut?: File | null; materials?: File | null; editor?: File | null },
): Promise<PreviewResponse> {
  const fd = new FormData();
  fd.append("image", image);
  if (resources?.lut) fd.append("project_lut", resources.lut);
  if (resources?.materials) fd.append("project_materials", resources.materials);
  if (resources?.editor) fd.append("project_editor", resources.editor);
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) {
      continue;
    }
    if (Array.isArray(value)) {
      fd.append(key, JSON.stringify(value));
      continue;
    }
    fd.append(key, String(value));
  }

  const response = await apiClient.post<PreviewResponse>(
    "/convert/preview",
    fd,
    {
      timeout: 0,
      signal,
    },
  );
  return response.data;
}

/** 使用 session_id + 全部参数，生成 3MF 模型 */
export async function convertGenerate(
  sessionId: string,
  params: ConvertGenerateRequest,
  preserveUploadFilenameFor3mf = false,
): Promise<GenerateResponse> {
  const response = await apiClient.post<GenerateResponse>(
    "/convert/generate",
    {
      session_id: sessionId,
      preserve_upload_filename_for_3mf: preserveUploadFilenameFor3mf,
      params,
    },
    { timeout: 0 },
  );
  return response.data;
}

/** Check native filament choices before building printable geometry. */
export async function fetchExportMaterialSelection(
  sessionId: string | null,
  params: ConvertGenerateRequest | BatchConvertParams,
  resources?: { lut?: File | null; materials?: File | null },
): Promise<ExportMaterialSelection> {
  if (!sessionId && (resources?.lut || resources?.materials)) {
    const form = new FormData();
    form.append("request_json", JSON.stringify({ params }));
    if (resources.lut) form.append("project_lut", resources.lut);
    if (resources.materials) form.append("project_materials", resources.materials);
    const response = await apiClient.post<ExportMaterialSelection>("/convert/project-export-materials", form, { timeout: 60_000 });
    return response.data;
  }
  const response = await apiClient.post<ExportMaterialSelection>(
    "/convert/export-materials",
    { session_id: sessionId, params },
    { timeout: 30_000 },
  );
  return response.data;
}

/** 上传用于覆面的 STL/OBJ 模型。 */
export async function uploadModelSurface(
  model: File,
): Promise<ModelSurfaceUploadResponse> {
  const fd = new FormData();
  fd.append("model", model);
  const response = await apiClient.post<ModelSurfaceUploadResponse>(
    "/convert/model-surface/upload",
    fd,
    { timeout: 0 },
  );
  return response.data;
}

/** 在已上传模型上选择一个平面区域。 */
export async function selectModelSurface(
  modelFileId: string,
  hit: ModelSurfaceHitTriangle & { model_transform?: ModelSurfaceModelTransform },
): Promise<ModelSurfaceSelectResponse> {
  const { model_transform, ...hitPayload } = hit;
  const response = await apiClient.post<ModelSurfaceSelectResponse>(
    "/convert/model-surface/select",
    {
      model_file_id: modelFileId,
      hit: hitPayload,
      include_same_plane_disconnected: false,
      ...(model_transform ? { model_transform } : {}),
    },
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** 生成验证色卡 3MF：从当前 session 的调色板生成可打印的色块色卡 */
export interface ColorCardDeviceSelection {
  printer_id: string;
  slicer: string;
  nozzle_size: string;
  device_profile_id?: string;
  build_plate_id?: string;
  custom_3mf_template_id?: string | null;
  enable_wipe_tower_auto_placement?: boolean;
}

export async function generateColorCard(
  sessionId: string,
  device: ColorCardDeviceSelection,
  targetWidthMm: number = 100,
  spacerThick: number = 0.48,
  showLabels: boolean = true,
): Promise<GenerateResponse> {
  const response = await apiClient.post<GenerateResponse>(
    "/convert/color-card",
    {
      session_id: sessionId,
      target_width_mm: targetWidthMm,
      spacer_thick: spacerThick,
      show_labels: showLabels,
      ...device,
    },
    { timeout: 0 },
  );
  return response.data;
}

/** 大画幅模式：切割图片并生成多片 3MF 压缩包 */
export async function convertGenerateLargeFormat(
  sessionId: string,
  params: LargeFormatGenerateRequest,
): Promise<LargeFormatGenerateResponse> {
  const response = await apiClient.post<LargeFormatGenerateResponse>(
    "/convert/generate-large-format",
    { session_id: sessionId, params },
    { timeout: 0 },
  );
  return response.data;
}

/** 拼图模式：生成叠线预览覆盖图 */
export async function convertPuzzleLayoutPreview(
  sessionId: string,
  params: PuzzleLayoutPreviewRequest,
): Promise<PuzzleLayoutPreviewResponse> {
  const response = await apiClient.post<PuzzleLayoutPreviewResponse>(
    "/convert/puzzle-layout-preview",
    { session_id: sessionId, params },
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** 拼图模式：逐块生成并导出单个 3MF */
export async function convertGeneratePuzzle(
  sessionId: string,
  params: PuzzleGenerateRequest,
): Promise<PuzzleGenerateResponse> {
  const response = await apiClient.post<PuzzleGenerateResponse>(
    "/convert/generate-puzzle",
    { session_id: sessionId, params },
    { timeout: 0 },
  );
  return response.data;
}

/** 获取可用 LUT 列表 */
export async function fetchLutList(
  options: ApiRequestOptions = {},
): Promise<LutListResponse> {
  const response = await apiClient.get<LutListResponse>("/lut/list", {
    timeout: 3_600_000,
    ...(options.suppressClientLog === true ? { suppressClientLog: true } : {}),
  });
  return response.data;
}

/** 上传 LUT 文件到预设目录 */
export async function uploadLut(
  file: File,
): Promise<{ status: string; message: string; name: string }> {
  const fd = new FormData();
  fd.append("file", file);
  const response = await apiClient.post<{
    status: string;
    message: string;
    name: string;
  }>("/lut/upload", fd, { timeout: 3_600_000 });
  return response.data;
}

/** 根据 file_id 获取文件下载 URL */
export function getFileUrl(fileId: string): string {
  return `/api/files/${fileId}`;
}

/** 获取可用热床尺寸列表 */
export async function fetchBedSizes(): Promise<BedSizeListResponse> {
  const response =
    await apiClient.get<BedSizeListResponse>("/convert/bed-sizes");
  return response.data;
}

/** 获取空热床 3D 预览 GLB URL */
export async function fetchBedPreview(bedLabel: string): Promise<string> {
  const response = await apiClient.get<{ preview_3d_url: string }>(
    "/convert/bed-preview",
    { params: { bed_label: bedLabel } },
  );
  return response.data.preview_3d_url;
}

/** 上传高度图并获取基于高度图的 color_height_map */
export async function uploadHeightmap(
  heightmapFile: File,
  sessionId: string,
  maxReliefHeight: number,
): Promise<HeightmapUploadResponse> {
  const fd = new FormData();
  fd.append("heightmap", heightmapFile);
  fd.append("session_id", sessionId);
  fd.append("max_relief_height", String(maxReliefHeight));

  const response = await apiClient.post<HeightmapUploadResponse>(
    "/convert/upload-heightmap",
    fd,
    { timeout: 0 },
  );
  return response.data;
}

/** 获取 LUT 中所有可用颜色 */
export async function fetchLutColors(
  lutName: string,
  signal?: AbortSignal,
  sessionId?: string | null,
): Promise<LutColorsResponse> {
  const response = await apiClient.get<LutColorsResponse>(
    `/lut/${encodeURIComponent(lutName)}/colors`,
    {
      params: sessionId ? { session_id: sessionId } : undefined,
      timeout: 3_600_000,
      ...(signal ? { signal } : {}),
    },
  );
  return response.data;
}

/** 裁剪响应 */
export interface CropResponse {
  status: string;
  message: string;
  cropped_url: string;
  width: number;
  height: number;
}

/** 发送裁剪坐标到后端，返回裁剪后的图片信息 */
export async function cropImage(
  file: File,
  x: number,
  y: number,
  width: number,
  height: number,
): Promise<CropResponse> {
  const fd = new FormData();
  fd.append("image", file);
  fd.append("x", String(Math.round(x)));
  fd.append("y", String(Math.round(y)));
  fd.append("width", String(Math.round(width)));
  fd.append("height", String(Math.round(height)));
  const response = await apiClient.post<CropResponse>("/convert/crop", fd);
  return response.data;
}

/** 批量转换：上传多张图片 + 共享参数，返回批量处理结果 */
export async function convertBatch(
  images: File[],
  params: BatchConvertParams,
  resources?: { lut?: File | null; materials?: File | null },
): Promise<BatchResponse> {
  const fd = new FormData();
  if (resources?.lut) fd.append("project_lut", resources.lut);
  if (resources?.materials) fd.append("project_materials", resources.materials);
  for (const file of images) {
    fd.append("images", file);
  }
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) {
      continue;
    }
    if (typeof value === "object") {
      fd.append(key, JSON.stringify(value));
      continue;
    }
    fd.append(key, String(value));
  }
  const response = await apiClient.post<BatchResponse>("/convert/batch", fd, {
    timeout: 0,
  });
  return response.data;
}

/** 替换预览中的单个颜色 */
export async function replaceColor(
  sessionId: string,
  selectedColor: string,
  replacementColor: string,
  operationId?: string,
): Promise<ColorReplaceResponse> {
  const response = await apiClient.post<ColorReplaceResponse>(
    "/convert/replace-color",
    {
      session_id: sessionId,
      selected_color: selectedColor,
      replacement_color: replacementColor,
      ...(operationId ? { operation_id: operationId } : {}),
    },
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** 一次颜色替换对：{ 原色, 目标色 } */
export interface ColorReplacePair {
  selectedColor: string;
  replacementColor: string;
}

/**
 * Batch-replace multiple colours in one backend round-trip.
 *
 * Semantically equivalent to calling :func:`replaceColor` for each pair in
 * order, but the server runs the styled PNG render and the segmented GLB
 * rebuild exactly once at the end, making batch swaps O(N) cheaper on
 * those dominant cost centres. Use whenever the caller already knows the
 * full list of colour swaps up front (multi-select replace, colour-remap
 * undo replay, gradient whole-group flatten, etc.).
 * 一次请求里批量替换多个颜色。语义等价于循环调用 replaceColor，但 PNG
 * 渲染和 GLB 重建只做 1 次，批量颜色替换 N× 提速。
 */
export async function replaceColorsBatch(
  sessionId: string,
  pairs: ColorReplacePair[],
  operationId?: string,
): Promise<ColorReplaceResponse> {
  const response = await apiClient.post<ColorReplaceResponse>(
    "/convert/replace-colors-batch",
    {
      session_id: sessionId,
      replacements: pairs.map((p) => ({
        selected_color: p.selectedColor,
        replacement_color: p.replacementColor,
      })),
      ...(operationId ? { operation_id: operationId } : {}),
    },
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** 按预览像素坐标读取当前匹配色，用于同颜色全选跟随用户已替换/自定义后的预览。 */
export async function sourceColorPick(
  sessionId: string,
  x: number,
  y: number,
): Promise<SourceColorPickResponse> {
  const response = await apiClient.post<SourceColorPickResponse>(
    "/convert/source-color-pick",
    { session_id: sessionId, x, y },
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** 分层图片响应 */
export interface LayerImageInfo {
  layer_index: number;
  name: string;
  url: string;
}

export interface LayerImagesResponse {
  session_id: string;
  layers: LayerImageInfo[];
}

/** 获取分层材料预览图 */
export async function fetchLayerImages(
  sessionId: string,
): Promise<LayerImagesResponse> {
  const response = await apiClient.get<LayerImagesResponse>(
    `/convert/layer-images/${sessionId}`,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** Optional scope arguments for ``colorHighlight``.
 * colorHighlight 的可选裁剪参数。
 *
 * Prefer ``gradientGroupIndex + gradientRegionIndex`` to restrict the
 * highlight to the exact pixel mask of a single gradient sub-region — this
 * is the correct fix for "clicking a sub-region lights up the whole group"
 * because it consults the cached per-pixel region_id_map on the backend
 * instead of an imprecise bounding rectangle.
 * ``regionBbox`` remains as a legacy fallback for clients that cannot yet
 * supply region identifiers; its accuracy is limited to the region's
 * external rectangle and should be avoided for gradient-region flows.
 */
export interface ColorHighlightScope {
  gradientGroupIndex?: number;
  gradientRegionIndex?: number;
  regionBbox?: [number, number, number, number];
}

/**
 * 高亮指定颜色的所有像素。
 *
 * - 若传入 ``gradientGroupIndex + gradientRegionIndex``，后端使用预览生成
 *   时缓存的每像素 region 编码图精确裁剪，只点亮该子区域的像素。
 * - 否则若传入 ``regionBbox``，按矩形 bbox 回退裁剪。
 * - 两者都未传时，点亮整张预览上所有匹配像素。
 */
export async function colorHighlight(
  sessionId: string,
  colorHexes: string[],
  scope?: ColorHighlightScope,
): Promise<ColorHighlightResponse> {
  const body: Record<string, unknown> = {
    session_id: sessionId,
    color_hexes: colorHexes,
  };
  if (
    scope?.gradientGroupIndex !== undefined &&
    scope?.gradientRegionIndex !== undefined
  ) {
    body.gradient_group_index = scope.gradientGroupIndex;
    body.gradient_region_index = scope.gradientRegionIndex;
  } else if (scope?.regionBbox) {
    body.region_bbox = scope.regionBbox;
  }
  const response = await apiClient.post<ColorHighlightResponse>(
    "/convert/color-highlight",
    body,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** Read the shared, revisioned editor selection. */
export async function getEditorSelection(
  sessionId: string,
): Promise<SelectionDocumentResponse> {
  const response = await apiClient.get<SelectionDocumentResponse>(
    `/convert/selection/${encodeURIComponent(sessionId)}`,
  );
  return response.data;
}

/** Apply one point, same-colour, brush, or clear mutation to the shared selection. */
export async function mutateEditorSelection(
  request: SelectionMutationRequest,
): Promise<SelectionDocumentResponse> {
  const response = await apiClient.post<SelectionDocumentResponse>(
    "/convert/selection/mutate",
    request,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/**
 * Suggest printable recipes closest to a target colour (colour workspace).
 * 推荐与目标颜色色差最小的可打印配方（颜色工作台）。
 */
export async function fetchSimilarRecipes(
  request: SimilarRecipesRequest,
  signal?: AbortSignal,
): Promise<SimilarRecipesResponse> {
  const response = await apiClient.post<SimilarRecipesResponse>(
    "/convert/similar-recipes",
    request,
    { timeout: 30_000, signal },
  );
  return response.data;
}

/** 检测点击位置的连通区域 */
export async function detectRegion(
  sessionId: string,
  x: number,
  y: number,
  options?: { includePreview?: boolean },
): Promise<RegionDetectResponse> {
  const body: Record<string, unknown> = {
    session_id: sessionId,
    x,
    y,
    include_preview: options?.includePreview ?? false,
  };
  const response = await apiClient.post<RegionDetectResponse>(
    "/convert/region-detect",
    body,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/**
 * Scope object for :func:`regionReplace` identifying *which* spatial region
 * should be edited. Leave undefined to consume the one-shot mask that
 * :func:`regionDetect` stashed in the session. Provide a
 * :obj:`GradientRegionReplaceScope` to rebuild the mask on the server from
 * the cached per-pixel ``gradient_region_id_map`` — the only way to scope
 * the edit to a single banded sub-region when several disjoint regions
 * share the same quantised hex.
 * :func:`regionReplace` 的区域来源：不传 = 用 click-detected 的一次性
 * mask（legacy）；传 GradientRegionReplaceScope = 服务端从 region_id_map
 * 现场生成 mask。仅传 ``gradientGroupIndex`` = 整组 mask（去海带纹）；
 * 同时传 ``gradientRegionIndex`` = 单子区域 mask。
 */
export interface GradientRegionReplaceScope {
  gradientGroupIndex: number;
  /** 不传时 mask 覆盖整个 group（去海带纹） */
  gradientRegionIndex?: number;
}

/** 替换已选中连通区域的颜色 */
export async function regionReplace(
  sessionId: string,
  replacementColor: string,
  scope?: GradientRegionReplaceScope,
  selectionRevision?: number,
  operationId?: string,
): Promise<RegionReplaceResponse> {
  const body: Record<string, unknown> = {
    session_id: sessionId,
    replacement_color: replacementColor,
  };
  if (selectionRevision !== undefined) {
    body.selection_revision = selectionRevision;
  }
  if (scope) {
    body.gradient_group_index = scope.gradientGroupIndex;
    if (scope.gradientRegionIndex !== undefined) {
      body.gradient_region_index = scope.gradientRegionIndex;
    }
  }
  if (operationId) body.operation_id = operationId;
  const response = await apiClient.post<RegionReplaceResponse>(
    "/convert/region-replace",
    body,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/**
 * One entry in a region-replace batch request. Either the click
 * coordinate pair (``clickX`` + ``clickY``) or the gradient indices
 * (``gradientGroupIndex``, optionally with ``gradientRegionIndex``) must
 * be supplied — exactly the same source modes as the non-batch
 * :func:`regionReplace`.
 * 批量区域替换的单条 item：click 坐标或 gradient 索引二选一，与非批量
 * :func:`regionReplace` 的 mask 来源语义一致。
 */
export interface RegionReplaceBatchItemPayload {
  replacementColor: string;
  clickX?: number;
  clickY?: number;
  gradientGroupIndex?: number;
  gradientRegionIndex?: number;
}

/**
 * Batch region-replace: multiple masks + target colours in one round-trip.
 *
 * Server applies each item's mask cumulatively to the cached matched_rgb
 * then renders the styled PNG and rebuilds the segmented GLB exactly
 * once for the whole batch. Use this for multi-region click replace and
 * for any flow that edits several gradient regions in a row — the
 * per-call GLB rebuild was the dominant latency before.
 * 一次请求批量处理多个区域替换。服务端累积 mask 后统一渲染 PNG 和 GLB，
 * 解决"N 区域 → N 次 GLB 重建"的瓶颈。
 */
export async function regionReplaceBatch(
  sessionId: string,
  items: RegionReplaceBatchItemPayload[],
  operationId?: string,
): Promise<RegionReplaceResponse> {
  const response = await apiClient.post<RegionReplaceResponse>(
    "/convert/region-replace-batch",
    {
      session_id: sessionId,
      items: items.map((it) => {
        const body: Record<string, unknown> = {
          replacement_color: it.replacementColor,
        };
        if (it.clickX !== undefined) body.click_x = it.clickX;
        if (it.clickY !== undefined) body.click_y = it.clickY;
        if (it.gradientGroupIndex !== undefined) {
          body.gradient_group_index = it.gradientGroupIndex;
        }
        if (it.gradientRegionIndex !== undefined) {
          body.gradient_region_index = it.gradientRegionIndex;
        }
        return body;
      }),
      ...(operationId ? { operation_id: operationId } : {}),
    },
    { timeout: 3_600_000 },
  );
  return response.data;
}

/**
 * One gradient-region target inside a re-quantisation request.
 * 二次量化请求中的单个渐变 region 目标（group + region 索引均 1-based）。
 */
export interface RegionRequantizeTargetPayload {
  gradientGroupIndex: number;
  gradientRegionIndex: number;
}

/**
 * Per-region secondary re-quantisation — takes the original source pixels
 * under each selected region's mask, runs a dedicated K-Means with
 * ``localQuantizeColors`` clusters, re-matches through the same material
 * solver the preview uses, and splices the result back into
 * ``matched_rgb``. Material-archive mode only.
 *
 * 渐变面板的区域级二次量化：对每个选中 region 独立跑一次 K-Means
 * 量化（局部调色板预算），再用管线同款材料求解器重匹配，只写回这些
 * region 的像素。仅在耗材档案模式下可用。
 */
export async function regionRequantize(
  sessionId: string,
  targets: RegionRequantizeTargetPayload[],
  localQuantizeColors: number,
  operationId?: string,
): Promise<RegionReplaceResponse> {
  const response = await apiClient.post<RegionReplaceResponse>(
    "/convert/region-requantize",
    {
      session_id: sessionId,
      targets: targets.map((t) => ({
        gradient_group_index: t.gradientGroupIndex,
        gradient_region_index: t.gradientRegionIndex,
      })),
      local_quantize_colors: localQuantizeColors,
      ...(operationId ? { operation_id: operationId } : {}),
    },
    { timeout: 3_600_000 },
  );
  return response.data;
}

/**
 * Snapshot of the backend's async segmented-GLB build state.
 *
 * Emitted by ``GET /api/convert/glb-status/{session_id}`` so the frontend
 * can keep polling after a replace endpoint returned ``preview_glb_url:
 * null`` (the server now runs ``generate_segmented_glb`` off the request
 * thread to cut perceived replace latency by ~75%). When ``status`` goes
 * to ``"ready"`` the caller should drop the ``glb_url`` into
 * ``previewGlbUrl`` and stop polling. ``color_contours`` may be present
 * on ready snapshots so async preview can restore highlight contours.
 * 后端异步 GLB 构建状态快照：因为 replace 端点不再同步等 GLB，前端通过
 * 这个端点轮询拿 ``glb_url``，``status`` 切到 ready 后更新 previewGlbUrl。
 */
export interface GlbStatusResponse {
  session_id: string;
  status: "idle" | "pending" | "ready" | "error";
  glb_url: string | null;
  job_token: string | null;
  error: string | null;
  color_contours?: Record<string, number[][][]> | null;
}

/**
 * Fetch the async segmented-GLB build status for a session.
 *
 * Safe to call repeatedly (read-only, no side effects); the backend's
 * status endpoint returns ``idle`` for sessions that have never scheduled
 * a build yet, so callers can start polling speculatively without a 404.
 * 查询 session 的异步 GLB 构建状态，可重复调用；从未调度过的 session
 * 返回 ``idle``，前端可放心先起轮询。
 */
export async function getGlbStatus(
  sessionId: string,
): Promise<GlbStatusResponse> {
  const response = await apiClient.get<GlbStatusResponse>(
    `/convert/glb-status/${encodeURIComponent(sessionId)}`,
    { timeout: GLB_STATUS_TIMEOUT_MS, suppressErrorTicket: true },
  );
  return response.data;
}

export const GLB_STATUS_TIMEOUT_MS = 30_000;

/** Rebuild only the browser GLB renderer for an active native Vector session. */
export async function rebuildVectorPreviewRenderer(
  sessionId: string,
  enableSmoothVectorPreview: boolean,
): Promise<VectorPreviewRendererResponse> {
  const response = await apiClient.post<VectorPreviewRendererResponse>(
    "/convert/vector-preview-renderer",
    {
      session_id: sessionId,
      enable_smooth_vector_preview: enableSmoothVectorPreview,
    },
    { timeout: 30_000 },
  );
  return response.data;
}

/** Predict a custom recipe color against the active preview session/source. */
export async function predictCustomRecipe(
  request: RecipeOverrideApplyRequest | RecipePredictRequest,
): Promise<RecipePredictResponse> {
  const response = await apiClient.post<RecipePredictResponse>(
    "/convert/predict-recipe",
    {
      session_id: request.session_id,
      recipe: request.recipe,
      layer_order: request.layer_order,
      color_layers: request.color_layers,
      layer_height_mm: request.layer_height_mm,
    },
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** Apply a custom recipe override to one or more selected regions. */
export async function applyRecipeOverride(
  request: RecipeOverrideApplyRequest,
): Promise<RecipeOverrideApplyResponse> {
  const response = await apiClient.post<RecipeOverrideApplyResponse>(
    "/convert/apply-recipe-override",
    request,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/**
 * Read the current per-layer material stack for one or more selected regions.
 * 读取选中区域当前每层的堆叠材料，用于自定义配方对话框预设下拉。
 *
 * The Custom Recipe dialog calls this on open so the per-layer dropdowns
 * pre-populate with each region's real matched recipe instead of the
 * all-White default. Short timeout (15s) because the backend path is a
 * cheap ``material_matrix[mask]`` sample — not a full solve.
 *
 * 自定义配方对话框打开时调用，让每层下拉预设为该区域真实匹配的配方而
 * 非全白默认。超时取短值（15s），后端只是 ``material_matrix[mask]`` 的
 * 轻量采样，不是完整求解。
 */
export async function fetchRegionRecipe(
  request: RegionRecipeRequest,
): Promise<RegionRecipeResponse> {
  const response = await apiClient.post<RegionRecipeResponse>(
    "/convert/region-recipe",
    request,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** 预测任意配方的显示颜色 */
export async function predictRecipe(
  payload: RecipePredictRequest,
): Promise<RecipePredictResponse> {
  const response = await apiClient.post<RecipePredictResponse>(
    "/convert/predict-recipe",
    payload,
    { timeout: 3_600_000 },
  );
  return response.data;
}

export async function mutateFreeColors(
  sessionId: string,
  action: "toggle" | "clear" | "replace",
  colorHexes: string[] = [],
  operationId?: string,
): Promise<FreeColorMutationResponse> {
  const response = await apiClient.post<FreeColorMutationResponse>(
    "/convert/free-colors",
    {
      session_id: sessionId,
      action,
      color_hexes: colorHexes,
      ...(operationId ? { operation_id: operationId } : {}),
    },
  );
  return response.data;
}

/** 重置所有颜色替换，恢复原始预览 */
export async function resetReplacements(
  sessionId: string,
  operationId?: string,
): Promise<ResetReplacementsResponse> {
  const response = await apiClient.post<ResetReplacementsResponse>(
    "/convert/reset-replacements",
    {
      session_id: sessionId,
      ...(operationId ? { operation_id: operationId } : {}),
    },
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** 撤销或重做一次颜色调整。 */
export async function replacementHistory(
  sessionId: string,
  action: "undo" | "redo",
  operationId?: string,
): Promise<ReplacementHistoryResponse> {
  const response = await apiClient.post<ReplacementHistoryResponse>(
    "/convert/replacement-history",
    {
      session_id: sessionId,
      action,
      ...(operationId ? { operation_id: operationId } : {}),
    },
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** Capture editable pixels and spatial masks at the confirmed editor revisions. */
export async function exportEditorProject(
  sessionId: string,
  editorContentRevision?: number,
  selectionRevision?: number,
): Promise<File> {
  const response = await apiClient.get<Blob>(
    `/convert/editor-project/${encodeURIComponent(sessionId)}`,
    { responseType: "blob", params: { editor_content_revision: editorContentRevision, selection_revision: selectionRevision }, timeout: 60_000 },
  );
  return new File([response.data], "editor.json.gz", { type: "application/gzip" });
}

/** Initialize a fresh source preview with the embedded editable checkpoint. */
export async function restoreEditorProject(
  sessionId: string, file: File, operationId: string,
): Promise<EditorCommitStatusResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("operation_id", operationId);
  const response = await apiClient.post<EditorCommitStatusResponse>(
    `/convert/editor-project/${encodeURIComponent(sessionId)}/restore`, form, { timeout: 60_000 },
  );
  return response.data;
}

/** Read the server-side confirmation for one editor operation. */
export async function getEditorCommitStatus(
  sessionId: string,
  operationId: string,
): Promise<EditorCommitStatusResponse> {
  const response = await apiClient.get<EditorCommitStatusResponse>(
    `/convert/editor-commit/${encodeURIComponent(sessionId)}/${encodeURIComponent(operationId)}`,
    { timeout: 15_000 },
  );
  return response.data;
}

/** 清理 session 中间文件（预览、GLB 等），保留指定文件 */
export async function cleanupSessionFiles(
  sessionId: string,
  keepFileIds: string[] = [],
): Promise<void> {
  await apiClient
    .post("/convert/cleanup-session-files", {
      session_id: sessionId,
      keep_file_ids: keepFileIds,
    })
    .catch(() => {
      /* fire-and-forget: ignore cleanup failures */
    });
}

/**
 * Use navigator.sendBeacon to reliably clean up session files when the page
 * is closing (tab close, browser quit, navigation away). sendBeacon survives
 * page unload unlike fetch/XHR.
 */
export function beaconCleanupSessionFiles(
  sessionId: string,
  keepFileIds: string[] = [],
): void {
  const base =
    (import.meta.env.VITE_API_BASE_URL as string | undefined) || "/api";
  const url = `${base}/convert/cleanup-session-files`;
  const body = JSON.stringify({
    session_id: sessionId,
    keep_file_ids: keepFileIds,
  });
  if (
    typeof navigator !== "undefined" &&
    typeof navigator.sendBeacon === "function"
  ) {
    try {
      const queued = navigator.sendBeacon(
        url,
        new Blob([body], { type: "application/json" }),
      );
      if (queued) {
        return;
      }
    } catch {
      // Fall back to the regular cleanup request below.
    }
  }

  void cleanupSessionFiles(sessionId, keepFileIds);
}

/** 自动检测推荐量化颜色数 */
export async function autoDetectColors(
  image: File,
  targetWidthMm: number,
): Promise<AutoDetectColorsResponse> {
  const fd = new FormData();
  fd.append("image", image);
  fd.append("target_width_mm", String(targetWidthMm));
  const response = await apiClient.post<AutoDetectColorsResponse>(
    "/convert/auto-detect-colors",
    fd,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** 读取 session 预览完成后缓存的"渐变海带纹分组"分析。 */
export async function fetchGradientGroups(
  sessionId: string,
  signal?: AbortSignal,
): Promise<GradientGroupsResponse> {
  const response = await apiClient.get<GradientGroupsResponse>(
    `/convert/gradient-groups/${sessionId}`,
    { timeout: 30_000, signal },
  );
  return response.data;
}
