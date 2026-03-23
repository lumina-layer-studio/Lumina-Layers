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
import { COLLAPSED_HEIGHT, WIDGET_PANEL_RADIUS, WIDGET_WIDTH } from '../../utils/widgetUtils';
import type { WidgetId } from '../../types/widget';
import { useI18n } from '../../i18n/context';

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
        <WidgetErrorFallback onRetry={() => this.setState({ hasError: false })} />
      );
    }
    return this.props.children;
  }
}

function WidgetErrorFallback({ onRetry }: { onRetry: () => void }) {
  const { t } = useI18n();
  return (
    <div className="p-4 text-center text-sm text-red-500">
      <p>{t('widget_error')}</p>
      <button
        className="mt-2 px-3 py-1 text-xs bg-red-100 dark:bg-red-900/30 rounded hover:bg-red-200"
        onClick={onRetry}
      >
        {t('widget_retry')}
      </button>
    </div>
  );
}

// ===== WidgetPanel =====

interface WidgetPanelProps {
  widgetId: WidgetId;
  titleKey: string;
  children: ReactNode;
  dockOffsetX?: number;
  width?: number;
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
  dockOffsetX = 0,
  width = WIDGET_WIDTH,
}: WidgetPanelProps) {
  const widget = useWidgetStore((s) => s.widgets[widgetId]);
  const toggleCollapse = useWidgetStore((s) => s.toggleCollapse);
  const setExpandedHeight = useWidgetStore((s) => s.setExpandedHeight);
  const isActiveDragWidget = useWidgetStore((s) => s.activeWidgetId === widgetId);
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

  const isBeingDragged = isActiveDragWidget && !!transform;
  const targetHeight = isBeingDragged
    ? COLLAPSED_HEIGHT
    : (widget.collapsed ? COLLAPSED_HEIGHT : widget.expandedHeight);
  const localLeft = widget.position.x - dockOffsetX;

  // Always set left/top in style so framer-motion has a stable base.
  // During drag: dnd-kit transform is layered on top via CSS transform.
  // After drag: framer-motion animates left/top from current to target.
  //
  // IMPORTANT: We do NOT set left/top in style — framer-motion owns them
  // exclusively via `animate`. During drag we still feed the visual position
  // (base + delta) into animate so framer-motion tracks the value; this way,
  // when drag ends and the target switches to the stacked position, framer
  // interpolates smoothly from the drop point instead of jumping from 0.
  const style: React.CSSProperties = {
    position: 'absolute',
    width,
    borderRadius: WIDGET_PANEL_RADIUS,
    pointerEvents: isBeingDragged ? 'none' : 'auto',
    zIndex: isBeingDragged ? 50 : 30,
    overflow: 'hidden',
    contain: 'layout style',
    ...(isBeingDragged ? { opacity: 0 } : {}),
  };

  // During drag, include dnd transform in animate target so framer-motion
  // tracks the *visual* position (even while hidden). This avoids stale
  // motion values that can cause drop animation to start from dock top.
  const animateTarget = isBeingDragged
    ? {
        left: localLeft + (transform?.x ?? 0),
        top: widget.position.y + (transform?.y ?? 0),
        height: targetHeight,
      }
    : {
        left: localLeft,
        top: widget.position.y,
        height: targetHeight,
      };

  // During drag, use instant transitions for left/top so the widget
  // follows the cursor without lag. Normal transitions resume after drop.
  const transition = isBeingDragged
    ? {
        left: { duration: 0 },
        top: { duration: 0 },
        height: TRANSITION_CONFIG.height,
      }
    : TRANSITION_CONFIG;

  return (
      <motion.div
        ref={setNodeRef}
        initial={false}
        style={style}
        data-widget-id={widgetId}
        animate={animateTarget}
        transition={transition}
        onAnimationComplete={handleAnimationComplete}
        className={`border border-slate-200/80 shadow-[var(--shadow-control)] will-change-transform ${
          enableBlur
            ? 'bg-slate-50/92 backdrop-blur-[2px] dark:bg-slate-950/92'
            : 'bg-slate-50/98 dark:bg-slate-950/98'
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
          onPointerDown={(e) => e.stopPropagation()}
          style={{
            height: widget.collapsed || isBeingDragged ? 0 : 'auto',
            overflow: 'hidden',
            ...(widget.collapsed || isBeingDragged
              ? { visibility: 'hidden' as const, contentVisibility: 'hidden' as const }
              : {}),
          }}
        >
          <WidgetErrorBoundary widgetId={widgetId}>
            {children}
          </WidgetErrorBoundary>
        </div>
      </motion.div>
  );
});
