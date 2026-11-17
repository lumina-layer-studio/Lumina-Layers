import { useRef, useState } from "react";
import { apiErrorToVisibleMessage } from "../../api/client";
import { useI18n } from "../../i18n/context";
import { exportShareCard, MODEL_SURFACE_RECIPE_EXPORT_UNAVAILABLE_ERROR } from "../../recipe/importFlow";
import { useConverterStore } from "../../stores/converter";
import { useWidgetStore } from "../../stores/widgetStore";

function exportError(cause: unknown, t: (key: string) => string): string {
  const message = cause instanceof Error ? cause.message.trim() : "";
  if (message === t("recipe_export_wait_edits")) return message;
  const knownErrors: Record<string, string> = {
    file_save_failed: "file_save_failed",
    file_save_too_large: "file_save_too_large",
    recipe_export_wait_edits: "recipe_export_wait_edits",
    "No image file loaded": "recipe_export_error_no_image",
    "No preview available — please generate a preview first": "recipe_export_error_no_preview",
    "Failed to load preview image for cover": "recipe_export_error_preview_load",
    [MODEL_SURFACE_RECIPE_EXPORT_UNAVAILABLE_ERROR]: "recipe_export_model_surface_unavailable",
  };
  if (knownErrors[message]) return t(knownErrors[message]);
  if ((cause && typeof cause === "object" && "response" in cause)
    || /(?:Request failed with status code|HTTP(?:\s+error)?|status(?:\s+code)?)\s*\d{3}\b/i.test(message)) {
    return apiErrorToVisibleMessage(cause, t("recipe_export_error_unknown"));
  }
  return t("recipe_export_error_unknown");
}

export function useProjectShareCard(projectBusy: boolean) {
  const { t } = useI18n();
  const activeTab = useWidgetStore(state => state.activeTab);
  const batchMode = useConverterStore(state => state.batchMode);
  const modelSurface = useConverterStore(state => state.modelSurfaceEnabled);
  const hasImage = useConverterStore(state => Boolean(state.imageFile));
  const hasPreview = useConverterStore(state => Boolean(state.previewImageUrl && state.sessionId));
  const processing = useConverterStore(state => state.isLoading || state.isGenerating || state.batchLoading);
  const editing = useConverterStore(state => state.replacePreviewLoading || state.contentCommitStatus === "pending" || state.contentCommitStatus === "unknown");
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const available = activeTab === "converter" && !batchMode;
  const disabledReason = projectBusy || processing || busy ? t("project_share_wait")
    : modelSurface ? t("recipe_export_model_surface_unavailable")
      : editing ? t("recipe_export_wait_edits")
        : !hasImage ? t("recipe_export_error_no_image")
          : !hasPreview ? t("recipe_export_error_no_preview") : null;

  const exportCard = async () => {
    if (!available || disabledReason || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const outcome = await exportShareCard();
      if (outcome !== "canceled") setNotice(t(outcome === "saved" ? "file_save_saved" : "file_save_download_started"));
    } catch (cause) {
      setError(t("recipe_export_error").replace("{error}", exportError(cause, t)));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };
  return { available, busy, disabledReason, exportCard, error, notice, dismissError: () => setError(null), dismissNotice: () => setNotice(null) };
}
