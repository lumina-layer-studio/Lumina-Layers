import { create } from "zustand";
import type { LutInfo, LutInfoResponse, MergeResponse } from "../api/types";
import { fetchLutInfo, mergeLuts } from "../api/lut";
import { fetchLutList as apiFetchLutList } from "../api/converter";
import { useConverterStore } from "./converterStore";

// ========== Compatibility Filtering ==========

/**
 * 兼容性过滤规则（复刻 on_merge_primary_select）：
 * - 8-Color → 允许 BW, 4-Color, 6-Color
 * - 6-Color → 允许 BW, 4-Color
 * - 排除 Primary 自身和 Merged 模式
 *
 * primaryMode 来自 detect_color_mode() 的短格式: "BW", "4-Color", "6-Color", "8-Color", "Merged"
 * lutList 中的 color_mode 来自 infer_color_mode() 的长格式: "BW (Black & White)", "4-Color", "6-Color (Smart 1296)", "8-Color Max", "Merged"
 */

const ALLOWED_SECONDARY_MODES: Record<string, string[]> = {
  "8-Color": ["BW", "4-Color", "6-Color"],
  "6-Color": ["BW", "4-Color"],
};

/** 检查列表中的长格式 color_mode 是否匹配短格式 allowed mode */
function matchesMode(listColorMode: string, shortMode: string): boolean {
  return listColorMode.startsWith(shortMode);
}

/**
 * 纯函数：根据 Primary 模式过滤可选的 Secondary LUT 列表。
 * 导出供属性测试使用。
 */
export function filterSecondaryOptions(
  lutList: LutInfo[],
  primaryName: string,
  primaryMode: string
): string[] {
  const allowedModes = ALLOWED_SECONDARY_MODES[primaryMode];
  if (!allowedModes) {
    return [];
  }

  return lutList
    .filter((lut) => {
      // 排除 Primary 自身
      if (lut.name === primaryName) return false;
      // 排除 Merged 模式
      if (lut.color_mode === "Merged") return false;
      // 检查是否在允许的模式列表中
      return allowedModes.some((mode) => matchesMode(lut.color_mode, mode));
    })
    .map((lut) => lut.name);
}

// ========== State & Actions Interfaces ==========

export interface LutManagerState {
  lutList: LutInfo[];
  lutListLoading: boolean;
  primaryName: string;
  primaryInfo: LutInfoResponse | null;
  primaryLoading: boolean;
  secondaryNames: string[];
  secondaryInfos: Map<string, LutInfoResponse>;
  filteredSecondaryOptions: string[];
  dedupThreshold: number;
  merging: boolean;
  mergeResult: MergeResponse | null;
  error: string | null;
}

export interface LutManagerActions {
  fetchLutList: () => Promise<void>;
  selectPrimary: (name: string) => Promise<void>;
  setSecondaryNames: (names: string[]) => void;
  setDedupThreshold: (value: number) => void;
  executeMerge: () => Promise<void>;
  clearError: () => void;
}


// ========== Default State ==========

const DEFAULT_STATE: LutManagerState = {
  lutList: [],
  lutListLoading: false,
  primaryName: "",
  primaryInfo: null,
  primaryLoading: false,
  secondaryNames: [],
  secondaryInfos: new Map(),
  filteredSecondaryOptions: [],
  dedupThreshold: 3.0,
  merging: false,
  mergeResult: null,
  error: null,
};

// ========== Store ==========

export const useLutManagerStore = create<LutManagerState & LutManagerActions>(
  (set, get) => ({
    ...DEFAULT_STATE,

    fetchLutList: async () => {
      set({ lutListLoading: true });
      try {
        const response = await apiFetchLutList();
        set({ lutList: response.luts, lutListLoading: false });
      } catch (err) {
        set({
          lutListLoading: false,
          error: err instanceof Error ? err.message : "LUT 列表加载失败",
        });
      }
    },

    selectPrimary: async (name: string) => {
      // 清空相关状态
      set({
        primaryName: name,
        primaryInfo: null,
        secondaryNames: [],
        secondaryInfos: new Map(),
        filteredSecondaryOptions: [],
        mergeResult: null,
        error: null,
      });

      if (!name) return;

      set({ primaryLoading: true });
      try {
        const info = await fetchLutInfo(name);
        const { lutList } = get();
        const filtered = filterSecondaryOptions(lutList, name, info.color_mode);
        set({
          primaryInfo: info,
          filteredSecondaryOptions: filtered,
          primaryLoading: false,
        });
      } catch (err) {
        set({
          primaryLoading: false,
          error: err instanceof Error ? err.message : "获取 LUT 信息失败",
        });
      }
    },

    setSecondaryNames: (names: string[]) => {
      const { secondaryInfos } = get();
      // 获取新增的 name（尚未有 info 的）
      const newNames = names.filter((n) => !secondaryInfos.has(n));

      set({ secondaryNames: names });

      // 异步获取新增 LUT 的 info
      for (const n of newNames) {
        fetchLutInfo(n)
          .then((info) => {
            const current = get().secondaryInfos;
            const updated = new Map(current);
            updated.set(n, info);
            set({ secondaryInfos: updated });
          })
          .catch(() => {
            // 静默处理，info 仅用于显示
          });
      }
    },

    setDedupThreshold: (value: number) => {
      set({ dedupThreshold: value });
    },

    executeMerge: async () => {
      const { primaryName, secondaryNames, dedupThreshold } = get();

      if (!primaryName || secondaryNames.length === 0) {
        set({ error: "请选择 Primary LUT 和至少一个 Secondary LUT" });
        return;
      }

      set({ merging: true, mergeResult: null, error: null });
      try {
        const result = await mergeLuts({
          primary_name: primaryName,
          secondary_names: secondaryNames,
          dedup_threshold: dedupThreshold,
        });
        set({ mergeResult: result, merging: false });

        // 刷新全局 LUT 列表（Converter Tab）和本 Store 的列表
        useConverterStore.getState().fetchLutList();
        get().fetchLutList();
      } catch (err) {
        set({
          merging: false,
          error: err instanceof Error ? err.message : "合并失败",
        });
      }
    },

    clearError: () => set({ error: null }),
  })
);
