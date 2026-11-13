/**
 * Shared material-combination selection for the Material > Gamut Coverage and
 * Material > Solver Cache tabs, so switching between them keeps the same combo.
 *
 * 耗材 > 色域覆盖 与 耗材 > 求解缓存 两个标签页共享的耗材组合选择，
 * 切换标签页时保持同一组合。
 */
import { create } from "zustand";

import type { MaterialComboSelection } from "../api/materialGamut";
import type { MaterialLayerMode } from "../api/types";
import {
  MATERIAL_DYNAMIC_LAYER_COUNT_MAX,
  MATERIAL_DYNAMIC_LAYER_COUNT_MIN,
  inferDefaultMaterialBackingDirName,
} from "./converter";

/** Converter fields that describe its current material-archive combination. */
export interface ConverterMaterialSnapshot {
  selectedMaterialDirNames: string[];
  materialDynamicLayerCountEnabled: boolean;
  materialLayerCount: number;
  materialMinLayerCount: number;
  materialMaxLayerCount: number;
  materialLayerHeightMm: number;
  materialBackingMaterialDirName: string | null;
}

interface MaterialWorkbenchState {
  materialDirectoryNames: string[];
  layerMode: MaterialLayerMode;
  layerCount: number;
  minLayerCount: number;
  maxLayerCount: number;
  layerHeightMm: number;
  substrate: "white" | "black";
  backingDirName: string | null;
  /** Whether the user (or the converter link) has set a combination yet. */
  initialized: boolean;
}

interface MaterialWorkbenchActions {
  setMaterialDirectoryNames: (names: string[]) => void;
  setLayerMode: (mode: MaterialLayerMode) => void;
  setLayerCount: (count: number) => void;
  setMinLayerCount: (count: number) => void;
  setMaxLayerCount: (count: number) => void;
  setLayerHeightMm: (height: number) => void;
  setSubstrate: (substrate: "white" | "black") => void;
  setBackingDirName: (name: string | null) => void;
  /** Replace the whole combination, e.g. from the converter. 整体替换组合。 */
  applySelection: (selection: MaterialComboSelection) => void;
  /** Seed from the converter only if nothing was chosen yet. 仅在未选择时用转换器初始化。 */
  ensureInitialized: (selection: MaterialComboSelection) => void;
}

export type MaterialWorkbenchStore = MaterialWorkbenchState & MaterialWorkbenchActions;

const clampLayers = (count: number): number =>
  Math.min(
    MATERIAL_DYNAMIC_LAYER_COUNT_MAX,
    Math.max(MATERIAL_DYNAMIC_LAYER_COUNT_MIN, Math.round(count)),
  );

const INITIAL_STATE: MaterialWorkbenchState = {
  materialDirectoryNames: [],
  layerMode: "fixed",
  layerCount: 5,
  minLayerCount: MATERIAL_DYNAMIC_LAYER_COUNT_MIN,
  maxLayerCount: MATERIAL_DYNAMIC_LAYER_COUNT_MAX,
  layerHeightMm: 0.08,
  substrate: "white",
  backingDirName: null,
  initialized: false,
};

/** Pick the material-archive fields from converter state (use with useShallow). */
export function selectConverterMaterialSnapshot(
  state: ConverterMaterialSnapshot,
): ConverterMaterialSnapshot {
  return {
    selectedMaterialDirNames: state.selectedMaterialDirNames,
    materialDynamicLayerCountEnabled: state.materialDynamicLayerCountEnabled,
    materialLayerCount: state.materialLayerCount,
    materialMinLayerCount: state.materialMinLayerCount,
    materialMaxLayerCount: state.materialMaxLayerCount,
    materialLayerHeightMm: state.materialLayerHeightMm,
    materialBackingMaterialDirName: state.materialBackingMaterialDirName,
  };
}

/**
 * Build a combination from the converter's material-archive settings.
 * 由转换器的耗材档案设置构建组合。
 */
