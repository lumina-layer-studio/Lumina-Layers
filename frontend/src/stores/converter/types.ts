import type { PresetNameError, SavePresetResult, PresetOptions } from "../conversionPreferences";
import type { ApiRequestOptions } from "../../api/client";
import type {
  AutoHeightMode,
  BatchPreviewItem,
  BatchResponse,
  BackingOutput,
  BedSizeItem,
  ColorMode,
  ColorReplacementItem,
  DynamicMaterialRecipe,
  ExportMaterialSelection,
  FridgeMagnetItem,
  GradientGroupItem,
  GradientSelectionSource,
  LutColorEntry,
  LutColorsCard,
  LutDetailsCatalogGroup,
  LutInfo,
  LutInfoResponse,
  MaterialColorSuggestionsResponse,
  MaterialLayerBenefitPoint,
  MaterialLayerBenefitScope,
  ModelingMode,
  ModelSurfaceCandidate,
  ModelSurfaceMeshSummary,
  NativeBrandGroup,
  PaletteEntry,
  PerformanceTiming,
  PuzzleConnectorStyle,
  PuzzleSizingMode,
  PuzzleStyle,
  RecipeHistoryItem,
  RecipeOverrideItem,
  RecipeOverrideApplyRequest,
  RecipeOverrideApplyResponse,
  SelectionDocumentResponse,
  SelectionMutationRequest,
  StructureMode,
  VirtualMaterial,
} from "../../api/types";
import { type ImageRotationDegrees } from "../../utils/imageRotation";
import type { WorkshopRecipeSource } from "../../workshop/types";

// ========== Selection Mode Types ==========

export type SelectionMode =
  | "select-all"
  | "current"
  | "multi-select"
  | "region";

export type SelectionTool = "same-color" | "color-range" | "point" | "brush";

export type SelectionDocument = SelectionDocumentResponse;

export interface SelectionMutationInput {
  operation: SelectionMutationRequest["operation"];
  x?: number;
  y?: number;
  colorHex?: string;
  colorHexes?: string[];
  gradientGroupIndex?: number;
  gradientRegionIndex?: number;
  selectionSource?: GradientSelectionSource;
  colorTolerance?: number;
  brushRadius?: number;
  brushPoints?: Array<{ x: number; y: number }>;
  brushStrokes?: Array<Array<{ x: number; y: number }>>;
}

export interface PendingSelectionMutation {
  id: number;
  sessionId: string;
  input: SelectionMutationInput;
}

export type SourceVersion = "legacy" | "native" | "material";

export interface RegionData {
  regionId: string;
  colorHex: string;
  pixelCount: number;
  previewUrl: string;
  contours?: number[][][] | null;
  bbox?: [number, number, number, number] | null;
  clickX?: number;
  clickY?: number;
}

// ========== Pending Replacement Types ==========

export interface PendingReplacement {
  sourceHex: string; // 原色 hex（不带 #）
  targetHex: string; // 目标色 hex（不带 #）
  mode: SelectionMode; // 触发时的选择模式
  sourceColors?: string[]; // select-all 批量模式下的多个源色
  sourceRegions?: RegionData[]; // multi-select 模式下的多个连通区域
}

export type RemapSnapshot = Record<string, string>;


export type ModelSurfacePlacementMode = "edge_to_edge" | "inset";

export interface ModelSurfacePlacement {
  mode: ModelSurfacePlacementMode;
  offset_x_mm: number;
  offset_y_mm: number;
  scale: number;
  rotation_deg: number;
  inset_mm: number;
}

export interface ModelSurfaceModelRotation {
  x_deg: number;
  y_deg: number;
  z_deg: number;
}

export type ContentCommitStatus =
  | "idle"
  | "pending"
  | "committed"
  | "failed"
  | "unknown";

export interface WorkshopConverterImageInput {
  file: File;
  pixelWidth: number;
  pixelHeight: number;
  targetWidthMm: number;
  targetHeightMm: number;
  source: WorkshopRecipeSource;
}

export interface NativeFilamentProfileScope {
  slicer: string;
  printer_id: string;
  device_profile_id: string;
  nozzle_size: string;
}

export type NativeMaterialSelectionAction = "edit" | "generate" | "batch";

// ========== State Interface ==========

