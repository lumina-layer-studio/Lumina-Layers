import { useState, useMemo, useCallback, useEffect } from "react";
import { useConverterStore } from "../../stores/converterStore";
import { useSettingsStore } from "../../stores/settingsStore";
import { hexToRgb, sortByColorDistance } from "../../utils/colorUtils";
import { isCardModeAvailable } from "../../utils/cardUtils";
import type { LutColorEntry } from "../../api/types";
import { useI18n } from "../../i18n/context";
import { cx, mutedSectionCardClass, sectionCardClass } from "../ui/panelPrimitives";

export type HueCategory =
  | "all"
  | "fav"
  | "red"
  | "orange"
  | "yellow"
  | "green"
  | "cyan"
  | "blue"
  | "purple"
  | "neutral";

// HUE_FILTERS moved inside component for i18n

export function classifyHue(r: number, g: number, b: number): HueCategory {
  const rf = r / 255;
  const gf = g / 255;
  const bf = b / 255;
  const max = Math.max(rf, gf, bf);
  const min = Math.min(rf, gf, bf);
  const d = max - min;
  const s = max === 0 ? 0 : d / max;
  const v = max;

  // 提高中性色阈值，减少低饱和度颜色的误分类
  if (s < 0.2 || v < 0.15) return "neutral";

  let h = 0;
  if (d !== 0) {
    if (max === rf) h = ((gf - bf) / d) % 6;
    else if (max === gf) h = (bf - rf) / d + 2;
    else h = (rf - gf) / d + 4;
  }
  h = ((h * 60) + 360) % 360;

  // 使用更宽松的色相范围，减少边界色块
  // 核心策略：扩大每个色相类别的范围，让边界区域有更多容错空间
  if (h < 20 || h >= 340) return "red";      // 红色: 340-20° (扩大 10°)
  if (h < 50) return "orange";                // 橙色: 20-50° (扩大 20°)
  if (h < 80) return "yellow";                // 黄色: 50-80° (扩大 20°)
  if (h < 170) return "green";                // 绿色: 80-170° (扩大 20°)
  if (h < 200) return "cyan";                 // 青色: 170-200° (扩大 10°)
  if (h < 270) return "blue";                 // 蓝色: 200-270° (扩大 20°)
  if (h < 340) return "purple";               // 紫色: 270-340° (扩大 10°)
  return "neutral";
}

/**
 * Check if a LUT color entry matches a search query.
 * 检查 LUT 颜色条目是否匹配搜索查询。
 */
export function matchesSearch(entry: LutColorEntry, query: string): boolean {
  const q = query.toLowerCase().trim();
  if (!q) return true;
  const hexNoHash = entry.hex.replace("#", "").toLowerCase();
  if (hexNoHash.includes(q.replace("#", ""))) return true;
  const rgbMatch = q.match(/(\d{1,3})\s*[,\s]\s*(\d{1,3})\s*[,\s]\s*(\d{1,3})/);
  if (rgbMatch) {
    const [, rs, gs, bs] = rgbMatch;
    const [r, g, b] = entry.rgb;
    if (r === Number(rs) && g === Number(gs) && b === Number(bs)) return true;
  }
  return false;
}

// ========== Favorites persistence ==========

function loadFavorites(lutKey: string): Set<string> {
  try {
    const stored = localStorage.getItem(`lut_favorites_${lutKey}`);
    return stored ? new Set(JSON.parse(stored) as string[]) : new Set();
  } catch { return new Set(); }
}

function saveFavorites(lutKey: string, favs: Set<string>) {
  try {
    localStorage.setItem(`lut_favorites_${lutKey}`, JSON.stringify([...favs]));
  } catch { /* noop */ }
}

// ========== Compact ColorSwatch ==========

