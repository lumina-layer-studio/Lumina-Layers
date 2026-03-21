import { create } from "zustand";
import { persist } from "zustand/middleware";
import { saveSettings } from "../api/system";

// ========== State Interface ==========

export interface SettingsState {
  language: "zh" | "en";
  theme: "light" | "dark";
  lastLutName: string;
  lastColorMode: string;
  lastModelingMode: string;
  lastBedLabel: string;
  cropEnabled: boolean;
  lastSlicerId: string;
  enableBlur: boolean;
}

// ========== Actions Interface ==========

export interface SettingsActions {
  setLanguage: (lang: "zh" | "en") => void;
  setTheme: (theme: "light" | "dark") => void;
  setLastLutName: (name: string) => void;
  setLastColorMode: (mode: string) => void;
  setLastModelingMode: (mode: string) => void;
  setLastBedLabel: (label: string) => void;
  setCropEnabled: (enabled: boolean) => void;
  setLastSlicerId: (id: string) => void;
  setEnableBlur: (enabled: boolean) => void;
  syncToBackend: () => Promise<void>;
}

// ========== Default State ==========

export const DEFAULT_SETTINGS: SettingsState = {
  language: "zh",
  theme: "light",
  lastLutName: "",
  lastColorMode: "4-Color",
  lastModelingMode: "high-fidelity",
  lastBedLabel: "256×256 mm",
  cropEnabled: true,
  lastSlicerId: "",
  enableBlur: true,
};

// ========== Store ==========

export const useSettingsStore = create<SettingsState & SettingsActions>()(
  persist(
    (set, get) => ({
      ...DEFAULT_SETTINGS,

      setLanguage: (lang: "zh" | "en") => set({ language: lang }),

      setTheme: (theme: "light" | "dark") => set({ theme }),

      setLastLutName: (name: string) => set({ lastLutName: name }),

      setLastColorMode: (mode: string) => set({ lastColorMode: mode }),

      setLastModelingMode: (mode: string) => set({ lastModelingMode: mode }),

      setLastBedLabel: (label: string) => set({ lastBedLabel: label }),

      setCropEnabled: (enabled: boolean) => set({ cropEnabled: enabled }),

      setLastSlicerId: (id: string) => set({ lastSlicerId: id }),

      setEnableBlur: (enabled: boolean) => set({ enableBlur: enabled }),

      syncToBackend: async () => {
        const state = get();
        try {
          await saveSettings({
            last_lut: state.lastLutName,
            last_modeling_mode: state.lastModelingMode,
            last_color_mode: state.lastColorMode,
            last_slicer: state.lastSlicerId,
            palette_mode: "swatch",
            enable_crop_modal: state.cropEnabled,
          });
        } catch {
          // best-effort sync — settings are already persisted in localStorage
        }
      },
    }),
    {
      name: "lumina-settings",
    }
  )
);
