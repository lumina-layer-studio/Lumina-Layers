import apiClient from "./client";
import type {
  MaterialCacheOverviewResponse,
  MaterialDynamicCacheDeleteResponse,
  MaterialDynamicCachePrepareResponse,
  MaterialGamutContributionsResponse,
  MaterialGamutCoverageResponse,
  MaterialLayerMode,
} from "./types";

/**
 * Material combination gamut-coverage and cache-overview client.
 * 耗材组合色域覆盖与缓存概览客户端。
 */

/**
 * One material combination, in fixed or dynamic layer mode.
 * 一个耗材组合（固定或动态层数模式）。
 */
export interface MaterialComboSelection {
  materialDirectoryNames: string[];
  layerMode: MaterialLayerMode;
  /** Fixed-mode layer count. 固定模式层数。 */
  layerCount: number;
  /** Dynamic-mode smallest layer count. 动态模式最小层数。 */
  minLayerCount: number;
  /** Dynamic-mode largest layer count. 动态模式最大层数。 */
  maxLayerCount: number;
  layerHeightMm: number;
  substrate: "white" | "black";
  /** Dynamic-mode backing material, already resolved to a selected name. */
  backingDirName: string | null;
}

function comboFormData(combo: MaterialComboSelection): FormData {
  const fd = new FormData();
  fd.append("material_directory_names", JSON.stringify(combo.materialDirectoryNames));
  fd.append("layer_mode", combo.layerMode);
  fd.append("layer_height_mm", String(combo.layerHeightMm));
  fd.append("substrate", combo.substrate);
  if (combo.layerMode === "dynamic") {
    fd.append("min_layer_count", String(combo.minLayerCount));
    fd.append("max_layer_count", String(combo.maxLayerCount));
    if (combo.backingDirName) {
      fd.append("backing_material_directory_name", combo.backingDirName);
    }
  } else {
    fd.append("layer_count", String(combo.layerCount));
  }
  return fd;
}

/** Measure the sRGB coverage of a combination. 测量组合的 sRGB 覆盖率。 */
export async function fetchMaterialGamutCoverage(
  combo: MaterialComboSelection,
  options?: { maxPoints?: number; signal?: AbortSignal },
): Promise<MaterialGamutCoverageResponse> {
  const fd = comboFormData(combo);
  if (options?.maxPoints != null) fd.append("max_points", String(options.maxPoints));
  const response = await apiClient.post<MaterialGamutCoverageResponse>(
    "/extractor/material-gamut/coverage",
    fd,
    { timeout: 0, signal: options?.signal },
  );
  return response.data;
}

/** Coverage each material adds, by removing it in turn. 逐个移除耗材得到其贡献。 */
export async function fetchMaterialGamutContributions(
  combo: MaterialComboSelection,
  options?: { signal?: AbortSignal },
): Promise<MaterialGamutContributionsResponse> {
  const response = await apiClient.post<MaterialGamutContributionsResponse>(
    "/extractor/material-gamut/contributions",
    comboFormData(combo),
    { timeout: 0, signal: options?.signal },
  );
  return response.data;
}

/** Which caches are saved for a combination (metadata only). 组合已保存的缓存。 */
export async function fetchMaterialCacheOverview(
  combo: MaterialComboSelection,
  options?: { signal?: AbortSignal },
): Promise<MaterialCacheOverviewResponse> {
  const response = await apiClient.post<MaterialCacheOverviewResponse>(
    "/extractor/material-cache/overview",
    comboFormData(combo),
    { timeout: 0, signal: options?.signal },
  );
  return response.data;
}

/** Build and save everything a dynamic conversion needs. 预构建动态转换所需数据。 */
export async function prepareMaterialDynamicCache(
  combo: MaterialComboSelection,
): Promise<MaterialDynamicCachePrepareResponse> {
  const response = await apiClient.post<MaterialDynamicCachePrepareResponse>(
    "/extractor/material-dynamic-cache/prepare",
    comboFormData(combo),
    { timeout: 0 },
  );
  return response.data;
}

/** Delete the saved dynamic catalog for these settings. 删除当前设置的动态目录。 */
export async function deleteMaterialDynamicCache(
  combo: MaterialComboSelection,
): Promise<MaterialDynamicCacheDeleteResponse> {
  const response = await apiClient.post<MaterialDynamicCacheDeleteResponse>(
    "/extractor/material-dynamic-cache/delete",
    comboFormData(combo),
    { timeout: 0 },
  );
  return response.data;
}
