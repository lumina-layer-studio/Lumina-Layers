import { useEffect } from "react";
import type { ResourceKind, ResourceSource } from "../../api/resources";
import { useI18n } from "../../i18n/context";
import { useResourceStore } from "../../stores/resourceStore";
import Button from "./Button";
import { StatusBanner } from "./panelPrimitives";

/** Shown only after a successful local library read returns no resources. */
export default function ResourceLibraryEmpty({ kind, onBrowse, onImport, onCalibrate, importing = false }: {
  kind: ResourceKind;
  onBrowse: (source: ResourceSource) => void;
  onImport?: () => void;
  importing?: boolean;
  onCalibrate?: () => void;
}) {
  const { t } = useI18n();
  const { status, loading, error, observedContent, refresh } = useResourceStore();
  const library = status?.[kind];
  const cleared = observedContent[kind] || (library?.seed.state === "ready" && library.seed.reason !== "no_bundled_seed");
  useEffect(() => { void refresh(); }, [refresh]);

  return <section data-testid="resource-library-empty" className="flex min-h-48 flex-col items-center justify-center gap-4 px-2 py-8 text-center">
    <div className="grid max-w-md gap-2">
      <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{t(`resources_${kind}_empty`)}</h3>
      <p className="text-sm text-slate-500 dark:text-slate-400">{t(cleared ? "resources_library_cleared" : `resources_${kind}_intro`)}</p>
    </div>
    {error && <StatusBanner tone="error" action={<Button label={t("resources_retry")} loading={loading} onClick={() => void refresh()} />}>{t("resources_status_failed")}</StatusBanner>}
    {library?.configured === false && <StatusBanner tone="warning">{t("resources_source_not_configured")}</StatusBanner>}
    <div className="flex flex-wrap justify-center gap-2">
      <Button label={t(`resources_browse_${kind}`)} variant="primary" onClick={() => onBrowse("cloud")} disabled={library?.configured === false || importing} />
      {library?.seed.available && <Button label={t("resources_browse_offline")} onClick={() => onBrowse("offline")} disabled={importing} />}
      {onImport && <Button label={t("resources_import")} onClick={onImport} loading={importing} />}
      {onCalibrate && <Button label={t("resources_calibrate")} onClick={onCalibrate} disabled={importing} />}
    </div>
  </section>;
}
