import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import {
  buildMaterialSolverCache,
  buildMaterialSolverRuntime,
  DEFAULT_MATERIAL_SOLVER_RUNTIME_CANDIDATE_BUDGET,
  deleteMaterialSolverCache,
  deleteMaterialSolverRuntime,
  fetchMaterialSolverCacheDetails,
  fetchMaterialSolverCacheStatus,
  fetchMaterialSolverRuntimeDetails,
  fetchMaterialSolverRuntimeStatus,
  MATERIAL_SOLVER_RUNTIME_CANDIDATE_BUDGETS,
  type MaterialSolverCacheKey,
  type MaterialSolverRuntimeCandidateBudget,
} from "../api/materialCache";
import type {
  MaterialSolverCacheDetailsResponse,
  MaterialSolverCacheEntry,
  MaterialSolverRuntimeDetailsResponse,
  MaterialSolverRuntimeEntry,
} from "../api/types";
import { useI18n } from "../i18n/context";
import { tRuntime } from "../i18n/runtime";
import { useSettingsStore } from "../stores/settingsStore";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import Button from "./ui/Button";
import Dropdown from "./ui/Dropdown";
import HelpDot from "./ui/HelpDot";
import { LutColorDistributionCharts } from "./LutDetailsPanel";

interface MaterialSolverCacheStatusCardProps {
  /** User-selected material directory names (ordered as in the picker). */
  materialDirectoryNames: string[];
  /** Number of layers in the solver recipe. */
  layerCount: number;
  /** Layer thickness in millimetres. */
  layerHeightMm: number;
  /** Substrate — currently always ``"white"`` in the converter flow. */
  substrate?: "white" | "black";
}

type Phase = "idle" | "checking" | "cached" | "missing" | "error";

// The exhaustive API uses MITM_MAX_LAYER_COUNT; deeper stacks use smart caches.
const EXHAUSTIVE_LAYER_LIMIT = 10;

interface InternalState {
  phase: Phase;
  entry: MaterialSolverCacheEntry | null;
  errorMessage: string | null;
}

interface RuntimeInternalState {
  phase: Phase;
  entry: MaterialSolverRuntimeEntry | null;
  errorMessage: string | null;
}

const INITIAL_STATE: InternalState = {
  phase: "idle",
  entry: null,
  errorMessage: null,
};

const INITIAL_RUNTIME_STATE: RuntimeInternalState = {
  phase: "idle",
  entry: null,
  errorMessage: null,
};

/**
 * Status card shown next to the material picker: reports whether an exhaustive
 * solver cache exists for the currently-selected palette + layer parameters,
 * and offers build / rebuild / delete actions. Used in material-archive mode.
 *
 * 耗材求解器穷举缓存状态卡片：显示当前调色板 + 层数/层厚组合是否已构建缓存，
 * 并提供构建 / 重建 / 删除操作。用于 material-archive 模式。
 */
