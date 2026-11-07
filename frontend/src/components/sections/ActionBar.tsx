import { useMemo, useState, useRef, useEffect } from "react"
import { buildLayerImagesSourceKey, CONVERTER_ERROR_KEYS, resolveConverterSourceSelection, useConverterStore } from "../../stores/converter"
import Button from "../ui/Button"
import Checkbox from "../ui/Checkbox"
import { useSettingsStore } from "../../stores/settingsStore"
import { supportsExternalSpool } from "../../stores/converter/nativeMaterialSelection"
import { cardDividerClass } from "../ui/panelPrimitives"
import BatchResultSummary from "../ui/BatchResultSummary"
import LayerMaskViewerDialog from "../ui/LayerMaskViewerDialog"
import BedSizeSelector from "./BedSizeSelector"
import SlicerSelector from "./SlicerSelector"
import { StatusBanner } from "../ui/panelPrimitives"
import { useI18n } from "../../i18n/context"
import { useWorkspaceMode } from "../../hooks/useWorkspaceMode"
import { apiErrorToVisibleMessage } from "../../api/client"
import {
  exportShareCard,
  exportSidecar,
  MODEL_SURFACE_RECIPE_EXPORT_UNAVAILABLE_ERROR,
} from "../../recipe/importFlow"

const EMPTY_LAYER_IMAGES: { layer_index: number; name: string; url: string }[] = []
const EXPORT_NO_IMAGE_MESSAGE = "No image file loaded"
const EXPORT_NO_PREVIEW_MESSAGE = "No preview available — please generate a preview first"
const EXPORT_PREVIEW_LOAD_MESSAGE = "Failed to load preview image for cover"
const GENERIC_HTTP_STATUS_ERROR_RE =
  /(?:Request failed with status code|HTTP(?:\s+error)?|status(?:\s+code)?)\s*\d{3}\b/i

function hasApiErrorResponse(error: unknown): boolean {
  return Boolean(error && typeof error === "object" && "response" in error)
}

function shouldUseApiErrorLanguage(error: unknown): boolean {
  if (hasApiErrorResponse(error)) {
    return true
  }
  const message = error instanceof Error ? error.message.trim() : ""
  return GENERIC_HTTP_STATUS_ERROR_RE.test(message)
}

/** Compact stroke icons for the ghost action row. 幽灵操作行的线性图标。 */
function DownloadIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  )
}

function resolveRecipeExportError(error: unknown, t: (key: string) => string): string {
  if (error instanceof Error) {
    if (error.message === 'file_save_failed' || error.message === 'file_save_too_large') return t(error.message)
    if (error.message === EXPORT_NO_IMAGE_MESSAGE) {
      return t("recipe_export_error_no_image")
    }
    if (error.message === EXPORT_NO_PREVIEW_MESSAGE) {
      return t("recipe_export_error_no_preview")
    }
    if (error.message === EXPORT_PREVIEW_LOAD_MESSAGE) {
      return t("recipe_export_error_preview_load")
    }
    if (error.message === MODEL_SURFACE_RECIPE_EXPORT_UNAVAILABLE_ERROR) {
      return t("recipe_export_model_surface_unavailable")
    }
  }
  if (shouldUseApiErrorLanguage(error)) {
    return apiErrorToVisibleMessage(error, t("recipe_export_error_unknown"))
  }
  return t("recipe_export_error_unknown")
}

