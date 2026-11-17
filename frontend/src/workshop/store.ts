import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import type {
  WorkshopDiagnosticSummary,
  WorkshopRecipeSource,
} from "./types";

export type WorkshopManagerView =
  | "installed"
  | "discover"
  | "developer"
  | "storage";

export type WorkshopCatalogStatus =
  | "idle"
  | "loading"
  | "ready"
  | "error";

export type WorkshopManagerRuntimeMode =
  | "desktop-secure"
  | "browser-restricted"
  | "unsafe-development";

export interface ActiveWorkshopModule {
  moduleId: string;
  version: string;
}

export type WorkshopDiagnosticInstallSource =
  | "registry"
  | "github"
  | "local"
  | "seed"
  | "unknown";

export type WorkshopAuditStatus =
  | "official"
  | "verified"
  | "deprecated"
  | "blocked"
  | "unreviewed"
  | "unknown";

export interface ActiveWorkshopRuntimeContext {
  installSource: WorkshopDiagnosticInstallSource;
  auditStatus: WorkshopAuditStatus;
}

export interface WorkshopManagerState {
  view: WorkshopManagerView;
  activeModule: ActiveWorkshopModule | null;
  activeRuntimeContext: ActiveWorkshopRuntimeContext | null;
  catalogStatus: WorkshopCatalogStatus;
  runtimeMode: WorkshopManagerRuntimeMode;
  pendingRecipeSource: WorkshopRecipeSource | null;
  diagnostics: WorkshopDiagnosticSummary | null;
  setView(view: WorkshopManagerView): void;
  openModule(moduleId: string, version: string): void;
  returnHome(): void;
  openRecipe(source: WorkshopRecipeSource): void;
  clearPendingRecipe(): void;
  setCatalogStatus(status: WorkshopCatalogStatus): void;
  setRuntimeMode(mode: WorkshopManagerRuntimeMode): void;
  setActiveRuntimeContext(
    context: ActiveWorkshopRuntimeContext | null,
  ): void;
  setDiagnostics(summary: WorkshopDiagnosticSummary | null): void;
}

type PersistedWorkshopManagerState = Pick<
  WorkshopManagerState,
  "view" | "activeModule"
>;

function isPersistedView(value: unknown): value is WorkshopManagerView {
  return (
    value === "installed" ||
    value === "discover" ||
    value === "developer" ||
    value === "storage"
  );
}

function migratedState(
  persisted: unknown,
): PersistedWorkshopManagerState {
  if (
    typeof persisted !== "object" ||
    persisted === null ||
    Array.isArray(persisted)
  ) {
    return { view: "installed", activeModule: null };
  }
  const state = persisted as Record<string, unknown>;
  const view = isPersistedView(state.view)
    ? state.view
    : "installed";
  const active = state.activeModule;
  if (
    typeof active === "object" &&
    active !== null &&
    !Array.isArray(active) &&
    typeof (active as Record<string, unknown>).moduleId === "string" &&
    typeof (active as Record<string, unknown>).version === "string"
  ) {
    return {
      view,
      activeModule: {
        moduleId: (active as Record<string, string>).moduleId,
        version: (active as Record<string, string>).version,
      },
    };
  }
  return { view, activeModule: null };
}

export const useWorkshopStore = create<WorkshopManagerState>()(
  persist(
    (set) => ({
      view: "installed",
      activeModule: null,
      activeRuntimeContext: null,
      catalogStatus: "idle",
      runtimeMode: "browser-restricted",
      pendingRecipeSource: null,
      diagnostics: null,
      setView: (view) =>
        set({
          view,
          activeModule: null,
          activeRuntimeContext: null,
          catalogStatus:
            view === "discover" ? "loading" : "idle",
          diagnostics: null,
        }),
      openModule: (moduleId, version) =>
        set({
          activeModule: { moduleId, version },
          activeRuntimeContext: null,
          diagnostics: null,
        }),
      returnHome: () =>
        set({
          activeModule: null,
          activeRuntimeContext: null,
          pendingRecipeSource: null,
          diagnostics: null,
        }),
      openRecipe: (source) =>
        set({
          view: "installed",
          activeModule: {
            moduleId: source.moduleId,
            version: source.moduleVersion,
          },
          activeRuntimeContext: null,
          pendingRecipeSource: source,
          diagnostics: null,
        }),
      clearPendingRecipe: () => set({ pendingRecipeSource: null }),
      setCatalogStatus: (catalogStatus) => set({ catalogStatus }),
      setRuntimeMode: (runtimeMode) => set({ runtimeMode }),
      setActiveRuntimeContext: (activeRuntimeContext) =>
        set({ activeRuntimeContext }),
      setDiagnostics: (diagnostics) => set({ diagnostics }),
    }),
    {
      name: "lumina-workshop-shell",
      version: 2,
      storage: createJSONStorage(() => localStorage),
      migrate: (persisted) => migratedState(persisted),
      partialize: (state): PersistedWorkshopManagerState => ({
        view: state.view,
        activeModule:
          state.activeModule === null
            ? null
            : {
                moduleId: state.activeModule.moduleId,
                version: state.activeModule.version,
              },
      }),
    },
  ),
);
