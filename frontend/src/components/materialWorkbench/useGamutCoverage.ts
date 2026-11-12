import { useCallback, useEffect, useRef, useState } from "react";

import { apiErrorToVisibleMessage } from "../../api/client";
import {
  fetchMaterialGamutContributions,
  fetchMaterialGamutCoverage,
  type MaterialComboSelection,
} from "../../api/materialGamut";
import type {
  MaterialGamutContributionsResponse,
  MaterialGamutCoverageResponse,
} from "../../api/types";
import { tRuntime } from "../../i18n/runtime";
import { workbenchComboKey } from "../../stores/materialWorkbenchStore";

const CHART_MAX_POINTS = 8000;

interface GamutCoverageState {
  coverage: MaterialGamutCoverageResponse | null;
  /** Combination key the shown results belong to. */
  resultKey: string | null;
  coverageLoading: boolean;
  coverageError: string | null;
  contributions: MaterialGamutContributionsResponse | null;
  contributionsLoading: boolean;
  contributionsError: string | null;
}

const INITIAL_STATE: GamutCoverageState = {
  coverage: null,
  resultKey: null,
  coverageLoading: false,
  coverageError: null,
  contributions: null,
  contributionsLoading: false,
  contributionsError: null,
};

/**
 * Run a coverage calculation, then the per-material comparison, cancelling any
 * earlier run so a slow response never overwrites a newer one.
 *
 * 先计算覆盖率，再计算逐耗材贡献；新一次计算会取消旧请求，避免慢响应覆盖新结果。
 */
export function useGamutCoverage() {
  const [state, setState] = useState<GamutCoverageState>(INITIAL_STATE);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const calculate = useCallback(async (combo: MaterialComboSelection) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const key = workbenchComboKey(combo);
    setState((prev) => ({
      ...prev,
      coverageLoading: true,
      coverageError: null,
      contributionsLoading: false,
      contributionsError: null,
    }));

    let coverage: MaterialGamutCoverageResponse;
    try {
      coverage = await fetchMaterialGamutCoverage(combo, {
        maxPoints: CHART_MAX_POINTS,
        signal: controller.signal,
      });
    } catch (error) {
      if (controller.signal.aborted) return;
      setState((prev) => ({
        ...prev,
        coverageLoading: false,
        coverageError: tRuntime("material_gamut_failed", {
          message: apiErrorToVisibleMessage(error),
        }),
      }));
      return;
    }
    if (controller.signal.aborted) return;
    setState({
      ...INITIAL_STATE,
      coverage,
      resultKey: key,
      contributionsLoading: true,
    });

    try {
      const contributions = await fetchMaterialGamutContributions(combo, {
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setState((prev) => ({ ...prev, contributions, contributionsLoading: false }));
    } catch {
      if (controller.signal.aborted) return;
      setState((prev) => ({
        ...prev,
        contributionsLoading: false,
        contributionsError: tRuntime("material_gamut_contrib_failed"),
      }));
    }
  }, []);

  return { ...state, calculate };
}
