import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import {
  deleteMaterialDynamicCache,
  fetchMaterialCacheOverview,
  prepareMaterialDynamicCache,
  type MaterialComboSelection,
} from "../../api/materialGamut";
import type { MaterialDynamicCacheOverview } from "../../api/types";
import { useI18n } from "../../i18n/context";
import { tRuntime } from "../../i18n/runtime";
import { workbenchComboKey } from "../../stores/materialWorkbenchStore";
import Button from "../ui/Button";
import { StatusBanner, cardPadClass, groupHeaderClass, wellPadClass } from "../ui/panelPrimitives";
import { formatMegabytes } from "./format";

type OverviewPhase = "checking" | "ready" | "error";

function formatTimestamp(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

/**
 * Status and Prepare/Delete actions for the dynamic-layer cache of one combo.
 * 单个组合动态层数缓存的状态与 预构建/删除 操作。
 */
export default function DynamicLayerCacheCard({ combo }: { combo: MaterialComboSelection }) {
  const { t } = useI18n();
  const comboKey = useMemo(() => workbenchComboKey(combo), [combo]);
  const [phase, setPhase] = useState<OverviewPhase>("checking");
  const [overview, setOverview] = useState<MaterialDynamicCacheOverview | null>(null);
  const [busy, setBusy] = useState<"prepare" | "delete" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const comboRef = useRef(combo);
  const requestVersion = useRef(0);
  useLayoutEffect(() => {
    comboRef.current = combo;
  });
  const hasMaterials = combo.materialDirectoryNames.length > 0;

  useEffect(() => {
    const version = ++requestVersion.current;
    setOverview(null);
    setBusy(null);
    setNotice(null);
    setActionError(null);
    if (!hasMaterials) {
      setOverview(null);
      setPhase("ready");
      return;
    }
    const controller = new AbortController();
    setPhase("checking");
    fetchMaterialCacheOverview(comboRef.current, { signal: controller.signal })
      .then((response) => {
        if (version !== requestVersion.current || controller.signal.aborted) return;
        setOverview(response.dynamic);
        setPhase("ready");
      })
      .catch(() => {
        if (!controller.signal.aborted) setPhase("error");
      });
    return () => {
      controller.abort();
      requestVersion.current += 1;
    };
  }, [comboKey, hasMaterials]);

  const runAction = useCallback(
    async (kind: "prepare" | "delete") => {
      const version = requestVersion.current;
      const selection = comboRef.current;
      setBusy(kind);
      setNotice(null);
      setActionError(null);
      try {
        if (kind === "prepare") {
          const response = await prepareMaterialDynamicCache(selection);
          if (version !== requestVersion.current) return;
          setOverview(response.dynamic);
          setPhase("ready");
          setNotice(
            response.built
              ? tRuntime("material_cache_dynamic_prepared", {
                  seconds: response.elapsed_seconds.toFixed(1),
                })
              : t("material_cache_dynamic_already_prepared"),
          );
        } else {
          const deleted = await deleteMaterialDynamicCache(selection);
          if (version !== requestVersion.current) return;
          setOverview(null);
          setNotice(t(deleted.deleted ? "material_cache_dynamic_deleted" : "material_cache_dynamic_nothing_deleted"));
          setPhase("checking");
          try {
            const refreshed = await fetchMaterialCacheOverview(selection);
            if (version !== requestVersion.current) return;
            setOverview(refreshed.dynamic);
            setPhase("ready");
          } catch {
            if (version === requestVersion.current) setPhase("error");
          }
        }
      } catch {
        if (version === requestVersion.current) setActionError(t("material_cache_dynamic_failed"));
      } finally {
        if (version === requestVersion.current) setBusy(null);
      }
    },
    [t],
  );

  const handleDelete = useCallback(() => {
    if (window.confirm(t("material_cache_dynamic_confirm_delete"))) void runAction("delete");
  }, [runAction, t]);

  const totalLayers = combo.maxLayerCount - combo.minLayerCount + 1;
  const savedLayers = overview?.saved_layer_counts.length ?? 0;
  const statusLabel = (() => {
    if (phase === "checking") return t("material_cache_dynamic_status_checking");
    if (phase === "error") return t("material_cache_dynamic_status_error");
    return t(overview?.is_ready ? "material_cache_dynamic_status_ready" : "material_cache_dynamic_status_missing");
  })();
  const statusTone = phase === "error" ? "error" : overview?.is_ready ? "ok" : "warn";

  return (
    <section data-testid="dynamic-layer-cache-card" className={`${cardPadClass} flex flex-col gap-4`}>
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className={groupHeaderClass}>{t("material_cache_dynamic_title")}</p>
          <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
            {t("material_cache_dynamic_description")}
          </p>
        </div>
        {hasMaterials ? (
          <span
            data-testid="dynamic-layer-cache-status"
            data-tone={statusTone}
            className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${
              statusTone === "ok"
                ? "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300"
                : statusTone === "error"
                  ? "bg-rose-500/12 text-rose-700 dark:text-rose-300"
                  : "bg-amber-500/12 text-amber-700 dark:text-amber-300"
            }`}
          >
            {statusLabel}
          </span>
        ) : null}
      </header>

      {overview ? (
        <dl className={`${wellPadClass} grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs`}>
          <dt className="text-slate-500 dark:text-slate-400">{t("material_cache_dynamic_layers_label")}</dt>
          <dd data-testid="dynamic-layer-cache-layers" className="text-slate-700 dark:text-slate-200">
            {tRuntime("material_cache_dynamic_layers_value", { saved: savedLayers, total: totalLayers })}
          </dd>
          <dt className="text-slate-500 dark:text-slate-400">{t("material_cache_dynamic_catalog_label")}</dt>
          <dd className="text-slate-700 dark:text-slate-200">
            {overview.catalog
              ? tRuntime("material_cache_dynamic_catalog_value", {
                  size: formatMegabytes(overview.catalog.size_bytes),
                  time: formatTimestamp(overview.catalog.modified_at),
                })
              : t("material_cache_dynamic_catalog_missing")}
          </dd>
        </dl>
      ) : null}

      {overview && !overview.is_ready && savedLayers > 0 ? (
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {tRuntime("material_cache_dynamic_partial_hint", { saved: savedLayers })}
        </p>
      ) : null}
      {busy === "prepare" ? (
        <StatusBanner tone="info">{t("material_cache_dynamic_prepare_hint")}</StatusBanner>
      ) : null}
      {notice ? <StatusBanner tone="success">{notice}</StatusBanner> : null}
      {actionError ? <StatusBanner tone="error">{actionError}</StatusBanner> : null}

      <div className="flex flex-wrap gap-2">
        <Button
          label={t(busy === "prepare" ? "material_cache_dynamic_preparing" : "material_cache_dynamic_prepare_button")}
          variant="primary"
          disabled={!hasMaterials || busy !== null || phase === "checking"}
          loading={busy === "prepare"}
          onClick={() => void runAction("prepare")}
        />
        {overview && (overview.catalog || overview.prepared_layer_counts.length > 0) ? (
          <Button
            label={t("material_cache_dynamic_delete_button")}
            variant="secondary"
            disabled={busy !== null || phase !== "ready"}
            loading={busy === "delete"}
            onClick={handleDelete}
          />
        ) : null}
      </div>
    </section>
  );
}
