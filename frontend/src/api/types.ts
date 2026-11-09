export interface HealthResponse {
  status: string;
  version: string;
  uptime_seconds: number;
}

// ========== Enums ==========

export enum ColorMode {
  BW = "BW (Black & White)",
  FOUR_COLOR_CMYW = "4-Color (CMYW)",
  FOUR_COLOR_RYBW = "4-Color (RYBW)",
  FIVE_COLOR_EXT = "5-Color Extended",
  SIX_COLOR = "6-Color (CMYWGK 1296)",
  SIX_COLOR_RYBW = "6-Color (RYBWGK 1296)",
  EIGHT_COLOR = "8-Color Max",
  MERGED = "Merged",
}

export enum ModelingMode {
  HIGH_FIDELITY = "high-fidelity",
  PIXEL = "pixel",
  VECTOR = "vector",
  COLOR_CARD = "color-card",
}

export enum StructureMode {
  DOUBLE_SIDED = "Double-sided",
  SINGLE_SIDED = "Single-sided",
}

export type FridgeMagnetShape = "round" | "rect";

export interface FridgeMagnetItem {
  id: string;
  shape: FridgeMagnetShape;
  preset_key: string;
  diameter_mm: number | null;
  width_mm: number | null;
  height_mm: number | null;
  thickness_mm: number;
  center_x_mm: number;
  center_y_mm: number;
}

export type PuzzleStyle = "regular" | "irregular";
export type PuzzleSizingMode = "piece_size" | "grid" | "piece_count";
export type PuzzleConnectorStyle = "classic" | "easy_cut";
export type SourceKind = "legacy_single" | "legacy_multi" | "native_bundle";

export interface LutSupportedMode {
  color_layers: number;
  layer_height_mm: number;
  layer_order?: string;
  mode_key?: string;
}

export interface LegacySingleSourceSelection {
  source_kind?: "legacy_single";
  lut_name: string;
}

export interface LegacyMultiSourceSelection {
  source_kind: "legacy_multi";
  lut_name: string;
  lut_names: string[];
}

export interface NativeBundleSourceSelection {
  source_kind: "native_bundle";
  material_type: string;
  vendor: string;
  db_names: string[];
}

export type ConvertSourceSelection =
  | LegacySingleSourceSelection
  | LegacyMultiSourceSelection
  | NativeBundleSourceSelection;

// ========== Request Models ==========

export type ConvertPreviewRequest = ConvertSourceSelection & {
  target_width_mm: number;
  color_mode: ColorMode;
  modeling_mode: ModelingMode;
  color_layers?: number;
  layer_height_mm?: number;
  model_enable?: boolean;
  model_only?: boolean;
  model_threshold?: number | null;
  model_margin?: number | null;
  quantize_colors: number;
  high_precision_3d_preview?: boolean;
  enable_smooth_vector_preview?: boolean;
  enable_cleanup: boolean;
  enable_outline?: boolean;
  outline_width?: number;
  svg_pixels_per_mm?: number;
  svg_hole_compensation_enabled?: boolean;
  svg_hole_max_area_mm2?: number;
  svg_hole_max_width_mm?: number;
  hue_weight?: number;
  chroma_gate?: number;
  is_dark?: boolean;
  material_source?: "lut" | "material_archive";
  selected_materials?: string[];
  material_layer_count?: number;
  material_layer_height_mm?: number;
  material_grid_resolution?: number;
  material_backing_material_index?: number;
  material_dynamic_layer_count_enabled?: boolean;
  material_min_layer_count?: number;
  material_max_layer_count?: number;
  material_delta_e00_tolerance?: number;
  large_format_enabled?: boolean;
  replacement_regions?: ColorReplacementItem[];
  surface_model_file_id?: string;
  surface_selection_json?: string;
  surface_footprint_json?: string;
  surface_placement_json?: string;
  surface_model_transform_json?: string;
};

export interface VectorPreviewRendererResponse {
  session_id: string;
  status: "pending";
  job_token: string;
  glb_url: null;
  renderer: "vector_analytic" | "segmented";
}

export interface CoatingMaterialReference {
  source: "palette" | "material_archive";
  key: string;
}

export type BackingOutput = "same_project" | "separate_project";

export type ConvertGenerateRequest = ConvertPreviewRequest & {
  project_revision_file_id?: string;
  spacer_thick: number;
  backing_infill_density_percent?: number;
  structure_mode: StructureMode;
  separate_backing: boolean;
  backing_output?: BackingOutput;
  add_loop: boolean;
  loop_width: number;
  loop_length: number;
  loop_hole: number;
  loop_angle?: number;
  loop_offset_x?: number;
  loop_offset_y?: number;
  loop_position_preset?: string;
  loop_pos?: [number, number];
  enable_relief: boolean;
  height_mode?: string;
  color_height_map?: Record<string, number>;
  heightmap_max_height: number;
  enable_outline: boolean;
  outline_width: number;
  enable_cloisonne: boolean;
  wire_width_mm: number;
  wire_height_mm: number;
  enable_coating: boolean;
  coating_height_mm: number;
  /** Deprecated selection accepted for compatibility; generation chooses the type automatically. */
  coating_material?: CoatingMaterialReference | null;
  replacement_regions?: ColorReplacementItem[];
  recipe_overrides?: RecipeOverrideItem[];
  free_color_set?: string[];
  enable_fridge_magnet?: boolean;
  fridge_magnets?: FridgeMagnetItem[];
  printer_id?: string;
  slicer?: string;
  nozzle_size?: string;
  device_profile_id?: string;
  build_plate_id?: string;
  custom_3mf_template_id?: string | null;
  native_filament_profiles?: Record<string, string>;
  external_spool_material?: string;
  enable_base_layer_height_modifier?: boolean;
  enable_wipe_tower_auto_placement?: boolean;
  use_cached_matched_rgb?: boolean;
  /** Exact committed visible-content revision used for generation. */
  editor_content_revision?: number;
  /** Exact shared-selection revision captured for generation. */
  selection_revision?: number;
};

export interface NativeFilamentProfile {
  name: string;
  vendor: string;
  material_type: string;
  available: boolean;
  supported_build_plate_uids: string[];
}

export type ExportMaterialIssueCode =
  | "native_material_ambiguous"
  | "native_material_plate_incompatible"
  | "native_material_unavailable"
  | "native_material_selection_invalid"
  | "native_material_settings_incompatible";

export interface ExportMaterialSelection {
  ready: boolean;
  slicer_id: string;
  machine_uid: string;
  nozzle_uid: string;
  device_profile_id: string;
  machine_profile_id: string;
  build_plate_uid: string;
  materials: Array<{
    name: string;
    material_type: string;
    selected_profile_name: string | null;
    profiles: NativeFilamentProfile[];
  }>;
  build_plates: Array<{
    id: string;
    build_plate_uid: string;
    name: string;
    compatible: boolean;
  }>;
  issues: Array<{
    code: ExportMaterialIssueCode;
    material_index: number | null;
    material_name: string;
    material_type: string;
    build_plate_uid: string;
    message: string;
  }>;
}

export interface PuzzleLayoutPreviewRequest {
  target_height_mm: number;
  puzzle_style: PuzzleStyle;
  sizing_mode: PuzzleSizingMode;
  piece_width_mm: number;
  piece_height_mm: number;
  rows: number;
  cols: number;
  target_piece_count: number;
  seed?: number;
  connector_style: PuzzleConnectorStyle;
  labels_enabled: boolean;
  engrave_back_labels: boolean;
  irregularity_strength: number;
  min_neck_width_mm: number;
}

export interface PuzzleLayoutPreviewResponse {
  status: string;
  message?: string;
  overlay_url: string;
  piece_count: number;
  grid_cols: number;
  grid_rows: number;
  derived_piece_width_mm: number;
  derived_piece_height_mm: number;
  warnings: string[];
}

export interface PuzzleGenerateRequest extends PuzzleLayoutPreviewRequest {
  params: ConvertGenerateRequest;
}

export interface PuzzleGenerateResponse {
  status: string;
  message: string;
  download_url: string;
  threemf_disk_path?: string;
  piece_count: number;
  grid_cols: number;
  grid_rows: number;
  warnings: string[];
  editor_content_revision?: number | null;
  selection_revision?: number | null;
}

/**
 * 用户声明的虚拟耗材：LUT 原生没有的原色由前端作为虚拟耗材附加。
 * 配方里 `>= lut_palette.length` 的索引指向 virtual_materials 列表的位置。
 *
 * User-declared extra material carried alongside a recipe override. Recipe
 * values at or beyond the LUT palette length index into `virtual_materials`,
 * so the pipeline can extend the working palette with the user's intended
 * colours for both the 2D preview and the 3MF output.
 */
export interface VirtualMaterial {
  /** 耗材显示名，例如 "Black"。Friendly name shown in preview / history. */
  name: string;
  /** 耗材 hex（#RRGGBB）。Canonical hex carried through to slicer filament colour. */
  hex: string;
}

export interface RecipeOverrideItem {
  region_id: string;
  recipe: number[];
  layer_order: string;
  color_layers?: number | null;
  actual_recipe_top_to_bottom?: number[] | null;
  print_recipe_top_to_bottom?: number[] | null;
  actual_layer_count?: number | null;
  padding_layer_count?: number | null;
  /** 可选虚拟耗材列表；recipe 中 >= LUT.N 的索引指向它。 */
  virtual_materials?: VirtualMaterial[];
}