/** Durable artwork inputs. Runtime results and view preferences never belong in document history. */
export interface ConverterDocumentState {
  projectSettings: import("./project").ProjectConverterSettings | null;
  projectLutFile: File | null;
  projectMaterialArchiveFile: File | null;
  native_filament_profiles: Record<string, string>;
  nativeFilamentProfileScope: NativeFilamentProfileScope | null;
  imageFile: File | null;
  workshopSource: WorkshopRecipeSource | null;
  modelSurfaceEnabled: boolean;
  modelSurfaceFile: File | null;
  modelSurfaceSelection: Record<string, unknown> | null;
  modelSurfacePlacement: ModelSurfacePlacement;
  modelSurfaceModelRotation: ModelSurfaceModelRotation;
  source_version: SourceVersion;
  lut_name: string;
  lut_names: string[];
  selectedNativeBrandKey: string;
  selectedNativeDbNames: string[];
  target_width_mm: number;
  target_height_mm: number;
  spacer_thick: number;
  backing_infill_density_percent: number;
  structure_mode: StructureMode;
  color_mode: ColorMode;
  modeling_mode: ModelingMode;
  color_layers: number | null;
  layer_height_mm: number | null;
  model_enable: boolean;
  model_only: boolean;
  model_threshold: number | null;
  model_margin: number | null;
  selectedMaterialDirNames: string[];
  materialLayerCount: number;
  materialLayerHeightMm: number;
  materialBackingMaterialDirName: string | null;
  materialDynamicLayerCountEnabled: boolean;
  materialMinLayerCount: number;
  materialMaxLayerCount: number;
  quantize_colors: number;
  quantize_colors_unlocked: boolean;
  high_precision_3d_preview: boolean;
  enable_cleanup: boolean;
  svg_hole_compensation_enabled: boolean;
  svg_hole_max_area_mm2: number;
  svg_hole_max_width_mm: number;
  hue_enable: boolean;
  use_lut_constrained: boolean;
  auto_dynamic_range: boolean;
  chroma_gate: number;
  separate_backing: boolean;
  backingOutput: BackingOutput;
  add_loop: boolean;
  loop_width: number;
  loop_length: number;
  loop_hole: number;
  loop_angle: number; // -180 到 180 度，默认 0
  loop_offset_x: number; // -20 到 20 mm，默认 0
  loop_offset_y: number; // -20 到 20 mm，默认 0
  loop_position_preset: string; // 默认 "top-center"
  enable_fridge_magnet: boolean;
  fridge_magnets: FridgeMagnetItem[];
  base_spacer_thick: number;
  enable_relief: boolean;
  color_height_map: Record<string, number>;
  heightmap_max_height: number;
  enable_outline: boolean;
  outline_width: number;
  enable_cloisonne: boolean;
  wire_width_mm: number;
  wire_height_mm: number;
  enable_coating: boolean;
  coating_height_mm: number;
  largeFormatEnabled: boolean;
  tileWidthMm: number;
  tileHeightMm: number;
  puzzleEnabled: boolean;
  puzzleStyle: PuzzleStyle;
  puzzleSizingMode: PuzzleSizingMode;
  pieceWidthMm: number;
  pieceHeightMm: number;
  puzzleRows: number;
  puzzleCols: number;
  targetPieceCount: number;
  connectorStyle: PuzzleConnectorStyle;
  labelsEnabled: boolean;
  engraveBackLabels: boolean;
  irregularityStrength: number;
  minNeckWidthMm: number;
  autoHeightMode: AutoHeightMode;
  heightmapFile: File | null;
  batchMode: boolean;
  batchFiles: File[];
}

/** Source-specific handles and metadata, rebuilt or leased independently of artwork inputs. */
export interface ConverterSourceRuntimeState {
  modelSurfacePreviewUrl: string | null;
  imagePreviewUrl: string | null;
  projectSourceKey: string | null;
  projectResourceSessionIds: string[];
  aspectRatio: number | null;
  conversionParameterContext: "defaults" | "restoring" | "project";
  modelSurfaceModelFileId: string | null;
  modelSurfaceSummary: ModelSurfaceMeshSummary | null;
  modelSurfaceSelectionId: string | null;
  modelSurfaceFootprint: Record<string, unknown> | null;
  modelSurfaceCandidates: ModelSurfaceCandidate[];
  selectedLutInfo: LutInfoResponse | null;
  heightmapThumbnailUrl: string | null;
  heightmapUploadSessionId: string | null;
}

/** Local presentation and interaction preferences, outside the undo journal. */
export interface ConverterViewState {
  preferredSizeAxis: "width" | "height";
  selectedFridgeMagnetId: string | null;
  largeFormatTileOverlayVisible: boolean;
  enableCrop: boolean;
  cropModalOpen: boolean;
  layerImagesOpen: boolean;
  selectionMode: SelectionMode;
  selectionTool: SelectionTool;
  brushSizePx: number;
  colorRangeTolerance: number;
  selectionBlinkEnabled: boolean;
}

export interface ConverterRuntimeState {
  nativeMaterialSelection: ExportMaterialSelection | null;
  nativeMaterialSelectionAction: NativeMaterialSelectionAction | null;
  nativeMaterialSelectionLoading: boolean;
  nativeMaterialSelectionError: string | null;
  // 图片

  // 模型覆面
  modelSurfaceLoading: boolean;
  modelSurfaceSelecting: boolean;
  modelSurfaceError: string | null;
  modelSurfaceWarnings: string[];

