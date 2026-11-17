import { useSettingsStore } from "../stores/settingsStore";

export function useFilamentMarket(): "CN" | "INTL" {
  return useSettingsStore(({ filamentMarket, language }) =>
    filamentMarket === "auto" ? (language === "zh" ? "CN" : "INTL") : filamentMarket,
  );
}
