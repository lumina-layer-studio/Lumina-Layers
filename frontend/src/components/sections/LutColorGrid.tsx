import { useState, useMemo, useCallback, useEffect } from "react";
import { useConverterStore } from "../../stores/converterStore";
import { hexToRgb, sortByColorDistance } from "../../utils/colorUtils";
import type { LutColorEntry } from "../../api/types";
import { useI18n } from "../../i18n/context";

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

  if (s < 0.15 || v < 0.1) return "neutral";

  let h = 0;
  if (d !== 0) {
    if (max === rf) h = ((gf - bf) / d) % 6;
    else if (max === gf) h = (bf - rf) / d + 2;
    else h = (rf - gf) / d + 4;
  }
  h = ((h * 60) + 360) % 360;

  if (h < 15 || h >= 345) return "red";
  if (h < 40) return "orange";
  if (h < 70) return "yellow";
  if (h < 160) return "green";
  if (h < 195) return "cyan";
  if (h < 260) return "blue";
  if (h < 345) return "purple";
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
      className={`relative flex flex-col items-center rounded cursor-pointer transition-colors hover:bg-gray-700/50 p-0.5 ${
        isTarget ? "ring-2 ring-yellow-500" : ""
      }`}
      title={`${entry.hex} · ${isFav ? t("lut_grid_dblclick_unfav") : t("lut_grid_dblclick_fav")}`}
    >
      <span
        className="block w-5 h-5 rounded-sm border border-gray-600"
        style={{ backgroundColor: entry.hex }}
      />
      {isFav && (
        <span className="absolute -top-0.5 -right-0.5 text-[8px] leading-none text-yellow-400">★</span>
      )}
      <span className="text-[7px] text-gray-500 font-mono leading-none mt-0.5">
        {entry.hex}
      </span>
    </button>
  );
}

// ========== ColorSection ==========

function ColorSection({
  title,
  titleColor,
  colors,
  selectedColor,
  colorRemapMap,
  favorites,
  onColorClick,
  onToggleFav,
}: {
  title: string;
  titleColor: string;
  colors: LutColorEntry[];
  selectedColor: string | null;
  colorRemapMap: Record<string, string>;
  favorites: Set<string>;
  onColorClick: (hex: string) => void;
  onToggleFav: (hex: string) => void;
}) {
  if (colors.length === 0) return null;
  return (
    <div>
      <p className="text-[10px] font-semibold mb-0.5" style={{ color: titleColor }}>
        {title}
      </p>
      <div className="grid grid-cols-10 gap-0.5">
        {colors.map((c) => {
          const hexNoHash = c.hex.replace("#", "");
          const isTarget = selectedColor
            ? colorRemapMap[selectedColor] === hexNoHash
            : false;
          return (
            <ColorSwatch
              key={c.hex}
              entry={c}
              isTarget={isTarget}
              isFav={favorites.has(c.hex.toLowerCase())}
              onClick={() => onColorClick(c.hex)}
              onDoubleClick={() => onToggleFav(c.hex)}
            />
          );
        })}
      </div>
    </div>
  );
}

// ========== Main Component ==========

export default function LutColorGrid() {
  const { t } = useI18n();

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
  const applyColorRemap = useConverterStore((s) => s.applyColorRemap);
  const setSelectedColor = useConverterStore((s) => s.setSelectedColor);
  const colorRemapMap = useConverterStore((s) => s.colorRemapMap);
  const lutColors = useConverterStore((s) => s.lutColors);
  const lutColorsLoading = useConverterStore((s) => s.lutColorsLoading);
  const lutColorsLutName = useConverterStore((s) => s.lutColorsLutName);
  const [hueFilter, setHueFilter] = useState<HueCategory>("all");
  const [searchText, setSearchText] = useState("");
  const [favorites, setFavorites] = useState<Set<string>>(new Set());

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
    if (!selectedColor) return;
    applyColorRemap(selectedColor, clickedHex.replace("#", ""));
    setSelectedColor(null);
  };

  return (
    <div>
      {lutColorsLoading ? (
        <p className="text-xs text-gray-500 py-2">{t("lut_grid_loading")}</p>
      ) : lutColors.length === 0 ? (
        <p className="text-xs text-gray-500 py-2">{t("lut_grid_select_lut")}</p>
      ) : (
        <div className="flex flex-col gap-1">
          {/* Status line */}
          <p className="text-[10px] text-gray-400 leading-tight">
            共 {lutColors.length} 色，显示 {visibleCount} 色
            {favorites.size > 0 && ` · ★${favorites.size}`}
            {selectedColor && (
              <>
                {" · 已选中 "}
                <span
                  className="inline-block w-2.5 h-2.5 rounded-sm border border-gray-600 align-middle"
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
            className="w-full px-2 py-0.5 text-[10px] rounded border border-gray-600 bg-gray-800 text-gray-200 outline-none focus:border-blue-500"
          />

          {/* Hue filter bar */}
          <div className="flex flex-wrap gap-0.5">
            {HUE_FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                onClick={() => setHueFilter(f.key)}
                className={`flex items-center gap-0.5 px-1.5 py-0.5 text-[9px] rounded-full border transition-colors ${
                  hueFilter === f.key
                    ? "bg-gray-200 text-gray-900 border-gray-400"
                    : "bg-gray-800 text-gray-400 border-gray-600 hover:border-gray-400"
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

          {/* Color grid */}
          <div className="overflow-y-auto flex flex-col gap-1.5" style={{ maxHeight: '28vh' }} role="listbox" aria-label="LUT 可用颜色列表">
            {recommendations && recommendations.length > 0 && (
              <div>
                <p className="text-[10px] font-semibold mb-0.5" style={{ color: "#f59e0b" }}>
                  {t("lut_grid_recommendations")} ({recommendations.length})
                </p>
                <div className="grid grid-cols-10 gap-0.5">
                  {recommendations.map((c) => {
                    const hexNoHash = c.hex.replace("#", "");
                    const isTarget = selectedColor ? colorRemapMap[selectedColor] === hexNoHash : false;
                    return (
                      <ColorSwatch
                        key={c.hex}
                        entry={c}
                        isTarget={isTarget}
                        isFav={favorites.has(c.hex.toLowerCase())}
                        onClick={() => handleColorClick(c.hex)}
                        onDoubleClick={() => toggleFav(c.hex)}
                      />
                    );
                  })}
                </div>
              </div>
            )}
            <ColorSection
              title={`${t("lut_grid_used_in_image")} (${usedColors.length})`}
              titleColor="#4CAF50"
              colors={usedColors}
              selectedColor={selectedColor}
              colorRemapMap={colorRemapMap}
              favorites={favorites}
              onColorClick={handleColorClick}
              onToggleFav={toggleFav}
            />
            <ColorSection
              title={usedColors.length > 0 ? `${t("lut_grid_other_available")} (${otherColors.length})` : `${t("lut_grid_all_available")} (${otherColors.length})`}
              titleColor="#888"
              colors={otherColors}
              selectedColor={selectedColor}
              colorRemapMap={colorRemapMap}
              favorites={favorites}
              onColorClick={handleColorClick}
              onToggleFav={toggleFav}
            />
            {visibleCount === 0 && (
              <p className="text-xs text-gray-500 py-1">{t("lut_grid_no_match")}</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
