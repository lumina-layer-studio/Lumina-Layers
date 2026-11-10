import type {
  WorkshopUninstallReport,
  WorkshopUninstallReportItem,
} from "../../api/workshop";
import Button from "../../components/ui/Button";
import CloseButton from "../../components/ui/CloseButton";
import { cx } from "../../components/ui/panelPrimitives";
import { useI18n } from "../../i18n/context";
import { formatBytes } from "./backendSetup";
import { backendDialogShellClass, backendDialogTitleClass } from "./dialogClasses";

const SECTIONS = ["cleared", "shared", "retained", "failed"] as const;

interface UninstallReportDialogProps {
  report: WorkshopUninstallReport;
  onClose(): void;
}

/** What an uninstall cleaned, still shares, kept by choice, or could not delete. */
export function UninstallReportDialog({ report, onClose }: UninstallReportDialogProps) {
  const { t } = useI18n();
  const describe = (item: WorkshopUninstallReportItem): string => {
    const parts = [t(`workshop.report.kind.${item.kind}`)];
    if (item.label) {
      parts.push(item.label);
    }
    if (typeof item.bytes === "number" && item.bytes > 0) {
      parts.push(formatBytes(item.bytes));
    }
    if (item.users && item.users.length > 0) {
      parts.push(t("workshop.report.users").replace("{users}", item.users.join(", ")));
    }
    if (item.will_retry) {
      parts.push(t("workshop.report.willRetry"));
    }
    return parts.join(" · ");
  };
  const title = t("workshop.report.title");
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4 backdrop-blur-sm"
    >
      <section className={cx(backendDialogShellClass, "max-w-lg")}>
        <div className="flex items-start justify-between gap-3">
          <h2 className={backendDialogTitleClass}>{title}</h2>
          <CloseButton label={t("common_close")} onClick={onClose} />
        </div>
        {SECTIONS.map((section) => (
          <div key={section} className="mt-4">
            <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-50">
              {t(`workshop.report.${section}`)}
            </h3>
            {report[section].length === 0 ? (
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{t("workshop.report.none")}</p>
            ) : (
              <ul className="mt-1 flex flex-col gap-1 text-xs leading-5 text-slate-600 dark:text-slate-300">
                {report[section].map((item, index) => (
                  <li key={`${section}-${index}`}>{describe(item)}</li>
                ))}
              </ul>
            )}
          </div>
        ))}
        <p className="mt-4 text-xs leading-5 text-slate-500 dark:text-slate-400">
          {t("workshop.report.scope")}
        </p>
        <div className="mt-5 flex justify-end">
          <Button label={t("workshop.manager.close")} variant="secondary" onClick={onClose} />
        </div>
      </section>
    </div>
  );
}

export default UninstallReportDialog;
