import apiClient, { downloadResourceBlob } from "../api/client";
import { exportGradientCardMaterials } from "../api/extractor";
import { boundProjectResources } from "../stores/converter/project";
import { buildConversionSourceParams } from "../stores/converter/sources";
import type { ConverterState } from "../stores/converter/types";

export async function captureProjectTemplate(templateId: string | null): Promise<File | null> {
  if (!templateId) return null;
  const response = await apiClient.get(`/projects/templates/${encodeURIComponent(templateId)}`);
  return new File([JSON.stringify(response.data)], "3mf-template.json", { type: "application/json" });
}

export async function restoreProjectTemplate(template: File) {
  const form = new FormData();
  form.append("template", template);
  const response = await apiClient.post<{ template_id: string; session_id: string }>("/projects/templates", form);
  return response.data;
}

export async function captureConverterResources(state: ConverterState): Promise<{ lut: File | null; materials: File | null }> {
  const bound = boundProjectResources(state);
  if (state.source_version === "material") {
    if (bound.materials) return bound;
    if (!state.selectedMaterialDirNames.length) return { lut: null, materials: null };
    const exported = await exportGradientCardMaterials(state.selectedMaterialDirNames);
    const blob = await downloadResourceBlob(exported.download_url);
    return { lut: null, materials: new File([blob], "materials.zip", { type: "application/zip" }) };
  }
  if (bound.lut) return bound;
  const source = buildConversionSourceParams(state);
  if (!source || (source.source_kind === "legacy_single" && !source.lut_name)) return { lut: null, materials: null };
  const result = await apiClient.post<Blob>("/lut/project-source", source, { responseType: "blob", timeout: 60_000 });
  const filename = String(result.headers["x-project-filename"] ?? "source.npz");
  return { lut: new File([result.data], filename, { type: "application/octet-stream" }), materials: null };
}
