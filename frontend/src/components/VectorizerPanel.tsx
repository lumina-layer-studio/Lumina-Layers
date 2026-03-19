import { useCallback } from "react";
import { motion } from "framer-motion";
import { useShallow } from "zustand/react/shallow";
import { useI18n } from "../i18n/context";
import { useVectorizerStore } from "../stores/vectorizerStore";
import { usePanZoom } from "../hooks/usePanZoom";
import ImageUpload from "./ui/ImageUpload";
import Slider from "./ui/Slider";
import Checkbox from "./ui/Checkbox";
import Switch from "./ui/Switch";
import Button from "./ui/Button";
import Accordion from "./ui/Accordion";
import ZoomViewport from "./ui/ZoomViewport";

const ACCEPT_FORMATS = "image/png,image/jpeg,image/webp,image/bmp";

export default function VectorizerPanel() {
  const { t } = useI18n();

  const {
    imagePreviewUrl,
    params,
    isProcessing,
    error,
    result,
  } = useVectorizerStore(
    useShallow((s) => ({
      imagePreviewUrl: s.imagePreviewUrl,
      params: s.params,
      isProcessing: s.isProcessing,
      error: s.error,
      result: s.result,
    })),
  );

  const setImageFile = useVectorizerStore((s) => s.setImageFile);
  const setParam = useVectorizerStore((s) => s.setParam);
  const submit = useVectorizerStore((s) => s.submit);
  const cancel = useVectorizerStore((s) => s.cancel);

  const compareZoom = usePanZoom();

  const handleFileSelect = useCallback(
    (file: File) => setImageFile(file),
    [setImageFile],
  );

  const handleSubmit = useCallback(() => {
    if (isProcessing) {
      cancel();
    } else {
      submit();
    }
  }, [isProcessing, cancel, submit]);

  const svgUrl = result?.svg_url ?? null;

  const handleDownload = useCallback(() => {
    if (!svgUrl) return;
    const a = document.createElement("a");
    a.href = svgUrl;
    a.download = "vectorized.svg";
    a.click();
  }, [svgUrl]);

  const isDetailEnabled = params.detail_level >= 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", damping: 25, stiffness: 300 }}
      className="w-full max-w-4xl mx-auto h-full overflow-y-auto p-6"
    >
      <div className="bg-white/85 dark:bg-gray-900/85 backdrop-blur-2xl border border-white/40 dark:border-gray-700/50 shadow-2xl rounded-2xl p-6 flex flex-col gap-5">
        {/* Title */}
        <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-100">
          {t("vec.title")}
        </h2>

        {/* Upload */}
        <ImageUpload
          onFileSelect={handleFileSelect}
          accept={ACCEPT_FORMATS}
          preview={imagePreviewUrl ?? undefined}
        />

        {/* ===== Basic Parameters ===== */}
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-medium text-gray-600 dark:text-gray-400">
            {t("vec.basic_params")}
          </h3>

          {/* num_colors: Switch(Auto/Manual) + Slider */}
          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-700 dark:text-gray-300 cursor-help border-b border-dashed border-gray-400 dark:border-gray-500" title={t("vec.hint_num_colors")}>
              {t("vec.num_colors")}
            </span>
            <Switch
              checked={params.num_colors === 0}
              onChange={(v) => setParam("num_colors", v ? 0 : 16)}
              checkedLabel={t("vec.num_colors_auto")}
              uncheckedLabel={t("vec.num_colors_manual")}
            />
          </div>
          {params.num_colors > 0 && (
            <Slider
              label={t("vec.num_colors")}
              value={params.num_colors}
              min={2}
              max={256}
              step={1}
              onChange={(v) => setParam("num_colors", v)}
            />
          )}

          <Slider
            label={t("vec.smoothness")}
            tooltip={t("vec.hint_smoothness")}
            value={params.smoothness}
            min={0}
            max={1}
            step={0.01}
            onChange={(v) => setParam("smoothness", v)}
          />

          {/* detail_level: Switch(Enable/Disable) + Slider */}
          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-700 dark:text-gray-300 cursor-help border-b border-dashed border-gray-400 dark:border-gray-500" title={t("vec.hint_detail_level")}>
              {t("vec.detail_level")}
            </span>
            <Switch
              checked={isDetailEnabled}
              onChange={(v) => setParam("detail_level", v ? 0.5 : -1)}
              checkedLabel={t("vec.detail_level_on")}
              uncheckedLabel={t("vec.detail_level_off")}
            />
          </div>
          {isDetailEnabled && (
            <Slider
              label={t("vec.detail_level")}
              value={params.detail_level}
              min={0}
              max={1}
              step={0.01}
              onChange={(v) => setParam("detail_level", v)}
            />
          )}
        </div>

        {/* ===== Output Enhancement ===== */}
        <Accordion title={t("vec.output_enhance")}>
          <div className="flex flex-col gap-3 pt-1">
            <Checkbox
              label={t("vec.svg_enable_stroke")}
              tooltip={t("vec.hint_svg_enable_stroke")}
              checked={params.svg_enable_stroke}
              onChange={(v) => setParam("svg_enable_stroke", v)}
            />
            {params.svg_enable_stroke && (
              <Slider
                label={t("vec.svg_stroke_width")}
                tooltip={t("vec.hint_svg_stroke_width")}
                value={params.svg_stroke_width}
                min={0}
                max={20}
                step={0.1}
                onChange={(v) => setParam("svg_stroke_width", v)}
              />
            )}

            <Slider
              label={t("vec.thin_line_max_radius")}
              tooltip={t("vec.hint_thin_line_max_radius")}
              value={params.thin_line_max_radius}
              min={0.5}
              max={10}
              step={0.1}
              unit="px"
              onChange={(v) => setParam("thin_line_max_radius", v)}
            />

            <Checkbox
              label={t("vec.enable_coverage_fix")}
              tooltip={t("vec.hint_enable_coverage_fix")}
              checked={params.enable_coverage_fix}
              onChange={(v) => setParam("enable_coverage_fix", v)}
            />
            {params.enable_coverage_fix && (
              <Slider
                label={t("vec.min_coverage_ratio")}
                tooltip={t("vec.hint_min_coverage_ratio")}
                value={params.min_coverage_ratio}
                min={0}
                max={1}
                step={0.001}
                onChange={(v) => setParam("min_coverage_ratio", v)}
              />
            )}
          </div>
        </Accordion>

        {/* ===== Advanced Parameters ===== */}
        <Accordion title={t("vec.advanced_params")}>
          <div className="flex flex-col gap-1">
            {/* Preprocessing */}
            <Accordion title={t("vec.adv_preprocess")}>
              <div className="flex flex-col gap-3 pt-1">
                <Slider
                  label={t("vec.smoothing_spatial")}
                  tooltip={t("vec.hint_smoothing_spatial")}
                  value={params.smoothing_spatial}
                  min={0}
                  max={50}
                  step={0.5}
                  onChange={(v) => setParam("smoothing_spatial", v)}
                />
                <Slider
                  label={t("vec.smoothing_color")}
                  tooltip={t("vec.hint_smoothing_color")}
                  value={params.smoothing_color}
                  min={0}
                  max={80}
                  step={0.5}
                  onChange={(v) => setParam("smoothing_color", v)}
                />
                <Slider
                  label={t("vec.max_working_pixels")}
                  tooltip={t("vec.hint_max_working_pixels")}
                  value={params.max_working_pixels}
                  min={100000}
                  max={10000000}
                  step={100000}
                  onChange={(v) => setParam("max_working_pixels", v)}
                />
              </div>
            </Accordion>

            {/* Segmentation */}
            <Accordion title={t("vec.adv_segmentation")}>
              <div className="flex flex-col gap-3 pt-1">
                <Slider
                  label={t("vec.slic_region_size")}
                  tooltip={t("vec.hint_slic_region_size")}
                  value={params.slic_region_size}
                  min={5}
                  max={100}
                  step={1}
                  onChange={(v) => setParam("slic_region_size", v)}
                />
                <Slider
                  label={t("vec.edge_sensitivity")}
                  tooltip={t("vec.hint_edge_sensitivity")}
                  value={params.edge_sensitivity}
                  min={0}
                  max={1}
                  step={0.05}
                  onChange={(v) => setParam("edge_sensitivity", v)}
                />
                <Slider
                  label={t("vec.refine_passes")}
                  tooltip={t("vec.hint_refine_passes")}
                  value={params.refine_passes}
                  min={0}
                  max={20}
                  step={1}
                  onChange={(v) => setParam("refine_passes", v)}
                />
                <Checkbox
                  label={t("vec.enable_antialias_detect")}
                  tooltip={t("vec.hint_enable_antialias_detect")}
                  checked={params.enable_antialias_detect}
                  onChange={(v) => setParam("enable_antialias_detect", v)}
                />
                {params.enable_antialias_detect && (
                  <Slider
                    label={t("vec.aa_tolerance")}
                    tooltip={t("vec.hint_aa_tolerance")}
                    value={params.aa_tolerance}
                    min={1}
                    max={50}
                    step={1}
                    onChange={(v) => setParam("aa_tolerance", v)}
                  />
                )}
              </div>
            </Accordion>

            {/* Curve Fitting */}
            <Accordion title={t("vec.adv_curve_fitting")}>
              <div className="flex flex-col gap-3 pt-1">
                <Slider
                  label={t("vec.curve_fit_error")}
                  tooltip={t("vec.hint_curve_fit_error")}
                  value={params.curve_fit_error}
                  min={0.1}
                  max={5}
                  step={0.1}
                  unit="px"
                  onChange={(v) => setParam("curve_fit_error", v)}
                />
                <Slider
                  label={t("vec.contour_simplify")}
                  tooltip={t("vec.hint_contour_simplify")}
                  value={params.contour_simplify}
                  min={0}
                  max={2}
                  step={0.05}
                  onChange={(v) => setParam("contour_simplify", v)}
                />
                <Slider
                  label={t("vec.merge_segment_tolerance")}
                  tooltip={t("vec.hint_merge_segment_tolerance")}
                  value={params.merge_segment_tolerance}
                  min={0}
                  max={0.5}
                  step={0.01}
                  onChange={(v) => setParam("merge_segment_tolerance", v)}
                />
              </div>
            </Accordion>

            {/* Filtering */}
            <Accordion title={t("vec.adv_filtering")}>
              <div className="flex flex-col gap-3 pt-1">
                <Slider
                  label={t("vec.min_region_area")}
                  tooltip={t("vec.hint_min_region_area")}
                  value={params.min_region_area}
                  min={0}
                  max={1000}
                  step={1}
                  unit="px²"
                  onChange={(v) => setParam("min_region_area", v)}
                />
                <Slider
                  label={t("vec.max_merge_color_dist")}
                  tooltip={t("vec.hint_max_merge_color_dist")}
                  value={params.max_merge_color_dist}
                  min={0}
                  max={500}
                  step={10}
                  onChange={(v) => setParam("max_merge_color_dist", v)}
                />
                <Slider
                  label={t("vec.min_contour_area")}
                  tooltip={t("vec.hint_min_contour_area")}
                  value={params.min_contour_area}
                  min={0}
                  max={500}
                  step={1}
                  unit="px²"
                  onChange={(v) => setParam("min_contour_area", v)}
                />
                <Slider
                  label={t("vec.min_hole_area")}
                  tooltip={t("vec.hint_min_hole_area")}
                  value={params.min_hole_area}
                  min={0}
                  max={100}
                  step={0.5}
                  unit="px²"
                  onChange={(v) => setParam("min_hole_area", v)}
                />
              </div>
            </Accordion>
          </div>
        </Accordion>

        {/* Submit Button */}
        <Button
          label={isProcessing ? t("vec.processing") : t("vec.submit")}
          onClick={handleSubmit}
          loading={isProcessing}
          disabled={!imagePreviewUrl}
        />

        {/* Error */}
        {error && (
          <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-3">
            <p className="text-sm text-red-600 dark:text-red-400">
              {t("vec.error")}: {error}
            </p>
          </div>
        )}

        {/* Result */}
        {result && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
            className="flex flex-col gap-4"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-gray-600 dark:text-gray-400">
                {t("vec.result_title")}
              </h3>
              <button
                type="button"
                onClick={compareZoom.reset}
                className="rounded bg-gray-200 dark:bg-gray-700 px-2 py-1 text-xs text-gray-600 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-gray-600 transition-colors"
              >
                {t("zoom_reset")}
              </button>
            </div>

            {/* Synced side-by-side comparison */}
            <div className="grid grid-cols-2 gap-4">
              {/* Original */}
              <div className="flex flex-col gap-2">
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
                  {t("vec.original")}
                </span>
                <ZoomViewport
                  src={imagePreviewUrl ?? undefined}
                  alt="original"
                  scale={compareZoom.scale}
                  translate={compareZoom.translate}
                  zoom={compareZoom.zoom}
                  mouseHandlers={compareZoom.mouseHandlers}
                />
              </div>

              {/* SVG Preview */}
              <div className="flex flex-col gap-2">
                <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
                  {t("vec.svg_preview")}
                </span>
                <ZoomViewport
                  src={svgUrl ?? undefined}
                  alt="SVG result"
                  scale={compareZoom.scale}
                  translate={compareZoom.translate}
                  zoom={compareZoom.zoom}
                  mouseHandlers={compareZoom.mouseHandlers}
                />
              </div>
            </div>

            {/* Stats & Download */}
            <div className="flex items-center justify-between rounded-lg bg-gray-50 dark:bg-gray-800/60 border border-gray-200 dark:border-gray-700 px-4 py-3">
              <div className="flex items-center gap-6 text-sm text-gray-600 dark:text-gray-300">
                <span>
                  {t("vec.shapes")}: <strong>{result.num_shapes}</strong>
                </span>
                <span>
                  {t("vec.colors")}: <strong>{result.num_colors}</strong>
                </span>
                <span>
                  {result.width} x {result.height} px
                </span>
              </div>

              {/* Palette swatches */}
              {result.palette.length > 0 && (
                <div className="flex items-center gap-1">
                  {result.palette.slice(0, 16).map((hex, i) => (
                    <div
                      key={i}
                      className="w-4 h-4 rounded-sm border border-gray-300 dark:border-gray-600"
                      style={{ backgroundColor: hex }}
                      title={hex}
                    />
                  ))}
                  {result.palette.length > 16 && (
                    <span className="text-xs text-gray-400 ml-1">
                      +{result.palette.length - 16}
                    </span>
                  )}
                </div>
              )}
            </div>

            <Button
              label={t("vec.download_svg")}
              onClick={handleDownload}
              variant="secondary"
            />
          </motion.div>
        )}
      </div>
    </motion.div>
  );
}
