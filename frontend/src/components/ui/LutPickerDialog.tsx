import { useResourceActivity } from "../../hooks/useResourceActivity";
import CloseButton from "./CloseButton";
import { useCommunityStore } from "../../stores/communityStore";
import { CommunityFilter, CommunityNotice, ResourceActivityActions } from "./ResourceActivity";
import type { PersonalFilter } from "../../api/community";
import { useI18n } from "../../i18n/context";
import { useFilamentMarket } from "../../hooks/useFilamentMarket";
import { filamentIdentity, filamentMatches } from "../../utils/filamentIdentity";
import { localLutIdentity } from "../../utils/libraryFilamentIdentity";
import { LibraryBrandLogo, LibraryCardIdentity } from "./LibraryDetails";
import { resourceColorMode } from "../../utils/resourcePresentation";
import CalibrationThumbnail from "./CalibrationThumbnail";
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import Button from "./Button";
import type { ResourceSource } from "../../api/resources";
import type { LocalLutVersion } from "../../api/types";
import ResourceCatalogPanel from "../ResourceCatalogPanel";
import ResourceLibraryEmpty from "./ResourceLibraryEmpty";
import TransientBanner from "./TransientBanner";
import { useWidgetStore } from "../../stores/widgetStore";
import type { ResourceSelectionCheck } from "../../stores/converter/resourceSelection";
import {
  cx,
  StatusBanner,
  workstationInputClass,
} from "./panelPrimitives";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface LutPickerOption {
  /** Unique LUT name that flows back to the store. */
  value: string;
  /** Human-readable label shown in the list. */
  label: string;
  brand?: string;
  display?: Record<string, unknown> | null;
  searchTokens?: string[];
  mode?: string;
  /** Color-mode group label, e.g. "4 色 RYBW". */
  group: string;
  localVersion?: LocalLutVersion | null;
}

export interface LutPickerBrand {
  value: string;
  label: string;
  logo?: string;
  display?: Record<string, unknown> | null;
  displayName?: string;
  materialTypes?: string[];
  vendor?: string;
}

interface LutPickerDialogProps {
  open: boolean;
  /** All available brands (manufacturer dropdown options). */
  brands: LutPickerBrand[];
  /** All available LUT options for the currently selected brand. */
  lutOptions: LutPickerOption[];
  catalogOptions?: LutPickerOption[];
  /** Currently selected brand value. */
  selectedBrand: string;
  /** Currently selected LUT name(s) — used to initialise staged state. */
  initialSelectedLuts: string[];
  onBrandChange: (brand: string) => void;
  onConfirm: (lutNames: string[], allowModeChange?: boolean) => void | string | null;
  onCancel: () => void;
  onUploadClick: () => void;
  onRefresh: () => void;
  onCalibrate?: (selected: string[]) => void;
  loading?: boolean;
  lutLoading?: boolean;
  refreshing?: boolean;
  loadError?: string | null;
  uploading?: boolean;
  uploadError?: string | null;
  uploadSuccess?: string | null;
  onDismissUploadSuccess?: () => void;
  onInstalled?: () => void | Promise<unknown>;
  checkSelection?: (values: string[]) => ResourceSelectionCheck;
  labels: {
    title: string;
    searchPlaceholder: string;
    allGroups: string;
    brandLabel: string;
    upload: string;
    refreshTooltip: string;
    noBrandHint: string;
    noMatchHint: string;
    loadingHint: string;
    selectedCount: string;
    deselectAll: string;
    confirm: string;
    cancel: string;
    brandInfo?: string;
    materialType?: string;
    vendor?: string;
  };
}

// ---------------------------------------------------------------------------
// Focus trap
// ---------------------------------------------------------------------------

