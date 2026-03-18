/**
 * Widget workspace container with DnD context and snap guides.
 * Widget 工作区容器，包含拖拽上下文和吸附引导线。
 *
 * Wraps all widgets in a DndContext from @dnd-kit/core, handles drag lifecycle,
 * computes snap on drag end, and manages z-index layering for Three.js coexistence.
 * 使用 @dnd-kit/core 的 DndContext 包裹所有 Widget，处理拖拽生命周期，
 * 在拖拽结束时计算吸附，并管理 z-index 分层以与 Three.js 共存。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
} from '@dnd-kit/core';
import { useWidgetStore, WIDGET_REGISTRY, TAB_WIDGET_MAP } from '../../stores/widgetStore';
import { useSettingsStore } from '../../stores/settingsStore';
import { computeSnap, computeStackPositions, computeDockBottomInset, WIDGET_WIDTH, COLLAPSED_HEIGHT, EXPANDED_HEIGHT, STACK_GAP } from '../../utils/widgetUtils';
import { WidgetPanel } from './WidgetPanel';
import { SnapGuides } from './SnapGuides';
import BasicSettingsWidgetContent from './BasicSettingsWidgetContent';
import AdvancedSettingsWidgetContent from './AdvancedSettingsWidgetContent';
import ReliefSettingsWidgetContent from './ReliefSettingsWidgetContent';
import OutlineSettingsWidgetContent from './OutlineSettingsWidgetContent';
import CloisonneSettingsWidgetContent from './CloisonneSettingsWidgetContent';
import CoatingSettingsWidgetContent from './CoatingSettingsWidgetContent';
import KeychainLoopWidgetContent from './KeychainLoopWidgetContent';
import ActionBarWidgetContent from './ActionBarWidgetContent';
import CalibrationWidgetContent from './CalibrationWidgetContent';
import ExtractorWidgetContent from './ExtractorWidgetContent';
import LutManagerWidgetContent from './LutManagerWidgetContent';
import FiveColorWidgetContent from './FiveColorWidgetContent';
import ColorWorkstation from './ColorWorkstation';
import { useConverterDataInit } from '../../hooks/useConverterDataInit';
import { useI18n } from '../../i18n/context';
import type { WidgetId } from '../../types/widget';
import type { ReactNode, ComponentType } from 'react';
import { useShallow } from 'zustand/react/shallow';

/**
 * Map from WidgetId to its content component.
 * WidgetId 到内容组件的映射。
 */
