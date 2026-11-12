/**
 * Widget layout store for the floating widget workspace.
 * 浮动 Widget 工作区布局状态管理。
 *
 * Manages widget positions, collapse states, snap edges, and stack ordering.
 * Uses Zustand persist middleware to save layout to localStorage.
 * 管理 Widget 位置、折叠状态、吸附边缘和堆叠排序。
 * 使用 Zustand persist middleware 将布局持久化到 localStorage。
 */

import { create } from "zustand";
import { persist, subscribeWithSelector } from "zustand/middleware";
import { EXPANDED_HEIGHT } from "../utils/widgetUtils";
import type {
  WidgetId,
  WidgetLayoutState,
  WidgetStore,
  WidgetConfig,
  TabId,
  ConverterSubTabId,
} from "../types/widget";

// ===== TAB → Widget 映射 =====

export const TAB_WIDGET_MAP: Record<TabId, WidgetId[]> = {
  converter: [
    "model-surface-settings",
    "basic-settings",
    "advanced-settings",
    "relief-settings",
    "outline-settings",
    "coating-settings",
    "keychain-loop",
    "fridge-magnet-settings",
    "puzzle-settings",
    "action-bar",
  ],
  calibration: [],
  extractor: [],
  "gradient-card-generate": [],
  "gradient-card-extract": [],
  "material-library": [],
  "material-cloud-sync": [],
  "material-recipe": [],
  "material-gamut": [],
  "material-cache": [],
  "lut-library": [],
  "lut-manager": [],
  "lut-cloud-sync": [],
  "lut-details": [],
  "lut-compare": [],
  "five-color": [],
  vectorizer: [],
  workshop: [],
  settings: [],
};

// ===== Converter sub-tab → Widget 映射 =====
// 核心设置：只有基础设置、操作栏、高级设置 3 个面板，专注于 3MF 生成所需的主要参数。
// 颜色调整：dock 中不显示任何 widget；改由 Color2DOverlay 全屏接管。
// 高级功能：仅列出向用户开放的面板；掐丝珐琅保留数据兼容，但不提供 UI 入口。
export const CONVERTER_SUB_TAB_WIDGET_MAP: Record<ConverterSubTabId, readonly WidgetId[]> = {
  core: ["basic-settings", "action-bar", "advanced-settings"],
  color: [],
  advanced: [
    "model-surface-settings",
    "basic-settings",
    "advanced-settings",
    "relief-settings",
    "outline-settings",
    "coating-settings",
    "keychain-loop",
    "fridge-magnet-settings",
    "puzzle-settings",
    "action-bar",
  ],
};

// ===== 默认布局 =====

