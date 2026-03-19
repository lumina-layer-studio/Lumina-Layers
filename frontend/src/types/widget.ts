/**
 * Widget type definitions for the floating widget workspace.
 * 浮动 Widget 工作区类型定义。
 */

// ===== TAB ID =====
export type TabId = 'converter' | 'calibration' | 'extractor' | 'lut-manager' | 'five-color' | 'vectorizer' | 'settings';

// ===== Widget ID =====
export type WidgetId =
  | 'basic-settings'
  | 'advanced-settings'
  | 'relief-settings'
  | 'outline-settings'
  | 'cloisonne-settings'
  | 'coating-settings'
  | 'keychain-loop'
  | 'action-bar'
  | 'calibration'
  | 'extractor'
  | 'lut-manager'
  | 'five-color';

// ===== Widget 布局状态 =====
export interface WidgetLayoutState {
  id: WidgetId;
  position: { x: number; y: number };
  collapsed: boolean;
  visible: boolean;
  snapEdge: 'left' | 'right' | null;  // 当前吸附的边缘
  stackOrder: number;                   // 在 Widget_Stack 中的排序
  expandedHeight: number;               // 预计算的展开高度（像素）
}

// ===== Widget Store（仅布局状态）=====
export interface WidgetStore {
  widgets: Record<WidgetId, WidgetLayoutState>;
  isDragging: boolean;
  activeWidgetId: WidgetId | null;
  activeTab: TabId;

  // TAB 切换
  setActiveTab: (tab: TabId) => void;

  // 布局操作
  moveWidget: (id: WidgetId, position: { x: number; y: number }) => void;
  setWidgetPositions: (positions: Partial<Record<WidgetId, { x: number; y: number }>>) => void;
  toggleCollapse: (id: WidgetId) => void;
  toggleVisible: (id: WidgetId) => void;
  snapToEdge: (id: WidgetId, edge: 'left' | 'right') => void;
  detachFromEdge: (id: WidgetId) => void;
  setDragging: (isDragging: boolean, activeId?: WidgetId) => void;
  setExpandedHeight: (id: WidgetId, height: number) => void;
  autoArrange: () => void;
  resetLayout: () => void;

  // 堆叠管理
  reorderStack: (edge: 'left' | 'right', orderedIds: WidgetId[]) => void;
  snapAndReorder: (id: WidgetId, edge: 'left' | 'right', orderedIds: WidgetId[]) => void;

  // ColorWorkstation 展开/收起
  colorWorkstationCollapsed: boolean;
  toggleColorWorkstation: () => void;
}

// ===== 吸附计算 =====
export interface SnapResult {
  shouldSnap: boolean;
  edge: 'left' | 'right' | null;
  snappedPosition: { x: number; y: number };
}

// ===== Widget 注册表（静态配置）=====
export interface WidgetConfig {
  id: WidgetId;
  titleKey: string;        // i18n key
  icon: string;            // 图标标识
  defaultWidth: number;
  minWidth: number;
  component: React.ComponentType;  // 对应的业务组件
}

// ===== 持久化状态 =====
export interface PersistedWidgetState {
  widgets: Record<WidgetId, {
    position: { x: number; y: number };
    collapsed: boolean;
    visible: boolean;
    snapEdge: 'left' | 'right' | null;
    stackOrder: number;
    expandedHeight: number;
  }>;
  version: number;  // 用于数据迁移
}