const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "[href]",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function LutPickerDialog({
  open,
  brands,
  lutOptions,
  catalogOptions,
  selectedBrand,
  initialSelectedLuts,
  onBrandChange,
  onConfirm,
  onCancel,
  onUploadClick,
  onRefresh,
  onCalibrate,
  loading = false,
  lutLoading = false,
  refreshing = false,
  loadError,
  uploading = false,
  uploadError,
  uploadSuccess,
  onDismissUploadSuccess,
  onInstalled,
  checkSelection,
  labels,
}: LutPickerDialogProps) {
  const { t, lang } = useI18n();
  const market = useFilamentMarket();
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);
  // Held in a ref so the open effect can read the latest selection without
  // re-running (and re-focusing) on every parent render.
  const initialSelectedRef = useRef(initialSelectedLuts);
  initialSelectedRef.current = initialSelectedLuts;

  const [staged, setStaged] = useState<string[]>(initialSelectedLuts);
  const [query, setQuery] = useState("");
  const [groupFilter, setGroupFilter] = useState<string>("all");
  const [catalogSource, setCatalogSource] = useState<ResourceSource | null>(null);
  const cloudOpen = catalogSource !== null;
  const [success, setSuccess] = useState<string | null>(null);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const selectionCheck = checkSelection?.(staged) ?? {};
  const returnToLocal = () => {
    setCatalogSource(null);
    window.setTimeout(() => searchRef.current?.focus(), 0);
  };
  const calibrate = () => {
    if (onCalibrate) onCalibrate(staged);
    else { onCancel(); useWidgetStore.getState().setActiveTab("calibration"); }
  };

  // Reset state when dialog opens
  useEffect(() => {
    if (!open) return undefined;

    previouslyFocusedRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;

    setStaged(initialSelectedRef.current);
    setQuery("");
    setGroupFilter("all");
    setCatalogSource(null);
    setSelectionError(null);
    setSuccess(null);

    const timer = window.setTimeout(() => {
      searchRef.current?.focus();
    }, 0);

    return () => {
      window.clearTimeout(timer);
      previouslyFocusedRef.current?.focus();
    };
  }, [open]);

  // Keyboard: Escape → cancel; Tab → trap focus inside dialog
  useEffect(() => {
    if (!cloudOpen) return;
    const timer = window.setTimeout(() => dialogRef.current?.querySelector<HTMLInputElement>('input[type="search"]')?.focus(), 0);
    return () => window.clearTimeout(timer);
  }, [cloudOpen]);

  useEffect(() => {
    if (!open) return undefined;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (document.querySelector("[data-resource-dialog]")) return;
      if (e.key === "Escape") {
        e.preventDefault();
        if (cloudOpen) {
          setCatalogSource(null);
          window.setTimeout(() => searchRef.current?.focus(), 0);
        } else onCancel();
        return;
      }
      if (e.key !== "Tab") return;
      const container = dialogRef.current;
      if (!container) return;
      const focusable = Array.from(
        container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      );
      if (focusable.length === 0) {
        e.preventDefault();
        container.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      } else if (!container.contains(active)) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onCancel, cloudOpen]);

  // Selected brand meta
  const selectedBrandMeta = useMemo(
    () => brands.find((b) => b.value === selectedBrand) ?? null,
    [brands, selectedBrand],
  );

  const [personalFilter, setPersonalFilter] = useState<PersonalFilter>("all");
  const references = useCommunityStore((state) => state.references.luts);
  const myActivity = useCommunityStore((state) => state.mine.luts);
  useResourceActivity("luts", Object.values(references).map((row) => row.resource_id), open);
  useEffect(() => { if (open) void useCommunityStore.getState().loadReferences("luts"); }, [open, lutOptions]);
  const catalogSearchOptions = (query.trim() || personalFilter !== "all") ? catalogOptions : undefined;
  const searchingCatalog = catalogSearchOptions !== undefined;
  const sourceOptions = catalogSearchOptions ?? lutOptions;
  const allGroups = useMemo(() => [...new Set(sourceOptions.map((opt) => opt.group).filter(Boolean))], [sourceOptions]);
  const options = useMemo(() => sourceOptions.map((opt) => {
    const identity = localLutIdentity(opt.brand ?? selectedBrandMeta?.label, opt.label, lang, opt.display, market);
    const searchText = [identity.searchText, opt.label, opt.value, opt.group, ...(opt.searchTokens ?? [])].join(" ");
    return { ...opt, identity, searchText };
  }), [sourceOptions, selectedBrandMeta, lang, market]);
  const visibleOptions = useMemo(() => options.filter((opt) =>
    (groupFilter === "all" || opt.group === groupFilter) && filamentMatches(query, opt.searchText)
      && (personalFilter === "all" || myActivity[references[opt.value]?.resource_id]?.[personalFilter])),
  [options, query, groupFilter, references, myActivity, personalFilter]);

  // Staged set for O(1) lookup
  const stagedSet = useMemo(() => new Set(staged), [staged]);

  // Brand navigation changes only the visible list, not the staged selection.
  useEffect(() => {
    setQuery("");
    setGroupFilter("all");
  }, [selectedBrand]);

  const handleToggle = (value: string) => {
    setSelectionError(null);
    setStaged((prev) => {
      return prev.includes(value)
        ? prev.filter((name) => name !== value)
        : [...prev, value];
    });
  };

  if (!open) return null;

  const lutDisabled = loading || lutLoading || (!selectedBrand && !searchingCatalog);

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  return createPortal(
    <div
      role="presentation"
      className="fixed inset-0 z-[9999] flex items-center justify-center p-3 sm:p-5"
      style={{ background: "var(--surface-scrim)" }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        data-testid="lut-picker-dialog"
        className="flex h-[min(48rem,calc(100vh-3rem))] w-[min(68rem,calc(100vw-1.5rem))] flex-col overflow-hidden rounded-2xl border"
        style={{
          maxHeight: "calc(100vh - 3rem)",
          borderColor: "var(--surface-card-outline)",
          background: "var(--surface-panel-strong)",
        }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* ---- Header ---- */}
        <div className="flex items-center justify-between border-b px-5 py-4" style={{ borderColor: "var(--surface-outline)" }}>
          <h2
            id={titleId}
            className="text-[15px] font-semibold text-slate-900 dark:text-slate-50"
          >
            {labels.title}
          </h2>
          <div className="flex items-center gap-2">
            {cloudOpen && <Button label={t("resources_back_to_picker")} onClick={returnToLocal} />}
            <Button size="icon" label={labels.refreshTooltip} onClick={onRefresh}
              disabled={loading || uploading} loading={refreshing} icon={<span aria-hidden="true">⟳</span>} />
            <CloseButton label={t("common_close")} onClick={onCancel} />
          </div>
        </div>

        {cloudOpen ? <div className="min-h-0 flex-1"><ResourceCatalogPanel kind="luts" initialSource={catalogSource ?? "cloud"} initialPersonalFilter={personalFilter} initialQuery={query} onQueryChange={setQuery} onInstalled={async () => {
          if (onInstalled) await onInstalled();
          else onRefresh();
          setSuccess(t("resources_installed_pick"));
        }} /></div> : <>
        <div className="flex min-h-0 flex-1 flex-col sm:flex-row">
          {/* Brand sidebar */}
          <aside
            data-testid="lut-picker-brand-sidebar"
            className="flex max-h-36 shrink-0 flex-col gap-1 overflow-y-auto overscroll-y-contain border-b p-3 sm:max-h-none sm:w-44 sm:border-b-0 sm:border-r"
            style={{ borderColor: "var(--surface-outline)" }}
          >
            <p className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
              {labels.brandLabel}
            </p>
            <div className="flex flex-col gap-0.5">
              {brands.map((brand) => {
                const isSelected = brand.value === selectedBrand;
                const identity = filamentIdentity(brand.label, "", lang, brand.display, market);
                return (
                  <button
                    key={brand.value}
                    type="button"
                    data-testid={`lut-picker-brand-option-${brand.value}`}
                    onClick={() => {
                      onBrandChange(brand.value);
                      setGroupFilter("all");
                      setQuery("");
                    }}
                    className={cx(
                      "w-full rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors duration-100",
                      "focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--focus-ring)]",
                      isSelected
                        ? "bg-blue-50 font-medium text-blue-700 dark:bg-blue-500/15 dark:text-blue-200"
                        : "text-slate-700 hover:bg-[var(--nav-chip-hover)] dark:text-slate-300",
                    )}
                  >
                    <span className="flex items-center gap-1.5"><LibraryBrandLogo logo={brand.logo ?? identity.logo} /><span className="truncate">{identity.brand}</span></span>
                  </button>
                );
              })}
            </div>

            {/* Upload */}
            <div className="mt-2 flex flex-col gap-2 border-t pt-2" style={{ borderColor: "var(--surface-outline)" }}>
              <Button label={labels.upload} onClick={onUploadClick} loading={uploading} className="w-full" />
              {brands.length > 0 && <Button label={t("resources_calibrate")} onClick={calibrate} disabled={uploading} className="w-full" />}
            </div>
          </aside>

          {/* Main content */}
          <div className="flex min-w-0 flex-1 flex-col">
            {/* Search + group filter bar */}
            <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3" style={{ borderColor: "var(--surface-outline)" }}>
              <input
                ref={searchRef}
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={labels.searchPlaceholder}
                disabled={!selectedBrand && !catalogOptions?.length}
                data-testid="lut-picker-search-input"
                className={cx(workstationInputClass, "!w-auto min-w-[10rem] flex-1 min-h-9 py-1.5 text-sm")}
              />
              <CommunityFilter value={personalFilter} onChange={setPersonalFilter} />
            </div>
            <CommunityNotice kind="luts" ids={Object.values(references).map((row) => row.resource_id)} />
            {/* Group filter tabs */}
            {allGroups.length > 1 && (
              <div
                className="flex gap-1 overflow-x-auto border-b px-4 py-2"
                style={{ borderColor: "var(--surface-outline)" }}
                role="tablist"
                aria-label={labels.allGroups}
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={groupFilter === "all"}
                  onClick={() => setGroupFilter("all")}
                  className={cx(
                    "shrink-0 rounded-lg px-3 py-1 text-xs font-medium transition-colors",
                    groupFilter === "all"
                      ? "bg-blue-50 text-blue-700 dark:bg-blue-500/15 dark:text-blue-200"
                      : "text-slate-600 hover:bg-[var(--nav-chip-hover)] dark:text-slate-400",
                  )}
                >
                  {labels.allGroups}
                </button>
                {allGroups.map((g) => (
                  <button
                    key={g}
                    type="button"
                    role="tab"
                    aria-selected={groupFilter === g}
                    onClick={() => setGroupFilter(g)}
                    className={cx(
                      "shrink-0 rounded-lg px-3 py-1 text-xs font-medium transition-colors",
                      groupFilter === g
                        ? "bg-blue-50 text-blue-700 dark:bg-blue-500/15 dark:text-blue-200"
                        : "text-slate-600 hover:bg-[var(--nav-chip-hover)] dark:text-slate-400",
                    )}
                  >
                    {g}
                  </button>
                ))}
              </div>
            )}

            {/* LUT list */}
            <div className="dock-scrollbar min-h-0 flex-1 overflow-y-auto overscroll-contain p-4">
              {loadError && <StatusBanner tone="error" action={<Button label={t("resources_retry")} onClick={onRefresh} loading={refreshing} />}>{loadError}</StatusBanner>}
              {uploadError && <StatusBanner tone="error">{uploadError}</StatusBanner>}
              <TransientBanner message={uploadSuccess ?? null} onDismiss={onDismissUploadSuccess} />
              <TransientBanner message={success} onDismiss={() => setSuccess(null)} />
              {loading || lutLoading ? (
                <p className="flex min-h-32 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
                  {labels.loadingHint}
                </p>
              ) : brands.length === 0 ? (
                !loadError && <ResourceLibraryEmpty kind="luts" onBrowse={setCatalogSource} onImport={onUploadClick} importing={uploading}
                  onCalibrate={calibrate} />
              ) : !selectedBrand && !searchingCatalog ? (
                <p className="flex min-h-32 items-center justify-center text-center text-sm text-slate-500 dark:text-slate-400">
                  {labels.noBrandHint}
                </p>
              ) : visibleOptions.length === 0 ? (
                <p
                  data-testid="lut-picker-no-match"
                  className="flex min-h-32 items-center justify-center text-sm text-slate-500 dark:text-slate-400"
                >
                  {labels.noMatchHint}
                </p>
              ) : (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {visibleOptions.map((opt) => {
                    const checked = stagedSet.has(opt.value);
                    return (
                      <div key={opt.value} className="relative flex min-w-0">
                      <button
                        type="button"
                        role="checkbox"
                        aria-checked={checked}
                        disabled={lutDisabled}
                        onClick={() => handleToggle(opt.value)}
                        data-testid="lut-picker-option"
                        className={cx(
                          "flex min-w-0 flex-1 items-center gap-3 rounded-[14px] border px-3.5 py-2.5 text-left text-sm transition-all duration-150",
                          "focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]",
                          "disabled:cursor-not-allowed disabled:opacity-45",
                          references[opt.value] && "pr-12",
                          checked
                            ? "border-blue-300/80 bg-blue-50/60 dark:border-blue-400/60 dark:bg-blue-500/10"
                            : "border-slate-200/80 bg-white/60 hover:border-[color:var(--surface-card-outline)] hover:bg-[var(--nav-chip-hover)] dark:border-slate-700/80 dark:bg-slate-900/55",
                        )}
                      >
                        {/* Checkbox indicator */}
                        <span
                          aria-hidden="true"
                          className={cx(
                            "flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-all duration-200",
                            checked
                              ? "border-blue-500 bg-blue-500"
                              : "border-slate-300/80 bg-white dark:border-slate-600/80 dark:bg-slate-800",
                          )}
                        >
                          <span className={cx("h-2.5 w-2.5 rounded-sm", checked ? "bg-white" : "bg-transparent")} />
                        </span>
                        <CalibrationThumbnail kind="luts" mode={opt.mode ?? opt.group} name={opt.label} display={opt.display} size="sm" />
                        <LibraryCardIdentity {...opt.identity}
                          subtitle={[opt.identity.brand, resourceColorMode(opt.group, lang)].filter(Boolean).join(" · ")}
                          localVersion={opt.localVersion}
                          thumbnail={{ kind: "luts", mode: opt.mode ?? opt.group, name: opt.label, display: opt.display }} />
                      </button>
                      {references[opt.value] && <div className="absolute right-2 top-2">
                        <ResourceActivityActions kind="luts" resource={references[opt.value]} favoriteOnly />
                      </div>}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Brand meta summary */}
            {selectedBrandMeta && (selectedBrandMeta.materialTypes?.length || selectedBrandMeta.vendor) && (
              <div className="border-t px-4 py-2.5" style={{ borderColor: "var(--surface-outline)" }}>
                <p className="flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-slate-500 dark:text-slate-400">
                  {selectedBrandMeta.displayName && (
                    <span>
                      {labels.brandInfo ?? "Brand"}: <span className="text-slate-700 dark:text-slate-300">{filamentIdentity(selectedBrandMeta.displayName, "", lang, selectedBrandMeta.display, market).brand}</span>
                    </span>
                  )}
                  {(selectedBrandMeta.materialTypes ?? []).length > 0 && (
                    <span>
                      {labels.materialType ?? "Material"}: <span className="text-slate-700 dark:text-slate-300">{(selectedBrandMeta.materialTypes ?? []).join(", ")}</span>
                    </span>
                  )}
                  {selectedBrandMeta.vendor && (
                    <span>
                      {labels.vendor ?? "Vendor"}: <span className="text-slate-700 dark:text-slate-300">{filamentIdentity(selectedBrandMeta.vendor, "", lang, selectedBrandMeta.display, market).brand}</span>
                    </span>
                  )}
                </p>
              </div>
            )}
          </div>
        </div>

        {/* ---- Footer ---- */}
        <div className="grid gap-3 border-t px-5 py-3" style={{ borderColor: "var(--surface-outline)" }}>
          {(selectionError || selectionCheck.error) && <StatusBanner tone="error">{t(selectionError || selectionCheck.error!)}</StatusBanner>}
          {!selectionCheck.error && selectionCheck.modeChange && <StatusBanner tone="warning">{t("resources_mode_change").replace("{mode}", selectionCheck.modeChange)}</StatusBanner>}
          <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-slate-600 dark:text-slate-400">
            <span aria-live="polite">
              {labels.selectedCount}: <span className="font-semibold text-slate-800 dark:text-slate-200">{staged.length}</span>
            </span>
          </p>
          <div className="flex flex-wrap items-center gap-2">
            {brands.length > 0 && <Button label={t(personalFilter === "saved" ? "community_saved_browse" : "resources_browse_public")} disabled={uploading} onClick={() => setCatalogSource("cloud")} />}
            <Button
              label={labels.deselectAll}
              onClick={() => setStaged([])}
              disabled={staged.length === 0}
              variant="secondary"
              size="sm"
            />
            <Button
              label={selectionCheck.modeChange ? t("resources_confirm_mode").replace("{mode}", selectionCheck.modeChange) : labels.confirm}
              disabled={!!selectionCheck.error || loading || lutLoading || uploading}
              onClick={() => { const error = onConfirm(staged, !!selectionCheck.modeChange); if (error) setSelectionError(error); }}
              size="sm"
              variant="primary"
            />
          </div>
          </div>
        </div>
        </>}
      </div>
    </div>,
    document.body,
  );
}