function ColorSwatch({
  entry,
  isTarget,
  isFav,
  onClick,
  onDoubleClick,
}: {
  entry: LutColorEntry;
  isTarget: boolean;
  isFav: boolean;
  onClick: () => void;
  onDoubleClick: () => void;
}) {
  const { t } = useI18n();
  return (
    <button
      type="button"
      aria-label={`${t("lut_grid_color_label").replace("{hex}", entry.hex)}${isFav ? ` (${t("lut_grid_color_fav")})` : ""}`}
      aria-selected={isTarget}
      onClick={onClick}
      onDoubleClick={(e) => { e.stopPropagation(); onDoubleClick(); }}
      className={`relative flex flex-col items-center rounded-2xl border p-1 transition-colors ${
        isTarget
          ? "border-amber-400 bg-amber-400/10 ring-2 ring-amber-400/30"
          : "border-transparent hover:border-slate-300 hover:bg-white/65 dark:hover:border-slate-600 dark:hover:bg-slate-900/75"
      }`}
      title={`${entry.hex} · ${isFav ? t("lut_grid_dblclick_unfav") : t("lut_grid_dblclick_fav")}`}
    >
      <span
        className="block h-5 w-5 rounded-lg border border-slate-300/80 dark:border-slate-600/80"
        style={{ backgroundColor: entry.hex }}
      />
      {isFav && (
        <span className="absolute -top-0.5 -right-0.5 text-[8px] leading-none text-yellow-400">★</span>
      )}
      <span className="mt-0.5 font-mono text-[7px] leading-none text-slate-500 dark:text-slate-400">
        {entry.hex}
      </span>
    </button>
  );
}

// Card mode helpers have been moved inside the main component to access state variables.

