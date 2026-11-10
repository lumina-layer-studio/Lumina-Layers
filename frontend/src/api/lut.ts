import apiClient, { type ApiRequestOptions } from "./client";
import { workflowHeaders } from "../project/workflowRuntime";
import { isPredictiveLutSource } from "../utils/lutVisibility";
import type {
  CompareRequest,
  CompareResponse,
  CloudLutInstallRecord,
  CloudLutInstallRequest,
  CloudLutRegistryCatalogItem,
  CloudLutRegistryCatalogRequest,
  CloudLutRegistryCatalogResponse,
  CloudLutRegistryStatusResponse,
  LutCatalogResponse,
  LutDetailsCatalogResponse,
  LutDetailsResponse,
  LutInfoResponse,
  MergeRequest,
  MergeResponse,
  RecipeColorPredictRequest,
  RecipeColorPredictResponse,
  RecipeSearchRequest,
  RecipeSearchResponse,
} from "./types";

/** 获取指定 LUT 的颜色模式和颜色数量 */
export async function fetchLutInfo(lutName: string, workflow = "lut-manager"): Promise<LutInfoResponse> {
  const response = await apiClient.get<LutInfoResponse>(
    `/lut/${encodeURIComponent(lutName)}/info`,
    { headers: workflowHeaders(workflow) },
  );
  return response.data;
}

/**
 * 获取当前会话所绑定 LUT 的通道调色板与能力信息。
 * Fetches the channel palette bound to a converter session, which works for
 * material-archive / native-bundle sessions that have no globally-known LUT
 * name. Used by the custom recipe editor to show channel-ordered materials.
 */
export async function fetchSessionLutInfo(
  sessionId: string,
): Promise<LutInfoResponse> {
  const response = await apiClient.get<LutInfoResponse>(
    `/lut/session/${encodeURIComponent(sessionId)}/info`,
  );
  return response.data;
}

/** 执行 LUT 合并操作 */
export async function mergeLuts(request: MergeRequest): Promise<MergeResponse> {
  const response = await apiClient.post<MergeResponse>("/lut/merge", request, {
    headers: workflowHeaders("lut-manager"),
    timeout: 3_600_000,
  });
  return response.data;
}

/** Compare two LUTs by shared recipe */
export async function compareLuts(
  request: CompareRequest,
): Promise<CompareResponse> {
  const response = await apiClient.post<CompareResponse>(
    "/lut/compare",
    request,
    { timeout: 3_600_000, headers: workflowHeaders("lut-compare") },
  );
  return response.data;
}

/** 获取转换器可见的 LUT 目录。 */
export async function fetchLutCatalog(
  signal?: AbortSignal,
): Promise<LutCatalogResponse> {
  const response = signal
    ? await apiClient.get<LutCatalogResponse>("/lut/catalog", {
        signal,
      })
    : await apiClient.get<LutCatalogResponse>("/lut/catalog");
  return { ...response.data, native_brand_groups: [] };
}

/** 获取 LUT 详情目录，包含 manufacturer 分组与可搜索 tokens。 */
export async function fetchLutDetailsCatalog(
  options: ApiRequestOptions = {},
): Promise<LutDetailsCatalogResponse> {
  const response =
    options.suppressClientLog === true
      ? await apiClient.get<LutDetailsCatalogResponse>("/lut/details/catalog", {
          suppressClientLog: true,
        })
      : await apiClient.get<LutDetailsCatalogResponse>("/lut/details/catalog");
  return {
    ...response.data,
    groups: response.data.groups
      .map((group) => ({
        ...group,
        items: group.items.filter((item) => !isPredictiveLutSource(item.source_kind)),
      }))
      .filter((group) => group.items.length > 0),
  };
}

/** 上传一个本地 LUT 到 Custom 预设目录。 */
export async function uploadLocalLut(
  file: File,
): Promise<{ status: string; message: string; name: string }> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await apiClient.post<{
    status: string;
    message: string;
    name: string;
  }>("/lut/upload", formData, { timeout: 3_600_000 });
  return response.data;
}

/** 获取云端 LUT registry 目录。 */
export async function fetchCloudLutRegistryCatalog(
  request: CloudLutRegistryCatalogRequest = {},
): Promise<CloudLutRegistryCatalogResponse> {
  const response = await apiClient.get<CloudLutRegistryCatalogResponse>(
    "/lut-registry/catalog",
    {
      params: {
        ...(request.channels ? { channel: request.channels } : {}),
        ...(request.limit !== undefined ? { limit: request.limit } : {}),
        ...(request.offset !== undefined ? { offset: request.offset } : {}),
      },
    },
  );
  return response.data;
}

/** 安装一个云端 LUT registry 目录条目。 */
export async function installCloudLut(
  entry: CloudLutRegistryCatalogItem,
): Promise<CloudLutInstallRecord> {
  const request: CloudLutInstallRequest = {
    lut_id: entry.lut_id,
    revision_id: entry.revision_id,
  };
  const response = await apiClient.post<CloudLutInstallRecord>(
    "/lut-registry/install",
    request,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** 获取本机云端 LUT 同步状态。 */
export async function fetchCloudLutRegistryStatus(): Promise<CloudLutRegistryStatusResponse> {
  const response = await apiClient.get<CloudLutRegistryStatusResponse>(
    "/lut-registry/status",
  );
  return response.data;
}

/** 获取单个 LUT 的完整详情。 */
export async function fetchLutDetails(lutName: string): Promise<LutDetailsResponse> {
  const url = `/lut/${encodeURIComponent(lutName)}/details`;
  const headers = workflowHeaders("lut-details");
  const response = headers ? await apiClient.get<LutDetailsResponse>(url, { headers }) : await apiClient.get<LutDetailsResponse>(url);
  return response.data;
}

/** Predict a custom recipe color for a predictive source. */
export async function predictRecipeColor(
  lutName: string,
  request: RecipeColorPredictRequest,
): Promise<RecipeColorPredictResponse> {
  const response = await apiClient.post<RecipeColorPredictResponse>(
    `/lut/${encodeURIComponent(lutName)}/predict-recipe-color`,
    request,
    { timeout: 3_600_000 },
  );
  return response.data;
}

/** Search predictive candidate recipes by layer pattern. */
export async function searchRecipes(
  lutName: string,
  request: RecipeSearchRequest,
): Promise<RecipeSearchResponse> {
  const response = await apiClient.post<RecipeSearchResponse>(
    `/lut/${encodeURIComponent(lutName)}/search-recipes`,
    request,
    { timeout: 3_600_000 },
  );
  return response.data;
}
