import { create } from "zustand";
import type {
  LutDetailsCatalogGroup,
  LutDetailsCatalogItem,
  LutDetailsResponse,
} from "../api/types";
import {
  fetchLutDetails as apiFetchLutDetails,
  fetchLutDetailsCatalog as apiFetchLutDetailsCatalog,
} from "../api/lut";
import { lutErrorToVisibleMessage } from "./lutErrorMessages";
import { workflowRuntime } from "../project/workflowRuntime";

export interface FilteredLutDetailsCatalog {
  manufacturers: string[];
  items: LutDetailsCatalogItem[];
  groups: LutDetailsCatalogGroup[];
}

export interface LutDetailsState {
  catalog: LutDetailsCatalogGroup[];
  catalogLoading: boolean;
  selectedManufacturer: string;
  selectedLutName: string;
  loadedLutName: string;
  query: string;
  detail: LutDetailsResponse | null;
  detailLoading: boolean;
  error: string | null;
  errorKind: "catalog" | "detail" | null;
  hasLoadedDetail: boolean;
  isSelectionDirty: boolean;
  canLoadSelectedLut: boolean;
}

export interface LutDetailsActions {
  fetchCatalog: () => Promise<void>;
  loadSelectedLut: () => Promise<void>;
  setQuery: (query: string) => void;
  selectManufacturer: (manufacturer: string) => void;
  selectLut: (name: string) => void;
  clearError: () => void;
}

const DEFAULT_STATE: LutDetailsState = {
  catalog: [],
  catalogLoading: false,
  selectedManufacturer: "",
  selectedLutName: "",
  loadedLutName: "",
  query: "",
  detail: null,
  detailLoading: false,
  error: null,
  errorKind: null,
  hasLoadedDetail: false,
  isSelectionDirty: false,
  canLoadSelectedLut: false,
};

function deriveFlags({
  selectedLutName,
  loadedLutName,
  detail,
  detailLoading,
}: Pick<LutDetailsState, "selectedLutName" | "loadedLutName" | "detail" | "detailLoading">) {
  const hasLoadedDetail = Boolean(detail && loadedLutName);
  const isSelectionDirty = Boolean(loadedLutName && selectedLutName && selectedLutName !== loadedLutName);
  const canLoadSelectedLut = Boolean(selectedLutName) && !detailLoading;
  return {
    hasLoadedDetail,
    isSelectionDirty,
    canLoadSelectedLut,
  };
}

function applyDerivedState(
  current: LutDetailsState,
  patch: Partial<LutDetailsState>,
): Partial<LutDetailsState> {
  const selectedLutName = patch.selectedLutName ?? current.selectedLutName;
  const loadedLutName = patch.loadedLutName ?? current.loadedLutName;
  const detail = patch.detail !== undefined ? patch.detail : current.detail;
  const detailLoading = patch.detailLoading ?? current.detailLoading;
  return {
    ...patch,
    ...deriveFlags({
      selectedLutName,
      loadedLutName,
      detail,
      detailLoading,
    }),
  };
}

function splitQuery(query: string): string[] {
  return query
    .trim()
    .split(/\s+/)
    .map((token) => token.toLowerCase().replace(/[\s\-_&/\\]+/g, ""))
    .filter(Boolean);
}

function itemMatchesQuery(item: LutDetailsCatalogItem, terms: string[]): boolean {
  if (terms.length === 0) {
    return true;
  }

  const tokens = item.search_tokens.map((token) => token.toLowerCase());
  return terms.every((term) => tokens.some((token) => token.startsWith(term)));
}

function itemMatchesManufacturer(item: LutDetailsCatalogItem, manufacturer: string): boolean {
  if (!manufacturer) {
    return true;
  }
  return item.manufacturer === manufacturer;
}

function filterGroups(
  catalog: LutDetailsCatalogGroup[],
  query: string,
  selectedManufacturer: string,
): FilteredLutDetailsCatalog {
  const terms = splitQuery(query);
  const queryMatchedGroups = catalog
    .map((group) => ({
      manufacturer: group.manufacturer,
      items: group.items.filter((item) => itemMatchesQuery(item, terms)),
    }))
    .filter((group) => group.items.length > 0);

  const manufacturers = queryMatchedGroups.map((group) => group.manufacturer);
  const groups = queryMatchedGroups
    .map((group) => ({
      manufacturer: group.manufacturer,
      items: group.items.filter((item) => itemMatchesManufacturer(item, selectedManufacturer)),
    }))
    .filter((group) => group.items.length > 0);
  const items = groups.flatMap((group) => group.items);

  return { manufacturers, items, groups };
}

function findItemByName(
  catalog: LutDetailsCatalogGroup[],
  name: string,
): LutDetailsCatalogItem | null {
  if (!name) {
    return null;
  }

  for (const group of catalog) {
    const item = group.items.find((entry) => entry.name === name);
    if (item) {
      return item;
    }
  }

  return null;
}

function resolveSelection(
  catalog: LutDetailsCatalogGroup[],
  query: string,
  selectedManufacturer: string,
  selectedLutName: string,
): {
  manufacturer: string;
  lutName: string;
  filtered: FilteredLutDetailsCatalog;
} {
  const queryMatched = filterGroups(catalog, query, "");
  const manufacturer =
    selectedManufacturer && queryMatched.manufacturers.includes(selectedManufacturer)
      ? selectedManufacturer
      : "";

  const filtered = filterGroups(catalog, query, manufacturer);
  const lutName =
    selectedLutName && filtered.items.some((item) => item.name === selectedLutName)
      ? selectedLutName
      : filtered.items[0]?.name ?? "";

  return { manufacturer, lutName, filtered };
}