const WIDGET_CONTENT_MAP: Record<WidgetId, ComponentType> = {
  'basic-settings': BasicSettingsWidgetContent,
  'advanced-settings': AdvancedSettingsWidgetContent,
  'relief-settings': ReliefSettingsWidgetContent,
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

const DOCK_SCROLL_WIDTH = WIDGET_WIDTH + 16;

interface InsertPreviewState {
  edge: 'left' | 'right';
  lineY: number;
  upperId: WidgetId | null;
  lowerId: WidgetId | null;
}

interface WidgetWorkspaceProps {
  children?: ReactNode; // CenterCanvas (Three.js)
}

export function WidgetWorkspace({ children }: WidgetWorkspaceProps) {
  const { t } = useI18n();
  const moveWidget = useWidgetStore((s) => s.moveWidget);
  const setWidgetPositions = useWidgetStore((s) => s.setWidgetPositions);
  const snapAndReorder = useWidgetStore((s) => s.snapAndReorder);
  const setDragging = useWidgetStore((s) => s.setDragging);
  const isDragging = useWidgetStore((s) => s.isDragging);
  const activeWidgetId = useWidgetStore((s) => s.activeWidgetId);
  const activeTab = useWidgetStore((s) => s.activeTab);

  // Filter registry to only show widgets for the active tab
  const activeWidgetIds = TAB_WIDGET_MAP[activeTab];
  const activeRegistry = WIDGET_REGISTRY.filter((c) => activeWidgetIds.includes(c.id));
  const activeWidgets = useWidgetStore(
    useShallow((s) => activeWidgetIds.map((id) => s.widgets[id]))
  );

  // Initialize converter data (LUT list, bed sizes) on mount
  useConverterDataInit();

  const containerRef = useRef<HTMLDivElement>(null);
  const leftDockRef = useRef<HTMLDivElement>(null);
  const rightDockRef = useRef<HTMLDivElement>(null);
  const colorWorkstationRef = useRef<HTMLDivElement>(null);
  const dragPositionRef = useRef<{ x: number; y: number } | null>(null);
  const dragSourceRef = useRef<{ edge: 'left' | 'right'; scrollTop: number } | null>(null);
  const insertPreviewRef = useRef<InsertPreviewState | null>(null);
  const isDraggingRef = useRef(false);
  const [containerWidth, setContainerWidth] = useState(0);
  const [dockBottomInsets, setDockBottomInsets] = useState({ left: 0, right: 0 });
  const activeWidgetMap = useMemo(() => {
    const map = new Map(activeWidgets.map((widget) => [widget.id, widget]));
    return map;
  }, [activeWidgets]);

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
    const batchedPositions: Partial<Record<WidgetId, { x: number; y: number }>> = {};
    for (const edge of ['left', 'right'] as const) {
      const stackWidgets = updatedTabWidgets.filter((w) => w.snapEdge === edge && w.visible);
      if (stackWidgets.length > 0) {
        const positions = computeStackPositions(stackWidgets, edge, width, measuredHeights);
        positions.forEach((pos, id) => {
          batchedPositions[id] = pos;
        });
      }
    }
    setWidgetPositions(batchedPositions);
  }, [setWidgetPositions]);

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

  // Keep a live workspace width snapshot for right-dock local positioning.
  useEffect(() => {
    const updateWidth = () => {
      const width = containerRef.current?.getBoundingClientRect().width ?? 0;
      setContainerWidth(width);
    };
    updateWidth();
    window.addEventListener('resize', updateWidth);
    return () => window.removeEventListener('resize', updateWidth);
  }, []);

  // Only recompute dock avoidance on viewport or workstation size changes.
  // This keeps the runtime cost low while still responding to real overlap.
  useEffect(() => {
    let frameId = 0;

    const updateDockInsets = () => {
      const workstationRect = colorWorkstationRef.current?.getBoundingClientRect();
      const leftDockRect = leftDockRef.current?.getBoundingClientRect();
      const rightDockRect = rightDockRef.current?.getBoundingClientRect();

      const nextInsets = {
        left: workstationRect && leftDockRect ? computeDockBottomInset(leftDockRect, workstationRect) : 0,
        right: workstationRect && rightDockRect ? computeDockBottomInset(rightDockRect, workstationRect) : 0,
      };

      setDockBottomInsets((prev) =>
        prev.left === nextInsets.left && prev.right === nextInsets.right ? prev : nextInsets
      );
    };

    const scheduleDockInsetUpdate = () => {
      if (frameId) {
        cancelAnimationFrame(frameId);
      }
      frameId = requestAnimationFrame(updateDockInsets);
    };

    scheduleDockInsetUpdate();
    window.addEventListener('resize', scheduleDockInsetUpdate);

    const observer = new ResizeObserver(scheduleDockInsetUpdate);
    if (containerRef.current) observer.observe(containerRef.current);
    if (colorWorkstationRef.current) observer.observe(colorWorkstationRef.current);

    return () => {
      if (frameId) {
        cancelAnimationFrame(frameId);
      }
      window.removeEventListener('resize', scheduleDockInsetUpdate);
      observer.disconnect();
    };
  }, [activeTab]);

  const leftRegistry = activeRegistry.filter((config) => activeWidgetMap.get(config.id)?.snapEdge !== 'right');
  const rightRegistry = activeRegistry.filter((config) => activeWidgetMap.get(config.id)?.snapEdge === 'right');

  const stackHeight = (edge: 'left' | 'right') => {
    const stackWidgets = activeWidgets
      .filter((w) => w.visible && (edge === 'left' ? w.snapEdge !== 'right' : w.snapEdge === 'right'))
      .sort((a, b) => a.stackOrder - b.stackOrder);
    if (stackWidgets.length === 0) return 0;
    return stackWidgets.reduce(
      (sum, w) => sum + (w.collapsed ? COLLAPSED_HEIGHT : (w.expandedHeight ?? EXPANDED_HEIGHT)) + STACK_GAP,
      STACK_GAP
    );
  };

  const leftStackHeight = stackHeight('left');
  const rightStackHeight = stackHeight('right');
  const rightDockOffset = Math.max(0, (containerWidth || window.innerWidth) - WIDGET_WIDTH);

  const getDockScrollTop = useCallback((edge: 'left' | 'right') => {
    return edge === 'left'
      ? (leftDockRef.current?.scrollTop ?? 0)
      : (rightDockRef.current?.scrollTop ?? 0);
  }, []);

  const lockDockHorizontalScroll = useCallback((edge: 'left' | 'right') => {
    const dock = edge === 'left' ? leftDockRef.current : rightDockRef.current;
    if (dock && dock.scrollLeft !== 0) {
      dock.scrollLeft = 0;
    }
  }, []);

  const toEdgeContentY = useCallback(
    (globalDropY: number, targetEdge: 'left' | 'right') => {
      const sourceScrollTop = dragSourceRef.current?.scrollTop ?? 0;
      const targetScrollTop = getDockScrollTop(targetEdge);
      return Math.max(0, globalDropY - sourceScrollTop + targetScrollTop);
    },
    [getDockScrollTop]
  );

  const computeInsertion = useCallback(
    (draggedId: WidgetId, targetEdge: 'left' | 'right', contentDropY: number) => {
      const state = useWidgetStore.getState();
      const currentTabIds = TAB_WIDGET_MAP[state.activeTab];
      const siblings = currentTabIds
        .map((wid) => state.widgets[wid])
        .filter((w) => w.snapEdge === targetEdge && w.visible && w.id !== draggedId)
        .sort((a, b) => a.stackOrder - b.stackOrder);

      const orderedIds: WidgetId[] = [];
      let inserted = false;
      let lineY = STACK_GAP / 2;
      let upperId: WidgetId | null = null;
      let lowerId: WidgetId | null = siblings[0]?.id ?? null;
      let prevId: WidgetId | null = null;
      let accY = STACK_GAP;

      for (const sibling of siblings) {
        const h = sibling.collapsed
          ? COLLAPSED_HEIGHT
          : (sibling.expandedHeight ?? EXPANDED_HEIGHT);
        const midpoint = accY + h / 2;

        if (!inserted && contentDropY < midpoint) {
          orderedIds.push(draggedId);
          inserted = true;
          upperId = prevId;
          lowerId = sibling.id;
          lineY = Math.max(0, accY - STACK_GAP / 2);
        }

        orderedIds.push(sibling.id);
        prevId = sibling.id;
        accY += h + STACK_GAP;
      }

      if (!inserted) {
        orderedIds.push(draggedId);
        upperId = prevId;
        lowerId = null;
        lineY = Math.max(0, accY - STACK_GAP / 2);
      }

      return { orderedIds, lineY, upperId, lowerId };
    },
    []
  );

  const handleDragStart = useCallback(
    (event: DragStartEvent) => {
      const id = event.active.id as WidgetId;
      const widget = useWidgetStore.getState().widgets[id];
      const sourceEdge = widget?.snapEdge === 'right' ? 'right' : 'left';
      lockDockHorizontalScroll(sourceEdge);
      dragSourceRef.current = { edge: sourceEdge, scrollTop: getDockScrollTop(sourceEdge) };
      insertPreviewRef.current = null;
      isDraggingRef.current = true;
      setDragging(true, id);
    },
    [setDragging, getDockScrollTop, lockDockHorizontalScroll]
  );

  const handleDragMove = useCallback(
    (event: DragMoveEvent) => {
      const { active, delta } = event;
      const id = active.id as WidgetId;
      const widget = useWidgetStore.getState().widgets[id];
      if (widget) {
        lockDockHorizontalScroll('left');
        lockDockHorizontalScroll('right');
        const newX = widget.position.x + delta.x;
        const newY = widget.position.y + delta.y;
        dragPositionRef.current = { x: newX, y: newY };

        const width = containerRef.current?.getBoundingClientRect().width ?? containerWidth;
        const snap = computeSnap(newX, newX + WIDGET_WIDTH, width, newY);
        const targetEdge = snap.edge ?? 'left';
        const contentDropY = toEdgeContentY(newY, targetEdge);
        const insertion = computeInsertion(id, targetEdge, contentDropY);
        const visualLineY = Math.max(0, insertion.lineY - getDockScrollTop(targetEdge));
        const prev = insertPreviewRef.current;
        if (
          !prev ||
          prev.edge !== targetEdge ||
          prev.lineY !== visualLineY ||
          prev.upperId !== insertion.upperId ||
          prev.lowerId !== insertion.lowerId
        ) {
          insertPreviewRef.current = {
            edge: targetEdge,
            lineY: visualLineY,
            upperId: insertion.upperId,
            lowerId: insertion.lowerId,
          };
        }
      }
    },
    [containerWidth, toEdgeContentY, computeInsertion, getDockScrollTop, lockDockHorizontalScroll]
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, delta } = event;
      const id = active.id as WidgetId;
      const state = useWidgetStore.getState();
      const widget = state.widgets[id];
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

      const targetEdge = snap.edge!;
      const contentDropY = toEdgeContentY(newY, targetEdge);
      const insertion = computeInsertion(id, targetEdge, contentDropY);

      // First, move widget to the actual drop position (position + delta).
      // This gives framer-motion the correct starting point for the snap
      // animation. recalculateStacks (next frame) will update to the final
      // stacked position, producing a smooth visual transition.
      moveWidget(id, { x: newX, y: newY });
      snapAndReorder(id, targetEdge, insertion.orderedIds);

      // Reset isDraggingRef BEFORE scheduling recalculateStacks so the
      // ResizeObserver guard won't block the recalculation.
      isDraggingRef.current = false;
      requestAnimationFrame(() => recalculateStacks());

      setDragging(false);
      dragPositionRef.current = null;
      dragSourceRef.current = null;
      insertPreviewRef.current = null;
    },
    [moveWidget, snapAndReorder, setDragging, recalculateStacks, toEdgeContentY, computeInsertion]
  );

  const handleDragCancel = useCallback(
    () => {
      isDraggingRef.current = false;
      setDragging(false);
      dragPositionRef.current = null;
      dragSourceRef.current = null;
      insertPreviewRef.current = null;
    },
    [setDragging]
  );

  return (
    <>
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
            isDragging={isDragging}
            dragPositionRef={dragPositionRef}
            insertPreviewRef={insertPreviewRef}
            containerRef={containerRef}
            containerWidth={containerWidth}
          />

          {/* Left Dock Layer — z-30 */}
          <div
            ref={leftDockRef}
            className="dock-scrollbar absolute inset-y-0 left-0 z-30 overflow-y-auto overflow-x-hidden"
            onScroll={() => lockDockHorizontalScroll('left')}
            data-testid="left-dock"
            style={{
              width: DOCK_SCROLL_WIDTH,
              bottom: dockBottomInsets.left,
              pointerEvents: 'none',
              overflowX: 'hidden',
              overscrollBehaviorX: 'none',
            }}
          >
            <div className="relative min-h-full" style={{ height: leftStackHeight }}>
              {leftRegistry.map((config) => {
                const ContentComponent = WIDGET_CONTENT_MAP[config.id];
                return (
                  <WidgetPanel
                    key={config.id}
                    widgetId={config.id}
                    titleKey={config.titleKey}
                    dockOffsetX={0}
                  >
                    <ContentComponent />
                  </WidgetPanel>
                );
              })}
            </div>
          </div>

          {/* Right Dock Layer — z-30 */}
          <div
            ref={rightDockRef}
            className="dock-scrollbar absolute inset-y-0 right-0 z-30 overflow-y-auto overflow-x-hidden"
            onScroll={() => lockDockHorizontalScroll('right')}
            data-testid="right-dock"
            style={{
              width: DOCK_SCROLL_WIDTH,
              bottom: dockBottomInsets.right,
              pointerEvents: 'none',
              overflowX: 'hidden',
              overscrollBehaviorX: 'none',
            }}
          >
            <div className="relative min-h-full" style={{ height: rightStackHeight }}>
              {rightRegistry.map((config) => {
                const ContentComponent = WIDGET_CONTENT_MAP[config.id];
                return (
                  <WidgetPanel
                    key={config.id}
                    widgetId={config.id}
                    titleKey={config.titleKey}
                    dockOffsetX={rightDockOffset}
                  >
                    <ContentComponent />
                  </WidgetPanel>
                );
              })}
            </div>
          </div>

          {/* DragOverlay — z-40 */}
          <DragOverlay>
            {activeWidgetId ? (
              <div
                className="z-40 rounded-xl shadow-2xl border border-white/30 backdrop-blur-xl bg-white/50 dark:bg-gray-900/50 opacity-80"
                style={{ width: WIDGET_WIDTH, height: COLLAPSED_HEIGHT }}
              >
                <div className="px-3 py-2 text-sm font-medium text-gray-600 dark:text-gray-300">
                  {t(WIDGET_REGISTRY.find((w) => w.id === activeWidgetId)?.titleKey ?? activeWidgetId)}
                </div>
              </div>
            ) : null}
          </DragOverlay>
        </div>
      </DndContext>
      {/* ColorWorkstation — fixed bottom center, outside DnD system (z-35) */}
      <ColorWorkstation ref={colorWorkstationRef} />
    </>
  );
}