export const DEFAULT_LAYOUT: Record<WidgetId, WidgetLayoutState> = {
  // --- Converter 页面 ---
  // 左侧：模型贴图（展开，置顶），从基础设置中拆出的独立面板。
  // 与基础设置同为 stackOrder 0，靠 TAB/REGISTRY 的遍历顺序稳定排序取胜出，
  // 因此本条目必须排在 "basic-settings" 之前。
  "model-surface-settings": {
    id: "model-surface-settings",
    position: { x: 0, y: 0 },
    collapsed: false,
    visible: true,
    snapEdge: "left",
    stackOrder: 0,
    expandedHeight: EXPANDED_HEIGHT,
  },
  // 左侧：基础设置（展开）
  "basic-settings": {
    id: "basic-settings",
    position: { x: 0, y: 0 },
    collapsed: false,
    visible: true,
    snapEdge: "left",
    stackOrder: 0,
    expandedHeight: EXPANDED_HEIGHT,
  },
  // 右侧：操作栏（展开）+ 其余 6 个（折叠）
  "action-bar": {
    id: "action-bar",
    position: { x: 0, y: 0 },
    collapsed: false,
    visible: true,
    snapEdge: "right",
    stackOrder: 0,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "keychain-loop": {
    id: "keychain-loop",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: true,
    snapEdge: "right",
    stackOrder: 1,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "fridge-magnet-settings": {
    id: "fridge-magnet-settings",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: true,
    snapEdge: "right",
    stackOrder: 2,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "puzzle-settings": {
    id: "puzzle-settings",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: true,
    snapEdge: "right",
    stackOrder: 3,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "coating-settings": {
    id: "coating-settings",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: true,
    snapEdge: "right",
    stackOrder: 4,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "cloisonne-settings": {
    id: "cloisonne-settings",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: false,
    snapEdge: "right",
    stackOrder: 5,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "outline-settings": {
    id: "outline-settings",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: true,
    snapEdge: "right",
    stackOrder: 6,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "relief-settings": {
    id: "relief-settings",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: true,
    snapEdge: "right",
    stackOrder: 7,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "advanced-settings": {
    id: "advanced-settings",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: true,
    snapEdge: "right",
    stackOrder: 8,
    expandedHeight: EXPANDED_HEIGHT,
  },
  // --- Material/LUT pages: one dockable control widget each ---
  calibration: {
    id: "calibration",
    position: { x: 0, y: 0 },
    collapsed: false,
    visible: true,
    snapEdge: "left",
    stackOrder: 0,
    expandedHeight: EXPANDED_HEIGHT,
  },
  extractor: {
    id: "extractor",
    position: { x: 0, y: 0 },
    collapsed: false,
    visible: true,
    snapEdge: "left",
    stackOrder: 0,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "lut-manager": {
    id: "lut-manager",
    position: { x: 0, y: 0 },
    collapsed: false,
    visible: true,
    snapEdge: "left",
    stackOrder: 0,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "five-color": {
    id: "five-color",
    position: { x: 0, y: 0 },
    collapsed: false,
    visible: true,
    snapEdge: "left",
    stackOrder: 0,
    expandedHeight: EXPANDED_HEIGHT,
  },
};

// ===== Widget 注册表（静态配置，不含 component 字段）=====

export const WIDGET_REGISTRY: Omit<WidgetConfig, "component">[] = [
  // Converter 页面（顺序即左坞渲染顺序：模型贴图在基础设置之上）
  {
    id: "model-surface-settings",
    titleKey: "widget.modelSurfaceSettings",
    icon: "image",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "basic-settings",
    titleKey: "widget.basicSettings",
    icon: "settings",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "advanced-settings",
    titleKey: "widget.advancedSettings",
    icon: "sliders",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "relief-settings",
    titleKey: "widget.reliefSettings",
    icon: "layers",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "outline-settings",
    titleKey: "widget.outlineSettings",
    icon: "pen-tool",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "cloisonne-settings",
    titleKey: "widget.cloisonneSettings",
    icon: "hexagon",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "coating-settings",
    titleKey: "widget.coatingSettings",
    icon: "droplet",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "keychain-loop",
    titleKey: "widget.keychainLoop",
    icon: "link",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "fridge-magnet-settings",
    titleKey: "widget.fridgeMagnetSettings",
    icon: "circle",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "puzzle-settings",
    titleKey: "widget.puzzleSettings",
    icon: "grid",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "action-bar",
    titleKey: "widget.actionBar",
    icon: "play",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "calibration",
    titleKey: "widget.calibration",
    icon: "grid",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "extractor",
    titleKey: "widget.extractor",
    icon: "eyedropper",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "lut-manager",
    titleKey: "widget.lutManager",
    icon: "table",
    defaultWidth: 350,
    minWidth: 300,
  },
  {
    id: "five-color",
    titleKey: "widget.fiveColor",
    icon: "palette",
    defaultWidth: 350,
    minWidth: 300,
  },
];

// ===== Store =====

/**
 * Sanitize a persisted widget payload so it never references removed tabs or
 * widgets. Drops widget layouts whose id is no longer in DEFAULT_LAYOUT and
 * resets an ``activeTab`` that is no longer a valid TabId back to "converter".
 * 清洗持久化载荷，确保不引用已删除的标签/widget：丢弃 DEFAULT_LAYOUT 中已不存在
 * 的 widget 布局，并把失效的 ``activeTab`` 重置为 "converter"。
 */
function _sanitizePersistedState(persistedState: unknown): WidgetStore {
  const state =
    typeof persistedState === "object" && persistedState !== null
      ? (persistedState as { widgets?: Record<string, WidgetLayoutState>; activeTab?: TabId })
      : {};

  const validWidgetIds = new Set(Object.keys(DEFAULT_LAYOUT));
  const sourceWidgets = (state.widgets ?? {}) as Record<string, WidgetLayoutState>;
  const widgets: Record<string, WidgetLayoutState> = {};
  for (const [id, layout] of Object.entries(sourceWidgets)) {
    if (validWidgetIds.has(id)) {
      widgets[id] = layout;
    }
  }
  // Ensure every current widget exists (fill any missing from defaults).
  for (const id of Object.keys(DEFAULT_LAYOUT)) {
    if (!widgets[id]) {
      widgets[id] = { ...DEFAULT_LAYOUT[id as WidgetId] };
    }
  }

  const validTab = (Object.keys(TAB_WIDGET_MAP) as TabId[]).includes(
    state.activeTab as TabId,
  );

  return {
    ...(state as object),
    widgets,
    activeTab: validTab ? (state.activeTab as TabId) : "converter",
  } as WidgetStore;
}

/**
 * Relocate the persisted ``model-surface-settings`` entry so its key precedes
 * every other widget id (notably ``basic-settings``) in the hydrated record.
 *
 * The panel joined DEFAULT_LAYOUT only today under persist v8, so nobody has
 * customized its position yet; the v8→v9 migration re-aligns stored record
 * order with the new default dock order. Record key order is observable:
 * iteration-order-sensitive flows such as ``autoArrange`` stack free-floating
 * widgets in record order, and equal-``stackOrder`` ties fall back to stable
 * iteration order.
 * 将持久化的 ``model-surface-settings`` 条目前移到记录中其他 widget（尤其是
 * ``basic-settings``）之前。该面板今日才随 v8 加入，尚无用户自定义其位置，
 * 因此 v8→v9 迁移把存储键序与新默认坞内顺序对齐。记录键序可被观察到：
 * ``autoArrange`` 等流程按遍历顺序收纳自由浮动 widget，相同 ``stackOrder``
 * 的并列也依赖稳定排序的遍历顺序。
 */
function _promoteModelSurfaceEntry(
  persistedState: unknown,
): Record<string, unknown> {
  const state =
    typeof persistedState === "object" && persistedState !== null
      ? (persistedState as Record<string, unknown>)
      : {};
  const widgets = state.widgets as
    | Record<string, WidgetLayoutState>
    | undefined;
  if (!widgets || !widgets["model-surface-settings"]) {
    return state;
  }
  const {
    "model-surface-settings": modelSurfaceEntry,
    ...restWidgets
  } = widgets;
  return {
    ...state,
    widgets: { "model-surface-settings": modelSurfaceEntry, ...restWidgets },
  };
}

export const useWidgetStore = create<WidgetStore>()(
  subscribeWithSelector(
    persist(
      (set, get) => ({
      widgets: { ...DEFAULT_LAYOUT },
      isDragging: false,
      activeWidgetId: null,
      activeTab: "converter" as TabId,
      activeConverterSubTab: "core" as ConverterSubTabId,
      color2DOverlayOpen: false,

      /**
       * Set the active TAB page.
       * 设置当前激活的 TAB 页面。
       */
      setActiveTab: (tab: TabId) => {
        set({ activeTab: tab });
      },

      /**
       * Set the active Converter sub-tab.
       * Switching to 'color' opens the Color2DOverlay; leaving 'color' closes it.
       * Sub-tab and overlay state stay in lockstep so the overlay behaves like a
       * full-bleed page rather than a modal.
       *
       * 设置 Converter 页面下的二级 sub-tab。
       * 切到「颜色调整」即打开 2D 颜色覆盖层；离开「颜色调整」即关闭，
       * 让覆盖层像普通子页面一样进入/退出，而不是模态弹层。
       */
      setActiveConverterSubTab: (subTab: ConverterSubTabId) => {
        set({
          activeConverterSubTab: subTab,
          color2DOverlayOpen: subTab === "color",
        });
      },

      /**
       * Update widget position.
       * 更新 Widget 位置。
       */
      moveWidget: (id: WidgetId, position: { x: number; y: number }) => {
        set((state) => ({
          widgets: {
            ...state.widgets,
            [id]: { ...state.widgets[id], position },
          },
        }));
      },

      /**
       * Batch update widget positions in a single store commit.
       * 批量更新 Widget 位置，合并为一次 store 提交。
       */
      setWidgetPositions: (
        positions: Partial<Record<WidgetId, { x: number; y: number }>>,
      ) => {
        const widgets = get().widgets;
        let nextWidgets: typeof widgets | undefined;
        for (const [id, position] of Object.entries(positions) as [
          WidgetId,
          { x: number; y: number },
        ][]) {
          const current = widgets[id];
          if (
            !current ||
            (current.position.x === position.x && current.position.y === position.y)
          ) {
            continue;
          }
          nextWidgets ??= { ...widgets };
          nextWidgets[id] = { ...current, position };
        }
        // Even set(state => state) serializes the persisted layout.
        if (nextWidgets) set({ widgets: nextWidgets });
      },

      /**
       * Toggle widget collapsed state.
       * 切换 Widget 折叠状态。
       */
      toggleCollapse: (id: WidgetId) => {
        set((state) => ({
          widgets: {
            ...state.widgets,
            [id]: {
              ...state.widgets[id],
              collapsed: !state.widgets[id].collapsed,
            },
          },
        }));
      },

      /**
       * Toggle widget visibility.
       * 切换 Widget 可见性。
       */
      toggleVisible: (id: WidgetId) => {
        set((state) => ({
          widgets: {
            ...state.widgets,
            [id]: { ...state.widgets[id], visible: !state.widgets[id].visible },
          },
        }));
      },

      /**
       * Snap widget to a screen edge and assign next stack order.
       * 将 Widget 吸附到屏幕边缘并分配下一个堆叠顺序。
       *
       * Only considers widgets belonging to the same TAB when computing maxOrder,
       * preventing cross-tab stackOrder inflation that pushes widgets off-screen.
       * 仅考虑同一 TAB 页的 Widget 计算 maxOrder，防止跨 TAB 堆叠顺序膨胀导致 Widget 超出屏幕。
       */
      snapToEdge: (id: WidgetId, edge: "left" | "right") => {
        set((state) => {
          // Find which tab this widget belongs to
          const ownerTab = (Object.keys(TAB_WIDGET_MAP) as TabId[]).find(
            (tab) => TAB_WIDGET_MAP[tab].includes(id),
          );
          const tabWidgetIds = ownerTab ? TAB_WIDGET_MAP[ownerTab] : [];

          // Only consider widgets from the same tab for maxOrder calculation
          const maxOrder = Object.values(state.widgets)
            .filter(
              (w) =>
                w.snapEdge === edge &&
                w.id !== id &&
                tabWidgetIds.includes(w.id),
            )
            .reduce((max, w) => Math.max(max, w.stackOrder), -1);

          return {
            widgets: {
              ...state.widgets,
              [id]: {
                ...state.widgets[id],
                snapEdge: edge,
                stackOrder: maxOrder + 1,
              },
            },
          };
        });
      },

      /**
       * Detach widget from edge, making it free-floating.
       * 将 Widget 从边缘脱离，恢复为自由浮动。
       */
      detachFromEdge: (id: WidgetId) => {
        set((state) => ({
          widgets: {
            ...state.widgets,
            [id]: { ...state.widgets[id], snapEdge: null, stackOrder: -1 },
          },
        }));
      },

      /**
       * Set dragging state and active widget.
       * 设置拖拽状态和活动 Widget。
       */
      setDragging: (isDragging: boolean, activeId?: WidgetId) => {
        set({ isDragging, activeWidgetId: activeId ?? null });
      },

      /**
       * Update the pre-measured expanded height for a widget.
       * 更新 Widget 预测量的展开高度。
       */
      setExpandedHeight: (id: WidgetId, height: number) => {
        if (get().widgets[id].expandedHeight === height) return;
        set((state) => {
          return {
            widgets: {
              ...state.widgets,
              [id]: { ...state.widgets[id], expandedHeight: height },
            },
          };
        });
      },

      /**
       * Auto-arrange all free-floating visible widgets to the left edge.
       * 将所有自由浮动的可见 Widget 自动收纳到左侧边缘。
       */
      autoArrange: () => {
        set((state) => {
          const updated = { ...state.widgets };
          const floatingVisible = Object.values(updated).filter(
            (w) => w.snapEdge === null && w.visible,
          );

          if (floatingVisible.length === 0) return state;

          const maxOrder = Object.values(updated)
            .filter((w) => w.snapEdge === "left")
            .reduce((max, w) => Math.max(max, w.stackOrder), -1);

          let nextOrder = maxOrder + 1;
          for (const widget of floatingVisible) {
            updated[widget.id] = {
              ...updated[widget.id],
              snapEdge: "left",
              stackOrder: nextOrder++,
            };
          }

          return { widgets: updated };
        });
      },

      /**
       * Reset all widgets to default layout, preserving measured expandedHeight.
       *
       * `expandedHeight` is a ResizeObserver-derived runtime measurement, not a
       * user-facing layout setting. If we reset it to the static default
       * (EXPANDED_HEIGHT = 400) the wrapper instantly clips taller widgets
       * (e.g. BasicSettings ≈ 650px) and the observer never re-fires until
       * the user manually toggles collapse — visible as a one-frame "snap and
       * shrink" right after Reset Layout.
       *
       * 重置 widget 布局，但保留已测得的 expandedHeight。
       * expandedHeight 是 ResizeObserver 在运行时测量得到的派生值，并非
       * 用户可配置的布局项；如果一并重置成静态默认 400，wrapper 会瞬间
       * 把基础设置（~650px）等内容裁短，且 observer 不会再触发，必须
       * 手动收起/展开才能恢复——用户可见的「按下重置就被裁短」即此。
       */
      resetLayout: () => {
        set((state) => {
          const widgets = {} as Record<WidgetId, WidgetLayoutState>;
          (Object.keys(DEFAULT_LAYOUT) as WidgetId[]).forEach((id) => {
            const measured = state.widgets[id]?.expandedHeight;
            widgets[id] = {
              ...DEFAULT_LAYOUT[id],
              expandedHeight:
                typeof measured === "number" && measured > 0
                  ? measured
                  : DEFAULT_LAYOUT[id].expandedHeight,
            };
          });
          return {
            widgets,
            isDragging: false,
            activeWidgetId: null,
          };
        });
      },

      /**
       * Reorder widgets on a given edge based on ordered ID array.
       * 根据有序 ID 数组重新排列指定边缘上的 Widget。
       */
      reorderStack: (edge: "left" | "right", orderedIds: WidgetId[]) => {
        set((state) => {
          const updated = { ...state.widgets };
          orderedIds.forEach((id, index) => {
            if (updated[id] && updated[id].snapEdge === edge) {
              updated[id] = { ...updated[id], stackOrder: index };
            }
          });
          return { widgets: updated };
        });
      },

      /**
       * Atomically snap dragged widget and reorder target edge stack.
       * 原子化执行吸附与重排，避免中间态导致的错误动画。
       */
      snapAndReorder: (
        id: WidgetId,
        edge: "left" | "right",
        orderedIds: WidgetId[],
      ) => {
        set((state) => {
          const updated = { ...state.widgets };

          orderedIds.forEach((wid, index) => {
            if (!updated[wid]) return;
            updated[wid] = {
              ...updated[wid],
              snapEdge: edge,
              stackOrder: index,
            };
          });

          if (updated[id] && !orderedIds.includes(id)) {
            updated[id] = { ...updated[id], snapEdge: edge };
          }

          return { widgets: updated };
        });
      },

      /**
       * Open the 2D color overlay and switch the converter sub-tab to 'color'.
       * 打开 2D 颜色覆盖层，并把 converter 二级 sub-tab 切到「颜色调整」。
       */
      openColor2DOverlay: () => {
        set({ color2DOverlayOpen: true, activeConverterSubTab: "color" });
      },

      /**
       * Close the 2D color overlay. If the converter is currently sitting on
       * the 'color' sub-tab, fall back to 'core' so the user lands on a real
       * settings page rather than an empty dock.
       *
       * 关闭 2D 颜色覆盖层。如果 converter 当前位于「颜色调整」sub-tab，
       * 则自动回退到「核心设置」，避免用户看到一个空的工作区。
       */
      closeColor2DOverlay: () => {
        set((state) => ({
          color2DOverlayOpen: false,
          activeConverterSubTab:
            state.activeConverterSubTab === "color"
              ? "core"
              : state.activeConverterSubTab,
        }));
      },

    }),
    {
      name: "lumina-widget-layout",
      // v9: model-surface-settings promoted to the TOP of the left dock;
      // migration relocates its persisted entry before basic-settings.
      // v9：模型贴图面板升至左坞顶部；迁移会把已存在的条目前移到基础设置之前。
      version: 9,
      // Sanitize on EVERY hydration, not only when the stored version is
      // older than ``version``. Zustand skips ``migrate`` entirely when the
      // stored version matches, so a stale SAME-version payload written
      // before a new widget id joined DEFAULT_LAYOUT would previously bypass
      // the backfill and leave ``undefined`` widget entries behind (white
      // screen in WidgetWorkspace). Running _sanitizePersistedState inside
      // ``merge`` guarantees every hydration path — fresh, migrated, or
      // same-version stale — ends up with all current DEFAULT_LAYOUT ids.
      //
      // 无论存储版本是否过期，每次水合都执行清洗。Zustand 在版本号一致时会
      // 完全跳过 ``migrate``，因此「同版本但缺少新增 widget」的旧载荷此前
      // 不会补齐默认项，导致 WidgetWorkspace 读到 ``undefined`` 而白屏。
      // 把 _sanitizePersistedState 放进 ``merge`` 可保证所有水合路径
      // （全新 / 迁移 / 同版本旧数据）都补齐当前 DEFAULT_LAYOUT 的全部 id。
      merge: (persistedState: unknown, currentState: WidgetStore): WidgetStore => ({
        ...currentState,
        ..._sanitizePersistedState(
          _promoteModelSurfaceEntry(persistedState),
        ),
      }),
      migrate: (persistedState, version) => {
        type PersistedWidgetState = {
          widgets?: Record<WidgetId, WidgetLayoutState>;
          activeTab?: TabId;
          colorWorkstationCollapsed?: boolean;
          color2DOverlayOpen?: boolean;
        };

        if (version < 3) {
          return { widgets: { ...DEFAULT_LAYOUT }, activeTab: "converter" };
        }
        if (version === 3 || version === 4 || version === 5 || version === 6) {
          const state =
            typeof persistedState === "object" && persistedState !== null
              ? (persistedState as PersistedWidgetState)
              : {};
          const widgets: Record<string, WidgetLayoutState> = {
            ...((state.widgets ?? {}) as Record<string, WidgetLayoutState>),
          };
          delete widgets["palette-panel"];
          delete widgets["lut-color-grid"];
          if (!widgets["fridge-magnet-settings"]) {
            widgets["fridge-magnet-settings"] = {
              ...DEFAULT_LAYOUT["fridge-magnet-settings"],
            };
          }
          if (!widgets["puzzle-settings"]) {
            widgets["puzzle-settings"] = {
              ...DEFAULT_LAYOUT["puzzle-settings"],
            };
          }
          // Recalculate stackOrder for converter widgets on both dock edges.
          const converterIds = TAB_WIDGET_MAP.converter;
          const reorderConverterEdge = (edge: "left" | "right") => {
            const edgeWidgets = converterIds
              .filter((id) => widgets[id]?.snapEdge === edge)
              .sort((a, b) => {
                const orderDiff =
                  (widgets[a]?.stackOrder ?? 0) - (widgets[b]?.stackOrder ?? 0);
                if (orderDiff !== 0) {
                  return orderDiff;
                }
                return converterIds.indexOf(a) - converterIds.indexOf(b);
              });

            edgeWidgets.forEach((id, index) => {
              if (widgets[id]) {
                widgets[id] = { ...widgets[id], stackOrder: index };
              }
            });
          };

          reorderConverterEdge("left");
          reorderConverterEdge("right");
          // Drop the deprecated `colorWorkstationCollapsed` field if it lingers in
          // the persisted payload; the entry has moved to a top-level secondary tab.
          // 颜色入口已迁移至顶部二级 tab，丢弃过时的折叠状态字段。
          const { colorWorkstationCollapsed: _drop, ...rest } = state;
          void _drop;
          return _sanitizePersistedState({ ...rest, widgets });
        }
        // v7 → v9 keeps the defensive sanitizer; v8 → v9 additionally
        // relocates an existing ``model-surface-settings`` entry before
        // ``basic-settings`` (the panel shipped today under v8, so no user
        // could have customized its position yet). Material/LUT widgets are
        // part of DEFAULT_LAYOUT, so old localStorage is backfilled instead
        // of being coerced away.
        // v7 → v9 保留防御性清洗；v8 → v9 额外把已存在的 ``model-surface-settings``
        // 条目前移到 ``basic-settings`` 之前（该面板今日才随 v8 上线，尚无用户
        // 自定义其位置）。耗材/LUT widget 已恢复到 DEFAULT_LAYOUT，因此旧
        // localStorage 会被补齐，而不是被归位到 converter。
        const state =
          typeof persistedState === "object" && persistedState !== null
            ? (persistedState as PersistedWidgetState)
            : {};
        return _sanitizePersistedState(
          _promoteModelSurfaceEntry(state),
        );
      },
      partialize: (state) => ({
        widgets: state.widgets,
        activeTab: state.activeTab,
      }),
      // Defensive guard for any payload (even at the current version) whose
      // activeTab/widgets reference removed entries: snap them back to valid
      // values on rehydrate so the UI never reads ``undefined``.
      // 二次防护：无论何种持久化载荷，重新水合时把失效的 activeTab/widgets 归位，
      // 确保 UI 不会读到 ``undefined``。
      onRehydrateStorage: () => (state) => {
        if (!state) return;
        const validTab = (Object.keys(TAB_WIDGET_MAP) as TabId[]).includes(
          state.activeTab,
        );
        if (!validTab) {
          state.activeTab = "converter";
        }
      },
    },
    ),
  ),
);