export function comboFromConverter(snapshot: ConverterMaterialSnapshot): MaterialComboSelection {
  return {
    materialDirectoryNames: [...snapshot.selectedMaterialDirNames],
    layerMode: snapshot.materialDynamicLayerCountEnabled ? "dynamic" : "fixed",
    layerCount: snapshot.materialLayerCount,
    minLayerCount: snapshot.materialMinLayerCount,
    maxLayerCount: snapshot.materialMaxLayerCount,
    layerHeightMm: snapshot.materialLayerHeightMm,
    // The converter always prints on the white optical substrate.
    substrate: "white",
    backingDirName: resolveBackingDirName(
      snapshot.selectedMaterialDirNames,
      snapshot.materialBackingMaterialDirName,
    ),
  };
}

/** Use the chosen backing if it is selected, else the converter's default rule. */
export function resolveBackingDirName(names: string[], backing: string | null): string | null {
  if (backing && names.includes(backing)) return backing;
  return inferDefaultMaterialBackingDirName(names);
}

/** Current combination with the backing material resolved. 解析基板后的当前组合。 */
export function selectWorkbenchCombo(state: MaterialWorkbenchState): MaterialComboSelection {
  return {
    materialDirectoryNames: state.materialDirectoryNames,
    layerMode: state.layerMode,
    layerCount: state.layerCount,
    minLayerCount: state.minLayerCount,
    maxLayerCount: state.maxLayerCount,
    layerHeightMm: state.layerHeightMm,
    substrate: state.substrate,
    backingDirName: resolveBackingDirName(state.materialDirectoryNames, state.backingDirName),
  };
}

/** Stable string key; results are stale once it changes. 组合的稳定键。 */
export function workbenchComboKey(combo: MaterialComboSelection): string {
  return JSON.stringify(
    combo.layerMode === "dynamic"
      ? [combo.materialDirectoryNames, "dynamic", combo.minLayerCount, combo.maxLayerCount,
        combo.layerHeightMm, combo.substrate, combo.backingDirName]
      : [combo.materialDirectoryNames, "fixed", combo.layerCount, combo.layerHeightMm,
        combo.substrate],
  );
}

export const useMaterialWorkbenchStore = create<MaterialWorkbenchStore>((set, get) => ({
  ...INITIAL_STATE,
  setMaterialDirectoryNames: (names) =>
    set({ materialDirectoryNames: [...names], initialized: true }),
  setLayerMode: (layerMode) => set({ layerMode, initialized: true }),
  setLayerCount: (count) => set({ layerCount: clampLayers(count), initialized: true }),
  setMinLayerCount: (count) => {
    const minLayerCount = clampLayers(count);
    set((state) => ({
      minLayerCount,
      maxLayerCount: Math.max(state.maxLayerCount, minLayerCount),
      initialized: true,
    }));
  },
  setMaxLayerCount: (count) => {
    const maxLayerCount = clampLayers(count);
    set((state) => ({
      maxLayerCount,
      minLayerCount: Math.min(state.minLayerCount, maxLayerCount),
      initialized: true,
    }));
  },
  setLayerHeightMm: (layerHeightMm) => set({ layerHeightMm, initialized: true }),
  setSubstrate: (substrate) => set({ substrate, initialized: true }),
  setBackingDirName: (backingDirName) => set({ backingDirName, initialized: true }),
  applySelection: (selection) =>
    set({
      materialDirectoryNames: [...selection.materialDirectoryNames],
      layerMode: selection.layerMode,
      layerCount: clampLayers(selection.layerCount),
      minLayerCount: clampLayers(Math.min(selection.minLayerCount, selection.maxLayerCount)),
      maxLayerCount: clampLayers(selection.maxLayerCount),
      layerHeightMm: selection.layerHeightMm,
      substrate: selection.substrate,
      backingDirName: selection.backingDirName,
      initialized: true,
    }),
  ensureInitialized: (selection) => {
    if (!get().initialized && selection.materialDirectoryNames.length > 0) {
      get().applySelection(selection);
    }
  },
}));