export default function LutColorGrid() {
  const { t } = useI18n();
  const paletteMode = useSettingsStore((s) => s.paletteMode);
  const setPaletteMode = useSettingsStore((s) => s.setPaletteMode);

  const HUE_FILTERS: { key: HueCategory; label: string; dot: string }[] = [
    { key: "all", label: t("lut_grid_hue_all_short"), dot: "" },
    { key: "fav", label: t("lut_grid_hue_fav_short"), dot: "" },
    { key: "red", label: t("lut_grid_hue_red_short"), dot: "#e53935" },
    { key: "orange", label: t("lut_grid_hue_orange_short"), dot: "#fb8c00" },
    { key: "yellow", label: t("lut_grid_hue_yellow_short"), dot: "#fdd835" },
    { key: "green", label: t("lut_grid_hue_green_short"), dot: "#43a047" },
    { key: "cyan", label: t("lut_grid_hue_cyan_short"), dot: "#00acc1" },
    { key: "blue", label: t("lut_grid_hue_blue_short"), dot: "#1e88e5" },
    { key: "purple", label: t("lut_grid_hue_purple_short"), dot: "#8e24aa" },
    { key: "neutral", label: t("lut_grid_hue_neutral_short"), dot: "#9e9e9e" },
  ];

  const palette = useConverterStore((s) => s.palette);
  const selectedColor = useConverterStore((s) => s.selectedColor);
  const colorRemapMap = useConverterStore((s) => s.colorRemapMap);
  const lutColors = useConverterStore((s) => s.lutColors);
  const lutColorsLoading = useConverterStore((s) => s.lutColorsLoading);
  const lutColorsLutName = useConverterStore((s) => s.lutColorsLutName);
  const selectionMode = useConverterStore((s) => s.selectionMode);
  const selectedColors = useConverterStore((s) => s.selectedColors);
  const replacePreviewLoading = useConverterStore((s) => s.replacePreviewLoading);
  const setPendingReplacement = useConverterStore((s) => s.setPendingReplacement);
  const pendingReplacement = useConverterStore((s) => s.pendingReplacement);
  const confirmReplacement = useConverterStore((s) => s.confirmReplacement);
  const colorMode = useConverterStore((s) => s.color_mode);
  const [hueFilter, setHueFilter] = useState<HueCategory>("all");
  const [searchText, setSearchText] = useState("");
  const [favorites, setFavorites] = useState<Set<string>>(new Set());

  const cardAvailable = useMemo(
    () => isCardModeAvailable(colorMode),
    [colorMode],
  );

  // --- Local Components ---
  const CardSection = ({
    colors,
    cols,
    title,
    selectedColor,
    colorRemapMap,
    onColorClick,
  }: {
    colors: LutColorEntry[];
    cols: number;
    title?: string;
    selectedColor: string | null;
    colorRemapMap: Record<string, string>;
    onColorClick: (hex: string) => void;
  }) => {
    return (
      <div>
        {title && (
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">{title}</p>
        )}
        <div
          className="rounded-[20px] border border-slate-200/80 bg-white/55 p-2 shadow-[var(--shadow-control)] dark:border-slate-700/80 dark:bg-slate-900/60"
          style={{
            display: "grid",
            gridTemplateColumns: `repeat(${cols}, 18px)`,
            gap: "1px",
          }}
        >
          {colors.map((c, i) => {
            const hexNoHash = c.hex.replace("#", "");
            const isTarget = selectedColor
              ? colorRemapMap[selectedColor] === hexNoHash
              : false;
            const [r, g, b] = c.rgb;
            return (
              <button
                key={`${c.hex}-${i}`}
                type="button"
                title={`${c.hex} · RGB(${r}, ${g}, ${b})`}
                onClick={() => onColorClick(c.hex)}
                className={`cursor-pointer rounded-[4px] border transition-colors ${
                  isTarget
                    ? "border-amber-500 ring-1 ring-amber-500"
                    : "border-transparent hover:border-slate-400"
                }`}
                style={{
                  width: 18,
                  height: 18,
                  backgroundColor: c.hex,
                }}
              />
            );
          })}
        </div>
      </div>
    );
  };

  const CardGrid = ({
    lutColors,
    colorMode,
    selectedColor,
    colorRemapMap,
    onColorClick,
  }: {
    lutColors: LutColorEntry[];
    colorMode: string;
    selectedColor: string | null;
    colorRemapMap: Record<string, string>;
    onColorClick: (hex: string) => void;
  }) => {
    const total = lutColors.length;
    const isEightColor = colorMode === "8-Color Max";

    if (isEightColor && total > 1) {
      const half = Math.floor(total / 2);
      const colsA = Math.ceil(Math.sqrt(half));
      const colsB = Math.ceil(Math.sqrt(total - half));
      return (
        <div className="flex gap-3 overflow-auto" style={{ maxHeight: "28vh" }}>
          <CardSection
            colors={lutColors.slice(0, half)}
            cols={colsA}
            title={t("lut_grid_card_a")}
            selectedColor={selectedColor}
            colorRemapMap={colorRemapMap}
            onColorClick={onColorClick}
          />
          <CardSection
            colors={lutColors.slice(half)}
            cols={colsB}
            title={t("lut_grid_card_b")}
            selectedColor={selectedColor}
            colorRemapMap={colorRemapMap}
            onColorClick={onColorClick}
          />
        </div>
      );
    }

    const cols = Math.ceil(Math.sqrt(total));
    return (
      <div className="overflow-auto" style={{ maxHeight: "28vh" }}>
        <CardSection
          colors={lutColors}
          cols={cols}
          selectedColor={selectedColor}
          colorRemapMap={colorRemapMap}
          onColorClick={onColorClick}
        />
      </div>
    );
  };

  // Load favorites when LUT changes
  useEffect(() => {
    if (lutColorsLutName) {
      setFavorites(loadFavorites(lutColorsLutName));
    } else {
      setFavorites(new Set());
    }
  }, [lutColorsLutName]);

  const toggleFav = useCallback((hex: string) => {
    const key = hex.toLowerCase();
    setFavorites((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      if (lutColorsLutName) saveFavorites(lutColorsLutName, next);
      return next;
    });
  }, [lutColorsLutName]);

  const usedHexSet = useMemo(() => {
    const s = new Set<string>();
    for (const e of palette) s.add(`#${e.matched_hex}`.toLowerCase());
    return s;
  }, [palette]);

  const { usedColors, otherColors, visibleCount } = useMemo(() => {
    const used: LutColorEntry[] = [];
    const other: LutColorEntry[] = [];

    for (const c of lutColors) {
      const hex = c.hex.toLowerCase();
      const [r, g, b] = c.rgb;

      // Favorites filter
      if (hueFilter === "fav") {
        if (!favorites.has(hex)) continue;
        if (searchText && !matchesSearch(c, searchText)) continue;
      } else {
        if (hueFilter !== "all" && classifyHue(r, g, b) !== hueFilter) continue;
        if (searchText && !matchesSearch(c, searchText)) continue;
      }

      if (usedHexSet.has(hex)) used.push(c);
      else other.push(c);
    }
    return { usedColors: used, otherColors: other, visibleCount: used.length + other.length };
  }, [lutColors, hueFilter, searchText, usedHexSet, favorites]);

  const recommendations = useMemo(() => {
    if (!selectedColor || lutColors.length === 0) return null;
    return sortByColorDistance(hexToRgb(selectedColor), lutColors, 12);
  }, [selectedColor, lutColors]);

  const handleColorClick = (clickedHex: string) => {
    if (replacePreviewLoading) return;

    const hexNoHash = clickedHex.replace("#", "");

    switch (selectionMode) {
      case 'select-all': {
        // 全选模式：需要先选中源色
        if (!selectedColor) return;
        setPendingReplacement({
          sourceHex: selectedColor,
          targetHex: hexNoHash,
          mode: 'select-all',
        });
        break;
      }
      case 'multi-select': {
        // 多选模式：需要先选中至少一个源色
        if (selectedColors.size === 0) return;
        setPendingReplacement({
          sourceHex: selectedColor ?? '',
          targetHex: hexNoHash,
          mode: 'multi-select',
          sourceColors: Array.from(selectedColors),
        });
        break;
      }
      case 'current':
      case 'region': {
        // 当前/区域模式：设置 pending 状态
        setPendingReplacement({
          sourceHex: selectedColor ?? '',
          targetHex: hexNoHash,
          mode: selectionMode,
        });
        break;
      }
    }
  };

  return (
    <div className="relative">
      {replacePreviewLoading && (
        <div className="absolute inset-0 z-10 flex items-center justify-center rounded-[24px] bg-slate-950/40">
          <p className="text-xs text-slate-100">{t("lut_grid_loading")}</p>
        </div>
      )}
      {lutColorsLoading ? (
        <p className="py-4 text-sm text-slate-500 dark:text-slate-400">{t("lut_grid_loading")}</p>
      ) : lutColors.length === 0 ? (
        <p className="py-4 text-sm text-slate-500 dark:text-slate-400">{t("lut_grid_select_lut")}</p>
      ) : (
        <div className={cx(sectionCardClass, "flex h-full flex-col gap-3 rounded-[26px] px-4 py-4")}>
          {/* Confirmation preview bar */}
          {pendingReplacement && (
            <div className={cx(mutedSectionCardClass, "flex items-center gap-1.5 px-3 py-2")}>
              {/* Source color swatch(es) */}
              <div className="flex items-center gap-0.5">
                {pendingReplacement.mode === 'multi-select' && pendingReplacement.sourceColors ? (
                  pendingReplacement.sourceColors.map((hex) => (
                    <span
                      key={hex}
                      className="inline-block h-5 w-5 rounded-lg border border-slate-400/80 dark:border-slate-500/80"
                      style={{ backgroundColor: `#${hex}` }}
                      title={`#${hex}`}
                    />
                  ))
                ) : (
                  <span
                    className="inline-block h-5 w-5 rounded-lg border border-slate-400/80 dark:border-slate-500/80"
                    style={{ backgroundColor: `#${pendingReplacement.sourceHex}` }}
                    title={`#${pendingReplacement.sourceHex}`}
                  />
                )}
              </div>
              {/* Arrow */}
              <span className="text-xs text-slate-400">→</span>
              {/* Target color swatch */}
              <span
                className="inline-block h-5 w-5 rounded-lg border border-slate-400/80 dark:border-slate-500/80"
                style={{ backgroundColor: `#${pendingReplacement.targetHex}` }}
                title={`#${pendingReplacement.targetHex}`}
              />
              {/* Spacer */}
              <div className="flex-1" />
              {/* Confirm button */}
              <button
                type="button"
                onClick={() => confirmReplacement()}
                className="rounded-full bg-blue-600 px-2.5 py-1 text-[10px] font-medium text-white transition-colors hover:bg-blue-500"
              >
                {t("replace_confirm_btn")}
              </button>
              {/* Cancel button */}
              <button
                type="button"
                onClick={() => setPendingReplacement(null)}
                className="rounded-full border border-slate-300/80 bg-white/80 px-2.5 py-1 text-[10px] font-medium text-slate-700 transition-colors hover:bg-white dark:border-slate-700/80 dark:bg-slate-900/70 dark:text-slate-200 dark:hover:bg-slate-900"
              >
                {t("replace_cancel_btn")}
              </button>
            </div>
          )}

          {/* Status line */}
          <p className="text-[11px] leading-tight text-slate-500 dark:text-slate-400">
            共 {lutColors.length} 色，显示 {visibleCount} 色
            {favorites.size > 0 && ` · ★${favorites.size}`}
            {selectedColor && (
              <>
                {" · 已选中 "}
                <span
                  className="inline-block h-2.5 w-2.5 rounded-sm border border-slate-400/80 align-middle dark:border-slate-500/80"
                  style={{ backgroundColor: `#${selectedColor}` }}
                />
                <span className="font-mono text-[10px]"> #{selectedColor}</span>
              </>
            )}
          </p>

          {/* Search */}
          <input
            type="text"
            placeholder={t("lut_grid_search_placeholder_short")}
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            className="w-full rounded-2xl border border-slate-200/80 bg-white/78 px-3 py-2 text-xs text-slate-700 outline-none shadow-[var(--shadow-control)] focus:border-blue-400 focus:ring-4 focus:ring-[var(--focus-ring)] dark:border-slate-700/80 dark:bg-slate-900/72 dark:text-slate-100"
          />

          {/* Hue filter bar + mode toggle */}
          <div className="flex items-center gap-0.5">
            <div className="flex flex-wrap gap-0.5">
              {HUE_FILTERS.map((f) => (
                <button
                  key={f.key}
                  type="button"
                  onClick={() => setHueFilter(f.key)}
                  className={`flex items-center gap-0.5 rounded-full border px-2 py-1 text-[10px] transition-colors ${
                    hueFilter === f.key
                      ? "border-blue-300 bg-blue-500/12 text-blue-700 dark:border-blue-700 dark:bg-blue-500/16 dark:text-blue-300"
                      : "border-slate-200/80 bg-white/65 text-slate-500 hover:border-slate-300 dark:border-slate-700/80 dark:bg-slate-900/60 dark:text-slate-400 dark:hover:border-slate-600"
                  }`}
                >
                  {f.key === "fav" ? (
                    <span className="text-yellow-400 text-[9px]">★</span>
                  ) : f.dot ? (
                    <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ backgroundColor: f.dot }} />
                  ) : null}
                  {f.label}
                </button>
              ))}
            </div>
            {cardAvailable && (
              <>
                <div className="flex-1" />
                <div className="flex items-center gap-0.5 shrink-0">
                  <button
                    type="button"
                    onClick={() => setPaletteMode("swatch")}
                    className={`rounded-full border px-2 py-1 text-[10px] transition-colors ${
                      paletteMode === "swatch"
                        ? "border-blue-300 bg-blue-500/12 text-blue-700 dark:border-blue-700 dark:bg-blue-500/16 dark:text-blue-300"
                        : "border-slate-200/80 bg-white/65 text-slate-500 hover:border-slate-300 dark:border-slate-700/80 dark:bg-slate-900/60 dark:text-slate-400 dark:hover:border-slate-600"
                    }`}
                  >
                    {t("lut_grid_mode_swatch")}
                  </button>
                  <button
                    type="button"
                    onClick={() => setPaletteMode("card")}
                    className={`rounded-full border px-2 py-1 text-[10px] transition-colors ${
                      paletteMode === "card"
                        ? "border-blue-300 bg-blue-500/12 text-blue-700 dark:border-blue-700 dark:bg-blue-500/16 dark:text-blue-300"
                        : "border-slate-200/80 bg-white/65 text-slate-500 hover:border-slate-300 dark:border-slate-700/80 dark:bg-slate-900/60 dark:text-slate-400 dark:hover:border-slate-600"
                    }`}
                  >
                    {t("lut_grid_mode_card")}
                  </button>
                </div>
              </>
            )}
          </div>

          {/* Color grid — conditional swatch vs card rendering */}
          {paletteMode === "card" && cardAvailable ? (
            <CardGrid
              lutColors={lutColors}
              colorMode={colorMode}
              selectedColor={selectedColor}
              colorRemapMap={colorRemapMap}
              onColorClick={handleColorClick}
            />
          ) : (
            <div className="dock-scrollbar flex max-h-[28vh] flex-col gap-2 overflow-y-auto pr-1" role="listbox" aria-label="LUT 可用颜色列表">
              {recommendations && recommendations.length > 0 && (
                <div>
                  <p className="mb-1 text-[11px] font-semibold text-amber-500">
                    {t("lut_grid_recommendations")} ({recommendations.length})
                  </p>
                  <div className="grid grid-cols-10 gap-1">
                    {recommendations.map((c) => {
                      const hexNoHash = c.hex.replace("#", "");
                      const isTarget = selectedColor ? colorRemapMap[selectedColor] === hexNoHash : false;
                      return (
                        <div key={c.hex}>
                          <ColorSwatch
                            entry={c}
                            isTarget={isTarget}
                            isFav={favorites.has(c.hex.toLowerCase())}
                            onClick={() => handleColorClick(c.hex)}
                            onDoubleClick={() => toggleFav(c.hex)}
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
              {/* Used Colors Section */}
              {usedColors.length > 0 && (
                <div>
                  <p className="mb-1 text-[11px] font-semibold text-emerald-500">
                    {t("lut_grid_used_in_image")} ({usedColors.length})
                  </p>
                  <div className="grid grid-cols-10 gap-1">
                    {usedColors.map((c) => {
                      const hexNoHash = c.hex.replace("#", "");
                      const isTarget = selectedColor ? colorRemapMap[selectedColor] === hexNoHash : false;
                      return (
                        <div key={c.hex}>
                          <ColorSwatch
                            entry={c}
                            isTarget={isTarget}
                            isFav={favorites.has(c.hex.toLowerCase())}
                            onClick={() => handleColorClick(c.hex)}
                            onDoubleClick={() => toggleFav(c.hex)}
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Other/All Colors Section */}
              {otherColors.length > 0 && (
                <div>
                  <p className="mb-1 text-[11px] font-semibold text-slate-500 dark:text-slate-400">
                    {usedColors.length > 0 ? `${t("lut_grid_other_available")} (${otherColors.length})` : `${t("lut_grid_all_available")} (${otherColors.length})`}
                  </p>
                  <div className="grid grid-cols-10 gap-1">
                    {otherColors.map((c) => {
                      const hexNoHash = c.hex.replace("#", "");
                      const isTarget = selectedColor ? colorRemapMap[selectedColor] === hexNoHash : false;
                      return (
                        <div key={c.hex}>
                          <ColorSwatch
                            entry={c}
                            isTarget={isTarget}
                            isFav={favorites.has(c.hex.toLowerCase())}
                            onClick={() => handleColorClick(c.hex)}
                            onDoubleClick={() => toggleFav(c.hex)}
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {visibleCount === 0 && (
                <p className="py-1 text-xs text-slate-500 dark:text-slate-400">{t("lut_grid_no_match")}</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
