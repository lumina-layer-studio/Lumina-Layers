/**
 * Pure helpers for the cloud material library page: display projection,
 * local install-state resolution, fit-error grading, and channel mapping.
 * 云端耗材库页面的纯函数：展示字段、本地安装状态、拟合误差分级、发布频道。
 */
import type {
  MaterialRegistryCatalogEntry,
  MaterialSyncInstalledEntry,
} from "../../api/types";
import { filamentIdentity, materialDisplayName } from "../../utils/filamentIdentity";

export type CatalogFilter = "all" | "not_installed" | "updates" | "installed";
export type CatalogInstallState =
  | "not_installed"
  | "installed"
  | "update_available"
  | "local_missing"
  | "local_available";
export type CatalogChannel = "official" | "community" | "team" | "other";
export type FitErrorGrade = "excellent" | "good" | "high" | "unknown";

export interface CatalogDisplay {
  brand: string;
  name: string;
  materialType: string;
  rgb: [number, number, number] | null;
}

export interface CatalogFitError {
  meanDeltaE: number | null;
  verificationCount: number | null;
  layerHeightMm: number | null;
  grade: FitErrorGrade;
}

export const CATALOG_FILTERS: CatalogFilter[] = [
  "all",
  "not_installed",
  "updates",
  "installed",
];

/** Mean ΔE at or below this is graded "excellent". */
export const FIT_ERROR_EXCELLENT_THRESHOLD = 2.0;

/**
 * Mirrors `_MEAN_DELTA_E_HIGH_THRESHOLD` in core/single_stage/materials.py:
 * above this mean ΔE the fit is treated as borderline.
 */
export const FIT_ERROR_HIGH_THRESHOLD = 3.0;

export const gradeFitError = (meanDeltaE: number | null): FitErrorGrade => {
  if (meanDeltaE === null) {
    return "unknown";
  }
  if (meanDeltaE <= FIT_ERROR_EXCELLENT_THRESHOLD) {
    return "excellent";
  }
  return meanDeltaE <= FIT_ERROR_HIGH_THRESHOLD ? "good" : "high";
};

const KNOWN_CHANNELS: ReadonlySet<string> = new Set(["official", "community", "team"]);

export const catalogEntryKey = (entry: MaterialRegistryCatalogEntry): string =>
  `${entry.material_id}:${entry.revision_id}`;

export const formatBytes = (bytes: number): string => {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
};