export interface RecipePredictRequest {
  session_id: string;
  recipe: number[];
  layer_order: string;
  /** 可选虚拟耗材列表；与后端 RecipePredictRequest.virtual_materials 对齐。 */
  virtual_materials?: VirtualMaterial[];
  color_layers: number;
  layer_height_mm: number;
}

export interface RecipePredictResponse {
  status: string;
  message: string;
  rgb: number[];
  lab: number[];
  source: string;
  runtime_mode_key?: string | null;
}

export interface RecipeOverrideApplyRequest extends RecipePredictRequest {
  region_ids?: string[];
  operation_id?: string;
}

export interface RecipeOverrideApplyResponse
  extends RecipePredictResponse,
    DynamicMaterialResultResponse {
  preview_url: string;
  preview_glb_url?: string | null;
  override_count: number;
  recipe_overrides?: RecipeOverrideItem[];
  can_undo?: boolean;
  can_redo?: boolean;
  /** Authoritative selection and content revision after the edit. */
  selection?: SelectionDocumentResponse | null;
}

export interface RegionRecipeRequest {
  session_id: string;
  region_ids: string[];
  layer_order?: string;
}

export interface RegionRecipeEntry {
  region_id: string;
  recipe: number[];
  color_layers: number;
  layer_height_mm: number;
  layer_order: string;
}

export interface RegionRecipeResponse {
  status: string;
  message: string;
  recipes: RegionRecipeEntry[];
}

/**
 * Whole-image color mapping applied to every matching LUT color.
 * This type never represents a connected-region mask or other spatial edit.
 *
 * 全图颜色映射：应用于所有匹配的 LUT 颜色；不表示连通区域掩码或其它空间编辑。
 */
export interface ColorReplacementItem {
  quantized_hex: string;
  matched_hex: string;
  replacement_hex: string;
}

// ========== Palette & Height Types ==========

/** 调色板条目：量化原色、LUT 匹配色、像素统计 */
export interface PaletteEntry {
  quantized_hex: string; // 量化原色
  matched_hex: string; // LUT 匹配色
  pixel_count: number; // 像素数量
  percentage: number; // 占比百分比
}

/** One exact cumulative dynamic-layer option for a target color. */
export interface DynamicMaterialLayerCapOption {
  max_effective_layer_count: number;
  actual_layer_count: number;
  matched_srgb: [number, number, number];
  actual_recipe_top_to_bottom: number[];
  print_recipe_top_to_bottom: number[];
  delta_e00: number;
}

/** Exact dynamic material recipe metadata returned for one target color. */
export interface DynamicMaterialRecipe {
  target_srgb: [number, number, number];
  matched_srgb: [number, number, number];
  actual_layer_count: number;
  padding_layer_count: number;
  actual_recipe_top_to_bottom: number[];
  print_recipe_top_to_bottom: number[];
  selected_delta_e00: number;
  best_range_delta_e00: number;
  fixed_max_delta_e00: number;
  delta_e00_sacrifice: number;
  layer_cap_options: DynamicMaterialLayerCapOption[];
}

/** Pixel-weighted exact Delta-E00 result at one effective-layer cap. */
export interface MaterialLayerBenefitPoint {
  max_effective_layer_count: number;
  weighted_mean_delta_e00: number;
  marginal_delta_e00_reduction: number;
}

/** Pixel population represented by a dynamic layer benefit curve. */
export type MaterialLayerBenefitScope =
  | "all_printable_pixels"
  | "automatic_pixels";

/** Dynamic result fields shared by preview and post-edit responses. */
export interface DynamicMaterialResultResponse {
  material_dynamic_recipes?: DynamicMaterialRecipe[] | null;
  material_layer_benefit_curve?: MaterialLayerBenefitPoint[] | null;
  material_layer_benefit_scope?: MaterialLayerBenefitScope | null;
  material_layer_benefit_pixel_count?: number | null;
  operation_id?: string | null;
  editor_content_revision?: number | null;
}

/** 自动高度分配模式 */
export type AutoHeightMode =
  | "darker-higher"
  | "lighter-higher"
  | "use-heightmap";

/** 高度图上传响应 */
export interface HeightmapUploadResponse {
  status: string;
  message: string;
  thumbnail_url: string;
  original_size: [number, number];
  color_height_map: Record<string, number>;
  warnings: string[];
}

/** 自动检测推荐量化颜色数响应 */
export interface AutoDetectColorsResponse {
  recommended: number;
  max_safe: number;
  unique_colors: number;
  complexity_score: number;
}

// ========== Response Models ==========

/** 接口性能耗时统计，单位毫秒。 Endpoint timing stats in milliseconds. */
export interface PerformanceTiming {
  total_ms?: number | null;
  upload_ms?: number | null;
  worker_ms?: number | null;
  pickle_load_ms?: number | null;
  segmented_glb_ms?: number | null;
  palette_ms?: number | null;
  overhead_ms?: number | null;
}

/** 预览接口响应，包含 session_id 和预览图 URL */
export interface PreviewResponse extends DynamicMaterialResultResponse {
  session_id: string;
  status: string;
  message: string;
  preview_url: string;
  preview_glb_url: string | null; // GLB 3D 预览 URL
  lut_match_mode?: string | null;
  lut_match_info?: Record<string, unknown> | null;
  palette: PaletteEntry[];
  dimensions: {
    width: number;
    height: number;
    width_mm?: number;
    height_mm?: number;
    preview_raw_url?: string;
  };
  contours?: Record<string, number[][][]> | null; // hex -> list of contour polygons (world coords mm)
  warnings: string[];
  performance_timing?: PerformanceTiming | null;
}

/** 大画幅生成请求，嵌套 ConvertGenerateRequest + 切片参数 */
export type LargeFormatConvertGenerateRequest = Omit<
  ConvertGenerateRequest,
  "target_width_mm"
> & {
  target_width_mm?: number;
};

export interface LargeFormatGenerateRequest {
  target_height_mm?: number;
  tile_width_mm: number;
  tile_height_mm: number;
  params: LargeFormatConvertGenerateRequest;
}

/** 大画幅生成响应 */
export interface LargeFormatGenerateResponse {
  status: string;
  message: string;
  download_url: string;
  tile_count: number;
  failed_tiles?: string[];
  grid_cols: number;
  grid_rows: number;
  warnings: string[];
  editor_content_revision?: number | null;
  selection_revision?: number | null;
}

/** 生成接口响应，包含下载 URL 和可选的 3D 预览 URL */
export interface GenerateResponse {
  status: string;
  message: string;
  download_url: string;
  preview_3d_url?: string;
  threemf_disk_path?: string;
  warnings?: string[];
  performance_timing?: PerformanceTiming | null;
  /** Content revision consumed by the generator, when available. */
  editor_content_revision?: number | null;
  /** Shared-selection revision consumed by the generator, when available. */
  selection_revision?: number | null;
}

export interface ModelSurfaceMeshSummary {
  vertex_count: number;
  face_count: number;
  bounds_min_mm: [number, number, number];
  bounds_max_mm: [number, number, number];
  extents_mm: [number, number, number];
  is_watertight: boolean;
  is_winding_consistent: boolean;
  body_count: number;
  unit_warning: string | null;
}

export interface ModelSurfaceUploadResponse {
  status: string;
  model_file_id: string;
  summary: ModelSurfaceMeshSummary;
  surface_candidates: ModelSurfaceCandidate[];
  preview_glb_url?: string | null;
  warnings: string[];
}

export interface ModelSurfaceHitTriangle {
  face_index?: number | null;
  candidate_id?: string | null;
  point?: [number, number, number] | null;
  normal?: [number, number, number] | null;
  vertices?: [
    [number, number, number],
    [number, number, number],
    [number, number, number],
  ] | null;
}

export interface ModelSurfaceModelTransform {
  rotation_deg: {
    x: number;
    y: number;
    z: number;
  };
}

export interface ModelSurfaceCandidate {
  id: string;
  face_index: number;
  face_count: number;
  area_mm2: number;
  normal: [number, number, number];
  plane_origin?: [number, number, number];
  footprint: Record<string, unknown>;
}

export interface ModelSurfaceSelectResponse {
  status: string;
  selection_id: string;
  selection: Record<string, unknown>;
  footprint: Record<string, unknown>;
  warnings: string[];
}

export interface LutListResponse {
  luts: LutInfo[];
}

export interface LutInfo {
  name: string;
  color_mode: ColorMode;
  path: string;
}

export interface LutCatalogItem {
  name: string;
  color_mode: ColorMode;
  path: string;
}

export interface LutCatalogGroup {
  group_name: string;
  items: LutCatalogItem[];
}

export interface NativeDbOption {
  name: string;
  path: string;
  color_mode: string;
}

export interface NativeBrandGroup {
  brand_key: string;
  material_type: string;
  vendor: string;
  display_name: string;
  db_options: NativeDbOption[];
  default_db_names: string[];
  package_name?: string | null;
  model_name?: string | null;
  supported_modes: LutSupportedMode[];
}

