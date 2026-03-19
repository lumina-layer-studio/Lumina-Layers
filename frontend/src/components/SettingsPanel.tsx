/**
 * SettingsPanel - System settings page.
 * 系统设置页面，包含切片软件设置和缓存清理功能。
 */

import { motion } from "framer-motion";
import { useState, useEffect } from "react";
import { useI18n } from "../i18n/context";
import { clearCache, getPrinters, getSlicers } from "../api/system";
import { useSettingsStore } from "../stores/settingsStore";
import type { PrinterInfo, SlicerOption } from "../api/types";
import Button from "./ui/Button";

export default function SettingsPanel() {
  const { t } = useI18n();

  const [clearing, setClearing] = useState(false);
  const [cacheResult, setCacheResult] = useState<string | null>(null);

  // Printer list state (task 5.2)
  const [printers, setPrinters] = useState<PrinterInfo[]>([]);
  const [printersLoading, setPrintersLoading] = useState(true);

  // Slicer list state
  const [slicers, setSlicers] = useState<SlicerOption[]>([]);
  const [slicersLoading, setSlicersLoading] = useState(true);

  // Store state (task 5.3)
  const printerModel = useSettingsStore((s) => s.printerModel);
  const setPrinterModel = useSettingsStore((s) => s.setPrinterModel);
  const slicerSoftware = useSettingsStore((s) => s.slicerSoftware);
  const setSlicerSoftware = useSettingsStore((s) => s.setSlicerSoftware);
  const setLastBedLabel = useSettingsStore((s) => s.setLastBedLabel);
  const syncToBackend = useSettingsStore((s) => s.syncToBackend);

  // Load printers and slicers on mount
  useEffect(() => {
    let cancelled = false;
    setPrintersLoading(true);
    setSlicersLoading(true);
    getPrinters()
      .then((list) => {
        if (!cancelled) setPrinters(list);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setPrintersLoading(false);
      });
    getSlicers()
      .then((list) => {
        if (!cancelled) setSlicers(list);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setSlicersLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  // Filter printers by selected slicer
  const filteredPrinters = printers.filter(
    (p) =>
      !p.supported_slicers ||
      p.supported_slicers.length === 0 ||
      p.supported_slicers.includes(slicerSoftware)
  );

  // Handle printer selection change (task 5.3 + 6.1)
  const handlePrinterChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const id = e.target.value;
    setPrinterModel(id);
    const selected = printers.find((p) => p.id === id);
    if (selected) {
      setLastBedLabel(`${selected.bed_width}×${selected.bed_depth} mm`);
    }
    syncToBackend();
  };

  // Handle slicer selection change — auto-select first compatible printer
  const handleSlicerChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const id = e.target.value;
    setSlicerSoftware(id);
    // If current printer doesn't support the new slicer, switch to first compatible
    const compatible = printers.filter(
      (p) =>
        !p.supported_slicers ||
        p.supported_slicers.length === 0 ||
        p.supported_slicers.includes(id)
    );
    const currentStillValid = compatible.some((p) => p.id === printerModel);
    if (!currentStillValid && compatible.length > 0) {
      setPrinterModel(compatible[0].id);
      setLastBedLabel(
        `${compatible[0].bed_width}×${compatible[0].bed_depth} mm`
      );
    }
    syncToBackend();
  };

  const selectedPrinter = printers.find((p) => p.id === printerModel);

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
      setCacheResult("Error");
    } finally {
      setClearing(false);
    }
  };

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", damping: 25, stiffness: 300 }}
      data-testid="settings-panel"
      className="w-full max-w-2xl mx-auto h-full overflow-y-auto bg-white/85 dark:bg-gray-900/85 backdrop-blur-2xl border border-white/40 dark:border-gray-700/50 shadow-2xl rounded-2xl p-6 flex flex-col gap-6"
    >
      <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
        {t("settings.title")}
      </h3>

      {/* Slicer Settings / 切片软件设置 (task 5.1) */}
      <section className="flex flex-col gap-3">
        <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300">
          {t("settings.slicer_settings")}
        </h4>

        {/* Slicer software dropdown — first */}
        <div className="flex flex-col gap-1.5">
          <label
            htmlFor="slicer-software-select"
            className="text-sm text-gray-500 dark:text-gray-400"
          >
            {t("settings.slicer_software")}
          </label>
          <select
            id="slicer-software-select"
            value={slicerSoftware}
            onChange={handleSlicerChange}
            disabled={slicersLoading}
            className="w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500 dark:focus:ring-blue-400 disabled:opacity-50 disabled:cursor-wait"
          >
            {slicers.map((s) => (
              <option key={s.id} value={s.id}>
                {s.display_name}
              </option>
            ))}
          </select>
        </div>

        {/* Printer model dropdown — filtered by slicer */}
        <div className="flex flex-col gap-1.5">
          <label
            htmlFor="printer-model-select"
            className="text-sm text-gray-500 dark:text-gray-400"
          >
            {t("settings.printer_model")}
          </label>
          <select
            id="printer-model-select"
            value={printerModel}
            onChange={handlePrinterChange}
            disabled={printersLoading}
            className="w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500 dark:focus:ring-blue-400 disabled:opacity-50 disabled:cursor-wait"
          >
            {filteredPrinters.map((p) => (
              <option key={p.id} value={p.id}>
                {p.display_name}
              </option>
            ))}
          </select>
        </div>

        {/* Selected printer info summary */}
        {selectedPrinter && (
          <div className="flex items-center gap-3 text-xs text-gray-500 dark:text-gray-400 pl-0.5">
            <span>
              {t("settings.bed_size")}: {selectedPrinter.bed_width}&times;{selectedPrinter.bed_depth}mm
            </span>
            <span className="text-gray-300 dark:text-gray-600">|</span>
            <span>
              {t("settings.nozzle_count")}: {selectedPrinter.nozzle_count}
            </span>
          </div>
        )}
      </section>

      {/* Cache Management / 缓存管理 */}
      <section className="flex flex-col gap-2">
        <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300">
          {t("settings.cache")}
        </h4>
        <p className="text-xs text-gray-500 dark:text-gray-400">
          {t("settings.clear_cache_desc")}
        </p>
        <div className="flex items-center gap-3">
          <Button
            label={t("settings.clear_cache")}
            onClick={handleClearCache}
            loading={clearing}
            variant="secondary"
          />
          {cacheResult && (
            <span className="text-sm text-green-600 dark:text-green-400">
              {cacheResult}
            </span>
          )}
        </div>
      </section>
    </motion.aside>
  );
}
