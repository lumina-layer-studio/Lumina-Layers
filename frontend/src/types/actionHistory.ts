/**
 * Shared types for the action-history store used by the bug report pipeline.
 * Bug 反馈复现包所用的操作历史数据类型。
 *
 * These types intentionally live outside `stores/actionHistoryStore.ts` so
 * downstream consumers (bugReportContext builders, tests, UI summaries)
 * can import them without creating a circular dependency back to the store.
 * 把类型抽离独立文件，避免反馈上下文组装、测试、摘要组件再引用 store 时出现循环依赖。
 */

/**
 * Metadata-only record for a `File` uploaded by the user.
 * 用户上传文件的元数据（不含文件二进制）。
 *
 * The bug report pipeline never serializes `File`/`Blob` instances or data
 * URLs; instead it records `name`, `size`, and MIME `type` so developers can
 * tell which file was selected without exfiltrating the content.
 * 反馈上报永远不直接序列化 File/Blob 或 data URL，只保留文件名、字节大小和 MIME 类型。
 */
export interface FileMetadata {
  name: string;
  size: number;
  type: string;
}

/**
 * Scalar-only fridge-magnet item written into `advanced_params.fridge_magnet`.
 * 冰箱贴参数中保留的纯标量项（不含网格或多边形数据）。
 *
 * Only the numeric / string fields needed to rebuild a placement are
 * captured. Mesh geometry, preview thumbnails, and Three.js objects are
 * intentionally excluded to keep the snapshot small and JSON-safe.
 * 仅保留重建摆放所需的数值与字符串字段；网格、缩略图、Three.js 对象均不记录。
 */
export interface FridgeMagnetScalarItem {
  id: string;
  shape: "round" | "rect";
  preset_key: string;
  diameter_mm: number | null;
  width_mm: number | null;
  height_mm: number | null;
  thickness_mm: number;
  center_x_mm: number;
  center_y_mm: number;
}

/**
 * Scalar-only color-replacement item written into
 * `advanced_params.color_replacement`.
 * 颜色替换参数中保留的标量项。
 *
 * Stores the quantized source hex, the matched palette hex, and the user's
 * chosen replacement hex — enough to reproduce the substitution without
 * shipping the full region mask or preview data.
 * 只保留量化后的源颜色、匹配到的调色板颜色和用户选择的替换颜色，不含掩码/预览数据。
 */
export interface ColorReplacementScalarItem {
  quantized_hex: string;
  matched_hex: string;
  replacement_hex: string;
}

/**
 * Scalar-only virtual material attached to a custom recipe override.
 * 自定义配方覆盖中携带的虚拟耗材定义。
 */
export interface AdvancedParamsVirtualMaterial {
  name: string;
  hex: string;
}

/**
 * Region-level custom recipe override captured for reproducibility.
 * 反馈复现用的区域级自定义配方覆盖。
 */
export interface AdvancedParamsRecipeOverride {
  region_id: string;
  recipe: number[];
  layer_order: string;
  virtual_materials?: AdvancedParamsVirtualMaterial[];
}

/**
 * Target geometry inputs used by every converter generation.
 * 所有转换生成流程都会用到的目标几何参数。
 *
 * These fields are always populated when `activeTab === "converter"` because
 * the converter store initializes them with numeric defaults.
 * 只要处于 converter Tab，这组字段一定有数值（store 会提供默认值）。
 */
export interface AdvancedParamsDimensions {
  target_width_mm: number;
  target_height_mm: number;
  spacer_thick: number;
  base_spacer_thick: number;
  backing_infill_density_percent: number;
}

/**
 * Core generation / quantization tuning knobs.
 * 核心生成与量化调参字段。
 *
 * Captures structure/modeling mode plus 14 additional knobs that affect the
 * final 3MF output (color layer count, quantization, hue/chroma gating, LUT
 * constraints, dynamic range, backing separation).
 * 包含结构与建模模式，以及会影响最终 3MF 输出的开关与阈值。
 */
