import Button from "../components/ui/Button";
import CloseButton from "../components/ui/CloseButton";
import { cx } from "../components/ui/panelPrimitives";
import { useI18n } from "../i18n/context";
import { formatBytes } from "./backend/backendSetup";
import {
  backendDialogShellClass,
  backendDialogTitleClass,
} from "./backend/dialogClasses";
import type { WorkshopMaterialImportConfirmation } from "./runtime/handlers";

interface MaterialImportDialogProps {
  request: WorkshopMaterialImportConfirmation;
  moduleName: string;
  publisher: string | null;
  reviewLevel: string;
  onConfirm(): void;
  onCancel(): void;
}

/**
 * Host confirmation for one Workshop `material.import` call. It renders
 * outside the module frame; the module summary is labelled as untrusted.
 * 宿主在模块 iframe 外确认一次耗材导入；模块提供的说明单独标注。
 */
export function MaterialImportDialog({
  request,
  moduleName,
  publisher,
  reviewLevel,
  onConfirm,
  onCancel,
}: MaterialImportDialogProps) {
  const { t } = useI18n();
  const title = t("workshop.materialImport.title");
  const rows: Array<[string, string]> = [
    [t("workshop.materialImport.module"), `${moduleName} (${request.identity.moduleId} ${request.identity.moduleVersion})`],
    [t("workshop.materialImport.publisher"), publisher ?? "—"],
    [t("workshop.materialImport.review"), reviewLevel],
    [t("workshop.materialImport.file"), `${request.fileName} · ${formatBytes(request.sizeBytes)}`],
  ];
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      data-testid="workshop-material-import-dialog"
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4 backdrop-blur-sm"
    >
      <section className={cx(backendDialogShellClass, "max-w-lg")}>
        <div className="flex items-start justify-between gap-3">
          <h2 className={backendDialogTitleClass}>{title}</h2>
          <CloseButton label={t("common_close")} onClick={onCancel} />
        </div>
        <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
          {t("workshop.materialImport.description")}
        </p>
        <dl className="mt-4 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
          {rows.map(([label, value]) => (
            <div key={label} className="contents">
              <dt className="text-slate-500 dark:text-slate-400">{label}</dt>
              <dd className="break-words text-slate-900 dark:text-slate-50">{value}</dd>
            </div>
          ))}
        </dl>
        {request.summary ? (
          <div className="mt-4 rounded-2xl border border-[color:var(--surface-outline)] p-3">
            <h3 className="text-xs font-semibold text-slate-600 dark:text-slate-300">
              {t("workshop.materialImport.summary")}
            </h3>
            <ul className="mt-2 flex flex-col gap-2 text-sm text-slate-900 dark:text-slate-50">
              {request.summary.materials.map((material, index) => (
                <li key={index} className="break-words">
                  <span className="font-medium">{material.name}</span>
                  {material.brand ? (
                    <span className="text-slate-500 dark:text-slate-400"> · {material.brand}</span>
                  ) : null}
                  {material.notes && material.notes.length > 0 ? (
                    <ul className="mt-1 list-disc pl-5 text-xs leading-5 text-slate-600 dark:text-slate-300">
                      {material.notes.map((note, noteIndex) => (
                        <li key={noteIndex}>{note}</li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <div className="mt-5 flex justify-end gap-2">
          <Button
            label={t("workshop.manager.cancel")}
            variant="secondary"
            onClick={onCancel}
          />
          <Button
            label={t("workshop.materialImport.confirm")}
            variant="primary"
            onClick={onConfirm}
          />
        </div>
      </section>
    </div>
  );
}
