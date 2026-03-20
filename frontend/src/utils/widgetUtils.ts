/**
 * Widget utility functions for the floating widget workspace.
 * 浮动 Widget 工作区工具函数。
 */

import type { WidgetId, WidgetLayoutState, SnapResult } from '../types/widget';

// ===== 常量 =====
/** Default widget width in pixels. (默认 Widget 宽度，单位像素) */
export const WIDGET_WIDTH = 350;

/** Collapsed widget height — header only. (折叠状态高度，仅标题栏) */
export const COLLAPSED_HEIGHT = 40;

/** Default expanded widget height. (默认展开状态高度) */
export const EXPANDED_HEIGHT = 400;

/** Snap zone threshold in pixels. (吸附区域阈值，单位像素) */
export const SNAP_THRESHOLD = 48;

/** Gap between stacked widgets in pixels. (堆叠 Widget 间距，单位像素) */
export const STACK_GAP = 8;

/**
 * Clamp widget position within container bounds.
 * 将 Widget 位置约束在容器边界内。
 *
 * Args:
 *   position ({ x: number; y: number }): The raw widget position. (原始 Widget 位置)
 *   containerWidth (number): Container width in pixels. (容器宽度)
 *   containerHeight (number): Container height in pixels. (容器高度)
 *   widgetWidth (number): Widget width, defaults to WIDGET_WIDTH. (Widget 宽度)
 *   headerHeight (number): Minimum visible height, defaults to COLLAPSED_HEIGHT. (最小可见高度)
 *
 * Returns:
 *   { x: number; y: number }: Clamped position within bounds. (约束后的位置)
 */
export function clampPosition(
  position: { x: number; y: number },
  containerWidth: number,
  containerHeight: number,
  widgetWidth: number = WIDGET_WIDTH,
  headerHeight: number = COLLAPSED_HEIGHT
): { x: number; y: number } {
  const maxX = Math.max(0, containerWidth - widgetWidth);
  const maxY = Math.max(0, containerHeight - headerHeight);

  return {
    x: Math.min(Math.max(0, position.x), maxX),
    y: Math.min(Math.max(0, position.y), maxY),
  };
}

/**
 * Always snap widget to the nearest screen edge (left or right).
 * 始终将 Widget 吸附到最近的屏幕边缘（左或右）。
 *
 * Widgets are never free-floating — they always belong to an edge stack.
 * Widget 不允许自由浮动，始终属于某个边缘堆叠。
 *
 * Args:
 *   widgetLeft (number): Left edge x-coordinate of the widget. (Widget 左边缘 x 坐标)
 *   widgetRight (number): Right edge x-coordinate of the widget. (Widget 右边缘 x 坐标)
 *   containerWidth (number): Container width in pixels. (容器宽度)
 *   widgetTop (number): Top edge y-coordinate of the widget. (Widget 顶部 y 坐标)
 *   _threshold (number): Unused, kept for API compatibility. (未使用，保留 API 兼容性)
 *
 * Returns:
 *   SnapResult: Snap result — always snaps to nearest edge. (吸附结果，始终吸附到最近边缘)
 */
export function computeSnap(
  widgetLeft: number,
  widgetRight: number,
  containerWidth: number,
  widgetTop: number,
  _threshold: number = SNAP_THRESHOLD
): SnapResult {
  // Always snap: pick the nearest edge based on widget center position
  const widgetCenter = (widgetLeft + widgetRight) / 2;
  const snapToLeft = widgetCenter <= containerWidth / 2;

  return {
    shouldSnap: true,
    edge: snapToLeft ? 'left' : 'right',
    snappedPosition: {
      x: snapToLeft ? 0 : containerWidth - WIDGET_WIDTH,
      y: widgetTop,
    },
  };
}

/**
 * Compute stacked positions for widgets snapped to the same edge.
 * 计算吸附到同一边缘的 Widget 堆叠位置。
 *
 * Uses the pre-calculated expandedHeight from widget state for expanded widgets,
 * with optional DOM-measured heights as override for final accuracy.
 * 展开的 Widget 使用状态中预计算的 expandedHeight，
 * 可选的 DOM 测量高度作为最终精度覆盖。
 *
 * Args:
 *   stackWidgets (WidgetLayoutState[]): Widgets snapped to the target edge. (吸附到目标边缘的 Widget 列表)
 *   edge ('left' | 'right'): The edge to stack against. (堆叠的目标边缘)
 *   containerWidth (number): Container width in pixels. (容器宽度)
 *   measuredHeights (Map<WidgetId, number>): Optional actual DOM heights per widget. (可选的实际 DOM 高度映射)
 *
 * Returns:
 *   Map<WidgetId, { x: number; y: number }>: Computed positions keyed by widget ID. (按 Widget ID 索引的计算位置)
 */
export function computeStackPositions(
  stackWidgets: WidgetLayoutState[],
  edge: 'left' | 'right',
  containerWidth: number,
  measuredHeights?: Map<WidgetId, number>
): Map<WidgetId, { x: number; y: number }> {
  const sorted = [...stackWidgets].sort((a, b) => a.stackOrder - b.stackOrder);
  const positions = new Map<WidgetId, { x: number; y: number }>();
  const x = edge === 'left' ? 0 : containerWidth - WIDGET_WIDTH;
  let currentY = STACK_GAP; // top padding

  for (const widget of sorted) {
    positions.set(widget.id, { x, y: currentY });
    const height = widget.collapsed
      ? COLLAPSED_HEIGHT
      : (measuredHeights?.get(widget.id) ?? widget.expandedHeight ?? EXPANDED_HEIGHT);
    currentY += height + STACK_GAP;
  }

  return positions;
}
