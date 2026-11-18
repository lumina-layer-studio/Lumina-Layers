import { useEffect, useState, type ReactNode } from "react";
import LutPickerDialog, { type LutPickerBrand, type LutPickerOption } from "../ui/LutPickerDialog";
import { cx, workstationPickerTriggerClass, workstationFieldLabelClass } from "../ui/panelPrimitives";
import type { ResourceSelectionCheck } from "../../stores/converter/resourceSelection";
import { useI18n } from "../../i18n/context";
import { useFilamentMarket } from "../../hooks/useFilamentMarket";
import { localLutIdentity } from "../../utils/libraryFilamentIdentity";
import type { LocalLutVersion } from "../../api/types";

interface LegacyLutOption {
  label: string;
  value: string;
  brand?: string;
  materialType?: string;
  display?: Record<string, unknown> | null;
  searchTokens?: string[];
  mode?: string;
  group?: string;
  logo?: string;
  localVersion?: LocalLutVersion | null;
}

interface LegacyLutOptionGroup {
  label: string;
  options: LegacyLutOption[];
}

interface LegacyBrandInfo {
  displayName: string;
  materialTypes: string[];
  vendor: string;
}

interface LegacyLutSelectorProps {
  manufacturer: string;
  lutName: string;
  selectedLutNames?: string[];
  manufacturerOptions: LegacyLutOption[];
  groupedLutOptions: LegacyLutOptionGroup[];
  /** Catalog-wide options for search and selections outside the visible brand. */
  allLutOptions?: LegacyLutOption[];
  brandInfo?: LegacyBrandInfo | null;
  colorModeSummary?: ReactNode;
  onManufacturerChange: (value: string) => void;
  onLutChange: (value: string) => void;
  onLutSelectionChange?: (values: string[]) => void;
  onRefresh: () => void;
  onUploadClick: () => void;
  loading?: boolean;
  lutLoading?: boolean;
  refreshing?: boolean;
  loadError?: string | null;
  uploading?: boolean;
  uploadError?: string | null;
  uploadSuccess?: string | null;
  onDismissUploadSuccess?: () => void;
  onPickerOpen?: () => void;
  resumeSelection?: { id: number; selected: string[] } | null;
  onCalibrate?: (selected: string[]) => void;
  onPickerClose?: () => void;
  onInstalled?: () => void | Promise<unknown>;
  checkSelection?: (values: string[]) => ResourceSelectionCheck;
  onApplySelection?: (values: string[], allowModeChange: boolean) => string | null;
  labels: {
    manufacturer: string;
    manufacturerPlaceholder: string;
    lutPlaceholder: string;
    refreshTooltip: string;
    upload: string;
    loadingHint: string;
    noBrandHint: string;
    selectedCount?: string;
    brandInfo?: string;
    materialType?: string;
    vendor?: string;
    /** Dialog-specific labels (fall back to base labels when omitted). */
    dialogTitle?: string;
    dialogSearchPlaceholder?: string;
    dialogAllGroups?: string;
    dialogNoMatch?: string;
    dialogDeselectAll?: string;
    dialogConfirm?: string;
    dialogCancel?: string;
    openPicker?: string;
    change?: string;
    selectionSummary?: string;
    moreSelected?: string;
  };
}

// Flatten groups preserving order, deduplicating by value.
function flattenOptions(groups: LegacyLutOptionGroup[]): LegacyLutOption[] {
  const seen = new Set<string>();
  const result: LegacyLutOption[] = [];
  for (const group of groups) {
    for (const option of group.options) {
      if (seen.has(option.value)) continue;
      seen.add(option.value);
      result.push(option);
    }
  }
  return result;
}

// Build picker options from grouped LUT options.
function buildPickerOptions(groups: LegacyLutOptionGroup[]): LutPickerOption[] {
  const seen = new Set<string>();
  const result: LutPickerOption[] = [];
  for (const group of groups) {
    for (const option of group.options) {
      if (seen.has(option.value)) continue;
      seen.add(option.value);
      result.push({ ...option, group: group.label });
    }
  }
  return result;
}