  // 会话（预览后由后端返回）
  sessionId: string | null;

  // 基础参数
  nativeBrandGroups: NativeBrandGroup[];
  nativeBrandGroupsLoading: boolean;

  // Material-archive mode
  materialDynamicRecipes: DynamicMaterialRecipe[];
  materialLayerBenefitCurve: MaterialLayerBenefitPoint[];
  materialLayerBenefitScope: MaterialLayerBenefitScope;
  materialLayerBenefitPixelCount: number;

  // 高级设置

  // 挂件环

  // 浮雕

  // 描边

  // 掐丝珐琅

  // 涂层

  // 大画幅
  /** View-only: draw the tile cut lines over the 3D preview. */
  puzzleOverlayUrl: string | null;
  puzzleWarnings: string[];
  puzzleResolvedRows: number | null;
  puzzleResolvedCols: number | null;
  puzzleResolvedPieceCount: number | null;
  puzzleDerivedPieceWidthMm: number | null;
  puzzleDerivedPieceHeightMm: number | null;

  // 颜色替换
  replacement_regions: ColorReplacementItem[];
  recipe_overrides: RecipeOverrideItem[];
  customRecipeHistory: RecipeHistoryItem[];
  free_color_set: Set<string>;

  // 调色板与选择
  selectedColor: string | null;
  palette: PaletteEntry[];

  // 颜色替换映射（纯前端）
  colorRemapMap: Record<string, string>;
  remapHistory: RemapSnapshot[];
  remapRedoHistory: RemapSnapshot[];
  historyCanUndo: boolean;
  historyCanRedo: boolean;
  historyBusy: boolean;
  contentCommitStatus: ContentCommitStatus;
  contentCommitOperationId: string | null;
  /** Revisions explicitly acknowledged by authoritative editor responses. */
  confirmedEditorCommit: {
    sessionId: string;
    selectionRevision: number;
    contentRevision: number;
  } | null;
  pendingEditorProject: File | null;

  // 颜色轮廓数据（后端 OpenCV 提取，用于 3D 高亮）
  colorContours: Record<string, number[][][]>;
  // 浮雕联动

  // 3D 预览
  previewGlbUrl: string | null;
  previewPerformanceTiming: PerformanceTiming | null;
  generatePerformanceTiming: PerformanceTiming | null;
  lutMatchMode: string | null;
  lutMatchInfo: Record<string, unknown> | null;

  // 预览时的原始尺寸（用于实时缩放比例计算）
  preview_width_mm: number | null; // 预览时的原始宽度
  preview_height_mm: number | null; // 预览时的原始高度
  preview_spacer_thick: number | null; // 预览时的原始厚度
  previewPixelWidth: number | null; // 预览图像像素宽度（用于 3D→像素坐标转换）
  previewPixelHeight: number | null; // 预览图像像素高度（用于 3D→像素坐标转换）
  previewWarnings: string[];
  generateWarnings: string[];
  largeFormatWarnings: string[];
  largeFormatFailedTiles: string[];

  // 模型边界（供 KeychainRing3D 定位）
  modelBounds: {
    minX: number;
    maxX: number;
    minY: number;
    maxY: number;
    maxZ: number;
  } | null;

  // 裁剪
  isCropping: boolean;

  // 自动检测颜色
  autoDetectColorsLoading: boolean;

  // UI 状态
  isLoading: boolean;
  isGenerating: boolean;
  error: string | null;
  previewImageUrl: string | null;
  modelUrl: string | null;

  // LUT 列表
  lutList: string[];
  lutListLoading: boolean;
  lutListFull: LutInfo[];
  legacyCatalogGroups: LutDetailsCatalogGroup[];
  legacyCatalogLoading: boolean;
  selectedLegacyManufacturer: string;

  // LUT 全部颜色
  lutColors: LutColorEntry[];
  lutColorCards: LutColorsCard[];
  lutColorsLoading: boolean;
  lutColorsLutName: string;
  lutColorsSessionId: string | null;

  // 材料档案模式下的可达色建议（替换 lutColors 的作用）
  // Material-archive mode's achievable-color suggestions (replaces lutColors).
  materialSuggestions: MaterialColorSuggestionsResponse | null;
  materialSuggestionsLoading: boolean;
  materialSuggestionsTargetHex: string | null;
  materialSuggestionsError: string | null;

  // 预览完成后后端同步计算的"渐变海带纹分组"。用于颜色工作站的按组多选替换
  // 以及可选的自动去海带纹批量换色。未计算 / 未命中时保持为 ``null``。
  // Gradient-banding groups computed synchronously by the preview pipeline.
  // Drives the Color Workstation group multi-select flow and the optional
  // "auto replace gradient banding" setting. Stays ``null`` until a fetch
  // completes; ``[]`` means the backend ran but reported no banding.
  gradientGroups: GradientGroupItem[] | null;
  gradientGroupsLoading: boolean;
  gradientGroupsError: string | null;
  /** Session ID of the currently-loaded groups (for staleness checks). */
  gradientGroupsSessionId: string | null;
  /**
   * Which gradient group/region the user most recently clicked in the
   * Gradient Groups panel. ``null`` when the current multi-selection was not
   * initiated from the panel. UI uses this to disambiguate group vs region
   * highlight when their hex sets are identical.
   *
   * 面板最近一次点击的分组/区域标识；当前多选不是由面板发起时为 null。
   */
  gradientSelection: GradientSelectionSource | null;

