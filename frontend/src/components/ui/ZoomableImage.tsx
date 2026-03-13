import { useState, useRef, useCallback, type WheelEvent, type MouseEvent } from "react";
import { useI18n } from "../../i18n/context";

/** Clamp scale to the allowed zoom range [0.5, 5.0]. */
export function clampScale(value: number): number {
  return Math.min(5.0, Math.max(0.5, value));
}

/**
 * Compute the new translate after a zoom so the point under the cursor stays stationary.
 *
 * Formula: newTranslate = mousePos - (mousePos - oldTranslate) * (newScale / oldScale)
 */
export function computeZoomTranslate(
  mousePos: { x: number; y: number },
  oldTranslate: { x: number; y: number },
  oldScale: number,
  newScale: number,
): { x: number; y: number } {
  const ratio = newScale / oldScale;
  return {
    x: mousePos.x - (mousePos.x - oldTranslate.x) * ratio,
    y: mousePos.y - (mousePos.y - oldTranslate.y) * ratio,
  };
}

interface ZoomableImageProps {
  src: string;
  alt: string;
  className?: string;
}

export default function ZoomableImage({ src, alt, className }: ZoomableImageProps) {
  const { t } = useI18n();
  const [scale, setScale] = useState(1);
  const [translate, setTranslate] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const dragStart = useRef({ x: 0, y: 0 });
  const translateAtDragStart = useRef({ x: 0, y: 0 });

  const resetZoom = useCallback(() => {
    setScale(1);
    setTranslate({ x: 0, y: 0 });
  }, []);

  const handleWheel = useCallback(
    (e: WheelEvent<HTMLDivElement>) => {
      e.preventDefault();
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;

      const mousePos = {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
      };

      const newScale = clampScale(scale * (1 - e.deltaY * 0.001));
      const newTranslate = computeZoomTranslate(mousePos, translate, scale, newScale);

      setScale(newScale);
      setTranslate(newTranslate);
    },
    [scale, translate],
  );

  const handleMouseDown = useCallback(
    (e: MouseEvent<HTMLDivElement>) => {
      e.preventDefault();
      setIsDragging(true);
      dragStart.current = { x: e.clientX, y: e.clientY };
      translateAtDragStart.current = { ...translate };
    },
    [translate],
  );

  const handleMouseMove = useCallback(
    (e: MouseEvent<HTMLDivElement>) => {
      if (!isDragging) return;
      const dx = e.clientX - dragStart.current.x;
      const dy = e.clientY - dragStart.current.y;
      setTranslate({
        x: translateAtDragStart.current.x + dx,
        y: translateAtDragStart.current.y + dy,
      });
    },
    [isDragging],
  );

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  return (
    <div className={`relative ${className ?? ""}`}>
      <div
        ref={containerRef}
        className="overflow-hidden cursor-grab active:cursor-grabbing"
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        <img
          src={src}
          alt={alt}
          draggable={false}
          className="w-full select-none"
          style={{
            transform: `translate(${translate.x}px, ${translate.y}px) scale(${scale})`,
            transformOrigin: "0 0",
          }}
        />
      </div>
      <button
        type="button"
        onClick={resetZoom}
        className="absolute top-2 right-2 rounded bg-black/30 dark:bg-black/60 px-2 py-1 text-xs text-white hover:bg-black/50 dark:hover:bg-black/80 transition-colors"
      >
        {t("zoom_reset")}
      </button>
    </div>
  );
}
