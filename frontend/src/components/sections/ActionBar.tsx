import { useConverterStore } from "../../stores/converterStore";
import Button from "../ui/Button";
import BatchResultSummary from "../ui/BatchResultSummary";
import ZoomableImage from "../ui/ZoomableImage";
import BedSizeSelector from "./BedSizeSelector";
import SlicerSelector from "./SlicerSelector";
import { useI18n } from "../../i18n/context";

export default function ActionBar() {
  const { t } = useI18n();
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

  const batchMode = useConverterStore((s) => s.batchMode);
  const batchFiles = useConverterStore((s) => s.batchFiles);
  const batchLoading = useConverterStore((s) => s.batchLoading);
  const batchResult = useConverterStore((s) => s.batchResult);
  const submitBatch = useConverterStore((s) => s.submitBatch);

  const canSubmit = !!imageFile && !!lut_name;
  const canBatchSubmit = batchFiles.length > 0 && !!lut_name;

  return (
    <div className="flex flex-col gap-3">
      {batchMode ? (
        <>
          {!canBatchSubmit && (
            <p className="text-xs text-yellow-600 dark:text-yellow-400">{t("action_batch_upload_hint")}</p>
          )}

          <div className="flex gap-2">
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

          <div className="flex gap-2">
            <Button
              label={t("action_preview")}
              variant="secondary"
              onClick={submitPreview}
              disabled={!canSubmit || isLoading}
              loading={isLoading}
            />
            <Button
              label={t("action_generate")}
              variant="primary"
              onClick={() => void submitGenerate()}
              disabled={!canSubmit || isLoading}
              loading={isLoading}
            />
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
          className="w-full rounded-md border border-gray-300 dark:border-gray-700"
        />
      )}

      <SlicerSelector
        threemfDiskPath={threemfDiskPath}
        downloadUrl={downloadUrl}
        canSubmit={canSubmit}
        onAutoGenerate={async () => {
          await submitFullPipeline();
          return useConverterStore.getState().threemfDiskPath ?? null;
        }}
      />
    </div>
  );
}
