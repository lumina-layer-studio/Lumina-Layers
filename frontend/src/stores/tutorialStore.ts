/**
 * Beginner tutorial orchestration store.
 * 新手引导编排 store。
 *
 * Owns the welcome/tour phase, the current step, first-run persistence, and
 * usage analytics. Components only render state and call these actions.
 * 负责欢迎窗/分步引导阶段、当前步骤、首次启动记录和使用统计；
 * 组件只负责渲染状态并调用这些 action。
 */
import { create } from "zustand";
import { trackLuminaEvent } from "../analytics/umami";
import { TUTORIAL_STEPS } from "../data/tutorialSteps";
import type { TutorialStep } from "../data/tutorialSteps";
import type { ConverterSubTabId, TabId, WidgetId } from "../types/widget";
import {
  hasTutorialBeenOffered,
  readTutorialWorkspaceSnapshot,
  writeTutorialProgress,
  writeTutorialWorkspaceSnapshot,
} from "../utils/tutorialProgress";
import {
  CONVERTER_SUB_TAB_WIDGET_MAP,
  DEFAULT_LAYOUT,
  TAB_WIDGET_MAP,
  useWidgetStore,
} from "./widgetStore";

export type TutorialPhase = "idle" | "welcome" | "touring";
/** How the tutorial was opened. 引导的打开方式。 */
export type TutorialTrigger = "auto" | "manual";
/** How the tutorial was skipped. 引导的跳过方式。 */
export type TutorialSkipVia = "welcome" | "skip_button" | "escape";

interface TutorialState {
  phase: TutorialPhase;
  stepIndex: number;
  trigger: TutorialTrigger;
  startedAtMs: number | null;
  /** Open the welcome dialog once per device. 每台设备只自动弹出一次欢迎窗。 */
  offerFirstRun: () => void;
  startTour: (trigger: TutorialTrigger) => void;
  next: () => void;
  back: () => void;
  skip: (via: TutorialSkipVia) => void;
  finish: () => void;
  /**
   * Report that the material picker opened or closed, so a step waiting for
   * that action moves on by itself. 报告耗材选择框打开/关闭，等待该操作的步骤自动前进。
   */
  notifyMaterialPicker: (open: boolean) => void;
  /**
   * Restore the workspace left changed by a tour interrupted by a reload.
   * 恢复因刷新而中断的引导留下的工作区改动。
   */
  recoverInterruptedTour: () => void;
}

const TOTAL_STEPS = TUTORIAL_STEPS.length;

interface OpenedWidget {
  wasHidden: boolean;
  wasCollapsed: boolean;
}

/**
 * Workspace state the tour changed, restored on every exit path.
 * 引导改动过的工作区状态，在所有退出路径上恢复。
 *
 * It is mirrored to browser storage because the page and panel layout it
 * undoes are persisted too; a reload mid-tour must still restore them.
 * 由于它要撤销的页面和面板布局本身是持久化的，快照也同步写入浏览器存储，
 * 引导中途刷新后仍能恢复。
 */
interface WorkspaceSnapshot {
  activeTab: TabId;
  activeConverterSubTab: ConverterSubTabId;
  /** Only panels the tour itself revealed or expanded. 仅记录引导自己展开的面板。 */
  openedWidgets: Partial<Record<WidgetId, OpenedWidget>>;
}

let workspaceSnapshot: WorkspaceSnapshot | null = null;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Validate a stored snapshot against the current tabs and widgets. 按当前页面和面板校验已保存的快照。 */
function parseWorkspaceSnapshot(raw: unknown): WorkspaceSnapshot | null {
  if (!isRecord(raw)) {
    return null;
  }
  const { activeTab, activeConverterSubTab, openedWidgets } = raw;
  if (typeof activeTab !== "string" || !(activeTab in TAB_WIDGET_MAP)) {
    return null;
  }
  if (
    typeof activeConverterSubTab !== "string" ||
    !(activeConverterSubTab in CONVERTER_SUB_TAB_WIDGET_MAP)
  ) {
    return null;
  }
  const opened: Partial<Record<WidgetId, OpenedWidget>> = {};
  if (isRecord(openedWidgets)) {
    for (const [id, value] of Object.entries(openedWidgets)) {
      if (id in DEFAULT_LAYOUT && isRecord(value)) {
        opened[id as WidgetId] = {
          wasHidden: value.wasHidden === true,
          wasCollapsed: value.wasCollapsed === true,
        };
      }
    }
  }
  return {
    activeTab: activeTab as TabId,
    activeConverterSubTab: activeConverterSubTab as ConverterSubTabId,
    openedWidgets: opened,
  };
}