export interface LutCatalogResponse {
  legacy_groups: LutCatalogGroup[];
  native_brand_groups: NativeBrandGroup[];
}

export interface LutDetailsCatalogItem {
  name: string;
  path: string;
  color_mode: string;
  source_kind: string;
  compatibility_key?: string;
  manufacturer: string;
  material_type: string;
  manufacturer_source: string;
  material_source: string;
  search_tokens: string[];
  revision?: string;
}

export interface LutDetailsCatalogGroup {
  manufacturer: string;
  items: LutDetailsCatalogItem[];
}

export interface LutDetailsCatalogResponse {
  groups: LutDetailsCatalogGroup[];
}

export interface CloudLutRegistryCatalogRequest {
  channels?: string[];
  limit?: number;
  offset?: number;
}

export interface CloudLutRegistryCatalogItem {
  lut_id: string;
  revision_id: string;
  content_hash: string;
  package_url: string;
  package_sha256: string;
  package_bytes: number;
  local_path: string;
  local_state?: "not_installed" | "installed" | "local_available" | string;
  local_exists?: boolean;
  local_match_path?: string | null;
  installed_path?: string;
  channel?: string | null;
  visibility?: string | null;
  display?: Record<string, unknown> | null;
  compatibility?: Record<string, unknown> | null;
  [key: string]: unknown;
}

export interface CloudLutRegistryCatalogResponse {
  configured: boolean;
  channels: string[];
  items: CloudLutRegistryCatalogItem[];
  total: number;
}

export interface CloudLutInstallRecord extends CloudLutRegistryCatalogItem {
  installed_path: string;
  installed_at?: string;
  source_url?: string;
}

export interface CloudLutInstallRequest {
  lut_id: string;
  revision_id: string;
  channels?: string[];
}

export interface CloudLutRegistryStatusResponse {
  configured: boolean;
  base_url: string | null;
  channels: string[];
  installed_count: number;
  local_lut_count?: number;
  synced_count?: number;
  local_luts?: Array<Record<string, unknown>>;
  installed?: Array<Record<string, unknown>>;
}

export interface BedSizeItem {
  label: string;
  width_mm: number;
  height_mm: number;
  is_default: boolean;
  printer_id?: string | null;
}

export interface BedSizeListResponse {
  beds: BedSizeItem[];
}

// ========== Calibration Enums ==========

export enum CalibrationColorMode {
  BW = "BW (Black & White)",
  FOUR_COLOR_CMYW = "4-Color (CMYW)",
  FOUR_COLOR_RYBW = "4-Color (RYBW)",
  FIVE_COLOR_EXT = "5-Color Extended (1444)",
  SIX_COLOR = "6-Color (CMYWGK 1296)",
  SIX_COLOR_RYBW = "6-Color (RYBWGK 1296)",
  EIGHT_COLOR = "8-Color Max",
}

export enum BackingColor {
  WHITE = "White",
  CYAN = "Cyan",
  MAGENTA = "Magenta",
  YELLOW = "Yellow",
  RED = "Red",
  BLUE = "Blue",
}

// ========== Calibration Request Models ==========

export interface CalibrationGenerateRequest {
  color_mode: CalibrationColorMode;
  block_size: number;
  gap: number;
  backing_thickness?: number;
  eight_color_full_export?: boolean;
  printer_id?: string;
  slicer?: string;
  nozzle_size?: string;
  device_profile_id?: string;
  build_plate_id?: string;
  custom_3mf_template_id?: string | null;
}

// ========== Calibration Response Models ==========

export interface CalibrationResponse {
  status: string;
  message: string;
  download_url: string;
  preview_url: string | null;
  layer_urls: string[] | null;
  threemf_disk_path?: string | null;
  warnings?: string[];
}

export interface SingleStageJobSummary {
  color: string;
  color_name: string;
  material: string;
  substrate_id: string;
  substrate_display_name: string;
  filename: string;
}

export interface SingleStageKitGenerateRequest {
  palette: ExtractorPaletteEntry[];
  substrate_id: string;
  substrate_display_name: string;
  material_default: string;
  layer_height_mm: number;
  printer_id?: string;
  slicer?: string;
  nozzle_size?: string;
  device_profile_id?: string;
  build_plate_id?: string;
  custom_3mf_template_id?: string | null;
}

export interface SingleStageKitResponse {
  status: string;
  message: string;
  kit_download_url: string;
  preview_url: string | null;
  manifest_url: string;
  jobs: SingleStageJobSummary[];
}

// ========== Extractor Enums ==========

export enum ExtractorColorMode {
  BW = "BW (Black & White)",
  FOUR_COLOR_CMYW = "4-Color (CMYW)",
  FOUR_COLOR_RYBW = "4-Color (RYBW)",
  FIVE_COLOR_EXT = "5-Color Extended",
  SIX_COLOR = "6-Color (CMYWGK 1296)",
  SIX_COLOR_RYBW = "6-Color (RYBWGK 1296)",
  EIGHT_COLOR = "8-Color Max",
}

export enum ExtractorPage {
  PAGE_1 = "Page 1",
  PAGE_2 = "Page 2",
  PAGE_3 = "Page 3",
  PAGE_4 = "Page 4",
  PAGE_5 = "Page 5",
  PAGE_6 = "Page 6",
  PAGE_7 = "Page 7",
  PAGE_8 = "Page 8",
  PAGE_9 = "Page 9",
  PAGE_10 = "Page 10",
  PAGE_11 = "Page 11",
  PAGE_12 = "Page 12",
  PAGE_13 = "Page 13",
  PAGE_14 = "Page 14",
  PAGE_15 = "Page 15",
  PAGE_16 = "Page 16",
  PAGE_17 = "Page 17",
  PAGE_18 = "Page 18",
  PAGE_19 = "Page 19",
  PAGE_20 = "Page 20",
  PAGE_21 = "Page 21",
  PAGE_22 = "Page 22",
  PAGE_23 = "Page 23",
  PAGE_24 = "Page 24",
}

export const EXTRACTOR_EIGHT_COLOR_FULL_TOTAL_PAGES = 24;

// ========== Extractor Response Models ==========

/** 调色板条目（提取器返回的默认调色板） */
export interface ExtractorPaletteEntry {
  color: string;
  material: string;
  hex_color: string | null;
  color_name: string | null;
}

export interface ConfirmPaletteRequest {
  session_id: string;
  manufacturer: string;
  type: string;
  palette: ExtractorPaletteEntry[];
}

export interface ExtractResponse {
  workspace_session_id?: string | null;
  session_id: string;
  status: string;
  message: string;
  lut_download_url: string;
  warp_view_url: string;
  lut_preview_url: string;
  default_palette: ExtractorPaletteEntry[];
  lut_layout?: LutCardLayout | null;
}

export interface SingleStageCoverageItem {
  substrate_id: string;
  colors: string[];
}

export interface SingleStageDatasetItem {
  substrate_id: string;
  color_name: string;
  image_count: number;
  label_count?: number | null;
  calibration?: Record<string, unknown> | null;
}

export interface SingleStageDatasetSummary {
  substrate_count: number;
  color_count: number;
  dataset_count: number;
  image_count: number;
  label_count?: number | null;
  substrates: string[];
  coverage: SingleStageCoverageItem[];
  datasets: SingleStageDatasetItem[];
  uploaded_dataset?: Record<string, unknown> | null;
}

export interface SingleStageExtractResponse {
  session_id: string;
  status: string;
  message: string;
  stage_json_url: string;
  warnings: string[];
  dataset_summary: SingleStageDatasetSummary;
}

export interface StageAFitSummary {
  substrate_count: number;
  channel_count: number;
  substrates: string[];
  colors: string[];
  overall_validation: StageAOverallValidationSummary;
  warnings: string[];
}

export interface StageAOverallValidationSummary {
  mean_delta_e?: number | null;
  max_delta_e?: number | null;
  rmse_linear?: number | null;
  channel_rmse?: number[];
}

export interface StageAFitResponse {
  status: string;
  message: string;
  stage_a_params_url: string;
  fit_summary: StageAFitSummary;
}

export interface GradientCardMaterialSummary {
  sample_count: number;
  per_substrate_sample_count: number;
  grid_rows: number;
  grid_cols: number;
  layer_height_mm: number;
  warp_width_px?: number | null;
  warp_height_px?: number | null;
  thickness_layers: number[];
  sample_boxes: GradientCardSampleBox[];
  white_zero_rgb: number[];
  black_zero_rgb: number[];
  estimated_rgb: number[];
  estimated_k: number[];
}

export interface GradientCardSampleBox {
  row: number;
  col: number;
  x: number;
  y: number;
  width: number;
  height: number;
  thickness_layers: number;
}

export const AGGREGATION_BIAS_FLAGS = [
  "c0_white_avg_gt_0_95",
  "c0_white_avg_lt_0_60",
  "image_source_restored",
  "white_substrate_flat",
  "black_substrate_flat",
  "orientation_unreliable",
  "mean_de_gt_3",
  // Cross-material session outlier: this run's white_C0 disagrees with
  // the median white_C0 of OTHER materials calibrated in the same
  // session (same image_source, captured within the time window). The
  // backend persists this code on both ``run_scores[].structural_flags``
  // and ``excluded_runs[].reason`` for the affected run.
  // 跨材料 session 白底中位数 outlier；前后端共用此稳定 code。
  "c0_session_outlier",
] as const;

