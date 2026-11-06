import type { ConverterDocumentState, ConverterState } from "./types";

// The exhaustive record makes a new document field an explicit history/persistence decision.
const fields: Record<keyof ConverterDocumentState, true> = {
  projectSettings: true,
  projectLutFile: true,
  projectMaterialArchiveFile: true,
  native_filament_profiles: true,
  nativeFilamentProfileScope: true,
  imageFile: true,
  workshopSource: true,
  modelSurfaceEnabled: true,
  modelSurfaceFile: true,
  modelSurfaceSelection: true,
  modelSurfacePlacement: true,
  modelSurfaceModelRotation: true,
  source_version: true,
  lut_name: true,
  lut_names: true,
  selectedNativeBrandKey: true,
  selectedNativeDbNames: true,
  target_width_mm: true,
  target_height_mm: true,
  spacer_thick: true,
  backing_infill_density_percent: true,
  structure_mode: true,
  color_mode: true,
  modeling_mode: true,
  color_layers: true,
  layer_height_mm: true,
  model_enable: true,
  model_only: true,
  model_threshold: true,
  model_margin: true,
  selectedMaterialDirNames: true,
  materialLayerCount: true,
  materialLayerHeightMm: true,
  materialBackingMaterialDirName: true,
  materialDynamicLayerCountEnabled: true,
  materialMinLayerCount: true,
  materialMaxLayerCount: true,
  quantize_colors: true,
  quantize_colors_unlocked: true,
  high_precision_3d_preview: true,
  enable_cleanup: true,
  svg_hole_compensation_enabled: true,
  svg_hole_max_area_mm2: true,
  svg_hole_max_width_mm: true,
  hue_enable: true,
  use_lut_constrained: true,
  auto_dynamic_range: true,
  chroma_gate: true,
  separate_backing: true,
  backingOutput: true,
  add_loop: true,
  loop_width: true,
  loop_length: true,
  loop_hole: true,
  loop_angle: true,
  loop_offset_x: true,
  loop_offset_y: true,
  loop_position_preset: true,
  enable_fridge_magnet: true,
  fridge_magnets: true,
  base_spacer_thick: true,
  enable_relief: true,
  color_height_map: true,
  heightmap_max_height: true,
  enable_outline: true,
  outline_width: true,
  enable_cloisonne: true,
  wire_width_mm: true,
  wire_height_mm: true,
  enable_coating: true,
  coating_height_mm: true,
  largeFormatEnabled: true,
  tileWidthMm: true,
  tileHeightMm: true,
  puzzleEnabled: true,
  puzzleStyle: true,
  puzzleSizingMode: true,
  pieceWidthMm: true,
  pieceHeightMm: true,
  puzzleRows: true,
  puzzleCols: true,
  targetPieceCount: true,
  connectorStyle: true,
  labelsEnabled: true,
  engraveBackLabels: true,
  irregularityStrength: true,
  minNeckWidthMm: true,
  autoHeightMode: true,
  heightmapFile: true,
  batchMode: true,
  batchFiles: true,
};
export const DOCUMENT_KEYS = Object.keys(fields) as Array<keyof ConverterDocumentState>;
export function captureConverterDocument(state: ConverterState): ConverterDocumentState {
  return Object.fromEntries(DOCUMENT_KEYS.map(key => [key, state[key]])) as unknown as ConverterDocumentState;
}

export function equalDocumentValue(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true;
  if (!left || !right || typeof left !== "object" || typeof right !== "object") return false;
  if (left instanceof Blob || right instanceof Blob) return false;
  if (left instanceof Set && right instanceof Set) return left.size === right.size && [...left].every(value => right.has(value));
  if (Array.isArray(left) !== Array.isArray(right)) return false;
  const a = left as Record<string, unknown>, b = right as Record<string, unknown>;
  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every(key => Object.hasOwn(b, key) && equalDocumentValue(a[key], b[key]));
}
export function sameConverterDocument(left: ConverterDocumentState, right: ConverterDocumentState): boolean {
  return DOCUMENT_KEYS.every(key => equalDocumentValue(left[key], right[key]));
}
