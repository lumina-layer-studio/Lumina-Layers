import { useConverterStore } from "../../stores/converterStore";
import type { PaletteEntry } from "../../api/types";
import Slider from "../ui/Slider";
import Button from "../ui/Button";
import { useI18n } from "../../i18n/context";

// ========== PaletteItem ==========

interface PaletteItemProps {
  entry: PaletteEntry;
  isSelected: boolean;
  remappedHex: string | undefined;
  heightMm: number | undefined;
  showHeightSlider: boolean;
  maxHeight: number;
  onSelect: () => void;
  onHeightChange: (h: number) => void;
}

function PaletteItem({
  entry,
  isSelected,
  remappedHex,
  heightMm,
  showHeightSlider,
  maxHeight,
  onSelect,
  onHeightChange,
}: PaletteItemProps) {
  const { t } = useI18n();
  const displayHex = remappedHex ?? entry.matched_hex;
  const isRemapped = !!remappedHex;

  // Compact block mode (no height slider)
  if (!showHeightSlider) {
    return (
      <div
        role="button"
        tabIndex={0}
        aria-label={`${t("lut_grid_color_label").replace("{hex}", entry.matched_hex)}，${entry.percentage.toFixed(1)}%${isRemapped ? `，${t("palette_replaced").replace("{hex}", `#${remappedHex}`)}` : ""}`}
        aria-pressed={isSelected}
        onClick={onSelect}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onSelect();
          }
        }}
        className={`flex flex-col items-center gap-0.5 rounded px-1 py-1 cursor-pointer transition-colors ${
          isSelected
            ? "ring-2 ring-blue-500 bg-gray-700/60"
            : "hover:bg-gray-700/40"
        }`}
        style={{ width: 52 }}
      >
        <span
          className={`inline-block w-6 h-6 rounded border ${isRemapped ? "border-yellow-500" : "border-gray-600"}`}
          style={{ backgroundColor: `#${displayHex}` }}
          title={`#${displayHex}`}
        />
        <span className="text-[9px] text-gray-400 tabular-nums leading-none">
          {entry.percentage.toFixed(1)}%
        </span>
      </div>
    );
  }

  // Vertical compact block with height slider (relief mode, 3-col grid)
  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`${t("lut_grid_color_label").replace("{hex}", entry.matched_hex)}，${entry.percentage.toFixed(1)}%${isRemapped ? `，${t("palette_replaced").replace("{hex}", `#${remappedHex}`)}` : ""}`}
      aria-pressed={isSelected}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className={`flex flex-col gap-1 rounded-md px-2 py-1.5 cursor-pointer transition-colors ${
        isSelected
          ? "ring-2 ring-blue-500 bg-gray-700/60"
          : "hover:bg-gray-700/40"
      }`}
    >
      {/* Top row: swatch + percentage */}
      <div className="flex items-center gap-1.5">
        <span
          className={`inline-block w-5 h-5 rounded border shrink-0 ${isRemapped ? "border-yellow-500" : "border-gray-600"}`}
          style={{ backgroundColor: `#${displayHex}` }}
          title={`#${displayHex}`}
        />
        <span className="text-[10px] text-gray-400 tabular-nums truncate">
          {entry.percentage.toFixed(1)}%
        </span>
      </div>
      {/* Height slider */}
      <div
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        <Slider
          label=""
          value={heightMm ?? maxHeight * 0.5}
          min={0.08}
          max={maxHeight}
          step={0.04}
          unit="mm"
          onChange={onHeightChange}
        />
      </div>
    </div>
  );
}

// ========== ColorBlock ==========

interface ColorBlockProps {
  label: string;
  hex: string;
}

function ColorBlock({ label, hex }: ColorBlockProps) {
  return (
    <div className="flex flex-col items-center gap-1">
      <span className="text-[10px] text-gray-400">{label}</span>
      <span
        className="inline-block w-10 h-10 rounded border border-gray-600"
        style={{ backgroundColor: `#${hex}` }}
      />
      <span className="text-[10px] text-gray-300 font-mono">#{hex}</span>
    </div>
  );
}

// ========== SelectedColorDetail ==========

interface SelectedColorDetailProps {
  entry: PaletteEntry;
  remappedHex?: string;
}

function SelectedColorDetail({ entry, remappedHex }: SelectedColorDetailProps) {
  const { t } = useI18n();
  return (
    <div className="flex gap-4 items-start py-2 px-3 bg-gray-800/40 rounded-lg mb-2">
      <ColorBlock label={t("palette_quantized")} hex={entry.quantized_hex} />
      <ColorBlock label={t("palette_matched")} hex={entry.matched_hex} />
      {remappedHex && <ColorBlock label={t("palette_replaced")} hex={remappedHex} />}
    </div>
  );
}

// ========== PalettePanel ==========

export default function PalettePanel() {
  const { t } = useI18n();
  const palette = useConverterStore((s) => s.palette);
  const selectedColor = useConverterStore((s) => s.selectedColor);
  const setSelectedColor = useConverterStore((s) => s.setSelectedColor);
  const enable_relief = useConverterStore((s) => s.enable_relief);
  const color_height_map = useConverterStore((s) => s.color_height_map);
  const updateColorHeight = useConverterStore((s) => s.updateColorHeight);
  const colorRemapMap = useConverterStore((s) => s.colorRemapMap);
  const remapHistory = useConverterStore((s) => s.remapHistory);
  const undoColorRemap = useConverterStore((s) => s.undoColorRemap);
  const clearAllRemaps = useConverterStore((s) => s.clearAllRemaps);
  const heightmap_max_height = useConverterStore((s) => s.heightmap_max_height);

  const hasRemaps = Object.keys(colorRemapMap).length > 0;
  const hasHistory = remapHistory.length > 0;

  const handleSelect = (hex: string) => {
    setSelectedColor(selectedColor === hex ? null : hex);
  };

  return (
    <div>
      {palette.length === 0 ? (
        <p className="text-xs text-gray-500 py-2">
          {t("palette_no_data")}
        </p>
      ) : (
        <div className="flex flex-col gap-1">
          {/* Selected color detail */}
          {selectedColor && (() => {
            const selectedEntry = palette.find(
              (e) => e.matched_hex === selectedColor
            );
            if (!selectedEntry) return null;
            return (
              <SelectedColorDetail
                entry={selectedEntry}
                remappedHex={colorRemapMap[selectedColor]}
              />
            );
          })()}

          {/* Undo / Clear buttons */}
          <div className="flex gap-2 mb-2">
            <Button
              label={t("palette_undo")}
              variant="secondary"
              onClick={undoColorRemap}
              disabled={!hasHistory}
            />
            <Button
              label={t("palette_clear_remaps")}
              variant="secondary"
              onClick={clearAllRemaps}
              disabled={!hasRemaps}
            />
          </div>

          {/* Palette items */}
          <div
            className="max-h-80 overflow-y-auto"
            role="listbox"
            aria-label={t("palette_list_label")}
          >
            <div
              className={
                enable_relief
                  ? "grid grid-cols-3 gap-1"
                  : "flex flex-wrap gap-1"
              }
            >
              {palette.map((entry) => (
                <PaletteItem
                  key={entry.matched_hex}
                  entry={entry}
                  isSelected={selectedColor === entry.matched_hex}
                  remappedHex={colorRemapMap[entry.matched_hex]}
                  heightMm={color_height_map[entry.matched_hex]}
                  showHeightSlider={enable_relief}
                  maxHeight={heightmap_max_height}
                  onSelect={() => handleSelect(entry.matched_hex)}
                  onHeightChange={(h) => updateColorHeight(entry.matched_hex, h)}
                />
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
