import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { useShallow } from "zustand/react/shallow";
import { useI18n } from "../i18n/context";
import { useVectorizerStore } from "../stores/vectorizerStore";
import { useConverterStore } from "../stores/converter";
import { useWidgetStore } from "../stores/widgetStore";
import { usePanZoom } from "../hooks/usePanZoom";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import {
  apiErrorToVisibleMessage,
  buildApiResourceUrl,
  downloadResourceBlob,
} from "../api/client";
import ImageUpload from "./ui/ImageUpload";
import Slider from "./ui/Slider";
import Checkbox from "./ui/Checkbox";
import Switch from "./ui/Switch";
import Button from "./ui/Button";
import Accordion from "./ui/Accordion";
import ZoomViewport from "./ui/ZoomViewport";
import { cx, resolvePanelSurfaceClass, resolveSectionCardClass } from "./ui/panelPrimitives";
import HelpDot from "./ui/HelpDot";
import { WIKI_DOCS } from "../utils/wikiDocs";

const ACCEPT_FORMATS = "image/png,image/jpeg,image/webp,image/bmp";

function toVisibleErrorMessage(error: unknown, fallback: string): string {
  return apiErrorToVisibleMessage(error, fallback);
}

/**
 * Build full URL from a relative API file path.
 * In dev mode (frontend :5173, backend :8000), apiClient.defaults.baseURL
 * points to the backend origin, so we prepend it to ensure correct resolution.
 */
export function buildFileUrl(relativePath: string): string {
  return buildApiResourceUrl(relativePath);
}