export interface AdvancedParamsGeneration {
  structure_mode: string;
  modeling_mode: string;
  color_layers: number | null;
  layer_height_mm: number | null;
  model_enable: boolean;
  model_only: boolean;
  model_threshold: number | null;
  model_margin: number | null;
  quantize_colors: number;
  quantize_colors_unlocked: boolean;
  high_precision_3d_preview: boolean;
  enable_cleanup: boolean;
  svg_pixels_per_mm: number;
  svg_hole_compensation_enabled: boolean;
  svg_hole_max_area_mm2: number;
  svg_hole_max_width_mm: number;
  hue_enable: boolean;
  chroma_gate: number;
  use_lut_constrained: boolean;
  auto_dynamic_range: boolean;
  separate_backing: boolean;
  backing_output?: import("../api/types").BackingOutput;
  material_dynamic_layer_count_enabled: boolean;
  material_min_layer_count: number | null;
  material_max_layer_count: number | null;
  material_backing_material_dir_name: string | null;
  material_delta_e00_tolerance: number | null;
  enable_wipe_tower_auto_placement?: boolean;
  wipe_tower_warning_codes?: string[];
  native_filament_profiles?: Record<string, string>;
  external_spool_material?: string;
  native_filament_profile_scope?: {
    slicer: string;
    printer_id: string;
    device_profile_id: string;
    nozzle_size: string;
  } | null;
}

/**
 * Relief / heightmap settings (`enable_relief` toggle + per-color heights).
 * 浮雕 / 高度图设置（enable_relief 开关及各颜色高度）。
 *
 * When `enable_relief` is `false`, every detail field except
 * `hasHeightmapThumbnail` is forced to `null`. Every color height is preserved.
 * `enable_relief` 为 false 时，除 `hasHeightmapThumbnail` 外所有细节字段置 null；
 * color_height_map 完整保留，不再截断。
 */
export interface AdvancedParamsRelief {
  enable_relief: boolean;
  color_height_map: Record<string, number> | null;
  color_height_map_truncated?: boolean;
  heightmap_max_height: number | null;
  autoHeightMode: string | null;
  heightmapFile: FileMetadata | null;
  hasHeightmapThumbnail: boolean;
}

/**
 * Outline / border settings.
 * 描边设置。
 *
 * When `enable_outline` is `false`, `outline_width` is `null`.
 * enable_outline 为 false 时，outline_width 为 null。
 */
export interface AdvancedParamsOutline {
  enable_outline: boolean;
  outline_width: number | null;
}

/**
 * Cloisonné (wire-frame) settings.
 * 景泰蓝（线框）设置。
 *
 * When `enable_cloisonne` is `false`, both `wire_width_mm` and
 * `wire_height_mm` are `null`.
 * enable_cloisonne 为 false 时，wire_width_mm 与 wire_height_mm 均为 null。
 */
export interface AdvancedParamsCloisonne {
  enable_cloisonne: boolean;
  wire_width_mm: number | null;
  wire_height_mm: number | null;
}

/**
 * Coating / surface-layer settings.
 * 涂层设置。
 *
 * When `enable_coating` is `false`, `coating_height_mm` is `null`.
 * enable_coating 为 false 时，coating_height_mm 为 null。
 */
export interface AdvancedParamsCoating {
  enable_coating: boolean;
  coating_height_mm: number | null;
}

/**
 * Hanging loop / keyring settings.
 * 挂环 / 钥匙圈设置。
 *
 * When `add_loop` is `false`, every detail field (width, length, hole,
 * angle, offset x/y, position preset) is forced to `null`.
 * add_loop 为 false 时，所有细节字段（宽度、长度、孔径、角度、偏移、预设位置）均为 null。
 */
export interface AdvancedParamsLoop {
  add_loop: boolean;
  loop_width: number | null;
  loop_length: number | null;
  loop_hole: number | null;
  loop_angle: number | null;
  loop_offset_x: number | null;
  loop_offset_y: number | null;
  loop_position_preset: string | null;
}

/**
 * Fridge-magnet cavity settings.
 * 冰箱贴（磁铁嵌入）设置。
 *
 * When `enable_fridge_magnet` is `false`, both `fridge_magnets` and
 * `selectedFridgeMagnetId` are `null`. Every magnet is preserved.
 * enable_fridge_magnet 为 false 时，fridge_magnets 与 selectedFridgeMagnetId 均为 null；
 * fridge_magnets 完整保留，不再截断。
 */
export interface AdvancedParamsFridgeMagnet {
  enable_fridge_magnet: boolean;
  selectedFridgeMagnetId: string | null;
  fridge_magnets: FridgeMagnetScalarItem[] | null;
  fridge_magnets_truncated?: boolean;
}

/**
 * Puzzle (jigsaw) layout and style settings.
 * 拼图布局与样式设置。
 *
 * When `puzzleEnabled` is `false`, every other field is `null`.
 * puzzleEnabled 为 false 时，除 puzzleEnabled 之外的字段均为 null。
 */