export type AggregationBiasFlag = (typeof AGGREGATION_BIAS_FLAGS)[number];

export interface AggregationRunScore {
  index: number;
  is_fresh: boolean;
  bias_flag_count: number;
  bias_flags: AggregationBiasFlag[];
  structural_flag_count: number;
  structural_flags: AggregationBiasFlag[];
  white_c0_avg: number | null;
  image_source: string | null;
  cross_val_rmse: number | null;
}

export interface AggregationExcludedRun {
  index: number;
  reason: string;
  bias_flags: AggregationBiasFlag[];
  structural_flags: AggregationBiasFlag[];
  cross_val_rmse: number | null;
  // Pairwise white_C0 mismatch only — populated when ``reason`` is
  // ``"c0_white_pairwise_mismatch"`` so the UI can show the actual
  // ratio + values that triggered the exclusion.
  fresh_white_c0_avg?: number;
  run_white_c0_avg?: number;
  ratio?: number;
  // Cross-material session outlier diagnostics — populated when
  // ``reason`` is ``"c0_session_outlier"`` so the UI can render a
  // concrete "your run vs session median" comparison instead of just
  // saying "outlier". All values are in linear RGB (per-channel for
  // the two arrays, scalars for the rest).
  // 跨材料 session 白底诊断字段；当 reason === c0_session_outlier 时
  // 必填，前端可直接渲染"本次 vs 同期中位数"的对比卡片。
  run_white_c0?: number[];
  session_median?: number[];
  max_abs_diff?: number;
  max_rel_diff?: number;
  abs_threshold?: number;
  rel_threshold?: number;
  sample_count?: number;
}

export interface AggregationSelection {
  selected_indices: number[];
  excluded_runs: AggregationExcludedRun[];
  selection_strategy: string;
  run_scores: AggregationRunScore[];
  fresh_index: number | null;
}

export interface SavedMaterialSummary {
  material_name: string;
  directory_name: string;
  brand?: string | null;
  verification_count?: number;
  created_at?: string | null;
  updated_at?: string | null;
  aggregation_method?: string | null;
  aggregation_selection?: AggregationSelection | null;
}

export interface OrientationCandidate {
  white_orientation: string;
  black_orientation: string;
  anchor_penalty: number;
  mean_delta_e: number;
  rmse_linear: number;
  max_delta_e: number;
}

export const MANUAL_ORIENTATION_LABELS = [
  "identity",
  "rotate_90_cw",
  "rotate_180",
  "rotate_90_ccw",
  "flip_horizontal",
  "flip_vertical",
  "transpose",
  "transverse",
] as const;

export type ManualOrientationLabel = (typeof MANUAL_ORIENTATION_LABELS)[number];

export interface SubstrateOrientationInfo {
  signal_strength: number;
  flat: boolean;
  manual_override: ManualOrientationLabel | null;
  locked_to: ManualOrientationLabel | null;
}

export interface OrientationRanking {
  orientation_reliable: boolean;
  delta_e_gap: number;
  top_candidates: OrientationCandidate[];
  white_signal_strength?: number | null;
  black_signal_strength?: number | null;
  white_orientation_info?: SubstrateOrientationInfo | null;
  black_orientation_info?: SubstrateOrientationInfo | null;
}

export interface GradientCardStageAExtractResponse {
  session_id: string;
  status: string;
  message: string;
  stage_a_params_url: string;
  white_warp_preview_url?: string | null;
  black_warp_preview_url?: string | null;
  fit_summary: StageAFitSummary;
  material_summary: GradientCardMaterialSummary;
  orientation_ranking?: OrientationRanking | null;
  warnings: string[];
}

export interface GradientCardMaterialSaveResponse {
  status: string;
  message: string;
  material_file_url: string;
  stage_a_params_url: string;
  material_summary: SavedMaterialSummary;
}

export interface GradientCardMaterialDeleteResponse {
  status: string;
  message: string;
  directory_name: string;
  material_name: string;
}

export interface GradientCardMaterialUpdateResponse {
  status: string;
  message: string;
  material: SavedMaterialLibraryItem;
}

export interface SavedMaterialVerificationHistoryItem {
  verification_index: number;
  captured_at?: string | null;
  mean_delta_e?: number | null;
  rmse_linear?: number | null;
  estimated_rgb: number[];
  estimated_k: number[];
  e_values: number[];
  k_values: number[];
  white_c0_values: number[];
  black_c0_values: number[];
  white_detected_orientation?: string | null;
  black_detected_orientation?: string | null;
}

export interface SavedMaterialLibraryItem {
  material_name: string;
  directory_name: string;
  brand?: string | null;
  material_type?: string | null;
  material_type_source?: "archive" | "legacy_name" | null;
  material_product_id?: string | null;
  material_profile_id?: string | null;
  contributor_name?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  material_file_url: string | null;
  stage_a_params_url?: string | null;
  /** Legacy private-path fields may still appear in old test fixtures/imports. */
  archive_path?: string | null;
  stage_a_params_path?: string | null;
  estimated_rgb: number[];
  layer_height_mm?: number | null;
  mean_delta_e?: number | null;
  verification_count?: number;
  verification_history?: SavedMaterialVerificationHistoryItem[];
  // Material usage statistics surfaced from the backend sidecar file.
  // 后端边车文件提供的耗材使用次数。
  usage_total?: number;
  usage_by_color_mode?: Record<string, number>;
  usage_last_used_at?: string | null;
  usage_last_used_color_mode?: string | null;
  sync_material_id?: string | null;
  sync_revision_id?: string | null;
  sync_channel?: string | null;
  sync_official?: boolean;
}

export interface GradientCardMaterialLibraryResponse {
  status: string;
  message: string;
  materials: SavedMaterialLibraryItem[];
}

export interface MaterialRecipePreviewRequest {
  directory_names: string[];
  layer_height_mm: number;
  substrate: "white" | "black";
}

export interface MaterialRecipeLayer {
  layer_index: number;
  directory_name: string;
  material_name: string;
  estimated_rgb: [number, number, number];
  estimated_hex: string;
}

export interface MaterialRecipePreviewResponse {
  status: string;
  layer_count: number;
  layer_height_mm: number;
  substrate: string;
  predicted_rgb: [number, number, number];
  predicted_hex: string;
  layers: MaterialRecipeLayer[];
}

export interface GradientCardMaterialBulkExportResponse {
  status: string;
  message: string;
  download_url: string;
  filename: string;
  exported_count: number;
  exported_directory_names: string[];
}

export interface GradientCardMaterialBulkImportResponse {
  status: string;
  message: string;
  imported_count: number;
  imported_materials: SavedMaterialSummary[];
}

export interface MaterialSyncInstalledEntry {
  material_id: string;
  revision_id: string;
  content_hash: string;
  channel: string;
  source: string;
  local_directory: string;
  display_brand: string;
  display_name: string;
  installed_at?: string | null;
  updated_at?: string | null;
  local_exists: boolean;
  material_file_exists: boolean;
  available_revisions: string[];
  revision_history?: { revision_id: string; installed_at?: string | null }[];
}

export interface MaterialSyncStatusResponse {
  status: string;
  message: string;
  schema_version: string;
  index_state: "missing" | "ready" | "invalid";
  last_sync_at?: string | null;
  registries: Record<string, unknown>;
  installed_count: number;
  installed: MaterialSyncInstalledEntry[];
  local_overrides_count: number;
}

export interface MaterialSyncRefreshFailure {
  material_id: string;
  revision_id: string;
  package_url: string;
  error: string;
}

export interface MaterialSyncRefreshResponse {
  status: "ok" | "partial" | string;
  message: string;
  registry_url: string;
  channels: string[];
  checked_count: number;
  installed_count: number;
  skipped_count: number;
  failed_count: number;
  installed_materials: SavedMaterialSummary[];
  failures: MaterialSyncRefreshFailure[];
}

export interface MaterialSyncRollbackResponse {
  status: string;
  message: string;
  material_id: string;
  revision_id: string;
  content_hash: string;
  channel: string;
  local_directory: string;
}

export interface MaterialRegistryCatalogEntry {
  material_id: string;
  revision_id: string;
  content_hash: string;
  channel: string;
  visibility: string;
  local_directory: string;
  display: Record<string, unknown>;
  compatibility: Record<string, unknown>;
  package_url: string;
  package_sha256: string;
  package_bytes: number;
  /** Public card projection from the Registry; older registries omit it. */
  card_metadata?: MaterialRegistryCardMetadata | null;
}

/** Registry card metadata; every field is optional and may be malformed upstream. */
export interface MaterialRegistryCardMetadata {
  created_at?: string | null;
  updated_at?: string | null;
  estimated_rgb?: number[] | null;
  layer_height_mm?: number | null;
  mean_delta_e?: number | null;
  verification_count?: number | null;
}

export interface MaterialRegistryCatalogResponse {
  schema_version: string;
  channels: string[];
  count: number;
  total_count: number | null;
  offset: number;
  limit: number | null;
  materials: MaterialRegistryCatalogEntry[];
}