  /**
   * Ordered list of regions the user ticked in the Gradient Groups panel
   * for merged flatten/recolor. All entries share the same ``groupIndex``
   * (same-group invariant enforced by the toggle action). Empty array
   * means "no multi-region selection" — the existing single-region /
   * single-group flows stay untouched.
   * 用户在面板勾选的 region 列表（保持勾选顺序），用于"合并去海带纹 / 合并
   * 换色"；同 group 不变式由 toggle action 守护。
   */
  selectedGradientRegions: Array<{
    groupIndex: number;
    regionIndex: number;
  }>;

  // 热床尺寸
  bed_label: string;
  bedSizes: BedSizeItem[];
  bedSizesLoading: boolean;

  // 批量模式
  batchLoading: boolean;
  batchResult: BatchResponse | null;
  batchPreviewItems: BatchPreviewItem[];

  // 颜色替换预览
  replacePreviewLoading: boolean;
  originalPreviewUrl: string | null;
  previewBaseImageUrl: string | null;

  // 切片集成：3MF 路径
  threemfDiskPath: string | null;
  downloadUrl: string | null;

  // 分层预览
  layerImages: { layer_index: number; name: string; url: string }[];
  layerImagesLoading: boolean;
  layerImagesSourceKey: string | null;

  // 选择工具与统一选区。Legacy fields remain during migration so existing
  // gradient/custom-recipe consumers can be moved without a flag day.
  selectionDocument: SelectionDocument | null;
  /** Unconfirmed gesture intents for immediate visual feedback only. */
  pendingSelectionMutations: PendingSelectionMutation[];
  /** CIEDE2000 tolerance used by the colour-range selection tool. */
  selectedColors: Set<string>;
  regionData: RegionData | null;
  selectedRegions: RegionData[];

  // 待确认颜色替换
  pendingReplacement: PendingReplacement | null;

  // 区域替换计数（current 模式不走 colorRemapMap，需要独立计数以启用清除按钮）
  regionReplacementCount: number;

  // 当前图片是否已手动点击过预览按钮（自动预览的前置条件）
  hasManualPreview: boolean;

  /**
   * An established preview was invalidated and still needs one debounced
   * refresh. Store-owned so the obligation survives hook unmount/remount.
   * 已有预览失效后仍欠一次防抖刷新；由 store 持有以跨越 Hook 重挂载。
   */
  previewAutoRefreshPending: boolean;

  /**
   * Monotonic ownership revision for preview inputs/results. Any action that
   * clears the preview increments it so an older response cannot bind later.
   * 预览输入/结果所有权版本；清空预览时递增，拒绝旧响应回写。
   */
  previewRequestRevision: number;

  /** Monotonic counter bumped whenever a valid preview request starts. */
  previewSubmissionSequence: number;
}

export interface ConverterState extends ConverterDocumentState, ConverterSourceRuntimeState, ConverterViewState, ConverterRuntimeState {}

// ========== Actions Interface ==========

export interface ConverterActions {
  setProjectSettings: (changes: Partial<import("./project").ProjectConverterSettings>) => void;
  /** Publish a fully prepared project without resetting/re-importing its source. */
  commitProjectRestore: (state: ConverterState) => void;
  restoreConversionDefaults: () => void;
  applyConversionPreset: (id: string | null) => boolean;
  saveConversionPreset: (name: string, options?: PresetOptions) => SavePresetResult;
  updateConversionPreset: (id: string) => boolean;
  renameConversionPreset: (id: string, name: string) => PresetNameError | "missing-preset" | null;
  deleteConversionPreset: (id: string) => void;
  // 图片
  setImageFile: (file: File | null) => void;
  rotateImageForExport: (degrees: ImageRotationDegrees) => Promise<void>;
  loadVectorizedSvgIntoConverter: (file: File) => void;
  loadWorkshopImageIntoConverter: (
    input: WorkshopConverterImageInput,
  ) => void;
  setModelSurfaceEnabled: (enabled: boolean) => void;
  uploadModelSurfaceFile: (file: File) => Promise<void>;
  clearModelSurface: () => void;
  selectModelSurfaceFace: (faceIndex: number, candidateId?: string) => Promise<void>;
  updateModelSurfacePlacement: (updates: Partial<ModelSurfacePlacement>) => void;
  updateModelSurfaceModelRotation: (updates: Partial<ModelSurfaceModelRotation>) => void;
  fitModelSurfaceArtwork: () => void;