function toErrorMessage(error: unknown, fallbackKey: string): string {
  if (
    error instanceof Error ||
    (error !== null && typeof error === "object" && "response" in error)
  ) {
    return lutErrorToVisibleMessage(error, fallbackKey);
  }
  return fallbackKey;
}

export function filterLutDetailsCatalog(
  catalog: LutDetailsCatalogGroup[],
  query: string,
  selectedManufacturer: string,
): FilteredLutDetailsCatalog {
  return filterGroups(catalog, query, selectedManufacturer);
}

export const useLutDetailsStore = create<LutDetailsState & LutDetailsActions>(
  (set, get) => {
    let catalogRequestId = 0;
    let detailRequestId = 0;
    const loadDetail = async (
      lutName: string,
      target: "selected" | "loaded",
    ) => {
      if (!lutName) {
        set((state) => applyDerivedState(state, { detailLoading: false }));
        return;
      }

      const requestId = ++detailRequestId;
      set((state) => applyDerivedState(state, {
        detailLoading: true,
        error: null,
        errorKind: null,
      }));

      try {
        const detail = await apiFetchLutDetails(lutName);
        const state = get();
        const isStaleRequest = requestId !== detailRequestId;
        const selectionChanged = target === "selected"
          ? state.selectedLutName !== lutName
          : state.loadedLutName !== lutName;
        if (isStaleRequest || selectionChanged) {
          return;
        }
        set({
          detail,
          loadedLutName: lutName,
          detailLoading: false,
          error: null,
          errorKind: null,
          ...deriveFlags({
            selectedLutName: state.selectedLutName,
            loadedLutName: lutName,
            detail,
            detailLoading: false,
          }),
        });
      } catch (error) {
        const state = get();
        const isStaleRequest = requestId !== detailRequestId;
        const selectionChanged = target === "selected"
          ? state.selectedLutName !== lutName
          : state.loadedLutName !== lutName;
        if (isStaleRequest || selectionChanged) {
          return;
        }
        set((current) => applyDerivedState(current, {
          detailLoading: false,
          error: toErrorMessage(error, "lut_details_error_load_detail"),
          errorKind: "detail",
        }));
      }
    };

    const applySelection = (
      nextQuery: string,
      nextManufacturer: string,
      preferredLutName: string,
    ) => {
      const state = get();
      const { manufacturer, lutName } = resolveSelection(
        state.catalog,
        nextQuery,
        nextManufacturer,
        preferredLutName,
      );
      set((current) => applyDerivedState(current, {
        query: nextQuery,
        selectedManufacturer: manufacturer,
        selectedLutName: lutName,
        detailLoading: false,
        error: null,
        errorKind: null,
      }));
    };

    return {
      ...DEFAULT_STATE,

      fetchCatalog: async () => {
        const requestId = ++catalogRequestId;
        set({ catalogLoading: true, error: null });
        try {
          const response = await apiFetchLutDetailsCatalog();
          if (requestId != catalogRequestId) {
            return;
          }
          const current = get();
          const bound = new Set(Object.keys(workflowRuntime("lut-details")?.lutFiles ?? {}));
          const catalog = (response.groups ?? []).map((group) => ({ ...group, items: group.items.filter((item) => !bound.has(item.name)) }));
          for (const group of current.catalog) {
            const items = group.items.filter((item) => bound.has(item.name));
            if (items.length) catalog.push({ ...group, items });
          }
          const previousLoadedItem = findItemByName(current.catalog, current.loadedLutName);
          const { manufacturer, lutName } = resolveSelection(
            catalog,
            current.query,
            current.selectedManufacturer,
            current.selectedLutName,
          );
          set((state) => applyDerivedState(state, {
            catalog,
            catalogLoading: false,
            selectedManufacturer: manufacturer,
            selectedLutName: lutName,
            error: null,
            errorKind: null,
          }));

          const refreshedState = get();
          const loadedItem = refreshedState.loadedLutName
            ? findItemByName(catalog, refreshedState.loadedLutName)
            : null;
          if (refreshedState.loadedLutName && !loadedItem) {
            set((state) => applyDerivedState(state, {
              loadedLutName: "",
              detail: null,
              detailLoading: false,
            }));
            return;
          }
          if (
            refreshedState.detail
            && loadedItem
            && (
              refreshedState.detail.path !== loadedItem.path
              || (loadedItem.revision && loadedItem.revision !== previousLoadedItem?.revision)
            )
          ) {
            void loadDetail(refreshedState.loadedLutName, "loaded");
          }
        } catch (error) {
          if (requestId != catalogRequestId) {
            return;
          }
          set({
            catalogLoading: false,
            error: toErrorMessage(error, "lut_details_error_load_catalog"),
            errorKind: "catalog",
          });
        }
      },

      loadSelectedLut: async () => {
        const { selectedLutName } = get();
        await loadDetail(selectedLutName, "selected");
      },

      setQuery: (query: string) => {
        const current = get();
        applySelection(query, current.selectedManufacturer, current.selectedLutName);
      },

      selectManufacturer: (manufacturer: string) => {
        const current = get();
        applySelection(current.query, manufacturer, current.selectedLutName);
      },

      selectLut: (name: string) => {
        const item = findItemByName(get().catalog, name);
        if (!item) {
          set((state) => applyDerivedState(state, {
            selectedManufacturer: "",
            selectedLutName: "",
            detailLoading: false,
            error: null,
            errorKind: null,
          }));
          return;
        }

        set((state) => applyDerivedState(state, {
          selectedLutName: item.name,
          detailLoading: false,
          error: null,
          errorKind: null,
        }));
      },

      clearError: () => set({ error: null, errorKind: null }),
    };
  },
);