export interface MaterialRegistryInstallRequest {
  material_id: string;
  revision_id: string;
  package_url: string;
  package_sha256: string;
}

export interface MaterialSyncInstallResponse {
  status: string;
  message: string;
  installed_count: number;
  installed_materials: SavedMaterialSummary[];
}

export interface MaterialRegistryPackageMutationResponse {
  status: string;
  message: string;
  channel: string;
  package_path: string;
  package_url: string;
  package_sha256: string;
  package_bytes: number;
  materials: MaterialRegistryCatalogEntry[];
}

// ========== Material solver cache (64³ Lab-grid recipe lookup) ==========

/** Metadata for one persisted material-solver cache entry. */
export interface MaterialSolverCacheEntry {
  palette_hash: string;
  material_directory_names: string[];
  layer_count: number;
  layer_height_mm: number;
  substrate: string;
  grid_resolution: number;
  total_combinations: number;
  valid_cell_count: number;
  total_cell_count: number;
  mean_delta_e: number;
  max_delta_e: number;
  build_time_seconds: number;
  built_at?: string | null;
  cache_file_size_bytes: number;
}

/** Status response for a specific ``(palette, N, t, substrate)`` combination. */
export interface MaterialSolverCacheStatusResponse {
  status: string;
  message: string;
  cached: boolean;
  palette_hash: string;
  layer_count: number;
  layer_height_mm: number;
  substrate: string;
  entry?: MaterialSolverCacheEntry | null;
}

/** Response after an explicit cache build. */
export interface MaterialSolverCacheBuildResponse {
  status: string;
  message: string;
  entry: MaterialSolverCacheEntry;
}

/** Listing response for all persisted solver caches. */
export interface MaterialSolverCacheListResponse {
  status: string;
  message: string;
  entries: MaterialSolverCacheEntry[];
}

/** Delete response for a solver cache entry. */
export interface MaterialSolverCacheDeleteResponse {
  status: string;
  message: string;
  deleted: boolean;
  palette_hash: string;
  layer_count: number;
  layer_height_mm: number;
  substrate: string;
}

// ========== Material solver hybrid runtime (bounded candidate lookup) ==========

/** Metadata for one persisted hybrid material runtime. */
export interface MaterialSolverRuntimeEntry {
  palette_hash: string;
  material_directory_names: string[];
  layer_count: number;
  layer_height_mm: number;
  substrate: string;
  mode: string;
  candidate_budget: number;
  candidate_count: number;
  candidate_pool_multiplier: number;
  batch_recipe_count: number;
  lab_grid_resolution: number;
  seed: number;
  inverse_refinement_enabled: boolean;
  built_at?: string | null;
  cache_file_size_bytes: number;
}

/** Status response for a bounded hybrid runtime combination. */
export interface MaterialSolverRuntimeStatusResponse {
  status: string;
  message: string;
  cached: boolean;
  palette_hash: string;
  layer_count: number;
  layer_height_mm: number;
  substrate: string;
  candidate_budget: number;
  entry?: MaterialSolverRuntimeEntry | null;
}

/** Response after an explicit hybrid runtime build. */
export interface MaterialSolverRuntimeBuildResponse {
  status: string;
  message: string;
  entry: MaterialSolverRuntimeEntry;
}

/** Delete response for a hybrid runtime entry. */
export interface MaterialSolverRuntimeDeleteResponse {
  status: string;
  message: string;
  deleted: boolean;
  palette_hash: string;
  layer_count: number;
  layer_height_mm: number;
  substrate: string;
  candidate_budget: number;
}

/** Visualization payload for one persisted hybrid runtime entry. */
export interface MaterialSolverRuntimeDetailsResponse {
  status: string;
  message: string;
  palette_hash: string;
  material_directory_names: string[];
  layer_count: number;
  layer_height_mm: number;
  substrate: string;
  grid_resolution: number;
  valid_cell_count: number;
  total_cell_count: number;
  candidate_budget: number;
  candidate_count: number;
  coverage_stats: LutDetailsCoverageStats;
  lab_points: LutDetailsPoint[];
  lab_points_3d: LutDetailsPoint3D[];
  lab_hull: Array<{ x: number; y: number }>;
  rgb_points: LutDetailsPoint[];
}

/**
 * Color-distribution visualization payload for one solver-cache entry.
 * Mirrors the LUT details ``lab_points`` / ``rgb_points`` / ``coverage_stats``
 * fields so the existing scatter chart components can render it verbatim.
 *
 * 单份求解器缓存的色彩分布图载荷；与 LUT 详情的散点字段同构，可直接复用既有图表
 * 组件渲染。
 */
export interface MaterialSolverCacheDetailsResponse {
  status: string;
  message: string;
  palette_hash: string;
  material_directory_names: string[];
  layer_count: number;
  layer_height_mm: number;
  substrate: string;
  grid_resolution: number;
  valid_cell_count: number;
  total_cell_count: number;
  coverage_stats: LutDetailsCoverageStats;
  lab_points: LutDetailsPoint[];
  lab_points_3d: LutDetailsPoint3D[];
  lab_hull: Array<{ x: number; y: number }>;
  rgb_points: LutDetailsPoint[];
}

/** One achievable-color candidate returned by the suggester endpoint. */
export interface MaterialColorSuggestionItem {
  hex: string;
  rgb: [number, number, number];
  delta_e: number;
  recipe: number[];
  recipe_display: string;
}

/** Response payload for ``POST /material-solver-cache/suggest-colors``. */
export interface MaterialColorSuggestionsResponse {
  status: string;
  message: string;
  /**
   * ``"cache"`` for exact cache, ``"runtime"`` for hybrid runtime,
   * ``"mitm"`` otherwise.
   */
  source: "cache" | "runtime" | "mitm";
  palette_hash: string;
  layer_count: number;
  layer_height_mm: number;
  substrate: string;
  target_hex: string;
  target_rgb: [number, number, number];
  suggestions: MaterialColorSuggestionItem[];
}

export interface ManualFixResponse {
  status: string;
  message: string;
  lut_preview_url: string;
  lut_layout?: LutCardLayout | null;
}

// ========== LUT Manager Models ==========

export interface LutInfoResponse {
  name: string;
  color_mode: string;
  color_count: number;
  palette?: Array<{
    color: string;
    material: string;
    hex_color: string | null;
    color_name?: string | null;
  }>;
  max_color_layers?: number;
  layer_height_mm?: number;
  line_width_mm?: number;
  base_layers?: number;
  base_channel_idx?: number;
  layer_order?: string;
  schema_version?: string;
  capabilities?: string[];
  supports_predictive_match?: boolean;
  supports_dynamic_layer_height?: boolean;
  supports_dynamic_layer_count?: boolean;
  supports_custom_recipe?: boolean;
  source_kind?: string;
  supported_modes?: LutSupportedMode[];
}

export interface LutDetailsCoverageRange {
  min: number;
  max: number;
}

export interface LutDetailsCoverageStats {
  entry_count: number;
  plotted_point_count: number;
  l_range: LutDetailsCoverageRange;
  a_range: LutDetailsCoverageRange;
  b_range: LutDetailsCoverageRange;
  r_range: LutDetailsCoverageRange;
  g_range: LutDetailsCoverageRange;
  b_rgb_range: LutDetailsCoverageRange;
}

export interface LutDetailsPoint {
  x: number;
  y: number;
  hex_color: string | null;
  rgb: [number, number, number];
  label?: string | null;
}

export interface LutDetailsPoint3D {
  l: number;
  a: number;
  b: number;
  hex_color: string | null;
  rgb: [number, number, number];
  label?: string | null;
}

export interface LutDetailsResponse {
  name: string;
  path: string;
  manufacturer: string;
  manufacturer_source: string;
  material_type: string;
  material_source: string;
  color_mode: string;
  color_count: number;
  source_kind: string;
  schema_version: string;
  capabilities: string[];
  supported_modes: LutSupportedMode[];
  raw_metadata: Record<string, unknown>;
  palette: Array<{
    color: string;
    material: string;
    hex_color: string | null;
    color_name?: string | null;
  }>;
  coverage_stats: LutDetailsCoverageStats;
  lab_points: LutDetailsPoint[];
  lab_points_3d: LutDetailsPoint3D[];
  lab_hull: Array<{ x: number; y: number }>;
  rgb_points: LutDetailsPoint[];
  max_color_layers: number;
  layer_height_mm: number;
  line_width_mm: number;
  base_layers: number;
  base_channel_idx: number;
  layer_order: string;
}

export interface RecipeColorPredictRequest {
  recipe: number[];
  color_layers: number;
  layer_height_mm: number;
  layer_order: string;
}

export interface RecipeColorPredictResponse {
  status: string;
  rgb: number[];
  lab: number[];
  runtime_mode_key: string;
  source: string;
}

export interface RecipeSearchRequest {
  pattern: string;
  color_layers: number;
  layer_height_mm: number;
  layer_order: string;
  limit?: number;
}

export interface RecipeSearchItem {
  recipe: number[];
  rgb: number[];
  lab: number[];
}

export interface RecipeSearchResponse {
  status: string;
  runtime_mode_key: string;
  items: RecipeSearchItem[];
}

export interface MergeStats {
  total_before: number;
  total_after: number;
  exact_dupes: number;
  similar_removed: number;
}

