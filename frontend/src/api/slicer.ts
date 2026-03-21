import apiClient from "./client";
import type {
  SlicerDetectResponse,
  SlicerLaunchRequest,
  SlicerLaunchResponse,
} from "./types";

/** 检测系统已安装的切片软件 */
export async function detectSlicers(): Promise<SlicerDetectResponse> {
  const response = await apiClient.get<SlicerDetectResponse>("/slicer/detect");
  return response.data;
}

/** 启动指定切片软件打开 3MF 文件 */
export async function launchSlicer(
  request: SlicerLaunchRequest
): Promise<SlicerLaunchResponse> {
  const response = await apiClient.post<SlicerLaunchResponse>(
    "/slicer/launch",
    request
  );
  return response.data;
}
