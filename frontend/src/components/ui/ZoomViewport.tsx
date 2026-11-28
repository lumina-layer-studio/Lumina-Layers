import { useRef, useEffect, type MouseEvent, type ReactNode } from "react";
import { wheelZoomDelta } from "../../utils/wheelZoom";

interface ZoomViewportProps {
  src?: string;
  alt?: string;
  /**
   * 对比图路径。与 ``comparisonSplit`` 一起使用时，对比图叠加在同一视口里，
   * 只在分割线右侧绘制（左侧保留主图），用于拖动滑条对比原图与矢量化结果。
   */
  comparisonSrc?: string;
  comparisonAlt?: string;
  /** 分割位置占视口宽度的比例（0–1）；``null`` 关闭对比。 */
  comparisonSplit?: number | null;
  scale: number;
  translate: { x: number; y: number };
  zoom: (mouseX: number, mouseY: number, deltaY: number) => void;
  mouseHandlers: {
    onMouseDown: (e: MouseEvent<HTMLDivElement>) => void;
    onMouseMove: (e: MouseEvent<HTMLDivElement>) => void;
    onMouseUp: () => void;
    onMouseLeave: () => void;
  };
  height?: number;
  children?: ReactNode;
}

export default function ZoomViewport({
  src,
  alt = "",
  comparisonSrc,
  comparisonAlt = "",
  comparisonSplit = null,
  scale,
  translate,
  zoom,
  mouseHandlers,
  height = 400,
  children,
}: ZoomViewportProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const rect = el.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      zoomRef.current(mouseX, mouseY, wheelZoomDelta(e.deltaY, e.deltaMode, rect.height));
    };
    el.addEventListener("wheel", handler, { passive: false });
    return () => el.removeEventListener("wheel", handler);
  }, []);

  const transformStyle = {
    transform: `translate(${translate.x}px, ${translate.y}px) scale(${scale})`,
    transformOrigin: "0 0",
  };
  const comparisonVisible = Boolean(comparisonSrc) && comparisonSplit !== null;
  const comparisonPercent = comparisonSplit === null
    ? 0
    : Math.min(100, Math.max(0, comparisonSplit * 100));

  return (
    <div
      ref={containerRef}
      className="relative w-full overflow-hidden rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 cursor-grab active:cursor-grabbing select-none"
      style={{ height }}
      {...mouseHandlers}
    >
      {src && (
        <img
          src={src}
          alt={alt}
          draggable={false}
          className="absolute top-0 left-0 w-full h-full object-contain pointer-events-none"
          style={transformStyle}
        />
      )}
      {comparisonVisible && (
        <div
          className="pointer-events-none absolute inset-0"
          data-testid="zoom-viewport-comparison"
          style={{ clipPath: `inset(0 0 0 ${comparisonPercent}%)` }}
        >
          <img
            src={comparisonSrc}
            alt={comparisonAlt}
            draggable={false}
            className="absolute top-0 left-0 w-full h-full object-contain pointer-events-none"
            style={transformStyle}
          />
        </div>
      )}
      {children}
    </div>
  );
}
