/**
 * Widget type definitions for the floating widget workspace.
 * 浮动 Widget 工作区类型定义。
 */

// ===== TAB ID =====
// The main app owns converter, Material/LUT, vectorizer, workshop, and settings tabs.
// 主应用拥有 converter、耗材/LUT、vectorizer、workshop 和 settings 全部标签。
export type TabId =
  | "converter"
  | "calibration"
  | "extractor"
  | "gradient-card-generate"
  | "gradient-card-extract"
  | "material-library"
  | "material-cloud-sync"
  | "material-recipe"
  | "material-gamut"
  | "material-cache"
  | "lut-library"
  | "lut-manager"
  | "lut-cloud-sync"
  | "lut-details"
  | "lut-compare"
  | "five-color"
  | "vectorizer"
  | "workshop"
  | "settings";

// ===== Converter 二级 sub-tab ID =====
// Converter 主 tab 下的语义分组：核心设置 / 颜色调整 / 高级功能。
// 颜色调整 sub-tab 与 Color2DOverlay 双向同步：进入 'color' 即打开 overlay，
// 离开 'color' 或关闭 overlay 都会回到上一个 sub-tab（默认 'core'）。
export type ConverterSubTabId = "core" | "color" | "advanced";

// ===== Widget ID =====
export type WidgetId =
  | "basic-settings"
  | "model-surface-settings"
  | "advanced-settings"
  | "relief-settings"
  | "outline-settings"
  | "cloisonne-settings"
  | "coating-settings"
  | "keychain-loop"
  | "fridge-magnet-settings"
  | "puzzle-settings"
  | "action-bar"
  | "calibration"
  | "extractor"
  | "lut-manager"
  | "five-color";

// ===== Widget 布局状态 =====
export interface WidgetLayoutState {
  id: WidgetId;
  position: { x: number; y: number };
  collapsed: boolean;
  visible: boolean;
  snapEdge: "left" | "right" | null; // 当前吸附的边缘
  stackOrder: number; // 在 Widget_Stack 中的排序
  expandedHeight: number; // 预计算的展开高度（像素）
}

// ===== Widget Store（仅布局状态）=====
export interface WidgetStore {
  widgets: Record<WidgetId, WidgetLayoutState>;
  isDragging: boolean;
  activeWidgetId: WidgetId | null;
  activeTab: TabId;
  activeConverterSubTab: ConverterSubTabId;

  // TAB 切换
  setActiveTab: (tab: TabId) => void;
  setActiveConverterSubTab: (subTab: ConverterSubTabId) => void;

  // 布局操作
  moveWidget: (id: WidgetId, position: { x: number; y: number }) => void;
  setWidgetPositions: (
    positions: Partial<Record<WidgetId, { x: number; y: number }>>,
  ) => void;
  toggleCollapse: (id: WidgetId) => void;
  toggleVisible: (id: WidgetId) => void;
  snapToEdge: (id: WidgetId, edge: "left" | "right") => void;
  detachFromEdge: (id: WidgetId) => void;
  setDragging: (isDragging: boolean, activeId?: WidgetId) => void;
  setExpandedHeight: (id: WidgetId, height: number) => void;
  autoArrange: () => void;
  resetLayout: () => void;

  // 堆叠管理
  reorderStack: (edge: "left" | "right", orderedIds: WidgetId[]) => void;
  snapAndReorder: (
    id: WidgetId,
    edge: "left" | "right",
    orderedIds: WidgetId[],
  ) => void;

  // 2D 颜色覆盖层
  color2DOverlayOpen: boolean;
  openColor2DOverlay: () => void;
  closeColor2DOverlay: () => void;
}

// ===== Widget 注册表（静态配置）=====
export interface WidgetConfig {
  id: WidgetId;
  titleKey: string; // i18n key
  icon: string; // 图标标识
  defaultWidth: number;
  minWidth: number;
  component: React.ComponentType; // 对应的业务组件
}

// ===== 持久化状态 =====
export interface PersistedWidgetState {
  widgets: Record<
    WidgetId,
    {
      position: { x: number; y: number };
      collapsed: boolean;
      visible: boolean;
      snapEdge: "left" | "right" | null;
      stackOrder: number;
      expandedHeight: number;
    }
  >;
  version: number; // 用于数据迁移
}
