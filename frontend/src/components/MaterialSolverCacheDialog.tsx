import CloseButton from "./ui/CloseButton";
import { useState } from "react";
import { createPortal } from "react-dom";

import { useI18n } from "../i18n/context";
import MaterialSolverCacheStatusCard from "./MaterialSolverCacheStatusCard";
import Button from "./ui/Button";

interface MaterialSolverCacheDialogProps {
  /** User-selected material directory names (ordered as in the picker). */
  materialDirectoryNames: string[];
  /** Number of layers in the solver recipe. */
  layerCount: number;
  /** Layer thickness in millimetres. */
  layerHeightMm: number;
  /** Substrate — currently always ``"white"`` in the converter flow. */
  substrate?: "white" | "black";
}

/**
 * Trigger button + modal dialog wrapping ``MaterialSolverCacheStatusCard``.
 * 按钮 + 弹窗壳：复用 MaterialSolverCacheStatusCard 的完整状态/操作。
 *
 * Keeps the inline BasicSettings panel compact by hiding the cache management
 * UI behind a single button; opens a dialog only on demand.
 */
export default function MaterialSolverCacheDialog({
  materialDirectoryNames,
  layerCount,
  layerHeightMm,
  substrate = "white",
}: MaterialSolverCacheDialogProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const disabled = materialDirectoryNames.length === 0;

  return (
    <>
      <Button
        label={t("basic_material_cache_open_button")}
        variant="secondary"
        onClick={() => setOpen(true)}
        disabled={disabled}
        className="px-3 text-xs"
      />
      {open
        ? createPortal(
            <div
              className="fixed inset-0 z-[9999] flex items-center justify-center backdrop-blur-sm"
              style={{ background: "var(--surface-scrim)" }}
              onClick={() => setOpen(false)}
              data-testid="material-solver-cache-dialog-overlay"
            >
              <div
                role="dialog"
                aria-modal="true"
                aria-label={t("basic_material_cache_section_title")}
                className="relative mx-4 flex max-h-[85vh] w-full max-w-md flex-col overflow-hidden rounded-2xl border shadow-2xl"
                style={{
                  borderColor: "var(--surface-outline)",
                  background: "var(--surface-panel-strong)",
                }}
                onClick={(e) => e.stopPropagation()}
                data-testid="material-solver-cache-dialog"
              >
                <div className="flex items-start justify-between border-b border-slate-200 px-5 py-4 dark:border-slate-700">
                  <div className="flex flex-col gap-1">
                    <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100">
                      {t("basic_material_cache_section_title")}
                    </h2>
                  </div>
                  <CloseButton label={t("basic_material_picker_close")} onClick={() => setOpen(false)} />
                </div>
                <div className="flex-1 overflow-y-auto overscroll-y-contain px-5 py-4">
                  <MaterialSolverCacheStatusCard
                    materialDirectoryNames={materialDirectoryNames}
                    layerCount={layerCount}
                    layerHeightMm={layerHeightMm}
                    substrate={substrate}
                  />
                </div>
              </div>
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
