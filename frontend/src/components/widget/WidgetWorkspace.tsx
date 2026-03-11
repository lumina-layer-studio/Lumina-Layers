/**
 * Widget workspace container with DnD context and snap guides.
 * Widget 工作区容器，包含拖拽上下文和吸附引导线。
 *
 * Wraps all widgets in a DndContext from @dnd-kit/core, handles drag lifecycle,
 * computes snap on drag end, and manages z-index layering for Three.js coexistence.
 * 使用 @dnd-kit/core 的 DndContext 包裹所有 Widget，处理拖拽生命周期，
 * 在拖拽结束时计算吸附，并管理 z-index 分层以与 Three.js 共存。
 */

import { useCallback, useEffect, useRef } from 'react';
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import type {
  DragStartEvent,
  DragMoveEvent,
  DragEndEvent,
  DragCancelEvent,
} from '@dnd-kit/core';
import { useWidgetStore, WIDGET_REGISTRY, TAB_WIDGET_MAP } from '../../stores/widgetStore';
import { useSettingsStore } from '../../stores/settingsStore';
import { computeSnap, computeStackPositions, WIDGET_WIDTH, COLLAPSED_HEIGHT } from '../../utils/widgetUtils';
import { WidgetPanel } from './WidgetPanel';
import { SnapGuides } from './SnapGuides';
import BasicSettingsWidgetContent from './BasicSettingsWidgetContent';
import AdvancedSettingsWidgetContent from './AdvancedSettingsWidgetContent';
import ReliefSettingsWidgetContent from './ReliefSettingsWidgetContent';
import PalettePanelWidgetContent from './PalettePanelWidgetContent';
import LutColorGridWidgetContent from './LutColorGridWidgetContent';
import OutlineSettingsWidgetContent from './OutlineSettingsWidgetContent';
import CloisonneSettingsWidgetContent from './CloisonneSettingsWidgetContent';
import CoatingSettingsWidgetContent from './CoatingSettingsWidgetContent';
import KeychainLoopWidgetContent from './KeychainLoopWidgetContent';
import ActionBarWidgetContent from './ActionBarWidgetContent';
import CalibrationWidgetContent from './CalibrationWidgetContent';
import ExtractorWidgetContent from './ExtractorWidgetContent';
import LutManagerWidgetContent from './LutManagerWidgetContent';
import FiveColorWidgetContent from './FiveColorWidgetContent';
import { useConverterDataInit } from '../../hooks/useConverterDataInit';
import type { WidgetId } from '../../types/widget';
import type { ReactNode, ComponentType } from 'react';

/**
 * Map from WidgetId to its content component.
 * WidgetId 到内容组件的映射。
 */
const WIDGET_CONTENT_MAP: Record<WidgetId, ComponentType> = {
  'basic-settings': BasicSettingsWidgetContent,
  'advanced-settings': AdvancedSettingsWidgetContent,
  'relief-settings': ReliefSettingsWidgetContent,
  'palette-panel': PalettePanelWidgetContent,
  'lut-color-grid': LutColorGridWidgetContent,
  'outline-settings': OutlineSettingsWidgetContent,
  'cloisonne-settings': CloisonneSettingsWidgetContent,
  'coating-settings': CoatingSettingsWidgetContent,
  'keychain-loop': KeychainLoopWidgetContent,
  'action-bar': ActionBarWidgetContent,
  'calibration': CalibrationWidgetContent,
  'extractor': ExtractorWidgetContent,
  'lut-manager': LutManagerWidgetContent,
  'five-color': FiveColorWidgetContent,
};

interface WidgetWorkspaceProps {
  children?: ReactNode; // CenterCanvas (Three.js)
}

