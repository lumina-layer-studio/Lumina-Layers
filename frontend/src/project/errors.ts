import { apiErrorToVisibleMessage } from "../api/client";
import { translations } from "../i18n/translations";

const workshopProjectErrorKeys = [
  "workshop_project_snapshots_unsupported",
  "workshop_project_save_disconnected",
  "workshop_project_restore_disconnected",
] as const;

export function workshopProjectError(key: typeof workshopProjectErrorKeys[number], cause?: unknown): Error {
  return new Error(translations[key].en, { cause });
}

/** User-facing explanations; callers keep the original error in details. */
export function projectErrorMessage(cause: unknown, t: (key: string) => string): string {
  const message = cause instanceof Error ? cause.message : String(cause);
  const workshopErrorKey = workshopProjectErrorKeys.find((key) => translations[key].en === message);
  if (workshopErrorKey) return t(workshopErrorKey);
  if (/Project catalog update failed/.test(message)) return t("project_error_catalog");
  if (/[\u3400-\u9fff]/.test(message)) return message;
  if (/Request failed with status code|HTTP\s*\d{3}/i.test(message) || (cause && typeof cause === "object" && "response" in cause)) return apiErrorToVisibleMessage(cause, t("project_error_unknown"));
  if (/write access|permission|EACCES|EPERM|file_save_failed/i.test(message)) return t("file_save_failed");
  if (/changed while|Save again/.test(message)) return t("project_error_changed");
  if (/Wait for|pending|unresolved|commit.*unknown/i.test(message)) return t("recipe_export_wait_edits");
  if (/thumbnail could not/.test(message)) return t("project_error_thumbnail");
  if (/Locate the project file|ENOENT|not found|missing.*file/i.test(message)) return t("project_error_missing");
  if (/quota|IndexedDB|Recovery database|Recovery snapshot/i.test(message)) return t("project_error_recovery");
  if (/unsupported|not supported|newer project|workspace versions/i.test(message)) return t("project_error_version");
  if (/checksum|Invalid project|project ZIP|project JSON|Unexpected project|Project thumbnail|manifest\.|resourceRefs/i.test(message)) return t("project_error_invalid");
  return t("project_error_unknown");
}