export interface MergeRequest {
  primary_name: string;
  secondary_names: string[];
  dedup_threshold: number;
}

export interface MergeResponse {
  status: string;
  message: string;
  filename: string;
  stats: MergeStats;
  palette?: Array<{
    color: string;
    material: string;
    hex_color: string | null;
    color_name?: string | null;
  }>;
  warnings?: string[];
}

export interface CompareDiffItem {
  recipe: string[];
  rgb_a: [number, number, number];
  rgb_b: [number, number, number];
  hex_a: string;
  hex_b: string;
  delta_e00: number;
}

export interface CompareStats {
  matched_recipe_count: number;
  recipe_coverage_a: number;
  recipe_coverage_b: number;
  mean_delta_e00: number;
  median_delta_e00: number;
  p95_delta_e00: number;
  max_delta_e00: number;
  identical_rgb_count: number;
  recipes_only_in_a: number;
  recipes_only_in_b: number;
}

export interface CompareRequest {
  lut_a_name: string;
  lut_b_name: string;
  top_n: number;
}

export interface CompareResponse {
  status: string;
  message: string;
  lut_a_name: string;
  lut_b_name: string;
  lut_a_mode: string;
  lut_b_mode: string;
  stats: CompareStats;
  warnings: string[];
  worst_diffs: CompareDiffItem[];
}

// ========== System Models ==========

export interface ClearCacheResponse {
  status: string;
  message: string;
  deleted_files: number;
  freed_bytes: number;
  details: {
    registry_cleaned: number;
    sessions_cleaned: number;
    output_files_cleaned: number;
  };
}

// ========== LUT Color Types ==========

export interface LutColorEntry {
  hex: string;
  rgb: [number, number, number];
}

export interface LutCardPage {
  page_index: number;
  page_label: string;
  card_index: number;
  card_label: string;
  start_index: number;
  item_count: number;
  data_rows: number;
  data_cols: number;
  padding: number;
  physical_rows: number;
  physical_cols: number;
}

export interface LutCardLayout {
  color_mode: string;
  total_count: number;
  pages: LutCardPage[];
}

export interface LutCardCellCoordinate {
  card_index: number;
  card_label: string;
  page_index: number;
  page_label: string;
  grid_size: number;
  data_rows: number;
  data_cols: number;
  row: number;
  col: number;
  data_row: number;
  data_col: number;
  display_row: number;
  display_col: number;
  physical_row: number;
  physical_col: number;
  row_index: number;
}

export interface LutPreviewResolvedCell {
  cell: LutCardCellCoordinate;
  rgb: [number, number, number];
  hex: string;
  overlay_bbox: {
    left: number;
    top: number;
    width: number;
    height: number;
  };
}

export interface LutColorsCard {
  page: LutCardPage;
  colors: LutColorEntry[];
}

export interface LutColorsResponse {
  lut_name: string;
  total: number;
  colors: LutColorEntry[];
  layout?: LutCardLayout | null;
  cards?: LutColorsCard[];
}

// ========== Slicer Models ==========

export interface SlicerInfo {
  id: string;
  display_name: string;
  exe_path?: string | null;
  source?: string;
}

export interface SlicerDetectResponse {
  slicers: SlicerInfo[];
}

export interface SlicerLaunchRequest {
  slicer_id: string;
  file_path?: string;
  download_url?: string;
  slicer_path?: string;
}

export interface SlicerLaunchResponse {
  status: string;
  message: string;
}

export interface SlicerCustomPathRequest {
  path: string;
}

export interface SlicerCustomPathResponse {
  status: string;
  message: string;
  slicer: SlicerInfo | null;
}

// ========== Batch Processing Models ==========

export interface BatchItemResult {
  filename: string;
  status: string;
  error?: string;
  download_url?: string | null;
}

/**
 * Single warning entry attached to BatchResponse.warnings.
 *
 * `code` 是稳定的机器可读标识；前端 SHALL 通过 `code` 选择本地化文案，
 * 不依赖后端 `message` 文本判断。`(string & {})` 这种"开口字符串"写法
 * 保留扩展位但仍享受 `"plate-overflow"` 字面量的 IDE 提示。
 */
export interface WarningEntry {
  /** Stable machine-readable warning code; routes the i18n key on the frontend. */
  code:
    | "plate-overflow"
    | "preview-limited"
    | "wipe_tower_manual_adjustment_required"
    | (string & {});
  /** Server-rendered human-readable text; only used as fallback. */
  message: string;
}

export interface BatchResponse {
  status: string;
  message: string;
  /** 合并 3MF 的下载 URL；零成功项时为 null */
  download_url: string | null;
  /** Legacy field kept for compatibility; public responses should be null. */
  threemf_disk_path?: string | null;
  /** 兼容旧客户端的首个批量预览 GLB URL；零成功项时为 null */
  preview_3d_url: string | null;
  /** 批量预览条目；前端按坐标同时渲染多个原始单件 GLB */
  preview_items?: BatchPreviewItem[];
  results: BatchItemResult[];
  warnings: WarningEntry[];
}

export interface BatchPreviewItem {
  url: string;
  filename: string;
  tx_mm: number;
  ty_mm: number;
  width_mm: number;
  depth_mm: number;
}

export interface BatchConvertParams {
  project_revision_file_id?: string;
  enable_outline?: boolean;
  outline_width?: number;
  backing_output?: BackingOutput;
  svg_hole_compensation_enabled?: boolean;
  svg_hole_max_area_mm2?: number;
  svg_hole_max_width_mm?: number;
  enable_coating?: boolean;
  coating_height_mm?: number;
  /** Deprecated selection accepted for compatibility; generation chooses the type automatically. */
  coating_material?: CoatingMaterialReference | null;
  source_kind?: "legacy_single" | "legacy_multi" | "native_bundle";
  lut_name?: string;
  lut_names?: string[];
  material_type?: string;
  vendor?: string;
  db_names?: string[];
  material_source?: "lut" | "material_archive";
  selected_materials?: string[];
  material_layer_count?: number;
  material_layer_height_mm?: number;
  material_grid_resolution?: number;
  material_backing_material_index?: number;
  material_dynamic_layer_count_enabled?: boolean;
  material_min_layer_count?: number;
  material_max_layer_count?: number;
  material_delta_e00_tolerance?: number;
  separate_backing?: boolean;
  target_width_mm: number;
  spacer_thick: number;
  backing_infill_density_percent?: number;
  structure_mode: string;
  color_mode: string;
  modeling_mode: string;
  color_layers?: number;
  layer_height_mm?: number;
  quantize_colors: number;
  high_precision_3d_preview?: boolean;
  enable_cleanup: boolean;
  svg_pixels_per_mm?: number;
  hue_weight: number;
  chroma_gate: number;
  model_enable?: boolean;
  model_only?: boolean;
  model_threshold?: number;
  model_margin?: number;
  use_lut_constrained?: boolean;
  auto_dynamic_range?: boolean;
  enable_relief?: boolean;
  height_mode?: string;
  color_height_map?: Record<string, number>;
  heightmap_max_height?: number;
  printer_id?: string;
  slicer?: string;
  nozzle_size?: string;
  device_profile_id?: string;
  build_plate_id?: string;
  custom_3mf_template_id?: string | null;
  native_filament_profiles?: Record<string, string>;
  external_spool_material?: string;
  enable_base_layer_height_modifier?: boolean;
  enable_wipe_tower_auto_placement?: boolean;
}

// ========== Five-Color Query Models ==========

export interface BaseColorEntry {
  index: number;
  rgb: [number, number, number];
  name: string;
  hex: string;
}

export interface BaseColorsResponse {
  lut_name: string;
  color_count: number;
  colors: BaseColorEntry[];
  combinations?: number[][] | null;
}

export interface FiveColorQueryRequest {
  lut_name: string;
  selected_indices: number[];
}

export interface FiveColorQueryResponse {
  found: boolean;
  selected_indices: number[];
  result_rgb: [number, number, number] | null;
  result_hex: string | null;
  row_index: number;
  message: string;
  source: string;
  reason?: string | null;
}

export interface FiveColorCardCoordinate {
  card_index: number;
  card_label: string;
  page_index: number;
  page_label: string;
  grid_size: number;
  data_rows: number;
  data_cols: number;
  row: number;
  col: number;
  data_row: number;
  data_col: number;
  display_row: number;
  display_col: number;
  physical_row: number;
  physical_col: number;
  row_index: number;
}

export interface FiveColorNeighborhoodCell {
  card_index: number | null;
  card_label: string | null;
  page_index: number | null;
  page_label: string | null;
  grid_size: number | null;
  data_rows: number | null;
  data_cols: number | null;
  row: number | null;
  col: number | null;
  data_row: number | null;
  data_col: number | null;
  display_row: number | null;
  display_col: number | null;
  physical_row: number | null;
  physical_col: number | null;
  row_index: number | null;
  rgb: [number, number, number] | null;
  hex: string | null;
  is_match: boolean;
}

export interface FiveColorMatchRequest {
  lut_name: string;
  target_hex: string;
  neighborhood_radius?: number;
}

