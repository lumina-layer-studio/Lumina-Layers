import { memo, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useI18n } from "../../i18n/context";
import { calibrationPreview, type LutBoardPreview } from "../../utils/calibrationPreview";
import { calibrationCardTexture, cardPair, lutBoardTexture, lutFace, lutStack, materialFaces, type CardFootprint } from "../../utils/calibrationCardArtwork";
import { ChevronLeft, ChevronRight } from "./icons";
import "./CalibrationThumbnail.css";

export interface CalibrationThumbnailProps {
  kind: "materials" | "luts";
  rgb?: unknown;
  mode?: string | null;
  name?: string | null;
  display?: Record<string, unknown> | null;
  metadata?: Record<string, unknown> | null;
  size?: "sm" | "md" | "lg";
  resourceKey?: string;
  loading?: boolean;
}

type ThumbnailProps = CalibrationThumbnailProps & { renderDetails?: (controls: ReactNode) => ReactNode };

const sizeClass = { sm: "h-10 w-10", md: "h-14 w-14", lg: "h-24 w-24" };
const pixels = { sm: 40, md: 56, lg: 96 };
const boardPercent = (mm: number) => `${100 * mm / cardPair.size}%`;
const boardSwapMs = 360;

function CardEdges({ faces, depth }: { faces: readonly CardFootprint[]; depth: number }) {
  return faces.map(({ x, y, width, height, light }) => (
    <span key={x} aria-hidden="true" className={`calibration-edge-frame ${light ? "is-white" : ""}`}
      style={{
        top: boardPercent(y), left: boardPercent(x),
        width: boardPercent(width), height: boardPercent(height),
        "--edge-width": `${100 * depth / width}%`,
        "--edge-height": `${100 * depth / height}%`,
      } as CSSProperties}>
      <i className="calibration-edge-left" /><i className="calibration-edge-right" />
      <i className="calibration-edge-top" /><i className="calibration-edge-bottom" />
    </span>
  ));
}

function boardName(t: (key: string) => string, board: LutBoardPreview, page: number): string {
  if (board.family === "five") return t(page === 1 ? "resources_lut_base_board" : "resources_lut_extension_board");
  if (board.family === "eight") return t("resources_lut_letter_board").replace("{letter}", page === 1 ? "A" : "B");
  return t("resources_lut_numbered_board").replace("{page}", String(page)).replace("{total}", String(board.setSize));
}