export default function LegacyLutSelector({
  manufacturer,
  lutName,
  selectedLutNames,
  manufacturerOptions,
  groupedLutOptions,
  allLutOptions,
  brandInfo,
  colorModeSummary,
  onManufacturerChange,
  onLutChange,
  onLutSelectionChange,
  onRefresh,
  onUploadClick,
  loading = false,
  lutLoading = false,
  refreshing = false,
  loadError,
  uploading,
  uploadError,
  uploadSuccess,
  onDismissUploadSuccess,
  onPickerOpen,
  resumeSelection,
  onCalibrate,
  onPickerClose,
  onInstalled,
  checkSelection,
  onApplySelection,
  labels,
}: LegacyLutSelectorProps) {
  const { lang } = useI18n();
  const market = useFilamentMarket();
  const [dialogOpen, setDialogOpen] = useState(false);
  useEffect(() => {
    if (resumeSelection) setDialogOpen(true);
  }, [resumeSelection]);

  const catalogOptions = allLutOptions ?? flattenOptions(groupedLutOptions);
  const pickerOptions = buildPickerOptions(groupedLutOptions);

  const selectedSet = new Set(
    selectedLutNames && selectedLutNames.length > 0
      ? selectedLutNames
      : lutName
        ? [lutName]
        : [],
  );
  const optionsByName = new Map(catalogOptions.map((option) => [option.value, option]));
  const selectedOptions = Array.from(selectedSet, (value) =>
    optionsByName.get(value) ?? { value, label: value },
  );
  const selectedCount = selectedOptions.length;

  // Build brand list for picker sidebar
  const pickerBrands: LutPickerBrand[] = manufacturerOptions.map((opt) => ({
    value: opt.value,
    label: opt.label,
    display: opt.display,
    logo: opt.logo,
    displayName: brandInfo && opt.value === manufacturer ? brandInfo.displayName : undefined,
    materialTypes: brandInfo && opt.value === manufacturer ? brandInfo.materialTypes : undefined,
    vendor: brandInfo && opt.value === manufacturer ? brandInfo.vendor : undefined,
  }));

  const closePicker = () => { setDialogOpen(false); onPickerClose?.(); };
  const handleConfirm = (lutNames: string[], allowModeChange = false) => {
    if (onApplySelection) {
      const error = onApplySelection(lutNames, allowModeChange);
      if (error) return error;
      closePicker();
      return;
    }
    setDialogOpen(false);
    if (onLutSelectionChange) {
      onLutSelectionChange(lutNames);
    } else if (lutNames.length > 0) {
      onLutChange(lutNames[0]);
    }
  };

  const primaryOption = selectedOptions[0];
  const primaryIdentity = primaryOption && localLutIdentity(primaryOption.brand, primaryOption.label, lang, primaryOption.display, market);
  const primaryMetadata = primaryOption && primaryIdentity
    ? [primaryIdentity.brand, primaryOption.materialType]
      .filter((value): value is string => !!value && !primaryIdentity.name.toLowerCase().includes(value.toLowerCase()))
      .join(" · ")
    : "";
  const selectionSummary = (labels.selectionSummary ?? "Selected {count} LUTs")
    .replace("{count}", String(selectedCount));
  const moreSelected = (labels.moreSelected ?? "+{count} more")
    .replace("{count}", String(selectedCount - 1));

  // Empty states describe the next selection step.
  const triggerEmpty = !manufacturer;
  const triggerPlaceholder = loading
    ? labels.loadingHint
    : triggerEmpty
      ? labels.manufacturerPlaceholder
      : labels.lutPlaceholder;

  return (
    <div className="flex flex-col gap-2">
      {/* Brand / LUT label row */}
      <span className={workstationFieldLabelClass}>{labels.manufacturer}</span>

      {/* Keep the collapsed selection compact; the dialog owns the full list. */}
      <button
        type="button"
        disabled={loading && manufacturerOptions.length === 0}
        onClick={() => { onPickerOpen?.(); setDialogOpen(true); }}
        data-testid="lut-picker-trigger"
        aria-haspopup="dialog"
        aria-expanded={dialogOpen}
        className={cx(
          workstationPickerTriggerClass,
          "flex min-h-11 items-center justify-between gap-3 text-left",
          triggerEmpty && "text-slate-400 dark:text-slate-500",
        )}
      >
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="truncate text-sm font-medium">
            {selectedCount > 1 ? selectionSummary : primaryIdentity?.name ?? triggerPlaceholder}
          </span>
          {primaryOption && (
            <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
              {selectedCount > 1 ? (
                <>
                  <span className="min-w-0 flex-1 truncate">{primaryIdentity?.name}</span>
                  <span className="shrink-0">{moreSelected}</span>
                </>
              ) : primaryMetadata ? <span>{primaryMetadata}</span> : null}
              {colorModeSummary}
            </span>
          )}
        </span>
        {selectedCount > 0 && (
          <span className="shrink-0 text-xs font-medium text-blue-600 dark:text-blue-400">
            {labels.change ?? labels.openPicker ?? labels.manufacturer}
          </span>
        )}
      </button>

      {/* The sr-only live region so screen readers still announce changes. */}
      <div className="sr-only" aria-live="polite">
        {labels.selectedCount ?? "Selected"}: {selectedCount}
      </div>

      <LutPickerDialog
        open={dialogOpen}
        brands={pickerBrands}
        lutOptions={pickerOptions}
        catalogOptions={allLutOptions?.map((opt) => ({ ...opt, group: opt.group ?? opt.mode ?? "" }))}
        selectedBrand={manufacturer}
        initialSelectedLuts={
          resumeSelection?.selected ?? (selectedLutNames && selectedLutNames.length > 0
            ? selectedLutNames
            : lutName ? [lutName] : [])
        }
        onBrandChange={(brand) => {
          onManufacturerChange(brand);
        }}
        onConfirm={handleConfirm}
        onCancel={closePicker}
        onUploadClick={onUploadClick}
        onCalibrate={onCalibrate ? (selected) => { onCalibrate(selected); setDialogOpen(false); } : undefined}
        onRefresh={onRefresh}
        loading={loading}
        lutLoading={lutLoading}
        refreshing={refreshing}
        loadError={loadError}
        uploading={uploading}
        uploadError={uploadError}
        uploadSuccess={uploadSuccess}
        onDismissUploadSuccess={onDismissUploadSuccess}
        onInstalled={onInstalled}
        checkSelection={checkSelection}
        labels={{
          title: labels.dialogTitle ?? labels.manufacturer,
          searchPlaceholder: labels.dialogSearchPlaceholder ?? labels.lutPlaceholder,
          allGroups: labels.dialogAllGroups ?? "全部",
          brandLabel: labels.manufacturer,
          upload: labels.upload,
          refreshTooltip: labels.refreshTooltip,
          noBrandHint: labels.noBrandHint,
          noMatchHint: labels.dialogNoMatch ?? "无匹配结果",
          loadingHint: labels.loadingHint,
          selectedCount: labels.selectedCount ?? "已选",
          deselectAll: labels.dialogDeselectAll ?? "清空",
          confirm: labels.dialogConfirm ?? "确认",
          cancel: labels.dialogCancel ?? "取消",
          brandInfo: labels.brandInfo,
          materialType: labels.materialType,
          vendor: labels.vendor,
        }}
      />
    </div>
  );
}