  // 参数 setter
  setLutName: (name: string) => void;
  setLegacyLutNames: (names: string[]) => void;
  setTargetWidthMm: (width: number) => void;
  setTargetHeightMm: (height: number) => void;
  setSpacerThick: (thick: number) => void;
  setBackingInfillDensityPercent: (density: number) => void;
  setStructureMode: (mode: StructureMode) => void;
  setColorMode: (mode: ColorMode) => void;
  setModelingMode: (mode: ModelingMode) => void;
  setColorLayers: (layers: number | null) => void;
  setLayerHeightMm: (height: number | null) => void;
  setModelEnable: (enabled: boolean) => void;
  setModelOnly: (enabled: boolean) => void;
  setModelThreshold: (value: number | null) => void;
  setModelMargin: (value: number | null) => void;
  setQuantizeColors: (colors: number) => void;
  setQuantizeColorsUnlocked: (unlocked: boolean) => void;
  setHighPrecision3dPreview: (enabled: boolean) => void;
  setEnableCleanup: (enabled: boolean) => void;
  setSvgHoleCompensationEnabled: (enabled: boolean) => void;
  setSvgHoleMaxAreaMm2: (area: number) => void;
  setSvgHoleMaxWidthMm: (width: number) => void;
  setHueEnable: (enabled: boolean) => void;
  setUseLutConstrained: (enabled: boolean) => void;
  setAutoDynamicRange: (enabled: boolean) => void;
  setChromaGate: (threshold: number) => void;
  setSeparateBacking: (enabled: boolean) => void;
  setBackingOutput: (output: BackingOutput) => void;
  setAddLoop: (enabled: boolean) => void;
  setLoopWidth: (width: number) => void;
  setLoopLength: (length: number) => void;
  setLoopHole: (hole: number) => void;
  setLoopAngle: (angle: number) => void;
  setLoopOffsetX: (x: number) => void;
  setLoopOffsetY: (y: number) => void;
  setLoopOffsets: (x: number, y: number) => void;
  setLoopPositionPreset: (preset: string) => void;
  setEnableFridgeMagnet: (enabled: boolean) => void;
  resetFridgeMagnetLayout: () => void;
  addFridgeMagnet: () => void;
  removeFridgeMagnet: (id: string) => void;
  updateFridgeMagnet: (
    id: string,
    updates: Partial<Omit<FridgeMagnetItem, "id">>,
  ) => void;
  updateFridgeMagnetCenter: (
    id: string,
    centerX: number,
    centerY: number,
  ) => void;
  selectFridgeMagnet: (id: string | null) => void;
  clearSelectedFridgeMagnet: () => void;
  setEnableRelief: (enabled: boolean) => void;
  setColorHeightMap: (map: Record<string, number>) => void;
  setHeightmapMaxHeight: (height: number) => void;
  setEnableOutline: (enabled: boolean) => void;
  setOutlineWidth: (width: number) => void;
  setEnableCloisonne: (enabled: boolean) => void;
  setWireWidthMm: (width: number) => void;
  setWireHeightMm: (height: number) => void;
  setEnableCoating: (enabled: boolean) => void;
  setCoatingHeightMm: (height: number) => void;

  // 大画幅
  setLargeFormatEnabled: (enabled: boolean) => void;
  setTileWidthMm: (width: number) => void;
  setTileHeightMm: (height: number) => void;
  setLargeFormatTileOverlayVisible: (visible: boolean) => void;
  setPuzzleEnabled: (enabled: boolean) => void;
  setPuzzleStyle: (style: PuzzleStyle) => void;
  setPuzzleSizingMode: (mode: PuzzleSizingMode) => void;
  setPieceWidthMm: (width: number) => void;
  setPieceHeightMm: (height: number) => void;
  setPuzzleRows: (rows: number) => void;
  setPuzzleCols: (cols: number) => void;
  setTargetPieceCount: (count: number) => void;
  setConnectorStyle: (style: PuzzleConnectorStyle) => void;
  setLabelsEnabled: (enabled: boolean) => void;
  setEngraveBackLabels: (enabled: boolean) => void;
  setIrregularityStrength: (strength: number) => void;
  setMinNeckWidthMm: (width: number) => void;
  submitPuzzleLayoutPreview: () => Promise<boolean>;
  clearPuzzleLayoutPreview: () => void;

  // 热床尺寸
  setBedLabel: (label: string) => void;
  fetchBedSizes: () => Promise<void>;

  // 调色板与选择
  setSelectedColor: (hex: string | null) => void;
  setPalette: (entries: PaletteEntry[]) => void;

