import { useEditorHistory } from "../../hooks/useEditorHistory";
import { useState, type ReactNode } from "react";
import { useConverterStore } from "../../stores/converter";
import type { DynamicMaterialRecipe, PaletteEntry } from "../../api/types";
import Slider from "../ui/Slider";
import Button from "../ui/Button";
import Switch from "../ui/Switch";
import CustomRecipeDialog from "../ui/CustomRecipeDialog";
import { useI18n } from "../../i18n/context";
import { cx, cardClass, groupHeaderClass, wellPadClass } from "../ui/panelPrimitives";
import MaterialLayerBenefitCurve from "./MaterialLayerBenefitCurve";
import SelectionToolPicker from "./SelectionToolPicker";

// ========== ToolbarGroup ==========

interface ToolbarGroupProps {
  label: string;
  children: ReactNode;
  contentClassName?: string;
}

/** Toolbar groups use neutral headings and spacing. */
function ToolbarGroup({ label, children, contentClassName }: ToolbarGroupProps) {
  return (
    <div className="flex flex-col gap-1" role="group" aria-label={label}>
      <span className={groupHeaderClass}>
        {label}
      </span>
      <div className={contentClassName ?? "flex min-h-9 flex-wrap items-center gap-1.5"}>{children}</div>
    </div>
  );
}

// ========== PaletteItem ==========

interface PaletteItemProps {
  entry: PaletteEntry;
  dynamicRecipe?: DynamicMaterialRecipe;
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
  dynamicRecipe,
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
  const dynamicAccessibleText = dynamicRecipe
    ? [
        `${t("palette_dynamic_actual_layers")} ${dynamicRecipe.actual_layer_count}`,
        `${t("palette_dynamic_saved_layers")} ${dynamicRecipe.padding_layer_count}`,
        `${t("palette_dynamic_selected_delta_e00")} ${dynamicRecipe.selected_delta_e00.toFixed(2)}`,
        `${t("palette_dynamic_fixed_delta_e00")} ${dynamicRecipe.fixed_max_delta_e00.toFixed(2)}`,
        `${t("palette_dynamic_best_delta_e00")} ${dynamicRecipe.best_range_delta_e00.toFixed(2)}`,
        `${t("palette_dynamic_sacrifice")} ${dynamicRecipe.delta_e00_sacrifice.toFixed(2)}`,
      ]
        .join("，")
    : "";
  const accessibleLabel = `${t("lut_grid_color_label").replace("{hex}", entry.matched_hex)}，${entry.percentage.toFixed(1)}%${isRemapped ? `，${t("palette_replaced_label").replace("{hex}", `#${remappedHex}`)}` : ""}${dynamicAccessibleText ? `，${dynamicAccessibleText}` : ""}`;

  // Border priority: isFreeColor > isRemapped > default
  const borderClass = isFreeColor
    ? "border-2 border-dashed border-red-400"
    : isRemapped
      ? "border border-yellow-500"
      : "border border-slate-600";

  // Compact block mode (no height slider)
  if (!showHeightSlider) {
    return (
      <div
        role="button"
        tabIndex={0}
        aria-label={accessibleLabel}
        aria-pressed={isSelected}
        onClick={onSelect}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onSelect();
          }
        }}
        className={`relative flex w-full min-w-0 flex-col items-center gap-1 rounded-[10px] px-1.5 py-2 cursor-pointer border transition-all duration-150 ${
          isSelected
            ? "border-amber-400 bg-amber-400/10"
            : "border-transparent hover:border-[color:var(--surface-card-outline)] hover:bg-[var(--nav-chip-hover)]"
        }`}
      >
        <span
          className={`inline-block h-[clamp(1.4rem,2vw,1.75rem)] w-[clamp(1.4rem,2vw,1.75rem)] rounded-md ${borderClass}`}
          style={{ backgroundColor: `#${displayHex}` }}
          title={`#${displayHex}`}
        />
        <span className="text-[clamp(0.55rem,0.75vw,0.625rem)] tabular-nums leading-none text-slate-500 dark:text-slate-400">
          {entry.percentage.toFixed(1)}%
        </span>
        {dynamicRecipe && (
          <DynamicMaterialRecipeMetrics recipe={dynamicRecipe} />
        )}
      </div>
    );
  }

  // Vertical compact block with height slider (relief mode, 3-col grid)
  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={accessibleLabel}
      aria-pressed={isSelected}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className={`relative flex h-full min-h-0 flex-col gap-2 rounded-[10px] px-2.5 py-2 cursor-pointer border transition-all duration-150 ${
        isSelected
          ? "border-amber-400 bg-amber-400/10"
          : "border-transparent hover:border-[color:var(--surface-card-outline)] hover:bg-[var(--nav-chip-hover)]"
      }`}
    >
      {/* Top row: swatch + percentage */}
      <div className="flex items-center gap-1.5">
        <span
          className={`inline-block h-[clamp(1.25rem,1.7vw,1.5rem)] w-[clamp(1.25rem,1.7vw,1.5rem)] shrink-0 rounded-md ${borderClass}`}
          style={{ backgroundColor: `#${displayHex}` }}
          title={`#${displayHex}`}
        />
        <span className="truncate text-[clamp(0.55rem,0.75vw,0.625rem)] tabular-nums text-slate-500 dark:text-slate-400">
          {entry.percentage.toFixed(1)}%
        </span>
      </div>
      {dynamicRecipe && (
        <DynamicMaterialRecipeMetrics recipe={dynamicRecipe} />
      )}
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

