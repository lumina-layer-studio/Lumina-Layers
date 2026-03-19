import apiClient from "./client";
import type { VectorizeParams, VectorizeResponse, VectorizeDefaultsResponse } from "./types";

export async function vectorizeImage(
  image: File,
  params: VectorizeParams,
  signal?: AbortSignal,
): Promise<VectorizeResponse> {
  const fd = new FormData();
  fd.append("image", image);
  fd.append("params", JSON.stringify(params));

  const response = await apiClient.post<VectorizeResponse>(
    "/vectorize",
    fd,
    { timeout: 0, signal },
  );
  return response.data;
}

export async function fetchVectorizeDefaults(): Promise<VectorizeDefaultsResponse> {
  const response = await apiClient.get<VectorizeDefaultsResponse>("/vectorize/defaults");
  return response.data;
}
