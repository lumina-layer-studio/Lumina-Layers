import { useEffect, useMemo, useState } from "react";
import { useShallow } from "zustand/react/shallow";

import { fetchMaterialCacheOverview } from "../../api/materialGamut";
import type { MaterialCacheOverviewResponse } from "../../api/types";
import { useI18n } from "../../i18n/context";
import { tRuntime } from "../../i18n/runtime";
import { useConverterStore } from "../../stores/converter";
import {
  comboFromConverter,
  selectConverterMaterialSnapshot,
  useMaterialWorkbenchStore,
  workbenchComboKey,
} from "../../stores/materialWorkbenchStore";
import { useWidgetStore } from "../../stores/widgetStore";
import type { TabId } from "../../types/widget";
import Button from "../ui/Button";
import { formatCandidateCount } from "./format";

/** Wait for slider drags to settle before asking the backend. */
const OVERVIEW_DEBOUNCE_MS = 350;

type LineTone = "ok" | "warn" | "neutral" | "error";

function describeOverview(overview: MaterialCacheOverviewResponse): { text: string; tone: LineTone } {
  if (overview.dynamic) {
    if (overview.dynamic.is_ready) {
      return { text: tRuntime("basic_material_cache_status_line_dynamic_ready"), tone: "ok" };
    }
    return overview.dynamic.saved_layer_counts.length > 0
      ? { text: tRuntime("basic_material_cache_status_line_dynamic_partial"), tone: "neutral" }
      : { text: tRuntime("basic_material_cache_status_line_dynamic_missing"), tone: "warn" };
  }
  const fixed = overview.fixed;
  if (fixed && fixed.exhaustive_grid_resolutions.length > 0) {
    return { text: tRuntime("basic_material_cache_status_line_fixed_exhaustive"), tone: "ok" };
  }
  if (fixed && fixed.saved_runtime_budgets.length > 0) {
    return {
      text: tRuntime("basic_material_cache_status_line_fixed_smart", {
        budget: formatCandidateCount(fixed.saved_runtime_budgets[0]),
      }),
      tone: "ok",
    };
  }
  return { text: tRuntime("basic_material_cache_status_line_fixed_missing"), tone: "neutral" };
}

const TONE_CLASS: Record<LineTone, string> = {
  ok: "bg-emerald-500",
  warn: "bg-amber-500",
  neutral: "bg-slate-400",
  error: "bg-rose-500",
};

/**
 * Converter-side cache readiness line with links to the Material tabs.
 * 转换器中的缓存就绪状态行，并可跳转到耗材标签页。
 */
export default function MaterialCacheStatusLine() {
  const { t } = useI18n();
  const snapshot = useConverterStore(useShallow(selectConverterMaterialSnapshot));
  const isConverting = useConverterStore((state) => state.isLoading);
  const combo = useMemo(() => comboFromConverter(snapshot), [snapshot]);
  const comboKey = useMemo(() => workbenchComboKey(combo), [combo]);
  const setActiveTab = useWidgetStore((s) => s.setActiveTab);
  const applySelection = useMaterialWorkbenchStore((s) => s.applySelection);
  const [overview, setOverview] = useState<MaterialCacheOverviewResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const hasMaterials = combo.materialDirectoryNames.length > 0;

  useEffect(() => {
    setOverview(null);
    setFailed(false);
    if (!hasMaterials || isConverting) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      fetchMaterialCacheOverview(combo, { signal: controller.signal })
        .then((response) => {
          if (!controller.signal.aborted) setOverview(response);
        })
        .catch(() => {
          if (!controller.signal.aborted) setFailed(true);
        });
    }, OVERVIEW_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
    // comboKey captures every field of combo that matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [comboKey, hasMaterials, isConverting]);

  if (!hasMaterials) return null;

  const status = failed
    ? { text: t("basic_material_cache_status_line_error"), tone: "error" as const }
    : overview
      ? describeOverview(overview)
      : { text: t("basic_material_cache_status_line_checking"), tone: "neutral" as const };

  const openTab = (tab: TabId) => {
    applySelection(combo);
    setActiveTab(tab);
  };

  return (
    <div data-testid="material-cache-status-line" className="flex flex-col gap-2">
      <p className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
        <span aria-hidden className={`h-1.5 w-1.5 shrink-0 rounded-full ${TONE_CLASS[status.tone]}`} />
        <span data-testid="material-cache-status-text">{status.text}</span>
      </p>
      <div className="flex flex-wrap gap-2">
        <Button
          label={t("basic_material_cache_manage_button")}
          variant="secondary"
          size="sm"
          onClick={() => openTab("material-cache")}
        />
        <Button
          label={t("basic_material_gamut_button")}
          variant="secondary"
          size="sm"
          onClick={() => openTab("material-gamut")}
        />
      </div>
    </div>
  );
}