export default function MaterialSolverCacheStatusCard({
  materialDirectoryNames,
  layerCount,
  layerHeightMm,
  substrate = "white",
}: MaterialSolverCacheStatusCardProps) {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();
  const supportsExhaustiveBuild = layerCount <= EXHAUSTIVE_LAYER_LIMIT;
  const [state, setState] = useState<InternalState>(INITIAL_STATE);
  const [isBuilding, setIsBuilding] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [chartsExpanded, setChartsExpanded] = useState(false);
  const [chartsLoading, setChartsLoading] = useState(false);
  const [chartsError, setChartsError] = useState<string | null>(null);
  const [chartsData, setChartsData] = useState<MaterialSolverCacheDetailsResponse | null>(null);
  const [runtimeCandidateBudget, setRuntimeCandidateBudget] =
    useState<MaterialSolverRuntimeCandidateBudget>(
      DEFAULT_MATERIAL_SOLVER_RUNTIME_CANDIDATE_BUDGET,
    );
  const [runtimeState, setRuntimeState] =
    useState<RuntimeInternalState>(INITIAL_RUNTIME_STATE);
  const [isRuntimeBuilding, setIsRuntimeBuilding] = useState(false);
  const [isRuntimeDeleting, setIsRuntimeDeleting] = useState(false);
  const [runtimeActionError, setRuntimeActionError] = useState<string | null>(null);
  const [runtimeChartsExpanded, setRuntimeChartsExpanded] = useState(false);
  const [runtimeChartsLoading, setRuntimeChartsLoading] = useState(false);
  const [runtimeChartsError, setRuntimeChartsError] = useState<string | null>(null);
  const [runtimeChartsData, setRuntimeChartsData] =
    useState<MaterialSolverRuntimeDetailsResponse | null>(null);

  const enableSolverCacheGridSelection = useSettingsStore(
    (s) => s.enableSolverCacheGridSelection,
  );
  const solverCacheGridResolution = useSettingsStore(
    (s) => s.solverCacheGridResolution,
  );

  // Only forward the user-selected resolution when the opt-in toggle is on.
  // With the toggle off every request omits ``grid_resolution`` so the
  // backend uses its low (64) default, matching what the user sees in the UI.
  const effectiveGridResolution = enableSolverCacheGridSelection
    ? solverCacheGridResolution
    : undefined;
  const activeGridResolution =
    effectiveGridResolution ?? solverCacheGridResolution;
  const cacheKey = useMemo<MaterialSolverCacheKey>(
    () => ({
      materialDirectoryNames,
      layerCount,
      layerHeightMm,
      substrate,
    }),
    [materialDirectoryNames, layerCount, layerHeightMm, substrate],
  );

  // Track whether component is still mounted / whether the current refresh
  // request is still relevant, to avoid state updates after unmount or stale
  // responses clobbering newer ones.
  const requestIdRef = useRef(0);
  const runtimeRequestIdRef = useRef(0);
  const cacheGenerationRef = useRef(0);
  const runtimeGenerationRef = useRef(0);
  const cacheIdentity = JSON.stringify([cacheKey, effectiveGridResolution]);
  const runtimeIdentity = JSON.stringify([cacheKey, runtimeCandidateBudget]);

  const runtimeBudgetOptions = useMemo(
    () =>
      MATERIAL_SOLVER_RUNTIME_CANDIDATE_BUDGETS.map((budget) => ({
        value: String(budget),
        label: t(`basic_material_runtime_budget_option_${budget}`),
      })),
    [t],
  );

  const refreshStatus = useCallback(async () => {
    if (materialDirectoryNames.length === 0) {
      setState(INITIAL_STATE);
      setActionError(null);
      return;
    }
    const thisRequest = ++requestIdRef.current;
    setState((prev) => ({ ...prev, phase: "checking", errorMessage: null }));
    try {
      const response = await fetchMaterialSolverCacheStatus(cacheKey, {
        gridResolution: effectiveGridResolution,
      });
      if (requestIdRef.current !== thisRequest) return;
      if (response.cached && response.entry) {
        setState({
          phase: "cached",
          entry: response.entry,
          errorMessage: null,
        });
      } else {
        setState({ phase: "missing", entry: null, errorMessage: null });
      }
    } catch {
      if (requestIdRef.current !== thisRequest) return;
      setState({
        phase: "error",
        entry: null,
        errorMessage: tRuntime("basic_material_cache_status_error_detail"),
      });
    }
  }, [materialDirectoryNames.length, cacheKey, effectiveGridResolution]);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  const refreshRuntimeStatus = useCallback(async () => {
    if (materialDirectoryNames.length === 0) {
      setRuntimeState(INITIAL_RUNTIME_STATE);
      setRuntimeActionError(null);
      return;
    }
    const thisRequest = ++runtimeRequestIdRef.current;
    setRuntimeState((prev) => ({
      ...prev,
      phase: "checking",
      errorMessage: null,
    }));
    try {
      const response = await fetchMaterialSolverRuntimeStatus(cacheKey, {
        candidateBudget: runtimeCandidateBudget,
      });
      if (runtimeRequestIdRef.current !== thisRequest) return;
      if (response.cached && response.entry) {
        setRuntimeState({
          phase: "cached",
          entry: response.entry,
          errorMessage: null,
        });
      } else {
        setRuntimeState({ phase: "missing", entry: null, errorMessage: null });
      }
    } catch {
      if (runtimeRequestIdRef.current !== thisRequest) return;
      setRuntimeState({
        phase: "error",
        entry: null,
        errorMessage: tRuntime("basic_material_runtime_status_error_detail"),
      });
    }
  }, [materialDirectoryNames.length, cacheKey, runtimeCandidateBudget]);

  useEffect(() => {
    refreshRuntimeStatus();
  }, [refreshRuntimeStatus]);

  // Whenever the cache key (palette, layer count, layer height, substrate, or
  // selected grid resolution) changes, drop any stale chart payload and
  // collapse the section back to its closed state. The user can re-open it
  // to fetch the new cache's distribution.
  // 当缓存键 (调色板/层数/层厚/基底/分辨率) 变化时清空已加载的图表并收起,
  // 用户可重新展开以拉取新缓存的分布。
  useLayoutEffect(() => {
    cacheGenerationRef.current += 1;
    requestIdRef.current += 1;
    setState(INITIAL_STATE);
    setIsBuilding(false);
    setIsDeleting(false);
    setActionError(null);
    setChartsData(null);
    setChartsError(null);
    setChartsLoading(false);
    setChartsExpanded(false);
    return () => {
      cacheGenerationRef.current += 1;
      requestIdRef.current += 1;
    };
  }, [cacheIdentity]);

  useLayoutEffect(() => {
    runtimeGenerationRef.current += 1;
    runtimeRequestIdRef.current += 1;
    setRuntimeState(INITIAL_RUNTIME_STATE);
    setIsRuntimeBuilding(false);
    setIsRuntimeDeleting(false);
    setRuntimeActionError(null);
    setRuntimeChartsData(null);
    setRuntimeChartsError(null);
    setRuntimeChartsLoading(false);
    setRuntimeChartsExpanded(false);
    return () => {
      runtimeGenerationRef.current += 1;
      runtimeRequestIdRef.current += 1;
    };
  }, [runtimeIdentity]);

  const handleToggleCharts = useCallback(async () => {
    const generation = cacheGenerationRef.current;
    if (chartsExpanded) {
      setChartsExpanded(false);
      return;
    }
    setChartsExpanded(true);
    if (chartsData || chartsLoading) {
      return;
    }
    setChartsError(null);
    setChartsLoading(true);
    try {
      const response = await fetchMaterialSolverCacheDetails(cacheKey, {
        gridResolution: effectiveGridResolution,
        maxPoints: 8000,
      });
      if (generation !== cacheGenerationRef.current) return;
      setChartsData(response);
    } catch {
      if (generation !== cacheGenerationRef.current) return;
      setChartsError(tRuntime("basic_material_cache_charts_failed"));
    } finally {
      if (generation === cacheGenerationRef.current) setChartsLoading(false);
    }
  }, [cacheKey, chartsData, chartsExpanded, chartsLoading, effectiveGridResolution]);

  const handleToggleRuntimeCharts = useCallback(async () => {
    const generation = runtimeGenerationRef.current;
    if (runtimeChartsExpanded) {
      setRuntimeChartsExpanded(false);
      return;
    }
    setRuntimeChartsExpanded(true);
    if (runtimeChartsData || runtimeChartsLoading) {
      return;
    }
    setRuntimeChartsError(null);
    setRuntimeChartsLoading(true);
    try {
      const response = await fetchMaterialSolverRuntimeDetails(cacheKey, {
        candidateBudget: runtimeCandidateBudget,
        maxPoints: 8000,
      });
      if (generation !== runtimeGenerationRef.current) return;
      setRuntimeChartsData(response);
    } catch {
      if (generation !== runtimeGenerationRef.current) return;
      setRuntimeChartsError(tRuntime("basic_material_runtime_charts_failed"));
    } finally {
      if (generation === runtimeGenerationRef.current) setRuntimeChartsLoading(false);
    }
  }, [
    cacheKey,
    runtimeCandidateBudget,
    runtimeChartsData,
    runtimeChartsExpanded,
    runtimeChartsLoading,
  ]);

  const handleBuild = useCallback(async () => {
    if (materialDirectoryNames.length === 0 || !supportsExhaustiveBuild) return;
    const generation = cacheGenerationRef.current;
    setActionError(null);
    setIsBuilding(true);
    try {
      const response = await buildMaterialSolverCache(cacheKey, {
        gridResolution: effectiveGridResolution,
      });
      if (generation !== cacheGenerationRef.current) return;
      setState({
        phase: "cached",
        entry: response.entry,
        errorMessage: null,
      });
    } catch {
      if (generation !== cacheGenerationRef.current) return;
      setActionError(tRuntime("basic_material_cache_build_failed"));
    } finally {
      if (generation === cacheGenerationRef.current) setIsBuilding(false);
    }
  }, [
    cacheKey,
    materialDirectoryNames.length,
    effectiveGridResolution,
    supportsExhaustiveBuild,
  ]);

  const handleDelete = useCallback(async () => {
    if (materialDirectoryNames.length === 0) return;
    const generation = cacheGenerationRef.current;
    const confirmed = window.confirm(t("basic_material_cache_confirm_delete"));
    if (!confirmed) return;
    setActionError(null);
    setIsDeleting(true);
    try {
      await deleteMaterialSolverCache(cacheKey, {
        gridResolution: effectiveGridResolution,
      });
      if (generation !== cacheGenerationRef.current) return;
      setState({ phase: "missing", entry: null, errorMessage: null });
    } catch {
      if (generation !== cacheGenerationRef.current) return;
      setActionError(tRuntime("basic_material_cache_delete_failed"));
    } finally {
      if (generation === cacheGenerationRef.current) setIsDeleting(false);
    }
  }, [cacheKey, materialDirectoryNames.length, effectiveGridResolution, t]);

  const handleRuntimeBudgetChange = useCallback((value: string) => {
    const parsed = Number(value) as MaterialSolverRuntimeCandidateBudget;
    if (
      MATERIAL_SOLVER_RUNTIME_CANDIDATE_BUDGETS.includes(parsed)
    ) {
      setRuntimeCandidateBudget(parsed);
    }
  }, []);

  const handleBuildRuntime = useCallback(async () => {
    if (materialDirectoryNames.length === 0) return;
    const generation = runtimeGenerationRef.current;
    setRuntimeActionError(null);
    setIsRuntimeBuilding(true);
    try {
      const response = await buildMaterialSolverRuntime(cacheKey, {
        candidateBudget: runtimeCandidateBudget,
      });
      if (generation !== runtimeGenerationRef.current) return;
      setRuntimeState({
        phase: "cached",
        entry: response.entry,
        errorMessage: null,
      });
    } catch {
      if (generation !== runtimeGenerationRef.current) return;
      setRuntimeActionError(tRuntime("basic_material_runtime_build_failed"));
    } finally {
      if (generation === runtimeGenerationRef.current) setIsRuntimeBuilding(false);
    }
  }, [cacheKey, materialDirectoryNames.length, runtimeCandidateBudget]);

  const handleDeleteRuntime = useCallback(async () => {
    if (materialDirectoryNames.length === 0) return;
    const generation = runtimeGenerationRef.current;
    const confirmed = window.confirm(t("basic_material_runtime_confirm_delete"));
    if (!confirmed) return;
    setRuntimeActionError(null);
    setIsRuntimeDeleting(true);
    try {
      await deleteMaterialSolverRuntime(cacheKey, {
        candidateBudget: runtimeCandidateBudget,
      });
      if (generation !== runtimeGenerationRef.current) return;
      setRuntimeState({ phase: "missing", entry: null, errorMessage: null });
    } catch {
      if (generation !== runtimeGenerationRef.current) return;
      setRuntimeActionError(tRuntime("basic_material_runtime_delete_failed"));
    } finally {
      if (generation === runtimeGenerationRef.current) setIsRuntimeDeleting(false);
    }
  }, [cacheKey, materialDirectoryNames.length, runtimeCandidateBudget, t]);

  const combinationsEstimate = useMemo(
    () =>
      materialDirectoryNames.length > 0
        ? Math.pow(materialDirectoryNames.length, Math.max(layerCount, 1))
        : 0,
    [materialDirectoryNames.length, layerCount],
  );
  const combinationsLabel = formatCompactNumber(combinationsEstimate);
  const secondsEstimate = estimateBuildSeconds(
    materialDirectoryNames.length,
    layerCount,
  );

  // Compose status pill copy based on the current phase.
  const statusText = (() => {
    if (materialDirectoryNames.length === 0) {
      return t("basic_material_cache_status_idle");
    }
    if (state.phase === "checking") {
      return t("basic_material_cache_status_checking");
    }
    if (state.phase === "cached") return t("basic_material_cache_status_ready");
    if (state.phase === "missing") {
      return t("basic_material_cache_status_missing");
    }
    if (state.phase === "error") return t("basic_material_cache_status_error");
    return "";
  })();

  const statusTone = (() => {
    if (state.phase === "cached") return "ok" as const;
    if (state.phase === "error") return "error" as const;
    if (state.phase === "missing") return "warn" as const;
    return "neutral" as const;
  })();

  const runtimeStatusText = (() => {
    if (materialDirectoryNames.length === 0) {
      return t("basic_material_runtime_status_idle");
    }
    if (runtimeState.phase === "checking") {
      return t("basic_material_runtime_status_checking");
    }
    if (runtimeState.phase === "cached") {
      return t("basic_material_runtime_status_ready");
    }
    if (runtimeState.phase === "missing") {
      return t("basic_material_runtime_status_missing");
    }
    if (runtimeState.phase === "error") {
      return t("basic_material_runtime_status_error");
    }
    return "";
  })();

  const runtimeStatusTone = (() => {
    if (runtimeState.phase === "cached") return "ok" as const;
    if (runtimeState.phase === "error") return "error" as const;
    if (runtimeState.phase === "missing") return "warn" as const;
    return "neutral" as const;
  })();

  return (
    <section
      data-testid="material-solver-cache-status-card"
      className="mt-3 flex flex-col gap-2 rounded-xl border px-3 py-3"
      style={{
        borderColor: "var(--surface-outline)",
        background: "var(--surface-panel-muted)",
      }}
    >
      <header className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-1 min-w-0">
          <h4 className="flex items-center gap-1.5 text-sm font-semibold text-slate-800 dark:text-slate-100">
            <span>{t("basic_material_cache_section_title")}</span>
            <HelpDot
              title={t("basic_material_cache_section_title")}
              description={t("basic_material_cache_section_description")}
            />
          </h4>
        </div>
        <StatusPill tone={statusTone} label={statusText} />
      </header>

      <p
        data-testid="material-solver-cache-active-grid"
        className="text-[11px] leading-snug text-slate-500 dark:text-slate-400"
      >
        {tRuntime("basic_material_cache_active_grid_label", {
          tier: t(
            `settings.solver_cache_density_option_${activeGridResolution}`,
          ),
          grid: activeGridResolution,
        })}
      </p>

      {state.phase === "error" && state.errorMessage ? (
        <p className="text-xs text-rose-500">
          {state.errorMessage}
        </p>
      ) : null}

      {state.phase === "cached" && state.entry ? (
        <CachedEntryDetails entry={state.entry} />
      ) : null}

      {!supportsExhaustiveBuild ? (
        <p className="text-[11px] text-slate-500 dark:text-slate-400">
          {tRuntime("basic_material_cache_layer_limit_hint", { max: EXHAUSTIVE_LAYER_LIMIT })}
        </p>
      ) : state.phase === "missing" && materialDirectoryNames.length > 0 ? (
        <p className="text-[11px] text-slate-500 dark:text-slate-400">
          {t("basic_material_cache_fallback_hint")}
        </p>
      ) : null}

      {isBuilding ? (
        <p className="text-[11px] text-slate-500 dark:text-slate-400">
          {tRuntime("basic_material_cache_building_hint", {
            combinations: combinationsLabel,
            seconds: secondsEstimate,
          })}
        </p>
      ) : null}

      {actionError ? (
        <p className="text-xs text-rose-500">{actionError}</p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        {state.phase === "cached" ? (
          <>
            <Button
              label={t("basic_material_cache_rebuild_button")}
              variant="secondary"
              disabled={materialDirectoryNames.length === 0 || !supportsExhaustiveBuild}
              loading={isBuilding}
              onClick={handleBuild}
              className="px-3 text-xs"
            />
            <Button
              label={t("basic_material_cache_delete_button")}
              variant="secondary"
              disabled={materialDirectoryNames.length === 0}
              loading={isDeleting}
              onClick={handleDelete}
              className="px-3 text-xs"
              tone="danger"
            />
            <Button
              label={t(
                chartsExpanded
                  ? "basic_material_cache_charts_hide_button"
                  : "basic_material_cache_charts_show_button",
              )}
              variant="secondary"
              disabled={materialDirectoryNames.length === 0}
              loading={chartsLoading}
              onClick={handleToggleCharts}
              className="px-3 text-xs"
              data-testid="material-solver-cache-charts-toggle"
            />
          </>
        ) : (
          <Button
            label={
              isBuilding
                ? t("basic_material_cache_building_label")
                : t("basic_material_cache_build_button")
            }
            variant="secondary"
            disabled={materialDirectoryNames.length === 0 || isBuilding || !supportsExhaustiveBuild}
            loading={isBuilding}
            onClick={handleBuild}
            className="px-3 text-xs"
          />
        )}
      </div>

      <div
        data-testid="material-solver-runtime-section"
        className="mt-3 flex flex-col gap-2 border-t pt-3"
        style={{ borderColor: "var(--surface-outline)" }}
      >
        <header className="flex items-start justify-between gap-2">
          <div className="flex min-w-0 flex-col gap-1">
            <h4 className="flex items-center gap-1.5 text-sm font-semibold text-slate-800 dark:text-slate-100">
              <span>{t("basic_material_runtime_section_title")}</span>
              <HelpDot
                title={t("basic_material_runtime_section_title")}
                description={t("basic_material_runtime_section_description")}
              />
            </h4>
          </div>
          <StatusPill
            tone={runtimeStatusTone}
            label={runtimeStatusText}
            testId="material-solver-runtime-status-pill"
          />
        </header>

        <Dropdown
          label={t("basic_material_runtime_budget_label")}
          value={String(runtimeCandidateBudget)}
          options={runtimeBudgetOptions}
          onChange={handleRuntimeBudgetChange}
          disabled={materialDirectoryNames.length === 0 || isRuntimeBuilding}
        />

        {runtimeState.phase === "error" && runtimeState.errorMessage ? (
          <p className="text-xs text-rose-500">
            {runtimeState.errorMessage}
          </p>
        ) : null}

        {runtimeState.phase === "cached" && runtimeState.entry ? (
          <RuntimeEntryDetails entry={runtimeState.entry} />
        ) : null}

        {runtimeState.phase === "missing" && materialDirectoryNames.length > 0 ? (
          <p className="text-[11px] text-slate-500 dark:text-slate-400">
            {t("basic_material_runtime_missing_hint")}
          </p>
        ) : null}

        {isRuntimeBuilding ? (
          <p className="text-[11px] text-slate-500 dark:text-slate-400">
            {tRuntime("basic_material_runtime_building_hint", {
              budget: formatCompactNumber(runtimeCandidateBudget),
            })}
          </p>
        ) : null}

        {runtimeActionError ? (
          <p className="text-xs text-rose-500">{runtimeActionError}</p>
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          {runtimeState.phase === "cached" ? (
            <>
              <Button
                label={t("basic_material_runtime_rebuild_button")}
                variant="secondary"
                disabled={materialDirectoryNames.length === 0}
                loading={isRuntimeBuilding}
                onClick={handleBuildRuntime}
                className="px-3 text-xs"
              />
              <Button
                label={t("basic_material_runtime_delete_button")}
                variant="secondary"
                disabled={materialDirectoryNames.length === 0}
                loading={isRuntimeDeleting}
                onClick={handleDeleteRuntime}
                className="px-3 text-xs"
                tone="danger"
              />
              <Button
                label={t(
                  runtimeChartsExpanded
                    ? "basic_material_runtime_charts_hide_button"
                    : "basic_material_runtime_charts_show_button",
                )}
                variant="secondary"
                disabled={materialDirectoryNames.length === 0}
                loading={runtimeChartsLoading}
                onClick={handleToggleRuntimeCharts}
                className="px-3 text-xs"
                data-testid="material-solver-runtime-charts-toggle"
              />
            </>
          ) : (
            <Button
              label={
                isRuntimeBuilding
                  ? t("basic_material_runtime_building_label")
                  : t("basic_material_runtime_build_button")
              }
              variant="secondary"
              disabled={materialDirectoryNames.length === 0 || isRuntimeBuilding}
              loading={isRuntimeBuilding}
              onClick={handleBuildRuntime}
              className="px-3 text-xs"
            />
          )}
        </div>

        {runtimeChartsExpanded && runtimeState.phase === "cached" ? (
          <div
            data-testid="material-solver-runtime-charts-region"
            className="mt-2 flex flex-col gap-3"
          >
            {runtimeChartsError ? (
              <p className="text-xs text-rose-500">{runtimeChartsError}</p>
            ) : runtimeChartsLoading ? (
              <p className="text-[11px] text-slate-500 dark:text-slate-400">
                {t("basic_material_runtime_charts_loading")}
              </p>
            ) : runtimeChartsData ? (
              <LutColorDistributionCharts
                source={{
                  lab_points: runtimeChartsData.lab_points,
                  lab_points_3d: runtimeChartsData.lab_points_3d,
                  lab_hull: runtimeChartsData.lab_hull,
                  rgb_points: runtimeChartsData.rgb_points,
                  coverage_stats: runtimeChartsData.coverage_stats,
                }}
                workspaceMode={workspace.mode}
              />
            ) : null}
          </div>
        ) : null}
      </div>

      {chartsExpanded && state.phase === "cached" ? (
        <div
          data-testid="material-solver-cache-charts-region"
          className="mt-3 flex flex-col gap-3"
        >
          {chartsError ? (
            <p className="text-xs text-rose-500">{chartsError}</p>
          ) : chartsLoading ? (
            <p className="text-[11px] text-slate-500 dark:text-slate-400">
              {t("basic_material_cache_charts_loading")}
            </p>
          ) : chartsData ? (
            <LutColorDistributionCharts
              source={{
                lab_points: chartsData.lab_points,
                lab_points_3d: chartsData.lab_points_3d,
                lab_hull: chartsData.lab_hull,
                rgb_points: chartsData.rgb_points,
                coverage_stats: chartsData.coverage_stats,
              }}
              workspaceMode={workspace.mode}
            />
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

interface CachedEntryDetailsProps {
  entry: MaterialSolverCacheEntry;
}

function CachedEntryDetails({ entry }: CachedEntryDetailsProps) {
  const { t } = useI18n();
  const items: Array<{ label: string; value: string }> = [];
  if (entry.built_at) {
    items.push({
      label: t("basic_material_cache_built_at_label"),
      value: formatTimestamp(entry.built_at),
    });
  }
  items.push({
    label: t("basic_material_cache_size_label"),
    value: tRuntime("basic_material_cache_units_mb", {
      mb: (entry.cache_file_size_bytes / (1024 * 1024)).toFixed(2),
    }),
  });
  items.push({
    label: t("basic_material_cache_coverage_label"),
    value: `${entry.valid_cell_count.toLocaleString()} / ${entry.total_cell_count.toLocaleString()}`,
  });
  items.push({
    label: t("basic_material_cache_mean_delta_e_label"),
    value: entry.mean_delta_e.toFixed(2),
  });
  items.push({
    label: t("basic_material_cache_max_delta_e_label"),
    value: entry.max_delta_e.toFixed(2),
  });
  items.push({
    label: t("basic_material_cache_build_time_label"),
    value: tRuntime("basic_material_cache_units_seconds", {
      seconds: entry.build_time_seconds.toFixed(1),
    }),
  });
  return (
    <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-slate-600 dark:text-slate-300">
      {items.map((item) => (
        <div key={item.label} className="flex items-baseline justify-between gap-2">
          <dt className="text-slate-500 dark:text-slate-400">{item.label}</dt>
          <dd className="font-medium tabular-nums">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

interface RuntimeEntryDetailsProps {
  entry: MaterialSolverRuntimeEntry;
}

function RuntimeEntryDetails({ entry }: RuntimeEntryDetailsProps) {
  const { t } = useI18n();
  const items: Array<{ label: string; value: string }> = [];
  if (entry.built_at) {
    items.push({
      label: t("basic_material_cache_built_at_label"),
      value: formatTimestamp(entry.built_at),
    });
  }
  items.push({
    label: t("basic_material_cache_size_label"),
    value: tRuntime("basic_material_cache_units_mb", {
      mb: (entry.cache_file_size_bytes / (1024 * 1024)).toFixed(2),
    }),
  });
  items.push({
    label: t("basic_material_runtime_candidates_label"),
    value: formatCompactNumber(entry.candidate_count),
  });
  items.push({
    label: t("basic_material_runtime_budget_label"),
    value: formatCompactNumber(entry.candidate_budget),
  });
  items.push({
    label: t("basic_material_runtime_inverse_label"),
    value: entry.inverse_refinement_enabled
      ? t("basic_material_runtime_enabled")
      : t("basic_material_runtime_disabled"),
  });
  return (
    <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-slate-600 dark:text-slate-300">
      {items.map((item) => (
        <div key={item.label} className="flex items-baseline justify-between gap-2">
          <dt className="text-slate-500 dark:text-slate-400">{item.label}</dt>
          <dd className="font-medium tabular-nums">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

interface StatusPillProps {
  tone: "ok" | "warn" | "error" | "neutral";
  label: string;
  testId?: string;
}

function StatusPill({
  tone,
  label,
  testId = "material-solver-cache-status-pill",
}: StatusPillProps) {
  const toneClass = {
    ok: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
    warn: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
    error: "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
    neutral: "bg-slate-200 text-slate-600 dark:bg-slate-700/50 dark:text-slate-300",
  }[tone];
  return (
    <span
      data-testid={testId}
      data-tone={tone}
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold flex-none ${toneClass}`}
    >
      {label}
    </span>
  );
}

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function formatCompactNumber(value: number): string {
  if (value <= 0) return "0";
  if (value >= 1_000_000_000) {
    return `${(value / 1_000_000_000).toFixed(1)}B`;
  }
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}M`;
  }
  if (value >= 1_000) {
    return `${(value / 1_000).toFixed(1)}K`;
  }
  return value.toLocaleString();
}

function estimateBuildSeconds(
  numMaterials: number,
  layerCount: number,
): string {
  // Crude estimate: combinations × ~40 ns per combo (MITM decomposition).
  // Enough to prepare the user for order-of-magnitude wait times.
  if (numMaterials <= 0) return "0";
  const combinations = Math.pow(numMaterials, Math.max(layerCount, 1));
  const seconds = (combinations * 40) / 1_000_000_000;
  if (seconds < 1) return "<1";
  if (seconds < 60) return seconds.toFixed(0);
  if (seconds < 600) {
    return `${(seconds / 60).toFixed(1)}m`;
  }
  return `${Math.round(seconds / 60)}m`;
}
