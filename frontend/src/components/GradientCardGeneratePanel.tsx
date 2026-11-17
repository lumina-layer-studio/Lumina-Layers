import { useState, type MouseEvent } from "react";
import { motion } from "framer-motion";
import { useCalibrationStore } from "../stores/calibrationStore";
import { useI18n } from "../i18n/context";
import Dropdown from "./ui/Dropdown";
import Button from "./ui/Button";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { MATERIAL_PRESET_OPTIONS } from "../constants/materialPresets";
import {
  StatusBanner,
  resolvePanelSurfaceClass,
  cardPadClass,
  cardDividerClass,
  workstationInputClass,
} from "./ui/panelPrimitives";
import HelpDot from "./ui/HelpDot";
import { WIKI_DOCS } from "../utils/wikiDocs";
import { useWidgetStore } from "../stores/widgetStore";
import { useSingleStageStore } from "../stores/singleStageStore";

const singleStageLayerHeightOptions = [0.04, 0.08, 0.1].map((value) => ({
  label: `${value.toFixed(2)} mm`,
  value: value.toString(),
}));

export default function GradientCardGeneratePanel() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();
  const { materialName, materialBrand, setMaterialName, setMaterialBrand } = useSingleStageStore();
  const [linkError, setLinkError] = useState(false);
  const handleModelLink = (event: MouseEvent<HTMLAnchorElement>) => {
    const openModel = (window as Window & {
      electronAPI?: { openGradientModel?: (url: string) => Promise<unknown> };
    }).electronAPI?.openGradientModel;
    if (!openModel) return;
    event.preventDefault();
    setLinkError(false);
    void openModel(event.currentTarget.href).catch(() => setLinkError(true));
  };
  const {
    substrateId,
    substrateDisplayName,
    materialDefault,
    singleStageLayerHeightMm,
    lastSubmittedWorkflow,
    isLoading,
    error,
    downloadUrl,
    statusMessage,
    setSubstrateId,
    setSubstrateDisplayName,
    setMaterialDefault,
    setSingleStageLayerHeightMm,
    submitSingleStageGenerate,
  } = useCalibrationStore();

  return (
    <motion.aside
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      data-testid="gradient-card-generate-panel"
      className={`${resolvePanelSurfaceClass(workspace.mode)} flex flex-col gap-5`}
    >
      <div className="flex flex-col gap-6 w-full">
        <div className="grid w-full items-start gap-5 lg:grid-cols-[minmax(16rem,22rem)_minmax(0,1fr)]">
          <section className={`${cardPadClass} flex flex-col gap-4 min-w-0`}>
            <div>
              <h3 className="flex items-center gap-1.5 text-[15px] font-semibold text-slate-900 dark:text-slate-50">
                <span>{t("mat_gradient_generate_section_title")}</span>
                <HelpDot
                  title={t("mat_gradient_generate_section_title")}
                  description={t("mat_gradient_generate_section_desc")}
                  wikiPath={WIKI_DOCS.gradientCardGeneration}
                />
              </h3>
            </div>

            <div className="flex flex-col gap-4 flex-1">
              <label className="flex flex-col gap-2 text-sm text-slate-700 dark:text-slate-200">
                {t("mat_gradient_material_name_label")}
                <input value={materialName} onChange={(event) => setMaterialName(event.target.value)}
                  placeholder={t("material_guide_name_placeholder")} className={workstationInputClass} />
              </label>
              <label className="flex flex-col gap-2 text-sm text-slate-700 dark:text-slate-200">
                {t("mat_gradient_brand_label")}
                <input value={materialBrand} onChange={(event) => setMaterialBrand(event.target.value)}
                  placeholder={t("mat_gradient_brand_placeholder")} className={workstationInputClass} />
              </label>
              <Dropdown
                label={t("cal_single_stage_layer_height_label")}
                tooltip={t("mat_gradient_generate_section_desc")}
                wikiPath={WIKI_DOCS.gradientCardGeneration}
                value={singleStageLayerHeightMm.toString()}
                options={singleStageLayerHeightOptions}
                onChange={(value) =>
                  setSingleStageLayerHeightMm(Number.parseFloat(value))
                }
              />

              <div style={{ display: "none" }}>
                <label className="flex flex-col gap-1">
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                    {t("cal_substrate_id_label")}
                  </span>
                  <input
                    className={workstationInputClass}
                    value={substrateId}
                    onChange={(event) => setSubstrateId(event.target.value)}
                  />
                </label>
              </div>

              <div style={{ display: "none" }}>
                <label className="flex flex-col gap-1">
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                    {t("cal_substrate_name_label")}
                  </span>
                  <input
                    className={workstationInputClass}
                    value={substrateDisplayName}
                    onChange={(event) => setSubstrateDisplayName(event.target.value)}
                  />
                </label>
              </div>

              <div style={{ display: "none" }}>
                <Dropdown
                  label={t("cal_material_default_label")}
                  value={materialDefault}
                  options={[...MATERIAL_PRESET_OPTIONS]}
                  onChange={(value) => setMaterialDefault(value)}
                />
              </div>
            </div>

            <div className="pt-2">
              <Button
                label={t("mat_gradient_generate_btn")}
                variant="primary"
                onClick={() => void submitSingleStageGenerate()}
                disabled={isLoading}
                loading={isLoading}
                className="w-full"
              />
            </div>
          </section>

          <section className={`${cardPadClass} flex flex-col gap-4 min-w-0`}>
            <div>
              <h3 className="text-[15px] font-semibold text-slate-900 dark:text-slate-50">
                {t("mat_gradient_generate_notice_title")}
              </h3>
            </div>

            <div className="text-sm leading-6 text-slate-600 dark:text-slate-300">
              <p>{t("mat_gradient_generate_notice_dual_print")}</p>
              <p className="mt-2">{t("mat_gradient_generate_notice_config")}</p>
              <p className="mt-3">{t("mat_gradient_generate_notice_online_model")}</p>
              <div className={`${cardDividerClass} mt-4 flex flex-col gap-3 pt-4`}>
                <a
                  href="https://makerworld.com.cn/zh/models/2394753-lumina2-0-ti-xing-xiao-se-se-qia-0-08ceng-gao-15ce#profileId-2721317"
                  onClick={handleModelLink}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex max-w-full self-start items-center gap-2 text-sm font-medium text-blue-600 rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 transition-colors hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" /></svg>
                  {t("mat_gradient_generate_online_model_link")}
                </a>
                <a
                  href="https://makerworld.com.cn/zh/models/2400920-can-shu-hua-lumina-2-0ti-du-se-qia-zi-ding-yi-shou#profileId-2729620"
                  onClick={handleModelLink}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex max-w-full self-start items-center gap-2 text-sm font-medium text-blue-600 rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 transition-colors hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" /></svg>
                  {t("mat_gradient_generate_parametric_box_link")}
                </a>
              </div>
              {linkError && <StatusBanner tone="error" role="alert">{t("mat_gradient_model_open_error")}</StatusBanner>}
            </div>
          </section>
        </div>

        {lastSubmittedWorkflow === "single-stage" && (statusMessage || error || downloadUrl) && (
          <div className="flex flex-col gap-4">
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
              <section className={`${cardPadClass} flex flex-col gap-3`}>
                <div>
                  <h3 className="text-[15px] font-semibold text-slate-900 dark:text-slate-50">
                    {t("mat_gradient_download_title")}
                  </h3>
                  <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                    {t("mat_gradient_download_desc")}
                  </p>
                </div>
                <div className="flex flex-col gap-3 sm:flex-row mt-2">
                  <a
                    data-testid="download-link"
                    href={downloadUrl}
                    download
                    className="action-control action-control-primary inline-flex min-h-9 items-center justify-center rounded-lg px-4 py-2 text-sm font-medium"
                  >
                    <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>
                    {t("mat_gradient_download_btn")}
                  </a>
                  <Button label={t("material_guide_next_extract")}
                    onClick={() => useWidgetStore.getState().setActiveTab("gradient-card-extract")} />
                </div>
              </section>
            )}
          </div>
        )}
      </div>
    </motion.aside>
  );
}
