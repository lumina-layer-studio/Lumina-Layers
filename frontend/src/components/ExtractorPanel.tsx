import { useExtractorStore } from "../stores/extractorStore";
import { useI18n } from "../i18n/context";
import { ExtractorColorMode, ExtractorPage } from "../api/types";
import Dropdown from "./ui/Dropdown";
import Slider from "./ui/Slider";
import Checkbox from "./ui/Checkbox";
import Button from "./ui/Button";
import ImageUpload from "./ui/ImageUpload";

const colorModeOptions = Object.values(ExtractorColorMode).map((v) => ({
  label: v,
  value: v,
}));

const pageOptions = Object.values(ExtractorPage).map((v) => ({
  label: v,
  value: v,
}));

export default function ExtractorPanel() {
  const { t } = useI18n();
  const {
    color_mode,
    page,
    imageFile,
    imagePreviewUrl,
    corner_points,
    offset_x,
    offset_y,
    zoom,
    distortion,
    white_balance,
    vignette_correction,
    isLoading,
    error,
    lut_download_url,
    manualFixError,
    page1Extracted,
    page2Extracted,
    page1Extracted_5c,
    page2Extracted_5c,
    mergeLoading,
    mergeError,
    setColorMode,
    setPage,
    setImageFile,
    setOffsetX,
    setOffsetY,
    setZoom,
    setDistortion,
    setWhiteBalance,
    setVignetteCorrection,
    submitExtract,
    submitMerge,
    clearCornerPoints,
  } = useExtractorStore();

  const isMultiPage =
    color_mode === ExtractorColorMode.EIGHT_COLOR ||
    color_mode === ExtractorColorMode.FIVE_COLOR_EXT;

  const is5c = color_mode === ExtractorColorMode.FIVE_COLOR_EXT;
  const p1Done = is5c ? page1Extracted_5c : page1Extracted;
  const p2Done = is5c ? page2Extracted_5c : page2Extracted;
  const mergeTitle = is5c ? t("ext_merge_5c_title") : t("ext_merge_8c_title");
  const mergeLabel = is5c ? t("ext_merge_5c_btn") : t("ext_merge_8c_btn");

  const extractDisabled =
    imageFile === null || corner_points.length < 4 || isLoading;

  return (
    <aside
      data-testid="extractor-panel"
      className="w-[400px] shrink-0 h-full overflow-y-auto bg-white dark:bg-gray-800 p-4 flex flex-col gap-4"
    >
      {/* 颜色模式 */}
      <div data-testid="color-mode-select">
        <Dropdown
          label={t("ext_color_mode_label")}
          value={color_mode}
          options={colorModeOptions}
          onChange={(v) => setColorMode(v as ExtractorColorMode)}
        />
      </div>

      {/* 页码 */}
      {isMultiPage && (
        <div data-testid="page-select">
          <Dropdown
            label={t("ext_page_label")}
            value={page}
            options={pageOptions}
            onChange={(v) => setPage(v as ExtractorPage)}
          />
        </div>
      )}

      {/* 图片上传 */}
      <div data-testid="image-upload">
        <label className="text-sm text-gray-700 dark:text-gray-300 mb-1 block">{t("ext_upload_label")}</label>
        <ImageUpload
          onFileSelect={(file) => setImageFile(file)}
          accept="image/*"
          preview={imagePreviewUrl ?? undefined}
        />
      </div>

      {/* 参数 Sliders */}
      <Slider label={t("ext_offset_x_label")} value={offset_x} min={-30} max={30} step={1} onChange={setOffsetX} />
      <Slider label={t("ext_offset_y_label")} value={offset_y} min={-30} max={30} step={1} onChange={setOffsetY} />
      <Slider label={t("ext_zoom_label")} value={zoom} min={0.8} max={1.2} step={0.01} onChange={setZoom} />
      <Slider label={t("ext_distortion_label")} value={distortion} min={-0.2} max={0.2} step={0.01} onChange={setDistortion} />

      {/* 布尔开关 */}
      <Checkbox label={t("ext_wb_label")} checked={white_balance} onChange={setWhiteBalance} />
      <Checkbox label={t("ext_vignette_label")} checked={vignette_correction} onChange={setVignetteCorrection} />

      {/* 操作按钮 */}
      <div data-testid="extract-button">
        <Button label={t("ext_extract_btn_label")} variant="primary" onClick={() => void submitExtract()} disabled={extractDisabled} loading={isLoading} />
      </div>
      <div data-testid="clear-corners-button">
        <Button label={t("ext_clear_corners")} variant="secondary" onClick={clearCornerPoints} />
      </div>

      {/* 双页模式：页面提取状态 + 合并按钮 */}
      {isMultiPage && (
        <div data-testid="merge-section" className="flex flex-col gap-2 border border-gray-200 dark:border-gray-700 rounded-md p-3">
          <span className="text-xs text-gray-500 dark:text-gray-400">{mergeTitle}</span>
          <div className="flex gap-2 text-xs">
            <span className={p1Done ? "text-green-600 dark:text-green-400" : "text-gray-400 dark:text-gray-500"}>
              Page 1: {p1Done ? t("ext_page_extracted") : t("ext_page_not_extracted")}
            </span>
            <span className={p2Done ? "text-green-600 dark:text-green-400" : "text-gray-400 dark:text-gray-500"}>
              Page 2: {p2Done ? t("ext_page_extracted") : t("ext_page_not_extracted")}
            </span>
          </div>
          <Button label={mergeLabel} variant="primary" onClick={() => void submitMerge()} disabled={!p1Done || !p2Done || mergeLoading} loading={mergeLoading} />
          {mergeError && <p className="text-xs text-red-400">{mergeError}</p>}
        </div>
      )}

      {/* 错误信息 */}
      {error && (
        <p data-testid="error-message" className="text-xs text-red-400">{error}</p>
      )}

      {/* LUT 下载链接 */}
      {lut_download_url && (
        <a
          data-testid="lut-download-link"
          href={lut_download_url}
          download
          className="text-sm text-blue-400 underline hover:text-blue-300"
        >
          {t("ext_download_lut")}
        </a>
      )}

      {/* 手动修正提示 */}
      {lut_download_url && (
        <div data-testid="manual-fix-section" className="text-xs text-gray-500 dark:text-gray-500 border border-gray-200 dark:border-gray-700 rounded-md p-2">
          {t("ext_manual_fix_hint")}
        </div>
      )}

      {/* 手动修正错误 */}
      {manualFixError && (
        <p data-testid="manual-fix-error" className="text-xs text-red-400">{manualFixError}</p>
      )}
    </aside>
  );
}