function captureWorkspace(): void {
  const { activeTab, activeConverterSubTab } = useWidgetStore.getState();
  workspaceSnapshot = { activeTab, activeConverterSubTab, openedWidgets: {} };
  writeTutorialWorkspaceSnapshot(workspaceSnapshot);
}

function recordOpenedWidget(id: WidgetId, wasHidden: boolean, wasCollapsed: boolean): void {
  if (!workspaceSnapshot || workspaceSnapshot.openedWidgets[id]) {
    return;
  }
  workspaceSnapshot.openedWidgets[id] = { wasHidden, wasCollapsed };
  writeTutorialWorkspaceSnapshot(workspaceSnapshot);
}

/**
 * Undo the page, sub-tab, and panel changes the tour made, so viewing or
 * skipping it never rewrites the user's persisted workspace.
 * 撤销引导切换的页面、子页面和展开的面板，查看或跳过引导不会改写用户持久化的工作区。
 */
function restoreWorkspace(): void {
  const snapshot = workspaceSnapshot ?? parseWorkspaceSnapshot(readTutorialWorkspaceSnapshot());
  workspaceSnapshot = null;
  writeTutorialWorkspaceSnapshot(null);
  if (!snapshot) {
    return;
  }
  const widgetStore = useWidgetStore.getState();
  for (const [id, opened] of Object.entries(snapshot.openedWidgets) as [WidgetId, OpenedWidget][]) {
    const layout = useWidgetStore.getState().widgets[id];
    if (!layout) {
      continue;
    }
    if (opened.wasCollapsed && !layout.collapsed) {
      widgetStore.toggleCollapse(id);
    }
    if (opened.wasHidden && layout.visible) {
      widgetStore.toggleVisible(id);
    }
  }
  if (useWidgetStore.getState().activeConverterSubTab !== snapshot.activeConverterSubTab) {
    widgetStore.setActiveConverterSubTab(snapshot.activeConverterSubTab);
  }
  if (useWidgetStore.getState().activeTab !== snapshot.activeTab) {
    widgetStore.setActiveTab(snapshot.activeTab);
  }
}

/**
 * Open the page, sub-tab, and panel a step needs so its anchor can render.
 * 打开步骤所需的页面、子页面和面板，使高亮目标能够渲染出来。
 *
 * Args:
 *     step (TutorialStep): Step about to be shown. 即将显示的步骤。
 */
export function applyTutorialStepPrepare(step: TutorialStep): void {
  const prepare = step.prepare;
  if (!prepare) {
    return;
  }
  const widgetStore = useWidgetStore.getState();
  if (prepare.tab && widgetStore.activeTab !== prepare.tab) {
    widgetStore.setActiveTab(prepare.tab);
  }
  if (
    prepare.converterSubTab &&
    widgetStore.activeConverterSubTab !== prepare.converterSubTab
  ) {
    widgetStore.setActiveConverterSubTab(prepare.converterSubTab);
  }
  if (prepare.widget) {
    const layout = useWidgetStore.getState().widgets[prepare.widget];
    if (layout && (!layout.visible || layout.collapsed)) {
      recordOpenedWidget(prepare.widget, !layout.visible, layout.collapsed);
    }
    if (layout && !layout.visible) {
      widgetStore.toggleVisible(prepare.widget);
    }
    if (layout && layout.collapsed) {
      widgetStore.toggleCollapse(prepare.widget);
    }
  }
}

