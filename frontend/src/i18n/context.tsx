import { useContext, useMemo } from "react";
import type { ReactNode } from "react";
import { translations } from "./translations";
import { useSettingsStore } from "../stores/settingsStore";
import { I18nContext, type I18nContextValue } from "./value";

export function I18nProvider({ children }: { children: ReactNode }) {
  const language = useSettingsStore((s) => s.language);

  const value = useMemo<I18nContextValue>(
    () => ({
      t: (key: string) => {
        const entry = translations[key];
        if (!entry) return key;
        return entry[language] ?? entry["zh"] ?? key;
      },
      lang: language,
    }),
    [language]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  return useContext(I18nContext);
}
