import type { ColorReplacementItem, LutColorEntry, PaletteEntry } from "../../api/types";
import { svgHoleCompensationOptions } from "../../constants/svgHoleCompensation";
import { computeAutoHeightMap, toAbsoluteReliefHeightMap } from "../../utils/colorUtils";
import type { SettingsState } from "../settingsStore";
import { newestEditorContentRevision } from "./editorRevision";
import { externalSpoolMaterial, scopedNativeFilamentProfiles } from "./nativeMaterialSelection";
import {
  buildConversionSourceParams,
  clampAbsoluteReliefHeightMap,
  getMaterialArchiveReliefMinimumTotalHeight,
  normalizePublicColorMode,
  resolveColorMatchingWeights,
  resolveMaterialPrintLayerCount,
  resolveRecipeAwareLayerCount,
} from "./sources";
import type { ConverterState } from "./types";
import { resolveConverterSettings } from "./project";

type SourceParams = NonNullable<ReturnType<typeof buildConversionSourceParams>>;

function buildConversionInputParams(
  state: ConverterState,
  settings: SettingsState,
  sourceParams: SourceParams,
) {

  return {
    ...sourceParams,
    color_layers:
      state.source_version === "material"
        ? resolveMaterialPrintLayerCount(state)
        : sourceParams.source_kind === "native_bundle"
          ? (sourceParams.color_layers ?? undefined)
          : (state.color_layers ?? undefined),
    layer_height_mm:
      state.source_version === "material"
        ? state.materialLayerHeightMm
        : sourceParams.source_kind === "native_bundle"
          ? (sourceParams.layer_height_mm ?? undefined)
          : (state.layer_height_mm ?? undefined),
    target_width_mm: state.target_width_mm,
    color_mode: normalizePublicColorMode(state.color_mode),
    modeling_mode: state.modeling_mode,
    quantize_colors: state.quantize_colors,
    high_precision_3d_preview: state.high_precision_3d_preview,
    enable_cleanup: state.enable_cleanup,
    enable_outline: state.enable_outline,
    outline_width: state.outline_width,
    svg_pixels_per_mm: settings.svgPixelsPerMm,
    ...svgHoleCompensationOptions(state),
    ...resolveColorMatchingWeights(state),
    use_lut_constrained: state.use_lut_constrained,
    auto_dynamic_range: state.auto_dynamic_range,
  };
}
function buildOutputParams(
  state: ConverterState,
  settings: SettingsState,
) {
  const spool = externalSpoolMaterial(state, settings);
  return {
    spacer_thick: state.spacer_thick,
    backing_infill_density_percent:
      state.backing_infill_density_percent,
    structure_mode: state.structure_mode,
    separate_backing: state.separate_backing,
    backing_output: state.separate_backing ? state.backingOutput : "same_project",
    enable_relief: state.enable_relief,
    enable_coating: state.enable_coating,
    coating_height_mm: state.coating_height_mm,
    printer_id: settings.printerModel,
    slicer: settings.slicerSoftware,
    nozzle_size: settings.nozzleSize,
    device_profile_id: settings.deviceProfileId,
    build_plate_id: settings.buildPlateId,
    custom_3mf_template_id: settings.custom3mfTemplateId,
    native_filament_profiles: scopedNativeFilamentProfiles(state, settings),
    ...(spool ? { external_spool_material: spool } : {}),
    enable_base_layer_height_modifier:
      settings.enableBaseLayerHeightModifier,
    enable_wipe_tower_auto_placement:
      settings.enableWipeTowerAutoPlacement,
  };
}
function buildSurfaceParams(state: ConverterState) {
  return state.modelSurfaceEnabled &&
    state.modelSurfaceModelFileId &&
    state.modelSurfaceSelection &&
    state.modelSurfaceFootprint
    ? {
      surface_model_file_id: state.modelSurfaceModelFileId,
      surface_selection_json: JSON.stringify(state.modelSurfaceSelection),
      surface_footprint_json: JSON.stringify(state.modelSurfaceFootprint),
      surface_placement_json: JSON.stringify(state.modelSurfacePlacement),
      surface_model_transform_json: JSON.stringify({
        rotation_deg: {
          x: state.modelSurfaceModelRotation.x_deg,
          y: state.modelSurfaceModelRotation.y_deg,
          z: state.modelSurfaceModelRotation.z_deg,
        },
      }),
    }
    : {};
}

