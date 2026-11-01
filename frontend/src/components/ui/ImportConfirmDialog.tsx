import CloseButton from "./CloseButton";
import { createPortal } from "react-dom";
import { useI18n } from "../../i18n/context";
import Button from "./Button";
import type { ImportPreview } from "../../recipe/importFlow";
import type { RecipeFileSource } from "../../recipe/importRecipe";

interface ImportConfirmDialogProps {
  open: boolean;
  preview: ImportPreview | null;
  source: RecipeFileSource;
  onConfirm: () => void;
  onContinueEditing?: () => void;
  onCancel: () => void;
  isLoading?: boolean;
}

export default function ImportConfirmDialog({
  open,
  preview,
  source,
  onConfirm,
  onContinueEditing,
  onCancel,
  isLoading,
}: ImportConfirmDialogProps) {
  const { t } = useI18n();
  const localizeWarning = (warning: string) => {
    const localized = t(warning);
    return localized === warning ? warning : localized;
  };

  if (!open || !preview) return null;

  const { recipe, restoreResult } = preview;
  const conv = recipe.recipe.converter;

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center backdrop-blur-sm"
      style={{ background: "var(--surface-scrim)" }}
      onClick={onCancel}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("recipe_import_title")}
        className="relative mx-4 flex max-h-[90vh] w-full max-w-md flex-col overflow-hidden rounded-2xl border shadow-2xl"
        style={{
          borderColor: "var(--surface-outline)",
          background: "var(--surface-panel-strong)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4 dark:border-slate-700">
          <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100">
            {t("recipe_import_title")}
          </h2>
          <CloseButton label={t("common_close")} onClick={onCancel} />
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto overscroll-y-contain px-5 py-4">
          {/* Cover preview */}
          {recipe.cover && (
            <div className="mb-4 flex justify-center">
              <div className="overflow-hidden rounded-xl border border-slate-200 dark:border-slate-700">
                {preview.coverUrl ? (
                  <img
                    src={preview.coverUrl}
                    alt={recipe.asset.primary.filename}
                    className="block bg-slate-100 object-contain dark:bg-slate-800"
                    style={{
                      maxWidth: 320,
                      maxHeight: 200,
                    }}
                  />
                ) : (
                  <div
                    className="flex items-center justify-center bg-slate-100 text-xs text-slate-400 dark:bg-slate-800 dark:text-slate-500"
                    style={{
                      width: Math.min(recipe.cover.width, 320),
                      height: Math.min(recipe.cover.height, 200),
                    }}
                  >
                    {recipe.asset.primary.filename}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Info grid */}
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
            <dt className="text-slate-500 dark:text-slate-400">
              {t("recipe_import_source_label")}
            </dt>
            <dd className="text-slate-800 dark:text-slate-200">
              {source === "png"
                ? t("recipe_import_source_png")
                : t("recipe_import_source_json")}
            </dd>

            <dt className="text-slate-500 dark:text-slate-400">
              {t("recipe_import_version_label")}
            </dt>
            <dd className="text-slate-800 dark:text-slate-200">
              {recipe.app_version}
            </dd>

            <dt className="text-slate-500 dark:text-slate-400">
              {t("recipe_import_created_label")}
            </dt>
            <dd className="text-slate-800 dark:text-slate-200">
              {new Date(recipe.created_at).toLocaleString()}
            </dd>

            {conv && (
              <>
                {(conv.source?.source_version ?? "legacy") === "legacy" && (
                  <>
                    <dt className="text-slate-500 dark:text-slate-400">
                      {t("recipe_import_lut_label")}
                    </dt>
                    <dd className="text-slate-800 dark:text-slate-200">
                      {conv.base.lut.name}
                    </dd>
                  </>
                )}

                <dt className="text-slate-500 dark:text-slate-400">
                  {t("recipe_import_color_mode_label")}
                </dt>
                <dd className="text-slate-800 dark:text-slate-200">
                  {conv.base.color_mode}
                </dd>

                <dt className="text-slate-500 dark:text-slate-400">
                  {t("recipe_import_size_label")}
                </dt>
                <dd className="text-slate-800 dark:text-slate-200">
                  {conv.base.target_width_mm} × {conv.base.target_height_mm} {t("common_unit_mm")}
                </dd>
              </>
            )}
          </dl>

          {/* Warnings */}
          {restoreResult.warnings.length > 0 && (
            <div className="mt-4">
              <p className="mb-1.5 text-xs font-medium text-amber-600 dark:text-amber-400">
                {t("recipe_import_warnings_label")}
              </p>
              <ul className="space-y-1">
                {restoreResult.warnings.map((w, i) => (
                  <li
                    key={i}
                    className="rounded-lg bg-amber-50 px-3 py-1.5 text-xs text-amber-700 dark:bg-amber-900/30 dark:text-amber-300"
                  >
                    {localizeWarning(w)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-slate-200 px-5 py-3 dark:border-slate-700">
          <Button
            label={t("recipe_import_cancel")}
            variant="secondary"
            onClick={onCancel}
            disabled={isLoading}
            className="px-4"
          />
          {restoreResult.state.workshopSource &&
            onContinueEditing && (
              <Button
                label={t("recipe_import_continue_workshop")}
                variant="secondary"
                onClick={onContinueEditing}
                disabled={isLoading}
                className="px-4"
              />
            )}
          <Button
            label={t("recipe_import_confirm")}
            variant="primary"
            onClick={onConfirm}
            disabled={isLoading}
            loading={isLoading}
            className="px-4"
          />
        </div>
      </div>
    </div>,
    document.body,
  );
}
