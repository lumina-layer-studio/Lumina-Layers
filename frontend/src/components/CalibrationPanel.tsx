import { motion } from "framer-motion";
import { useCalibrationStore } from "../stores/calibrationStore";
import { useI18n } from "../i18n/context";
import { CalibrationColorMode, BackingColor } from "../api/types";
import Dropdown from "./ui/Dropdown";
import Slider from "./ui/Slider";
import Button from "./ui/Button";
import { PanelIntro, StatusBanner, centeredPanelClass, sectionCardClass } from "./ui/panelPrimitives";

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
  const isSixColor = color_mode === CalibrationColorMode.SIX_COLOR || color_mode === CalibrationColorMode.SIX_COLOR_RYBW;
  const blockSizeDisabled = isEightColor || isFiveColorExt;
  const gapDisabled = isEightColor || isFiveColorExt;
  const backingDisabled = isEightColor || isFiveColorExt || isSixColor;

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", damping: 25, stiffness: 300 }}
      data-testid="calibration-panel"
      className={`${centeredPanelClass} flex max-w-3xl flex-col gap-5`}
    >
      <PanelIntro
        eyebrow={t("tab.calibration")}
        title={t("cal_title")}
        description={t("cal_desc")}
      />

      <section className={`${sectionCardClass} flex flex-col gap-4`}>
        <div>
          <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("cal_params")}</h3>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t("cal_generate_btn")}</p>
        </div>
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
          label={t("cal_generate_btn_panel")}
          variant="primary"
          onClick={() => void submitGenerate()}
          disabled={isLoading}
          loading={isLoading}
          className="w-full"
        />
      </section>

      {statusMessage && (
        <StatusBanner data-testid="status-message" tone="success">
          {statusMessage}
        </StatusBanner>
      )}

      {error && (
        <StatusBanner data-testid="error-message" tone="error">
          {error}
        </StatusBanner>
      )}

      {downloadUrl && (
        <section className={`${sectionCardClass} flex items-center justify-between gap-3`}>
          <div>
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("cal_download")}</h3>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t("cal_status")}</p>
          </div>
          <a
            data-testid="download-link"
            href={downloadUrl}
            download
            className="inline-flex min-h-11 items-center justify-center rounded-2xl bg-blue-600 px-4 py-2.5 text-sm font-medium text-white shadow-[0_12px_24px_rgba(37,99,235,0.22)] transition-colors hover:bg-blue-700"
          >
            {t("cal_download_3mf")}
          </a>
        </section>
      )}

      {previewImageUrl && (
        <section className={`${sectionCardClass} flex flex-col gap-4`}>
          <div>
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("cal_preview")}</h3>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t("cal_preview_alt")}</p>
          </div>
          <img
            data-testid="preview-image"
            src={previewImageUrl}
            alt={t("cal_preview_alt")}
            className="w-full rounded-[24px] border border-slate-200/80 object-cover shadow-[var(--shadow-control)] dark:border-slate-700/80"
          />
        </section>
      )}
    </motion.aside>
  );
}