function DynamicMaterialRecipeMetrics({
  recipe,
}: {
  recipe: DynamicMaterialRecipe;
}) {
  const { t } = useI18n();
  const metrics = [
    [t("palette_dynamic_actual_layers"), String(recipe.actual_layer_count)],
    [t("palette_dynamic_saved_layers"), String(recipe.padding_layer_count)],
    [t("palette_dynamic_selected_delta_e00"), recipe.selected_delta_e00.toFixed(2)],
    [t("palette_dynamic_fixed_delta_e00"), recipe.fixed_max_delta_e00.toFixed(2)],
    [t("palette_dynamic_best_delta_e00"), recipe.best_range_delta_e00.toFixed(2)],
    [t("palette_dynamic_sacrifice"), recipe.delta_e00_sacrifice.toFixed(2)],
  ] as const;

  return (
    <dl className="mt-1 grid w-full grid-cols-[minmax(0,1fr)_auto] gap-x-1.5 gap-y-0.5 border-t border-[color:var(--surface-divider)] pt-1.5 text-[9px] leading-tight">
      {metrics.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="truncate text-left text-slate-500 dark:text-slate-400">
            {label}
          </dt>
          <dd className="tabular-nums text-right font-medium text-slate-700 dark:text-slate-200">
            {value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function dynamicTargetHex(recipe: DynamicMaterialRecipe): string | null {
  if (recipe.target_srgb.length !== 3) {
    return null;
  }
  const channels: string[] = [];
  for (const channel of recipe.target_srgb) {
    if (!Number.isInteger(channel) || channel < 0 || channel > 255) {
      return null;
    }
    channels.push(channel.toString(16).padStart(2, "0"));
  }
  return channels.join("");
}

function normalizedPaletteTargetHex(value: string): string | null {
  const normalized = value.replace(/^#/, "").toLowerCase();
  return /^[0-9a-f]{6}$/.test(normalized) ? normalized : null;
}

// ========== FreeColorSummary ==========

function FreeColorSummary({ freeColors }: { freeColors: Set<string> }) {
  const { t } = useI18n();
  if (freeColors.size === 0) return null;
  return (
    <div className={cx(wellPadClass, "flex flex-wrap items-center gap-2")}>
      <span className="text-[clamp(0.65rem,0.8vw,0.7rem)] font-medium text-slate-500 dark:text-slate-400">{t("conv_free_color_label")}:</span>
      {Array.from(freeColors).sort().map(hex => (
        <span
          key={hex}
          className="h-6 w-6 rounded-md border-2 border-dashed border-red-400"
          style={{ backgroundColor: `#${hex}` }}
          title={`#${hex}`}
        />
      ))}
    </div>
  );
}

// ========== PalettePanel ==========

interface PalettePanelProps {
  showHoverMagnifier?: boolean;
  showHoverLayerDetails?: boolean;
  onToggleHoverMagnifier?: (checked: boolean) => void;
  onToggleHoverLayerDetails?: (checked: boolean) => void;
}

export default function PalettePanel({
  showHoverMagnifier = true,
  showHoverLayerDetails = true,
  onToggleHoverMagnifier,
  onToggleHoverLayerDetails,
}: PalettePanelProps) {
  const { t } = useI18n();
  const [recipeDialogOpen, setRecipeDialogOpen] = useState(false);
  const palette = useConverterStore((s) => s.palette);
  const materialDynamicRecipes = useConverterStore(
    (s) => s.materialDynamicRecipes,
  );
  const materialLayerBenefitCurve = useConverterStore(
    (s) => s.materialLayerBenefitCurve,
  );
  const materialLayerBenefitScope = useConverterStore(
    (s) => s.materialLayerBenefitScope,
  );
  const materialLayerBenefitPixelCount = useConverterStore(
    (s) => s.materialLayerBenefitPixelCount,
  );
  const selectedLutInfo = useConverterStore((s) => s.selectedLutInfo);
  const sessionId = useConverterStore((s) => s.sessionId);
  const color_layers = useConverterStore((s) => s.color_layers);
  const layer_height_mm = useConverterStore((s) => s.layer_height_mm);
  const selectedColor = useConverterStore((s) => s.selectedColor);
  const selectedColors = useConverterStore((s) => s.selectedColors);
  const toggleColorInSelection = useConverterStore((s) => s.toggleColorInSelection);
  const removeColorFromSelection = useConverterStore((s) => s.removeColorFromSelection);
  const enable_relief = useConverterStore((s) => s.enable_relief);
  const color_height_map = useConverterStore((s) => s.color_height_map);
  const updateColorHeight = useConverterStore((s) => s.updateColorHeight);
  const colorRemapMap = useConverterStore((s) => s.colorRemapMap);
  const recipeOverrides = useConverterStore((s) => s.recipe_overrides);
  const clearAllRemaps = useConverterStore((s) => s.clearAllRemaps);
  const clearSelection = useConverterStore((s) => s.clearSelection);
  const replacePreviewLoading = useConverterStore((s) => s.replacePreviewLoading);
  const heightmap_max_height = useConverterStore((s) => s.heightmap_max_height);
  const selectionMode = useConverterStore((s) => s.selectionMode);
  const selectionDocument = useConverterStore((s) => s.selectionDocument);
  const selectionBlinkEnabled = useConverterStore((s) => s.selectionBlinkEnabled);
  const toggleSelectionBlink = useConverterStore((s) => s.toggleSelectionBlink);
  const gradientSelection = useConverterStore((s) => s.gradientSelection);
  const selectedRegions = useConverterStore((s) => s.selectedRegions);
  const regionData = useConverterStore((s) => s.regionData);
  const removeRegionFromSelection = useConverterStore((s) => s.removeRegionFromSelection);
  const free_color_set = useConverterStore((s) => s.free_color_set);
  const toggleFreeColor = useConverterStore((s) => s.toggleFreeColor);
  const clearFreeColors = useConverterStore((s) => s.clearFreeColors);
  const regionReplacementCount = useConverterStore((s) => s.regionReplacementCount);
  const selectedColorList = Array.from(selectedColors);
  const selectAllRecipeRegionIds =
    selectionMode === 'select-all' &&
    selectedColorList.length > 0 &&
    gradientSelection?.kind !== 'region'
      ? selectedColorList.map((hex) => `__select_all_color__:${hex.replace(/^#/, "").toLowerCase()}`)
      : [];
  const activeRecipeRegionIds =
    selectionDocument && selectionDocument.selected_component_count > 0
      ? selectionDocument.region_ids
      : selectionMode === 'select-all'
      ? selectAllRecipeRegionIds
      : selectedRegions.length > 0
      ? selectedRegions.map((region) => region.regionId)
      : (regionData?.regionId ? [regionData.regionId] : selectAllRecipeRegionIds);
  const activeSelectAllColorHex =
    selectionMode === 'select-all'
      ? (selectedColor && selectedColors.has(selectedColor)
        ? selectedColor
        : selectedColorList[selectedColorList.length - 1] ?? null)
      : null;
  // Custom recipe lets users manually compose the layer stack for a region;
  // it is LUT-agnostic. Forward-model prediction is an optional add-on that
  // degrades gracefully inside the dialog when the LUT has no predictor.
  // 自定义配方是手动指定区域的叠层耗材，与 LUT 预测能力无关；预测按钮
  // 在无预测模型的 LUT 下会在对话框内优雅降级提示。
  const canUseCustomRecipe = activeRecipeRegionIds.length > 0;
  const customRecipeDisabledHint = !canUseCustomRecipe
    ? t("recipe_custom_disabled_region")
    : undefined;

  const hasRemaps =
    Object.keys(colorRemapMap).length > 0 ||
    regionReplacementCount > 0 ||
    recipeOverrides.length > 0;
  const { canUndo: canUndoHistory, canRedo: canRedoHistory, undo: undoColorRemap, redo: redoColorRemap } = useEditorHistory();
  const dynamicRecipesByTarget = new Map<string, DynamicMaterialRecipe>();
  for (const recipe of materialDynamicRecipes) {
    const targetHex = dynamicTargetHex(recipe);
    if (targetHex && !dynamicRecipesByTarget.has(targetHex)) {
      dynamicRecipesByTarget.set(targetHex, recipe);
    }
  }
  const hasDynamicRecipeData = palette.some((entry) => {
    const targetHex = normalizedPaletteTargetHex(entry.quantized_hex);
    return targetHex !== null && dynamicRecipesByTarget.has(targetHex);
  });

  const handleSelect = (hex: string) => {
    switch (selectionMode) {
      case 'current':
      case 'multi-select':
      case 'region':
        break;
      case 'select-all':
        toggleColorInSelection(hex);
        break;
    }
  };

  // Multi-select highlights colors that have at least one region selected
  const multiSelectHexSet = selectionMode === 'multi-select'
    ? new Set(selectedRegions.map((r) => r.colorHex.replace(/^#/, "")))
    : null;

  // When the current select-all set was populated from a gradient *region*
  // (not a whole group), the palette must NOT draw its usual "selected"
  // borders on those colour tiles. Each of the region's colours typically
  // appears elsewhere on the canvas too, so lighting up the tiles falsely
  // suggests "every instance of this colour is selected across the whole
  // image" — which is exactly the confusion users ran into: the preview
  // correctly showed only the region, but the palette made it look like a
  // whole-image multi-select.
  // 来源是"区域"的 select-all 不应把调色板色块渲染为选中态：同色在图上
  // 通常出现在多处，点亮色块会误导用户以为"全图这些色都被选中"，和预览
  // 上只点亮单个区域的事实不符。
  const isRegionScopedSelection = gradientSelection?.kind === 'region';

  const getIsSelected = (hex: string): boolean => {
    if (multiSelectHexSet) {
      return multiSelectHexSet.has(hex);
    }
    if (
      selectionMode === 'select-all' &&
      selectedColors.size > 0 &&
      !isRegionScopedSelection
    ) {
      return selectedColors.has(hex);
    }
    return selectedColor === hex;
  };

  return (
    <div className={cx(cardClass, "color-tools-panel flex h-full min-h-0 flex-col px-4 py-4")}>
      {palette.length === 0 ? (
        <p className="py-4 text-sm text-slate-500 dark:text-slate-400">
          {t("palette_no_data")}
        </p>
      ) : (
        <div
          className="dock-scrollbar min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1"
          data-testid="palette-content-scroll"
        >
          {/* Toolbar: selected color detail + grouped action buttons */}
          <div className="shrink-0 flex flex-col gap-1.5">
            {/* Inline selected color swatches */}
            {selectedColor && (() => {
              const selectedEntry = palette.find(
                (e) => e.matched_hex === selectedColor
              );
              if (!selectedEntry) return null;
              const remapped = colorRemapMap[selectedColor];
              return (
                <div className="flex flex-wrap items-center gap-1.5">
                  <span
                    className="inline-block h-5 w-5 shrink-0 rounded-md border border-slate-300/80 dark:border-slate-600/80"
                    style={{ backgroundColor: `#${selectedEntry.quantized_hex}` }}
                    title={`${t("palette_quantized")}: #${selectedEntry.quantized_hex}`}
                  />
                  <span className="text-[10px] text-slate-400">{"\u2192"}</span>
                  <span
                    className="inline-block h-5 w-5 shrink-0 rounded-md border border-slate-300/80 dark:border-slate-600/80"
                    style={{ backgroundColor: `#${selectedEntry.matched_hex}` }}
                    title={`${t("palette_matched")}: #${selectedEntry.matched_hex}`}
                  />
                  {remapped && (
                    <>
                      <span className="text-[10px] text-slate-400">{"\u2192"}</span>
                      <span
                        className="inline-block h-5 w-5 shrink-0 rounded-md border-2 border-yellow-500"
                        style={{ backgroundColor: `#${remapped}` }}
                        title={`${t("palette_replaced_label")}: #${remapped}`}
                      />
                    </>
                  )}
                </div>
              );
            })()}

            {/* Grouped toolbar: auto-fit grid keeps every group card the same width */}
            <div className="grid grid-cols-[repeat(auto-fit,minmax(14rem,1fr))] gap-2">
              <ToolbarGroup label={t("palette_group_history")}>
                <Button
                  label={t("palette_undo")}
                  variant="secondary"
                  size="sm"
                  onClick={undoColorRemap}
                  disabled={!canUndoHistory || replacePreviewLoading}
                />
                <Button
                  label={t("palette_redo")}
                  variant="secondary"
                  size="sm"
                  onClick={redoColorRemap}
                  disabled={!canRedoHistory || replacePreviewLoading}
                />
                <Button
                  label={t("palette_clear_remaps")}
                  variant="secondary"
                  size="sm"
                  onClick={clearAllRemaps}
                  disabled={!hasRemaps || replacePreviewLoading}
                />
              </ToolbarGroup>

              <ToolbarGroup
                label={t("palette_group_mode")}
                contentClassName="grid min-h-9 grid-cols-[repeat(auto-fit,minmax(6.75rem,1fr))] items-center gap-1.5"
              >
                <SelectionToolPicker />
                <Button
                  label={t("palette_clear_selection")}
                  variant="secondary"
                  size="sm"
                  onClick={clearSelection}
                  className="w-full"
                />
                <label
                  className="col-span-full mt-1 flex items-center justify-between gap-3 border-t border-slate-200 py-2 text-xs text-slate-600 dark:border-slate-700 dark:text-slate-300"
                  title={t("palette_selection_blink_title")}
                >
                  {t("palette_selection_blink")}
                  <Switch
                    checked={selectionBlinkEnabled}
                    onChange={toggleSelectionBlink}
                    ariaLabel={t("palette_selection_blink")}
                  />
                </label>
              </ToolbarGroup>

              <ToolbarGroup label={t("palette_group_free")}>
                <Button
                  label={t("conv_free_color_btn")}
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    if (selectedColor) toggleFreeColor(selectedColor);
                  }}
                  disabled={selectedColor === null}
                />
                <Button
                  label={t("conv_free_color_clear_btn")}
                  variant="secondary"
                  size="sm"
                  onClick={clearFreeColors}
                  disabled={free_color_set.size === 0}
                />
              </ToolbarGroup>

              <ToolbarGroup label={t("palette_group_recipe")}>
                <Button
                  label={t("recipe_custom_button")}
                  variant="secondary"
                  size="sm"
                  onClick={() => setRecipeDialogOpen(true)}
                  disabled={!canUseCustomRecipe}
                  title={customRecipeDisabledHint}
                />
              </ToolbarGroup>

              <ToolbarGroup label={t("viewer_hover_toggle_group")}>
                <label className="flex items-center gap-1.5 whitespace-nowrap text-[11px] text-slate-600 dark:text-slate-300">
                  <Switch
                    checked={showHoverMagnifier}
                    onChange={(checked) => onToggleHoverMagnifier?.(checked)}
                    ariaLabel={t("viewer_hover_toggle_magnifier")}
                  />
                  {t("viewer_hover_toggle_magnifier")}
                </label>
                <label className="flex items-center gap-1.5 whitespace-nowrap text-[11px] text-slate-600 dark:text-slate-300">
                  <Switch
                    checked={showHoverLayerDetails}
                    onChange={(checked) => onToggleHoverLayerDetails?.(checked)}
                    ariaLabel={t("viewer_hover_toggle_layers")}
                  />
                  {t("viewer_hover_toggle_layers")}
                </label>
              </ToolbarGroup>
            </div>
          </div>

          <div className="shrink-0 flex flex-col gap-1.5">
            {selectionDocument && selectionDocument.selected_component_count > 0 && (
              <div className={cx(wellPadClass, "flex items-center gap-2 text-[11px] text-slate-600 dark:text-slate-300")}>
                <span>{t("palette_selected_blocks").replace("{count}", String(selectionDocument.selected_component_count))}</span>
                <span aria-hidden="true">·</span>
                <span>{t("palette_selected_colors").replace("{count}", String(selectionDocument.selected_color_hexes.length))}</span>
              </div>
            )}
            {/* Select-all multi-color indicator. Hidden when the selection
                came from a gradient region — the amber "N colours selected"
                chip strip duplicates the already-confusing selection-border
                rendering on the palette and reinforces the wrong impression
                that the whole image will be acted on. The Gradient Groups
                panel itself still shows which region is active. */}
            {selectionMode === 'select-all' &&
              selectedColors.size > 0 &&
              !isRegionScopedSelection && (
            <div className={cx(wellPadClass, "flex min-h-11 flex-nowrap items-center gap-2 overflow-hidden")}>
              <span className="shrink-0 whitespace-nowrap text-[clamp(0.55rem,0.75vw,0.625rem)] font-medium text-amber-500 dark:text-amber-400">
                {t("palette_multi_select_count").replace("{count}", String(selectedColors.size))}
              </span>
              <div className="dock-scrollbar flex min-w-0 flex-1 flex-nowrap items-center gap-1.5 overflow-x-auto overflow-y-hidden py-0.5">
                {Array.from(selectedColors).map((hex) => (
                  <button
                    key={hex}
                    type="button"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => removeColorFromSelection(hex)}
                    className="h-5 w-5 shrink-0 rounded-md border-2 border-amber-400 transition-transform hover:scale-110"
                    style={{ backgroundColor: `#${hex}` }}
                    title={`#${hex} — ${t("palette_multi_select_click_remove")}`}
                  />
                ))}
              </div>
            </div>
          )}

            {/* Multi-select region indicator */}
            {selectionMode === 'multi-select' && selectedRegions.length > 0 && (
            <div className={cx(wellPadClass, "flex flex-wrap items-center gap-2")}>
              <span className="text-[clamp(0.55rem,0.75vw,0.625rem)] font-medium text-amber-500 dark:text-amber-400">
                {t("palette_multi_select_region_count").replace("{count}", String(selectedRegions.length))}
              </span>
              {selectedRegions.map((region) => {
                const hex = region.colorHex.replace(/^#/, "");
                return (
                  <button
                    key={region.regionId}
                    type="button"
                    onClick={() => removeRegionFromSelection(region.regionId)}
                    className="h-5 w-5 rounded-md border-2 border-amber-400 transition-transform hover:scale-110"
                    style={{ backgroundColor: `#${hex}` }}
                    title={`#${hex} (${region.pixelCount}px) — ${t("palette_multi_select_click_remove")}`}
                  />
                );
              })}
            </div>
          )}

            {/* Free color summary */}
            <FreeColorSummary freeColors={free_color_set} />
          </div>

          <MaterialLayerBenefitCurve
            points={materialLayerBenefitCurve}
            scope={materialLayerBenefitScope}
            pixelCount={materialLayerBenefitPixelCount}
          />

          {/* Palette items */}
          <div
            role="listbox"
            aria-label={t("palette_list_label")}
          >
            <div
              className={
                hasDynamicRecipeData
                  ? "grid grid-cols-[repeat(auto-fit,minmax(12rem,1fr))] gap-2"
                  : enable_relief
                  ? "grid grid-cols-[repeat(auto-fit,minmax(7rem,1fr))] gap-2"
                  : "grid grid-cols-[repeat(auto-fit,minmax(3.4rem,1fr))] gap-2"
              }
            >
              {palette.map((entry) => (
                <PaletteItem
                  key={entry.matched_hex}
                  entry={entry}
                  dynamicRecipe={
                    dynamicRecipesByTarget.get(
                      normalizedPaletteTargetHex(entry.quantized_hex) ?? "",
                    )
                  }
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
      <CustomRecipeDialog
        open={recipeDialogOpen}
        sessionId={sessionId ?? ""}
        palette={(selectedLutInfo?.palette ?? []).map((entry) => ({
          color: entry.color_name ?? entry.color,
          material: entry.material,
          hex: entry.hex_color ?? null,
        }))}
        regionIds={activeRecipeRegionIds}
        currentRegionColorHex={
          selectionMode === 'select-all'
            ? (activeSelectAllColorHex ? `#${activeSelectAllColorHex}` : null)
            : selectedRegions.length > 0
            ? selectedRegions[selectedRegions.length - 1]?.colorHex ?? null
            : regionData?.colorHex ?? null
        }
        colorLayers={color_layers ?? selectedLutInfo?.max_color_layers ?? 5}
        layerHeightMm={layer_height_mm ?? selectedLutInfo?.layer_height_mm ?? 0.08}
        layerOrder={selectedLutInfo?.layer_order ?? "Top2Bottom"}
        baseChannelIdx={selectedLutInfo?.base_channel_idx ?? 0}
        onClose={() => setRecipeDialogOpen(false)}
      />
    </div>
  );
}
