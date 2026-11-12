import { motion } from "framer-motion";
import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";

import { useWorkspaceMode } from "../../hooks/useWorkspaceMode";
import { useI18n } from "../../i18n/context";
import {
  selectWorkbenchCombo,
  useMaterialWorkbenchStore,
  workbenchComboKey,
} from "../../stores/materialWorkbenchStore";
import { LutColorDistributionCharts } from "../LutDetailsPanel";
import Button from "../ui/Button";
import {
  PanelIntro,
  StatusBanner,
  cardDividerClass,
  cardPadClass,
  desktopPrimaryColumnClass,
  desktopSecondaryColumnClass,
  groupHeaderClass,
  resolveDesktopSplitLayoutClass,
  resolvePanelSurfaceClass,
} from "../ui/panelPrimitives";
import GamutResultSummary from "./GamutResultSummary";
import MaterialComboControls from "./MaterialComboControls";
import MaterialContributionList from "./MaterialContributionList";
import { useGamutCoverage } from "./useGamutCoverage";
import { useSeedWorkbenchFromConverter } from "./useSeedWorkbenchFromConverter";

/**
 * Material > Gamut Coverage: sRGB coverage, per-layer caps, per-material
 * contributions, and the color-distribution charts of one combination.
 *
 * 耗材 > 色域覆盖：单个组合的 sRGB 覆盖率、逐层数上限、逐耗材贡献与色彩分布图。
 */
export default function MaterialGamutPanel() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();
  useSeedWorkbenchFromConverter();
  const combo = useMaterialWorkbenchStore(useShallow(selectWorkbenchCombo));
  const gamut = useGamutCoverage();
  const comboKey = useMemo(() => workbenchComboKey(combo), [combo]);

  const hasMaterials = combo.materialDirectoryNames.length > 0;
  const isStale = gamut.coverage !== null && gamut.resultKey !== comboKey;

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      data-testid="material-gamut-panel"
      className={`${resolvePanelSurfaceClass(workspace.mode)} flex flex-col gap-5`}
    >
      <PanelIntro title={t("material_gamut_title")} description={t("material_gamut_description")} />
      <div className={resolveDesktopSplitLayoutClass(workspace.mode)}>
        <div className={desktopPrimaryColumnClass}>
          <MaterialComboControls disabled={gamut.coverageLoading} />
          {!hasMaterials ? (
            <StatusBanner tone="info">{t("material_workbench_empty_hint")}</StatusBanner>
          ) : null}
          {combo.layerMode === "dynamic" && hasMaterials ? (
            <StatusBanner tone="info">{t("material_gamut_dynamic_first_run_hint")}</StatusBanner>
          ) : null}
          <Button
            label={t(gamut.coverageLoading ? "material_gamut_calculating" : "material_gamut_calculate")}
            variant="primary"
            disabled={!hasMaterials}
            loading={gamut.coverageLoading}
            onClick={() => void gamut.calculate(combo)}
            className="w-full"
          />
        </div>

        <div className={desktopSecondaryColumnClass}>
          {gamut.coverageError ? (
            <StatusBanner tone="error" data-testid="material-gamut-error">
              {gamut.coverageError}
            </StatusBanner>
          ) : null}
          {isStale ? <StatusBanner tone="warning">{t("material_gamut_stale_hint")}</StatusBanner> : null}
          {gamut.coverage ? (
            <>
              <section className={`${cardPadClass} flex flex-col gap-5`}>
                <GamutResultSummary result={gamut.coverage} />
                <div className={`${cardDividerClass} pt-4`}>
                  <MaterialContributionList
                    data={gamut.contributions}
                    loading={gamut.contributionsLoading}
                    error={gamut.contributionsError}
                  />
                </div>
              </section>
              <section className={`${cardPadClass} flex flex-col gap-3`}>
                <p className={groupHeaderClass}>{t("material_gamut_charts_header")}</p>
                <LutColorDistributionCharts source={gamut.coverage} workspaceMode={workspace.mode} />
              </section>
            </>
          ) : (
            <section className={cardPadClass} data-testid="material-gamut-empty-state">
              <p className="text-sm text-slate-500 dark:text-slate-400">{t("material_gamut_empty_state")}</p>
            </section>
          )}
        </div>
      </div>
    </motion.aside>
  );
}
