import { useConverterStore } from "../../stores/converterStore";
import Button from "../ui/Button";
import BatchResultSummary from "../ui/BatchResultSummary";
import ZoomableImage from "../ui/ZoomableImage";
import BedSizeSelector from "./BedSizeSelector";
import SlicerSelector from "./SlicerSelector";

export default function ActionBar() {
  const imageFile = useConverterStore((s) => s.imageFile);
  const lut_name = useConverterStore((s) => s.lut_name);
  const isLoading = useConverterStore((s) => s.isLoading);
  const error = useConverterStore((s) => s.error);
  const previewImageUrl = useConverterStore((s) => s.previewImageUrl);
  const modelUrl = useConverterStore((s) => s.modelUrl);
  const submitPreview = useConverterStore((s) => s.submitPreview);
  const submitGenerate = useConverterStore((s) => s.submitGenerate);
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
            <p className="text-xs text-yellow-400">请先添加图片并选择 LUT</p>
          )}

          <div className="flex gap-2">
            <Button
              label="批量生成"
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
            <p className="text-xs text-yellow-400">请先上传图片并选择 LUT</p>
          )}

          <div className="flex gap-2">
            <Button
              label="预览"
              variant="secondary"
              onClick={submitPreview}
              disabled={!canSubmit || isLoading}
              loading={isLoading}
            />
            <Button
              label="生成"
              variant="primary"
              onClick={() => void submitGenerate()}
              disabled={!canSubmit || isLoading}
              loading={isLoading}
            />
          </div>
        </>
      )}

      {error && (
        <div className="text-xs text-red-400">{error}</div>
      )}

      <BedSizeSelector />

      {previewImageUrl && (
        <ZoomableImage
          src={previewImageUrl}
          alt="预览结果"
          className="w-full rounded-md border border-gray-700"
        />
      )}

      {(modelUrl || threemfDiskPath) && (
        <SlicerSelector
          threemfDiskPath={threemfDiskPath}
          downloadUrl={downloadUrl}
          onAutoGenerate={async () => {
            await submitGenerate();
            return useConverterStore.getState().threemfDiskPath ?? null;
          }}
        />
      )}
    </div>
  );
}
