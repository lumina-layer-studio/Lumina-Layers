import apiClient from "./client";
import type { CalibrationGenerateRequest, CalibrationResponse } from "./types";

/** 提交校准板生成请求，返回下载链接和预览信息 */
export async function calibrationGenerate(
  request: CalibrationGenerateRequest
): Promise<CalibrationResponse> {
  const response = await apiClient.post<CalibrationResponse>(
    "/calibration/generate",
    request,
    { timeout: 60_000 }
  );
  return response.data;
}