function Thumbnail({
  kind, rgb, mode, name, display, metadata, size = "md", renderDetails, loading = false,
}: ThumbnailProps) {
  const { t, lang } = useI18n();
  const frameRef = useRef<HTMLSpanElement>(null);
  const planeRef = useRef<HTMLSpanElement>(null);
  const [hovered, setHovered] = useState(false);
  const [selectedPage, setSelectedPage] = useState(0);
  const [swapping, setSwapping] = useState(false);
  const preview = useMemo(() => calibrationPreview({ kind, rgb, mode, name, display, metadata }),
    [kind, rgb, mode, name, display, metadata]);
  const board = preview.lutBoard;
  const pageIndex = size === "lg" && board ? Math.min(selectedPage, board.pages.length - 1) : 0;
  const page = board?.pages[pageIndex];
  const dualBoard = size === "lg" && board?.pages.length === 2;
  const stacked = size !== "lg" && (board?.pages.length ?? 0) > 1;
  const missingBoard = kind === "luts" && !board;
  const faces = kind === "materials" ? materialFaces : stacked ? lutStack : lutFace;
  const texture = useMemo(() => kind === "luts" ? board && lutBoardTexture(preview, pageIndex, stacked) : calibrationCardTexture(preview),
    [kind, board, preview, pageIndex, stacked]);
  const deckTextures = useMemo(() => dualBoard ? [0, 1].map((index) => lutBoardTexture(preview, index, false)) : [],
    [dualBoard, preview]);

  useEffect(() => {
    if (!swapping) return;
    // One finite timer also releases the interaction if a hidden tab cancels CSS animation.
    const timer = window.setTimeout(() => setSwapping(false), boardSwapMs);
    return () => window.clearTimeout(timer);
  }, [swapping]);

  useEffect(() => {
    const frame = frameRef.current;
    const plane = planeRef.current;
    if (!frame || !plane) return;
    // Listen across the row, but rotate around the thumbnail's own center.
    const target = frame.closest<HTMLElement>("button, [data-calibration-hover]") ?? frame;
    let pending: number | null = null;
    let x = 0, y = 0;

    const move = (event: PointerEvent) => {
      if (event.pointerType !== "mouse") return;
      x = event.clientX;
      y = event.clientY;
      if (pending !== null) return;
      pending = requestAnimationFrame(() => {
        pending = null;
        // The frame stays flat while its child plane tilts, so these bounds are stable.
        const box = frame.getBoundingClientRect();
        if (!box.width || !box.height) return;
        const axis = (offset: number, extent: number) => Math.max(-1, Math.min(1, 2 * offset / extent - 1));
        // Positive CSS Z points toward the viewer: lift the edge nearest the pointer.
        const pitch = 20 * axis(y - box.top, box.height);
        const yaw = -30 * axis(x - box.left, box.width);
        plane.style.transform = `perspective(var(--calibration-perspective)) rotateX(${pitch.toFixed(2)}deg) rotateY(${yaw.toFixed(2)}deg)`;
      });
    };

    const release = () => {
      if (pending !== null) cancelAnimationFrame(pending);
      pending = null;
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerleave", leave);
      target.removeEventListener("pointercancel", leave);
      window.removeEventListener("blur", leave);
      plane.style.removeProperty("transform");
    };
    function leave() {
      release();
      setHovered(false);
    }
    function enter(event: PointerEvent) {
      if (event.pointerType !== "mouse") return;
      setHovered(true);
      target.addEventListener("pointermove", move, { passive: true });
      target.addEventListener("pointerleave", leave);
      target.addEventListener("pointercancel", leave);
      window.addEventListener("blur", leave);
      move(event);
    }
    target.addEventListener("pointerenter", enter, { passive: true });
    return () => {
      target.removeEventListener("pointerenter", enter);
      release();
    };
  }, [missingBoard]);

  const boardTitle = board && page ? boardName(t, board, page.number) : "";
  let caption: string;
  if (kind === "materials") {
    caption = t(preview.kind === "measured" ? "resources_thumbnail_caption_measured"
      : preview.kind === "illustrative" ? "resources_thumbnail_caption_illustrative"
        : "resources_thumbnail_caption_unknown");
  } else if (board && page) {
    caption = board.family === "index" ? t("resources_lut_recipe_overview") : board.setSize > 1 ? boardTitle : t("resources_lut_calibration_board");
  } else {
    caption = t(loading ? "resources_lut_loading_board" : "resources_lut_no_board");
  }
  const largeLut = size === "lg" && kind === "luts";
  const resolution = largeLut ? 128 : pixels[size];
  const frameSize = largeLut ? "h-28 w-28 sm:h-32 sm:w-32" : sizeClass[size];
  const switchLabel = dualBoard ? t("resources_lut_flip_board")
    .replace("{current}", boardTitle).replace("{next}", boardName(t, board, board.pages[1 - pageIndex].number)) : "";
  const plane = <span ref={planeRef} className={`calibration-plane${hovered ? " is-tilting" : ""}`}>
    {dualBoard ? board.pages.map((p, index) => (
      <span key={p.number} className={`calibration-deck-card ${index === pageIndex ? "is-front" : "is-back"}${swapping ? " is-swapping" : ""}`}>
        {hovered && <CardEdges faces={lutFace} depth={.85} />}
        <img src={deckTextures[index]} alt={index === pageIndex ? caption : ""} aria-hidden={index !== pageIndex}
          width={resolution} height={resolution} decoding="async" draggable={false} className="block h-full w-full" />
      </span>
    )) : <>
      {hovered && <CardEdges faces={faces} depth={kind === "luts" ? .85 : preview.boardThicknessMm ?? 2} />}
      <img src={texture} alt={size === "lg" ? caption : ""} aria-hidden={size !== "lg"}
        width={resolution} height={resolution} decoding="async" loading={size === "lg" ? "eager" : "lazy"}
        draggable={false} className="block h-full w-full" />
    </>}
  </span>;
  const image = missingBoard ? (size === "lg" && !loading ? null : (
    <span className={`${frameSize} flex shrink-0 items-center justify-center text-xs text-[var(--surface-text-muted)]`}>
      {loading ? "…" : t("resources_lut_no_preview_short")}
    </span>
  )) : (
    <span ref={frameRef}
      style={{ "--calibration-perspective": `${resolution * 4}px`, "--calibration-swap-duration": `${boardSwapMs}ms` } as CSSProperties}
      className={`calibration-thumbnail ${frameSize} relative block shrink-0 select-none`}>
      {dualBoard ? <button type="button" aria-label={switchLabel} className="calibration-deck-button"
        onClick={() => {
          if (swapping) return;
          setSelectedPage(1 - pageIndex);
          setSwapping(true);
        }}>{plane}</button> : plane}
    </span>
  );
  if (size !== "lg") return image;
  if (kind === "materials") return <><div className="flex shrink-0 flex-col items-center gap-1">{image}
    <span className="text-xs text-slate-500 dark:text-slate-400">{caption}</span>
  </div>{renderDetails?.(null)}</>;

  const controls = <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1">
    {board && board.pages.length > 2 ? (
      <div role="group" aria-label={t("resources_lut_switch_board")} className="calibration-page-options">
        <button type="button" aria-label={t("resources_lut_previous_board")} disabled={pageIndex === 0} onClick={() => setSelectedPage(pageIndex - 1)}><ChevronLeft /></button>
        <span aria-live="polite" className="self-center text-xs tabular-nums">{page?.number} / {board.setSize}</span>
        <button type="button" aria-label={t("resources_lut_next_board")} disabled={pageIndex === board.pages.length - 1} onClick={() => setSelectedPage(pageIndex + 1)}><ChevronRight /></button>
      </div>
    ) : !dualBoard && (!page || (board && (board.setSize > 1 || board.family === "index"))) &&
      <span className="text-xs text-slate-500 dark:text-slate-400">{caption}</span>}
    {page && <span aria-live="polite" className="text-xs tabular-nums text-slate-500 dark:text-slate-400">
      {dualBoard && `${boardTitle} · `}
      {t("resources_lut_recipe_count").replace("{count}", page.count.toLocaleString(lang))}
    </span>}
  </div>;
  return <>{image}{renderDetails ? renderDetails(controls) : controls}</>;
}

const CalibrationThumbnail = memo(function CalibrationThumbnail(props: ThumbnailProps) {
  return <Thumbnail key={props.resourceKey ?? props.name ?? props.kind} {...props} />;
});

export default CalibrationThumbnail;
