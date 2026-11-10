import apiClient from "./client";
import { workflowHeaders } from "../project/workflowRuntime";
import type {
  BaseColorsResponse,
  FiveColorMatchRequest,
  FiveColorMatchResponse,
  FiveColorQueryResponse,
  FiveColorQueryRequest,
  RecipeSwatchRequest,
  RecipeSwatchResponse,
} from "./types";

/** 获取指定 LUT 的基础颜色列表 */
export async function fetchBaseColors(lutName: string): Promise<BaseColorsResponse> {
  const response = await apiClient.get<BaseColorsResponse>(
    "/five-color/base-colors",
    { params: { lut_name: lutName }, headers: workflowHeaders("five-color") }
  );
  return response.data;
}

/** 查询 5 色组合结果 */
export async function queryFiveColor(request: FiveColorQueryRequest): Promise<FiveColorQueryResponse> {
  const response = await apiClient.post<FiveColorQueryResponse>(
    "/five-color/query",
    request, { headers: workflowHeaders("five-color") }
  );
  return response.data;
}

/** 按目标 Hex 色值匹配最近五色配方 */
export async function matchFiveColorByHex(request: FiveColorMatchRequest): Promise<FiveColorMatchResponse> {
  const response = await apiClient.post<FiveColorMatchResponse>(
    "/five-color/match-color",
    request, { headers: workflowHeaders("five-color") }
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

/** 生成配方色块验证 3MF */
export async function generateRecipeSwatch(request: RecipeSwatchRequest): Promise<RecipeSwatchResponse> {
  const response = await apiClient.post<RecipeSwatchResponse>(
    "/five-color/generate-swatch",
    request, { headers: workflowHeaders("five-color") }
  );
  return response.data;
}
