import CloseButton from "../ui/CloseButton";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { getMachineRegistryAssetUrl } from "../../api/system";
import type { PrinterInfo, SlicerOption } from "../../api/types";
import { useI18n } from "../../i18n/context";
import { getPrinterNozzleSizeOptions } from "../../utils/settingsOptionIds";
import SlicerLogo from "../slicer/SlicerLogo";
import Button from "../ui/Button";
import Dropdown from "../ui/Dropdown";
import {
  cx,
  workstationInputClass,
} from "../ui/panelPrimitives";

interface MachineSelectionDialogProps {
  description?: string;
  footer?: ReactNode;
  open: boolean;
  printers: PrinterInfo[];
  slicers: SlicerOption[];
  printersLoading: boolean;
  slicersLoading: boolean;
  slicerSoftware: string;
  printerModel: string;
  nozzleSize: string;
  onSlicerChange: (id: string) => void;
  onPrinterChange: (id: string) => void;
  onPrinterNozzleChange: (printer: PrinterInfo, value: string) => void;
  onClose: () => void;
}

type PrinterBrandGroup = {
  brand: string;
  printers: PrinterInfo[];
};

function getMachinePlaceholderLabel(printer: PrinterInfo): string {
  const compactBrand = printer.brand.replace(/\s+/g, "");
  return (compactBrand || printer.display_name).slice(0, 2).toUpperCase();
}

/**
 * Searchable machine registry dialog used by system settings.
 * 系统设置使用的可搜索机器选择弹窗。
 */
