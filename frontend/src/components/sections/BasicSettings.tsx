import { useShallow } from "zustand/react/shallow";
import { useConverterStore, isValidImageType } from "../../stores/converterStore";
import {
  ModelingMode,
  StructureMode,
} from "../../api/types";
import ImageUpload from "../ui/ImageUpload";
import BatchFileUploader from "../ui/BatchFileUploader";
import Checkbox from "../ui/Checkbox";
import Dropdown from "../ui/Dropdown";
import Slider from "../ui/Slider";
import RadioGroup from "../ui/RadioGroup";
import { CropModal } from "../ui/CropModal";
import type { CropData } from "../ui/CropModal";
import { useI18n } from "../../i18n/context";
import ColorModeBadge from "../ui/ColorModeBadge";

export default function BasicSettings() {
  const { t } = useI18n();

  const structureModeOptions = Object.values(StructureMode).map((v) => ({
    label: t(`structure_mode.${v}`),
    value: v,
  }));

  const modelingModeOptions = Object.values(ModelingMode).map((v) => ({
    label: t(`modeling_mode.${v}`),
    value: v,
  }));
  // 状态字段使用 useShallow 分组提取，避免无关字段变化触发重渲染
  const {
    imagePreviewUrl,
    lut_name,
    lutList,
    color_mode,
    target_width_mm,
    target_height_mm,
    spacer_thick,
    structure_mode,
    modeling_mode,
    enable_relief,
    enableCrop,
    cropModalOpen,
    isCropping,
    batchMode,
    batchFiles,
  } = useConverterStore(useShallow((s) => ({
    imagePreviewUrl: s.imagePreviewUrl,
    lut_name: s.lut_name,
    lutList: s.lutList,
    color_mode: s.color_mode,
    target_width_mm: s.target_width_mm,
    target_height_mm: s.target_height_mm,
    spacer_thick: s.spacer_thick,
    structure_mode: s.structure_mode,
    modeling_mode: s.modeling_mode,
    enable_relief: s.enable_relief,
    enableCrop: s.enableCrop,
    cropModalOpen: s.cropModalOpen,
    isCropping: s.isCropping,
    batchMode: s.batchMode,
    batchFiles: s.batchFiles,
  })));

  // Action 函数单独提取（函数引用稳定，不需要 shallow）
  const setImageFile = useConverterStore((s) => s.setImageFile);
  const setLutName = useConverterStore((s) => s.setLutName);
  const setTargetWidthMm = useConverterStore((s) => s.setTargetWidthMm);
  const setTargetHeightMm = useConverterStore((s) => s.setTargetHeightMm);
  const setSpacerThick = useConverterStore((s) => s.setSpacerThick);
  const setStructureMode = useConverterStore((s) => s.setStructureMode);
  const setModelingMode = useConverterStore((s) => s.setModelingMode);
  const setEnableCrop = useConverterStore((s) => s.setEnableCrop);
  const setCropModalOpen = useConverterStore((s) => s.setCropModalOpen);
  const submitCrop = useConverterStore((s) => s.submitCrop);
  const setError = useConverterStore((s) => s.setError);
  const setBatchMode = useConverterStore((s) => s.setBatchMode);
  const addBatchFiles = useConverterStore((s) => s.addBatchFiles);
  const removeBatchFile = useConverterStore((s) => s.removeBatchFile);

  const lutOptions = lutList.map((name) => ({ label: name, value: name }));

  const handleFileSelect = (file: File) => {
    if (!isValidImageType(file.type)) {
      setError(t("basic_image_format_error"));
      return;
    }
    setImageFile(file);
  };

  const handleCropConfirm = (data: CropData) => {
    void submitCrop(data.x, data.y, data.width, data.height);
  };

  return (
    <div className="flex flex-col gap-4">
      <Checkbox
        label={t("basic_batch_mode")}
        checked={batchMode}
        onChange={setBatchMode}
      />

      {batchMode ? (
        <BatchFileUploader
          files={batchFiles}
          onFilesAdd={addBatchFiles}
          onFileRemove={removeBatchFile}
          accept="image/jpeg,image/png,image/svg+xml"
        />
      ) : (
        <>
          <ImageUpload
            onFileSelect={handleFileSelect}
            accept="image/jpeg,image/png,image/svg+xml"
            preview={imagePreviewUrl ?? undefined}
          />

          <Checkbox
            label={t("basic_crop_after_upload")}
            checked={enableCrop}
            onChange={setEnableCrop}
          />

          <CropModal
            open={cropModalOpen}
            imageSrc={imagePreviewUrl ?? ""}
            onConfirm={handleCropConfirm}
            onUseOriginal={() => setCropModalOpen(false)}
            onClose={() => setCropModalOpen(false)}
            isLoading={isCropping}
          />
        </>
      )}

      <Dropdown
        label={t("basic_lut_label")}
        value={lut_name}
        options={lutOptions}
        onChange={setLutName}
        placeholder={t("basic_lut_placeholder")}
      />

      {lut_name && color_mode && (
        <div className="flex items-center gap-1.5 -mt-2 px-1">
          <span className="text-xs text-gray-500">{t("basic_color_mode_label")}:</span>
          <ColorModeBadge mode={color_mode} />
        </div>
      )}

      <Slider
        label={t("basic_width")}
        value={target_width_mm}
        min={10}
        max={400}
        step={1}
        unit="mm"
        onChange={setTargetWidthMm}
      />

      <Slider
        label={t("basic_height")}
        value={target_height_mm}
        min={10}
        max={400}
        step={1}
        unit="mm"
        onChange={setTargetHeightMm}
      />

      <Slider
        label={t("basic_thickness")}
        value={spacer_thick}
        min={0.2}
        max={3.5}
        step={0.08}
        unit="mm"
        onChange={setSpacerThick}
      />

      <RadioGroup
        label={t("basic_structure_mode")}
        value={structure_mode}
        options={structureModeOptions}
        onChange={(v) => setStructureMode(v as StructureMode)}
        disabled={enable_relief}
      />

      <RadioGroup
        label={t("basic_modeling_mode")}
        value={modeling_mode}
        options={modelingModeOptions}
        onChange={(v) => setModelingMode(v as ModelingMode)}
      />
    </div>
  );
}