export interface AdvancedParamsPuzzle {
  puzzleEnabled: boolean;
  puzzleStyle: string | null;
  puzzleSizingMode: string | null;
  pieceWidthMm: number | null;
  pieceHeightMm: number | null;
  puzzleRows: number | null;
  puzzleCols: number | null;
  targetPieceCount: number | null;
  connectorStyle: string | null;
  labelsEnabled: boolean | null;
  engraveBackLabels: boolean | null;
  irregularityStrength: number | null;
  minNeckWidthMm: number | null;
}

/**
 * Large-format tiling settings.
 * 大幅面分块设置。
 *
 * When `largeFormatEnabled` is `false`, both `tileWidthMm` and
 * `tileHeightMm` are `null`.
 * largeFormatEnabled 为 false 时，tileWidthMm 与 tileHeightMm 均为 null。
 */
export interface AdvancedParamsLargeFormat {
  largeFormatEnabled: boolean;
  tileWidthMm: number | null;
  tileHeightMm: number | null;
}

/**
 * Bounded model-surface diagnostics used by bug-report reproduction.
 * Bug 反馈复现使用的有界模型覆面诊断参数。
 *
 * Uploaded model bytes and full face-index/footprint geometry arrays are
 * intentionally excluded. Only file metadata, scalar counts, dimensions,
 * and placement transforms are captured.
 * 不包含上传模型二进制、完整面索引或轮廓坐标，仅记录文件元信息、数量、
 * 尺寸和摆放变换标量。
 */
export interface AdvancedParamsModelSurface {
  enabled: boolean;
  model_file: FileMetadata | null;
  model_file_id: string | null;
  selection_id: string | null;
  selected_face_count: number | null;
  footprint: {
    width_mm: number | null;
    height_mm: number | null;
    hole_count: number | null;
  } | null;
  placement: {
    mode: string;
    offset_x_mm: number;
    offset_y_mm: number;
    scale: number;
    rotation_deg: number;
    inset_mm: number;
  } | null;
  model_rotation: {
    x_deg: number;
    y_deg: number;
    z_deg: number;
  } | null;
}

/**
 * Global color mappings and the scalar count of session-scoped spatial edits
 * captured for the generation. Spatial masks and coordinates are never stored.
 *
 * 本次生成采集到的全局颜色映射，以及会话级空间编辑次数标量；不保存掩码或坐标。
 *
 * Every replacement, free color, and recipe override is preserved. An empty list is normalized to
 * `null` so consumers can check one condition for "no replacements".
 * 完整保留颜色替换、自由颜色和配方覆写；
 * 空列表统一归一化为 null，便于下游用同一条件判断"无替换"。
 */
export interface AdvancedParamsColorReplacement {
  /** Global whole-image mappings only. / 仅包含全图颜色映射。 */
  replacement_regions: ColorReplacementScalarItem[] | null;
  replacement_regions_truncated?: boolean;
  /** Non-negative count of session-scoped spatial edits. / 会话级空间编辑的非负次数。 */
  spatial_edit_count: number;
  free_color_set: string[] | null;
  free_color_set_truncated?: boolean;
  recipe_overrides: AdvancedParamsRecipeOverride[] | null;
  recipe_overrides_truncated?: boolean;
}

/**
 * Full grouped advanced-params snapshot attached to bug reports and action
 * history snapshots when `activeTab === "converter"`.
 * 当 Tab 为 converter 时，Bug 反馈与操作历史快照携带的完整高级参数分组对象。
 *
 * Contains 12 complete feature groups. Optional truncation fields remain
 * readable for older saved reports; the builder no longer emits them.
 * 包含 12 个完整功能分组；保留旧工单裁剪字段的读取兼容，新快照不再生成。
 */
export interface AdvancedParamsFull {
  dimensions: AdvancedParamsDimensions;
  generation: AdvancedParamsGeneration;
  relief: AdvancedParamsRelief;
  outline: AdvancedParamsOutline;
  cloisonne: AdvancedParamsCloisonne;
  coating: AdvancedParamsCoating;
  loop: AdvancedParamsLoop;
  fridge_magnet: AdvancedParamsFridgeMagnet;
  puzzle: AdvancedParamsPuzzle;
  large_format: AdvancedParamsLargeFormat;
  model_surface: AdvancedParamsModelSurface;
  color_replacement: AdvancedParamsColorReplacement;
  /** Set to `true` when tiered trimming was applied. / 执行过分层裁剪时置 true。 */
  _size_trimmed?: boolean;
  /** Indices (1-based) of the trimming tiers that ran. / 实际执行的裁剪层级（从 1 开始）。 */
  _dropped_tiers?: number[];
}

