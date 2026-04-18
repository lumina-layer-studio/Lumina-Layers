import { useCalibrationStore } from "../stores/calibrationStore";
import { useI18n } from "../i18n/context";
import { CalibrationColorMode, BackingColor } from "../api/types";
import Dropdown from "./ui/Dropdown";
import Slider from "./ui/Slider";
import Button from "./ui/Button";

const colorModeOptions = Object.values(CalibrationColorMode).map((v) => ({
  label: v,
  value: v,
}));

const backingColorOptions = Object.values(BackingColor).map((v) => ({
  label: v,
  value: v,
}));

export default function CalibrationPanel() {
  const { t } = useI18n();
  const {
    color_mode,
    block_size,
    gap,
    backing,
    isLoading,
    error,
    downloadUrl,
    previewImageUrl,
    statusMessage,
    setColorMode,
    setBlockSize,
    setGap,
    setBacking,
    submitGenerate,
  } = useCalibrationStore();

  const isEightColor = color_mode === CalibrationColorMode.EIGHT_COLOR;
  const isFiveColorExt = color_mode === CalibrationColorMode.FIVE_COLOR_EXT;
  const isSixColor = color_mode === CalibrationColorMode.SIX_COLOR;
  const blockSizeDisabled = isEightColor;
  const gapDisabled = isEightColor;
  const backingDisabled = isEightColor || isFiveColorExt || isSixColor;

  return (
    <aside
      data-testid="calibration-panel"
      className="w-full max-w-2xl mx-auto h-full overflow-y-auto bg-white dark:bg-gray-800 p-6 flex flex-col gap-4"
    >
      <Dropdown
        label={t("cal_color_mode_label")}
        value={color_mode}
        options={colorModeOptions}
        onChange={(v) => setColorMode(v as CalibrationColorMode)}
      />

      <Slider
        label={t("cal_block_size_label")}
        value={block_size}
        min={3}
        max={10}
        step={0.5}
        unit="mm"
        onChange={setBlockSize}
        disabled={blockSizeDisabled}
      />

      <Slider
        label={t("cal_gap_label")}
        value={gap}
        min={0.4}
        max={2.0}
        step={0.01}
        unit="mm"
        onChange={setGap}
        disabled={gapDisabled}
      />

      <Dropdown
        label={t("cal_backing_label")}
        value={backing}
        options={backingColorOptions}
        onChange={(v) => setBacking(v as BackingColor)}
        disabled={backingDisabled}
      />

      <Button
        label={t("cal_generate_btn")}
        variant="primary"
        onClick={() => void submitGenerate()}
        disabled={isLoading}
        loading={isLoading}
      />

      {statusMessage && (
        <p data-testid="status-message" className="text-xs text-green-400">
          {statusMessage}
        </p>
      )}

      {error && (
        <p data-testid="error-message" className="text-xs text-red-400">
          {error}
        </p>
      )}

      {downloadUrl && (
        <a
          data-testid="download-link"
          href={downloadUrl}
          download
          className="text-sm text-blue-400 underline hover:text-blue-300"
        >
          {t("cal_download_3mf")}
        </a>
      )}

      {previewImageUrl && (
        <img
          data-testid="preview-image"
          src={previewImageUrl}
          alt={t("cal_preview_alt")}
          className="w-full rounded-md border border-gray-700"
        />
      )}
    </aside>
  );
}
