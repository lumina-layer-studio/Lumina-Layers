import { useExtractorStore } from "../stores/extractorStore";
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
  const mergeTitle = is5c ? "5色扩展双页合并" : "8色双页合并";
  const mergeLabel = is5c ? "合并 5 色 LUT" : "合并 8 色 LUT";

  const extractDisabled =
    imageFile === null || corner_points.length < 4 || isLoading;

  return (
    <aside
      data-testid="extractor-panel"
      className="w-[350px] h-full overflow-y-auto bg-white dark:bg-gray-800 p-4 flex flex-col gap-4"
    >
      {/* 颜色模式 */}
      <div data-testid="color-mode-select">
        <Dropdown
          label="颜色模式"
          value={color_mode}
          options={colorModeOptions}
          onChange={(v) => setColorMode(v as ExtractorColorMode)}
        />
      </div>

      {/* 页码 - 8-Color Max 和 5-Color Extended 模式显示 */}
      {isMultiPage && (
        <div data-testid="page-select">
          <Dropdown
            label="页码"
            value={page}
            options={pageOptions}
            onChange={(v) => setPage(v as ExtractorPage)}
          />
        </div>
      )}

      {/* 图片上传 */}
      <div data-testid="image-upload">
        <label className="text-sm text-gray-700 dark:text-gray-300 mb-1 block">上传校准板照片</label>
        <ImageUpload
          onFileSelect={(file) => setImageFile(file)}
          accept="image/*"
          preview={imagePreviewUrl ?? undefined}
        />
      </div>

      {/* 参数 Sliders */}
      <Slider
        label="水平偏移 (offset_x)"
        value={offset_x}
        min={-30}
        max={30}
        step={1}
        onChange={setOffsetX}
      />
      <Slider
        label="垂直偏移 (offset_y)"
        value={offset_y}
        min={-30}
        max={30}
        step={1}
        onChange={setOffsetY}
      />
      <Slider
        label="缩放 (zoom)"
        value={zoom}
        min={0.8}
        max={1.2}
        step={0.01}
        onChange={setZoom}
      />
      <Slider
        label="畸变校正 (distortion)"
        value={distortion}
        min={-0.2}
        max={0.2}
        step={0.01}
        onChange={setDistortion}
      />

      {/* 布尔开关 */}
      <Checkbox
        label="白平衡校正"
        checked={white_balance}
        onChange={setWhiteBalance}
      />
      <Checkbox
        label="暗角校正"
        checked={vignette_correction}
        onChange={setVignetteCorrection}
      />

      {/* 操作按钮 */}
      <div data-testid="extract-button">
        <Button
          label="提取颜色"
          variant="primary"
          onClick={() => void submitExtract()}
          disabled={extractDisabled}
          loading={isLoading}
        />
      </div>
      <div data-testid="clear-corners-button">
        <Button
          label="清除角点"
          variant="secondary"
          onClick={clearCornerPoints}
        />
      </div>

      {/* 双页模式：页面提取状态 + 合并按钮 */}
      {isMultiPage && (
        <div data-testid="merge-section" className="flex flex-col gap-2 border border-gray-200 dark:border-gray-700 rounded-md p-3">
          <span className="text-xs text-gray-500 dark:text-gray-400">{mergeTitle}</span>
          <div className="flex gap-2 text-xs">
            <span className={p1Done ? "text-green-600 dark:text-green-400" : "text-gray-400 dark:text-gray-500"}>
              Page 1: {p1Done ? "已提取" : "未提取"}
            </span>
            <span className={p2Done ? "text-green-600 dark:text-green-400" : "text-gray-400 dark:text-gray-500"}>
              Page 2: {p2Done ? "已提取" : "未提取"}
            </span>
          </div>
          <Button
            label={mergeLabel}
            variant="primary"
            onClick={() => void submitMerge()}
            disabled={!p1Done || !p2Done || mergeLoading}
            loading={mergeLoading}
          />
          {mergeError && (
            <p className="text-xs text-red-400">{mergeError}</p>
          )}
        </div>
      )}

      {/* 错误信息 */}
      {error && (
        <p data-testid="error-message" className="text-xs text-red-400">
          {error}
        </p>
      )}

      {/* LUT 下载链接 - 提取完成后显示 */}
      {lut_download_url && (
        <a
          data-testid="lut-download-link"
          href={lut_download_url}
          download
          className="text-sm text-blue-400 underline hover:text-blue-300"
        >
          下载 LUT 文件 (.npy)
        </a>
      )}

      {/* 手动修正提示 */}
      {lut_download_url && (
        <div data-testid="manual-fix-section" className="text-xs text-gray-500 dark:text-gray-500 border border-gray-200 dark:border-gray-700 rounded-md p-2">
          点击右侧 LUT 预览图中的色块可手动修正颜色
        </div>
      )}

      {/* 手动修正错误 */}
      {manualFixError && (
        <p data-testid="manual-fix-error" className="text-xs text-red-400">
          {manualFixError}
        </p>
      )}
    </aside>
  );
}
