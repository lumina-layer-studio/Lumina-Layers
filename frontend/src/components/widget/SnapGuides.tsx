/**
 * Snap guide lines rendered during widget drag near screen edges.
 * Uses RAF polling of refs to avoid re-renders from parent state changes.
 * 拖拽 Widget 接近屏幕边缘时渲染的吸附引导线。
 * 通过 RAF 轮询 ref 避免父组件 state 变化导致的重渲染。
 */

import { useState, useEffect } from 'react';
import type { RefObject } from 'react';
import { SNAP_THRESHOLD, WIDGET_WIDTH } from '../../utils/widgetUtils';

interface SnapGuidesProps {
  isDraggingRef: RefObject<boolean>;
  dragPositionRef: RefObject<{ x: number; y: number } | null>;
  containerRef: RefObject<HTMLDivElement | null>;
}

export function SnapGuides({ isDraggingRef, dragPositionRef, containerRef }: SnapGuidesProps) {
  const [guides, setGuides] = useState<{ nearLeft: boolean; nearRight: boolean }>({
    nearLeft: false,
    nearRight: false,
  });

  useEffect(() => {
    let rafId: number;
    const tick = () => {
      const pos = dragPositionRef.current;
      const container = containerRef.current;
      if (isDraggingRef.current && pos && container) {
        const containerWidth = container.getBoundingClientRect().width;
        const nearLeft = pos.x < SNAP_THRESHOLD;
        const nearRight = containerWidth - (pos.x + WIDGET_WIDTH) < SNAP_THRESHOLD;
        setGuides((prev) => {
          if (prev.nearLeft === nearLeft && prev.nearRight === nearRight) return prev;
          return { nearLeft, nearRight };
        });
      } else {
        setGuides((prev) => {
          if (!prev.nearLeft && !prev.nearRight) return prev;
          return { nearLeft: false, nearRight: false };
        });
      }
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [isDraggingRef, dragPositionRef, containerRef]);

  if (!guides.nearLeft && !guides.nearRight) return null;

  return (
    <div className="absolute inset-0 z-20 pointer-events-none">
      {guides.nearLeft && (
        <div
          className="absolute left-0 top-0 bottom-0 w-0.5 bg-blue-400/60 shadow-[0_0_8px_rgba(59,130,246,0.5)]"
        />
      )}
      {guides.nearRight && (
        <div
          className="absolute right-0 top-0 bottom-0 w-0.5 bg-blue-400/60 shadow-[0_0_8px_rgba(59,130,246,0.5)]"
        />
      )}
    </div>
  );
}
