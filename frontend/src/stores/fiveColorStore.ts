import { workflowSettings } from "../project/workflowRuntime";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { BaseColorEntry, FiveColorMatchResponse, FiveColorQueryResponse } from "../api/types";
import {
  fetchBaseColors,
  queryFiveColor,
  matchFiveColorByHex,
  generateRecipeSwatch,
} from "../api/fiveColor";
import {
  captureGeneratedArtifactIdentity,
  isGeneratedArtifactIdentityCurrent,
  registerGeneratedArtifactInvalidator,
} from "./generatedArtifactInvalidation";
import { lutErrorToVisibleMessage } from "./lutErrorMessages";

// ========== Collected Recipe ==========

export interface CollectedRecipe {
  id: string;
  selectedIndices: number[];
  resultHex: string;
  baseColorNames: string[];
  baseColorHexes: string[];
  label: string;
}

type SelectionSource = "manual" | "target-match";
type FiveColorResult = FiveColorQueryResponse | FiveColorMatchResponse;
type PersistedFiveColorState = Pick<
  FiveColorState,
  | "lutName"
  | "baseColors"
  | "combinations"
  | "selectedIndices"
  | "manualSelectedIndices"
  | "selectionSource"
  | "collectedRecipes"
  | "swatchBlockSize"
  | "swatchGap"
  | "swatchCols"
  | "swatchStructureMode"
>;

const HEX_COLOR_PATTERN = /^#[0-9A-Fa-f]{6}$/;
const DEFAULT_RECIPE_LENGTH = 5;
const MAX_RECIPE_LENGTH = 6;
let baseColorsRequestSequence = 0;
let queryRequestSequence = 0;
let matchColorRequestSequence = 0;
let swatchRequestSequence = 0;

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function hasBackendValidationPath(error: unknown): boolean {
  const response = isRecord(error) && isRecord(error.response) ? error.response : null;
  const data = isRecord(response?.data) ? response.data : null;
  const detail = data?.detail;
  if (!Array.isArray(detail)) {
    return false;
  }
  return detail.some((item) => {
    const loc = isRecord(item) ? item.loc : null;
    if (!Array.isArray(loc)) {
      return false;
    }
    return loc.some((part) => {
      if (typeof part !== "string") {
        return false;
      }
      return part === "body" || part === "recipes" || part === "selected_indices";
    });
  });
}

function fiveColorErrorMessage(error: unknown, fallbackKey: string): string {
  if (!error || typeof error !== "object") {
    return fallbackKey;
  }
  const response = (error as { response?: unknown }).response;
  if (!response || typeof response !== "object") {
    return fallbackKey;
  }
  return lutErrorToVisibleMessage(error, fallbackKey);
}

function fiveColorSwatchErrorMessage(error: unknown): string {
  const fallbackKey = "five_color_error_generate_swatch_failed";
  if (hasBackendValidationPath(error)) {
    return fallbackKey;
  }
  return fiveColorErrorMessage(error, fallbackKey);
}

function invalidateMatchColorRequests() {
  matchColorRequestSequence += 1;
}

function invalidateQueryRequests() {
  queryRequestSequence += 1;
}

