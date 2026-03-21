import { useRef, useEffect, useMemo } from "react";
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
import Button from "../ui/Button";
import RadioGroup from "../ui/RadioGroup";
import { CropModal } from "../ui/CropModal";
import type { CropData } from "../ui/CropModal";
import { useI18n } from "../../i18n/context";
import { useWorkspaceMode } from "../../hooks/useWorkspaceMode";

const COLOR_MODE_DOTS: Record<string, string[]> = {
  [ColorMode.BW]: ["#000000", "#ffffff"],
  [ColorMode.FOUR_COLOR_RYBW]: ["#dc143c", "#ffe600", "#0064f0", "#ffffff"],
  [ColorMode.FOUR_COLOR_CMYW]: ["#0086d6", "#ec008c", "#f4ee2a", "#ffffff"],
  [ColorMode.FIVE_COLOR_EXT]: ["#ffffff", "#dc143c", "#ffe600", "#0064f0", "#141414"],
  [ColorMode.SIX_COLOR]: ["#ffffff", "#0086d6", "#ec008c", "#00ae42", "#f4ee2a", "#000000"],
  [ColorMode.SIX_COLOR_RYBW]: ["#ffffff", "#dc143c", "#ffe600", "#0064f0", "#00ae42", "#000000"],
  [ColorMode.EIGHT_COLOR]: [
    "#ffffff", "#0086d6", "#ec008c", "#f4ee2a",
    "#000000", "#c12e1f", "#0a2989", "#00ae42",
  ],
};

const DOT_CLS = "inline-block size-2 rounded-full shrink-0 ring-1 ring-black/10 dark:ring-white/20";

function ColorModeDots({ mode }: { mode: string }) {
  if (mode === ColorMode.MERGED) {
    return (
      <span
        className={`${DOT_CLS} animate-spin [animation-duration:3s]`}
        style={{
          background:
            "conic-gradient(#dc143c, #f4ee2a, #00ae42, #0086d6, #ec008c, #dc143c)",
        }}
      />
    );
  }

  const dots = COLOR_MODE_DOTS[mode];
  if (!dots) return null;

  return (
    <span className="inline-flex items-center gap-0.5">
      {dots.map((color, i) => (
        <span
          key={i}
          className={DOT_CLS}
          style={{ backgroundColor: color }}
        />
      ))}
    </span>
  );
}

export default function BasicSettings() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();

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
    largeFormatEnabled,
    tileWidthMm,
    tileHeightMm,
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
    largeFormatEnabled: s.largeFormatEnabled,
    tileWidthMm: s.tileWidthMm,
    tileHeightMm: s.tileHeightMm,
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
  const setLargeFormatEnabled = useConverterStore((s) => s.setLargeFormatEnabled);
  const setTileWidthMm = useConverterStore((s) => s.setTileWidthMm);
  const setTileHeightMm = useConverterStore((s) => s.setTileHeightMm);

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

  const dimMax = largeFormatEnabled ? 9999 : 400;

  const tileGrid = useMemo(() => {
    if (!largeFormatEnabled) return null;
    const cols = Math.max(1, Math.ceil(target_width_mm / tileWidthMm));
    const rows = Math.max(1, Math.ceil(target_height_mm / tileHeightMm));
    const lastW = Math.round(target_width_mm - (cols - 1) * tileWidthMm);
    const lastH = Math.round(target_height_mm - (rows - 1) * tileHeightMm);
    return { cols, rows, total: cols * rows, lastW, lastH };
  }, [largeFormatEnabled, target_width_mm, target_height_mm, tileWidthMm, tileHeightMm]);

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

      <div className={`gap-2 ${workspace.isCompact ? "grid grid-cols-1" : "flex items-end"}`}>
        <div className="min-w-0 flex-1">
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
        <Button
          label={`+ ${t("basic_lut_upload")}`}
          variant="secondary"
          onClick={() => lutFileRef.current?.click()}
          className={workspace.isCompact ? "w-full px-3" : "shrink-0 whitespace-nowrap px-3"}
        />
      </div>

      {lut_name && (
        <div className="-mt-2 px-1 text-xs text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
          <span>{t("basic_color_mode_label")}:</span>
          <ColorModeDots mode={color_mode} />
          <span>{color_mode}</span>
        </div>
      )}

      <Slider
        label={t("basic_width")}
        value={target_width_mm}
        min={10}
        max={dimMax}
        step={1}
        unit="mm"
        onChange={setTargetWidthMm}
      />

      <Slider
        label={t("basic_height")}
        value={target_height_mm}
        min={10}
        max={dimMax}
        step={1}
        unit="mm"
        onChange={setTargetHeightMm}
      />

      <Checkbox
        label={t("basic_large_format")}
        checked={largeFormatEnabled}
        onChange={setLargeFormatEnabled}
        tooltip={t("basic_large_format_hint")}
      />

      {largeFormatEnabled && (
        <div className="flex flex-col gap-3 rounded-lg border border-slate-200/60 bg-slate-100/50 p-3 dark:border-slate-700/40 dark:bg-slate-900/40">
          <Slider
            label={t("basic_tile_width")}
            value={tileWidthMm}
            min={50}
            max={500}
            step={10}
            unit="mm"
            onChange={setTileWidthMm}
          />
          <Slider
            label={t("basic_tile_height")}
            value={tileHeightMm}
            min={50}
            max={500}
            step={10}
            unit="mm"
            onChange={setTileHeightMm}
          />
          {tileGrid && (
            <div className="-mt-1 px-1 text-xs text-slate-500 dark:text-slate-400">
              {tileGrid.cols}×{tileGrid.rows} = {tileGrid.total}
              {tileGrid.total > 1 && (tileGrid.lastW !== tileWidthMm || tileGrid.lastH !== tileHeightMm)
                ? ` (${tileGrid.lastW}×${tileGrid.lastH}mm)`
                : ""}
            </div>
          )}
        </div>
      )}

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
