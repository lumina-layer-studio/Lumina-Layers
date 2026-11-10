import type { ConverterState } from "../stores/converter/store";
import type {
  AdvancedParams,
  AdvancedParamsColorReplacement,
  AdvancedParamsDimensions,
  AdvancedParamsFridgeMagnet,
  AdvancedParamsFull,
  AdvancedParamsGeneration,
  AdvancedParamsLargeFormat,
  AdvancedParamsLoop,
  AdvancedParamsModelSurface,
  AdvancedParamsCloisonne,
  AdvancedParamsCoating,
  AdvancedParamsOutline,
  AdvancedParamsPuzzle,
  AdvancedParamsRelief,
  ColorReplacementScalarItem,
  FileMetadata,
  FridgeMagnetScalarItem,
} from "../types/actionHistory";
import type {
  ColorReplacementItem,
  FridgeMagnetItem,
  RecipeOverrideItem,
} from "../api/types";
import {
  MATERIAL_DELTA_E00_TOLERANCE_DEFAULT,
  SVG_PIXELS_PER_MM_DEFAULT,
} from "../stores/settingsStore";
import { colorRemapToReplacementRegions } from "./colorUtils";
import { svgHoleCompensationOptions } from "../constants/svgHoleCompensation";

/**
 * Options for generation settings captured in the snapshot.
 * 构建选项：传入生成设置以补齐快照。
 */
export interface BuildAdvancedParamsOptions {
  /** Legacy option retained for callers; snapshots are never size-trimmed. */
  maxBytes: number;
  svgPixelsPerMm?: number;
  materialDeltaE00Tolerance?: number;
  enableWipeTowerAutoPlacement?: boolean;
  externalSpoolMaterial?: string;
}

/**
 * Build a grouped `AdvancedParams` snapshot from the converter store
 * state. Returns `null` when the converter tab is not active. The builder
 * is deterministic: identical `(state, activeTab, options.maxBytes)` tuples
 * produce byte-identical JSON output.
 *
 * The function applies, in order:
 *   1. Disabled-toggle → null rules for each of the 8 feature groups that
 *      have a master switch (relief, outline, cloisonne, coating, loop,
 *      fridge_magnet, puzzle, large_format).
 *   2. File → FileMetadata conversion (`name`, `size`, `type` only; never
 *      Blob or data URL).
 * All parameter collections are preserved without count or byte truncation.
 *
 * 根据 converter store 状态构建分组化的 AdvancedParams 快照；非 converter Tab
 * 时返回 null。对于相同的 (state, activeTab, maxBytes) 组合，输出是字节级确定的。
 * 依次执行：各功能组"关闭即置 null"规则 → File 转 FileMetadata。
 * 参数集合完整保留，不再按数量或字节裁剪。
 */
export function buildAdvancedParams(
  state: ConverterState,
  activeTab: string,
  options: BuildAdvancedParamsOptions,
): AdvancedParams | null {
  if (activeTab !== "converter") {
    return null;
  }

  return buildFullParams(state, options);
}

// ---------------------------------------------------------------------------
// Full params assembly (no byte trimming)
// 完整参数组装（未进行字节裁剪）
// ---------------------------------------------------------------------------

function buildFullParams(
  state: ConverterState,
  options: BuildAdvancedParamsOptions,
): AdvancedParamsFull {
  return {
    dimensions: buildDimensions(state),
    generation: buildGeneration(state, options),
    relief: buildRelief(state),
    outline: buildOutline(state),
    cloisonne: buildCloisonne(state),
    coating: buildCoating(state),
    loop: buildLoop(state),
    fridge_magnet: buildFridgeMagnet(state),
    puzzle: buildPuzzle(state),
    large_format: buildLargeFormat(state),
    model_surface: buildModelSurface(state),
    color_replacement: buildColorReplacement(state),
  };
}

function buildDimensions(state: ConverterState): AdvancedParamsDimensions {
  return {
    target_width_mm: state.target_width_mm,
    target_height_mm: state.target_height_mm,
    spacer_thick: state.spacer_thick,
    base_spacer_thick: state.base_spacer_thick,
    backing_infill_density_percent:
      state.backing_infill_density_percent,
  };
}