/**
 * Historical fallback shape retained for older saved reports.
 * 兼容旧工单中因字节上限而裁剪的历史结构。
 *
 * Consumers should treat this shape as "advanced params were present but
 * too large to serialize in full"; `_original_byte_length` records the
 * pre-trim UTF-8 byte count so developers can see how far over the limit
 * the snapshot was.
 * 消费方应将其视为"高级参数存在但序列化后超限"；_original_byte_length 记录
 * 的是裁剪前的 UTF-8 字节数，便于判断超出多少。
 */
export interface AdvancedParamsSizeTrimmed {
  _size_trimmed: true;
  _original_byte_length: number;
}

/**
 * Grouped advanced-generation parameters union used by both the context
 * payload and each action-history snapshot. `null` indicates the converter
 * tab was not active at capture time.
 * Bug 反馈上下文与操作历史快照共用的高级参数联合类型；null 表示采集时不在 converter Tab。
 */
export type AdvancedParams = AdvancedParamsFull | AdvancedParamsSizeTrimmed;

/**
 * Snapshot of the fields that influence workflow reproduction at a point in
 * time. All fields are captured by-value at push-action time.
 * 工作流快照：捕获某一时刻所有可能影响复现结果的字段。
 */
export interface WorkflowSnapshot {
  color_mode: string | null;
  lut_name: string | null;
  source_version: "legacy" | "native" | "material" | null;
  selected_native_db_names: readonly string[];
  selected_material_dir_names: readonly string[];
  material_layer_count: number | null;
  material_layer_height_mm: number | null;
  material_backing_material_dir_name: string | null;
  active_tab: string;
  /**
   * Grouped advanced generation parameters, or `null` when the converter
   * tab is not active (or when the shared builder is not yet installed).
   * 高级生成参数分组对象；当非 converter Tab 或构建器尚未安装时为 null。
   */
  advanced_params: AdvancedParams | null;
}

/**
 * Discriminator for every kind of user-visible action the store tracks.
 * 操作历史记录的类型枚举。
 */
export type ActionType =
  | "upload_image"
  | "preview"
  | "generate"
  | "download"
  | "apply_recipe"
  | "region_replace"
  | "switch_tab"
  | "switch_subtab"
  | "color_mode_change"
  | "lut_change"
  | "source_version_change"
  | "material_selection_change"
  | "material_param_commit"
  | "api_error"
  | "advanced_param_change";

/**
 * Extra error details attached only to `api_error` action entries.
 * 仅当 action_type === 'api_error' 时附带的错误信息。
 */
export interface ActionErrorInfo {
  status_code: number;
  path: string;
  request_id?: string;
  error_message: string;
}

/**
 * A single row in the action history ring.
 * 操作历史中的一条记录。
 */
export interface ActionEntry {
  /** Epoch milliseconds at push time. / 入栈时的毫秒时间戳。 */
  timestamp: number;
  action_type: ActionType;
  /** Optional map of field-level deltas captured by the caller. / 可选的字段级变化说明。 */
  changed_fields?: Record<string, { from: unknown; to: unknown }>;
  /** Snapshot of the workflow at push time. / 入栈时的工作流快照。 */
  snapshot: WorkflowSnapshot;
  /** Only present on api_error entries. / 仅 api_error 记录携带。 */
  error?: ActionErrorInfo;
}

/**
 * Work surface the session id belongs to.
 * Session id 所属的工作流。
 */
export type Workstream = "converter" | "single_stage";

/**
 * Entry in the 5-slot session ring. Stores workstream plus first/last seen
 * timestamps so developers can grep backend logs by session id after the
 * fact even if the source session has been cleaned up.
 * 会话环中的一条记录，保留首次/最后一次观察到的时间戳，便于后端日志追溯。
 */
export interface SessionRingEntry {
  workstream: Workstream;
  session_id: string;
  first_seen_at: number;
  last_seen_at: number;
}

/**
 * Exported payload shape consumed by bug report context builders.
 * 反馈上下文组装时导出的载荷结构。
 */
export interface ActionHistoryExport {
  history: ActionEntry[];
  session_history: SessionRingEntry[];
}
