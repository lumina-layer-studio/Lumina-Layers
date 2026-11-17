import { createContext } from "react";

export interface I18nContextValue {
  t: (key: string) => string;
  lang: "zh" | "en";
}

// Keep provider identity independent of translation and component hot updates.
export const I18nContext = createContext<I18nContextValue>({ t: key => key, lang: "zh" });