function buildGeneration(
  state: ConverterState,
  options: BuildAdvancedParamsOptions,
): AdvancedParamsGeneration {
  const isMaterialSource = state.source_version === "material";
  const wipeTowerWarningCodes = [...state.generateWarnings];
  return {
    structure_mode: state.structure_mode,
    modeling_mode: state.modeling_mode,
    color_layers: state.color_layers,
    layer_height_mm: state.layer_height_mm,
    model_enable: state.model_enable,
    model_only: state.model_only,
    model_threshold: state.model_threshold,
    model_margin: state.model_margin,
    quantize_colors: state.quantize_colors,
    quantize_colors_unlocked: state.quantize_colors_unlocked,
    high_precision_3d_preview: state.high_precision_3d_preview,
    enable_cleanup: state.enable_cleanup,
    ...svgHoleCompensationOptions(state),
    svg_pixels_per_mm:
      typeof options.svgPixelsPerMm === "number"
        ? options.svgPixelsPerMm
        : SVG_PIXELS_PER_MM_DEFAULT,
    hue_enable: state.hue_enable,
    chroma_gate: state.chroma_gate,
    use_lut_constrained: state.use_lut_constrained,
    auto_dynamic_range: state.auto_dynamic_range,
    separate_backing: state.separate_backing,
    backing_output: state.backingOutput,
    material_dynamic_layer_count_enabled:
      isMaterialSource && state.materialDynamicLayerCountEnabled,
    material_min_layer_count: isMaterialSource
      ? state.materialMinLayerCount
      : null,
    material_max_layer_count: isMaterialSource
      ? state.materialMaxLayerCount
      : null,
    material_backing_material_dir_name: isMaterialSource
      ? state.materialBackingMaterialDirName
      : null,
    material_delta_e00_tolerance: isMaterialSource
      ? typeof options.materialDeltaE00Tolerance === "number"
        ? options.materialDeltaE00Tolerance
        : MATERIAL_DELTA_E00_TOLERANCE_DEFAULT
      : null,
    enable_wipe_tower_auto_placement:
      options.enableWipeTowerAutoPlacement !== false,
    native_filament_profiles: { ...state.native_filament_profiles },
    ...(options.externalSpoolMaterial ? { external_spool_material: options.externalSpoolMaterial } : {}),
    native_filament_profile_scope: state.nativeFilamentProfileScope
      ? { ...state.nativeFilamentProfileScope }
      : null,
    ...(wipeTowerWarningCodes.length > 0
      ? { wipe_tower_warning_codes: wipeTowerWarningCodes }
      : {}),
  };
}

function buildRelief(state: ConverterState): AdvancedParamsRelief {
  const hasHeightmapThumbnail = state.heightmapThumbnailUrl !== null;

  if (!state.enable_relief) {
    return {
      enable_relief: false,
      color_height_map: null,
      heightmap_max_height: null,
      autoHeightMode: null,
      heightmapFile: null,
      hasHeightmapThumbnail,
    };
  }

  return {
    enable_relief: true,
    color_height_map: Object.keys(state.color_height_map).length > 0 ? { ...state.color_height_map } : null,
    heightmap_max_height: state.heightmap_max_height,
    autoHeightMode: state.autoHeightMode ?? null,
    heightmapFile: serializeFileMetadata(state.heightmapFile),
    hasHeightmapThumbnail,
  };
}

function buildOutline(state: ConverterState): AdvancedParamsOutline {
  if (!state.enable_outline) {
    return { enable_outline: false, outline_width: null };
  }
  return {
    enable_outline: true,
    outline_width: state.outline_width,
  };
}

function buildCloisonne(state: ConverterState): AdvancedParamsCloisonne {
  if (!state.enable_cloisonne) {
    return {
      enable_cloisonne: false,
      wire_width_mm: null,
      wire_height_mm: null,
    };
  }
  return {
    enable_cloisonne: true,
    wire_width_mm: state.wire_width_mm,
    wire_height_mm: state.wire_height_mm,
  };
}

function buildCoating(state: ConverterState): AdvancedParamsCoating {
  if (!state.enable_coating) {
    return { enable_coating: false, coating_height_mm: null };
  }
  return {
    enable_coating: true,
    coating_height_mm: state.coating_height_mm,
  };
}

