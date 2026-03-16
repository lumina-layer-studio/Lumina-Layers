import apiClient from "./client";
import type { LutInfoResponse, MergeRequest, MergeResponse } from "./types";

/** 获取指定 LUT 的颜色模式和颜色数量 */
export async function fetchLutInfo(
  lutName: string
): Promise<LutInfoResponse> {
  const response = await apiClient.get<LutInfoResponse>(
    `/lut/${encodeURIComponent(lutName)}/info`
  );
  return response.data;
}

/** 执行 LUT 合并操作 */
export async function mergeLuts(
  request: MergeRequest
): Promise<MergeResponse> {
  const response = await apiClient.post<MergeResponse>(
    "/lut/merge",
    request,
    { timeout: 600_000 }
  );
  return response.data;
}
