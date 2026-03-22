import { useConverterStore } from "../../stores/converterStore";
import type { PaletteEntry } from "../../api/types";
import Slider from "../ui/Slider";
import Button from "../ui/Button";
import { useI18n } from "../../i18n/context";
import { cx, workstationInsetCardClass, workstationPanelCardClass } from "../ui/panelPrimitives";

// ========== PaletteItem ==========

interface PaletteItemProps {
  entry: PaletteEntry;
  isSelected: boolean;
  remappedHex: string | undefined;
  heightMm: number | undefined;
  showHeightSlider: boolean;
  maxHeight: number;
  isFreeColor?: boolean;
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
  isFreeColor = false,
  onSelect,
  onHeightChange,
}: PaletteItemProps) {
  const { t } = useI18n();
  const displayHex = remappedHex ?? entry.matched_hex;
  const isRemapped = !!remappedHex;

  // Border priority: isFreeColor > isRemapped > default
  const borderClass = isFreeColor
    ? "border-2 border-dashed border-red-400"
    : isRemapped
      ? "border border-yellow-500"
      : "border border-gray-600";

  // Compact block mode (no height slider)
  if (!showHeightSlider) {
    return (
      <div
        role="button"
        tabIndex={0}
        aria-label={`${t("lut_grid_color_label").replace("{hex}", entry.matched_hex)}，${entry.percentage.toFixed(1)}%${isRemapped ? `，${t("palette_replaced_label").replace("{hex}", `#${remappedHex}`)}` : ""}`}
        aria-pressed={isSelected}
        onClick={onSelect}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onSelect();
          }
        }}
        className={`relative flex w-full min-w-0 flex-col items-center gap-1 rounded-2xl px-1.5 py-2 cursor-pointer border transition-all duration-150 ${
          isSelected
            ? "border-amber-400 bg-amber-400/10 ring-2 ring-amber-400/30"
            : "border-transparent bg-white/35 hover:border-slate-300 hover:bg-white/65 dark:bg-slate-900/35 dark:hover:border-slate-600 dark:hover:bg-slate-900/75"
        }`}
      >
        <span
          className={`inline-block h-[clamp(1.4rem,2vw,1.75rem)] w-[clamp(1.4rem,2vw,1.75rem)] rounded-xl ${borderClass}`}
          style={{ backgroundColor: `#${displayHex}` }}
          title={`#${displayHex}`}
        />
        <span className="text-[clamp(0.55rem,0.75vw,0.625rem)] tabular-nums leading-none text-slate-500 dark:text-slate-400">
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
      aria-label={`${t("lut_grid_color_label").replace("{hex}", entry.matched_hex)}，${entry.percentage.toFixed(1)}%${isRemapped ? `，${t("palette_replaced_label").replace("{hex}", `#${remappedHex}`)}` : ""}`}
      aria-pressed={isSelected}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className={`relative flex h-full min-h-0 flex-col gap-2 rounded-[20px] px-2.5 py-2 cursor-pointer border transition-all duration-150 ${
        isSelected
          ? "border-amber-400 bg-amber-400/10 ring-2 ring-amber-400/30"
          : "border-transparent bg-white/35 hover:border-slate-300 hover:bg-white/65 dark:bg-slate-900/35 dark:hover:border-slate-600 dark:hover:bg-slate-900/75"
      }`}
    >
      {/* Top row: swatch + percentage */}
      <div className="flex items-center gap-1.5">
        <span
          className={`inline-block h-[clamp(1.25rem,1.7vw,1.5rem)] w-[clamp(1.25rem,1.7vw,1.5rem)] shrink-0 rounded-xl ${borderClass}`}
          style={{ backgroundColor: `#${displayHex}` }}
          title={`#${displayHex}`}
        />
        <span className="truncate text-[clamp(0.55rem,0.75vw,0.625rem)] tabular-nums text-slate-500 dark:text-slate-400">
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
      <span className="text-[clamp(0.55rem,0.75vw,0.625rem)] font-medium text-slate-500 dark:text-slate-400">{label}</span>
      <span
        className="inline-block h-[clamp(2rem,3vw,2.75rem)] w-[clamp(2rem,3vw,2.75rem)] rounded-2xl border border-slate-300/80 dark:border-slate-600/80"
        style={{ backgroundColor: `#${hex}` }}
      />
      <span className="font-mono text-[clamp(0.55rem,0.75vw,0.625rem)] text-slate-600 dark:text-slate-300">#{hex}</span>
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
    <div className={cx(workstationInsetCardClass, "mb-1 flex items-start gap-4")}>
      <ColorBlock label={t("palette_quantized")} hex={entry.quantized_hex} />
      <ColorBlock label={t("palette_matched")} hex={entry.matched_hex} />
      {remappedHex && <ColorBlock label={t("palette_replaced_label")} hex={remappedHex} />}
    </div>
  );
}

// ========== FreeColorSummary ==========

