import { useState } from "react";
import { createPortal } from "react-dom";
import { useConverterStore } from "../../stores/converterStore";
import Button from "../ui/Button";
import BatchResultSummary from "../ui/BatchResultSummary";
import ZoomableImage from "../ui/ZoomableImage";
import BedSizeSelector from "./BedSizeSelector";
import SlicerSelector from "./SlicerSelector";
import WikiTooltip from "../ui/WikiTooltip";
import { useI18n } from "../../i18n/context";
import { useWorkspaceMode } from "../../hooks/useWorkspaceMode";

export default function ActionBar() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();
  const [zoomedLayerIdx, setZoomedLayerIdx] = useState<number | null>(null);
  const imageFile = useConverterStore((s) => s.imageFile);
  const lut_name = useConverterStore((s) => s.lut_name);
  const isLoading = useConverterStore((s) => s.isLoading);
  const error = useConverterStore((s) => s.error);
  const previewImageUrl = useConverterStore((s) => s.previewImageUrl);
  const submitPreview = useConverterStore((s) => s.submitPreview);
  const submitGenerate = useConverterStore((s) => s.submitGenerate);
  const submitFullPipeline = useConverterStore((s) => s.submitFullPipeline);
  const threemfDiskPath = useConverterStore((s) => s.threemfDiskPath);
  const downloadUrl = useConverterStore((s) => s.downloadUrl);
  const sessionId = useConverterStore((s) => s.sessionId);
  const largeFormatEnabled = useConverterStore((s) => s.largeFormatEnabled);

  const batchMode = useConverterStore((s) => s.batchMode);
  const batchFiles = useConverterStore((s) => s.batchFiles);
  const batchLoading = useConverterStore((s) => s.batchLoading);
  const batchResult = useConverterStore((s) => s.batchResult);
  const submitBatch = useConverterStore((s) => s.submitBatch);

  const fetchLayerImages = useConverterStore((s) => s.fetchLayerImages);
  const layerImagesLoading = useConverterStore((s) => s.layerImagesLoading);
  const layerImages = useConverterStore((s) => s.layerImages);

  const canSubmit = !!imageFile && !!lut_name;
  const canBatchSubmit = batchFiles.length > 0 && !!lut_name;
  const hasPreview = !!previewImageUrl && !!sessionId;

  return (
    <div className="flex flex-col gap-3">
      {batchMode ? (
        <>
          {!canBatchSubmit && (
            <p className="text-xs text-yellow-600 dark:text-yellow-400">{t("action_batch_upload_hint")}</p>
          )}

          <div className={`gap-2 ${workspace.isCompact ? "grid grid-cols-1" : "flex flex-wrap"}`}>
            <Button
              label={t("action_batch_generate")}
              variant="primary"
              onClick={() => void submitBatch()}
              disabled={!canBatchSubmit || batchLoading}
              loading={batchLoading}
            />
          </div>

          {batchResult && <BatchResultSummary result={batchResult} />}
        </>
      ) : (
        <>
          {!canSubmit && (
            <p className="text-xs text-yellow-600 dark:text-yellow-400">{t("action_upload_hint")}</p>
          )}

          <div className={`gap-2 ${workspace.isCompact ? "grid grid-cols-1" : "flex flex-wrap"}`}>
            <Button
              label={t("action_preview")}
              variant="secondary"
              onClick={submitPreview}
              disabled={!canSubmit || isLoading}
              loading={isLoading}
            />
            <WikiTooltip
              title="生成 3D 模型"
              description="基于当前图像和 LUT 校准数据，生成可打印的全彩 3MF 模型文件。"
              wikiUrl="https://github.com/pekingduck/lumina-layers/wiki/Image-Converter"
            >
              <Button
                label={t("action_generate")}
                variant="primary"
                onClick={() => void submitGenerate()}
                disabled={!canSubmit || isLoading}
                loading={isLoading}
              />
            </WikiTooltip>
            {hasPreview && (
              <Button
                label={layerImagesLoading ? t("action_layers_loading") : t("action_view_layers")}
                variant="secondary"
                onClick={() => void fetchLayerImages()}
                disabled={layerImagesLoading}
                loading={layerImagesLoading}
              />
            )}
          </div>
        </>
      )}

      {error && (
        <div className="text-xs text-red-500 dark:text-red-400">{error}</div>
      )}

      <BedSizeSelector />

      {previewImageUrl && (
        <ZoomableImage
          src={previewImageUrl}
          alt={t("action_preview_alt")}
          className="w-full rounded-[22px] border border-gray-300 dark:border-gray-700"
        />
      )}

      {/* 分层缩略图（inline） */}
      {layerImages.length > 0 && (
        <div className="rounded-lg border border-gray-200 p-3 dark:border-gray-700">
          <h4 className="mb-2 text-xs font-medium text-gray-600 dark:text-gray-400">{t("action_layers_title")}</h4>
          <div className={`grid gap-2 ${workspace.isCompact ? "grid-cols-2 sm:grid-cols-3" : "grid-cols-3 sm:grid-cols-4 md:grid-cols-5"}`}>
            {layerImages.map((layer, idx) => (
              <div
                key={layer.layer_index}
                className="group cursor-pointer flex flex-col items-center gap-1"
                onClick={() => setZoomedLayerIdx(idx)}
              >
                <div className="relative w-full overflow-hidden rounded border border-gray-200 dark:border-gray-600">
                  <img
                    src={layer.url}
                    alt={`${t("action_layer_nth")}${idx + 1}${t("action_layer_unit")}`}
                    className="w-full transition-transform group-hover:scale-105"
                    draggable={false}
                  />
                  <div className="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors group-hover:bg-black/20">
                    <span className="text-sm text-white opacity-0 transition-opacity group-hover:opacity-100">🔍</span>
                  </div>
                </div>
                <span className="text-[11px] text-gray-600 dark:text-gray-400">
                  {t("action_layer_nth")}{idx + 1}{t("action_layer_unit")}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 单张图片全屏查看（Portal 渲染到 body） */}
      {zoomedLayerIdx !== null && layerImages[zoomedLayerIdx] && createPortal(
        <div
          className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/80"
          onClick={() => setZoomedLayerIdx(null)}
        >
          <div
            className="relative flex max-h-[95vh] max-w-[95vw] flex-col items-center"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex w-full items-center justify-between">
              <span className="text-base font-medium text-white">
                {t("action_layer_nth")}{zoomedLayerIdx + 1}{t("action_layer_unit")}
              </span>
              <div className={`items-center gap-2 ${workspace.isCompact ? "grid grid-cols-[1fr_auto] gap-y-1" : "flex"}`}>
                <button
                  className="rounded-lg px-3 py-1 text-sm text-white/80 hover:bg-white/10 disabled:opacity-30"
                  onClick={() => setZoomedLayerIdx(Math.max(0, zoomedLayerIdx - 1))}
                  disabled={zoomedLayerIdx === 0}
                >
                  ← {t("action_layer_prev")}
                </button>
                <span className="text-sm text-white/60">{zoomedLayerIdx + 1} / {layerImages.length}</span>
                <button
                  className="rounded-lg px-3 py-1 text-sm text-white/80 hover:bg-white/10 disabled:opacity-30"
                  onClick={() => setZoomedLayerIdx(Math.min(layerImages.length - 1, zoomedLayerIdx + 1))}
                  disabled={zoomedLayerIdx === layerImages.length - 1}
                >
                  {t("action_layer_next")} →
                </button>
                <button
                  className="ml-2 rounded-lg p-2 text-white/80 hover:bg-white/10"
                  onClick={() => setZoomedLayerIdx(null)}
                  aria-label="Close"
                >
                  ✕
                </button>
              </div>
            </div>
            <img
              src={layerImages[zoomedLayerIdx].url}
              alt={`${t("action_layer_nth")}${zoomedLayerIdx + 1}${t("action_layer_unit")}`}
              className="max-h-[85vh] max-w-full rounded-lg object-contain"
              draggable={false}
            />
          </div>
        </div>,
        document.body,
      )}

      <SlicerSelector
        threemfDiskPath={threemfDiskPath}
        downloadUrl={downloadUrl}
        canSubmit={canSubmit}
        largeFormat={largeFormatEnabled}
        onAutoGenerate={async () => {
          await submitFullPipeline();
          return useConverterStore.getState().threemfDiskPath ?? null;
        }}
      />
    </div>
  );
}
