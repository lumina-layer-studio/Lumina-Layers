import { create } from "zustand";
import { useWidgetStore } from "./widgetStore";

/** A navigation request, consumed once by the converter's existing picker. */
export const useMaterialGuideStore = create<{ requested: boolean }>(() => ({ requested: false }));

export function requestMaterialTrial(): void {
  useMaterialGuideStore.setState({ requested: true });
  useWidgetStore.getState().setActiveTab("converter");
}

const DISMISSED_KEY = "lumina.material-archive-guide.dismissed.v1";

export function isMaterialGuideDismissed(): boolean {
  try { return localStorage.getItem(DISMISSED_KEY) === "true"; }
  catch { return false; }
}

export function dismissMaterialGuide(): void {
  try { localStorage.setItem(DISMISSED_KEY, "true"); }
  catch { /* The guide still closes when browser storage is unavailable. */ }
}