export function WidgetWorkspace({ children }: WidgetWorkspaceProps) {
  const moveWidget = useWidgetStore((s) => s.moveWidget);
  const snapToEdge = useWidgetStore((s) => s.snapToEdge);
  const setDragging = useWidgetStore((s) => s.setDragging);
  const isDragging = useWidgetStore((s) => s.isDragging);
  const activeWidgetId = useWidgetStore((s) => s.activeWidgetId);
  const activeTab = useWidgetStore((s) => s.activeTab);

  // Filter registry to only show widgets for the active tab
  const activeWidgetIds = TAB_WIDGET_MAP[activeTab];
  const activeRegistry = WIDGET_REGISTRY.filter((c) => activeWidgetIds.includes(c.id));

  // Initialize converter data (LUT list, bed sizes) on mount
  useConverterDataInit();

  const containerRef = useRef<HTMLDivElement>(null);
  const dragPositionRef = useRef<{ x: number; y: number } | null>(null);
  const isDraggingRef = useRef(false);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } })
  );

  // Responsive resize handler — clamp free widgets & recalculate stacks
  // Only processes widgets belonging to the current active tab to prevent
  // cross-tab stacking that pushes widgets off-screen.
  // Reads actual DOM heights for expanded widgets to avoid overlap.
  const recalculateStacks = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    const { width } = container.getBoundingClientRect();
    const state = useWidgetStore.getState();
    const currentTabIds = TAB_WIDGET_MAP[state.activeTab];
    const tabWidgets = currentTabIds.map((id) => state.widgets[id]);

    // Force any free-floating widgets in current tab to snap to left edge
    tabWidgets
      .filter((w) => w.snapEdge === null && w.visible)
      .forEach((w) => {
        state.snapToEdge(w.id, 'left');
      });

    // Measure actual DOM heights for expanded widgets
    const measuredHeights = new Map<WidgetId, number>();
    for (const id of currentTabIds) {
      const el = container.querySelector(`[data-widget-id="${id}"]`) as HTMLElement | null;
      if (el) {
        measuredHeights.set(id, el.offsetHeight);
      }
    }

    // Recalculate stack positions for snapped widgets in current tab only
    // Re-read state after potential snapToEdge calls
    const updatedState = useWidgetStore.getState();
    const updatedTabWidgets = currentTabIds.map((id) => updatedState.widgets[id]);
    for (const edge of ['left', 'right'] as const) {
      const stackWidgets = updatedTabWidgets.filter((w) => w.snapEdge === edge && w.visible);
      if (stackWidgets.length > 0) {
        const positions = computeStackPositions(stackWidgets, edge, width, measuredHeights);
        positions.forEach((pos, id) => {
          useWidgetStore.getState().moveWidget(id, pos);
        });
      }
    }
  }, []);

  // ResizeObserver to detect widget content height changes (e.g. checkbox
  // toggling extra options) and recalculate stack positions automatically.
  // Uses a debounce to avoid excessive recalculations during animations.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let debounceTimer: ReturnType<typeof setTimeout> | null = null;
    const debouncedRecalc = () => {
      if (isDraggingRef.current) return;
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => recalculateStacks(), 50);
    };

    const observer = new ResizeObserver(debouncedRecalc);

    // Observe all widget elements in the container
    const widgetEls = container.querySelectorAll('[data-widget-id]');
    widgetEls.forEach((el) => observer.observe(el));

    // Also observe newly added widgets via MutationObserver
    const mutationObs = new MutationObserver(() => {
      observer.disconnect();
      const els = container.querySelectorAll('[data-widget-id]');
      els.forEach((el) => observer.observe(el));
    });
    mutationObs.observe(container, { childList: true, subtree: true });

    return () => {
      observer.disconnect();
      mutationObs.disconnect();
      if (debounceTimer) clearTimeout(debounceTimer);
    };
  }, [recalculateStacks, activeTab]);

  useEffect(() => {
    window.addEventListener('resize', recalculateStacks);
    window.addEventListener('widget-animation-complete', recalculateStacks);
    recalculateStacks(); // run once on mount for correct initial positions

    return () => {
      window.removeEventListener('resize', recalculateStacks);
      window.removeEventListener('widget-animation-complete', recalculateStacks);
    };
  }, [recalculateStacks]);

  // Recalculate stack positions when any widget's collapsed state or
  // expandedHeight changes. This prevents widgets from overlapping after
  // expand/collapse or when content dynamically changes height.
  // Uses a targeted selector to avoid subscribing to the entire widgets object.
  const layoutKey = useWidgetStore(
    useCallback(
      (s: { widgets: Record<WidgetId, { collapsed: boolean; expandedHeight: number }> }) =>
        activeWidgetIds
          .map((id) => `${id}:${s.widgets[id].collapsed ? 1 : 0}:${s.widgets[id].expandedHeight}`)
          .join(','),
      [activeWidgetIds]
    )
  );

  useEffect(() => {
    recalculateStacks();
  }, [layoutKey, activeTab, recalculateStacks]);

  // Auto-detect backdrop-filter support and disable blur if unsupported
  useEffect(() => {
    const supportsBlur = CSS.supports?.('backdrop-filter', 'blur(12px)') ?? false;
    if (!supportsBlur) {
      useSettingsStore.getState().setEnableBlur(false);
    }
  }, []);

  const handleDragStart = useCallback(
    (event: DragStartEvent) => {
      isDraggingRef.current = true;
      setDragging(true, event.active.id as WidgetId);
    },
    [setDragging]
  );

  const handleDragMove = useCallback(
    (event: DragMoveEvent) => {
      const { active, delta } = event;
      const id = active.id as WidgetId;
      const widget = useWidgetStore.getState().widgets[id];
      if (widget) {
        dragPositionRef.current = {
          x: widget.position.x + delta.x,
          y: widget.position.y + delta.y,
        };
      }
    },
    []
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, delta } = event;
      const id = active.id as WidgetId;
      const widget = useWidgetStore.getState().widgets[id];
      const container = containerRef.current;

      if (!widget || !container) {
        setDragging(false);
        dragPositionRef.current = null;
        return;
      }

      const containerRect = container.getBoundingClientRect();
      const newX = widget.position.x + delta.x;
      const newY = widget.position.y + delta.y;
      const widgetLeft = newX;
      const widgetRight = newX + WIDGET_WIDTH;

      const snap = computeSnap(
        widgetLeft,
        widgetRight,
        containerRect.width,
        newY
      );

      // Always snap to nearest edge — widgets are never free-floating
      moveWidget(id, snap.snappedPosition);
      snapToEdge(id, snap.edge!);

      // Reset isDraggingRef BEFORE scheduling recalculateStacks so the
      // ResizeObserver guard won't block the recalculation.
      isDraggingRef.current = false;
      requestAnimationFrame(() => recalculateStacks());

      setDragging(false);
      dragPositionRef.current = null;
    },
    [moveWidget, snapToEdge, setDragging, recalculateStacks]
  );

  const handleDragCancel = useCallback(
    (_event: DragCancelEvent) => {
      isDraggingRef.current = false;
      setDragging(false);
      dragPositionRef.current = null;
    },
    [setDragging]
  );

  return (
    <DndContext
      sensors={sensors}
      onDragStart={handleDragStart}
      onDragMove={handleDragMove}
      onDragEnd={handleDragEnd}
      onDragCancel={handleDragCancel}
    >
      <div
        ref={containerRef}
        className="relative w-full h-full overflow-hidden"
        style={{ pointerEvents: isDragging ? 'all' : undefined }}
      >
        {/* Center Canvas (Three.js / Extractor) — z-10 */}
        <div className="absolute inset-0 z-10 flex flex-col" style={{ pointerEvents: 'auto' }}>
          {children}
        </div>

        {/* Snap Guides — z-20 */}
        <SnapGuides
          isDraggingRef={isDraggingRef}
          dragPositionRef={dragPositionRef}
          containerRef={containerRef}
        />

        {/* Widget Layer — z-30 */}
        <div className="absolute inset-0 z-30" style={{ pointerEvents: 'none' }}>
          {activeRegistry.map((config) => {
            const ContentComponent = WIDGET_CONTENT_MAP[config.id];
            return (
              <WidgetPanel key={config.id} widgetId={config.id} titleKey={config.titleKey}>
                <ContentComponent />
              </WidgetPanel>
            );
          })}
        </div>

        {/* DragOverlay — z-40 */}
        <DragOverlay>
          {activeWidgetId ? (
            <div
              className="z-40 rounded-xl shadow-2xl border border-white/30 backdrop-blur-xl bg-white/50 dark:bg-gray-900/50 opacity-80"
              style={{ width: WIDGET_WIDTH, height: COLLAPSED_HEIGHT }}
            >
              <div className="px-3 py-2 text-sm font-medium text-gray-600 dark:text-gray-300">
                {activeWidgetId}
              </div>
            </div>
          ) : null}
        </DragOverlay>
      </div>
    </DndContext>
  );
}