export interface FiveColorMatchResponse extends FiveColorQueryResponse {
  target_rgb: [number, number, number];
  target_hex: string;
  matched_rgb: [number, number, number] | null;
  matched_hex: string | null;
  delta_e: number | null;
  coordinate: FiveColorCardCoordinate;
  neighborhood: FiveColorNeighborhoodCell[][];
}

export interface RecipeSwatchItemRequest {
  selected_indices: number[];
  result_hex: string;
  base_color_names?: string[];
  base_color_hexes?: string[];
}

export interface RecipeSwatchRequest {
  lut_name: string;
  recipes: RecipeSwatchItemRequest[];
  block_size_mm?: number;
  gap_mm?: number;
  cols?: number;
  structure_mode?: string;
  printer_id?: string;
  slicer?: string;
  nozzle_size?: string;
  device_profile_id?: string;
  build_plate_id?: string;
  custom_3mf_template_id?: string | null;
}

export interface RecipeSwatchResponse {
  status: string;
  message: string;
  download_url: string;
  preview_url?: string | null;
  recipe_count: number;
}

// ========== Material Recipe Swatch Models ==========

export interface MaterialRecipeSwatchItemRequest {
  directory_names: string[];
  result_hex: string;
  layer_height_mm: number;
  substrate: string;
}

export interface MaterialRecipeSwatchRequest {
  recipes: MaterialRecipeSwatchItemRequest[];
  block_size_mm?: number;
  gap_mm?: number;
  cols?: number;
  structure_mode?: string;
  printer_id?: string;
  slicer?: string;
  nozzle_size?: string;
  device_profile_id?: string;
  build_plate_id?: string;
  custom_3mf_template_id?: string | null;
}

export interface MaterialRecipeSwatchResponse {
  status: string;
  message: string;
  download_url: string;
  preview_url?: string | null;
  recipe_count: number;
}

// ========== Color Replace Models ==========

export interface ColorReplaceResponse extends DynamicMaterialResultResponse {
  status: string;
  message: string;
  preview_url: string;
  preview_3d_url?: string | null;
  replacement_count: number;
  can_undo?: boolean;
  can_redo?: boolean;
  /** Authoritative selection and content revision after the edit. */
  selection?: SelectionDocumentResponse | null;
}

/** 同颜色全选点图时后端返回的当前匹配色拾取结果 */
export interface SourceColorPickResponse {
  source_matched_hex: string;
  quantized_hex: string;
}

// ========== Color Highlight Models ==========

/** 颜色高亮响应 */
export interface ColorHighlightResponse {
  preview_url: string;
}

// ========== Region Detection & Replace Models ==========

export interface SelectionComponentItem {
  label: number;
  region_id: string;
  color_hex: string;
  pixel_count: number;
  bbox: number[];
  anchor: number[];
  contours?: number[][][];
}

export interface SelectionDocumentResponse {
  selection_revision: number;
  content_revision: number;
  selected_pixel_count: number;
  selected_component_count: number;
  selected_color_hexes: string[];
  region_ids: string[];
  components: SelectionComponentItem[];
  contours: number[][][];
  can_undo: boolean;
  can_redo: boolean;
  brush_hit_component_count?: number | null;
  editor_content_revision?: number | null;
}

export interface EditorCommitResult {
  preview_url?: string | null;
  preview_glb_url?: string | null;
  replacement_regions?: ColorReplacementItem[] | null;
  recipe_overrides?: RecipeOverrideItem[] | null;
  recipe_override_count?: number | null;
  region_replacement_count?: number | null;
  color_layers?: number | null;
  layer_height_mm?: number | null;
  gradient_groups?: GradientGroupItem[] | null;
  free_color_set?: string[] | null;
  can_undo?: boolean | null;
  can_redo?: boolean | null;
  material_dynamic_recipes?: DynamicMaterialRecipe[] | null;
  material_layer_benefit_curve?: MaterialLayerBenefitPoint[] | null;
  material_layer_benefit_scope?: MaterialLayerBenefitScope | null;
  material_layer_benefit_pixel_count?: number | null;
}

export interface EditorCommitStatusResponse {
  status: "pending" | "committed" | "failed" | "unknown";
  operation_id: string;
  operation?: string | null;
  editor_content_revision: number;
  visible_content_revision?: number;
  selection_revision?: number | null;
  result?: EditorCommitResult | null;
}

export interface SelectionMutationRequest {
  session_id: string;
  operation:
    | "point-toggle"
    | "point-remove"
    | "same-color-toggle"
    | "same-color-remove"
    | "colors-set"
    | "gradient-region-set"
    | "color-range-toggle"
    | "brush-add"
    | "clear";
  base_selection_revision: number;
  content_revision: number;
  x?: number;
  y?: number;
  color_hex?: string;
  color_hexes?: string[];
  gradient_group_index?: number;
  gradient_region_index?: number;
  /** CIEDE2000 tolerance for ``color-range-toggle`` (0 = exact colour). */
  color_tolerance?: number;
  brush_radius?: number;
  brush_points?: Array<{ x: number; y: number }>;
  brush_strokes?: Array<Array<{ x: number; y: number }>>;
}

/** 连通区域检测响应 */
export interface RegionDetectResponse {
  region_id: string;
  color_hex: string;
  pixel_count: number;
  preview_url: string | null;
  contours?: number[][][] | null;
  /** Diagnostic/legacy metadata only; visible selection must use contours. */
  bbox?: [number, number, number, number] | null;
}

/** 区域替换响应 */
export interface RegionReplaceResponse extends DynamicMaterialResultResponse {
  preview_url: string;
  preview_glb_url?: string | null;
  color_contours?: Record<string, number[][][]> | null;
  message: string;
  can_undo?: boolean;
  can_redo?: boolean;
  /**
   * Refreshed gradient-banding groups when the endpoint re-ran the
   * gradient-group analyser (e.g. ``/region-requantize``). Endpoints that
   * do not mutate ``matched_rgb`` enough to shift the segmentation leave
   * this absent, and the frontend should keep the cached groups.
   * 端点重新分析了渐变分组时返回；普通 hex 替换不会填充此字段，前端应
   * 保留已缓存的分组。
   */
  gradient_groups?: GradientGroupItem[] | null;
  /**
   * Authoritative shared selection after a selection-scoped region replace.
   * 统一选区换色后端返回的权威选区状态；用于同步 revision/content_revision。
   */
  selection?: SelectionDocumentResponse | null;
}

export interface FreeColorMutationResponse {
  status: string;
  free_color_set: string[];
  can_undo: boolean;
  can_redo: boolean;
  operation_id?: string | null;
  editor_content_revision?: number | null;
}

export interface ResetReplacementsResponse extends DynamicMaterialResultResponse {
  status: string;
  message: string;
  preview_url: string;
  preview_glb_url?: string | null;
  can_undo?: boolean;
  can_redo?: boolean;
  /** Authoritative selection and content revision after the reset. */
  selection?: SelectionDocumentResponse | null;
}

export interface ReplacementHistoryResponse {
  status: string;
  action: "undo" | "redo";
  label?: string | null;
  entry_kind?: "content" | "selection";
  selection?: SelectionDocumentResponse | null;
  message: string;
  preview_url: string;
  preview_glb_url?: string | null;
  can_undo: boolean;
  can_redo: boolean;
  replacement_regions: ColorReplacementItem[];
  recipe_overrides: RecipeOverrideItem[];
  recipe_override_count: number;
  region_replacement_count?: number | null;
  color_layers?: number | null;
  layer_height_mm?: number | null;
  gradient_groups?: GradientGroupItem[] | null;
  free_color_set?: string[];
  operation_id?: string | null;
  editor_content_revision?: number | null;
}

// ========== Printer Models ==========

export interface DeviceProfileInfo {
  device_profile_id: string;
  machine_profile_id?: string;
  slicer_id: string;
  nozzle_size: string;
  source_profile_name: string;
  revision: string;
  supported: boolean;
  build_plates?: BuildPlateInfo[];
  default_build_plate_id?: string;
}

export interface BuildPlateInfo {
  id: string;
  display_name: string;
  display_name_zh?: string;
  image_url: string;
}

export interface PrinterInfo {
  id: string;
  display_name: string;
  brand: string;
  bed_width: number;
  bed_depth: number;
  bed_height: number;
  supported_nozzle_sizes: string[];
  supported_slicers: string[];
  thumbnail?: string;
  device_profiles?: DeviceProfileInfo[];
}

export interface PrinterListResponse {
  status: string;
  printers: PrinterInfo[];
}

// ========== Settings Models ==========

