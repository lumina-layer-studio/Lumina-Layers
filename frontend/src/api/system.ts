import apiClient from "./client";
import type {
  ClearCacheResponse,
  UserSettings,
  UserSettingsResponse,
  SaveSettingsResponse,
  StatsResponse,
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
