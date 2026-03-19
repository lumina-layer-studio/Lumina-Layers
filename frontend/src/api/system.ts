import apiClient from "./client";
import type {
  ClearCacheResponse,
  UserSettings,
  UserSettingsResponse,
  SaveSettingsResponse,
  StatsResponse,
  PrinterInfo,
  PrinterListResponse,
  SlicerOption,
  SlicerListResponse,
} from "./types";

/** 调用后端清除系统缓存，返回清理统计信息 */
export async function clearCache(): Promise<ClearCacheResponse> {
  const response = await apiClient.post<ClearCacheResponse>(
    "/system/clear-cache"
  );
  return response.data;
}

/** 获取用户设置 */
export async function getSettings(): Promise<UserSettingsResponse> {
  const response = await apiClient.get<UserSettingsResponse>("/system/settings");
  return response.data;
}

/** 保存用户设置 */
export async function saveSettings(settings: UserSettings): Promise<SaveSettingsResponse> {
  const response = await apiClient.post<SaveSettingsResponse>(
    "/system/settings",
    settings
  );
  return response.data;
}

/** 获取使用统计数据 */
export async function getStats(): Promise<StatsResponse> {
  const response = await apiClient.get<StatsResponse>("/system/stats");
  return response.data;
}

/** 获取所有支持的打印机型号列表 */
export async function getPrinters(): Promise<PrinterInfo[]> {
  const response = await apiClient.get<PrinterListResponse>("/system/printers");
  return response.data.printers;
}

/** 获取所有支持的切片器软件列表 */
export async function getSlicers(): Promise<SlicerOption[]> {
  const response = await apiClient.get<SlicerListResponse>("/system/slicers");
  return response.data.slicers;
}
