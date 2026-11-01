/**
 * Beginner tutorial step definitions.
 * 新手引导步骤定义。
 *
 * Each step points at a UI element through its `data-tutorial` attribute and
 * names the page/panel that must be open before the element can be shown.
 * The tour only explains; it never uploads, previews, or generates anything.
 * 每一步通过 `data-tutorial` 属性指向界面元素，并声明显示前需要打开的页面/面板。
 * 引导只做讲解，不会替用户上传、预览或生成。
 */
import type { ConverterSubTabId, TabId, WidgetId } from "../types/widget";

export type TutorialStepId =
  | "device-settings"
  | "color-source"
  | "materials-open"
  | "picker-palette"
  | "picker-cards"
  | "picker-favorites"
  | "picker-done"
  | "materials-summary"
  | "materials-backing"
  | "materials-missing"
  | "layer-height"
  | "layer-count"
  | "coating"
  | "image-upload"
  | "output-size"
  | "preview"
  | "view-3d"
  | "print-output"
  | "help";

/** UI state a step needs before its anchor can be found. 步骤显示前需要的界面状态。 */
export interface TutorialStepPrepare {
  tab?: TabId;
  converterSubTab?: ConverterSubTabId;
  widget?: WidgetId;
  /**
   * Keep the material picker dialog open (Material Archive mode only). When
   * the tour leaves these steps the picker is closed with Done, so whatever
   * the user selected is kept; the tour itself never selects anything.
   * 保持耗材选择框打开（仅耗材档案模式）。离开这些步骤时按「完成」关闭，
   * 保留用户自己的勾选；引导本身不会替用户勾选。
   */
  materialPicker?: boolean;
}

/** One "gesture → effect" row, e.g. left-drag → rotate. 一行「操作 → 效果」说明。 */
export interface TutorialControlHint {
  gestureKey: string;
  effectKey: string;
}

/** One color in a recommended palette. 推荐配色中的一个颜色。 */
export interface TutorialSwatch {
  /** CSS color; null draws a clear (transparent) swatch. CSS 颜色；null 表示透明耗材。 */
  color: string | null;
  labelKey: string;
}

/** A recommended material palette shown as swatches. 以色块展示的推荐配色。 */
export interface TutorialPalette {
  titleKey: string;
  noteKey?: string;
  swatches: readonly TutorialSwatch[];
}

/** Built-in illustrations a step can show. 步骤可显示的内置示意图。 */
export type TutorialIllustration = "print-size";

/**
 * Move the tour on when the user does the step's action, so it follows them.
 * 用户完成本步操作后自动前进，引导跟着用户走。
 */
export type TutorialAdvance =
  | { on: "material-picker-opened" }
  | { on: "material-picker-closed"; to: TutorialStepId };

export interface TutorialStep {
  id: TutorialStepId;
  /**
   * `data-tutorial` value to spotlight, or candidates tried in order (the
   * first visible one wins); null shows a centered card.
   * 高亮目标，或按顺序尝试的候选（取第一个可见的）；null 时卡片居中。
   */
  anchor: string | readonly string[] | null;
  titleKey: string;
  bodyKey: string;
  /** Short principle chain rendered as numbered chips. 原理流程芯片。 */
  flowKeys?: readonly string[];
  /** "What you need" line. 「需要准备」说明。 */
  needKey?: string;
  /** "Best for" line. 「适合」说明。 */
  fitKey?: string;
  /** Gesture list rendered as a small table. 操作说明列表。 */
  controlHints?: readonly TutorialControlHint[];
  /**
   * Let the user try the spotlighted area (clicks/drags/scroll pass through
   * the cut-out); everything outside stays blocked.
   * 允许用户在高亮区域内直接试用（点击、拖动、滚轮可穿透），区域外仍屏蔽。
   */
  interactive?: boolean;
  /**
   * Place the card inside the spotlight near its bottom edge, for targets
   * too large to leave room beside them.
   * 卡片放在高亮区域内部靠下，适用于太大、旁边放不下卡片的目标。
   */
  cardInside?: boolean;
  /** Recommended palettes rendered as swatch rows. 以色块行展示的推荐配色。 */
  palettes?: readonly TutorialPalette[];
  illustration?: TutorialIllustration;
  advance?: TutorialAdvance;
  prepare?: TutorialStepPrepare;
}

const BASIC_SETTINGS: TutorialStepPrepare = {
  tab: "converter",
  converterSubTab: "core",
  widget: "basic-settings",
};

const MATERIAL_PICKER: TutorialStepPrepare = {
  ...BASIC_SETTINGS,
  materialPicker: true,
};

