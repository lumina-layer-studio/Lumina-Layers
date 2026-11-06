import type { PreviewResponse } from "../../api/types";
import { normalizeResourceUrl } from "../../utils/resourceUrl";
import type { ConverterState } from "./types";

/** Shared publication of a fresh preview, including a prepared project open. */
export function previewResultState(state: ConverterState, response: PreviewResponse): Partial<ConverterState> {
  const previewUrl = normalizeResourceUrl(response.preview_url);
  return {
    sessionId: response.session_id,
    previewImageUrl: previewUrl,
    originalPreviewUrl: previewUrl,
    previewBaseImageUrl: normalizeResourceUrl(response.dimensions?.preview_raw_url) ?? previewUrl,
    previewGlbUrl: normalizeResourceUrl(response.preview_glb_url),
    lutMatchMode: response.lut_match_mode ?? "legacy",
    lutMatchInfo: response.lut_match_info ?? { match_mode: response.lut_match_mode ?? "legacy" },
    palette: (response.palette ?? []).map((entry) => ({
      ...entry,
      quantized_hex: entry.quantized_hex.replace(/^#/, ""),
      matched_hex: entry.matched_hex.replace(/^#/, ""),
    })),
    colorContours: response.contours ?? {},
    materialDynamicRecipes: response.material_dynamic_recipes ?? [],
    materialLayerBenefitCurve: response.material_layer_benefit_curve ?? [],
    materialLayerBenefitScope: response.material_layer_benefit_scope ?? "all_printable_pixels",
    materialLayerBenefitPixelCount: response.material_layer_benefit_pixel_count ?? 0,
    previewPixelWidth: response.dimensions?.width ?? null,
    previewPixelHeight: response.dimensions?.height ?? null,
    preview_width_mm: state.target_width_mm,
    preview_height_mm: state.target_height_mm,
    preview_spacer_thick: state.spacer_thick,
    previewPerformanceTiming: response.performance_timing ?? null,
    previewWarnings: response.warnings ?? [],
    hasManualPreview: true,
    previewAutoRefreshPending: false,
  };
}
