import { useConverterStore } from "../../stores/converterStore";
import type { PaletteEntry } from "../../api/types";
import Slider from "../ui/Slider";
import Button from "../ui/Button";
import { useI18n } from "../../i18n/context";
import { motion } from "framer-motion";

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
      <motion.div
        layout
        whileHover={{ scale: 1.05, zIndex: 10 }}
        whileTap={{ scale: 0.95 }}
        transition={{ type: "spring", stiffness: 400, damping: 25 }}
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
        className={`relative flex flex-col items-center gap-0.5 rounded px-1 py-1 cursor-pointer transition-colors border ${
          isSelected
            ? "border-yellow-400 shadow-[0_0_12px_rgba(250,204,21,0.6)] bg-gray-700/60 z-10"
            : "border-transparent hover:bg-gray-700/40"
        }`}
        style={{ width: 52 }}
      >
        <span
          className={`inline-block w-6 h-6 rounded ${borderClass}`}
          style={{ backgroundColor: `#${displayHex}` }}
          title={`#${displayHex}`}
        />
        <span className="text-[9px] text-gray-400 tabular-nums leading-none">
          {entry.percentage.toFixed(1)}%
        </span>
      </motion.div>
    );
  }

  // Vertical compact block with height slider (relief mode, 3-col grid)
  return (
    <motion.div
      layout
      whileHover={{ scale: 1.02, zIndex: 10 }}
      whileTap={{ scale: 0.98 }}
      transition={{ type: "spring", stiffness: 400, damping: 25 }}
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
      className={`relative flex flex-col gap-1 rounded-md px-2 py-1.5 cursor-pointer transition-colors border ${
        isSelected
          ? "border-yellow-400 shadow-[0_0_12px_rgba(250,204,21,0.6)] bg-gray-700/60 z-10"
          : "border-transparent hover:bg-gray-700/40"
      }`}
    >
      {/* Top row: swatch + percentage */}
      <div className="flex items-center gap-1.5">
        <span
          className={`inline-block w-5 h-5 rounded shrink-0 ${borderClass}`}
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
    </motion.div>
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
      {remappedHex && <ColorBlock label={t("palette_replaced_label")} hex={remappedHex} />}
    </div>
  );
}

// ========== FreeColorSummary ==========

function FreeColorSummary({ freeColors }: { freeColors: Set<string> }) {
  const { t } = useI18n();
  if (freeColors.size === 0) return null;
  return (
    <div className="flex items-center gap-1.5 flex-wrap py-1">
      <span className="text-[10px] text-gray-400">{t("conv_free_color_label")}:</span>
      {Array.from(freeColors).sort().map(hex => (
        <span
          key={hex}
          className="w-5 h-5 rounded border-2 border-dashed border-red-400"
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

          {/* Undo / Clear buttons + Mode switching buttons */}
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

            {/* Separator */}
            <div className="w-px bg-gray-600 mx-1" />

            {/* Mode switching buttons */}
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
          <div className="flex gap-2 mb-2">
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
            className="max-h-80 overflow-y-auto dock-scrollbar"
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