// Material Archive controls only exist in that mode; in Classic LUT mode the
// steps fall back to the color block (and the picker cannot open).
// 这些控件只在耗材档案模式下存在；经典 LUT 模式下退回高亮颜色设置区（选择框也不会打开）。
const MATERIAL_FALLBACK = ["material-picker", "color-source"] as const;

const COATING_SETTINGS: TutorialStepPrepare = {
  tab: "converter",
  converterSubTab: "advanced",
  widget: "coating-settings",
};

const swatch = (color: string | null, labelKey: string): TutorialSwatch => ({ color, labelKey });
const WHITE = swatch("var(--palette-white)", "tutorial_color_white");
const YELLOW = swatch("var(--palette-yellow)", "tutorial_color_yellow");
const RED = swatch("var(--palette-crimson)", "tutorial_color_red");
const BLUE = swatch("var(--palette-blue)", "tutorial_color_blue");
const BLACK = swatch("var(--palette-black)", "tutorial_color_black");
const MAGENTA = swatch("var(--palette-magenta)", "tutorial_color_magenta");
const CYAN = swatch("var(--palette-cyan)", "tutorial_color_cyan");
const GREEN = swatch("var(--palette-green)", "tutorial_color_green");
const CLEAR = swatch(null, "tutorial_color_clear");

export const TUTORIAL_PALETTES: readonly TutorialPalette[] = [
  {
    titleKey: "tutorial_palette_eight_title",
    swatches: [WHITE, YELLOW, RED, BLUE, BLACK, MAGENTA, CYAN, GREEN],
  },
  {
    titleKey: "tutorial_palette_clear_title",
    noteKey: "tutorial_palette_clear_note",
    swatches: [WHITE, YELLOW, RED, BLUE, BLACK, MAGENTA, CYAN, CLEAR],
  },
  {
    titleKey: "tutorial_palette_four_title",
    noteKey: "tutorial_palette_four_note",
    swatches: [WHITE, YELLOW, RED, BLUE],
  },
];

/** Picker steps: closing the picker (Done or ✕) jumps to the summary. 关闭选择框后跳到已选显示。 */
const AFTER_PICKER: TutorialAdvance = { on: "material-picker-closed", to: "materials-summary" };

const ACTION_BAR: TutorialStepPrepare = {
  tab: "converter",
  converterSubTab: "core",
  widget: "action-bar",
};

