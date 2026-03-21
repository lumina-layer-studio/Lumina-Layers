import "cropperjs/dist/cropper.css";

import { useState, useRef, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import ReactCropper from "react-cropper";
import type { ReactCropperElement } from "react-cropper";
import { useI18n } from "../../i18n/context";

// ========== Types ==========

export interface CropData {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface CropModalProps {
  open: boolean;
  imageSrc: string;
  onConfirm: (cropData: CropData) => void;
  onUseOriginal: () => void;
  onClose: () => void;
  isLoading?: boolean;
}

// ========== Constants ==========

interface AspectRatioPreset {
  label: string;
  value: number;
}

const ASPECT_RATIO_PRESETS: AspectRatioPreset[] = [
  { label: "crop_modal_free", value: NaN },
  { label: "1:1", value: 1 },
  { label: "4:3", value: 4 / 3 },
  { label: "3:2", value: 3 / 2 },
  { label: "16:9", value: 16 / 9 },
  { label: "9:16", value: 9 / 16 },
  { label: "3:4", value: 3 / 4 },
];

// ========== Component ==========

export function CropModal({
  open,
  imageSrc,
  onConfirm,
  onUseOriginal,
  onClose,
  isLoading = false,
}: CropModalProps) {
  const { t } = useI18n();
  const cropperRef = useRef<ReactCropperElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  const [activeRatio, setActiveRatio] = useState<number>(NaN);
  const [naturalWidth, setNaturalWidth] = useState(0);
  const [naturalHeight, setNaturalHeight] = useState(0);
  const [cropX, setCropX] = useState(0);
  const [cropY, setCropY] = useState(0);
  const [cropW, setCropW] = useState(0);
  const [cropH, setCropH] = useState(0);

  // Track whether manual input is in progress to avoid feedback loops
  const isManualInputRef = useRef(false);

  // ---------- Focus trap & Escape ----------

  useEffect(() => {
    if (!open) return;

    previousFocusRef.current = document.activeElement as HTMLElement | null;
    // Focus the modal container after mount
    const timer = setTimeout(() => {
      modalRef.current?.focus();
    }, 50);

    return () => {
      clearTimeout(timer);
      previousFocusRef.current?.focus();
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }

      // Focus trap: Tab / Shift+Tab
      if (e.key === "Tab" && modalRef.current) {
        const focusable = modalRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (focusable.length === 0) return;

        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  // ---------- Cropper callbacks ----------

  const handleCropEvent = useCallback(() => {
    if (isManualInputRef.current) return;
    const cropper = cropperRef.current?.cropper;
    if (!cropper) return;

    const data = cropper.getData(true);
    setCropX(data.x);
    setCropY(data.y);
    setCropW(data.width);
    setCropH(data.height);
  }, []);

  const handleReady = useCallback(() => {
    const cropper = cropperRef.current?.cropper;
    if (!cropper) return;

    const imgData = cropper.getImageData();
    setNaturalWidth(imgData.naturalWidth);
    setNaturalHeight(imgData.naturalHeight);

    const data = cropper.getData(true);
    setCropX(data.x);
    setCropY(data.y);
    setCropW(data.width);
    setCropH(data.height);
  }, []);

  // ---------- Aspect ratio ----------

  const handleAspectRatioChange = useCallback((value: number) => {
    setActiveRatio(value);
    const cropper = cropperRef.current?.cropper;
    if (!cropper) return;
    cropper.setAspectRatio(value);
  }, []);

  // ---------- Manual coordinate input ----------

  const syncManualInput = useCallback(
    (field: "x" | "y" | "width" | "height", raw: string) => {
      const num = parseInt(raw, 10);
      if (isNaN(num) || num < 0) return;

      const cropper = cropperRef.current?.cropper;
      if (!cropper) return;

      isManualInputRef.current = true;

      const current = cropper.getData(true);
      const updated = { ...current, [field]: num };
      cropper.setData(updated);

      // Read back the actual data after setData (cropper may clamp)
      const actual = cropper.getData(true);
      setCropX(actual.x);
      setCropY(actual.y);
      setCropW(actual.width);
      setCropH(actual.height);

      isManualInputRef.current = false;
    },
    []
  );

  // ---------- Confirm ----------

  const handleConfirm = useCallback(() => {
    const cropper = cropperRef.current?.cropper;
    if (!cropper) return;

    const data = cropper.getData(true);
    onConfirm({
      x: data.x,
      y: data.y,
      width: data.width,
      height: data.height,
    });
  }, [onConfirm]);

  // ---------- Render ----------

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onClose}
      role="presentation"
    >
      {/* Modal panel */}
      <div
        ref={modalRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={t("crop_modal_title")}
        onClick={(e) => e.stopPropagation()}
        className="relative flex max-h-[90vh] w-full max-w-3xl flex-col rounded-lg bg-white shadow-2xl outline-none dark:bg-gray-800"
      >
        {/* Title bar */}
        <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3 dark:border-gray-700">
          <h2 className="text-base font-semibold text-gray-800 dark:text-gray-100">
            {t("crop_modal_title")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-gray-200"
            aria-label={t("crop_modal_close")}
          >
            <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
              <path
                fillRule="evenodd"
                d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                clipRule="evenodd"
              />
            </svg>
          </button>
        </div>

        {/* Cropper area */}
        <div className="min-h-0 flex-1 overflow-hidden px-4 py-3">
          <ReactCropper
            ref={cropperRef}
            src={imageSrc}
            style={{ height: "100%", maxHeight: "50vh", width: "100%" }}
            viewMode={1}
            dragMode="crop"
            autoCropArea={1}
            responsive={true}
            guides={true}
            crop={handleCropEvent}
            ready={handleReady}
          />
        </div>

        {/* Info bar */}
        <div className="flex flex-wrap items-center gap-4 border-t border-gray-200 px-4 py-2 text-xs text-gray-600 dark:border-gray-700 dark:text-gray-400">
          <span>
            {t("crop_modal_original")}: {naturalWidth} x {naturalHeight} px
          </span>
          <span>
            {t("crop_modal_selection")}: {cropW} x {cropH} px
          </span>
        </div>

        {/* Aspect ratio presets */}
        <div className="flex flex-wrap gap-1.5 px-4 py-2">
          {ASPECT_RATIO_PRESETS.map((preset) => {
            const isActive =
              (isNaN(activeRatio) && isNaN(preset.value)) ||
              activeRatio === preset.value;
            return (
              <button
                key={preset.label}
                type="button"
                onClick={() => handleAspectRatioChange(preset.value)}
                className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                  isActive
                    ? "bg-blue-600 text-white"
                    : "bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600"
                }`}
              >
                {preset.label === "crop_modal_free" ? t("crop_modal_free") : preset.label}
              </button>
            );
          })}
        </div>

        {/* Manual coordinate inputs */}
        <div className="flex flex-wrap gap-3 px-4 py-2">
          {(
            [
              { label: "X", value: cropX, field: "x" },
              { label: "Y", value: cropY, field: "y" },
              { label: t("crop_width"), value: cropW, field: "width" },
              { label: t("crop_height"), value: cropH, field: "height" },
            ] as const
          ).map((item) => (
            <label key={item.label} className="flex items-center gap-1.5 text-xs">
              <span className="text-gray-600 dark:text-gray-400">
                {item.label}
              </span>
              <input
                type="number"
                min={0}
                value={item.value}
                onChange={(e) => syncManualInput(item.field, e.target.value)}
                className="w-20 rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-800 outline-none focus:border-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200"
              />
            </label>
          ))}
        </div>

        {/* Bottom buttons */}
        <div className="flex items-center justify-end gap-3 border-t border-gray-200 px-4 py-3 dark:border-gray-700">
          <button
            type="button"
            onClick={onUseOriginal}
            disabled={isLoading}
            className="rounded-md bg-gray-600 px-4 py-2 text-sm font-medium text-gray-200 transition-colors hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {t("crop_modal_use_original")}
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={isLoading}
            className="flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {isLoading && (
              <svg
                className="h-4 w-4 animate-spin"
                viewBox="0 0 24 24"
                fill="none"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                />
              </svg>
            )}
            {t("crop_modal_confirm")}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
