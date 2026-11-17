import { create } from "zustand";
import { apiErrorToVisibleMessage } from "../api/client";
import { fetchResourceStatus, type ResourceKind, type ResourceSource, type ResourceStatus } from "../api/resources";
import { tRuntime } from "../i18n/runtime";
import { useCommunityStore } from "./communityStore";

export interface CatalogHealth {
  sourceUrl: string;
  state: "ready" | "cached" | "error";
  fetchedAt?: string | null;
}

interface ResourceState {
  status: ResourceStatus | null;
  loading: boolean;
  error: string | null;
  generation: number;
  catalogHealth: Partial<Record<ResourceKind, CatalogHealth>>;
  observeCatalog: (kind: ResourceKind, health: CatalogHealth) => void;
  sourceChanged: (status: ResourceStatus) => void;
  catalogSource: Record<ResourceKind, ResourceSource>;
  setCatalogSource: (kind: ResourceKind, source: ResourceSource) => void;
  observedContent: Partial<Record<ResourceKind, boolean>>;
  observeLibrary: (kind: ResourceKind, count: number) => void;
  refresh: () => Promise<void>;
}

let statusRequest: Promise<void> | null = null;

export const useResourceStore = create<ResourceState>((set, get) => ({
  status: null,
  loading: false,
  error: null,
  generation: 0,
  catalogHealth: {},
  observeCatalog: (kind, health) => set((state) => ({ catalogHealth: { ...state.catalogHealth, [kind]: health } })),
  sourceChanged: (status) => {
    set((state) => ({ status, generation: state.generation + 1, catalogHealth: {} }));
    useCommunityStore.getState().resetActivity();
  },
  catalogSource: { materials: "cloud", luts: "cloud" },
  setCatalogSource: (kind, source) => set((state) => ({ catalogSource: { ...state.catalogSource, [kind]: source } })),
  observedContent: {},
  observeLibrary: (kind, count) => {
    if (count > 0 && !get().observedContent[kind]) set((state) => ({ observedContent: { ...state.observedContent, [kind]: true } }));
  },
  refresh: () => {
    if (statusRequest) return statusRequest;
    const generation = get().generation;
    set({ loading: true, error: null });
    statusRequest = fetchResourceStatus()
      .then((status) => {
        if (get().generation !== generation) return;
        const previous = get().status?.source_settings;
        const changed = previous && JSON.stringify(previous.urls) !== JSON.stringify(status.source_settings?.urls);
        if (changed) get().sourceChanged(status);
        else set({ status });
      })
      .catch((error: unknown) => {
        if (get().generation !== generation) return;
        set({ error: apiErrorToVisibleMessage(error, tRuntime("resources_status_failed")) });
      })
      .finally(() => { statusRequest = null; set({ loading: false }); });
    return statusRequest;
  },
}));