  // 统一选择工具；setSelectionMode 在迁移期仅保留兼容映射。
  setSelectionMode: (mode: SelectionMode) => void;
  setSelectionTool: (tool: SelectionTool) => void;
  setBrushSizePx: (size: number) => void;
  setColorRangeTolerance: (tolerance: number) => void;
  hydrateSelectionDocument: () => Promise<void>;
  applySelectionMutation: (input: SelectionMutationInput) => Promise<boolean>;
  toggleColorInSelection: (hex: string) => void;
  removeColorFromSelection: (hex: string) => void;
  applyBatchColorRemap: (newHex: string) => Promise<void>;
  detectRegion: (x: number, y: number) => Promise<void>;
  detectAndAccumulateRegion: (x: number, y: number) => Promise<void>;
  removeRegionFromSelection: (regionId: string) => void;
  setSelectionBlinkEnabled: (enabled: boolean) => void;
  toggleSelectionBlink: () => void;
  applyRegionReplace: (newHex: string) => Promise<void>;
  applyCustomRecipeOverride: (
    regionIds: string[],
    recipe: number[],
    layerOrder?: string,
    /** Virtual materials declared at apply time; required when ``recipe`` carries indices ``>= LUT.N``. */
    virtualMaterials?: VirtualMaterial[],
  ) => Promise<void>;
  commitRecipeOverride: (request: RecipeOverrideApplyRequest) => Promise<RecipeOverrideApplyResponse | undefined>;
  upsertRecipeOverrides: (
    regionIds: string[],
    recipe: number[],
    layerOrder: string,
    /** Optional virtuals to persist alongside the override so ``/generate`` can extend the palette. */
    virtualMaterials?: VirtualMaterial[],
  ) => void;
  clearRecipeOverrides: (regionIds?: string[]) => void;
  /** 追加一条历史；按 id LRU 置顶，容量 10。 */
  pushCustomRecipeHistory: (item: RecipeHistoryItem) => void;
  /** 清空历史（一般在 submitPreview 之外很少主动调）。 */
  clearCustomRecipeHistory: () => void;
  /** 应用一条历史到当前选区；内部复用 applyCustomRecipeOverride。 */
  applyCustomRecipeFromHistory: (
    historyId: string,
    regionIds: string[],
  ) => Promise<void>;

  /**
   * Replace the shared selection mask with ``targetHex`` via region replace.
   * Resolves ``true`` when the shared-selection path consumed the request
   * (applied or aborted) and ``false`` when no shared selection exists.
   * 用目标色替换共享选区；返回 true 表示已由共享选区路径处理（成功或中止），
   * false 表示当前没有共享选区。
   */
  replaceSharedSelectionColor: (targetHex: string) => Promise<boolean>;

  // 待确认颜色替换
  setPendingReplacement: (pending: PendingReplacement | null) => void;
  confirmReplacement: () => Promise<void>;

  // 颜色替换（纯前端）
  applyColorRemap: (origHex: string, newHex: string) => void;
  undoColorRemap: () => Promise<void>;
  redoColorRemap: () => Promise<void>;
  canUndoAdjustments: () => boolean;
  canRedoAdjustments: () => boolean;
  clearAllRemaps: () => Promise<void>;
  clearSelection: () => Promise<void>;

  // 浮雕高度
  updateColorHeight: (hex: string, heightMm: number) => void;
  applyAutoHeight: (mode: "darker-higher" | "lighter-higher") => void;
  setAutoHeightMode: (mode: AutoHeightMode) => void;

  // 高度图
  setHeightmapFile: (file: File | null) => void;
  uploadHeightmap: () => Promise<void>;

  // GLB 预览
  setPreviewGlbUrl: (url: string | null) => void;

  /**
   * Poll ``/api/convert/glb-status`` after a replace-* endpoint returned
   * ``preview_glb_url: null``; on ``ready`` the new URL is written into
   * ``previewGlbUrl``. Re-entrant: later replace calls override the
   * poller via a monotonic token so stale results can never overwrite
   * the freshest GLB. 异步 GLB 轮询；各 replace 成功后一行调用即可。
   */
  _pollAsyncGlb: () => void;

  /** Rebuild only the lightweight GLB renderer for the current SVG session. */
  rebuildVectorPreviewRenderer: (
    enableSmoothVectorPreview: boolean,
  ) => Promise<void>;

  // 模型边界
  setModelBounds: (bounds: ConverterState["modelBounds"]) => void;

  // API 操作
  uploadLut: (file: File) => Promise<void>;
  fetchLutList: (options?: ApiRequestOptions) => Promise<void>;
  fetchLutCatalog: (signal?: AbortSignal) => Promise<void>;
  fetchLegacyCatalog: (options?: ApiRequestOptions) => Promise<void>;
  setLegacyManufacturer: (name: string) => void;
  fetchLutColors: (
    lutName: string,
    signal?: AbortSignal,
  ) => Promise<void>;

  // 材料档案模式下按目标色请求建议
  // Query achievable-color suggestions for a target hex (material-archive mode).
  fetchMaterialSuggestions: (targetHex: string) => Promise<void>;
  clearMaterialSuggestions: () => void;

