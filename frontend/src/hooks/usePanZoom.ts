import { useState, useRef, useCallback, type MouseEvent } from "react";

const MIN_SCALE = 0.1;
const MAX_SCALE = 20;

function clampScale(value: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, value));
}

export function usePanZoom() {
  const scaleRef = useRef(1);
  const translateRef = useRef({ x: 0, y: 0 });
  const draggingRef = useRef(false);
  const dragStartRef = useRef({ x: 0, y: 0 });
  const dragTranslateRef = useRef({ x: 0, y: 0 });

  const [, setTick] = useState(0);
  const rerender = useCallback(() => setTick((v) => v + 1), []);

  const zoom = useCallback(
    (mouseX: number, mouseY: number, deltaY: number) => {
      const prev = scaleRef.current;
      const next = clampScale(prev * (deltaY > 0 ? 0.9 : 1.1));
      if (next === prev) return;

      const ratio = next / prev;
      const t = translateRef.current;
      scaleRef.current = next;
      translateRef.current = {
        x: mouseX - (mouseX - t.x) * ratio,
        y: mouseY - (mouseY - t.y) * ratio,
      };
      rerender();
    },
    [rerender],
  );

  const handleMouseDown = useCallback(
    (e: MouseEvent<HTMLDivElement>) => {
      e.preventDefault();
      draggingRef.current = true;
      dragStartRef.current = { x: e.clientX, y: e.clientY };
      dragTranslateRef.current = { ...translateRef.current };
    },
    [],
  );

  const handleMouseMove = useCallback(
    (e: MouseEvent<HTMLDivElement>) => {
      if (!draggingRef.current) return;
      translateRef.current = {
        x: dragTranslateRef.current.x + (e.clientX - dragStartRef.current.x),
        y: dragTranslateRef.current.y + (e.clientY - dragStartRef.current.y),
      };
      rerender();
    },
    [rerender],
  );

  const handleMouseUp = useCallback(() => {
    draggingRef.current = false;
  }, []);

  const reset = useCallback(() => {
    scaleRef.current = 1;
    translateRef.current = { x: 0, y: 0 };
    rerender();
  }, [rerender]);

  return {
    scale: scaleRef.current,
    translate: translateRef.current,
    zoom,
    reset,
    mouseHandlers: {
      onMouseDown: handleMouseDown,
      onMouseMove: handleMouseMove,
      onMouseUp: handleMouseUp,
      onMouseLeave: handleMouseUp,
    },
  };
}
