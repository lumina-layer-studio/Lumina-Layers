import CloseButton from "./CloseButton";
import "cropperjs/dist/cropper.css";

import { useState, useRef, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import ReactCropper from "react-cropper";
import type { ReactCropperElement } from "react-cropper";
import { ArrowUturnLeftIcon, ArrowUturnRightIcon } from "@heroicons/react/24/outline";
import { useI18n } from "../../i18n/context";
import type { ImageRotationDegrees } from "../../utils/imageRotation";
import Button from "./Button";
import { compactFieldClass, cx } from "./panelPrimitives";
import { wheelZoomDelta, wheelZoomFactor } from "../../utils/wheelZoom";

// ========== Types ==========

export interface CropData {
  x: number;
  y: number;
  width: number;
  height: number;
  rotation: 0 | ImageRotationDegrees;
}

export interface CropModalProps {
  open: boolean;
  imageSrc: string;
  onConfirm: (cropData: CropData) => void;
  onUseOriginal: () => void;
  onClose: () => void;
  isLoading?: boolean;
  allowCrop?: boolean;
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

export function CropModal({ open, ...props }: CropModalProps) {
  return open ? <CropModalContent key={props.imageSrc} {...props} /> : null;
}

function CropModalContent({
  imageSrc,
  onConfirm,
  onUseOriginal,
  onClose,
  isLoading = false,
  allowCrop = true,
}: Omit<CropModalProps, "open">) {
  const { t } = useI18n();
  const cropperRef = useRef<ReactCropperElement>(null);
  const cropAreaRef = useRef<HTMLDivElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  const [activeRatio, setActiveRatio] = useState<number>(NaN);
  const [naturalWidth, setNaturalWidth] = useState(0);
  const [naturalHeight, setNaturalHeight] = useState(0);
  const [cropX, setCropX] = useState(0);
  const [cropY, setCropY] = useState(0);
  const [cropW, setCropW] = useState(0);
  const [cropH, setCropH] = useState(0);
  const [rotation, setRotation] = useState<0 | ImageRotationDegrees>(0);
  const [isReady, setIsReady] = useState(false);
  const controlsDisabled = isLoading || !isReady;

  // Track whether manual input is in progress to avoid feedback loops
  const isManualInputRef = useRef(false);

  // ---------- Focus trap & Escape ----------

  useEffect(() => {
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    // Focus the modal container after mount
    const timer = setTimeout(() => {
      modalRef.current?.focus();
    }, 50);

    return () => {
      clearTimeout(timer);
      previousFocusRef.current?.focus();
    };
  }, []);

  useEffect(() => {
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
  }, [onClose]);

  // ---------- Cropper callbacks ----------

  useEffect(() => {
    const area = cropAreaRef.current;
    if (controlsDisabled || !area) return;
    const handleWheel = (event: WheelEvent) => {
      const cropper = cropperRef.current?.cropper;
      if (!cropper) return;
      event.preventDefault();
      event.stopPropagation();
      const delta = wheelZoomDelta(event.deltaY, event.deltaMode, area.clientHeight);
      if (delta === 0) return;
      const canvas = cropper.getCanvasData();
      if (!(canvas.naturalWidth > 0) || !(canvas.width > 0)) return;
      const rect = (area.querySelector(".cropper-container") ?? area).getBoundingClientRect();
      cropper.zoomTo(canvas.width / canvas.naturalWidth * wheelZoomFactor(delta), {
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      });
    };
    area.addEventListener("wheel", handleWheel, { passive: false });
    return () => area.removeEventListener("wheel", handleWheel);
  }, [controlsDisabled]);

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
    if (!(imgData.naturalWidth > 0) || !(imgData.naturalHeight > 0)) return;
    setNaturalWidth(imgData.naturalWidth);
    setNaturalHeight(imgData.naturalHeight);

    const data = cropper.getData(true);
    setCropX(data.x);
    setCropY(data.y);
    setCropW(data.width);
    setCropH(data.height);
    setIsReady(true);
  }, []);

  // ---------- Aspect ratio ----------

  const handleAspectRatioChange = useCallback((value: number) => {
    if (controlsDisabled) return;
    setActiveRatio(value);
    const cropper = cropperRef.current?.cropper;
    if (!cropper) return;
    cropper.setAspectRatio(value);
  }, [controlsDisabled]);

  // ---------- Manual coordinate input ----------

  const handleRotate = (delta: number) => {
    const cropper = cropperRef.current?.cropper;
    if (!cropper || controlsDisabled) return;
    const next = ((rotation + delta + 360) % 360) as 0 | ImageRotationDegrees;
    // Refit the selection to the rotated image instead of clipping its edges.
    cropper.clear();
    cropper.rotateTo(next);
    const canvas = cropper.getCanvasData();
    const container = cropper.getContainerData();
    const zoom = Math.min(container.width / canvas.naturalWidth, container.height / canvas.naturalHeight);
    cropper.zoomTo(zoom);
    cropper.setCanvasData({
      left: (container.width - canvas.naturalWidth * zoom) / 2,
      top: (container.height - canvas.naturalHeight * zoom) / 2,
    });
    if (allowCrop) {
      cropper.crop();
      cropper.setData({ x: 0, y: 0, width: canvas.naturalWidth, height: canvas.naturalHeight });
    }
    setRotation(next);
    handleCropEvent();
  };

  const syncManualInput = useCallback(
    (field: "x" | "y" | "width" | "height", raw: string) => {
      if (controlsDisabled) return;
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
    [controlsDisabled]
  );

  // ---------- Confirm ----------

  const handleConfirm = useCallback(() => {
    if (controlsDisabled) return;
    const cropper = cropperRef.current?.cropper;
    if (!cropper) return;

    const data = cropper.getData(true);
    onConfirm({
      x: data.x,
      y: data.y,
      width: data.width,
      height: data.height,
      rotation,
    });
  }, [controlsDisabled, onConfirm, rotation]);

  // ---------- Render ----------

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
        className="relative flex max-h-[90vh] w-full max-w-3xl flex-col overflow-y-auto overscroll-y-contain rounded-2xl bg-slate-50 outline-none dark:bg-slate-900"
      >
        {/* Title bar */}
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-700">
          <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100">
            {t("crop_modal_title")}
          </h2>
          <CloseButton label={t("crop_modal_close")} onClick={onClose} />
        </div>

        {/* Cropper area */}
        <div ref={cropAreaRef} className="h-[42vh] shrink-0 overflow-hidden px-4 py-3">
          <ReactCropper
            ref={cropperRef}
            src={imageSrc}
            style={{ height: "100%", maxHeight: "50vh", width: "100%" }}
            viewMode={1}
            dragMode={allowCrop ? "crop" : "move"}
            autoCrop={allowCrop}
            autoCropArea={1}
            responsive={true}
            zoomOnWheel={false}
            guides={true}
            crop={handleCropEvent}
            ready={handleReady}
          />
        </div>

        {/* Info bar */}
        <div className="flex flex-wrap items-center gap-4 border-t border-slate-200 px-4 py-2 text-xs text-slate-600 dark:border-slate-700 dark:text-slate-400">
          <span>
            {t("crop_modal_original")}: {naturalWidth} × {naturalHeight} {t("common_unit_px")}
          </span>
          {allowCrop && <span>
            {t("crop_modal_selection")}: {cropW} × {cropH} {t("common_unit_px")}
          </span>}
        </div>

        {/* Aspect ratio presets */}
        <div className="flex flex-wrap gap-2 px-4 py-2">
          <Button label={t("crop_modal_rotate_left")} variant="secondary" size="sm"
            leadingIcon={<ArrowUturnLeftIcon className="size-4" />}
            onClick={() => handleRotate(-90)} disabled={controlsDisabled} />
          <Button label={t("crop_modal_rotate_right")} variant="secondary" size="sm"
            leadingIcon={<ArrowUturnRightIcon className="size-4" />}
            onClick={() => handleRotate(90)} disabled={controlsDisabled} />
        </div>
        {!allowCrop && <p className="px-4 py-2 text-sm text-slate-500 dark:text-slate-400">{t("crop_modal_svg_rotation_only")}</p>}
        {allowCrop && <div className="flex flex-wrap gap-1.5 px-4 py-2">
          {ASPECT_RATIO_PRESETS.map((preset) => {
            const isActive =
              (isNaN(activeRatio) && isNaN(preset.value)) ||
              activeRatio === preset.value;
            return (
              <Button
                key={preset.label}
                label={preset.label === "crop_modal_free" ? t("crop_modal_free") : preset.label}
                variant="ghost"
                size="sm"
                active={isActive}
                disabled={controlsDisabled}
                onClick={() => handleAspectRatioChange(preset.value)}
              />
            );
          })}
        </div>}

        {/* Manual coordinate inputs */}
        {allowCrop && <div className="grid grid-cols-2 gap-3 px-4 py-2 sm:grid-cols-4">
          {(
            [
              { label: t("crop_modal_axis_x"), value: cropX, field: "x" },
              { label: t("crop_modal_axis_y"), value: cropY, field: "y" },
              { label: t("crop_width"), value: cropW, field: "width" },
              { label: t("crop_height"), value: cropH, field: "height" },
            ] as const
          ).map((item) => (
            <label key={item.label} className="flex min-w-0 flex-col gap-1.5 text-xs">
              <span className="text-slate-600 dark:text-slate-400">
                {item.label}
              </span>
              <input
                type="number"
                min={0}
                value={item.value}
                disabled={controlsDisabled}
                onChange={(e) => syncManualInput(item.field, e.target.value)}
                className={cx(compactFieldClass, "py-1 text-xs")}
              />
            </label>
          ))}
        </div>}

        {/* Bottom buttons */}
        <div className="flex items-center justify-end gap-3 border-t border-slate-200 px-4 py-3 dark:border-slate-700">
          <Button
            label={t("crop_modal_use_original")}
            variant="secondary"
            onClick={onUseOriginal}
            disabled={isLoading}
          />
          <Button
            label={t("crop_modal_confirm")}
            onClick={handleConfirm}
            loading={isLoading}
            disabled={controlsDisabled}
            variant="primary"
          />
        </div>
      </div>
    </div>,
    document.body
  );
}
