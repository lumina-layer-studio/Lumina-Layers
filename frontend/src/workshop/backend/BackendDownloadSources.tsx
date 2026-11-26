import type { WorkshopBackendStatus, WorkshopDownloadCategory, WorkshopDownloadPreferences, WorkshopDownloadRoute } from "../../api/workshop";
import { workstationInputClass } from "../../components/ui/panelPrimitives";
import { useI18n } from "../../i18n/context";
import { downloadSourceName, formatBytes } from "./backendSetup";

const CATEGORIES: WorkshopDownloadCategory[] = ["python", "wheels", "models", "artifacts"];

interface ExpectedSource {
  source: string;
  count: number;
  bytes: number;
  unknownSizeCount: number;
}

function expectedSources(routes: WorkshopDownloadRoute[], preferred: string): ExpectedSource[] {
  const groups = new Map<string, ExpectedSource>();
  for (const route of routes) {
    let source = route.original;
    if (preferred === "auto") {
      source = route.sources[0] ?? route.original;
    } else if (route.sources.includes(preferred)) {
      source = preferred;
    }
    const entry = groups.get(source) ?? { source, count: 0, bytes: 0, unknownSizeCount: 0 };
    entry.count += route.count;
    entry.bytes += route.bytes ?? 0;
    entry.unknownSizeCount += route.unknown_size_count ?? (route.bytes == null ? route.count : 0);
    groups.set(source, entry);
  }
  return [...groups.values()];
}

export function BackendDownloadSources({ status, preferences, disabled, onChange }: {
  status: WorkshopBackendStatus;
  preferences: WorkshopDownloadPreferences;
  disabled: boolean;
  onChange: (preferences: WorkshopDownloadPreferences) => void;
}) {
  const { t } = useI18n();
  const items = CATEGORIES.map((category) => {
    const routes = status.download_plan?.[category];
    const choices = routes
      ? [...new Set(routes.flatMap((route) => route.sources.filter((source) => source && source !== route.original)))]
      : [...(status.download_sources?.[category] ?? [])];
    const selected = preferences[category] ?? "auto";
    if (choices.length && selected !== "auto" && selected !== "original" && !choices.includes(selected)) {
      choices.push(selected);
    }
    return { category, choices, selected, plan: expectedSources(routes ?? [], selected) };
  });
  const plans = items.filter((item) => item.plan.length > 0);
  const controls = items.filter((item) => item.choices.length > 0);

  const sizeText = ({ bytes, unknownSizeCount }: ExpectedSource) => {
    if (unknownSizeCount > 0 && bytes === 0) return t("workshop.backend.downloadSizeUnknown");
    return t(unknownSizeCount > 0 ? "workshop.backend.downloadKnownSizes" : "workshop.backend.downloadAbout")
      .replace("{bytes}", formatBytes(bytes));
  };

  return (
    <>
      {plans.length > 0 ? (
        <div className="mt-3 text-xs leading-5 text-slate-600 dark:text-slate-300">
          <h4 className="font-semibold text-slate-800 dark:text-slate-100">{t("workshop.backend.sourcePlan")}</h4>
          <dl className="mt-1 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1">
            {plans.map(({ category, plan }) => (
              <div key={category} className="contents">
                <dt>{t(`workshop.backend.source.${category}`)}</dt>
                <dd className="break-words">
                  <ul>
                    {plan.map((item) => (
                      <li key={item.source}>
                        {t("workshop.backend.sourcePlanFiles")
                          .replace("{source}", item.source ? downloadSourceName(item.source, t) : t("workshop.backend.sourcePending"))
                          .replace("{count}", String(item.count))
                          .replace("{size}", sizeText(item))}
                      </li>
                    ))}
                  </ul>
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}
      {controls.length > 0 ? (
        <fieldset className="mt-4 grid gap-3 sm:grid-cols-2" disabled={disabled}>
          <legend className="mb-2 text-sm font-semibold text-slate-900 dark:text-slate-50">
            {t("workshop.backend.sources")}
          </legend>
          {controls.map(({ category, choices, selected }) => (
            <label key={category} className="flex min-w-0 flex-col gap-1 text-xs text-slate-600 dark:text-slate-300">
              {t(`workshop.backend.source.${category}`)}
              <select
                className={workstationInputClass}
                value={selected}
                onChange={(event) => onChange({ ...preferences, [category]: event.target.value })}
              >
                <option value="auto">{t("workshop.backend.source.auto")}</option>
                <option value="original">{t("workshop.backend.source.original")}</option>
                {choices.map((source) => <option key={source} value={source}>{downloadSourceName(source, t)}</option>)}
              </select>
            </label>
          ))}
        </fieldset>
      ) : null}
    </>
  );
}
