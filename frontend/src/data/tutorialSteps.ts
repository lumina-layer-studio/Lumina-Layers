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
  | "picker-search"
  | "picker-cards"
  | "picker-favorites"
  | "picker-done"
  | "materials-summary"
  | "materials-backing"
  | "materials-missing"
  | "layer-height"
  | "layer-count"
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
   * Keep the material picker dialog open (Material Archive mode only); it is
   * closed again when the tour leaves these steps. Nothing is selected.
   * 保持耗材选择框打开（仅耗材档案模式）；离开这些步骤后自动关闭，不会替用户勾选。
   */
  materialPicker?: boolean;
}

/** One "gesture → effect" row, e.g. left-drag → rotate. 一行「操作 → 效果」说明。 */
export interface TutorialControlHint {
  gestureKey: string;
  effectKey: string;
}

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
    prepare: { tab: "settings" },
  },
  {
    id: "color-source",
    anchor: "color-source",
    titleKey: "tutorial_step_source_title",
    bodyKey: "tutorial_step_source_body",
    prepare: BASIC_SETTINGS,
  },
  {
    id: "materials-open",
    anchor: MATERIAL_FALLBACK,
    titleKey: "tutorial_step_materials_title",
    bodyKey: "tutorial_step_materials_body",
    flowKeys: [
      "tutorial_flow_materials_find",
      "tutorial_flow_materials_favorite",
      "tutorial_flow_materials_done",
    ],
    prepare: BASIC_SETTINGS,
  },
  {
    id: "picker-search",
    anchor: ["material-picker-search", ...MATERIAL_FALLBACK],
    titleKey: "tutorial_step_picker_search_title",
    bodyKey: "tutorial_step_picker_search_body",
    prepare: MATERIAL_PICKER,
  },
  {
    id: "picker-cards",
    anchor: ["material-picker-cards", ...MATERIAL_FALLBACK],
    titleKey: "tutorial_step_picker_cards_title",
    bodyKey: "tutorial_step_picker_cards_body",
    prepare: MATERIAL_PICKER,
  },
  {
    id: "picker-favorites",
    anchor: ["material-picker-tabs", ...MATERIAL_FALLBACK],
    titleKey: "tutorial_step_picker_favorites_title",
    bodyKey: "tutorial_step_picker_favorites_body",
    prepare: MATERIAL_PICKER,
  },
  {
    id: "picker-done",
    anchor: ["material-picker-footer", ...MATERIAL_FALLBACK],
    titleKey: "tutorial_step_picker_done_title",
    bodyKey: "tutorial_step_picker_done_body",
    prepare: MATERIAL_PICKER,
  },
  {
    id: "materials-summary",
    anchor: MATERIAL_FALLBACK,
    titleKey: "tutorial_step_materials_summary_title",
    bodyKey: "tutorial_step_materials_summary_body",
    prepare: BASIC_SETTINGS,
  },
  {
    id: "materials-backing",
    anchor: ["material-backing", "color-source"],
    titleKey: "tutorial_step_backing_title",
    bodyKey: "tutorial_step_backing_body",
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
    prepare: BASIC_SETTINGS,
  },
  {
    id: "layer-count",
    anchor: ["material-layer-count", "color-source"],
    titleKey: "tutorial_step_layer_count_title",
    bodyKey: "tutorial_step_layer_count_body",
    prepare: BASIC_SETTINGS,
  },
  {
    id: "image-upload",
    anchor: "image-upload",
    titleKey: "tutorial_step_upload_title",
    bodyKey: "tutorial_step_upload_body",
    prepare: BASIC_SETTINGS,
  },
  {
    id: "output-size",
    anchor: "output-size",
    titleKey: "tutorial_step_size_title",
    bodyKey: "tutorial_step_size_body",
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
  ]);
}
