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
import { persist } from "zustand/middleware";
import { EXPANDED_HEIGHT } from "../utils/widgetUtils";
import type {
  WidgetId,
  WidgetLayoutState,
  WidgetStore,
  WidgetConfig,
  TabId,
} from "../types/widget";

// ===== TAB → Widget 映射 =====

export const TAB_WIDGET_MAP: Record<TabId, WidgetId[]> = {
  converter: [
    "basic-settings",
    "advanced-settings",
    "relief-settings",
    "outline-settings",
    "cloisonne-settings",
    "coating-settings",
    "keychain-loop",
    "action-bar",
  ],
  calibration: ["calibration"],
  extractor: ["extractor"],
  "lut-manager": ["lut-manager"],
  "five-color": ["five-color"],
  vectorizer: [],
  settings: [],
};

// ===== 默认布局 =====

export const DEFAULT_LAYOUT: Record<WidgetId, WidgetLayoutState> = {
  // --- Converter 页面：8 个 Widget，左侧吸附，stackOrder 0-7 ---
  "basic-settings": {
    id: "basic-settings",
    position: { x: 0, y: 0 },
    collapsed: false,
    visible: true,
    snapEdge: "left",
    stackOrder: 0,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "advanced-settings": {
    id: "advanced-settings",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: true,
    snapEdge: "left",
    stackOrder: 1,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "relief-settings": {
    id: "relief-settings",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: true,
    snapEdge: "left",
    stackOrder: 2,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "outline-settings": {
    id: "outline-settings",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: true,
    snapEdge: "left",
    stackOrder: 3,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "cloisonne-settings": {
    id: "cloisonne-settings",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: true,
    snapEdge: "left",
    stackOrder: 4,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "coating-settings": {
    id: "coating-settings",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: true,
    snapEdge: "left",
    stackOrder: 5,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "keychain-loop": {
    id: "keychain-loop",
    position: { x: 0, y: 0 },
    collapsed: true,
    visible: true,
    snapEdge: "left",
    stackOrder: 6,
    expandedHeight: EXPANDED_HEIGHT,
  },
  "action-bar": {
    id: "action-bar",
    position: { x: 0, y: 0 },
    collapsed: false,
    visible: true,
    snapEdge: "left",
    stackOrder: 7,
    expandedHeight: EXPANDED_HEIGHT,
  },
  // --- 其他 4 个页面：各 1 个 Widget，左侧吸附，stackOrder 0 ---
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
  // Converter 页面
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
    id: "action-bar",
    titleKey: "widget.actionBar",
    icon: "play",
    defaultWidth: 350,
    minWidth: 300,
  },
  // 其他页面
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

export const useWidgetStore = create<WidgetStore>()(
  persist(
    (set) => ({
      widgets: { ...DEFAULT_LAYOUT },
      isDragging: false,
      activeWidgetId: null,
      activeTab: "converter" as TabId,
      colorWorkstationCollapsed: true,

      /**
       * Set the active TAB page.
       * 设置当前激活的 TAB 页面。
       */
      setActiveTab: (tab: TabId) => {
        set({ activeTab: tab });
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
      setWidgetPositions: (positions: Partial<Record<WidgetId, { x: number; y: number }>>) => {
        set((state) => {
          const entries = Object.entries(positions) as [WidgetId, { x: number; y: number }][];
          if (entries.length === 0) return state;

          let changed = false;
          const widgets = { ...state.widgets };

          for (const [id, position] of entries) {
            const current = widgets[id];
            if (
              !current ||
              (current.position.x === position.x && current.position.y === position.y)
            ) {
              continue;
            }
            widgets[id] = { ...current, position };
            changed = true;
          }

          return changed ? { widgets } : state;
        });
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
        set((state) => {
          // Only update if height actually changed to avoid unnecessary re-renders
          if (state.widgets[id].expandedHeight === height) return state;
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
       * Reset all widgets to default layout.
       * 重置所有 Widget 到默认布局。
       */
      resetLayout: () => {
        set({
          widgets: { ...DEFAULT_LAYOUT },
          isDragging: false,
          activeWidgetId: null,
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
      snapAndReorder: (id: WidgetId, edge: "left" | "right", orderedIds: WidgetId[]) => {
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
       * Toggle ColorWorkstation collapsed state.
       * 切换 ColorWorkstation 展开/收起状态。
       */
      toggleColorWorkstation: () => {
        set((state) => ({
          colorWorkstationCollapsed: !state.colorWorkstationCollapsed,
        }));
      },
    }),
    {
      name: "lumina-widget-layout",
      version: 4,
      migrate: (persistedState, version) => {
        if (version < 3) {
          return { widgets: { ...DEFAULT_LAYOUT }, activeTab: "converter" };
        }
        if (version === 3) {
          const state = persistedState as any;
          const widgets = { ...state.widgets };
          delete widgets["palette-panel"];
          delete widgets["lut-color-grid"];
          // Recalculate stackOrder for converter widgets on left edge
          const converterIds = TAB_WIDGET_MAP.converter;
          const leftConverterWidgets = converterIds
            .filter((id) => widgets[id]?.snapEdge === "left")
            .sort(
              (a, b) =>
                (widgets[a]?.stackOrder ?? 0) - (widgets[b]?.stackOrder ?? 0),
            );
          leftConverterWidgets.forEach((id, index) => {
            if (widgets[id]) {
              widgets[id] = { ...widgets[id], stackOrder: index };
            }
          });
          return {
            ...state,
            widgets,
            colorWorkstationCollapsed: true,
          };
        }
        return persistedState as WidgetStore;
      },
      partialize: (state) => ({
        widgets: state.widgets,
        activeTab: state.activeTab,
        colorWorkstationCollapsed: state.colorWorkstationCollapsed,
      }),
      onRehydrateStorage: () => () => {},
    },
  ),
);
