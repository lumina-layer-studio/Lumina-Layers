import apiClient from "./client";
import type {
  ConvertPreviewRequest,
  ConvertGenerateRequest,
  PreviewResponse,
  GenerateResponse,
  LutListResponse,
  BedSizeListResponse,
  HeightmapUploadResponse,
  LutColorsResponse,
  BatchConvertParams,
  BatchResponse,
  ColorReplaceResponse,
  RegionDetectResponse,
  RegionReplaceResponse,
} from "./types";

/** 上传图片 + 参数，获取 2D 预览（返回 JSON，含 session_id 和 preview_url） */
export async function convertPreview(
  image: File,
  params: ConvertPreviewRequest,
  signal?: AbortSignal,
): Promise<PreviewResponse> {
  const fd = new FormData();
  fd.append("image", image);
  for (const [key, value] of Object.entries(params)) {
    fd.append(key, String(value));
  }

  const response = await apiClient.post<PreviewResponse>("/convert/preview", fd, {
    timeout: 0,
    signal,
  });
  return response.data;
}

/** 使用 session_id + 全部参数，生成 3MF 模型 */
export async function convertGenerate(
  sessionId: string,
  params: ConvertGenerateRequest
): Promise<GenerateResponse> {
  const response = await apiClient.post<GenerateResponse>(
    "/convert/generate",
    { session_id: sessionId, params },
    { timeout: 0 }
  );
  return response.data;
}

/** 获取可用 LUT 列表 */
export async function fetchLutList(): Promise<LutListResponse> {
  const response = await apiClient.get<LutListResponse>("/lut/list", {
    timeout: 5_000,
  });
  return response.data;
}

/** 根据 file_id 获取文件下载 URL */
export function getFileUrl(fileId: string): string {
  return `/api/files/${fileId}`;
}

/** 获取可用热床尺寸列表 */
export async function fetchBedSizes(): Promise<BedSizeListResponse> {
  const response = await apiClient.get<BedSizeListResponse>("/convert/bed-sizes");
  return response.data;
}

/** 获取空热床 3D 预览 GLB URL */
export async function fetchBedPreview(bedLabel: string): Promise<string> {
  const response = await apiClient.get<{ preview_3d_url: string }>(
    "/convert/bed-preview",
    { params: { bed_label: bedLabel } }
  );
  return response.data.preview_3d_url;
}

/** 上传高度图并获取基于高度图的 color_height_map */
export async function uploadHeightmap(
  heightmapFile: File,
  sessionId: string,
): Promise<HeightmapUploadResponse> {
  const fd = new FormData();
  fd.append("heightmap", heightmapFile);
  fd.append("session_id", sessionId);

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
): Promise<LutColorsResponse> {
  const response = await apiClient.get<LutColorsResponse>(
    `/lut/${encodeURIComponent(lutName)}/colors`,
    { timeout: 10_000 },
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
): Promise<BatchResponse> {
  const fd = new FormData();
  for (const file of images) {
    fd.append("images", file);
  }
  for (const [key, value] of Object.entries(params)) {
    fd.append(key, String(value));
  }
  const response = await apiClient.post<BatchResponse>(
    "/convert/batch",
    fd,
    { timeout: 0 },
  );
  return response.data;
}


/** 替换预览中的单个颜色 */
export async function replaceColor(
  sessionId: string,
  selectedColor: string,
  replacementColor: string,
): Promise<ColorReplaceResponse> {
  const response = await apiClient.post<ColorReplaceResponse>(
    "/convert/replace-color",
    {
      session_id: sessionId,
      selected_color: selectedColor,
      replacement_color: replacementColor,
    },
    { timeout: 30_000 },
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
    { timeout: 15_000 },
  );
  return response.data;
}

/** 检测点击位置的连通区域 */
export async function detectRegion(
  sessionId: string,
  x: number,
  y: number,
): Promise<RegionDetectResponse> {
  const response = await apiClient.post<RegionDetectResponse>(
    "/convert/region-detect",
    { session_id: sessionId, x, y },
    { timeout: 30_000 },
  );
  return response.data;
}

/** 替换已选中连通区域的颜色 */
export async function regionReplace(
  sessionId: string,
  replacementColor: string,
): Promise<RegionReplaceResponse> {
  const response = await apiClient.post<RegionReplaceResponse>(
    "/convert/region-replace",
    { session_id: sessionId, replacement_color: replacementColor },
    { timeout: 30_000 },
  );
  return response.data;
}

/** 重置所有颜色替换响应 */
export interface ResetReplacementsResponse {
  status: string;
  message: string;
  preview_url: string;
  preview_glb_url?: string | null;
}

/** 重置所有颜色替换，恢复原始预览 */
export async function resetReplacements(
  sessionId: string,
): Promise<ResetReplacementsResponse> {
  const response = await apiClient.post<ResetReplacementsResponse>(
    "/convert/reset-replacements",
    { session_id: sessionId },
    { timeout: 15_000 },
  );
  return response.data;
}
