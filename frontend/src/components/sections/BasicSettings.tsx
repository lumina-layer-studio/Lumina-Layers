import { useRef, useEffect } from "react";
import { useShallow } from "zustand/react/shallow";
import { useConverterStore, ACCEPT_IMAGE_FORMATS } from "../../stores/converterStore";
import {
  ColorMode,
  ModelingMode,
  StructureMode,
} from "../../api/types";
import UnifiedUploader from "../ui/UnifiedUploader";
import Checkbox from "../ui/Checkbox";
import Dropdown from "../ui/Dropdown";
import Slider from "../ui/Slider";
import RadioGroup from "../ui/RadioGroup";
import { CropModal } from "../ui/CropModal";
import type { CropData } from "../ui/CropModal";
import { useI18n } from "../../i18n/context";

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
    imageFile,
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
    imageFile: s.imageFile,
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
  const handleFilesSelect = useConverterStore((s) => s.handleFilesSelect);
  const setLutName = useConverterStore((s) => s.setLutName);
  const setTargetWidthMm = useConverterStore((s) => s.setTargetWidthMm);
  const setTargetHeightMm = useConverterStore((s) => s.setTargetHeightMm);
  const setSpacerThick = useConverterStore((s) => s.setSpacerThick);
  const setStructureMode = useConverterStore((s) => s.setStructureMode);
  const setModelingMode = useConverterStore((s) => s.setModelingMode);
  const setEnableCrop = useConverterStore((s) => s.setEnableCrop);
  const setCropModalOpen = useConverterStore((s) => s.setCropModalOpen);
  const submitCrop = useConverterStore((s) => s.submitCrop);
  const uploadLut = useConverterStore((s) => s.uploadLut);
  const removeBatchFile = useConverterStore((s) => s.removeBatchFile);

  const lutOptions = lutList.map((name) => ({ label: name, value: name }));

  const lutFileRef = useRef<HTMLInputElement>(null);

  // 5-Color Extended 模式下强制锁定为单面（浮雕）
  const isFiveColorExt = color_mode === ColorMode.FIVE_COLOR_EXT;
  useEffect(() => {
    if (isFiveColorExt && structure_mode === StructureMode.DOUBLE_SIDED) {
      setStructureMode(StructureMode.SINGLE_SIDED);
    }
  }, [isFiveColorExt, structure_mode, setStructureMode]);

  const handleLutUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await uploadLut(file);
    // Reset so same file can be re-uploaded
    if (lutFileRef.current) lutFileRef.current.value = "";
  };

  const handleCropConfirm = (data: CropData) => {
    void submitCrop(data.x, data.y, data.width, data.height);
  };

  return (
    <div className="flex flex-col gap-4">
      <UnifiedUploader
        singlePreview={imagePreviewUrl ?? undefined}
        batchFiles={batchFiles}
        isBatchMode={batchMode}
        onFilesSelect={handleFilesSelect}
        onBatchFileRemove={removeBatchFile}
        accept={ACCEPT_IMAGE_FORMATS}
      />

      {batchFiles.length === 0 && imageFile !== null && (
        <>
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

      <div className="flex items-end gap-2">
        <div className="flex-1">
          <Dropdown
            label={t("basic_lut_label")}
            value={lut_name}
            options={lutOptions}
            onChange={setLutName}
            placeholder={t("basic_lut_placeholder")}
          />
        </div>
        <input
          ref={lutFileRef}
          type="file"
          accept=".npy,.json,.npz"
          className="hidden"
          onChange={(e) => void handleLutUpload(e)}
        />
        <button
          type="button"
          onClick={() => lutFileRef.current?.click()}
          className="px-3 py-2 text-xs rounded-md border border-gray-300 dark:border-gray-600 bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors whitespace-nowrap"
          title={t("basic_lut_upload")}
        >
          📁 {t("basic_lut_upload")}
        </button>
      </div>

      {lut_name && (
        <div className="text-xs text-gray-500 -mt-2 px-1">
          {t("basic_color_mode_label")}: {color_mode}
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
        disabledValues={isFiveColorExt ? [StructureMode.DOUBLE_SIDED] : []}
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
