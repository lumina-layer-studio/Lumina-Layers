import { useResourceActivity } from "../../hooks/useResourceActivity";
import CloseButton from "./CloseButton";
import { useCommunityStore } from "../../stores/communityStore";
import { CommunityNotice, ResourceActivityActions } from "./ResourceActivity";
import { CommunityAccountDialog } from "../CommunityAccount";
import DisclosureChevron from "./DisclosureChevron";
import {
  MagnifyingGlassIcon,
  StarIcon as StarOutlineIcon,
  XMarkIcon,
} from "@heroicons/react/24/outline";
import { StarIcon } from "@heroicons/react/24/solid";
import {
  useEffect,
  useId,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import type { Ref } from "react";
import { createPortal } from "react-dom";

import type { SavedMaterialLibraryItem } from "../../api/types";
import { useI18n } from "../../i18n/context";
import { useFilamentMarket } from "../../hooks/useFilamentMarket";
import { savedMaterialIdentity } from "../../utils/libraryFilamentIdentity";
import { LibraryBrandLogo, LibraryCardIdentity } from "./LibraryDetails";
import CalibrationThumbnail from "./CalibrationThumbnail";
import {
  favoriteKeyForMaterial,
  loadMaterialProfileFavorites,
  saveMaterialProfileFavorites,
} from "../../utils/materialPickerPreferences";
import Button from "./Button";
import Dropdown from "./Dropdown";
import type { ResourceSource } from "../../api/resources";
import ResourceCatalogPanel from "../ResourceCatalogPanel";
import ResourceLibraryEmpty from "./ResourceLibraryEmpty";
import TransientBanner from "./TransientBanner";
import { useWidgetStore } from "../../stores/widgetStore";
import {
  buildBrandOptions,
  buildMaterialProductGroups,
  filterMaterialGroups,
  resolvedMaterialType,
  summarizeSelectedMaterialTypes,
  type MaterialPickerSort,
  type MaterialProductGroup,
  type MaterialTypeFilter,
} from "./materialPickerModel";
import {
  cx,
  StatusBanner,
  workstationInputClass,
} from "./panelPrimitives";

interface MaterialPickerDialogProps {
  open: boolean;
  materials: SavedMaterialLibraryItem[];
  loading: boolean;
  loadError?: boolean;
  initialSelected: string[];
  onConfirm: (selected: string[]) => void | string | null;
  onCancel: () => void;
  onRetry?: () => void;
  onOpen?: () => void;
  onImport?: () => void;
  onCalibrate?: (selected: string[]) => void;
  operationError?: string | null;
  initialQuery?: string;
  trial?: boolean;
  previewOnConfirm?: boolean;
  /** Lets a caller (the beginner tour) press Done on the user's behalf. 允许调用方（新手引导）代为点击「完成」。 */
  ref?: Ref<MaterialPickerDialogHandle>;
}

export interface MaterialPickerDialogHandle {
  /** Same as clicking Done, including the mixed-type confirmation. 等同点击「完成」，含混合类型确认。 */
  done: (onConfirmed?: () => void) => void;
}

const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "[href]",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

const materialPickerCardClass =
  "rounded-[22px] border px-3.5 py-3 transition-all duration-200";

const materialPickerIdleCardClass =
  "border-slate-200/80 bg-white/60 shadow-[var(--shadow-control)] " +
  "dark:border-slate-700/80 dark:bg-slate-900/55";

const materialPickerSelectedCardClass =
  "border-blue-300/80 bg-blue-50/50 " +
  "drop-shadow-[0_1px_2px_var(--focus-ring)] " +
  "dark:border-blue-400/60 dark:bg-blue-500/10";

function formatMessage(
  template: string,
  params: Record<string, string | number>,
): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => {
    const value = params[key];
    return value === undefined ? `{${key}}` : String(value);
  });
}

function clampRgb(value: number | undefined): number {
  return Math.max(0, Math.min(255, Math.round(value ?? 0)));
}

function materialSwatchColor(item: SavedMaterialLibraryItem): string {
  const [red, green, blue] = item.estimated_rgb;
  return `rgb(${clampRgb(red)} ${clampRgb(green)} ${clampRgb(blue)})`;
}

function profilesForDisplay(
  group: MaterialProductGroup,
): SavedMaterialLibraryItem[] {
  return group.displayProfiles ?? group.profiles;
}

function validLayerHeightMm(
  value: number | null | undefined,
): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? value
    : null;
}

function formatLayerHeightMm(
  value: number | null | undefined,
): string | null {
  const valid = validLayerHeightMm(value);
  return valid === null ? null : `${valid.toFixed(2)} mm`;
}

function formatLayerHeightSummary(
  profiles: SavedMaterialLibraryItem[],
): string | null {
  const heights = Array.from(
    new Set(
      profiles
        .map((profile) => validLayerHeightMm(profile.layer_height_mm))
        .filter((value): value is number => value !== null),
    ),
  ).sort((left, right) => left - right);
  if (heights.length === 0) return null;
  return `${heights.map((height) => height.toFixed(2)).join(" / ")} mm`;
}

