/**
 * Lumina Recipe schema type definitions.
 * Lumina 配方 schema 类型定义。
 *
 * V1: Full-site unified recipe schema, initially wired to converter only.
 * V1: 全站统一配方 schema，首批仅接入 converter。
 * V2: Region recipe overrides and custom recipe history.
 * V2: 区域配方覆盖与自定义配方历史。
 * V3: Optional versioned Creative Workshop restore source.
 * V3: 可选的版本化创意工坊恢复来源。
 * V4: Editable local recipes without application content digests.
 * V4: 可直接编辑的本地配方，不包含应用自建内容摘要。
 * V5: Portable authoritative editor checkpoint with spatial masks.
 * V5: 包含真实空间掩码的可携带权威编辑快照。
 */

import type {
  CoatingMaterialReference,
  BackingOutput,
  DynamicMaterialRecipe,
  FridgeMagnetItem,
  MaterialLayerBenefitPoint,
  MaterialLayerBenefitScope,
} from "../api/types";
import type { WorkshopRecipeSource } from "../workshop/types";

// ========== Asset ==========

/** Embedded asset entry (original file bytes preserved). */
export interface AssetEntry {
  filename: string;
  mime_type: string;
  byte_size: number;
  encoding: "base64";
  payload_b64: string;
}

// ========== LUT Reference ==========

/** LUT record identity and matching metadata. */
export interface LutReference {
  name: string;
  color_mode: string;
  path_hint?: string;
}

// ========== Converter Recipe Sub-sections ==========

export interface ConverterRecipeBase {
  lut: LutReference;
  color_mode: string;
  modeling_mode: string;
  target_width_mm: number;
  target_height_mm: number;
  /** @deprecated removed; kept optional for legacy recipe parsing only */
  auto_bg?: boolean;
  /** @deprecated removed; kept optional for legacy recipe parsing only */
  bg_tol?: number;
  quantize_colors: number;
  /** Preserve whether the editor allows the extended quantization range. */
  quantize_colors_unlocked?: boolean;
  high_precision_3d_preview?: boolean;
  enable_cleanup: boolean;
  svg_pixels_per_mm?: number;
  svg_hole_compensation_enabled?: boolean;
  svg_hole_max_area_mm2?: number;
  svg_hole_max_width_mm?: number;
  hue_enable: boolean;
  /** Constrain colour matching to colours represented by the active LUT. */
  use_lut_constrained?: boolean;
  /** Stretch the source colour range before LUT matching. */
  auto_dynamic_range?: boolean;
  chroma_gate: number;
}

export interface ConverterRecipeGeometry {
  spacer_thick: number;
  backing_infill_density_percent?: number;
  structure_mode: string;
  separate_backing: boolean;
  backing_output?: BackingOutput;
  add_loop: boolean;
  loop_width: number;
  loop_length: number;
  loop_hole: number;
  loop_angle: number;
  loop_offset_x: number;
  loop_offset_y: number;
  loop_position_preset: string;
}

export interface ConverterRecipeRelief {
  enable_relief: boolean;
  auto_height_mode: string;
  color_height_map: Record<string, number>;
  heightmap_max_height: number;
}

export interface ConverterRecipeOutline {
  enable_outline: boolean;
  outline_width: number;
}

export interface ConverterRecipeCloisonne {
  enable_cloisonne: boolean;
  wire_width_mm: number;
  wire_height_mm: number;
}

export interface ConverterRecipeCoating {
  enable_coating: boolean;
  coating_height_mm: number;
  /** Historical selection retained for reading old recipes; ignored on restore. */
  coating_material?: CoatingMaterialReference | null;
}

export interface ConverterRecipeColorOps {
  /**
   * Global mappings; local editable pixels and masks live in asset.editor.
   * 全图映射；局部可编辑像素及掩码由 asset.editor 保存。
   */
  replacement_regions: Array<{
    quantized_hex: string;
    matched_hex: string;
    replacement_hex: string;
    source_scope?: { shape: number[]; bits: string } | null;
  }>;
  free_color_set: string[];
  /** V2+: per-region custom recipe overrides (region_id, recipe, layer_order). */
  recipe_overrides?: Array<{
    region_id: string;
    recipe: number[];
    layer_order: string;
    virtual_materials?: Array<{
      name: string;
      hex: string;
    }>;
  }>;
  /** V2+: session-scoped custom recipe history; imported with fromModel forced to false. */
  custom_recipe_history?: Array<{
    id: string;
    recipe: number[];
    layer_order: string;
    predicted_rgb: [number, number, number];
    predicted_lab: [number, number, number];
    hex: string;
    from_model: boolean;
    /** 每层用户意图原色 hex（可选，v2 之后新增）。 */
    display_hexes?: string[];
    /** 每层用户意图原色名（可选，v2 之后新增）。 */
    display_labels?: string[];
    virtual_materials?: Array<{
      name: string;
      hex: string;
    }>;
    created_at_ms: number;
  }>;
}

export interface ConverterRecipeLargeFormat {
  large_format_enabled: boolean;
  tile_width_mm: number;
  tile_height_mm: number;
}