  /**
   * Pull the preview's gradient-banding groups from the backend session.
   * Safe to call multiple times: if ``sessionId`` matches the currently
   * loaded groups the call is a cheap no-op. A new session triggers a
   * fresh fetch that aborts any in-flight request.
   *
   * 从后端 session 拉取渐变海带纹分组：同 sessionId 直接复用缓存，不同则
   * 触发新请求并取消旧请求。
   */
  fetchGradientGroups: (sessionId: string) => Promise<void>;
  /** Reset gradient-group state (e.g. on new image upload or mode switch). */
  clearGradientGroups: () => void;
  /**
   * Collapse every gradient group to its representative colour by populating
   * ``colorRemapMap`` with non-representative → representative pairs and
   * flushing the batch through the existing replace-preview path.
   *
   * 把每个渐变分组统一替换为代表色：在 ``colorRemapMap`` 里注册非代表色 →
   * 代表色的映射，与手动换色共用批量提交与回执回滚流程。
   *
   * Called automatically when ``autoReplaceGradientBanding`` is on, but
   * also exposed so a button can trigger it on demand.
   */
  applyAutoGradientReplace: () => Promise<void>;
  /**
   * Replace ``selectedColors`` with the given hexes in one shot and switch
   * to ``select-all`` mode. Used by the Gradient Groups panel so a single
   * click multi-selects every colour inside a gradient group or region
   * without firing N sequential highlight requests. When ``source`` is
   * provided the store remembers *which* group/region triggered the batch
   * so the panel can highlight exactly one row even when a region and its
   * enclosing group share an identical hex set.
   *
   * 一次性把渐变分组内的所有耗材色写入多选集合：切到 select-all 模式 +
   * 合并成一次高亮预览请求。传 ``source`` 可记录触发本次多选的分组/区域，
   * 供面板按钮排它性高亮使用。
   */
  selectGradientGroupColors: (
    hexes: string[],
    source?: GradientSelectionSource,
  ) => void;
  /**
   * Flatten gradient banding for a single group — or a specific region
   * inside that group — without requiring the user to first multi-select
   * and pick a target colour. Mirrors :func:`applyAutoGradientReplace`
   * but scoped to one gradient, so the user can fix one band at a time.
   *
   * 针对单个渐变分组（或组内某个区域）一键去除海带纹：把非代表色映射
   * 到代表色并走 ``submitReplacePreview`` 刷预览，无需先选中再拾色器。
   */
  applyGradientReplaceForGroup: (
    groupIndex: number,
    regionIndex?: number,
  ) => Promise<void>;
  /**
   * Replace the pixels inside exactly one gradient sub-region with
   * ``targetHex``. Backed by ``POST /api/convert/region-replace`` with
   * ``gradient_group_index`` / ``gradient_region_index``; the server
   * rebuilds the mask from the cached per-pixel ``gradient_region_id_map``
   * so only that banded region changes, even when other regions on the
   * canvas share the same quantised hex.
   *
   * Unlike :func:`confirmReplacement` + ``colorRemapMap`` (which is a
   * whole-image ``hex → hex`` mapping and would recolour every matching
   * pixel), this action is strictly spatial. Callers are the Gradient
   * Groups panel + LUT picker when the current selection originated from
   * a region button.
   *
   * 仅替换某个 gradient 子区域内的像素为 ``targetHex``。用后端 region-replace
   * 的 gradient 路径，通过缓存的 region_id_map 精确定位，不会误伤共享
   * 同一量化 hex 的其它区域——修复"换一条 cyan 带 → 全身皮肤变色"的 bug。
   */
  applyGradientRegionPixelReplace: (
    groupIndex: number,
    regionIndex: number,
    targetHex: string,
  ) => Promise<void>;