function elapsedSeconds(startedAtMs: number | null): number | null {
  if (startedAtMs === null) {
    return null;
  }
  return Math.max(0, Math.round((Date.now() - startedAtMs) / 1000));
}

function trackStepView(trigger: TutorialTrigger, stepIndex: number): void {
  trackLuminaEvent("lumina_tutorial_step_view", {
    trigger,
    step_id: TUTORIAL_STEPS[stepIndex]?.id ?? null,
    step_index: stepIndex + 1,
    total_steps: TOTAL_STEPS,
  });
}

export const useTutorialStore = create<TutorialState>()((set, get) => {
  const goToStep = (stepIndex: number) => {
    const step = TUTORIAL_STEPS[stepIndex];
    if (!step) {
      return;
    }
    applyTutorialStepPrepare(step);
    set({ stepIndex });
    trackStepView(get().trigger, stepIndex);
  };

  return {
    phase: "idle",
    stepIndex: 0,
    trigger: "auto",
    startedAtMs: null,

    offerFirstRun: () => {
      if (get().phase !== "idle" || hasTutorialBeenOffered()) {
        return;
      }
      // Record the offer before any choice so closing the app mid-dialog
      // still counts as "shown once".
      // 在用户做选择前就记录，确保中途关闭软件也算「已弹出过一次」。
      writeTutorialProgress("offered");
      set({ phase: "welcome", trigger: "auto", stepIndex: 0, startedAtMs: null });
      trackLuminaEvent("lumina_tutorial_offered");
    },

    startTour: (trigger) => {
      if (get().phase === "touring") {
        return;
      }
      captureWorkspace();
      set({ phase: "touring", trigger, startedAtMs: Date.now() });
      trackLuminaEvent("lumina_tutorial_started", { trigger });
      goToStep(0);
    },

    next: () => {
      const { phase, stepIndex, finish } = get();
      if (phase !== "touring") {
        return;
      }
      if (stepIndex >= TOTAL_STEPS - 1) {
        finish();
        return;
      }
      goToStep(stepIndex + 1);
    },

    back: () => {
      const { phase, stepIndex } = get();
      if (phase !== "touring" || stepIndex <= 0) {
        return;
      }
      goToStep(stepIndex - 1);
    },

    skip: (via) => {
      const { phase, stepIndex, trigger, startedAtMs } = get();
      if (phase === "idle") {
        return;
      }
      const onWelcome = phase === "welcome";
      writeTutorialProgress("skipped");
      trackLuminaEvent("lumina_tutorial_skipped", {
        trigger,
        via,
        step_id: onWelcome ? "welcome" : (TUTORIAL_STEPS[stepIndex]?.id ?? null),
        step_index: onWelcome ? 0 : stepIndex + 1,
        total_steps: TOTAL_STEPS,
        elapsed_s: elapsedSeconds(startedAtMs),
      });
      restoreWorkspace();
      set({ phase: "idle", stepIndex: 0, startedAtMs: null });
    },

    finish: () => {
      const { phase, trigger, startedAtMs } = get();
      if (phase !== "touring") {
        return;
      }
      writeTutorialProgress("completed");
      trackLuminaEvent("lumina_tutorial_completed", {
        trigger,
        total_steps: TOTAL_STEPS,
        elapsed_s: elapsedSeconds(startedAtMs),
      });
      restoreWorkspace();
      set({ phase: "idle", stepIndex: 0, startedAtMs: null });
    },

    notifyMaterialPicker: (open) => {
      const { phase, stepIndex } = get();
      if (phase !== "touring") {
        return;
      }
      const advance = TUTORIAL_STEPS[stepIndex]?.advance;
      if (!advance) {
        return;
      }
      if (open && advance.on === "material-picker-opened") {
        get().next();
      } else if (!open && advance.on === "material-picker-closed") {
        const target = TUTORIAL_STEPS.findIndex((step) => step.id === advance.to);
        if (target >= 0) {
          goToStep(target);
        }
      }
    },

    recoverInterruptedTour: () => {
      if (get().phase !== "idle") {
        return;
      }
      restoreWorkspace();
    },
  };
});