function FreeColorSummary({ freeColors }: { freeColors: Set<string> }) {
  const { t } = useI18n();
  if (freeColors.size === 0) return null;
  return (
    <div className={cx(workstationInsetCardClass, "flex flex-wrap items-center gap-2 px-3 py-2.5")}>
      <span className="text-[clamp(0.65rem,0.8vw,0.7rem)] font-medium text-slate-500 dark:text-slate-400">{t("conv_free_color_label")}:</span>
      {Array.from(freeColors).sort().map(hex => (
        <span
          key={hex}
          className="h-6 w-6 rounded-xl border-2 border-dashed border-red-400"
          style={{ backgroundColor: `#${hex}` }}
          title={`#${hex}`}
        />
      ))}
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
  const selectionMode = useConverterStore((s) => s.selectionMode);
  const setSelectionMode = useConverterStore((s) => s.setSelectionMode);
  const selectedColors = useConverterStore((s) => s.selectedColors);
  const toggleColorInSelection = useConverterStore((s) => s.toggleColorInSelection);
  const free_color_set = useConverterStore((s) => s.free_color_set);
  const toggleFreeColor = useConverterStore((s) => s.toggleFreeColor);
  const clearFreeColors = useConverterStore((s) => s.clearFreeColors);
  const regionReplacementCount = useConverterStore((s) => s.regionReplacementCount);

  const hasRemaps = Object.keys(colorRemapMap).length > 0 || regionReplacementCount > 0;
  const hasHistory = remapHistory.length > 0;

  const handleSelect = (hex: string) => {
    switch (selectionMode) {
      case 'current':
        // 当前模式 = 单区域替换，调色板点击不响应（由 3D 预览处理）
        break;
      case 'select-all':
        // 全选模式 = 全局单色替换，点击调色板选中一个颜色
        setSelectedColor(selectedColor === hex ? null : hex);
        break;
      case 'multi-select':
        // 多选模式 = 可复选，点击切换选中状态
        // 同时设置 selectedColor 以触发 RGB 光带高亮
        setSelectedColor(selectedColor === hex ? null : hex);
        toggleColorInSelection(hex);
        break;
      case 'region':
        // 局部区域模式，调色板点击不响应（由 3D 预览处理）
        break;
    }
  };

  const getIsSelected = (hex: string): boolean => {
    if (selectionMode === 'multi-select') {
      return selectedColors.has(hex);
    }
    // 所有其他模式统一使用 selectedColor 高亮（RGB 光带效果一致）
    return selectedColor === hex;
  };

  return (
    <div className={workstationPanelCardClass}>
      {palette.length === 0 ? (
        <p className="py-4 text-sm text-slate-500 dark:text-slate-400">
          {t("palette_no_data")}
        </p>
      ) : (
        <div className="flex h-full flex-col gap-3">
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

          {/* Undo / Clear buttons + Mode switching buttons */}
          <div className="flex flex-wrap gap-2">
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
            <Button
              label={t("palette_mode_select_all")}
              variant={selectionMode === 'select-all' ? 'primary' : 'secondary'}
              onClick={() => setSelectionMode('select-all')}
            />
            <Button
              label={t("palette_mode_current")}
              variant={selectionMode === 'current' ? 'primary' : 'secondary'}
              onClick={() => setSelectionMode('current')}
            />
            <Button
              label={t("palette_mode_multi_select")}
              variant={selectionMode === 'multi-select' ? 'primary' : 'secondary'}
              onClick={() => setSelectionMode('multi-select')}
            />
            <Button
              label={t("palette_mode_region")}
              variant={selectionMode === 'region' ? 'primary' : 'secondary'}
              onClick={() => setSelectionMode('region')}
            />
          </div>

          {/* Free color buttons */}
          <div className="flex flex-wrap gap-2">
            <Button
              label={t("conv_free_color_btn")}
              variant="secondary"
              onClick={() => {
                if (selectedColor) toggleFreeColor(selectedColor);
              }}
              disabled={selectedColor === null}
            />
            <Button
              label={t("conv_free_color_clear_btn")}
              variant="secondary"
              onClick={clearFreeColors}
              disabled={free_color_set.size === 0}
            />
          </div>

          {/* Free color summary */}
          <FreeColorSummary freeColors={free_color_set} />

          {/* Palette items */}
          <div
            className="dock-scrollbar flex-1  pr-1"
            role="listbox"
            aria-label={t("palette_list_label")}
          >
            <div
              className={
                enable_relief
                  ? "grid grid-cols-[repeat(auto-fit,minmax(7rem,1fr))] gap-2"
                  : "grid grid-cols-[repeat(auto-fit,minmax(3.4rem,1fr))] gap-2"
              }
            >
              {palette.map((entry) => (
                <PaletteItem
                  key={entry.matched_hex}
                  entry={entry}
                  isSelected={getIsSelected(entry.matched_hex)}
                  remappedHex={colorRemapMap[entry.matched_hex]}
                  heightMm={color_height_map[entry.matched_hex]}
                  showHeightSlider={enable_relief}
                  maxHeight={heightmap_max_height}
                  isFreeColor={free_color_set.has(entry.matched_hex)}
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
