import apiClient from "./client";
import type { ExtractResponse, ManualFixResponse } from "./types";

/** 提取颜色 - multipart/form-data */
export async function extractColors(
  image: File,
  params: {
    corner_points: Array<[number, number]>;
    color_mode: string;
    page: string;
    offset_x: number;
    offset_y: number;
    zoom: number;
    distortion: number;
    white_balance: boolean;
    vignette_correction: boolean;
  }
): Promise<ExtractResponse> {
  const fd = new FormData();
  fd.append("image", image);
  fd.append("corner_points", JSON.stringify(params.corner_points));
  fd.append("color_mode", params.color_mode);
  fd.append("page", params.page);
  fd.append("offset_x", String(params.offset_x));
  fd.append("offset_y", String(params.offset_y));
  fd.append("zoom", String(params.zoom));
  fd.append("distortion", String(params.distortion));
  fd.append("white_balance", String(params.white_balance));
  fd.append("vignette_correction", String(params.vignette_correction));

  const response = await apiClient.post<ExtractResponse>(
    "/extractor/extract",
    fd,
    { timeout: 600_000 }
  );
  return response.data;
}

/** 手动修正 LUT 单元格 - JSON */
export async function manualFixCell(
  sessionId: string,
  cellCoord: [number, number],
  overrideColor: string
): Promise<ManualFixResponse> {
  const response = await apiClient.post<ManualFixResponse>(
    "/extractor/manual-fix",
    { session_id: sessionId, cell_coord: cellCoord, override_color: overrideColor }
  );
  return response.data;
}

/** 合并 8 色双页 LUT */
export async function mergeEightColor(): Promise<ExtractResponse> {
  const response = await apiClient.post<ExtractResponse>(
    "/extractor/merge-8color",
    {},
    { timeout: 600_000 }
  );
  return response.data;
}

/** 合并 5 色扩展双页 LUT */
export async function mergeFiveColorExtended(): Promise<ExtractResponse> {
  const response = await apiClient.post<ExtractResponse>(
    "/extractor/merge-5color-extended",
    {},
    { timeout: 600_000 }
  );
  return response.data;
}
