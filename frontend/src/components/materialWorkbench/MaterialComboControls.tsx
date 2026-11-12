import { useMemo, useState } from "react";
import { useShallow } from "zustand/react/shallow";

import { useI18n } from "../../i18n/context";
import { tRuntime } from "../../i18n/runtime";
import {
  MATERIAL_DYNAMIC_LAYER_COUNT_MAX,
  MATERIAL_DYNAMIC_LAYER_COUNT_MIN,
  useConverterStore,
} from "../../stores/converter";
import {
  comboFromConverter,
  resolveBackingDirName,
  selectConverterMaterialSnapshot,
  useMaterialWorkbenchStore,
} from "../../stores/materialWorkbenchStore";
import Button from "../ui/Button";
import Checkbox from "../ui/Checkbox";
import Dropdown from "../ui/Dropdown";
import MaterialPickerDialog from "../ui/MaterialPickerDialog";
import Slider from "../ui/Slider";
import {
  cardDividerClass,
  cardPadClass,
  groupHeaderClass,
  workstationInputClass,
} from "../ui/panelPrimitives";
import { useSavedMaterialLibrary } from "./useSavedMaterialLibrary";

const LAYER_HEIGHT_OPTIONS = [
  { label: "0.04 mm", value: "0.04" },
  { label: "0.08 mm", value: "0.08" },
  { label: "0.10 mm", value: "0.1" },
];
const SUMMARY_LIMIT = 3;

interface MaterialComboControlsProps {
  /** Lock inputs while a request for the current combination runs. */
  disabled?: boolean;
  /** Offer the white/black substrate choice (conversion always prints on white). */
  showSubstrate?: boolean;
}

/**
 * Material-combination inputs shared by the Gamut Coverage and Solver Cache tabs.
 * 色域覆盖与求解缓存标签页共用的耗材组合输入区。
 */
export default function MaterialComboControls({
  disabled = false,
  showSubstrate = true,
}: MaterialComboControlsProps) {
  const { t } = useI18n();
  const library = useSavedMaterialLibrary();
  const [pickerOpen, setPickerOpen] = useState(false);
  const workbench = useMaterialWorkbenchStore();
  const converterSnapshot = useConverterStore(useShallow(selectConverterMaterialSnapshot));

  const nameLookup = useMemo(
    () => new Map(library.materials.map((item) => [item.directory_name, item.material_name])),
    [library.materials],
  );
  const selectedNames = workbench.materialDirectoryNames;
  const displayName = (dirName: string) => nameLookup.get(dirName) ?? dirName;
  const hiddenCount = Math.max(0, selectedNames.length - SUMMARY_LIMIT);
  const backingOptions = selectedNames.map((dirName, index) => ({
    label: `${index + 1}. ${displayName(dirName)}`,
    value: dirName,
  }));
  const resolvedBacking = resolveBackingDirName(selectedNames, workbench.backingDirName) ?? "";
  const isDynamic = workbench.layerMode === "dynamic";

  return (
    <section data-testid="material-combo-controls" className={`${cardPadClass} flex flex-col gap-4`}>
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-2">
          <p className={groupHeaderClass}>{t("material_workbench_materials_header")}</p>
          <Button
            label={t("material_workbench_use_converter")}
            variant="secondary"
            size="sm"
            disabled={disabled || converterSnapshot.selectedMaterialDirNames.length === 0}
            onClick={() => workbench.applySelection(comboFromConverter(converterSnapshot))}
          />
        </div>
        <button
          type="button"
          onClick={() => setPickerOpen(true)}
          disabled={disabled}
          data-testid="material-combo-picker-trigger"
          className={`${workstationInputClass} flex items-center justify-between gap-3 text-left`}
        >
          <span className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
            {selectedNames.length === 0 ? (
              <span className="text-slate-400 dark:text-slate-500">
                {t("basic_material_picker_open")}
              </span>
            ) : (
              <>
                {selectedNames.slice(0, SUMMARY_LIMIT).map((dirName) => (
                  <span
                    key={dirName}
                    className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200"
                  >
                    {displayName(dirName)}
                  </span>
                ))}
                {hiddenCount > 0 ? (
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    {tRuntime("basic_material_picker_summary_more", { count: hiddenCount })}
                  </span>
                ) : null}
              </>
            )}
          </span>
          <span className="shrink-0 text-xs text-slate-400 dark:text-slate-500">
            {t("basic_material_selected_count")}: {selectedNames.length}
          </span>
        </button>
        <MaterialPickerDialog
          open={pickerOpen}
          materials={library.materials}
          loading={library.loading}
          loadError={library.loadError}
          initialSelected={selectedNames}
          onConfirm={(next) => {
            workbench.setMaterialDirectoryNames(next);
            setPickerOpen(false);
          }}
          onCancel={() => setPickerOpen(false)}
          onRetry={library.retry}
        />
      </div>

      <div className={`${cardDividerClass} flex flex-col gap-3 pt-4`}>
        <p className={groupHeaderClass}>{t("material_workbench_layers_header")}</p>
        <Checkbox
          label={t("basic_material_dynamic_layer_count_label")}
          tooltip={t("basic_material_dynamic_layer_count_hint")}
          checked={isDynamic}
          disabled={disabled}
          onChange={(checked) => workbench.setLayerMode(checked ? "dynamic" : "fixed")}
        />
        {isDynamic ? (
          <>
            <Slider
              label={t("basic_material_min_layer_count_label")}
              value={workbench.minLayerCount}
              min={MATERIAL_DYNAMIC_LAYER_COUNT_MIN}
              max={MATERIAL_DYNAMIC_LAYER_COUNT_MAX}
              step={1}
              disabled={disabled}
              onChange={workbench.setMinLayerCount}
            />
            <Slider
              label={t("basic_material_max_layer_count_label")}
              value={workbench.maxLayerCount}
              min={MATERIAL_DYNAMIC_LAYER_COUNT_MIN}
              max={MATERIAL_DYNAMIC_LAYER_COUNT_MAX}
              step={1}
              disabled={disabled}
              onChange={workbench.setMaxLayerCount}
            />
          </>
        ) : (
          <Slider
            label={t("basic_material_layer_count_label")}
            value={workbench.layerCount}
            min={MATERIAL_DYNAMIC_LAYER_COUNT_MIN}
            max={MATERIAL_DYNAMIC_LAYER_COUNT_MAX}
            step={1}
            disabled={disabled}
            onChange={workbench.setLayerCount}
          />
        )}
        <Dropdown
          label={t("basic_material_layer_height_label")}
          value={String(workbench.layerHeightMm)}
          options={LAYER_HEIGHT_OPTIONS}
          disabled={disabled}
          onChange={(value) => workbench.setLayerHeightMm(Number(value))}
        />
        {showSubstrate ? (
          <Dropdown
            label={t("material_recipe_substrate_label")}
            value={workbench.substrate}
            options={[
              { label: t("material_recipe_substrate_white"), value: "white" },
              { label: t("material_recipe_substrate_black"), value: "black" },
            ]}
            disabled={disabled}
            onChange={(value) => workbench.setSubstrate(value === "black" ? "black" : "white")}
          />
        ) : null}
        {isDynamic ? (
          <Dropdown
            label={t("basic_material_backing_label")}
            tooltip={t("basic_material_backing_hint")}
            value={resolvedBacking}
            options={backingOptions}
            disabled={disabled || selectedNames.length === 0}
            placeholder={t("basic_material_backing_placeholder")}
            onChange={(value) => workbench.setBackingDirName(value || null)}
          />
        ) : null}
      </div>
    </section>
  );
}