function sameSelection(left: number[], right: number[]) {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function isSupportedRecipeLength(length: number): boolean {
  return length >= DEFAULT_RECIPE_LENGTH && length <= MAX_RECIPE_LENGTH;
}

export function resolveFiveColorRecipeLength(
  combinations: number[][] | null,
  selection: number[] = [],
): number {
  const validCombinations = combinations?.filter(
    (candidate) => isSupportedRecipeLength(candidate.length),
  );
  if (validCombinations?.length) {
    const matchingCombinations = selection.length > 0
      ? validCombinations.filter(
        (candidate) =>
          candidate.length >= selection.length &&
          selection.every((value, index) => candidate[index] === value),
      )
      : validCombinations;
    if (matchingCombinations.length > 0) {
      return Math.max(...matchingCombinations.map((candidate) => candidate.length));
    }
  }
  if (selection.length === MAX_RECIPE_LENGTH) return MAX_RECIPE_LENGTH;
  return DEFAULT_RECIPE_LENGTH;
}

export function hasCompleteFiveColorSelection(
  combinations: number[][] | null,
  selection: number[],
): boolean {
  if (!isSupportedRecipeLength(selection.length)) return false;
  const validCombinations = combinations?.filter(
    (candidate) => isSupportedRecipeLength(candidate.length),
  );
  if (validCombinations?.length) {
    return validCombinations.some(
      (candidate) =>
        candidate.length === selection.length &&
        selection.every((value, index) => candidate[index] === value),
    );
  }
  return selection.length === resolveFiveColorRecipeLength(combinations, selection);
}

// ========== State Interface ==========

export interface FiveColorState {
  lutName: string;
  baseColors: BaseColorEntry[];
  combinations: number[][] | null;
  selectedIndices: number[];
  manualSelectedIndices: number[];
  selectionSource: SelectionSource;
  queryResult: FiveColorResult | null;
  isLoading: boolean;
  error: string | null;
  collectedRecipes: CollectedRecipe[];
  swatchBlockSize: number;
  swatchGap: number;
  swatchCols: number;
  swatchStructureMode: string;
  isGeneratingSwatch: boolean;
  swatchDownloadUrl: string | null;
  swatchPreviewUrl: string | null;
}

// ========== Actions Interface ==========

export interface FiveColorActions {
  loadBaseColors: (lutName: string) => Promise<void>;
  addSelection: (index: number) => void;
  removeLastSelection: () => void;
  clearSelection: () => void;
  reverseSelection: () => void;
  submitQuery: () => Promise<void>;
  matchColorByHex: (targetHex: string) => Promise<void>;
  clearError: () => void;
  addToCollection: () => void;
  removeFromCollection: (id: string) => void;
  clearCollection: () => void;
  setSwatchBlockSize: (size: number) => void;
  setSwatchGap: (gap: number) => void;
  setSwatchCols: (cols: number) => void;
  setSwatchStructureMode: (mode: string) => void;
  generateSwatch: () => Promise<void>;
}

// ========== Default State ==========

const DEFAULT_STATE: FiveColorState = {
  lutName: "",
  baseColors: [],
  combinations: null,
  selectedIndices: [],
  manualSelectedIndices: [],
  selectionSource: "manual",
  queryResult: null,
  isLoading: false,
  error: null,
  collectedRecipes: [],
  swatchBlockSize: 15,
  swatchGap: 2,
  swatchCols: 0,
  swatchStructureMode: "Single-sided",
  isGeneratingSwatch: false,
  swatchDownloadUrl: null,
  swatchPreviewUrl: null,
};

// ========== Store ==========

export const useFiveColorStore = create<FiveColorState & FiveColorActions>()(
  persist(
    (set, get) => ({
      ...DEFAULT_STATE,

      loadBaseColors: async (lutName: string) => {
        const requestId = ++baseColorsRequestSequence;
        invalidateQueryRequests();
        matchColorRequestSequence += 1;
        const hasLutChanged = get().lutName !== lutName;
        set({
          lutName,
          baseColors: [],
          selectedIndices: [],
          manualSelectedIndices: [],
          selectionSource: "manual",
          queryResult: null,
          combinations: null, // 先清空旧组合，强制拉取最新的
          collectedRecipes: hasLutChanged ? [] : get().collectedRecipes,
          swatchDownloadUrl: null,
          swatchPreviewUrl: null,
          isLoading: true,
          error: null,
        });
        try {
          const response = await fetchBaseColors(lutName);
          if (requestId !== baseColorsRequestSequence || get().lutName !== lutName) {
            return;
          }
          set({
            baseColors: response.colors,
            combinations: response.combinations ?? null,
            isLoading: false,
          });
        } catch (error) {
          if (requestId !== baseColorsRequestSequence || get().lutName !== lutName) {
            return;
          }
          set({
            error: fiveColorErrorMessage(error, "five_color_error_load_base_colors_failed"),
            isLoading: false,
          });
        }
      },

      addSelection: (index: number) => {
        const { selectedIndices, selectionSource, combinations } = get();
        const baseSelection = selectionSource === "target-match" ? [] : selectedIndices;
        const recipeLength = resolveFiveColorRecipeLength(combinations, baseSelection);
        if (baseSelection.length < recipeLength) {
          invalidateQueryRequests();
          invalidateMatchColorRequests();
          const nextSelection = [...baseSelection, index];
          set({
            selectedIndices: nextSelection,
            manualSelectedIndices: nextSelection,
            selectionSource: "manual",
            queryResult: null,
            isLoading: false,
          });
        }
      },

      removeLastSelection: () => {
        const { selectedIndices } = get();
        invalidateQueryRequests();
        invalidateMatchColorRequests();
        const nextSelection = selectedIndices.slice(0, -1);
        set({
          selectedIndices: nextSelection,
          manualSelectedIndices: nextSelection,
          selectionSource: "manual",
          queryResult: null,
          isLoading: false,
        });
      },

      clearSelection: () => {
        invalidateQueryRequests();
        invalidateMatchColorRequests();
        set({
          selectedIndices: [],
          manualSelectedIndices: [],
          selectionSource: "manual",
          queryResult: null,
          isLoading: false,
        });
      },

      reverseSelection: () => {
        const { selectedIndices, combinations } = get();
        if (hasCompleteFiveColorSelection(combinations, selectedIndices)) {
          invalidateQueryRequests();
          invalidateMatchColorRequests();
          const nextSelection = [...selectedIndices].reverse();
          set({
            selectedIndices: nextSelection,
            manualSelectedIndices: nextSelection,
            selectionSource: "manual",
            queryResult: null,
            isLoading: false,
          });
        }
      },

      submitQuery: async () => {
        const { selectedIndices, lutName, manualSelectedIndices, selectionSource, combinations } = get();
        if (!hasCompleteFiveColorSelection(combinations, selectedIndices)) return;
        const requestId = ++queryRequestSequence;
        invalidateMatchColorRequests();
        set({
          isLoading: true,
          error: null,
          queryResult: null,
        });
        try {
          const response = await queryFiveColor({
            lut_name: lutName,
            selected_indices: selectedIndices,
          });
          const current = get();
          if (
            requestId !== queryRequestSequence ||
            current.lutName !== lutName ||
            !sameSelection(current.selectedIndices, selectedIndices)
          ) {
            return;
          }
          set({
            queryResult: response,
            selectedIndices:
              !response.found && selectionSource === "target-match"
                ? manualSelectedIndices
                : selectedIndices,
            manualSelectedIndices: response.found
              ? selectedIndices
              : selectionSource === "manual"
                ? selectedIndices
                : get().manualSelectedIndices,
            selectionSource:
              !response.found && selectionSource === "target-match"
                ? "manual"
                : response.found
                  ? "manual"
                  : selectionSource,
            isLoading: false,
          });
        } catch (error) {
          const current = get();
          if (
            requestId !== queryRequestSequence ||
            current.lutName !== lutName ||
            !sameSelection(current.selectedIndices, selectedIndices)
          ) {
            return;
          }
          set({
            selectedIndices:
              selectionSource === "target-match" ? manualSelectedIndices : selectedIndices,
            manualSelectedIndices:
              selectionSource === "manual" ? selectedIndices : manualSelectedIndices,
            selectionSource: selectionSource === "target-match" ? "manual" : selectionSource,
            queryResult: null,
            error: fiveColorErrorMessage(error, "five_color_error_query_failed"),
            isLoading: false,
          });
        }
      },

      matchColorByHex: async (targetHex: string) => {
        const { lutName, selectedIndices, manualSelectedIndices, selectionSource } = get();
        if (!lutName) {
          set({ error: "five_color_error_select_lut_first" });
          return;
        }
        invalidateQueryRequests();
        const requestId = ++matchColorRequestSequence;
        const fallbackSelection =
          selectionSource === "target-match" ? manualSelectedIndices : selectedIndices;
        const normalizedHex = targetHex.trim();
        if (!HEX_COLOR_PATTERN.test(normalizedHex)) {
          set({
            selectedIndices: fallbackSelection,
            manualSelectedIndices: fallbackSelection,
            selectionSource: "manual",
            queryResult: null,
            error: "five_color_error_invalid_hex",
            isLoading: false,
          });
          return;
        }
        set({ isLoading: true, error: null, queryResult: null });
        try {
          const response = await matchFiveColorByHex({
            lut_name: lutName,
            target_hex: normalizedHex,
            neighborhood_radius: 2,
          });
          if (requestId !== matchColorRequestSequence || get().lutName !== lutName) {
            return;
          }
          set({
            selectedIndices: response.found ? response.selected_indices : fallbackSelection,
            manualSelectedIndices: fallbackSelection,
            selectionSource: response.found ? "target-match" : "manual",
            queryResult: response,
            isLoading: false,
          });
        } catch (error) {
          if (requestId !== matchColorRequestSequence || get().lutName !== lutName) {
            return;
          }
          set({
            selectedIndices: fallbackSelection,
            manualSelectedIndices: fallbackSelection,
            selectionSource: "manual",
            queryResult: null,
            error: fiveColorErrorMessage(error, "five_color_error_match_failed"),
            isLoading: false,
          });
        }
      },

      clearError: () => {
        set({ error: null });
      },

      addToCollection: () => {
        const {
          queryResult,
          selectedIndices,
          baseColors,
          lutName,
          collectedRecipes,
        } = get();
        if (!queryResult?.found || !queryResult.result_hex) return;

        const isDuplicate = collectedRecipes.some(
          (r) =>
            r.selectedIndices.join(",") === selectedIndices.join(",") &&
            r.resultHex === queryResult.result_hex,
        );
        if (isDuplicate) return;

        const label = selectedIndices
          .map(
            (idx) => baseColors.find((c) => c.index === idx)?.name ?? `#${idx}`,
          )
          .join(" → ");

        const recipe: CollectedRecipe = {
          id: `${lutName}_${selectedIndices.join("-")}_${Date.now()}`,
          selectedIndices: [...selectedIndices],
          resultHex: queryResult.result_hex,
          baseColorNames: baseColors.map((c) => c.name),
          baseColorHexes: baseColors.map((c) => c.hex),
          label,
        };
        set({
          collectedRecipes: [...collectedRecipes, recipe],
          selectedIndices: [],
          manualSelectedIndices: [],
          selectionSource: "manual",
          queryResult: null,
        });
      },

      removeFromCollection: (id: string) => {
        const { collectedRecipes } = get();
        set({ collectedRecipes: collectedRecipes.filter((r) => r.id !== id) });
      },

      clearCollection: () => {
        set({
          collectedRecipes: [],
          swatchDownloadUrl: null,
          swatchPreviewUrl: null,
        });
      },

      setSwatchBlockSize: (size: number) => {
        set({ swatchBlockSize: Math.max(5, Math.min(50, size)) });
      },

      setSwatchGap: (gap: number) => {
        set({ swatchGap: Math.max(0.5, Math.min(10, gap)) });
      },

      setSwatchCols: (cols: number) => {
        set({ swatchCols: Math.max(0, Math.min(20, Math.round(cols))) });
      },

      setSwatchStructureMode: (mode: string) => {
        set({ swatchStructureMode: mode });
      },

      generateSwatch: async () => {
        const {
          collectedRecipes,
          lutName,
          swatchBlockSize,
          swatchGap,
          swatchCols,
          swatchStructureMode,
        } = get();
        if (collectedRecipes.length === 0) return;
        const settings = workflowSettings("five-color");
        const requestIdentity = captureGeneratedArtifactIdentity(
          settings.deviceProfileId,
          settings.buildPlateId,
        );
        const requestSequence = ++swatchRequestSequence;
        const isCurrentRequest = (): boolean => {
          const latestSettings = workflowSettings("five-color");
          return (
            requestSequence === swatchRequestSequence &&
            isGeneratedArtifactIdentityCurrent(
              requestIdentity,
              latestSettings.deviceProfileId,
              latestSettings.buildPlateId,
            )
          );
        };
        set({
          isGeneratingSwatch: true,
          error: null,
          swatchDownloadUrl: null,
          swatchPreviewUrl: null,
        });
        try {
          const response = await generateRecipeSwatch({
            lut_name: lutName,
            recipes: collectedRecipes.map((r) => ({
              selected_indices: r.selectedIndices,
              result_hex: r.resultHex,
              base_color_names: r.baseColorNames,
              base_color_hexes: r.baseColorHexes,
            })),
            block_size_mm: swatchBlockSize,
            gap_mm: swatchGap,
            cols: swatchCols,
            structure_mode: swatchStructureMode,
            printer_id: settings.printerModel,
            slicer: settings.slicerSoftware,
            nozzle_size: settings.nozzleSize,
            device_profile_id: settings.deviceProfileId,
            build_plate_id: settings.buildPlateId,
            custom_3mf_template_id: settings.custom3mfTemplateId,
          });
          if (!isCurrentRequest()) return;
          set({
            swatchDownloadUrl: response.download_url,
            swatchPreviewUrl: response.preview_url,
            isGeneratingSwatch: false,
          });
        } catch (error) {
          if (!isCurrentRequest()) return;
          set({
            error: fiveColorSwatchErrorMessage(error),
            isGeneratingSwatch: false,
          });
        }
      },
    }),
    {
      name: "five-color-store",
      version: 1,
      migrate: (persistedState) => {
        const state = persistedState as Partial<PersistedFiveColorState>;
        const selectedIndices = state.selectedIndices ?? DEFAULT_STATE.selectedIndices;
        const fallbackManualIndices =
          state.selectionSource === "target-match"
            ? selectedIndices
            : state.manualSelectedIndices ?? selectedIndices;
        if (state.selectionSource !== "target-match") {
          return {
            lutName: state.lutName ?? DEFAULT_STATE.lutName,
            baseColors: state.baseColors ?? DEFAULT_STATE.baseColors,
            combinations: state.combinations ?? DEFAULT_STATE.combinations,
            selectedIndices,
            manualSelectedIndices: fallbackManualIndices,
            selectionSource: state.selectionSource ?? DEFAULT_STATE.selectionSource,
            collectedRecipes: state.collectedRecipes ?? DEFAULT_STATE.collectedRecipes,
            swatchBlockSize: state.swatchBlockSize ?? DEFAULT_STATE.swatchBlockSize,
            swatchGap: state.swatchGap ?? DEFAULT_STATE.swatchGap,
            swatchCols: state.swatchCols ?? DEFAULT_STATE.swatchCols,
            swatchStructureMode: state.swatchStructureMode ?? DEFAULT_STATE.swatchStructureMode,
          };
        }
        return {
          lutName: state.lutName ?? DEFAULT_STATE.lutName,
          baseColors: state.baseColors ?? DEFAULT_STATE.baseColors,
          combinations: state.combinations ?? DEFAULT_STATE.combinations,
          selectedIndices,
          manualSelectedIndices: fallbackManualIndices,
          selectionSource: "manual" as SelectionSource,
          collectedRecipes: state.collectedRecipes ?? DEFAULT_STATE.collectedRecipes,
          swatchBlockSize: state.swatchBlockSize ?? DEFAULT_STATE.swatchBlockSize,
          swatchGap: state.swatchGap ?? DEFAULT_STATE.swatchGap,
          swatchCols: state.swatchCols ?? DEFAULT_STATE.swatchCols,
          swatchStructureMode: state.swatchStructureMode ?? DEFAULT_STATE.swatchStructureMode,
        };
      },
      partialize: (state) => ({
        lutName: state.lutName,
        baseColors: state.baseColors,
        combinations: state.combinations,
        selectedIndices: state.selectedIndices,
        manualSelectedIndices:
          state.selectionSource === "target-match"
            ? state.selectedIndices
            : state.manualSelectedIndices,
        selectionSource: "manual" as SelectionSource,
        collectedRecipes: state.collectedRecipes,
        swatchBlockSize: state.swatchBlockSize,
        swatchGap: state.swatchGap,
        swatchCols: state.swatchCols,
        swatchStructureMode: state.swatchStructureMode,
      }),
    },
  ),
);

registerGeneratedArtifactInvalidator(({ preservePreviews }) => {
  swatchRequestSequence += 1;
  useFiveColorStore.setState({
    isGeneratingSwatch: false,
    swatchDownloadUrl: null,
    ...(preservePreviews ? {} : { swatchPreviewUrl: null }),
  });
});