export default function MachineSelectionDialog({
  description,
  footer,
  open,
  printers,
  slicers,
  printersLoading,
  slicersLoading,
  slicerSoftware,
  printerModel,
  nozzleSize,
  onSlicerChange,
  onPrinterChange,
  onPrinterNozzleChange,
  onClose,
}: MachineSelectionDialogProps) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    setQuery("");
    searchInputRef.current?.focus();

    return () => {
      previousFocusRef.current?.focus();
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }

      if (event.key === "Tab" && dialogRef.current) {
        const focusableElements = dialogRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        );
        if (focusableElements.length === 0) return;

        const firstFocusableElement = focusableElements[0];
        const lastFocusableElement =
          focusableElements[focusableElements.length - 1];

        if (event.shiftKey && document.activeElement === firstFocusableElement) {
          event.preventDefault();
          lastFocusableElement.focus();
        } else if (
          !event.shiftKey &&
          document.activeElement === lastFocusableElement
        ) {
          event.preventDefault();
          firstFocusableElement.focus();
        }
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose, open]);

  const visiblePrinters = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    if (!normalizedQuery) return printers;
    return printers.filter((printer) =>
      `${printer.brand} ${printer.display_name}`
        .toLocaleLowerCase()
        .includes(normalizedQuery),
    );
  }, [printers, query]);

  const groupedPrinters = useMemo<PrinterBrandGroup[]>(() => {
    const groups = new Map<string, PrinterInfo[]>();
    for (const printer of visiblePrinters) {
      const current = groups.get(printer.brand);
      if (current) {
        current.push(printer);
      } else {
        groups.set(printer.brand, [printer]);
      }
    }
    return Array.from(groups, ([brand, grouped]) => ({
      brand,
      printers: grouped,
    }));
  }, [visiblePrinters]);

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center p-3 backdrop-blur-sm sm:p-5"
      style={{ background: "var(--surface-scrim)" }}
      onClick={onClose}
      data-testid="machine-selection-dialog-overlay"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="machine-selection-dialog-title"
        aria-describedby="machine-selection-dialog-description"
        data-testid="machine-selection-dialog"
        className="panel-card grid max-h-[90vh] w-full max-w-5xl grid-rows-[auto_auto_minmax(0,1fr)_auto] overflow-hidden rounded-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-4 border-b panel-divider px-4 py-4 sm:px-6">
          <div className="min-w-0">
            <h2
              id="machine-selection-dialog-title"
              className="text-[15px] font-semibold text-slate-900 dark:text-slate-50"
            >
              {t("settings.machine_dialog_title")}
            </h2>
            <p
              id="machine-selection-dialog-description"
              className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400"
            >
              {description ?? t("settings.machine_dialog_description")}
            </p>
          </div>
          <CloseButton label={t("settings.machine_dialog_close")} onClick={onClose} />
        </header>

        <div className="grid gap-3 border-b panel-divider px-4 py-4 sm:grid-cols-[minmax(14rem,0.75fr)_minmax(18rem,1.25fr)] sm:px-6">
          <Dropdown
            label={t("settings.slicer_software")}
            value={slicerSoftware}
            onChange={onSlicerChange}
            disabled={slicersLoading}
            options={slicers.map((slicer) => ({
              label: slicer.display_name,
              value: slicer.id,
              leading: <SlicerLogo slicerId={slicer.id} />,
            }))}
          />
          <div className="flex min-w-0 flex-col gap-1.5">
            <label
              htmlFor="machine-selection-search"
              className="text-sm font-medium text-slate-700 dark:text-slate-200"
            >
              {t("settings.machine_search_label")}
            </label>
            <input
              ref={searchInputRef}
              id="machine-selection-search"
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              aria-label={t("settings.machine_search_label")}
              placeholder={t("settings.machine_search_placeholder")}
              className={workstationInputClass}
            />
          </div>
        </div>

        <div
          data-testid="machine-adapter-grid"
          className="dock-scrollbar min-h-0 overflow-y-auto overscroll-contain px-4 py-4 sm:px-6"
        >
          {printersLoading ? (
            <p className="text-sm text-slate-500 dark:text-slate-400">
              {t("settings.machine_options_loading")}
            </p>
          ) : groupedPrinters.length === 0 ? (
            <div className="panel-well rounded-[10px] px-4 py-8 text-center">
              <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
                {t("settings.machine_search_empty")}
              </p>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                {t("settings.machine_search_empty_hint")}
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-5">
              {groupedPrinters.map((group) => (
                <section key={group.brand} className="flex flex-col gap-2.5">
                  <div className="flex items-center gap-2">
                    <h3 className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      {group.brand}
                    </h3>
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      {group.printers.length}
                    </span>
                  </div>
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {group.printers.map((printer) => {
                      const isSelected = printer.id === printerModel;
                      const thumbnailUrl = printer.thumbnail
                        ? getMachineRegistryAssetUrl(printer.thumbnail)
                        : null;
                      const nozzleOptions = getPrinterNozzleSizeOptions(
                        printer,
                        slicerSoftware,
                      );

                      return (
                        <div
                          key={printer.id}
                          className={cx(
                            "group rounded-[10px] p-3 transition-colors duration-200",
                            isSelected
                              ? "bg-blue-500/10 dark:bg-blue-400/10"
                              : "panel-well hover:bg-[var(--nav-chip-hover)]",
                          )}
                        >
                          <button
                            type="button"
                            aria-pressed={isSelected}
                            data-testid={`machine-adapter-card-${printer.id}`}
                            onClick={() => onPrinterChange(printer.id)}
                            disabled={printersLoading}
                            className="grid min-h-[7.25rem] w-full grid-cols-[5.5rem_minmax(0,1fr)] gap-3 rounded-lg text-left transition-opacity focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)] disabled:cursor-not-allowed disabled:opacity-45"
                          >
                            <span
                              className={cx(
                                "flex aspect-square w-[5.5rem] items-center justify-center overflow-hidden",
                                thumbnailUrl
                                  ? "rounded-none bg-transparent"
                                  : "rounded-lg bg-[var(--surface-card)]",
                              )}
                            >
                              {thumbnailUrl ? (
                                <img
                                  src={thumbnailUrl}
                                  alt={printer.display_name}
                                  className="h-full w-full object-contain p-0"
                                  loading="lazy"
                                />
                              ) : (
                                <span className="text-lg font-semibold text-slate-400 dark:text-slate-500">
                                  {getMachinePlaceholderLabel(printer)}
                                </span>
                              )}
                            </span>
                            <span className="flex min-w-0 flex-col gap-1.5">
                              <span className="truncate text-sm font-semibold text-slate-900 dark:text-slate-50">
                                {printer.display_name}
                              </span>
                              <span className="text-xs text-slate-500 dark:text-slate-400">
                                {printer.brand}
                              </span>
                              <span className="text-xs text-slate-500 dark:text-slate-400">
                                {t("settings.bed_size")}: {printer.bed_width}
                                &times;{printer.bed_depth} {t("common_unit_mm")}
                              </span>
                              <span className="text-xs text-slate-500 dark:text-slate-400">
                                {t("settings.nozzle_size")}:{" "}
                                {nozzleOptions
                                  .map(
                                    (size) =>
                                      `${size} ${t("common_unit_mm")}`,
                                  )
                                  .join(", ")}
                              </span>
                            </span>
                          </button>
                          <div className="mt-3 flex flex-wrap gap-2 border-t panel-divider pt-3">
                            {nozzleOptions.map((size) => {
                              const isNozzleSelected =
                                isSelected && size === nozzleSize;
                              return (
                                <button
                                  key={size}
                                  type="button"
                                  aria-pressed={isNozzleSelected}
                                  aria-label={`${printer.display_name} ${size} ${t("common_unit_mm")}`}
                                  data-testid={`machine-adapter-nozzle-${printer.id}-${size.replace(/\./g, "_")}`}
                                  onClick={() =>
                                    onPrinterNozzleChange(printer, size)
                                  }
                                  disabled={printersLoading}
                                  className={cx(
                                    "ghost-control min-h-11 rounded-lg px-3 text-xs font-medium",
                                    isNozzleSelected
                                      ? "text-blue-700 dark:text-blue-200"
                                      : "text-slate-600 dark:text-slate-300",
                                  )}
                                >
                                  {size} {t("common_unit_mm")}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
          )}
        </div>

        <footer className="max-h-[40vh] overflow-y-auto border-t panel-divider px-4 py-3 sm:px-6">
          {footer}
          <div className="flex justify-end">
          <Button
            label={t("settings.machine_dialog_done")}
            onClick={onClose}
          />
          </div>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