  /**
   * Toggle a sub-region's checkbox in the Gradient Groups panel.
   *
   * Same-group invariant: if the new region's ``groupIndex`` differs from
   * the current selection's group, the existing list is dropped and only
   * the new region kept. This prevents users accidentally merging regions
   * from unrelated gradients (e.g. a sky band + a skin band) while still
   * letting them switch groups smoothly without an explicit clear.
   * 勾选同一 group 内的 region；点了别的 group 的 region 时清空旧选择，
   * 避免把不相关的渐变误合并。
   */
  toggleGradientRegionSelection: (
    groupIndex: number,
    regionIndex: number,
  ) => void;
  /** Clear all multi-region checkboxes. 清空多区域勾选。 */
  clearGradientRegionSelection: () => void;
  /**
   * Flatten the currently-checked regions by computing one pixel-count-
   * weighted representative colour across their union and repainting all
   * of them to that colour in a single ``/region-replace-batch`` call.
   * Noop when fewer than 2 regions are selected.
   * 对勾选的 region 求像素加权代表色，一次 batch 调用统一刷成该色。
   */
  flattenSelectedGradientRegions: () => Promise<void>;
  /**
   * Re-quantise gradient regions through the material-archive solver with
   * a fresh per-region palette of ``localQuantizeColors`` colours (range
   * 12-256). Unlike flatten which collapses everything to one
   * representative hex, this keeps each region's low-frequency gradient
   * by giving it a dedicated colour budget and re-matching those colours
   * to material recipes.
   *
   * Two call modes:
   *   - **Implicit** (``targets`` omitted): operates on
   *     ``selectedGradientRegions`` (the checkbox-driven list) and clears
   *     it on success so the panel resets to "nothing checked".
   *   - **Explicit** (``targets`` provided): operates on the caller-
   *     supplied list. Leaves ``selectedGradientRegions`` untouched so a
   *     per-region "re-quantize" button can run without nuking an
   *     unrelated batch selection the user was assembling.
   *
   * 支持两种调用形式：缺省 targets 走当前勾选列表并清空；显式 targets
   * 则仅量化调用方传入的 region 并保留 ``selectedGradientRegions``，便于
   * "某一个 region 单独二次量化"的按钮不破坏用户正在构造的批量选择。
   */
  requantizeSelectedGradientRegions: (
    localQuantizeColors: number,
    targets?: ReadonlyArray<{ groupIndex: number; regionIndex: number }>,
  ) => Promise<void>;
  /**
   * Repaint every currently-checked region with ``targetHex`` via a single
   * ``/region-replace-batch`` call. Used by the LUT picker flow when the
   * user has a multi-region selection and picks a target colour.
   * 用户从 LUT 选定 ``targetHex`` 后，把所有勾选的 region 一次 batch 刷成该色。
   */
  applyMultiRegionPixelReplace: (targetHex: string) => Promise<void>;
  setSourceVersion: (version: SourceVersion) => void;
  setSelectedMaterialDirNames: (names: string[]) => void;
  setMaterialLayerCount: (count: number) => void;
  setMaterialDynamicLayerCountEnabled: (enabled: boolean) => void;
  setMaterialMinLayerCount: (count: number) => void;
  setMaterialMaxLayerCount: (count: number) => void;
  setMaterialLayerHeightMm: (height: number) => void;
  setMaterialBackingMaterialDirName: (name: string | null) => void;
  setNativeBrandKey: (brandKey: string) => void;
  setNativeSupportedMode: (mode: {
    color_layers: number;
    layer_height_mm: number;
  }) => void;
  setNativeDbNames: (dbNames: string[]) => void;
  invalidatePreviewForAutoRefresh: () => void;
  submitPreview: () => Promise<void>;
  submitGenerate: () => Promise<string | null>;
  openNativeMaterialSelection: () => Promise<void>;
  refreshNativeMaterialSelection: (
    profiles: Record<string, string>,
    buildPlateId: string,
  ) => Promise<void>;
  applyNativeMaterialSelection: (
    profiles: Record<string, string>,
    buildPlateId: string,
    externalSpoolMaterial?: string,
  ) => Promise<void>;
  cancelNativeMaterialSelection: () => void;
  reconcileUnknownContentCommit: () => Promise<void>;

  // 裁剪
  setEnableCrop: (enabled: boolean) => void;
  setCropModalOpen: (open: boolean) => void;
  submitCrop: (
    x: number,
    y: number,
    width: number,
    height: number,
    rotation?: 0 | ImageRotationDegrees,
  ) => Promise<void>;

  // 自动检测颜色
  autoDetectColors: () => Promise<void>;

  // 批量模式
  addBatchFiles: (files: File[]) => void;
  removeBatchFile: (index: number) => void;
  clearBatchFiles: () => void;
  submitBatch: () => Promise<void>;

  // 统一文件选择（auto-batch-multiselect）
  handleFilesSelect: (files: File[]) => void;

  // 颜色替换预览
  submitReplacePreview: () => Promise<void>;
  submitSingleReplace: (origHex: string, newHex: string) => Promise<void>;
  cleanupAfterDownload: () => void;

  // 完整流水线（preview → generate）
  submitFullPipeline: () => Promise<string | null>;

  // 自由色
  toggleFreeColor: (hex: string) => void;
  clearFreeColors: () => void;

  // UI 状态
  setError: (error: string | null) => void;
  clearError: () => void;

  // 分层预览
  fetchLayerImages: (previewSourceKey?: string | null) => Promise<void>;
  resetLayerImages: () => void;
  setLayerImagesOpen: (open: boolean) => void;

  // 配方导入
  /** Capture source parameters and a confirmed portable editor checkpoint. */
  prepareRecipeExport: () => Promise<{ state: ConverterState; editorFile: File | null }>;
  importRecipeState: (
    partial: Partial<ConverterState>,
    imageFile: File,
    heightmapFile?: File | null,
  ) => void;
}
