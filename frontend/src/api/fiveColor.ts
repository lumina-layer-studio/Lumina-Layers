import apiClient from "./client";
import type { BaseColorsResponse, FiveColorQueryResponse, FiveColorQueryRequest } from "./types";

/** 获取指定 LUT 的基础颜色列表 */
export async function fetchBaseColors(lutName: string): Promise<BaseColorsResponse> {
  const response = await apiClient.get<BaseColorsResponse>(
    "/five-color/base-colors",
    { params: { lut_name: lutName } }
  );
  return response.data;
}

/** 查询 5 色组合结果 */
export async function queryFiveColor(request: FiveColorQueryRequest): Promise<FiveColorQueryResponse> {
  const response = await apiClient.post<FiveColorQueryResponse>(
    "/five-color/query",
    request
  );
  return response.data;
}

/** 清空 LUT 引擎缓存 */
export async function clearFiveColorCache(): Promise<{ success: boolean; message: string }> {
  const response = await apiClient.post<{ success: boolean; message: string }>(
    "/five-color/clear-cache"
  );
  return response.data;
}