export default function ActionBar() {
  const { t } = useI18n()
  const workspace = useWorkspaceMode()
  const [zoomedLayerIdx, setZoomedLayerIdx] = useState<number | null>(null)
  const fetchedLayerSourceRef = useRef<string | null>(null)

  const imageFile = useConverterStore((s) => s.imageFile)
  const lut_name = useConverterStore((s) => s.lut_name)
  const lut_names = useConverterStore((s) => s.lut_names)
  const lutListFull = useConverterStore((s) => s.lutListFull)
  const legacyCatalogGroups = useConverterStore((s) => s.legacyCatalogGroups)
  const sourceVersion = useConverterStore((s) => s.source_version)
  const autoReplaceGradientBanding = useSettingsStore((s) => s.autoReplaceGradientBanding)
  const setAutoReplaceGradientBanding = useSettingsStore((s) => s.setAutoReplaceGradientBanding)
  const selectedNativeBrandKey = useConverterStore((s) => s.selectedNativeBrandKey)
  const selectedNativeDbNames = useConverterStore((s) => s.selectedNativeDbNames)
  const nativeBrandGroups = useConverterStore((s) => s.nativeBrandGroups)
  const nativeColorLayers = useConverterStore((s) => s.color_layers)
  const nativeLayerHeightMm = useConverterStore((s) => s.layer_height_mm)
  const selectedMaterialDirNames = useConverterStore((s) => s.selectedMaterialDirNames)
  const materialLayerCount = useConverterStore((s) => s.materialLayerCount)
  const materialLayerHeightMm = useConverterStore((s) => s.materialLayerHeightMm)
  const isLoading = useConverterStore((s) => s.isLoading)
  const isGenerating = useConverterStore((s) => s.isGenerating)
  const replacePreviewLoading = useConverterStore((s) => s.replacePreviewLoading)
  const contentCommitStatus = useConverterStore((s) => s.contentCommitStatus)
  const reconcileUnknownContentCommit = useConverterStore((s) => s.reconcileUnknownContentCommit)
  const error = useConverterStore((s) => s.error)
  const previewImageUrl = useConverterStore((s) => s.previewImageUrl)
  const previewBaseImageUrl = useConverterStore((s) => s.previewBaseImageUrl)
  const puzzleOverlayUrl = useConverterStore((s) => s.puzzleOverlayUrl)
  const submitPreview = useConverterStore((s) => s.submitPreview)
  const openNativeMaterialSelection = useConverterStore((s) => s.openNativeMaterialSelection)
  const hasExternalSpool = useSettingsStore(supportsExternalSpool)
  const nativeMaterialSelectionLoading = useConverterStore((s) => s.nativeMaterialSelectionLoading)
  const submitFullPipeline = useConverterStore((s) => s.submitFullPipeline)
  const threemfDiskPath = useConverterStore((s) => s.threemfDiskPath)
  const downloadUrl = useConverterStore((s) => s.downloadUrl)
  const backingOutput = useConverterStore((s) => s.backingOutput)
  const separatedBacking = useConverterStore((s) => s.separate_backing)
  const generateWarnings = useConverterStore((s) => s.generateWarnings)
  const sessionId = useConverterStore((s) => s.sessionId)
  const largeFormatEnabled = useConverterStore((s) => s.largeFormatEnabled)
  const modelSurfaceEnabled = useConverterStore((s) => s.modelSurfaceEnabled)

  const batchMode = useConverterStore((s) => s.batchMode)
  const batchFiles = useConverterStore((s) => s.batchFiles)
  const batchLoading = useConverterStore((s) => s.batchLoading)
  const batchResult = useConverterStore((s) => s.batchResult)
  const submitBatch = useConverterStore((s) => s.submitBatch)

  const fetchLayerImages = useConverterStore((s) => s.fetchLayerImages)
  const layerImagesLoading = useConverterStore((s) => s.layerImagesLoading)
  const layerImages = useConverterStore((s) => s.layerImages)
  const layerImagesSourceKey = useConverterStore((s) => s.layerImagesSourceKey)
  const layerImagesCurrentKey = useConverterStore(buildLayerImagesSourceKey)
  const sourceSelection = useMemo(
    () =>
      resolveConverterSourceSelection({
        source_version: sourceVersion,
        lut_name,
        lut_names,
        nativeBrandGroups,
        selectedNativeBrandKey,
        selectedNativeDbNames,
        color_layers: nativeColorLayers,
        layer_height_mm: nativeLayerHeightMm,
        selectedMaterialDirNames,
        materialLayerCount,
        materialLayerHeightMm,
        lutListFull,
        legacyCatalogGroups,
      }),
    [
      sourceVersion,
      lut_name,
      lut_names,
      nativeBrandGroups,
      selectedNativeBrandKey,
      selectedNativeDbNames,
      nativeColorLayers,
      nativeLayerHeightMm,
      selectedMaterialDirNames,
      materialLayerCount,
      materialLayerHeightMm,
      lutListFull,
      legacyCatalogGroups,
    ],
  )

  const [isExporting, setIsExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  const [exportNotice, setExportNotice] = useState<string | null>(null)

  const canSubmit = !!imageFile && sourceSelection.isReady
  const largeFormatModelSurfaceConflict = largeFormatEnabled && modelSurfaceEnabled
  // Retained downloads remain available when the current modes cannot generate.
  const canSubmitSlicerOutput = canSubmit && (!largeFormatModelSurfaceConflict || !!downloadUrl)
  const canBatchSubmit = batchFiles.length > 0 && sourceSelection.isReady
  const singleSourceHintKey =
    sourceVersion === "material"
      ? "action_select_material_hint"
      : sourceVersion === "native"
        ? "action_select_native_hint"
        : "action_select_lut_hint"
  const singleCombinedHintKey =
    sourceVersion === "material"
      ? "action_upload_hint_material"
      : sourceVersion === "native"
        ? "action_upload_hint_native"
        : "action_upload_hint"
  const singleSubmitHintKey = canSubmit
    ? null
    : imageFile
      ? singleSourceHintKey
      : sourceSelection.isReady
        ? "action_upload_image_hint"
        : singleCombinedHintKey
  const batchUploadHintKey =
    sourceVersion === "material"
      ? "action_batch_upload_hint_material"
      : sourceVersion === "native"
        ? "action_batch_upload_hint_native"
        : "action_batch_upload_hint"
  const previewDisplayUrl = puzzleOverlayUrl
    ? (previewBaseImageUrl ?? previewImageUrl)
    : previewImageUrl
  const activeLayerImages =
    layerImagesSourceKey === layerImagesCurrentKey ? layerImages : EMPTY_LAYER_IMAGES
  const hasPreview = !!previewDisplayUrl && !!sessionId

  useEffect(() => {
    if (!sessionId) {
      fetchedLayerSourceRef.current = null
      return
    }

    if (
      !hasPreview ||
      isLoading ||
      !layerImagesCurrentKey ||
      layerImagesLoading ||
      activeLayerImages.length > 0
    ) {
      return
    }

    if (fetchedLayerSourceRef.current === layerImagesCurrentKey) {
      return
    }

    fetchedLayerSourceRef.current = layerImagesCurrentKey
    void fetchLayerImages(layerImagesCurrentKey)
  }, [
    activeLayerImages.length,
    fetchLayerImages,
    hasPreview,
    isLoading,
    layerImagesCurrentKey,
    layerImagesLoading,
    sessionId,
  ])

  useEffect(() => {
    setZoomedLayerIdx(null)
  }, [sessionId])

  useEffect(() => {
    setZoomedLayerIdx((previous) => {
      if (previous === null) {
        return previous
      }
      return activeLayerImages[previous] ? previous : null
    })
  }, [activeLayerImages])

  return (
    <div className="flex flex-col gap-3">
      {batchMode ? (
        <>
          {!canBatchSubmit && (
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {t(batchUploadHintKey)}
            </p>
          )}

          <div className={`gap-2 ${workspace.isCompact ? "grid grid-cols-1" : "flex flex-wrap"}`}>
            <Button
              label={t("action_batch_generate")}
              variant="primary"
              onClick={() => void submitBatch()}
              disabled={!canBatchSubmit || batchLoading || nativeMaterialSelectionLoading}
              loading={batchLoading}
            />
            {hasExternalSpool && (
              <Button
                label={t("native_material_edit_button")}
                variant="secondary"
                onClick={() => void openNativeMaterialSelection()}
                disabled={!sourceSelection.isReady || isGenerating || batchLoading}
                loading={nativeMaterialSelectionLoading}
              />
            )}
          </div>

          {batchResult && <BatchResultSummary result={batchResult} />}
        </>
      ) : (
        <>
          {contentCommitStatus === "unknown" && (
            <StatusBanner tone="warning" title={t("action_sync_editor_commit") }>
              <div className="flex flex-col gap-2">
                <span>{t("action_sync_editor_commit_hint")}</span>
                <Button
                  label={t("action_sync_editor_commit")}
                  variant="secondary"
                  onClick={() => void reconcileUnknownContentCommit()}
                  disabled={replacePreviewLoading || isGenerating}
                  className="w-full"
                />
              </div>
            </StatusBanner>
          )}
          {!canSubmit && (
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {singleSubmitHintKey ? t(singleSubmitHintKey) : null}
            </p>
          )}

          <div className="grid grid-cols-1 gap-2">
            <div data-tutorial="preview-button" className="grid">
              <Button
                label={t(isLoading && sourceSelection.isMaterial && autoReplaceGradientBanding ? "action_preview_with_gradient" : "action_preview")}
                variant="primary"
                onClick={submitPreview}
                disabled={!canSubmit || isLoading}
                loading={isLoading}
                className="w-full"
              />
            </div>
            {sourceSelection.isMaterial && (
              <div>
                <Checkbox
                  label={t("settings.auto_replace_gradient_heading")}
                  checked={autoReplaceGradientBanding}
                  onChange={setAutoReplaceGradientBanding}
                  disabled={isLoading || isGenerating || replacePreviewLoading}
                  tooltip={t("settings.auto_replace_gradient_description")}
                />
                {autoReplaceGradientBanding && (
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    {t("action_auto_gradient_hint")}
                  </p>
                )}
              </div>
            )}
            {largeFormatModelSurfaceConflict && error !== CONVERTER_ERROR_KEYS.largeFormatModelSurfaceConflict && (
              <p role="status" className="text-xs text-amber-700 dark:text-amber-300">
                {t("large_format_model_surface_conflict")}
              </p>
            )}
            <Button
              label={t("native_material_edit_button")}
              variant="secondary"
              onClick={() => void openNativeMaterialSelection()}
              disabled={!hasPreview || !sourceSelection.isReady || isLoading || isGenerating || batchLoading || replacePreviewLoading || contentCommitStatus === "unknown"}
              loading={nativeMaterialSelectionLoading}
              className="w-full min-h-9 px-4 py-2"
            />
            {hasPreview && (
              <>
                <div className={cardDividerClass} aria-hidden="true" />
                <div className="flex gap-2">
                  <Button
                    label={isExporting ? t("recipe_export_loading") : t("recipe_export_btn")}
                    variant="secondary"
                    onClick={() => {
                      setIsExporting(true)
                      setExportError(null)
                      exportShareCard()
                        .then((outcome) => setExportNotice(outcome === 'canceled' ? null : t(outcome === 'saved' ? 'file_save_saved' : 'file_save_download_started')))
                        .catch((err: unknown) => {
                          setExportError(resolveRecipeExportError(err, t))
                        })
                        .finally(() => setIsExporting(false))
                    }}
                    disabled={isExporting || modelSurfaceEnabled || isLoading || replacePreviewLoading}
                    loading={isExporting}
                    leadingIcon={<DownloadIcon />}
                    title={modelSurfaceEnabled ? t("recipe_export_model_surface_unavailable") : undefined}
                    className="flex-1"
                  />
                  <Button
                    label={t("recipe_export_sidecar_btn")}
                    variant="secondary"
                    onClick={() => {
                      setIsExporting(true)
                      setExportError(null)
                      exportSidecar()
                        .then((outcome) => setExportNotice(outcome === 'canceled' ? null : t(outcome === 'saved' ? 'file_save_saved' : 'file_save_download_started')))
                        .catch((err: unknown) => {
                          setExportError(resolveRecipeExportError(err, t))
                        })
                        .finally(() => setIsExporting(false))
                    }}
                    disabled={isExporting || modelSurfaceEnabled || isLoading || replacePreviewLoading}
                    leadingIcon={<DownloadIcon />}
                    title={modelSurfaceEnabled ? t("recipe_export_model_surface_unavailable") : undefined}
                    className="flex-1"
                  />
                </div>
              </>
            )}
            {hasPreview && modelSurfaceEnabled && (
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t("recipe_export_model_surface_unavailable")}
              </p>
            )}
            {exportError && (
              <div className="text-xs text-red-500 dark:text-red-400">
                {t("recipe_export_error").replace("{error}", exportError)}
              </div>
            )}
            {!isExporting && !exportError && exportNotice && <p role="status" className="text-xs">{exportNotice}</p>}
          </div>
        </>
      )}

      {error && (
        <div className="text-xs text-red-500 dark:text-red-400">{t(error)}</div>
      )}

      <BedSizeSelector />

      <LayerMaskViewerDialog
        open={zoomedLayerIdx !== null && !!activeLayerImages[zoomedLayerIdx]}
        layers={activeLayerImages}
        activeIndex={zoomedLayerIdx}
        onChangeIndex={setZoomedLayerIdx}
        onClose={() => setZoomedLayerIdx(null)}
        isCompact={workspace.isCompact}
      />

      {activeLayerImages.length > 0 && (
        <div className="flex flex-col gap-3">
          <div className={cardDividerClass} aria-hidden="true" />
          <h4 className="text-xs font-medium text-slate-600 dark:text-slate-400">
            {t("action_layers_title")}
          </h4>
          <div
            className={`grid gap-2 ${workspace.isCompact ? "grid-cols-2 sm:grid-cols-3" : "grid-cols-3 sm:grid-cols-4 md:grid-cols-5"}`}
          >
            {activeLayerImages.map((layer, idx) => (
              <div
                key={layer.layer_index}
                className="group flex cursor-pointer flex-col items-center gap-1"
                onClick={() => setZoomedLayerIdx(idx)}
              >
                <div className="relative w-full overflow-hidden rounded-lg border border-slate-200/70 dark:border-slate-700/70">
                  <img
                    src={layer.url}
                    alt={`${t("action_layer_nth")}${idx + 1}${t("action_layer_unit")}`}
                    className="w-full transition-transform group-hover:scale-105"
                    draggable={false}
                  />
                  <div className="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors group-hover:bg-black/20">
                    <span className="text-sm text-white opacity-0 transition-opacity group-hover:opacity-100">
                      {t("action_zoom_icon")}
                    </span>
                  </div>
                </div>
                <span className="text-[11px] text-slate-600 dark:text-slate-400">
                  {t("action_layer_nth")}{idx + 1}{t("action_layer_unit")}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {downloadUrl &&
        generateWarnings.includes("wipe_tower_manual_adjustment_required") && (
          <StatusBanner
            tone="warning"
            title={t("wipe_tower_manual_adjustment_title")}
          >
            {t("wipe_tower_manual_adjustment_warning")}
          </StatusBanner>
        )}

      <div data-tutorial="print-output">
        <SlicerSelector
          threemfDiskPath={threemfDiskPath}
          downloadUrl={downloadUrl}
          canSubmit={!nativeMaterialSelectionLoading && (batchMode ? canBatchSubmit && !batchLoading : canSubmitSlicerOutput && !isLoading && !replacePreviewLoading && contentCommitStatus !== "unknown")}
          largeFormat={batchMode ? false : largeFormatEnabled || (separatedBacking && backingOutput === "separate_project")}
          onAutoGenerate={async () => {
            if (batchMode) {
              await submitBatch()
              const state = useConverterStore.getState()
              return state.downloadUrl ?? state.threemfDiskPath ?? null
            }
            await submitFullPipeline()
            const state = useConverterStore.getState()
            return state.downloadUrl ?? state.threemfDiskPath ?? null
          }}
        />
      </div>
    </div>
  )
}