export interface UserSettings {
  conversion_preferences?: import("../stores/conversionPreferences").ConversionPreferences | null;
  custom_3mf_template_id?: string | null;
  language: "zh" | "en";
  theme: "light" | "dark";
  last_lut: string;
  last_modeling_mode: string;
  last_color_mode: string;
  last_slicer: string;
  last_bed_label: string;
  palette_mode: string;
  enable_crop_modal: boolean;
  enable_blur: boolean;
  enable_fancy_loading: boolean;
  enable_witty_loading: boolean;
  enable_completion_notifications: boolean;
  enable_smooth_vector_preview: boolean;
  preserve_upload_filename_for_3mf: boolean;
  printer_model: string;
  slicer_software: string;
  device_profile_id: string;
  build_plate_id: string;
  build_plate_selections: Record<string, string>;
  external_spool_selections?: Record<string, string>;
  custom_slicer_path: string;
  custom_slicer_id: string;
  nozzle_size: string;
  enable_base_layer_height_modifier: boolean;
  enable_wipe_tower_auto_placement: boolean;
  enable_solver_cache_grid_selection: boolean;
  solver_cache_grid_resolution: 64 | 128 | 256 | 512 | 1024 | 2048;
  svg_pixels_per_mm: number;
  material_delta_e00_tolerance: number;
  auto_replace_gradient_banding: boolean;
  /** Desktop save-dialog default folder; empty = OS default. 桌面版保存对话框默认文件夹。 */
  generated_file_directory?: string;
  /** Top navigation alignment. 顶部导航对齐方式。 */
  header_nav_alignment?: "center" | "left";
}

export interface UserSettingsResponse {
  status: string;
  settings: UserSettings;
}

export interface SaveSettingsResponse {
  status: string;
  message: string;
}

export interface StatsResponse {
  calibrations: number;
  extractions: number;
  conversions: number;
}

// ========== Slicer Template Models ==========

export interface SlicerOption {
  id: string;
  display_name: string;
}

export interface SlicerListResponse {
  status: string;
  slicers: SlicerOption[];
}

// ========== Vectorizer Models ==========

export interface VectorizeParams {
  // Core
  num_colors: number;
  smoothness: number;
  detail_level: number;
  // Output enhancement
  svg_enable_stroke: boolean;
  svg_stroke_width: number;
  thin_line_max_radius: number;
  enable_coverage_fix: boolean;
  min_coverage_ratio: number;
  // Preprocessing
  smoothing_spatial: number;
  smoothing_color: number;
  max_working_pixels: number;
  // Segmentation
  slic_region_size: number;
  edge_sensitivity: number;
  refine_passes: number;
  enable_antialias_detect: boolean;
  aa_tolerance: number;
  // Curve fitting
  curve_fit_error: number;
  contour_simplify: number;
  merge_segment_tolerance: number;
  // Filtering
  min_region_area: number;
  max_merge_color_dist: number;
  min_contour_area: number;
  min_hole_area: number;
}

export interface VectorizeResponse {
  status: string;
  message: string;
  svg_url: string;
  width: number;
  height: number;
  num_shapes: number;
  num_colors: number;
  palette: string[];
}

export interface VectorizeDefaultsResponse {
  defaults: VectorizeParams;
}

/** Lab 色三元组，保持和后端 RecipePredictResponse.lab 对齐。 */
export type LabColor = [number, number, number];

/** 失败来源分类：warning 级不吓人，error 级要醒目。 */
export type PredictFailureKind = "no_forward_model" | "unknown";

/** 用户在自定义配方对话框里手动或模型填入的目标色。 */
export interface TargetColor {
  /** 受控的 hex，带 "#" 前缀，上游/展示均统一带井号。 */
  hex: string;
  /** 对应 LAB 值（仅供 UI，不回传后端）。 */
  lab: LabColor;
  /** "model" 表示是点 Predict 由后端填的；"user" 表示用户手动调过。 */
  source: "user" | "model";
}

/** 自定义配方历史条目（会话内内存，不落 localStorage）。 */
export interface RecipeHistoryItem {
  /** 稳定 ID：`${recipe.join("-")}@${layerOrder}`，便于去重 + React key。 */
  id: string;
  recipe: number[];
  layerOrder: string;
  /** 用户 apply 或 predict 时拿到的 RGB（uint8），显示色块用。 */
  predictedRgb: [number, number, number];
  /** 对应的 LAB。 */
  predictedLab: LabColor;
  /** 井号前缀的 hex，展示用。 */
  hex: string;
  /** 这条配方的颜色是否来自模型 predict；用户手调目标色后为 false。 */
  fromModel: boolean;
  /** 写入时间戳，UI 排序 / 调试用。 */
  createdAtMs: number;
  /**
   * 每层用户实际点击的原色 hex（#RRGGBB，大写）。
   * `recipe` 是翻译到 LUT 通道后的索引，可能因稀疏 LUT 代用丢失原意；
   * 侧栏历史层条按此数组渲染，保证用户点"黑"历史就显示"黑"。
   *
   * Per-layer canonical hex the user actually picked. `recipe` holds the
   * translated LUT channel indices (which may be substituted on sparse
   * LUTs), so we persist the visual intent separately and drive the side
   * panel's LayerBar off of it. Optional for backward compatibility with
   * older session histories.
   */
  displayHexes?: string[];
  /** 对应每层的原色名（与 ``displayHexes`` 对齐），用作 tooltip。Primary name per layer. */
  displayLabels?: string[];
  /**
   * 应用本配方时声明的虚拟耗材列表（LUT 原生没有、recipe 里以
   * ``palette.length + k`` 引用的原色）。历史重放时必须随 recipe 一起回传
   * 后端，否则 validator 会以 "recipe[i] out of range" 拒绝请求，worker 也
   * 无法把虚拟索引扩展到 ctx["slot_names"]（表现为 3MF 缺对象 / 透明失效）。
   *
   * Virtual materials declared when this recipe was applied. Replay paths
   * MUST forward this alongside ``recipe`` so backend validation accepts
   * indices ``>= LUT.N`` and the worker can extend ``ctx["slot_names"]``;
   * dropping it collapses virtual-index pixels back onto native channels.
   */
  virtualMaterials?: VirtualMaterial[];
}

// ============================================================================
// Gradient-group (banding) analysis
// 渐变海带纹分组（预览完成后同步计算，驱动颜色工作站的分组多选 + 自动换色）
// ============================================================================

/** One material colour entry inside a gradient group or its region. */
export interface GradientMaterialColour {
  /** Material colour hex, e.g. "#D2AEB4". */
  hex: string;
  rgb: [number, number, number];
  pixel_count: number;
}

/** A spatial connected region inside a gradient group. */
export interface GradientRegionItem {
  /** 1-based index ordered by descending pixel_count within the group. */
  region_index: number;
  pixel_count: number;
  /** [x0, y0, x1, y1] with x1/y1 exclusive (pixel coordinates). */
  bbox: [number, number, number, number];
  /** Centroid [cx, cy] in pixel coordinates. */
  centroid: [number, number];
  material_breakdown: GradientMaterialColour[];
}

/** A cluster of material colours that originated from one smooth source gradient. */
export interface GradientGroupItem {
  /** 1-based index ordered by descending total_pixel_count. */
  group_index: number;
  total_pixel_count: number;
  material_colour_count: number;
  material_colours: GradientMaterialColour[];
  /** Representative colour hex (defaults to the pixel-count majority). */
  representative_hex: string;
  representative_rgb: [number, number, number];
  boundary_pair_count: number;
  regions: GradientRegionItem[];
}

/**
 * Identifies which gradient group or region is the current "origin" of the
 * multi-select, so the panel can show the exact row the user just clicked
 * even when a region's material breakdown equals the enclosing group's
 * material colours (otherwise identical hex sets make both buttons look
 * highlighted).
 *
 * 渐变选中来源标识：用于区分"点了整组"还是"点了组内某区域"，解决
 * region.material_breakdown 与 group.material_colours 重合时两个按钮同时
 * 高亮的问题。
 */
export type GradientSelectionSource =
  | { kind: "group"; groupIndex: number }
  | { kind: "region"; groupIndex: number; regionIndex: number }
  /**
   * Multi-region selection inside a single gradient group: the user ticked
   * ≥2 sub-region checkboxes in the Gradient Groups panel to merge them
   * for flatten/recolor. All ``regionIndices`` belong to ``groupIndex``
   * (the panel enforces same-group when toggling); ordering matches the
   * order the user checked them so UI can show a stable summary.
   * 用户在面板上跨 region 勾选合并处理时的来源；所有 regionIndex 必属于同
   * 一个 groupIndex（勾跨 group 的 region 会清空旧选择）。
   */
  | {
      kind: "multi-region";
      groupIndex: number;
      regionIndices: number[];
    };

/** Response payload for ``GET /convert/gradient-groups/{session_id}``. */
export interface GradientGroupsResponse {
  session_id: string;
  /** ``"ok"`` when groups are available; ``"unavailable"`` otherwise. */
  status: "ok" | "unavailable";
  groups: GradientGroupItem[];
}

/** Request for printable recipes close to a target colour (colour workspace). */
export interface SimilarRecipesRequest {
  session_id: string;
  /** Target colour as ``#rrggbb``. */
  target_color: string;
  limit?: number;
  include_predictive?: boolean;
}

/** One suggested recipe; ``recipe`` is ordered top (viewing face) to bottom. */
export interface SimilarRecipeItem {
  hex: string;
  rgb: [number, number, number];
  delta_e00: number;
  recipe: number[];
  /**
   * ``lut`` (measured LUT entry) and ``image`` (color already in the image)
   * apply via region replace; ``predictive`` applies via recipe override.
   */
  source: "lut" | "predictive" | "image";
  /** True when this color is already printed somewhere in the current image. */
  in_image: boolean;
}

export interface SimilarRecipesResponse {
  status: string;
  target_color: string;
  layer_order: string;
  predictive_available: boolean;
  items: SimilarRecipeItem[];
}