function buildLoop(state: ConverterState): AdvancedParamsLoop {
  if (!state.add_loop) {
    return {
      add_loop: false,
      loop_width: null,
      loop_length: null,
      loop_hole: null,
      loop_angle: null,
      loop_offset_x: null,
      loop_offset_y: null,
      loop_position_preset: null,
    };
  }
  return {
    add_loop: true,
    loop_width: state.loop_width,
    loop_length: state.loop_length,
    loop_hole: state.loop_hole,
    loop_angle: state.loop_angle,
    loop_offset_x: state.loop_offset_x,
    loop_offset_y: state.loop_offset_y,
    loop_position_preset: state.loop_position_preset,
  };
}

function buildFridgeMagnet(state: ConverterState): AdvancedParamsFridgeMagnet {
  if (!state.enable_fridge_magnet) {
    return {
      enable_fridge_magnet: false,
      selectedFridgeMagnetId: null,
      fridge_magnets: null,
    };
  }
  return {
    enable_fridge_magnet: true,
    selectedFridgeMagnetId: state.selectedFridgeMagnetId ?? null,
    fridge_magnets: serializeFridgeMagnets(state.fridge_magnets),
  };
}

function buildPuzzle(state: ConverterState): AdvancedParamsPuzzle {
  if (!state.puzzleEnabled) {
    return {
      puzzleEnabled: false,
      puzzleStyle: null,
      puzzleSizingMode: null,
      pieceWidthMm: null,
      pieceHeightMm: null,
      puzzleRows: null,
      puzzleCols: null,
      targetPieceCount: null,
      connectorStyle: null,
      labelsEnabled: null,
      engraveBackLabels: null,
      irregularityStrength: null,
      minNeckWidthMm: null,
    };
  }
  return {
    puzzleEnabled: true,
    puzzleStyle: state.puzzleStyle,
    puzzleSizingMode: state.puzzleSizingMode,
    pieceWidthMm: state.pieceWidthMm,
    pieceHeightMm: state.pieceHeightMm,
    puzzleRows: state.puzzleRows,
    puzzleCols: state.puzzleCols,
    targetPieceCount: state.targetPieceCount,
    connectorStyle: state.connectorStyle,
    labelsEnabled: state.labelsEnabled,
    engraveBackLabels: state.engraveBackLabels,
    irregularityStrength: state.irregularityStrength,
    minNeckWidthMm: state.minNeckWidthMm,
  };
}

function buildLargeFormat(state: ConverterState): AdvancedParamsLargeFormat {
  if (!state.largeFormatEnabled) {
    return {
      largeFormatEnabled: false,
      tileWidthMm: null,
      tileHeightMm: null,
    };
  }
  return {
    largeFormatEnabled: true,
    tileWidthMm: state.tileWidthMm,
    tileHeightMm: state.tileHeightMm,
  };
}

function buildModelSurface(
  state: ConverterState,
): AdvancedParamsModelSurface {
  if (!state.modelSurfaceEnabled) {
    return {
      enabled: false,
      model_file: null,
      model_file_id: null,
      selection_id: null,
      selected_face_count: null,
      footprint: null,
      placement: null,
      model_rotation: null,
    };
  }

  const selection = state.modelSurfaceSelection;
  const footprint = state.modelSurfaceFootprint;
  const selectedFaceCount =
    readFiniteNumber(selection, "face_count") ??
    readArrayLength(selection, "face_indices");
  const footprintWidth = readFiniteNumber(footprint, "bounds_width_mm");
  const footprintHeight = readFiniteNumber(footprint, "bounds_height_mm");
  const footprintHoleCount =
    readFiniteNumber(footprint, "hole_count") ??
    readArrayLength(footprint, "holes");

  return {
    enabled: true,
    model_file: serializeFileMetadata(state.modelSurfaceFile),
    model_file_id: state.modelSurfaceModelFileId,
    selection_id: state.modelSurfaceSelectionId,
    selected_face_count: selectedFaceCount,
    footprint:
      footprintWidth !== null ||
      footprintHeight !== null ||
      footprintHoleCount !== null
        ? {
            width_mm: footprintWidth,
            height_mm: footprintHeight,
            hole_count: footprintHoleCount,
          }
        : null,
    placement: {
      mode: state.modelSurfacePlacement.mode,
      offset_x_mm: state.modelSurfacePlacement.offset_x_mm,
      offset_y_mm: state.modelSurfacePlacement.offset_y_mm,
      scale: state.modelSurfacePlacement.scale,
      rotation_deg: state.modelSurfacePlacement.rotation_deg,
      inset_mm: state.modelSurfacePlacement.inset_mm,
    },
    model_rotation: {
      x_deg: state.modelSurfaceModelRotation.x_deg,
      y_deg: state.modelSurfaceModelRotation.y_deg,
      z_deg: state.modelSurfaceModelRotation.z_deg,
    },
  };
}