export default function VectorizerPanel() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();

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
  const [isDownloading, setIsDownloading] = useState(false);
  const [resultActionError, setResultActionError] = useState<string | null>(null);

  useEffect(() => {
    setResultActionError(null);
  }, [svgUrl]);

  const handleDownload = useCallback(async () => {
    if (!svgUrl) return;
    setIsDownloading(true);
    setResultActionError(null);
    let objectUrl: string | null = null;
    try {
      const blob = await downloadResourceBlob(buildFileUrl(svgUrl));
      objectUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objectUrl;
      a.download = "vectorized.svg";
      a.style.display = "none";
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (err) {
      setResultActionError(toVisibleErrorMessage(err, t("vec.resource_action_failed")));
    } finally {
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
      setIsDownloading(false);
    }
  }, [svgUrl, t]);

  const [isSending, setIsSending] = useState(false);
  const handleSendToConverter = useCallback(async () => {
    if (!svgUrl) return;
    setIsSending(true);
    setResultActionError(null);
    try {
      const blob = await downloadResourceBlob(buildFileUrl(svgUrl));
      const file = new File([blob], "vectorized.svg", { type: "image/svg+xml" });
      const converterStore = useConverterStore.getState();
      converterStore.loadVectorizedSvgIntoConverter(file);
      useWidgetStore.getState().setActiveTab("converter");
    } catch (err) {
      setResultActionError(toVisibleErrorMessage(err, t("vec.resource_action_failed")));
    } finally {
      setIsSending(false);
    }
  }, [svgUrl, t]);

  const isDetailEnabled = params.detail_level >= 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className={cx(resolvePanelSurfaceClass(workspace.mode), "flex flex-col gap-5")}
    >
      <div className={`mx-auto w-full ${workspace.isCompact ? "max-w-none" : "max-w-[96rem]"}`}>
        <div className="grid min-h-0 gap-5 xl:grid-cols-[minmax(22rem,30rem)_minmax(0,1fr)] xl:items-start">
            <div className="flex min-w-0 flex-col gap-5">

        {/* Upload */}
        <ImageUpload
          onFileSelect={handleFileSelect}
          accept={ACCEPT_FORMATS}
          preview={imagePreviewUrl ?? undefined}
        />

        {/* ===== Basic Parameters ===== */}
        <div className={cx(resolveSectionCardClass(workspace.mode), "flex flex-col gap-3")}>
          <h3 className="flex items-center gap-1.5 text-sm font-medium text-slate-500 dark:text-slate-400">
            <span>{t("vec.basic_params")}</span>
            <HelpDot
              title={t("vec.title")}
              description={t("vec.upload_hint")}
              wikiPath={WIKI_DOCS.vectorizerOverview}
            />
          </h3>

          {/* num_colors: Switch(Auto/Manual) + Slider */}
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 text-sm font-medium text-slate-700 dark:text-slate-200">
              {t("vec.num_colors")}
              <HelpDot title={t("vec.num_colors")} description={t("vec.hint_num_colors")} wikiPath={WIKI_DOCS.vectorizerColorAndDetail} />
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
            wikiPath={WIKI_DOCS.vectorizerColorAndDetail}
            value={params.smoothness}
            min={0}
            max={1}
            step={0.01}
            onChange={(v) => setParam("smoothness", v)}
          />

          {/* detail_level: Switch(Enable/Disable) + Slider */}
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 text-sm font-medium text-slate-700 dark:text-slate-200">
              {t("vec.detail_level")}
              <HelpDot title={t("vec.detail_level")} description={t("vec.hint_detail_level")} wikiPath={WIKI_DOCS.vectorizerColorAndDetail} />
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
              wikiPath={WIKI_DOCS.vectorizerOutputEnhancement}
              checked={params.svg_enable_stroke}
              onChange={(v) => setParam("svg_enable_stroke", v)}
            />
            {params.svg_enable_stroke && (
              <Slider
                label={t("vec.svg_stroke_width")}
                tooltip={t("vec.hint_svg_stroke_width")}
                wikiPath={WIKI_DOCS.vectorizerOutputEnhancement}
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
              wikiPath={WIKI_DOCS.vectorizerOutputEnhancement}
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
              wikiPath={WIKI_DOCS.vectorizerOutputEnhancement}
              checked={params.enable_coverage_fix}
              onChange={(v) => setParam("enable_coverage_fix", v)}
            />
            {params.enable_coverage_fix && (
              <Slider
                label={t("vec.min_coverage_ratio")}
                tooltip={t("vec.hint_min_coverage_ratio")}
                wikiPath={WIKI_DOCS.vectorizerOutputEnhancement}
                value={params.min_coverage_ratio}
                min={0}
                max={1}
                step={0.001}
                onChange={(v) => setParam("min_coverage_ratio", v)}
              />
            )}
          </div>
        </Accordion>

        {/* Submit Button */}
        <Button
          label={isProcessing ? t("vec.processing") : t("vec.submit")}
          onClick={handleSubmit}
          loading={isProcessing}
          disabled={!imagePreviewUrl}
          variant="primary"
        />

        {/* Error */}
        {error && (
          <div className="rounded-[22px] border border-red-200 bg-red-50 p-3 dark:border-red-800 dark:bg-red-900/20">
            <p className="text-sm text-red-600 dark:text-red-400">
              {t("vec.error")}: {error}
            </p>
          </div>
        )}

            </div>
            <div className="flex min-w-0 flex-col gap-5">

        {/* ===== Advanced Parameters ===== */}
        <Accordion title={t("vec.advanced_params")}>
          <div className="flex flex-col gap-1">
            {/* Preprocessing */}
            <Accordion title={t("vec.adv_preprocess")}>
              <div className="flex flex-col gap-3 pt-1">
                <Slider
                  label={t("vec.smoothing_spatial")}
                  tooltip={t("vec.hint_smoothing_spatial")}
                  wikiPath={WIKI_DOCS.vectorizerPreprocessing}
                  value={params.smoothing_spatial}
                  min={0}
                  max={50}
                  step={0.5}
                  onChange={(v) => setParam("smoothing_spatial", v)}
                />
                <Slider
                  label={t("vec.smoothing_color")}
                  tooltip={t("vec.hint_smoothing_color")}
                  wikiPath={WIKI_DOCS.vectorizerPreprocessing}
                  value={params.smoothing_color}
                  min={0}
                  max={80}
                  step={0.5}
                  onChange={(v) => setParam("smoothing_color", v)}
                />
                <Slider
                  label={t("vec.max_working_pixels")}
                  tooltip={t("vec.hint_max_working_pixels")}
                  wikiPath={WIKI_DOCS.vectorizerPreprocessing}
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
                  wikiPath={WIKI_DOCS.vectorizerSegmentation}
                  value={params.slic_region_size}
                  min={5}
                  max={100}
                  step={1}
                  onChange={(v) => setParam("slic_region_size", v)}
                />
                <Slider
                  label={t("vec.edge_sensitivity")}
                  tooltip={t("vec.hint_edge_sensitivity")}
                  wikiPath={WIKI_DOCS.vectorizerSegmentation}
                  value={params.edge_sensitivity}
                  min={0}
                  max={1}
                  step={0.05}
                  onChange={(v) => setParam("edge_sensitivity", v)}
                />
                <Slider
                  label={t("vec.refine_passes")}
                  tooltip={t("vec.hint_refine_passes")}
                  wikiPath={WIKI_DOCS.vectorizerSegmentation}
                  value={params.refine_passes}
                  min={0}
                  max={20}
                  step={1}
                  onChange={(v) => setParam("refine_passes", v)}
                />
                <Checkbox
                  label={t("vec.enable_antialias_detect")}
                  tooltip={t("vec.hint_enable_antialias_detect")}
                  wikiPath={WIKI_DOCS.vectorizerSegmentation}
                  checked={params.enable_antialias_detect}
                  onChange={(v) => setParam("enable_antialias_detect", v)}
                />
                {params.enable_antialias_detect && (
                  <Slider
                    label={t("vec.aa_tolerance")}
                    tooltip={t("vec.hint_aa_tolerance")}
                    wikiPath={WIKI_DOCS.vectorizerSegmentation}
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
                  wikiPath={WIKI_DOCS.vectorizerCurveAndFiltering}
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
                  wikiPath={WIKI_DOCS.vectorizerCurveAndFiltering}
                  value={params.contour_simplify}
                  min={0}
                  max={2}
                  step={0.05}
                  onChange={(v) => setParam("contour_simplify", v)}
                />
                <Slider
                  label={t("vec.merge_segment_tolerance")}
                  tooltip={t("vec.hint_merge_segment_tolerance")}
                  wikiPath={WIKI_DOCS.vectorizerCurveAndFiltering}
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
                  wikiPath={WIKI_DOCS.vectorizerCurveAndFiltering}
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
                  wikiPath={WIKI_DOCS.vectorizerCurveAndFiltering}
                  value={params.max_merge_color_dist}
                  min={0}
                  max={500}
                  step={10}
                  onChange={(v) => setParam("max_merge_color_dist", v)}
                />
                <Slider
                  label={t("vec.min_contour_area")}
                  tooltip={t("vec.hint_min_contour_area")}
                  wikiPath={WIKI_DOCS.vectorizerCurveAndFiltering}
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
                  wikiPath={WIKI_DOCS.vectorizerCurveAndFiltering}
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

        {/* Result */}
        {result && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, ease: "easeOut" }}
            className="flex flex-col gap-4"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400">
                {t("vec.result_title")}
              </h3>
              <button
                type="button"
                onClick={compareZoom.reset}
                className="action-control rounded-xl px-2.5 py-1 text-xs transition-colors"
              >
                {t("zoom_reset")}
              </button>
            </div>

            {/* Synced side-by-side comparison */}
            <div className={`grid grid-cols-1 gap-4 ${workspace.isWide ? "2xl:grid-cols-2" : ""}`}>
              {/* Original */}
              <div className="flex flex-col gap-2">
                <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
                  {t("vec.original")}
                </span>
                <ZoomViewport
                  src={imagePreviewUrl ?? undefined}
                  alt={t("vec.original")}
                  scale={compareZoom.scale}
                  translate={compareZoom.translate}
                  zoom={compareZoom.zoom}
                  mouseHandlers={compareZoom.mouseHandlers}
                />
              </div>

              {/* SVG Preview */}
              <div className="flex flex-col gap-2">
                <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
                  {t("vec.svg_preview")}
                </span>
                <ZoomViewport
                  src={svgUrl ?? undefined}
                  alt={t("vec.svg_preview")}
                  scale={compareZoom.scale}
                  translate={compareZoom.translate}
                  zoom={compareZoom.zoom}
                  mouseHandlers={compareZoom.mouseHandlers}
                />
              </div>
            </div>

            {/* Stats & Download */}
            <div className={`flex flex-col gap-3 rounded-[24px] border border-slate-200 bg-slate-100 px-4 py-3 dark:border-slate-700 dark:bg-slate-800/60 ${workspace.isWide ? "xl:flex-row xl:items-center xl:justify-between" : ""}`}>
              <div className={`text-sm text-slate-600 dark:text-slate-300 ${workspace.isCompact ? "grid gap-2" : "flex flex-wrap items-center gap-6"}`}>
                <span>
                  {t("vec.shapes")}: <strong>{result.num_shapes}</strong>
                </span>
                <span>
                  {t("vec.colors")}: <strong>{result.num_colors}</strong>
                </span>
                <span>
                  {result.width} × {result.height} {t("common_unit_px")}
                </span>
              </div>

              {/* Palette swatches */}
              {result.palette.length > 0 && (
                <div className="flex items-center gap-1">
                  {result.palette.slice(0, 16).map((hex, i) => (
                    <div
                      key={i}
                      className="h-4 w-4 rounded-md border border-slate-300 dark:border-slate-600"
                      style={{ backgroundColor: hex }}
                      title={hex}
                    />
                  ))}
                  {result.palette.length > 16 && (
                    <span className="text-xs text-slate-400 ml-1">
                      +{result.palette.length - 16}
                    </span>
                  )}
                </div>
              )}
            </div>

            <div className={`flex gap-3 ${workspace.isCompact ? "flex-col" : "flex-wrap"}`}>
              <Button
                label={t("vec.send_to_converter")}
                onClick={handleSendToConverter}
                loading={isSending}
                variant="primary"
              />
              <Button
                label={t("vec.download_svg")}
                onClick={handleDownload}
                loading={isDownloading}
                variant="secondary"
              />
            </div>
            {resultActionError && (
              <div
                role="alert"
                className="rounded-[18px] border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400"
              >
                {resultActionError}
              </div>
            )}
          </motion.div>
        )}
            </div>
          </div>
      </div>
    </motion.div>
  );
}