export const TUTORIAL_STEPS: readonly TutorialStep[] = [
  {
    id: "device-settings",
    anchor: "device-settings",
    titleKey: "tutorial_step_device_title",
    bodyKey: "tutorial_step_device_body",
    interactive: true,
    prepare: { tab: "settings" },
  },
  {
    id: "color-source",
    anchor: ["color-source-mode", "color-source"],
    titleKey: "tutorial_step_source_title",
    bodyKey: "tutorial_step_source_body",
    interactive: true,
    prepare: BASIC_SETTINGS,
  },
  {
    id: "materials-open",
    anchor: MATERIAL_FALLBACK,
    titleKey: "tutorial_step_materials_title",
    bodyKey: "tutorial_step_materials_body",
    interactive: true,
    advance: { on: "material-picker-opened" },
    prepare: BASIC_SETTINGS,
  },
  {
    id: "picker-palette",
    anchor: ["material-picker-search", ...MATERIAL_FALLBACK],
    titleKey: "tutorial_step_picker_palette_title",
    bodyKey: "tutorial_step_picker_palette_body",
    palettes: TUTORIAL_PALETTES,
    interactive: true,
    advance: AFTER_PICKER,
    prepare: MATERIAL_PICKER,
  },
  {
    id: "picker-cards",
    anchor: ["material-picker-cards", ...MATERIAL_FALLBACK],
    titleKey: "tutorial_step_picker_cards_title",
    bodyKey: "tutorial_step_picker_cards_body",
    interactive: true,
    advance: AFTER_PICKER,
    prepare: MATERIAL_PICKER,
  },
  {
    id: "picker-favorites",
    anchor: ["material-picker-tabs", ...MATERIAL_FALLBACK],
    titleKey: "tutorial_step_picker_favorites_title",
    bodyKey: "tutorial_step_picker_favorites_body",
    interactive: true,
    advance: AFTER_PICKER,
    prepare: MATERIAL_PICKER,
  },
  {
    id: "picker-done",
    anchor: ["material-picker-footer", ...MATERIAL_FALLBACK],
    titleKey: "tutorial_step_picker_done_title",
    bodyKey: "tutorial_step_picker_done_body",
    interactive: true,
    advance: AFTER_PICKER,
    prepare: MATERIAL_PICKER,
  },
  {
    id: "materials-summary",
    anchor: MATERIAL_FALLBACK,
    titleKey: "tutorial_step_materials_summary_title",
    bodyKey: "tutorial_step_materials_summary_body",
    interactive: true,
    prepare: BASIC_SETTINGS,
  },
  {
    id: "materials-backing",
    anchor: ["material-backing", "color-source"],
    titleKey: "tutorial_step_backing_title",
    bodyKey: "tutorial_step_backing_body",
    interactive: true,
    prepare: BASIC_SETTINGS,
  },
  {
    id: "materials-missing",
    anchor: ["nav-material-management", "primary-tabs"],
    titleKey: "tutorial_step_materials_missing_title",
    bodyKey: "tutorial_step_materials_missing_body",
    prepare: BASIC_SETTINGS,
  },
  {
    id: "layer-height",
    anchor: ["material-layer-height", "color-source"],
    titleKey: "tutorial_step_layer_height_title",
    bodyKey: "tutorial_step_layer_height_body",
    interactive: true,
    prepare: BASIC_SETTINGS,
  },
  {
    id: "layer-count",
    anchor: ["material-layer-count", "color-source"],
    titleKey: "tutorial_step_layer_count_title",
    bodyKey: "tutorial_step_layer_count_body",
    interactive: true,
    prepare: BASIC_SETTINGS,
  },
  {
    id: "coating",
    anchor: "coating-settings",
    titleKey: "tutorial_step_coating_title",
    bodyKey: "tutorial_step_coating_body",
    interactive: true,
    prepare: COATING_SETTINGS,
  },
  {
    id: "image-upload",
    anchor: "image-upload",
    titleKey: "tutorial_step_upload_title",
    bodyKey: "tutorial_step_upload_body",
    interactive: true,
    prepare: BASIC_SETTINGS,
  },
  {
    id: "output-size",
    anchor: "output-size",
    titleKey: "tutorial_step_size_title",
    bodyKey: "tutorial_step_size_body",
    illustration: "print-size",
    interactive: true,
    prepare: BASIC_SETTINGS,
  },
  {
    id: "preview",
    anchor: "preview-button",
    titleKey: "tutorial_step_preview_title",
    bodyKey: "tutorial_step_preview_body",
    prepare: ACTION_BAR,
  },
  {
    id: "view-3d",
    anchor: "viewport-3d",
    titleKey: "tutorial_step_view3d_title",
    bodyKey: "tutorial_step_view3d_body",
    controlHints: [
      { gestureKey: "tutorial_control_left_drag", effectKey: "tutorial_control_rotate" },
      { gestureKey: "tutorial_control_right_drag", effectKey: "tutorial_control_pan" },
      { gestureKey: "tutorial_control_wheel", effectKey: "tutorial_control_zoom" },
      { gestureKey: "tutorial_control_space_drag", effectKey: "tutorial_control_space_pan" },
    ],
    interactive: true,
    cardInside: true,
    prepare: { tab: "converter", converterSubTab: "core" },
  },
  {
    id: "print-output",
    anchor: "print-output",
    titleKey: "tutorial_step_output_title",
    bodyKey: "tutorial_step_output_body",
    prepare: ACTION_BAR,
  },
  {
    id: "help",
    anchor: "tutorial-launcher",
    titleKey: "tutorial_step_help_title",
    bodyKey: "tutorial_step_help_body",
  },
];

/**
 * Collect every translation key referenced by the tutorial steps.
 * 收集引导步骤引用的全部翻译键。
 */
export function collectTutorialStepKeys(
  steps: readonly TutorialStep[] = TUTORIAL_STEPS,
): string[] {
  return steps.flatMap((step) => [
    step.titleKey,
    step.bodyKey,
    ...(step.flowKeys ?? []),
    ...(step.needKey ? [step.needKey] : []),
    ...(step.fitKey ? [step.fitKey] : []),
    ...(step.controlHints ?? []).flatMap((hint) => [hint.gestureKey, hint.effectKey]),
    ...(step.palettes ?? []).flatMap((palette) => [
      palette.titleKey,
      ...(palette.noteKey ? [palette.noteKey] : []),
      ...palette.swatches.map((item) => item.labelKey),
    ]),
    ...(step.illustration === "print-size"
      ? ["tutorial_size_small", "tutorial_size_large", "tutorial_size_caption"]
      : []),
  ]);
}
