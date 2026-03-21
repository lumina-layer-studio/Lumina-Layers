import { useRef, useEffect, useCallback, useState } from "react";
import { useExtractorStore } from "../stores/extractorStore";
import { ExtractorColorMode } from "../api/types";
import { useI18n } from "../i18n/context";

// ========== Corner Labels Mapping (exported for testing) ==========

export const CORNER_LABELS: Record<string, string[]> = {
  "BW (Black & White)": [
    "白色 (左上) / White (TL)",
    "黑色 (右上) / Black (TR)",
    "黑色 (右下) / Black (BR)",
    "黑色 (左下) / Black (BL)",
  ],
  "4-Color": [
    "白色 (左上) / White (TL)",
    "青色 (右上) / Cyan (TR)",
    "品红 (右下) / Magenta (BR)",
    "黄色 (左下) / Yellow (BL)",
  ],
  "6-Color (Smart 1296)": [
    "白色 (左上) / White (TL)",
    "青色 (右上) / Cyan (TR)",
    "品红 (右下) / Magenta (BR)",
    "黄色 (左下) / Yellow (BL)",
  ],
  "8-Color Max": ["TL", "TR", "BR", "BL"],
  "5-Color Extended": [
    "白色 (左上) / White (TL)",
    "红色 (右上) / Red (TR)",
    "黑色 (右下) / Black (BR)",
    "黄色 (左下) / Yellow (BL)",
  ],
};

// ========== Coordinate Conversion (exported for testing) ==========

export function canvasClickToImageCoord(
  event: React.MouseEvent<HTMLCanvasElement>,
  canvas: HTMLCanvasElement,
  imageWidth: number,
  imageHeight: number
): [number, number] {
  const rect = canvas.getBoundingClientRect();
  const scaleX = imageWidth / rect.width;
  const scaleY = imageHeight / rect.height;
  const x = Math.round((event.clientX - rect.left) * scaleX);
  const y = Math.round((event.clientY - rect.top) * scaleY);
  return [x, y];
}

// ========== Corner marker drawing constants ==========

const MARKER_RADIUS = 8;
const MARKER_FONT = "bold 12px sans-serif";
const MARKER_FILL = "rgba(255, 50, 50, 0.85)";
const MARKER_STROKE = "#ffffff";
const MARKER_TEXT_COLOR = "#ffffff";

// ========== Helper: draw image + corner markers on canvas ==========

function drawCanvas(
  ctx: CanvasRenderingContext2D,
  img: HTMLImageElement,
  corners: Array<[number, number]>
): void {
  const { width, height } = ctx.canvas;
  ctx.clearRect(0, 0, width, height);
  ctx.drawImage(img, 0, 0, width, height);

  // Draw each corner marker
  corners.forEach(([ix, iy], idx) => {
    // Convert image coords → canvas coords
    const cx = (ix / img.naturalWidth) * width;
    const cy = (iy / img.naturalHeight) * height;

    // Circle
    ctx.beginPath();
    ctx.arc(cx, cy, MARKER_RADIUS, 0, Math.PI * 2);
    ctx.fillStyle = MARKER_FILL;
    ctx.fill();
    ctx.strokeStyle = MARKER_STROKE;
    ctx.lineWidth = 2;
    ctx.stroke();

    // Number label
    ctx.fillStyle = MARKER_TEXT_COLOR;
    ctx.font = MARKER_FONT;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(String(idx + 1), cx, cy);
  });
}

// ========== LUT grid size per color mode ==========

export const LUT_GRID_SIZE: Record<string, number> = {
  [ExtractorColorMode.BW]: 6,
  [ExtractorColorMode.FOUR_COLOR]: 32,
  [ExtractorColorMode.SIX_COLOR]: 36,
  [ExtractorColorMode.EIGHT_COLOR]: 37,
  [ExtractorColorMode.FIVE_COLOR_EXT]: 38,
};

// ========== Component ==========

