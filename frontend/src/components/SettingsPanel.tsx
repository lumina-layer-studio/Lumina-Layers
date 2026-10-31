import DisclosureChevron from "./ui/DisclosureChevron";
/**
 * SettingsPanel - System settings page.
 * 系统设置页面，包含切片软件设置和缓存清理功能。
 */

import { motion } from "framer-motion";
import { useState, useEffect, useCallback } from "react";
import { useI18n } from "../i18n/context";
import { apiErrorToVisibleMessage } from "../api/client";
import { clearCache, getMachineRegistryAssetUrl, getPrinters, getSlicers } from "../api/system";
import {
  MATERIAL_DELTA_E00_TOLERANCE_MAX,
  MATERIAL_DELTA_E00_TOLERANCE_MIN,
  MATERIAL_DELTA_E00_TOLERANCE_STEP,
  SVG_PIXELS_PER_MM_DEFAULT,
  SVG_PIXELS_PER_MM_MAX,
  SVG_PIXELS_PER_MM_MIN,
  SVG_PIXELS_PER_MM_STEP,
  SOLVER_CACHE_GRID_RESOLUTIONS,
  resolveBuildPlateSelection,
  useSettingsStore,
  type NozzleSize,
  type SolverCacheGridResolution,
} from "../stores/settingsStore";
import { useSlicerStore } from "../stores/slicerStore";
import type { PrinterInfo, SlicerOption } from "../api/types";
import {
  filterCompatiblePrinters,
  getDetectedSlicerIdForSoftware,
  resolveDeviceProfileOptionId,
  resolveNozzleSizeOption,
  resolvePrinterOptionId,
  resolveSlicerOptionId,
  supportsLayerConfigRanges,
} from "../utils/settingsOptionIds";
import {
  getBrowserNotificationPermission,
  requestBrowserNotificationPermission,
  type BrowserNotificationPermission,
} from "../utils/browserNotifications";
import { retryAsync } from "../utils/retryAsync";
import Button from "./ui/Button";
import Dropdown from "./ui/Dropdown";
import HelpDot from "./ui/HelpDot";
import Slider from "./ui/Slider";
import Switch from "./ui/Switch";
import SlicerLogo from "./slicer/SlicerLogo";
import MachineSelectionDialog from "./settings/MachineSelectionDialog";
import BuildPlateSelector from "./settings/BuildPlateSelector";
import Custom3mfTemplateSettings from "./settings/Custom3mfTemplateSettings";
import GeneratedFileDirectorySetting from "./settings/GeneratedFileDirectorySetting";
import HeaderNavAlignmentSetting from "./settings/HeaderNavAlignmentSetting";
import InterfaceScaleSetting from "./settings/InterfaceScaleSetting";
import SvgHoleCompensationSettings from "./sections/SvgHoleCompensationSettings";
import SettingsCategoryNav, {
  type SettingsCategory,
  type SettingsCategoryId,
} from "./settings/SettingsCategoryNav";
import {
  StatusBanner,
  dependentGroupClass,
  workstationInputClass,
} from "./ui/panelPrimitives";
import { WIKI_DOCS } from "../utils/wikiDocs";

const SETTINGS_OPTIONS_RETRY_ATTEMPTS = 6;
const SETTINGS_OPTIONS_RETRY_DELAY_MS = 1000;
const SETTINGS_OPTIONS_NOT_CANCELLED = () => false;

const COMPLETION_NOTIFICATION_STATUS: Record<
  BrowserNotificationPermission,
  {
    tone: "info" | "success" | "warning" | "error";
    translationKey: string;
  }
> = {
  granted: {
    tone: "success",
    translationKey: "settings.completion_notifications_granted",
  },
  denied: {
    tone: "error",
    translationKey: "settings.completion_notifications_denied",
  },
  default: {
    tone: "info",
    translationKey: "settings.completion_notifications_default",
  },
  unsupported: {
    tone: "warning",
    translationKey: "settings.completion_notifications_unsupported",
  },
  error: {
    tone: "error",
    translationKey: "settings.completion_notifications_request_failed",
  },
};

type CancellationCheck = () => boolean;

function formatSettingsOptionsLoadError(template: string, error: unknown): string {
  return template.replace("{error}", apiErrorToVisibleMessage(error));
}