const readDisplayString = (
  display: Record<string, unknown>,
  keys: string[],
): string | null => {
  for (const key of keys) {
    const value = display[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return null;
};

const readRgb = (value: unknown): [number, number, number] | null => {
  if (!Array.isArray(value) || value.length < 3) {
    return null;
  }
  const channels = value.slice(0, 3).map((channel) => Number(channel));
  if (channels.some((channel) => !Number.isInteger(channel) || channel < 0 || channel > 255)) {
    return null;
  }
  return [channels[0], channels[1], channels[2]];
};

const readNonNegativeNumber = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;

export const toRgbCss = ([red, green, blue]: [number, number, number]): string =>
  `rgb(${red}, ${green}, ${blue})`;

export const toHex = ([red, green, blue]: [number, number, number]): string =>
  `#${[red, green, blue]
    .map((channel) => channel.toString(16).padStart(2, "0"))
    .join("")
    .toUpperCase()}`;

export const resolveCatalogDisplay = (entry: MaterialRegistryCatalogEntry): CatalogDisplay => {
  const display = entry.display ?? {};
  return {
    brand: readDisplayString(display, ["brand", "manufacturer", "vendor"]) ?? "",
    name: readDisplayString(display, ["material_name", "name", "display_name"])
      ?? entry.local_directory
      ?? entry.material_id,
    materialType: readDisplayString(display, ["material_type", "type"]) ?? "",
    rgb: readRgb(display.estimated_rgb ?? display.rgb)
      ?? readRgb(entry.card_metadata?.estimated_rgb),
  };
};

export function regionalCatalogDisplay(entry: MaterialRegistryCatalogEntry, lang: "zh" | "en", market: string) {
  const display = resolveCatalogDisplay(entry);
  return { ...display, ...materialDisplayName(filamentIdentity(display.brand, display.name, lang, entry.display, market)),
    materialType: display.materialType };
}

export const resolveCatalogFitError = (entry: MaterialRegistryCatalogEntry): CatalogFitError => {
  const metadata = entry.card_metadata ?? {};
  const meanDeltaE = readNonNegativeNumber(metadata.mean_delta_e);
  const verificationCount = readNonNegativeNumber(metadata.verification_count);
  const layerHeight = readNonNegativeNumber(metadata.layer_height_mm);
  return {
    meanDeltaE,
    verificationCount: verificationCount === null ? null : Math.round(verificationCount),
    layerHeightMm: layerHeight && layerHeight > 0 ? layerHeight : null,
    grade: gradeFitError(meanDeltaE),
  };
};

export const resolveCatalogChannel = (entry: MaterialRegistryCatalogEntry): CatalogChannel => {
  const channel = (entry.channel ?? "").trim().toLowerCase();
  return KNOWN_CHANNELS.has(channel) ? (channel as CatalogChannel) : "other";
};

const stripRevisionPrefix = (value: string): string =>
  value.trim().replace(/^sha256:/i, "").replace(/^rev_/i, "");

export const shortContentFingerprint = (entry: MaterialRegistryCatalogEntry): string => {
  const normalized = stripRevisionPrefix(entry.content_hash || entry.revision_id || "");
  return normalized ? normalized.slice(0, 12) : "-";
};

/** Short, human-scannable revision label ("rev_34c2719f59cd…" -> "34c2719f"). */
export const shortRevisionLabel = (revisionId: string): string => {
  const normalized = stripRevisionPrefix(revisionId);
  return normalized ? normalized.slice(0, 8) : "-";
};

export const materialLocalSignatureKey = (
  localDirectory: string | null | undefined,
  contentHash: string | null | undefined,
): string | null => {
  const directory = (localDirectory ?? "")
    .trim()
    .replace(/\\/g, "/")
    .replace(/^\/+|\/+$/g, "");
  const hash = (contentHash ?? "").trim().toLowerCase();
  if (!directory || !hash) {
    return null;
  }
  return `${directory}\n${hash}`;
};

export const hasLocalMaterialFiles = (entry: MaterialSyncInstalledEntry): boolean =>
  entry.local_exists && entry.material_file_exists;

export const resolveInstallState = (
  entry: MaterialRegistryCatalogEntry,
  installed?: MaterialSyncInstalledEntry,
): CatalogInstallState => {
  if (!installed) {
    return "not_installed";
  }
  if (!hasLocalMaterialFiles(installed)) {
    return "local_missing";
  }
  if (
    materialLocalSignatureKey(installed.local_directory, installed.content_hash)
    === materialLocalSignatureKey(entry.local_directory, entry.content_hash)
  ) {
    return "installed";
  }
  if (installed.revision_id === entry.revision_id) {
    return "installed";
  }
  if (installed.available_revisions.includes(entry.revision_id)) {
    return "local_available";
  }
  return "update_available";
};

export const matchesCatalogFilter = (
  installState: CatalogInstallState,
  filter: CatalogFilter,
): boolean => {
  switch (filter) {
    case "not_installed":
      return installState === "not_installed" || installState === "local_missing";
    case "updates":
      return installState === "update_available";
    case "installed":
      return installState === "installed" || installState === "local_available";
    default:
      return true;
  }
};

export const resolveRollbackRevisions = (installed: MaterialSyncInstalledEntry): string[] =>
  Array.from(new Set(installed.available_revisions.filter(
    (revisionId) => revisionId && revisionId !== installed.revision_id,
  )));
