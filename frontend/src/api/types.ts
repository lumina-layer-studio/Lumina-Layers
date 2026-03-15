export interface HealthResponse {
  status: string;
  version: string;
  uptime_seconds: number;
}

// ========== Enums ==========

export enum ColorMode {
  BW = "BW (Black & White)",
  FOUR_COLOR = "4-Color",
  SIX_COLOR = "6-Color (Smart 1296)",
  EIGHT_COLOR = "8-Color Max",
  MERGED = "Merged",
}

export enum ModelingMode {
  HIGH_FIDELITY = "high-fidelity",
  PIXEL = "pixel",
  VECTOR = "vector",
}

export enum StructureMode {
  DOUBLE_SIDED = "Double-sided",
  SINGLE_SIDED = "Single-sided",
}

// ========== Request Models ==========

export interface ConvertPreviewRequest {
  lut_name: string;
  target_width_mm: number;
  auto_bg: boolean;
  bg_tol: number;
  color_mode: ColorMode;
  modeling_mode: ModelingMode;
  quantize_colors: number;
  enable_cleanup: boolean;
  hue_weight: number;
  is_dark: boolean;
}

export interface ConvertGenerateRequest extends ConvertPreviewRequest {
  spacer_thick: number;
  structure_mode: StructureMode;
  separate_backing: boolean;
  add_loop: boolean;
  loop_width: number;
  loop_length: number;
  loop_hole: number;
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
  replacement_regions?: ColorReplacementItem[];
  free_color_set?: string[];
  use_cached_matched_rgb?: boolean;
}

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

// ========== Response Models ==========

/** 预览接口响应，包含 session_id 和预览图 URL */
export interface PreviewResponse {
  session_id: string;
  status: string;
  message: string;
  preview_url: string;
  preview_glb_url: string | null; // GLB 3D 预览 URL
  palette: PaletteEntry[];
  dimensions: { width: number; height: number };
  contours?: Record<string, number[][][]> | null; // hex -> list of contour polygons (world coords mm)
}

/** 生成接口响应，包含下载 URL 和可选的 3D 预览 URL */
export interface GenerateResponse {
  status: string;
  message: string;
  download_url: string;
  preview_3d_url?: string;
  threemf_disk_path?: string;
}

export interface LutListResponse {
  luts: LutInfo[];
}

export interface LutInfo {
  name: string;
  color_mode: ColorMode;
  path: string;
}

export interface BedSizeItem {
  label: string;
  width_mm: number;
  height_mm: number;
  is_default: boolean;
}

export interface BedSizeListResponse {
  beds: BedSizeItem[];
}

// ========== Calibration Enums ==========

export enum CalibrationColorMode {
  BW = "BW (Black & White)",
  FOUR_COLOR = "4-Color",
  FIVE_COLOR_EXT = "5-Color Extended (1444)",
  SIX_COLOR = "6-Color (Smart 1296)",
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
  backing: BackingColor;
}

// ========== Calibration Response Models ==========

export interface CalibrationResponse {
  status: string;
  message: string;
  download_url: string;
  preview_url: string | null;
}

// ========== Extractor Enums ==========

export enum ExtractorColorMode {
  BW = "BW (Black & White)",
  FOUR_COLOR = "4-Color",
  FIVE_COLOR_EXT = "5-Color Extended",
  SIX_COLOR = "6-Color (Smart 1296)",
  EIGHT_COLOR = "8-Color Max",
}

export enum ExtractorPage {
  PAGE_1 = "Page 1",
  PAGE_2 = "Page 2",
}

// ========== Extractor Response Models ==========

export interface ExtractResponse {
  session_id: string;
  status: string;
  message: string;
  lut_download_url: string;
  warp_view_url: string;
  lut_preview_url: string;
}

export interface ManualFixResponse {
  status: string;
  message: string;
  lut_preview_url: string;
}

// ========== LUT Manager Models ==========

export interface LutInfoResponse {
  name: string;
  color_mode: string;
  color_count: number;
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

export interface LutColorsResponse {
  lut_name: string;
  total: number;
  colors: LutColorEntry[];
}

// ========== Slicer Models ==========

export interface SlicerInfo {
  id: string;
  display_name: string;
  exe_path: string;
}

export interface SlicerDetectResponse {
  slicers: SlicerInfo[];
}

export interface SlicerLaunchRequest {
  slicer_id: string;
  file_path: string;
}

export interface SlicerLaunchResponse {
  status: string;
  message: string;
}

// ========== Batch Processing Models ==========

export interface BatchItemResult {
  filename: string;
  status: string;
  error?: string;
}

export interface BatchResponse {
  status: string;
  message: string;
  download_url: string;
  results: BatchItemResult[];
}

export interface BatchConvertParams {
  lut_name: string;
  target_width_mm: number;
  spacer_thick: number;
  structure_mode: string;
  auto_bg: boolean;
  bg_tol: number;
  color_mode: string;
  modeling_mode: string;
  quantize_colors: number;
  enable_cleanup: boolean;
  hue_weight: number;
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
}

// ========== Color Replace Models ==========

export interface ColorReplaceResponse {
  status: string;
  message: string;
  preview_url: string;
  replacement_count: number;
}

// ========== Region Detection & Replace Models ==========

/** 连通区域检测响应 */
export interface RegionDetectResponse {
  region_id: string;
  color_hex: string;
  pixel_count: number;
  preview_url: string;
  contours?: number[][][] | null;
}

/** 区域替换响应 */
export interface RegionReplaceResponse {
  preview_url: string;
  preview_glb_url?: string | null;
  color_contours?: Record<string, number[][][]> | null;
  message: string;
}

// ========== Settings Models ==========

export interface UserSettings {
  last_lut: string;
  last_modeling_mode: string;
  last_color_mode: string;
  last_slicer: string;
  palette_mode: string;
  enable_crop_modal: boolean;
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