function buildReliefParams(
  state: ConverterState,
) {
  const reliefMinimumTotalHeight =
    getMaterialArchiveReliefMinimumTotalHeight(state);
  const reliefHeightmapMaxHeight = state.enable_relief
    ? Math.max(
      state.spacer_thick + state.heightmap_max_height,
      reliefMinimumTotalHeight,
    )
    : state.heightmap_max_height;
  const reliefColorHeightMap =
    state.enable_relief && state.autoHeightMode !== "use-heightmap"
      ? clampAbsoluteReliefHeightMap(
        toAbsoluteReliefHeightMap(
          state.color_height_map,
          state.spacer_thick,
        ),
        reliefMinimumTotalHeight,
      )
      : state.enable_relief
        ? clampAbsoluteReliefHeightMap(
          state.color_height_map,
          reliefMinimumTotalHeight,
        )
        : undefined;
  return {
    height_mode: state.enable_relief ? (state.autoHeightMode === "use-heightmap" ? "heightmap" : "color") : undefined,
    color_height_map: reliefColorHeightMap,
    heightmap_max_height: reliefHeightmapMaxHeight,
  } as const;
}
export function buildPreviewParams(
  state: ConverterState,
  settings: SettingsState,
  sourceParams: SourceParams,
  previewReplacementRegions: ColorReplacementItem[],
) {
  settings = resolveConverterSettings(state, settings);
  const shouldReplayGlobalReplacements = previewReplacementRegions.length > 0;
  return {
    ...buildConversionInputParams(state, settings, sourceParams),
    enable_smooth_vector_preview:
      settings.enableSmoothVectorPreview,
    is_dark: settings.theme === "dark",
    large_format_enabled: state.largeFormatEnabled,
    ...(shouldReplayGlobalReplacements
      ? { replacement_regions: previewReplacementRegions }
      : {}),
    ...buildSurfaceParams(state),
  };
}
export function buildGenerateParams(
  state: ConverterState,
  settings: SettingsState,
  sourceParams: SourceParams,
  mergedReplacements: ColorReplacementItem[] | undefined,
  confirmedEditorContentRevision: number | undefined,
) {
  settings = resolveConverterSettings(state, settings);
  const input = buildConversionInputParams(state, settings, sourceParams);
  return {
    ...input,
    ...buildOutputParams(state, settings),
    ...buildReliefParams(state),
    color_layers: resolveRecipeAwareLayerCount(
      state,
      input.color_layers,
    ),
    is_dark: settings.theme === "dark",
    add_loop: state.add_loop,
    loop_width: state.loop_width,
    loop_length: state.loop_length,
    loop_hole: state.loop_hole,
    loop_angle: state.loop_angle,
    loop_offset_x: state.loop_offset_x,
    loop_offset_y: state.loop_offset_y,
    loop_position_preset: state.loop_position_preset,
    enable_cloisonne: state.enable_cloisonne,
    wire_width_mm: state.wire_width_mm,
    wire_height_mm: state.wire_height_mm,
    enable_fridge_magnet: state.enable_fridge_magnet,
    fridge_magnets:
      state.enable_fridge_magnet && state.fridge_magnets.length > 0
        ? state.fridge_magnets
        : undefined,
    replacement_regions:
      mergedReplacements && mergedReplacements.length > 0
        ? mergedReplacements
        : undefined,
    recipe_overrides:
      state.recipe_overrides.length > 0
        ? state.recipe_overrides
        : undefined,
    free_color_set:
      state.free_color_set.size > 0
        ? Array.from(state.free_color_set).map((h) => `#${h}`)
        : undefined,
    use_cached_matched_rgb: state.regionReplacementCount > 0,
    editor_content_revision: newestEditorContentRevision(
      state.selectionDocument?.editor_content_revision,
      confirmedEditorContentRevision,
    ),
    selection_revision:
      state.selectionDocument?.selection_revision ?? undefined,
    ...buildSurfaceParams(state),
  } as const;
}
export function buildBatchParams(
  state: ConverterState,
  settings: SettingsState,
  sourceParams: SourceParams,
) {
  settings = resolveConverterSettings(state, settings);
  const relief = buildReliefParams(state);
  return {
    ...buildConversionInputParams(state, settings, sourceParams),
    ...buildOutputParams(state, settings),
    color_mode: state.color_mode,
    ...(state.enable_relief
      ? {
        height_mode: "color",
        color_height_map: relief.color_height_map,
        heightmap_max_height: relief.heightmap_max_height,
      }
      : {}),
  };
}

export function buildMissingAutoReliefHeightMap(
  state: Pick<
    ConverterState,
    | "enable_relief"
    | "autoHeightMode"
    | "color_height_map"
    | "heightmap_max_height"
    | "palette"
    | "lutColors"
  >,
  paletteOverride?: PaletteEntry[],
): Record<string, number> | null {
  if (!state.enable_relief) return null;
  if (state.autoHeightMode === "use-heightmap") return null;
  if (Object.keys(state.color_height_map).length > 0) return null;
  const palette =
    paletteOverride ??
    (state.palette.length > 0
      ? state.palette
      : state.lutColors.map((color: LutColorEntry) => {
        const hex = color.hex.replace(/^#/, "").toLowerCase();
        return {
          quantized_hex: hex,
          matched_hex: hex,
          pixel_count: 0,
          percentage: 0,
        };
      }));
  if (palette.length === 0) return null;
  return computeAutoHeightMap(
    palette,
    state.autoHeightMode,
    state.heightmap_max_height,
  );
}