/**
 * Material profile picker with type, brand, favorites, and contributor filters.
 * 支持类型、品牌、收藏和作者筛选的耗材档案选择弹窗。
 */
export default function MaterialPickerDialog({
  open,
  materials,
  loading,
  loadError = false,
  initialSelected,
  onConfirm,
  onCancel,
  onRetry,
  onOpen,
  onImport,
  onCalibrate,
  operationError,
  initialQuery = "",
  trial = false,
  previewOnConfirm = false,
  ref,
}: MaterialPickerDialogProps) {
  const { t, lang } = useI18n();
  const market = useFilamentMarket();
  const identities = useMemo(() => new Map(materials.map((item) =>
    [item.directory_name, savedMaterialIdentity(item, lang, market)])), [materials, lang, market]);
  const titleId = useId();
  const descriptionId = useId();
  const confirmTitleId = useId();
  const confirmDescriptionId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const confirmDialogRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const confirmBackRef = useRef<HTMLButtonElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);
  const afterConfirmRef = useRef<(() => void) | undefined>(undefined);

  const [staged, setStaged] = useState<string[]>(initialSelected);
  const initialSelectedRef = useRef(initialSelected);
  initialSelectedRef.current = initialSelected;
  const initialQueryRef = useRef(initialQuery);
  initialQueryRef.current = initialQuery;
  const previousInitialSelected = useRef(initialSelected);
  useEffect(() => {
    const previous = previousInitialSelected.current;
    previousInitialSelected.current = initialSelected;
    if (!open) return;
    // A directory migration may finish after opening. Follow it only while
    // the user has not changed the selection; catalog refreshes keep drafts.
    setStaged((current) => current.length === previous.length && current.every((name, index) => name === previous[index])
      ? initialSelected : current);
  }, [initialSelected, open]);
  const onOpenRef = useRef(onOpen);
  onOpenRef.current = onOpen;
  const [catalogSource, setCatalogSource] = useState<ResourceSource | null>(null);
  const cloudOpen = catalogSource !== null;
  const [resourceSuccess, setResourceSuccess] = useState<string | null>(null);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const returnToLocal = () => {
    setCatalogSource(null);
    window.setTimeout(() => searchInputRef.current?.focus(), 0);
  };
  const importResources = onImport ?? (() => { onCancel(); useWidgetStore.getState().setActiveTab("material-library"); });
  const calibrate = () => {
    if (onCalibrate) onCalibrate(staged);
    else { onCancel(); useWidgetStore.getState().setActiveTab("gradient-card-generate"); }
  };
  const materialByDirectory = useMemo(
    () => new Map(materials.map((item) => [item.directory_name, item])),
    [materials],
  );
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<MaterialTypeFilter | "local">("all");
  const [brandKey, setBrandKey] = useState("all");
  const [sort, setSort] = useState<MaterialPickerSort>("name");
  const [expandedGroupKeys, setExpandedGroupKeys] = useState<Set<string>>(
    () => new Set(),
  );
  const [localPins, setLocalPins] = useState<Set<string>>(
    () => new Set(),
  );
  const [accountOpen, setAccountOpen] = useState(false);
  const connection = useCommunityStore((state) => state.connection);
  useEffect(() => {
    if (connection?.state === "connected" && accountOpen) { setAccountOpen(false); setTypeFilter("favorites"); }
    else if (connection && connection.state !== "connected" && typeFilter === "favorites") setTypeFilter("all");
  }, [connection, accountOpen, typeFilter]);
  const references = useCommunityStore((state) => state.references.materials);
  const myActivity = useCommunityStore((state) => state.mine.materials);
  const favoriteKeys = useMemo(() => typeFilter === "local" ? localPins : new Set(materials
    .filter((profile) => myActivity[references[profile.directory_name]?.resource_id]?.saved)
    .map(favoriteKeyForMaterial)), [materials, references, myActivity, typeFilter, localPins]);
  useResourceActivity("materials", Object.values(references).map((row) => row.resource_id), open);
  useEffect(() => { if (open) void useCommunityStore.getState().loadReferences("materials"); }, [open, materials]);
  const [showMixedConfirmation, setShowMixedConfirmation] = useState(false);
  const [selectionEffectDirectory, setSelectionEffectDirectory] =
    useState<string | null>(null);

  useEffect(() => {
    if (!open) return undefined;

    previouslyFocusedRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    setStaged(initialSelectedRef.current);
    onOpenRef.current?.();
    setCatalogSource(null);
    setSelectionError(null);
    setResourceSuccess(null);
    setQuery(initialQueryRef.current);
    setTypeFilter("all");
    setBrandKey("all");
    setSort("name");
    setExpandedGroupKeys(new Set());
    setLocalPins(loadMaterialProfileFavorites());
    afterConfirmRef.current = undefined;
    setShowMixedConfirmation(false);
    setSelectionEffectDirectory(null);

    const focusTimer = window.setTimeout(() => {
      searchInputRef.current?.focus();
    }, 0);

    return () => {
      window.clearTimeout(focusTimer);
      previouslyFocusedRef.current?.focus();
    };
  }, [open]);

  useEffect(() => {
    if (!cloudOpen) return;
    const timer = window.setTimeout(() => dialogRef.current?.querySelector<HTMLInputElement>('input[type="search"]')?.focus(), 0);
    return () => window.clearTimeout(timer);
  }, [cloudOpen]);

  useEffect(() => {
    if (!showMixedConfirmation) return undefined;
    const focusTimer = window.setTimeout(() => {
      confirmBackRef.current?.focus();
    }, 0);
    return () => window.clearTimeout(focusTimer);
  }, [showMixedConfirmation]);

  useEffect(() => {
    if (!open) return undefined;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (document.querySelector("[data-resource-dialog]")) return;
      if (event.key === "Escape") {
        event.preventDefault();
        if (showMixedConfirmation) {
          afterConfirmRef.current = undefined;
          setShowMixedConfirmation(false);
        } else if (cloudOpen) {
          setCatalogSource(null);
          window.setTimeout(() => searchInputRef.current?.focus(), 0);
        } else {
          onCancel();
        }
        return;
      }
      if (event.key !== "Tab") return;

      const activeContainer = showMixedConfirmation
        ? confirmDialogRef.current
        : dialogRef.current;
      if (!activeContainer) return;
      const focusable = Array.from(
        activeContainer.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      );
      if (focusable.length === 0) {
        event.preventDefault();
        activeContainer.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const activeElement = document.activeElement;
      if (event.shiftKey && activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (!activeContainer.contains(activeElement)) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onCancel, open, showMixedConfirmation, cloudOpen]);

  const stagedSet = useMemo(() => new Set(staged), [staged]);
  const groups = useMemo(
    () => buildMaterialProductGroups(materials),
    [materials],
  );
  const brandOptions = useMemo(
    () =>
      buildBrandOptions(materials, {
        all: t("basic_material_picker_all_brands"),
        unassigned: t("basic_material_picker_brand_unassigned"),
      }, identities),
    [materials, identities, t],
  );
  const visibleGroups = useMemo(
    () =>
      filterMaterialGroups(groups, {
        query,
        type: typeFilter === "local" ? "favorites" : typeFilter,
        brandKey,
        favoriteKeys,
        sort,
        identities,
      }),
    [brandKey, favoriteKeys, groups, identities, query, sort, typeFilter],
  );
  const selectedTypeSummary = useMemo(
    () => summarizeSelectedMaterialTypes(materials, staged),
    [materials, staged],
  );
  const typeSummaryText = useMemo(
    () =>
      selectedTypeSummary.counts
        .map(({ label, count }) =>
          formatMessage(t("basic_material_picker_type_count"), {
            type:
              label === "UNKNOWN"
                ? t("basic_material_picker_unknown_type")
                : label,
            count,
          }),
        )
        .join("、"),
    [selectedTypeSummary.counts, t],
  );

  const selectProfile = (
    profile: SavedMaterialLibraryItem,
    group?: MaterialProductGroup,
  ) => {
    const isAlreadySelected = staged.includes(profile.directory_name);
    setSelectionEffectDirectory(
      isAlreadySelected ? null : profile.directory_name,
    );
    setStaged((previous) => {
      if (group?.productId) {
        const groupDirectoryNames = new Set(
          group.profiles.map((item) => item.directory_name),
        );
        let replaced = false;
        const next = previous.flatMap((name) => {
          if (!groupDirectoryNames.has(name)) return [name];
          if (replaced) return [];
          replaced = true;
          return [profile.directory_name];
        });
        return replaced ? next : [...next, profile.directory_name];
      }
      return previous.includes(profile.directory_name)
        ? previous.filter((name) => name !== profile.directory_name)
        : [...previous, profile.directory_name];
    });
  };

  const toggleFavorite = (profile: SavedMaterialLibraryItem) => {
    const favoriteKey = favoriteKeyForMaterial(profile);
    setLocalPins((previous) => {
      const next = new Set(previous);
      if (next.has(favoriteKey)) {
        next.delete(favoriteKey);
      } else {
        next.add(favoriteKey);
      }
      saveMaterialProfileFavorites(next);
      return next;
    });
  };

  const toggleExpanded = (groupKey: string) => {
    setExpandedGroupKeys((previous) => {
      const next = new Set(previous);
      if (next.has(groupKey)) {
        next.delete(groupKey);
      } else {
        next.add(groupKey);
      }
      return next;
    });
  };

  const confirmSelection = () => {
    const afterConfirm = afterConfirmRef.current;
    afterConfirmRef.current = undefined;
    const error = onConfirm(staged);
    if (error) { setSelectionError(error); setShowMixedConfirmation(false); return; }
    afterConfirm?.();
  };
  const cancelMixedConfirmation = () => {
    afterConfirmRef.current = undefined;
    setShowMixedConfirmation(false);
  };
  const handleDone = (onConfirmed?: () => void) => {
    afterConfirmRef.current = onConfirmed;
    if (selectedTypeSummary.requiresConfirmation) {
      setShowMixedConfirmation(true);
      return;
    }
    confirmSelection();
  };
  const handleDoneRef = useRef(handleDone);
  handleDoneRef.current = handleDone;
  useImperativeHandle(ref, () => ({ done: (onConfirmed) => handleDoneRef.current(onConfirmed) }), []);

  const renderFavoriteButton = (
    profile: SavedMaterialLibraryItem,
    materialName: string,
  ) => {
    const key = favoriteKeyForMaterial(profile);
    const isFavorite = localPins.has(key);
    const reference = references[profile.directory_name];
    if (reference && typeFilter !== "local") return <ResourceActivityActions kind="materials" resource={reference} favoriteOnly />;
    const label = `${t(isFavorite ? "community_local_unpin" : "community_local_pin")} · ${materialName}（${profile.contributor_name?.trim() || t("basic_material_picker_unknown_author")}）`;
    const FavoriteIcon = isFavorite ? StarIcon : StarOutlineIcon;
    return (
      <button
        type="button"
        aria-label={label}
        aria-pressed={isFavorite}
        onClick={() => toggleFavorite(profile)}
        className={cx(
          "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl transition-colors",
          "focus:outline-none focus:ring-4 focus:ring-[var(--focus-ring)]",
          isFavorite
            ? "bg-amber-100 text-amber-600 hover:bg-amber-200 dark:bg-amber-400/15 dark:text-amber-300 dark:hover:bg-amber-400/25"
            : "text-slate-400 hover:bg-slate-100 hover:text-amber-500 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-amber-300",
        )}
      >
        <FavoriteIcon className="h-5 w-5" aria-hidden="true" />
      </button>
    );
  };

  const renderSingleProfileCard = (
    group: MaterialProductGroup,
    profile: SavedMaterialLibraryItem,
  ) => {
    const selected = stagedSet.has(profile.directory_name);
    const identity = identities.get(profile.directory_name)!;
    const materialName = identity.name;
    const materialType =
      resolvedMaterialType(profile) ||
      t("basic_material_picker_unknown_type");
    const selectLabel = formatMessage(
      t(
        selected
          ? "basic_material_picker_deselect_material"
          : "basic_material_picker_select_material",
      ),
      { material: materialName },
    );

    return (
      <article
        key={group.key}
        data-testid="material-picker-product-card"
        className={cx(
          materialPickerCardClass,
          "flex min-w-0 flex-col gap-3 p-3.5",
          selected
            ? materialPickerSelectedCardClass
            : materialPickerIdleCardClass,
          selected &&
            selectionEffectDirectory === profile.directory_name &&
            "material-picker-card-select-effect",
        )}
      >
        <div className="flex min-w-0 items-start gap-3">
          <button
            type="button"
            aria-label={selectLabel}
            aria-pressed={selected}
            onClick={() =>
              selectProfile(
                profile,
                group.profiles.length > 1 ? group : undefined,
              )
            }
            className="flex min-w-0 flex-1 flex-col items-stretch gap-3 rounded-xl text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
          >
            <span className="flex min-w-0 items-start gap-3">
              <CalibrationThumbnail kind="materials" rgb={profile.estimated_rgb} display={profile.display} size="sm" />
              <span className="min-w-0 flex-1">
                <LibraryCardIdentity {...identity} subtitle={[identity.brand, materialType, formatLayerHeightMm(profile.layer_height_mm)].filter(Boolean).join(" · ")}
                  thumbnail={{ kind: "materials", rgb: profile.estimated_rgb, display: profile.display }} />
              </span>
            </span>
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500 dark:text-slate-400">
              {profile.mean_delta_e != null && (
                <span>
                  {formatMessage(t("basic_material_picker_delta_e"), {
                    value: profile.mean_delta_e.toFixed(1),
                  })}
                </span>
              )}
              {profile.verification_count != null && (
                <span>
                  {formatMessage(
                    t("basic_material_picker_verification_count"),
                    { count: profile.verification_count },
                  )}
                </span>
              )}
              {profile.contributor_name?.trim() && (
                <span className="truncate">
                  {profile.contributor_name.trim()}
                </span>
              )}
            </span>
          </button>
          {renderFavoriteButton(profile, materialName)}
        </div>
      </article>
    );
  };

  const renderMultiProfileCard = (group: MaterialProductGroup) => {
    const displayProfiles = profilesForDisplay(group);
    const summaryProfile = displayProfiles[0];
    const identity = identities.get(summaryProfile.directory_name)!;
    const materialName = identity.name;
    const materialType =
      resolvedMaterialType(summaryProfile) ||
      t("basic_material_picker_unknown_type");
    const selectedProfile = group.profiles.find((profile) =>
      stagedSet.has(profile.directory_name),
    );
    const forceExpanded =
      query.trim().length > 0 || typeFilter === "favorites" || typeFilter === "local";
    const expanded = forceExpanded || expandedGroupKeys.has(group.key);
    const expandLabel = formatMessage(
      t(
        expanded
          ? "basic_material_picker_collapse_profiles"
          : "basic_material_picker_expand_profiles",
      ),
      { material: materialName },
    );

    return (
      <article
        key={group.key}
        data-testid="material-picker-product-card"
        className={cx(
          materialPickerCardClass,
          "flex min-w-0 flex-col gap-3 p-3.5",
          selectedProfile
            ? materialPickerSelectedCardClass
            : materialPickerIdleCardClass,
          selectedProfile?.directory_name === selectionEffectDirectory &&
            "material-picker-card-select-effect",
        )}
      >
        <div data-calibration-hover className="flex min-w-0 items-start gap-3">
          <CalibrationThumbnail kind="materials" rgb={summaryProfile.estimated_rgb} display={summaryProfile.display} size="sm" />
          <div className="min-w-0 flex-1">
            <LibraryCardIdentity {...identity} subtitle={[identity.brand, materialType, formatLayerHeightSummary(displayProfiles)].filter(Boolean).join(" · ")}
              thumbnail={{ kind: "materials", rgb: summaryProfile.estimated_rgb, display: summaryProfile.display }} />
          </div>
          <button
            type="button"
            aria-label={expandLabel}
            aria-expanded={expanded}
            onClick={() => toggleExpanded(group.key)}
            className="inline-flex min-h-9 items-center gap-1 rounded-xl px-2.5 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            {formatMessage(t("basic_material_picker_profile_count"), {
              count: displayProfiles.length,
            })}
            <DisclosureChevron expanded={expanded} />
          </button>
        </div>

        {expanded && (
          <div className="grid gap-2 border-t border-slate-200/80 pt-3 dark:border-slate-700/80">
            {displayProfiles.map((profile) => {
              const selected = stagedSet.has(profile.directory_name);
              const author =
                profile.contributor_name?.trim() ||
                t("basic_material_picker_unknown_author");
              const radioLabel = formatMessage(
                t("basic_material_picker_select_profile"),
                { material: materialName, author },
              );
              const detailParts = [
                profile.mean_delta_e != null
                  ? formatMessage(t("basic_material_picker_delta_e"), {
                      value: profile.mean_delta_e.toFixed(1),
                    })
                  : null,
                formatMessage(
                  t("basic_material_picker_verification_count"),
                  { count: profile.verification_count ?? 0 },
                ),
                formatLayerHeightMm(profile.layer_height_mm),
              ].filter((value): value is string => Boolean(value));
              return (
                <div
                  key={profile.directory_name}
                  className={cx(
                    "flex min-w-0 items-center gap-2 rounded-xl border px-2.5 py-2",
                    selected
                      ? "border-blue-300 bg-blue-50/80 dark:border-blue-500/60 dark:bg-blue-500/10"
                      : "border-slate-200/80 dark:border-slate-700/80",
                  )}
                >
                  <button
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    aria-label={radioLabel}
                    onClick={() => selectProfile(profile, group)}
                    className="flex min-w-0 flex-1 items-center gap-2 rounded-lg text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
                  >
                    <span
                      aria-hidden="true"
                      className={cx(
                        "flex h-4 w-4 shrink-0 items-center justify-center rounded-full border",
                        selected
                          ? "border-blue-600"
                          : "border-slate-300 dark:border-slate-600",
                      )}
                    >
                      {selected && (
                        <span className="h-2 w-2 rounded-full bg-blue-600" />
                      )}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-xs font-medium text-slate-800 dark:text-slate-100">
                        {author}
                      </span>
                      <span className="mt-0.5 block text-[11px] text-slate-500 dark:text-slate-400">
                        {detailParts.join(" · ")}
                      </span>
                    </span>
                  </button>
                  {renderFavoriteButton(profile, materialName)}
                </div>
              );
            })}
          </div>
        )}
      </article>
    );
  };

  if (!open) return null;

  const showEmpty = !loading && !loadError && materials.length === 0;
  const showEmptyFavorites =
    !loading &&
    materials.length > 0 &&
    typeFilter === "favorites" &&
    visibleGroups.length === 0 &&
    query.trim().length === 0;
  const showNoMatch =
    !loading &&
    materials.length > 0 &&
    !showEmptyFavorites &&
    visibleGroups.length === 0;
  const tabs: Array<{ key: MaterialTypeFilter | "local"; label: string }> = [
    {
      key: "favorites",
      label: t("community_filter_saved"),
    },
    { key: "local", label: t("community_local_common") },
    { key: "all", label: t("basic_material_picker_tab_all") },
    { key: "pla", label: t("basic_material_picker_tab_pla") },
    { key: "petg", label: t("basic_material_picker_tab_petg") },
    { key: "other", label: t("basic_material_picker_tab_other") },
  ];

  return createPortal(
    <>
      <div
        role="presentation"
        className="fixed inset-0 z-[9999] flex items-center justify-center p-4 sm:p-6"
        style={{ background: "var(--surface-scrim)" }}
        onMouseDown={(event) => {
          if (event.target === event.currentTarget) onCancel();
        }}
        data-testid="material-picker-dialog-overlay"
      >
        <div
          ref={dialogRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          aria-describedby={descriptionId}
          aria-hidden={showMixedConfirmation || undefined}
          tabIndex={-1}
          className="grid h-[min(51.25rem,calc(100vh-3rem))] w-[min(68rem,calc(100vw-3rem))] max-w-none grid-cols-[minmax(0,1fr)] overflow-hidden rounded-2xl border"
          style={{
            borderColor: "var(--surface-card-outline)",
            background: "var(--surface-panel-strong)",
            gridTemplateRows: cloudOpen ? "auto minmax(0,1fr)" : "auto auto auto minmax(0,1fr) auto",
          }}
          onMouseDown={(event) => event.stopPropagation()}
          data-testid="material-picker-dialog"
        >
          <header className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3 border-b border-slate-200/80 px-5 py-4 dark:border-slate-700/80 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:px-6">
            <div className="min-w-0 pr-4">
              <h2
                id={titleId}
                className="text-[15px] font-semibold text-slate-900 dark:text-slate-50"
              >
                {t("basic_material_picker_dialog_title")}
              </h2>
              <p
                id={descriptionId}
                className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400"
              >
                {t(trial ? "material_guide_picker_hint" : "basic_material_picker_dialog_subtitle")}
              </p>
            </div>
            <div className="col-span-2 row-start-2 flex min-w-0 flex-wrap items-center gap-2 sm:col-span-1 sm:col-start-2 sm:row-start-1">
              {!cloudOpen && materials.length > 0 && <Button label={t("resources_calibrate")} onClick={calibrate} />}
              {cloudOpen ? <Button label={t("resources_back_to_picker")} onClick={returnToLocal} />
                : materials.length > 0 && <Button label={t("resources_browse_public")} onClick={() => setCatalogSource("cloud")} />}
            </div>
            <div className="col-start-2 row-start-1 sm:col-start-3">
              <CloseButton label={t("basic_material_picker_close")} onClick={onCancel} />
            </div>
          </header>

          {cloudOpen ? <div className="min-h-0"><ResourceCatalogPanel kind="materials" initialSource={catalogSource ?? "cloud"} initialPersonalFilter={typeFilter === "favorites" ? "saved" : "all"} initialQuery={query} onQueryChange={setQuery} onInstalled={() => {
            onRetry?.();
            setResourceSuccess(t("resources_installed_pick"));
          }} /></div> : <>
          <div className="border-b border-slate-200/80 px-4 py-3 dark:border-slate-700/80 sm:px-6">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div
                role="tablist"
                data-tutorial="material-picker-tabs"
                aria-label={t("basic_material_picker_dialog_title")}
                className="flex min-w-0 gap-1 overflow-x-auto rounded-2xl bg-slate-100/80 p-1 dark:bg-slate-800/70"
              >
                {tabs.map((tab) => {
                  const selected = typeFilter === tab.key;
                  return (
                    <button
                      key={tab.key}
                      type="button"
                      role="tab"
                      aria-selected={selected}
                      onClick={() => {
                        if (tab.key === "favorites" && connection?.state !== "connected") setAccountOpen(true);
                        else setTypeFilter(tab.key);
                      }}
                      className={cx(
                        "min-h-9 shrink-0 rounded-xl px-3 text-xs font-medium transition-colors focus:outline-none focus:ring-4 focus:ring-[var(--focus-ring)]",
                        selected
                          ? "bg-[var(--surface-panel-strong)] text-blue-700 dark:text-blue-300"
                          : "text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-slate-50",
                      )}
                    >
                      {tab.label}
                    </button>
                  );
                })}
              </div>

              <div className="flex min-w-0 flex-1 flex-col gap-2 sm:flex-row lg:max-w-[35rem] lg:justify-end">
                <label className="relative min-w-0 flex-1" data-tutorial="material-picker-search">
                  <span className="sr-only">
                    {t("basic_material_picker_search_placeholder")}
                  </span>
                  <MagnifyingGlassIcon
                    className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
                    aria-hidden="true"
                  />
                  <input
                    ref={searchInputRef}
                    type="search"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder={t(
                      "basic_material_picker_search_placeholder",
                    )}
                    aria-label={t(
                      "basic_material_picker_search_placeholder",
                    )}
                    className={`${workstationInputClass} pl-10 pr-9`}
                    data-testid="material-picker-search-input"
                  />
                  {query && (
                    <button
                      type="button"
                      onClick={() => setQuery("")}
                      aria-label={t("basic_material_picker_search_clear")}
                      className="absolute right-2 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                      data-testid="material-picker-search-clear"
                    >
                      <XMarkIcon className="h-4 w-4" aria-hidden="true" />
                    </button>
                  )}
                </label>
                <div className="min-w-32 shrink-0 self-end sm:self-center">
                  <Dropdown
                    variant="filter"
                    label={t("basic_material_picker_sort_label")}
                    value={sort}
                    onChange={value => setSort(value as MaterialPickerSort)}
                    options={[
                      { value: "name", label: t("basic_material_picker_sort_name") },
                      { value: "recent", label: t("basic_material_picker_sort_recent") },
                    ]}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Selected materials pinned above the list, in selection order, so
              the current palette stays visible while browsing. An empty row
              keeps the grid rows stable. 已选耗材固定在列表上方，按选择顺序显示，
              浏览时始终能看到当前配色；未选择时保留空行以保持网格行数不变。 */}
          <div
            className={staged.length > 0 ? "border-b border-slate-200/80 px-4 py-2.5 dark:border-slate-700/80 sm:px-6" : undefined}
            data-testid="material-picker-selected-strip"
          >
            {staged.length > 0 && (
              <div className="flex items-start gap-3">
                <p className="shrink-0 pt-1 text-xs font-medium text-slate-500 dark:text-slate-400">
                  {t("basic_material_picker_selected_label")}
                </p>
                <ul className="dock-scrollbar flex max-h-[4.5rem] min-w-0 flex-1 flex-wrap gap-1.5 overflow-y-auto">
                  {staged.map((directoryName) => {
                    const item = materialByDirectory.get(directoryName);
                    const name = identities.get(directoryName)?.name ?? directoryName;
                    return (
                      <li
                        key={directoryName}
                        className="flex min-w-0 items-center gap-1.5 rounded-full border border-slate-200/80 bg-slate-50 py-0.5 pl-2 pr-0.5 dark:bg-slate-800/60 text-xs font-medium text-slate-700 dark:border-slate-700/80 dark:text-slate-200"
                      >
                        <span
                          aria-hidden="true"
                          className="inline-block size-2.5 shrink-0 rounded-full bg-slate-200 ring-1 ring-black/15 dark:bg-slate-700 dark:ring-white/25"
                          style={item ? { backgroundColor: materialSwatchColor(item) } : undefined}
                        />
                        <span className="max-w-[12rem] truncate" title={name}>
                          {name}
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            setStaged((previous) =>
                              previous.filter((value) => value !== directoryName),
                            )
                          }
                          aria-label={formatMessage(
                            t("basic_material_picker_remove_selected"),
                            { material: name },
                          )}
                          className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100 hover:text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] dark:hover:bg-slate-800 dark:hover:text-slate-200"
                        >
                          <XMarkIcon className="h-3.5 w-3.5" aria-hidden="true" />
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
          </div>

          <div className="grid min-h-0 md:grid-cols-[13rem_minmax(0,1fr)]">
            <aside
              className="hidden min-h-0 flex-col border-r border-slate-200/80 dark:border-slate-700/80 md:flex"
              data-testid="material-picker-brand-sidebar"
              data-tutorial="material-picker-brands"
            >
              <p className="px-4 pb-2 pt-4 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                {t("basic_material_picker_brand_filter_label")}
              </p>
              <div className="dock-scrollbar min-h-0 space-y-1 overflow-y-auto overscroll-y-contain px-2 pb-4">
                {brandOptions.map((option) => {
                  const selected = brandKey === option.key;
                  return (
                    <button
                      key={option.key}
                      type="button"
                      data-testid="material-picker-brand-option"
                      aria-pressed={selected}
                      onClick={() => setBrandKey(option.key)}
                      className={cx(
                        "flex min-h-10 w-full items-center justify-between gap-2 rounded-xl px-3 text-left text-xs transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--focus-ring)]",
                        selected
                          ? "bg-blue-50 font-semibold text-blue-700 dark:bg-blue-500/10 dark:text-blue-300"
                          : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800",
                      )}
                    >
                      <span
                        className="flex min-w-0 items-center gap-1.5"
                        data-testid={`material-picker-brand-option-${option.key}`}
                      >
                        <LibraryBrandLogo logo={option.logo} /><span className="truncate">{option.label}</span>
                      </span>
                      <span className="shrink-0 tabular-nums text-slate-400 dark:text-slate-500">
                        {option.count}
                      </span>
                    </button>
                  );
                })}
              </div>
            </aside>

            <main className="flex min-h-0 min-w-0 flex-col">
              <div className="border-b border-slate-200/80 px-4 py-3 dark:border-slate-700/80 md:hidden">
                <Dropdown
                  variant="filter"
                  label={t("basic_material_picker_brand_filter_label")}
                  value={brandKey}
                  onChange={setBrandKey}
                  options={brandOptions.map(option => ({
                    value: option.key,
                    label: `${option.label} (${option.count})`,
                  }))}
                />
              </div>

              <div
                className="dock-scrollbar min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4 sm:px-5"
                data-tutorial="material-picker-cards"
              >
                <CommunityNotice kind="materials" ids={Object.values(references).map((row) => row.resource_id)} />
                {typeFilter === "local" && <p className="mb-3 text-xs text-slate-500">{t("community_local_hint")}</p>}
                {operationError && <StatusBanner tone="error">{operationError}</StatusBanner>}
                {loadError && materials.length > 0 && <StatusBanner tone="error" action={<Button label={t("resources_retry")} onClick={onRetry} />}>{t("basic_material_picker_load_error")}</StatusBanner>}
                <TransientBanner message={resourceSuccess} onDismiss={() => setResourceSuccess(null)} />
                {loading ? (
                  <div className="flex min-h-48 items-center justify-center text-sm text-slate-500 dark:text-slate-400">
                    {t("basic_material_loading")}
                  </div>
                ) : loadError && materials.length === 0 ? (
                  <div
                    data-testid="material-picker-load-error"
                    className="flex min-h-48 flex-col items-center justify-center gap-4 text-center"
                  >
                    <StatusBanner tone="error">
                      {t("basic_material_picker_load_error")}
                    </StatusBanner>
                    {onRetry && (
                      <Button
                        label={t("basic_material_picker_retry")}
                        onClick={onRetry}
                        variant="secondary"
                        size="sm"
                      />
                    )}
                  </div>
                ) : showEmpty ? (
                  <ResourceLibraryEmpty kind="materials" onBrowse={setCatalogSource} onImport={importResources}
                    onCalibrate={calibrate} />
                ) : showEmptyFavorites ? (
                  <div className="flex min-h-48 flex-col items-center justify-center gap-3 text-center text-sm text-slate-500 dark:text-slate-400">
                    {t("basic_material_picker_empty_favorites")}
                    <Button label={t("community_saved_browse")} onClick={() => setCatalogSource("cloud")} />
                  </div>
                ) : showNoMatch ? (
                  <div
                    data-testid="material-picker-no-match"
                    className="flex min-h-48 flex-col items-center justify-center gap-3 text-center text-sm text-slate-500 dark:text-slate-400"
                  >
                    <p>{t("basic_material_picker_no_match")}</p>
                    <div className="flex flex-wrap justify-center gap-2">
                      <Button label={t("resources_browse_materials")} onClick={() => setCatalogSource("cloud")} />
                      <Button label={t("material_guide_create_missing")} onClick={calibrate} />
                    </div>
                  </div>
                ) : (
                  <div
                    className="grid gap-3 md:grid-cols-2"
                    data-testid="material-picker-card-grid"
                  >
                    {visibleGroups.map((group) => {
                      const displayProfiles = profilesForDisplay(group);
                      return displayProfiles.length === 1
                        ? renderSingleProfileCard(group, displayProfiles[0])
                        : renderMultiProfileCard(group);
                    })}
                  </div>
                )}
              </div>
            </main>
          </div>

          <footer
            className="border-t border-slate-200/80 px-4 py-3 dark:border-slate-700/80 sm:px-6"
            data-tutorial="material-picker-footer"
          >
            {selectionError && <StatusBanner tone="error" className="mb-3">{t(selectionError)}</StatusBanner>}
            {selectedTypeSummary.requiresConfirmation && (
              <StatusBanner
                role="status"
                tone="warning"
                className="mb-3 py-2"
              >
                {formatMessage(t("basic_material_picker_mixed_status"), {
                  types: typeSummaryText,
                })}
              </StatusBanner>
            )}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
                {t("basic_material_selected_count")}：{staged.length}
              </p>
              <div className="flex items-center gap-2">
                <Button
                  label={t("basic_material_picker_deselect_all")}
                  onClick={() => setStaged([])}
                  disabled={staged.length === 0}
                  variant="secondary"
                  size="sm"
                />
                <Button
                  label={t(trial ? (previewOnConfirm ? "material_guide_use_preview" : "material_guide_use") : "basic_material_picker_done")}
                  onClick={() => handleDone()}
                  disabled={trial && staged.length === 0}
                  size="sm"
                  variant="primary"
                />
              </div>
            </div>
          </footer>
          </>}
        </div>
      </div>

      {accountOpen && <CommunityAccountDialog onClose={() => setAccountOpen(false)} />}
      {showMixedConfirmation && (
        <div
          role="presentation"
          className="fixed inset-0 z-[10000] flex items-center justify-center p-4"
          style={{ background: "var(--surface-scrim)" }}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              cancelMixedConfirmation();
            }
          }}
        >
          <div
            ref={confirmDialogRef}
            role="alertdialog"
            aria-modal="true"
            aria-labelledby={confirmTitleId}
            aria-describedby={confirmDescriptionId}
            tabIndex={-1}
            className="w-full max-w-md rounded-2xl border p-4 sm:p-5"
            style={{
              borderColor: "var(--surface-card-outline)",
              background: "var(--surface-panel-strong)",
            }}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3">
              <h3
                id={confirmTitleId}
                className="text-[15px] font-semibold text-slate-900 dark:text-slate-50"
              >
                {t("basic_material_picker_mixed_confirm_title")}
              </h3>
              <CloseButton label={t("common_close")} onClick={cancelMixedConfirmation} />
            </div>
            <p
              id={confirmDescriptionId}
              className="mt-3 text-sm leading-6 text-slate-600 dark:text-slate-300"
            >
              {formatMessage(
                t("basic_material_picker_mixed_confirm_body"),
                { types: typeSummaryText },
              )}
            </p>
            <div className="mt-5 flex flex-wrap justify-end gap-2">
              <button
                ref={confirmBackRef}
                type="button"
                onClick={cancelMixedConfirmation}
                className="action-control min-h-9 rounded-lg px-4 text-sm font-medium transition-colors"
              >
                {t("basic_material_picker_mixed_back")}
              </button>
              <button
                type="button"
                onClick={confirmSelection}
                className="action-control action-control-primary min-h-9 rounded-lg px-4 text-sm font-semibold"
              >
                {t("basic_material_picker_mixed_continue")}
              </button>
            </div>
          </div>
        </div>
      )}
    </>,
    document.body,
  );
}