export default function ExtractorCanvas() {
  const { t } = useI18n();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);

  const imagePreviewUrl = useExtractorStore((s) => s.imagePreviewUrl);
  const imageNaturalWidth = useExtractorStore((s) => s.imageNaturalWidth);
  const imageNaturalHeight = useExtractorStore((s) => s.imageNaturalHeight);
  const corner_points = useExtractorStore((s) => s.corner_points);
  const color_mode = useExtractorStore((s) => s.color_mode);
  const warp_view_url = useExtractorStore((s) => s.warp_view_url);
  const lut_preview_url = useExtractorStore((s) => s.lut_preview_url);
  const addCornerPoint = useExtractorStore((s) => s.addCornerPoint);

  const submitManualFix = useExtractorStore((s) => s.submitManualFix);
  const manualFixLoading = useExtractorStore((s) => s.manualFixLoading);

  // ---------- Manual fix state: selected cell + color picker ----------
  const [selectedCell, setSelectedCell] = useState<[number, number] | null>(null);
  const [fixColor, setFixColor] = useState("#000000");
  const lutPreviewRef = useRef<HTMLImageElement>(null);

  // ---------- Load image into off-screen Image object ----------
  useEffect(() => {
    if (!imagePreviewUrl) {
      imageRef.current = null;
      return;
    }
    const img = new Image();
    img.onload = () => {
      imageRef.current = img;
      // Trigger initial draw
      const canvas = canvasRef.current;
      if (canvas) {
        const ctx = canvas.getContext("2d");
        if (ctx) drawCanvas(ctx, img, corner_points);
      }
    };
    img.src = imagePreviewUrl;
  }, [imagePreviewUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------- Redraw when natural dimensions arrive or corners change ----------
  useEffect(() => {
    const canvas = canvasRef.current;
    const img = imageRef.current;
    if (!canvas || !img || !imageNaturalWidth || !imageNaturalHeight) return;
    const ctx = canvas.getContext("2d");
    if (ctx) drawCanvas(ctx, img, corner_points);
  }, [corner_points, imageNaturalWidth, imageNaturalHeight]);

  // ---------- Canvas click handler ----------
  const handleCanvasClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas || !imageNaturalWidth || !imageNaturalHeight) return;
      if (corner_points.length >= 4) return;

      const [x, y] = canvasClickToImageCoord(
        e,
        canvas,
        imageNaturalWidth,
        imageNaturalHeight
      );
      addCornerPoint([x, y]);
    },
    [imageNaturalWidth, imageNaturalHeight, corner_points.length, addCornerPoint]
  );

  // ---------- Derive hint text ----------
  const cornerCount = corner_points.length;
  const labels = CORNER_LABELS[color_mode] ?? CORNER_LABELS["4-Color"];
  const hintText =
    cornerCount >= 4
      ? t("ext_canvas_positioning_done")
      : t("ext_canvas_click_corner").replace("{n}", String(cornerCount + 1)).replace("{label}", labels[cornerCount]);

  // ---------- LUT preview click handler (for manual fix) ----------
  const handleLutPreviewClick = useCallback(
    (e: React.MouseEvent<HTMLImageElement>) => {
      const img = lutPreviewRef.current;
      if (!img) return;
      const rect = img.getBoundingClientRect();
      const gridSize = LUT_GRID_SIZE[color_mode] ?? 32;
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const col = Math.min(Math.floor((x / rect.width) * gridSize), gridSize - 1);
      const row = Math.min(Math.floor((y / rect.height) * gridSize), gridSize - 1);
      setSelectedCell([row, col]);
    },
    [color_mode]
  );

  const handleFixSubmit = useCallback(() => {
    if (!selectedCell) return;
    void submitManualFix(selectedCell[0], selectedCell[1], fixColor);
    setSelectedCell(null);
  }, [selectedCell, fixColor, submitManualFix]);

  // ===== Result mode =====
  if (warp_view_url || lut_preview_url) {
    return (
      <div
        data-testid="extractor-results"
        className="flex-1 flex flex-col items-center justify-center gap-6 p-6 overflow-auto"
      >
        {warp_view_url && (
          <div className="flex flex-col items-center gap-2">
            <span className="text-xs text-gray-500 dark:text-gray-400">
              {t("ext_canvas_warp_view")}
            </span>
            <img
              data-testid="warp-view-image"
              src={warp_view_url}
              alt="Warp view"
              className="max-w-full max-h-[40vh] rounded border border-gray-300 dark:border-gray-700"
            />
          </div>
        )}
        {lut_preview_url && (
          <div className="flex flex-col items-center gap-2">
            <span className="text-xs text-gray-500 dark:text-gray-400">
              {t("ext_canvas_lut_preview")}
            </span>
            <img
              ref={lutPreviewRef}
              data-testid="lut-preview-image"
              src={lut_preview_url}
              alt="LUT preview"
              onClick={handleLutPreviewClick}
              className="max-w-full max-h-[40vh] rounded border border-gray-300 dark:border-gray-700 cursor-crosshair"
            />
          </div>
        )}
        {/* 手动修正浮层：选中色块后显示 */}
        {selectedCell && (
          <div
            data-testid="manual-fix-popup"
            className="flex items-center gap-3 bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg px-4 py-3"
          >
            <span className="text-sm text-gray-700 dark:text-gray-300">
              {t("ext_canvas_row")} {selectedCell[0] + 1} / {t("ext_canvas_col")} {selectedCell[1] + 1}
            </span>
            <input
              data-testid="fix-color-picker"
              type="color"
              value={fixColor}
              onChange={(e) => setFixColor(e.target.value)}
              className="w-10 h-8 rounded border border-gray-300 dark:border-gray-500 cursor-pointer bg-transparent"
            />
            <span className="text-xs text-gray-500 dark:text-gray-400 font-mono">{fixColor}</span>
            <button
              data-testid="fix-submit-button"
              onClick={handleFixSubmit}
              disabled={manualFixLoading}
              className="px-3 py-1 text-sm rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white"
            >
              {manualFixLoading ? t("ext_canvas_fixing") : t("ext_canvas_confirm_fix")}
            </button>
            <button
              onClick={() => setSelectedCell(null)}
              className="px-2 py-1 text-sm rounded bg-gray-200 hover:bg-gray-300 dark:bg-gray-600 dark:hover:bg-gray-500 text-gray-700 dark:text-gray-300"
            >
              {t("ext_canvas_cancel")}
            </button>
          </div>
        )}
      </div>
    );
  }

  // ===== Empty state =====
  if (!imagePreviewUrl) {
    return (
      <div
        data-testid="extractor-empty-state"
        className="flex-1 flex flex-col items-center justify-center gap-3 text-gray-400 dark:text-gray-500"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="h-16 w-16 opacity-40"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"
          />
        </svg>
        <p className="text-sm">{t("ext_canvas_upload_hint")}</p>
        <p className="text-xs text-gray-500 dark:text-gray-600">
          {t("ext_canvas_upload_hint_en")}
        </p>
      </div>
    );
  }

  // ===== Canvas mode =====
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-3 p-4">
      {/* Corner hint */}
      <p
        data-testid="corner-hint"
        className={`text-sm font-medium ${
          cornerCount >= 4 ? "text-green-500 dark:text-green-400" : "text-yellow-500 dark:text-yellow-300"
        }`}
      >
        {hintText}
      </p>

      {/* Canvas */}
      <canvas
        ref={canvasRef}
        data-testid="extractor-canvas"
        width={imageNaturalWidth ?? 800}
        height={imageNaturalHeight ?? 600}
        onClick={handleCanvasClick}
        className="max-w-full max-h-[75vh] rounded border border-gray-300 dark:border-gray-700 cursor-crosshair"
        style={{ objectFit: "contain" }}
      />
    </div>
  );
}