export default function SettingsPanel() {
  const { t } = useI18n();

  const [clearing, setClearing] = useState(false);
  const [cacheResult, setCacheResult] = useState<string | null>(null);
  const [customSlicerPathInput, setCustomSlicerPathInput] = useState("");
  const [notificationPermission, setNotificationPermission] =
    useState<BrowserNotificationPermission>(() =>
      getBrowserNotificationPermission(),
    );
  const [notificationPermissionLoading, setNotificationPermissionLoading] =
    useState(false);
  const [activeCategory, setActiveCategory] =
    useState<SettingsCategoryId>("device");
  const [machineDialogOpen, setMachineDialogOpen] = useState(false);
  const [manualSetupOpen, setManualSetupOpen] = useState(false);

  // Printer list state (task 5.2)
  const [printers, setPrinters] = useState<PrinterInfo[]>([]);
  const [printersLoading, setPrintersLoading] = useState(true);
  const [printerOptionsError, setPrinterOptionsError] = useState<string | null>(null);

  // Slicer list state
  const [slicers, setSlicers] = useState<SlicerOption[]>([]);
  const [slicersLoading, setSlicersLoading] = useState(true);
  const [slicerOptionsError, setSlicerOptionsError] = useState<string | null>(null);

  // Store state (task 5.3)
  const printerModel = useSettingsStore((s) => s.printerModel);
  const language = useSettingsStore((s) => s.language);
  const setLanguage = useSettingsStore((s) => s.setLanguage);
  const setPrinterModel = useSettingsStore((s) => s.setPrinterModel);
  const slicerSoftware = useSettingsStore((s) => s.slicerSoftware);
  const setSlicerSoftware = useSettingsStore((s) => s.setSlicerSoftware);
  const deviceProfileId = useSettingsStore((s) => s.deviceProfileId);
  const setDeviceProfileId = useSettingsStore((s) => s.setDeviceProfileId);
  const buildPlateId = useSettingsStore((s) => s.buildPlateId);
  const buildPlateSelections = useSettingsStore((s) => s.buildPlateSelections);
  const setBuildPlateForMachine = useSettingsStore(
    (s) => s.setBuildPlateForMachine,
  );
  const customSlicerPath = useSettingsStore((s) => s.customSlicerPath);
  const nozzleSize = useSettingsStore((s) => s.nozzleSize);
  const setNozzleSize = useSettingsStore((s) => s.setNozzleSize);
  const enableBaseLayerHeightModifier = useSettingsStore(
    (s) => s.enableBaseLayerHeightModifier,
  );
  const setEnableBaseLayerHeightModifier = useSettingsStore(
    (s) => s.setEnableBaseLayerHeightModifier,
  );
  const enableWipeTowerAutoPlacement = useSettingsStore(
    (s) => s.enableWipeTowerAutoPlacement,
  );
  const setEnableWipeTowerAutoPlacement = useSettingsStore(
    (s) => s.setEnableWipeTowerAutoPlacement,
  );
  const setLastBedLabel = useSettingsStore((s) => s.setLastBedLabel);
  const syncToBackend = useSettingsStore((s) => s.syncToBackend);
  const enableWittyLoading = useSettingsStore((s) => s.enableWittyLoading);
  const setEnableWittyLoading = useSettingsStore((s) => s.setEnableWittyLoading);
  const enableCompletionNotifications = useSettingsStore(
    (s) => s.enableCompletionNotifications,
  );
  const setEnableCompletionNotifications = useSettingsStore(
    (s) => s.setEnableCompletionNotifications,
  );
  const enableSmoothVectorPreview = useSettingsStore(
    (s) => s.enableSmoothVectorPreview,
  );
  const setEnableSmoothVectorPreview = useSettingsStore(
    (s) => s.setEnableSmoothVectorPreview,
  );
  const preserveUploadFilenameFor3mf = useSettingsStore(
    (s) => s.preserveUploadFilenameFor3mf,
  );
  const setPreserveUploadFilenameFor3mf = useSettingsStore(
    (s) => s.setPreserveUploadFilenameFor3mf,
  );
  const enableSolverCacheGridSelection = useSettingsStore(
    (s) => s.enableSolverCacheGridSelection,
  );
  const setEnableSolverCacheGridSelection = useSettingsStore(
    (s) => s.setEnableSolverCacheGridSelection,
  );
  const solverCacheGridResolution = useSettingsStore(
    (s) => s.solverCacheGridResolution,
  );
  const setSolverCacheGridResolution = useSettingsStore(
    (s) => s.setSolverCacheGridResolution,
  );
  const svgPixelsPerMm = useSettingsStore((s) => s.svgPixelsPerMm);
  const setSvgPixelsPerMm = useSettingsStore((s) => s.setSvgPixelsPerMm);
  const resetSvgPixelsPerMm = useSettingsStore(
    (s) => s.resetSvgPixelsPerMm,
  );
  const materialDeltaE00Tolerance = useSettingsStore(
    (s) => s.materialDeltaE00Tolerance,
  );
  const setMaterialDeltaE00Tolerance = useSettingsStore(
    (s) => s.setMaterialDeltaE00Tolerance,
  );
  const autoReplaceGradientBanding = useSettingsStore(
    (s) => s.autoReplaceGradientBanding,
  );
  const setAutoReplaceGradientBanding = useSettingsStore(
    (s) => s.setAutoReplaceGradientBanding,
  );
  const isValidatingCustomPath = useSlicerStore(
    (s) => s.isValidatingCustomPath,
  );
  const detectedSlicers = useSlicerStore((s) => s.slicers);
  const selectedDetectedSlicerId = useSlicerStore((s) => s.selectedSlicerId);
  const setSelectedDetectedSlicerId = useSlicerStore((s) => s.setSelectedSlicerId);
  const customPathMessage = useSlicerStore((s) => s.customPathMessage);
  const customPathError = useSlicerStore((s) => s.customPathError);
  const validateAndSaveCustomSlicerPath = useSlicerStore(
    (s) => s.validateAndSaveCustomSlicerPath,
  );
  const clearCustomSlicerPath = useSlicerStore((s) => s.clearCustomSlicerPath);

  useEffect(() => {
    setCustomSlicerPathInput(customSlicerPath);
  }, [customSlicerPath]);

  useEffect(() => {
    if (
      enableCompletionNotifications &&
      notificationPermission !== "granted"
    ) {
      setEnableCompletionNotifications(false);
    }
  }, [
    enableCompletionNotifications,
    notificationPermission,
    setEnableCompletionNotifications,
  ]);

  const loadPrinterOptions = useCallback(async (
    isCancelled: CancellationCheck = SETTINGS_OPTIONS_NOT_CANCELLED,
  ) => {
    setPrintersLoading(true);
    setPrinterOptionsError(null);
    try {
      const list = await retryAsync(getPrinters, {
        attempts: SETTINGS_OPTIONS_RETRY_ATTEMPTS,
        delayMs: SETTINGS_OPTIONS_RETRY_DELAY_MS,
      });
      if (!isCancelled()) {
        setPrinters(list);
      }
    } catch (error) {
      console.warn("[SettingsPanel] Failed to load printer options", error);
      if (!isCancelled()) {
        setPrinterOptionsError(
          formatSettingsOptionsLoadError(t("settings.printer_options_load_failed"), error),
        );
      }
    } finally {
      if (!isCancelled()) {
        setPrintersLoading(false);
      }
    }
  }, [t]);

  const loadSlicerOptions = useCallback(async (
    isCancelled: CancellationCheck = SETTINGS_OPTIONS_NOT_CANCELLED,
  ) => {
    setSlicersLoading(true);
    setSlicerOptionsError(null);
    try {
      const list = await retryAsync(getSlicers, {
        attempts: SETTINGS_OPTIONS_RETRY_ATTEMPTS,
        delayMs: SETTINGS_OPTIONS_RETRY_DELAY_MS,
      });
      if (!isCancelled()) {
        setSlicers(list);
      }
    } catch (error) {
      console.warn("[SettingsPanel] Failed to load slicer options", error);
      if (!isCancelled()) {
        setSlicerOptionsError(
          formatSettingsOptionsLoadError(t("settings.slicer_options_load_failed"), error),
        );
      }
    } finally {
      if (!isCancelled()) {
        setSlicersLoading(false);
      }
    }
  }, [t]);

  // Load printers and slicers on mount.
  useEffect(() => {
    let cancelled = false;

    void loadPrinterOptions(() => cancelled);
    void loadSlicerOptions(() => cancelled);

    return () => { cancelled = true; };
  }, [loadPrinterOptions, loadSlicerOptions]);

  const resolvedSlicerSoftware = resolveSlicerOptionId(slicerSoftware, slicers);
  const resolvedPrinterModel = resolvePrinterOptionId(
    printerModel,
    printers,
    resolvedSlicerSoftware
  );
  const selectedPrinter = printers.find((p) => p.id === resolvedPrinterModel);
  const resolvedNozzleSize = resolveNozzleSizeOption(
    nozzleSize,
    selectedPrinter,
    resolvedSlicerSoftware,
  );
  const resolvedDeviceProfileId = resolveDeviceProfileOptionId(
    deviceProfileId,
    selectedPrinter,
    resolvedSlicerSoftware,
    resolvedNozzleSize,
  );
  const selectedDeviceProfile =
    selectedPrinter?.device_profiles?.find(
      (profile) => profile.device_profile_id === resolvedDeviceProfileId,
    ) ?? null;
  const selectedSlicer =
    slicers.find((slicer) => slicer.id === resolvedSlicerSoftware) ?? null;
  const selectedPrinterThumbnailUrl = getMachineRegistryAssetUrl(selectedPrinter?.thumbnail);
  const availableBuildPlates = selectedDeviceProfile?.build_plates ?? [];
  const buildPlateSelection = resolveBuildPlateSelection(
    selectedDeviceProfile?.machine_profile_id ?? "",
    availableBuildPlates.map((plate) => plate.id),
    selectedDeviceProfile?.default_build_plate_id ?? "",
    buildPlateSelections,
  );

  useEffect(() => {
    const machineProfileId = selectedDeviceProfile?.machine_profile_id ?? "";
    if (!machineProfileId) {
      return;
    }
    if (!buildPlateSelection.plateId) {
      if (buildPlateId) {
        setBuildPlateForMachine(machineProfileId, "");
        void syncToBackend();
      }
      return;
    }
    if (
      buildPlateId !== buildPlateSelection.plateId ||
      buildPlateSelections[machineProfileId] !== buildPlateSelection.plateId
    ) {
      setBuildPlateForMachine(machineProfileId, buildPlateSelection.plateId);
      void syncToBackend();
    }
  }, [
    buildPlateSelection.plateId,
    buildPlateId,
    buildPlateSelections,
    selectedDeviceProfile?.machine_profile_id,
    setBuildPlateForMachine,
    syncToBackend,
  ]);

  const handleBuildPlateSelect = (plateId: string) => {
    const machineProfileId = selectedDeviceProfile?.machine_profile_id ?? "";
    if (!machineProfileId) {
      return;
    }
    setBuildPlateForMachine(machineProfileId, plateId);
    void syncToBackend();
  };

  useEffect(() => {
    if (slicersLoading || printersLoading || slicers.length === 0 || printers.length === 0) {
      return;
    }

    const nextSlicer = resolveSlicerOptionId(slicerSoftware, slicers);
    const nextPrinter = resolvePrinterOptionId(printerModel, printers, nextSlicer);
    const nextPrinterInfo = printers.find((printer) => printer.id === nextPrinter);
    const nextNozzleSize = resolveNozzleSizeOption(nozzleSize, nextPrinterInfo, nextSlicer);
    const nextDeviceProfileId = resolveDeviceProfileOptionId(
      deviceProfileId,
      nextPrinterInfo,
      nextSlicer,
      nextNozzleSize,
    );

    let didNormalize = false;

    if (nextSlicer && nextSlicer !== slicerSoftware) {
      setSlicerSoftware(nextSlicer);
      didNormalize = true;
    }

    if (nextPrinter && nextPrinter !== printerModel) {
      setPrinterModel(nextPrinter);
      if (nextPrinterInfo) {
        setLastBedLabel(`${nextPrinterInfo.bed_width}×${nextPrinterInfo.bed_depth} mm`);
      }
      didNormalize = true;
    }

    if (nextNozzleSize !== nozzleSize) {
      setNozzleSize(nextNozzleSize as NozzleSize);
      didNormalize = true;
    }

    if (nextDeviceProfileId !== deviceProfileId) {
      setDeviceProfileId(nextDeviceProfileId);
      didNormalize = true;
    }

    if (didNormalize) {
      void syncToBackend();
    }
  }, [
    deviceProfileId,
    printerModel,
    printers,
    printersLoading,
    setDeviceProfileId,
    setLastBedLabel,
    setPrinterModel,
    setNozzleSize,
    setSlicerSoftware,
    nozzleSize,
    slicerSoftware,
    slicers,
    slicersLoading,
    syncToBackend,
  ]);

  // Filter printers by selected slicer
  const filteredPrinters = filterCompatiblePrinters(printers, resolvedSlicerSoftware);

  // Handle printer selection change (task 5.3 + 6.1)
  const handlePrinterChange = (id: string) => {
    setPrinterModel(id);
    const selected = printers.find((p) => p.id === id);
    if (selected) {
      setLastBedLabel(`${selected.bed_width}×${selected.bed_depth} mm`);
      const nextNozzleSize = resolveNozzleSizeOption(nozzleSize, selected, resolvedSlicerSoftware);
      if (nextNozzleSize !== nozzleSize) {
        setNozzleSize(nextNozzleSize as NozzleSize);
      }
      const nextDeviceProfileId = resolveDeviceProfileOptionId(
        deviceProfileId,
        selected,
        resolvedSlicerSoftware,
        nextNozzleSize,
      );
      if (nextDeviceProfileId !== deviceProfileId) {
        setDeviceProfileId(nextDeviceProfileId);
      }
    }
    syncToBackend();
  };

  // Handle slicer selection change — auto-select first compatible printer
  const handleSlicerChange = (id: string) => {
    setSlicerSoftware(id);
    const preferredDetectedSlicerId = getDetectedSlicerIdForSoftware(id);
    const nextDetectedSlicerId =
      preferredDetectedSlicerId &&
      detectedSlicers.some((slicer) => slicer.id === preferredDetectedSlicerId)
        ? preferredDetectedSlicerId
        : null;
    if (nextDetectedSlicerId !== selectedDetectedSlicerId) {
      setSelectedDetectedSlicerId(nextDetectedSlicerId);
    }
    // If current printer doesn't support the new slicer, switch to first compatible
    const compatible = filterCompatiblePrinters(printers, id);
    const currentStillValid = compatible.some((p) => p.id === resolvedPrinterModel);
    let resolvedPrinter =
      compatible.find((p) => p.id === resolvedPrinterModel) ?? compatible[0];
    if (!currentStillValid && compatible.length > 0) {
      setPrinterModel(compatible[0].id);
      setLastBedLabel(
        `${compatible[0].bed_width}×${compatible[0].bed_depth} mm`
      );
      resolvedPrinter = compatible[0];
    }
    const nextNozzleSize = resolveNozzleSizeOption(nozzleSize, resolvedPrinter, id);
    if (nextNozzleSize !== nozzleSize) {
      setNozzleSize(nextNozzleSize as NozzleSize);
    }
    const nextDeviceProfileId = resolveDeviceProfileOptionId(
      deviceProfileId,
      resolvedPrinter,
      id,
      nextNozzleSize,
    );
    if (nextDeviceProfileId !== deviceProfileId) {
      setDeviceProfileId(nextDeviceProfileId);
    }
    syncToBackend();
  };

  const handlePrinterNozzleChange = (printer: PrinterInfo, value: string) => {
    if (printer.id !== printerModel) {
      setPrinterModel(printer.id);
      setLastBedLabel(`${printer.bed_width}×${printer.bed_depth} mm`);
    }
    if (value !== nozzleSize) {
      setNozzleSize(value as NozzleSize);
    }
    const nextDeviceProfileId = resolveDeviceProfileOptionId(
      deviceProfileId,
      printer,
      resolvedSlicerSoftware,
      value,
    );
    if (nextDeviceProfileId !== deviceProfileId) {
      setDeviceProfileId(nextDeviceProfileId);
    }
    void syncToBackend();
  };

  const handleSaveCustomSlicerPath = () => {
    void validateAndSaveCustomSlicerPath(customSlicerPathInput);
  };

  const handleClearCustomSlicerPath = () => {
    setCustomSlicerPathInput("");
    clearCustomSlicerPath();
  };

  const handleClearCache = async () => {
    setClearing(true);
    setCacheResult(null);
    try {
      const res = await clearCache();
      const size = res.freed_bytes < 1024 * 1024
        ? `${(res.freed_bytes / 1024).toFixed(1)} KB`
        : `${(res.freed_bytes / (1024 * 1024)).toFixed(1)} MB`;
      setCacheResult(
        t("settings.cache_cleared_detail")
          .replace("{count}", String(res.deleted_files))
          .replace("{size}", size)
      );
    } catch {
      setCacheResult(t("settings.cache_clear_failed"));
    } finally {
      setClearing(false);
    }
  };

  const handleCompletionNotificationsChange = async (enabled: boolean) => {
    if (!enabled) {
      setEnableCompletionNotifications(false);
      return;
    }

    setNotificationPermissionLoading(true);
    const permission = await requestBrowserNotificationPermission();
    setNotificationPermission(permission);
    setEnableCompletionNotifications(permission === "granted");
    setNotificationPermissionLoading(false);
  };

  const completionNotificationStatus =
    COMPLETION_NOTIFICATION_STATUS[notificationPermission];

  const settingsCategories: SettingsCategory[] = [
    {
      id: "device",
      label: t("settings.category_device"),
      description: t("settings.category_device_desc"),
    },
    {
      id: "general",
      label: t("settings.category_general"),
      description: t("settings.category_general_desc"),
    },
    {
      id: "conversion",
      label: t("settings.category_conversion"),
      description: t("settings.category_conversion_desc"),
    },
    {
      id: "maintenance",
      label: t("settings.category_maintenance"),
      description: t("settings.category_maintenance_desc"),
    },
  ];

  const handleCategoryChange = (category: SettingsCategoryId) => {
    setActiveCategory(category);
    setMachineDialogOpen(false);
  };

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      data-testid="settings-panel"
      className="settings-workspace flex h-full min-h-0 w-full flex-col overflow-hidden"
    >
      <div className="grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)] sm:grid-cols-[12rem_minmax(0,1fr)] sm:grid-rows-[minmax(0,1fr)] lg:grid-cols-[15rem_minmax(0,1fr)]">
        <SettingsCategoryNav
          ariaLabel={t("settings.category_nav_label")}
          categories={settingsCategories}
          activeCategory={activeCategory}
          onChange={handleCategoryChange}
        />

        <div
          key={activeCategory}
          id={`settings-category-panel-${activeCategory}`}
          role="region"
          aria-labelledby={`settings-category-${activeCategory}`}
          tabIndex={0}
          className="dock-scrollbar min-h-0 min-w-0 overflow-auto overscroll-y-contain px-5 py-6 sm:px-7 lg:px-10"
        >
          <header className="mx-auto mb-7 w-full max-w-4xl border-b panel-divider pb-5">
            <h2 className="text-xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
              {settingsCategories.find((category) => category.id === activeCategory)?.label}
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">
              {settingsCategories.find((category) => category.id === activeCategory)?.description}
            </p>
          </header>
          {activeCategory === "device" && (
            <section
              data-tutorial="device-settings"
              className="settings-content mx-auto flex w-full max-w-4xl flex-col gap-5"
            >
              <div>
                <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900 dark:text-slate-50">
                  <span>{t("settings.current_device_heading")}</span>
                  <HelpDot
                    title={t("settings.current_device_heading")}
                    description={t("settings.current_device_description")}
                    wikiPath={WIKI_DOCS.deviceAndSlicer}
                  />
                </h3>
              </div>

              {slicerOptionsError && (
                <StatusBanner
                  role="alert"
                  tone="error"
                  action={(
                    <Button
                      label={t("widget_retry")}
                      variant="secondary"
                      size="sm"
                      loading={slicersLoading}
                      onClick={() => { void loadSlicerOptions(); }}
                    />
                  )}
                >
                  {slicerOptionsError}
                </StatusBanner>
              )}
              {printerOptionsError && (
                <StatusBanner
                  role="alert"
                  tone="error"
                  action={(
                    <Button
                      label={t("widget_retry")}
                      variant="secondary"
                      size="sm"
                      loading={printersLoading}
                      onClick={() => { void loadPrinterOptions(); }}
                    />
                  )}
                >
                  {printerOptionsError}
                </StatusBanner>
              )}

              <div
                data-testid="machine-adapter-summary"
                className="grid gap-4 py-1 md:grid-cols-[minmax(0,1fr)_auto] md:items-center"
              >
                <div className="flex min-w-0 items-center gap-4">
                  <div
                    className={`flex h-24 w-24 shrink-0 items-center justify-center overflow-hidden ${
                      selectedPrinterThumbnailUrl
                        ? "rounded-none bg-transparent"
                        : "rounded-[8px] bg-[var(--surface-card)]"
                    }`}
                  >
                    {selectedPrinterThumbnailUrl ? (
                      <img
                        src={selectedPrinterThumbnailUrl}
                        alt={selectedPrinter?.display_name ?? ""}
                        className="h-full w-full object-contain p-0"
                        loading="lazy"
                      />
                    ) : (
                      <span className="text-sm font-semibold text-slate-400 dark:text-slate-500">
                        {printersLoading
                          ? t("settings.machine_options_loading")
                          : t("settings.machine_thumbnail_fallback")}
                      </span>
                    )}
                  </div>
                  <div className="min-w-0">
                    <div className="flex min-w-0 items-center gap-2 text-xs font-medium text-slate-500 dark:text-slate-400">
                      {selectedSlicer && (
                        <SlicerLogo slicerId={selectedSlicer.id} />
                      )}
                      <span className="truncate">
                        {selectedSlicer?.display_name ??
                          resolvedSlicerSoftware ??
                          t("settings.machine_options_loading")}
                      </span>
                    </div>
                    <h4 className="mt-1 truncate text-sm font-semibold text-slate-900 dark:text-slate-50">
                      {selectedPrinter?.display_name ??
                        resolvedPrinterModel ??
                        t("settings.machine_options_loading")}
                    </h4>
                    {selectedPrinter && (
                      <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-600 dark:text-slate-300">
                        <span className="px-0 py-1">
                          {t("settings.bed_size")}: {selectedPrinter.bed_width}
                          &times;{selectedPrinter.bed_depth} {t("common_unit_mm")}
                        </span>
                        <span className="px-0 py-1">
                          {t("settings.nozzle_size")}: {resolvedNozzleSize}{" "}
                          {t("common_unit_mm")}
                        </span>
                      </div>
                    )}
                    {selectedDeviceProfile && (
                      <p className="mt-2 truncate text-xs text-slate-500 dark:text-slate-400">
                        {t("settings.device_profile")}:{" "}
                        {selectedDeviceProfile.source_profile_name}
                      </p>
                    )}
                    {resolvedSlicerSoftware === "PrusaSlicer" && (
                      <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                        {t("settings.prusa_preview_help")}
                      </p>
                    )}
                  </div>
                </div>
                <Button
                  label={t("settings.change_device")}
                  onClick={() => setMachineDialogOpen(true)}
                  disabled={
                    printersLoading ||
                    slicersLoading ||
                    filteredPrinters.length === 0
                  }
                  className="w-full md:w-auto"
                />
              </div>

              <BuildPlateSelector
                label={t("settings.build_plate")}
                hint={t("settings.build_plate_hint")}
                plates={availableBuildPlates}
                selectedId={buildPlateSelection.plateId}
                onSelect={handleBuildPlateSelect}
                language={language}
              />

              {buildPlateSelection.fellBack && (
                <StatusBanner tone="warning">
                  {t("settings.build_plate_fallback")}
                </StatusBanner>
              )}

              <Custom3mfTemplateSettings />

              <div
                data-testid="wipe-tower-auto-placement-row"
                className="flex items-center justify-between gap-4 border-t panel-divider pt-5"
              >
                <div className="flex min-w-0 items-center gap-1.5">
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                    {t("settings.wipe_tower_auto_placement")}
                  </span>
                  <HelpDot
                    title={t("settings.wipe_tower_auto_placement")}
                    description={t("settings.wipe_tower_auto_placement_desc")}
                    placement="left"
                  />
                </div>
                <Switch
                  checked={enableWipeTowerAutoPlacement}
                  onChange={(enabled) => {
                    setEnableWipeTowerAutoPlacement(enabled);
                    void syncToBackend();
                  }}
                  ariaLabel={t("settings.wipe_tower_auto_placement")}
                />
              </div>

              {supportsLayerConfigRanges(resolvedSlicerSoftware) && (
                <div
                  data-testid="base-layer-height-modifier-row"
                  className="flex items-center justify-between gap-4 border-t panel-divider pt-5"
                >
                  <div className="flex min-w-0 items-center gap-1.5">
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                      {t("settings.base_layer_height_modifier")}
                    </span>
                    <HelpDot
                      title={t("settings.base_layer_height_modifier")}
                      description={t("settings.base_layer_height_modifier_desc")}
                      wikiPath={WIKI_DOCS.baseLayerModifier}
                      placement="left"
                    />
                  </div>
                  <Switch
                    checked={enableBaseLayerHeightModifier}
                    onChange={(enabled) => {
                      setEnableBaseLayerHeightModifier(enabled);
                      void syncToBackend();
                    }}
                    ariaLabel={t("settings.base_layer_height_modifier")}
                  />
                </div>
              )}

              <div className="border-t panel-divider pt-5">
                <div className="relative flex min-h-11 items-center gap-1.5 pr-7">
                  <button
                    type="button"
                    aria-label={t("settings.manual_setup_heading")}
                    aria-expanded={manualSetupOpen}
                    aria-controls="settings-manual-slicer-setup"
                    onClick={() => setManualSetupOpen((open) => !open)}
                    className="absolute inset-0 flex items-center justify-end text-left outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
                  >
                    <DisclosureChevron expanded={manualSetupOpen} />
                  </button>
                  <h3 className="pointer-events-none relative min-w-0 text-sm font-medium text-slate-700 dark:text-slate-200">
                    {t("settings.manual_setup_heading")}
                  </h3>
                  <div className="relative shrink-0">
                    <HelpDot
                      title={t("settings.manual_setup_heading")}
                      ariaLabel={t("settings.manual_setup_description")}
                      description={`${t("settings.manual_setup_description")}\n\n${t("settings.custom_slicer_path_help")}`}
                      wikiPath={WIKI_DOCS.deviceAndSlicer}
                    />
                  </div>
                </div>

                {manualSetupOpen && (
                  <div
                    id="settings-manual-slicer-setup"
                    className="mt-3 flex flex-col gap-3"
                  >
                    <div>
                      <label
                        htmlFor="custom-slicer-path"
                        className="text-sm font-medium text-slate-700 dark:text-slate-200"
                      >
                        {t("settings.custom_slicer_path")}
                      </label>
                    </div>
                    <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_auto]">
                      <input
                        id="custom-slicer-path"
                        value={customSlicerPathInput}
                        onChange={(event) =>
                          setCustomSlicerPathInput(event.target.value)
                        }
                        placeholder={t("settings.custom_slicer_path_placeholder")}
                        className={workstationInputClass}
                      />
                      <Button
                        label={t("settings.custom_slicer_save")}
                        onClick={handleSaveCustomSlicerPath}
                        loading={isValidatingCustomPath}
                        disabled={!customSlicerPathInput.trim()}
                        variant="primary"
                      />
                      <Button
                        label={t("settings.custom_slicer_clear")}
                        onClick={handleClearCustomSlicerPath}
                        variant="secondary"
                        disabled={!customSlicerPath && !customSlicerPathInput}
                      />
                    </div>
                    {customPathMessage && (
                      <StatusBanner tone="success">
                        {customPathMessage}
                      </StatusBanner>
                    )}
                    {customPathError && (
                      <StatusBanner tone="error">
                        {customPathError}
                      </StatusBanner>
                    )}
                  </div>
                )}
              </div>
            </section>
          )}

          {activeCategory === "general" && (
            <section
              className="settings-content mx-auto flex w-full max-w-4xl flex-col gap-5"
            >
              <div data-testid="settings-language-section">
                <Dropdown
                  label={t("settings.language_label")}
                  value={language}
                  options={[
                    { value: "zh", label: t("settings.language_zh") },
                    { value: "en", label: t("settings.language_en") },
                  ]}
                  onChange={(value) => {
                    if (value === "zh" || value === "en") setLanguage(value);
                  }}
                />
              </div>
              <InterfaceScaleSetting />
              <div
                data-testid="settings-completion-notifications-section"
                className="flex flex-col gap-4 border-t panel-divider pt-5"
              >
                <div className="flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <h3 className="text-sm font-medium text-slate-700 dark:text-slate-200">
                        {t("settings.completion_notifications_heading")}
                      </h3>
                      <HelpDot
                        title={t("settings.completion_notifications_heading")}
                        description={[
                          t("settings.completion_notifications_description"),
                          t("settings.completion_notifications_hint"),
                          ...(["info", "success"].includes(completionNotificationStatus.tone)
                            ? [t(completionNotificationStatus.translationKey)]
                            : []),
                        ].join("\n\n")}
                      />
                    </div>
                  </div>
                  <Switch
                    checked={enableCompletionNotifications}
                    onChange={(enabled) => {
                      void handleCompletionNotificationsChange(enabled);
                    }}
                    disabled={
                      notificationPermissionLoading ||
                      notificationPermission === "unsupported"
                    }
                    ariaLabel={t("settings.completion_notifications_heading")}
                  />
                </div>
                {(completionNotificationStatus.tone === "warning" ||
                  completionNotificationStatus.tone === "error") && (
                  <StatusBanner
                    tone={completionNotificationStatus.tone}
                    role={
                      completionNotificationStatus.tone === "error"
                        ? "alert"
                        : undefined
                    }
                  >
                    {t(completionNotificationStatus.translationKey)}
                  </StatusBanner>
                )}
              </div>

              <div
                data-testid="settings-preserve-upload-filename-section"
                className="flex items-center justify-between gap-4 border-t panel-divider pt-5"
              >
                <div className="min-w-0">
                  <h3 className="flex items-center gap-1.5 text-sm font-medium text-slate-700 dark:text-slate-200">
                    <span>{t("settings.preserve_upload_filename_heading")}</span>
                    <HelpDot
                      title={t("settings.preserve_upload_filename_heading")}
                      description={t("settings.preserve_upload_filename_description")}
                    />
                  </h3>
                </div>
                <Switch
                  checked={preserveUploadFilenameFor3mf}
                  onChange={setPreserveUploadFilenameFor3mf}
                  ariaLabel={t("settings.preserve_upload_filename_heading")}
                />
              </div>

              <GeneratedFileDirectorySetting />

              <div className="flex items-center justify-between gap-4 border-t panel-divider pt-5">
                <div className="min-w-0">
                  <h3 className="flex items-center gap-1.5 text-sm font-medium text-slate-700 dark:text-slate-200">
                    <span>{t("settings.witty_loading")}</span>
                    <HelpDot
                      title={t("settings.witty_loading")}
                      description={t("settings.witty_loading_desc")}
                      wikiPath={WIKI_DOCS.wittyLoading}
                    />
                  </h3>
                </div>
                  <Switch
                    checked={enableWittyLoading}
                    onChange={setEnableWittyLoading}
                    ariaLabel={t("settings.witty_loading")}
                  />
              </div>

              <HeaderNavAlignmentSetting />
            </section>
          )}

          {activeCategory === "conversion" && (
            <section
              data-testid="settings-advanced-section"
              className="settings-content mx-auto flex w-full max-w-4xl flex-col gap-5"
            >
              <div
                data-testid="settings-solver-cache-density-section"
                className="flex flex-col gap-4"
              >
                <div className="flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <h3 className="flex items-center gap-1.5 text-sm font-medium text-slate-700 dark:text-slate-200">
                      <span>{t("settings.solver_cache_density_heading")}</span>
                      <HelpDot
                        title={t("settings.solver_cache_density_heading")}
                        description={`${t("settings.solver_cache_density_description")}\n\n${t("settings.solver_cache_density_tip")}`}
                        wikiPath={WIKI_DOCS.solverCacheDensity}
                        placement="left"
                      />
                    </h3>
                  </div>
                  <Switch
                    checked={enableSolverCacheGridSelection}
                    onChange={setEnableSolverCacheGridSelection}
                    ariaLabel={t("settings.solver_cache_density_heading")}
                  />
                </div>
                {enableSolverCacheGridSelection ? (
                  <div
                    data-testid="settings-solver-cache-density-dropdown-row"
                    className={dependentGroupClass}
                  >
                    <Dropdown
                      label={t("settings.solver_cache_density_select_label")}
                      value={String(solverCacheGridResolution)}
                      onChange={(value) =>
                        setSolverCacheGridResolution(
                          Number(value) as SolverCacheGridResolution,
                        )
                      }
                      options={SOLVER_CACHE_GRID_RESOLUTIONS.map((grid) => ({
                        value: String(grid),
                        label: t(`settings.solver_cache_density_option_${grid}`),
                      }))}
                    />
                  </div>
                ) : (
                  <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
                    {t("settings.solver_cache_density_default_hint")}
                  </p>
                )}
              </div>

              <div
                data-testid="settings-material-delta-e00-tolerance-section"
                className="flex flex-col gap-4 border-t panel-divider pt-5"
              >
                <div>
                  <h3 className="text-sm font-medium text-slate-700 dark:text-slate-200">
                    {t("settings.material_delta_e00_tolerance_heading")}
                  </h3>
                </div>
                <Slider
                  label={t("settings.material_delta_e00_tolerance_label")}
                  tooltip={`${t("settings.material_delta_e00_tolerance_description")}\n\n${t("settings.material_delta_e00_tolerance_hint")}`}
                  value={materialDeltaE00Tolerance}
                  min={MATERIAL_DELTA_E00_TOLERANCE_MIN}
                  max={MATERIAL_DELTA_E00_TOLERANCE_MAX}
                  step={MATERIAL_DELTA_E00_TOLERANCE_STEP}
                  displayDecimals={1}
                  minInputWidthCh={4}
                  onChange={setMaterialDeltaE00Tolerance}
                />
              </div>

              <div
                data-testid="settings-svg-raster-density-section"
                className="flex flex-col gap-4 border-t panel-divider pt-5"
              >
                <div>
                  <h3 className="text-sm font-medium text-slate-700 dark:text-slate-200">
                    {t("settings.svg_pixels_per_mm_heading")}
                  </h3>
                </div>
                <div className="grid gap-3 min-[960px]:grid-cols-[minmax(0,1fr)_max-content]">
                  <Slider
                    label={t("settings.svg_pixels_per_mm_label")}
                    tooltip={`${t("settings.svg_pixels_per_mm_tip")}\n\n${t("settings.svg_pixels_per_mm_default_hint")}`}
                    wikiPath={WIKI_DOCS.svgRasterDensity}
                    value={svgPixelsPerMm}
                    min={SVG_PIXELS_PER_MM_MIN}
                    max={SVG_PIXELS_PER_MM_MAX}
                    step={SVG_PIXELS_PER_MM_STEP}
                    displayDecimals={1}
                    minInputWidthCh={4}
                    unit={t("common_unit_px_per_mm")}
                    onChange={setSvgPixelsPerMm}
                  />
                  <Button
                    label={t("settings.svg_pixels_per_mm_reset")}
                    onClick={resetSvgPixelsPerMm}
                    variant="secondary"
                    disabled={svgPixelsPerMm === SVG_PIXELS_PER_MM_DEFAULT}
                    className="w-full min-[960px]:w-auto min-[960px]:min-w-max min-[960px]:self-end"
                  />
                </div>
              </div>

              <SvgHoleCompensationSettings />

              <div
                data-testid="settings-auto-replace-gradient-section"
                className="flex flex-col gap-4 border-t panel-divider pt-5"
              >
                <div className="flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <h3 className="flex items-center gap-1.5 text-sm font-medium text-slate-700 dark:text-slate-200">
                      <span>{t("settings.auto_replace_gradient_heading")}</span>
                      <HelpDot
                        title={t("settings.auto_replace_gradient_heading")}
                        description={`${t("settings.auto_replace_gradient_description")}\n\n${t("settings.auto_replace_gradient_tip")}`}
                        wikiPath={WIKI_DOCS.autoGradientReplacement}
                        placement="left"
                      />
                    </h3>
                  </div>
                  <Switch
                    checked={autoReplaceGradientBanding}
                    onChange={setAutoReplaceGradientBanding}
                    ariaLabel={t("settings.auto_replace_gradient_heading")}
                  />
                </div>
              </div>

              <div
                data-testid="settings-smooth-vector-preview-section"
                className="flex items-center justify-between gap-4 border-t panel-divider pt-5"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <h3 className="text-sm font-medium text-slate-700 dark:text-slate-200">
                      {t("settings.smooth_vector_preview_heading")}
                    </h3>
                    <HelpDot
                      title={t("settings.smooth_vector_preview_heading")}
                      description={`${t("settings.smooth_vector_preview_description")}\n\n${t("settings.smooth_vector_preview_hint")}`}
                      ariaLabel={t("settings.smooth_vector_preview_help_aria")}
                    />
                  </div>
                </div>
                <Switch
                  checked={enableSmoothVectorPreview}
                  onChange={setEnableSmoothVectorPreview}
                  ariaLabel={t("settings.smooth_vector_preview_heading")}
                />
              </div>
            </section>
          )}

          {activeCategory === "maintenance" && (
            <section
              className="settings-content mx-auto flex w-full max-w-4xl flex-col gap-5"
            >
              <div className="flex flex-col gap-4">
                <div>
                  <h3 className="flex items-center gap-1.5 text-sm font-medium text-slate-700 dark:text-slate-200">
                    <span>{t("settings.cache")}</span>
                    <HelpDot
                      title={t("settings.cache")}
                      description={t("settings.cache_summary")}
                      wikiPath={WIKI_DOCS.cacheMaintenance}
                    />
                  </h3>
                </div>
                <div>
                  <Button
                    label={t("settings.clear_cache")}
                    onClick={handleClearCache}
                    loading={clearing}
                    variant="secondary"
                    className="w-full sm:w-auto"
                  />
                </div>
                {cacheResult && (
                  <StatusBanner
                    tone={
                      cacheResult === t("settings.cache_clear_failed")
                        ? "error"
                        : "success"
                    }
                  >
                    {cacheResult}
                  </StatusBanner>
                )}
              </div>
            </section>
          )}
        </div>
      </div>

      <MachineSelectionDialog
        open={machineDialogOpen}
        printers={filteredPrinters}
        slicers={slicers}
        printersLoading={printersLoading}
        slicersLoading={slicersLoading}
        slicerSoftware={resolvedSlicerSoftware}
        printerModel={resolvedPrinterModel}
        nozzleSize={resolvedNozzleSize}
        onSlicerChange={handleSlicerChange}
        onPrinterChange={handlePrinterChange}
        onPrinterNozzleChange={handlePrinterNozzleChange}
        onClose={() => setMachineDialogOpen(false)}
      />

    </motion.aside>
  );
}
