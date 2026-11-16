import { useEffect, useRef } from "react";
import type { JSX } from "react";
import { createPortal } from "react-dom";
import { useI18n } from "../../i18n/context";
import { useDialogFocusTrap } from "../../hooks/useDialogFocusTrap";
import Button from "../ui/Button";
import CloseButton from "../ui/CloseButton";

interface MaterialLayerUnlockDialogProps {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

const WARNING_KEYS = [
  "adv_unlock_material_layers_warn_speed",
  "adv_unlock_material_layers_warn_raster",
  "adv_unlock_material_layers_warn_lock",
] as const;

/**
 * Confirmation shown before unlocking more than 10 colour layers.
 * 解锁 10 层以上叠色前的确认提示。
 */
export default function MaterialLayerUnlockDialog({
  open,
  onConfirm,
  onCancel,
}: MaterialLayerUnlockDialogProps): JSX.Element | null {
  const { t } = useI18n();
  const dialogRef = useRef<HTMLDivElement>(null);
  useDialogFocusTrap(dialogRef, open);

  useEffect(() => {
    if (!open) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCancel();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onCancel]);

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center backdrop-blur-sm"
      style={{ background: "var(--surface-scrim)" }}
      onClick={onCancel}
    >
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="material-layer-unlock-title"
        aria-describedby="material-layer-unlock-body"
        tabIndex={-1}
        className="relative mx-4 flex w-full max-w-md flex-col overflow-hidden rounded-2xl border shadow-2xl outline-none"
        style={{
          borderColor: "var(--warning-border)",
          background: "var(--surface-panel-strong)",
        }}
        onClick={(event) => event.stopPropagation()}
        data-testid="material-layer-unlock-dialog"
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4 dark:border-slate-700">
          <h2
            id="material-layer-unlock-title"
            className="text-base font-semibold text-slate-800 dark:text-slate-100"
          >
            {t("adv_unlock_material_layers_confirm_title")}
          </h2>
          <CloseButton label={t("common_close")} onClick={onCancel} />
        </div>
        <ul
          id="material-layer-unlock-body"
          className="flex list-disc flex-col gap-2 px-5 py-4 pl-9 text-sm leading-6 text-slate-600 dark:text-slate-300"
        >
          {WARNING_KEYS.map((key) => (
            <li key={key}>{t(key)}</li>
          ))}
        </ul>
        <div className="flex justify-end gap-2 border-t border-slate-200 px-5 py-3 dark:border-slate-700">
          <Button label={t("adv_unlock_material_layers_cancel")} variant="secondary" size="sm" onClick={onCancel} />
          <Button
            label={t("adv_unlock_material_layers_confirm")}
            variant="primary"
            size="sm"
            onClick={onConfirm}
          />
        </div>
      </div>
    </div>,
    document.body,
  );
}
