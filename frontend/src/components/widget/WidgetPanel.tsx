/**
 * Widget panel component with drag, collapse animation, and frosted glass effect.
 * Widget 面板组件，支持拖拽、折叠动画和毛玻璃效果。
 *
 * Uses ResizeObserver on the content area to measure expanded height.
 * Content is always in the DOM but hidden via height:0 when collapsed,
 * allowing scrollHeight measurement without double-instantiating children.
 * 使用 ResizeObserver 在内容区域测量展开高度。
 * 折叠时内容始终保留在 DOM 中（height:0），避免双重实例化子组件。
 */

import React, { Component, useCallback, useEffect, useRef, type ReactNode } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { motion } from 'framer-motion';
import { WidgetHeader } from './WidgetHeader';
import { useWidgetStore } from '../../stores/widgetStore';
import { useSettingsStore } from '../../stores/settingsStore';
import { COLLAPSED_HEIGHT, WIDGET_WIDTH } from '../../utils/widgetUtils';
import type { WidgetId } from '../../types/widget';

// ===== ErrorBoundary =====

interface ErrorBoundaryProps {
  children: ReactNode;
  widgetId: WidgetId;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

class WidgetErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="p-4 text-center text-sm text-red-500">
          <p>Widget error</p>
          <button
            className="mt-2 px-3 py-1 text-xs bg-red-100 dark:bg-red-900/30 rounded hover:bg-red-200"
            onClick={() => this.setState({ hasError: false })}
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

// ===== WidgetPanel =====

interface WidgetPanelProps {
  widgetId: WidgetId;
  titleKey: string;
  children: ReactNode;
}

/**
 * Per-property transition config for snappy widget animations.
 * 分属性过渡配置，实现快速响应的 Widget 动画。
 *
 * - left/top: fast ease-out tween for position shifts (被挤走时快速滑动)
 * - height: stiff spring for expand/collapse (展开/折叠用硬弹簧)
 */
const TRANSITION_CONFIG = {
  left: { type: 'tween' as const, duration: 0.2, ease: 'easeOut' as const },
  top: { type: 'tween' as const, duration: 0.2, ease: 'easeOut' as const },
  height: { type: 'tween' as const, duration: 0.2, ease: 'easeOut' as const },
};

export const WidgetPanel = React.memo(function WidgetPanel({
  widgetId,
  titleKey,
  children,
}: WidgetPanelProps) {
  const widget = useWidgetStore((s) => s.widgets[widgetId]);
  const toggleCollapse = useWidgetStore((s) => s.toggleCollapse);
  const setExpandedHeight = useWidgetStore((s) => s.setExpandedHeight);
  const activeWidgetId = useWidgetStore((s) => s.activeWidgetId);
  const enableBlur = useSettingsStore((s) => s.enableBlur);

  // Content area ref — used by ResizeObserver to measure expanded height
  const contentRef = useRef<HTMLDivElement>(null);

  const { attributes, listeners, setNodeRef, transform } = useDraggable({
    id: widgetId,
  });

  // Dispatch custom event when height animation completes so workspace
  // can do a final recalculation with accurate DOM heights.
  const handleAnimationComplete = useCallback(() => {
    window.dispatchEvent(new CustomEvent('widget-animation-complete'));
  }, []);

  // Measure content height via ResizeObserver on the visible content area.
  // Content is always in the DOM (hidden via height:0 when collapsed),
  // so scrollHeight remains measurable without a separate hidden div.
  useEffect(() => {
    const el = contentRef.current;
    if (!el) return;

    const update = () => {
      const h = el.scrollHeight;
      if (h > 0) setExpandedHeight(widgetId, COLLAPSED_HEIGHT + h);
    };

    // Initial measurement
    update();

    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [widgetId, setExpandedHeight]);

  if (!widget.visible) return null;

  const isBeingDragged = activeWidgetId === widgetId && !!transform;
  const targetHeight = widget.collapsed ? COLLAPSED_HEIGHT : widget.expandedHeight;

  // During drag, pin left/top in style so dnd-kit transform works correctly.
  // When not dragging, framer-motion animates left/top for smooth repositioning.
  const style: React.CSSProperties = {
    position: 'absolute',
    width: WIDGET_WIDTH,
    pointerEvents: 'auto',
    zIndex: isBeingDragged ? 50 : 30,
    ...(isBeingDragged
      ? {
          left: widget.position.x,
          top: widget.position.y,
          transform: `translate(${transform.x}px, ${transform.y}px)`,
        }
      : {}),
  };

  return (
      <motion.div
        ref={setNodeRef}
        style={style}
        data-widget-id={widgetId}
        animate={
          isBeingDragged
            ? { height: targetHeight }
            : {
                left: widget.position.x,
                top: widget.position.y,
                height: targetHeight,
              }
        }
        transition={TRANSITION_CONFIG}
        onAnimationComplete={handleAnimationComplete}
        className={`rounded-xl shadow-lg border border-white/20 dark:border-gray-700/50 overflow-hidden will-change-transform ${
          enableBlur
            ? 'backdrop-blur-xl bg-white/70 dark:bg-gray-900/70'
            : 'bg-gray-100/95 dark:bg-gray-900/95'
        }`}
      >
        <WidgetHeader
          widgetId={widgetId}
          titleKey={titleKey}
          collapsed={widget.collapsed}
          onToggleCollapse={() => toggleCollapse(widgetId)}
          dragListeners={listeners}
          dragAttributes={attributes}
        />
        <div
          ref={contentRef}
          className="overflow-hidden"
          onPointerDown={(e) => e.stopPropagation()}
          style={{
            height: widget.collapsed ? 0 : 'auto',
            overflow: 'hidden',
            visibility: widget.collapsed ? 'hidden' : 'visible',
          }}
        >
          <WidgetErrorBoundary widgetId={widgetId}>
            {children}
          </WidgetErrorBoundary>
        </div>
      </motion.div>
  );
});
