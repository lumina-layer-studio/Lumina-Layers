import { createProjectAsset } from "./identity";
import type { ProjectAsset, ProjectSnapshot } from "./types";

export function projectFile(snapshot: ProjectSnapshot, assetId: unknown): File | null {
  if (assetId === null || assetId === undefined) return null;
  if (typeof assetId !== "string" || !snapshot.assets[assetId]) throw new Error("Project resource is missing");
  const asset = snapshot.assets[assetId];
  return new File([new Uint8Array(asset.data)], asset.filename ?? asset.assetId, { type: asset.mediaType });
}

export async function fileAsset(id: string, file: File, role: "asset" | "resource" = "asset"): Promise<ProjectAsset> {
  return createProjectAsset(id, new Uint8Array(await file.arrayBuffer()), file.type || "application/octet-stream", file.name, role);
}