export interface ConverterRecipePuzzle {
  puzzle_enabled: boolean;
  puzzle_style: string;
  puzzle_sizing_mode: string;
  piece_width_mm: number;
  piece_height_mm: number;
  puzzle_rows: number;
  puzzle_cols: number;
  target_piece_count: number;
  puzzle_seed: number;
  connector_style: string;
  labels_enabled: boolean;
  engrave_back_labels: boolean;
  irregularity_strength: number;
  min_neck_width_mm: number;
}

/** Existing restore defaults for cards created before puzzle support. */
export const DEFAULT_CONVERTER_RECIPE_PUZZLE: Readonly<ConverterRecipePuzzle> = {
  puzzle_enabled: false,
  puzzle_style: "regular",
  puzzle_sizing_mode: "piece_size",
  piece_width_mm: 20,
  piece_height_mm: 20,
  puzzle_rows: 3,
  puzzle_cols: 3,
  target_piece_count: 12,
  puzzle_seed: 0,
  connector_style: "classic",
  labels_enabled: false,
  engrave_back_labels: false,
  irregularity_strength: 0.35,
  min_neck_width_mm: 1.2,
};

export interface ConverterRecipeDevice {
  printer_id: string;
  slicer: string;
  nozzle_size: string;
  /** V2 generated machine-registry device profile ID. */
  device_profile_id?: string;
  /** Slicer-native build plate selected for the device profile. */
  build_plate_id?: string;
  /** Device-local template ID; import the native project on each device. */
  custom_3mf_template_id?: string | null;
  /** Exact native filament presets, scoped to this recipe's hardware target. */
  native_filament_profiles?: Record<string, string>;
  external_spool_material?: string;
  /** Preserve the slicer's base-layer height modifier choice. */
  enable_base_layer_height_modifier?: boolean;
  /** Allow Lumina to adapt the model and wipe-tower layout during export. */
  enable_wipe_tower_auto_placement?: boolean;
}

export interface ConverterRecipeFridgeMagnet {
  enable_fridge_magnet: boolean;
  fridge_magnets: FridgeMagnetItem[];
}

export interface ConverterRecipeSource {
  source_version: "legacy" | "native" | "material" | string;
  selected_legacy_lut_names?: string[];
  selected_native_brand_key: string;
  selected_native_db_names: string[];
  color_layers: number | null;
  layer_height_mm: number | null;
  model_enable: boolean;
  model_only: boolean;
  model_threshold: number | null;
  model_margin: number | null;
  selected_material_dir_names: string[];
  material_layer_count: number;
  material_layer_height_mm: number;
  material_backing_material_dir_name: string | null;
  material_dynamic_layer_count_enabled?: boolean;
  material_min_layer_count?: number;
  material_max_layer_count?: number;
  material_delta_e00_tolerance?: number;
}

export interface ConverterRecipeMaterialDynamic {
  recipes: DynamicMaterialRecipe[];
  benefit_curve: MaterialLayerBenefitPoint[];
  /** Missing on legacy cards; import treats it as all printable pixels. */
  scope?: MaterialLayerBenefitScope;
  /** Effective pixel count represented by ``benefit_curve``. */
  pixel_count?: number;
}

// ========== Converter Recipe (combined) ==========

export interface ConverterRecipe {
  base: ConverterRecipeBase;
  source?: ConverterRecipeSource;
  material_dynamic?: ConverterRecipeMaterialDynamic;
  geometry: ConverterRecipeGeometry;
  relief: ConverterRecipeRelief;
  outline: ConverterRecipeOutline;
  cloisonne: ConverterRecipeCloisonne;
  coating: ConverterRecipeCoating;
  color_ops: ConverterRecipeColorOps;
  large_format: ConverterRecipeLargeFormat;
  puzzle: ConverterRecipePuzzle;
  fridge_magnet?: ConverterRecipeFridgeMagnet;
  device: ConverterRecipeDevice;
}

// ========== Top-level Recipe ==========

export type RecipeSource =
  | "converter"
  | "extractor"
  | "calibration"
  | "lut-manager";

export interface RecipeCover {
  width: number;
  height: number;
  mime_type: "image/png";
}

export interface RecipeAssets {
  primary: AssetEntry;
  heightmap?: AssetEntry;
  editor?: AssetEntry;
}

export interface RecipeCompat {
  min_schema_version: number;
  degraded_fields?: string[];
}

export interface LuminaRecipe {
  format: "lumina-recipe";
  schema_version: number;
  app_version: string;
  created_at: string;
  source: RecipeSource;
  cover: RecipeCover;
  asset: RecipeAssets;
  recipe: {
    converter?: ConverterRecipe;
    workshop?: WorkshopRecipeSource;
  };
  compat: RecipeCompat;
  warnings: string[];
}

// ========== Constants ==========

export const RECIPE_FORMAT = "lumina-recipe" as const;
export const RECIPE_SCHEMA_VERSION = 5;
export const EDITOR_PROJECT_MAX_BYTES = 512 * 1024 * 1024;
export const WORKSHOP_RECIPE_ENVELOPE_MAX_BYTES = 1024 * 1024;