function buildColorReplacement(
  state: ConverterState,
): AdvancedParamsColorReplacement {
  const liveReplacementRegions = colorRemapToReplacementRegions(
    state.colorRemapMap,
    state.palette,
  );
  const globalReplacementRegions = mergeGlobalReplacementRegions(
    state.replacement_regions,
    liveReplacementRegions,
  );
  return {
    replacement_regions: serializeReplacementRegions(globalReplacementRegions),
    spatial_edit_count: Number.isFinite(state.regionReplacementCount)
      ? Math.max(0, Math.trunc(state.regionReplacementCount))
      : 0,
    free_color_set: state.free_color_set.size > 0 ? Array.from(state.free_color_set, ensureHash) : null,
    recipe_overrides: serializeRecipeOverrides(state.recipe_overrides),
  };
}

// ---------------------------------------------------------------------------
// Serialization helpers
// 序列化辅助
// ---------------------------------------------------------------------------

function serializeFileMetadata(file: File | null): FileMetadata | null {
  if (!file) return null;
  return {
    name: file.name,
    size: file.size,
    type: file.type,
  };
}

function readFiniteNumber(
  value: Record<string, unknown> | null,
  key: string,
): number | null {
  const candidate = value?.[key];
  return typeof candidate === "number" && Number.isFinite(candidate)
    ? candidate
    : null;
}

function readArrayLength(
  value: Record<string, unknown> | null,
  key: string,
): number | null {
  const candidate = value?.[key];
  return Array.isArray(candidate) ? candidate.length : null;
}

function ensureHash(hex: string): string {
  return hex.startsWith("#") ? hex : `#${hex}`;
}

function normalizeReplacementSource(hex: string): string {
  return hex.trim().replace(/^#/, "").toLowerCase();
}

/**
 * Merge persisted and live global remaps by the source color used downstream.
 * Live store mappings are authoritative because they reflect the latest user
 * choice; deduplicating before serialization prevents stale duplicates from
 * consuming the 32-item telemetry allowance.
 *
 * 按下游实际使用的源色合并持久化与实时全局映射。实时映射代表用户最新选择，
 * 因此覆盖旧记录，保证快照反映实际使用的替换规则。
 */
function mergeGlobalReplacementRegions(
  persisted: ColorReplacementItem[],
  live: ColorReplacementItem[],
): ColorReplacementItem[] {
  const bySource = new Map<string, ColorReplacementItem>();
  for (const item of [...persisted, ...live]) {
    const source =
      normalizeReplacementSource(item.matched_hex) ||
      normalizeReplacementSource(item.quantized_hex);
    bySource.set(source, item);
  }
  return Array.from(bySource.values());
}

function serializeFridgeMagnets(magnets: FridgeMagnetItem[]): FridgeMagnetScalarItem[] | null {
  if (magnets.length === 0) {
    return null;
  }
  return magnets.map((item) => ({
    id: item.id,
    shape: item.shape,
    preset_key: item.preset_key,
    diameter_mm: item.diameter_mm,
    width_mm: item.width_mm,
    height_mm: item.height_mm,
    thickness_mm: item.thickness_mm,
    center_x_mm: item.center_x_mm,
    center_y_mm: item.center_y_mm,
  }));
}

function serializeReplacementRegions(regions: ColorReplacementItem[]): ColorReplacementScalarItem[] | null {
  if (regions.length === 0) {
    return null;
  }
  return regions.map((item) => ({
    quantized_hex: item.quantized_hex,
    matched_hex: item.matched_hex,
    replacement_hex: item.replacement_hex,
  }));
}

function serializeRecipeOverrides(overrides: RecipeOverrideItem[]): AdvancedParamsColorReplacement["recipe_overrides"] {
  if (overrides.length === 0) {
    return null;
  }
  return overrides.map((item) => ({
    region_id: item.region_id,
    recipe: [...item.recipe],
    layer_order: item.layer_order,
    ...(item.virtual_materials && item.virtual_materials.length > 0
      ? {
          virtual_materials: item.virtual_materials.map((material) => ({
            name: material.name,
            hex: material.hex,
          })),
        }
      : {}),
  }));
}
