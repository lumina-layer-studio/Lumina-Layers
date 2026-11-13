import { motion } from "framer-motion";
import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";

import { useWorkspaceMode } from "../../hooks/useWorkspaceMode";
import { useI18n } from "../../i18n/context";
import {
  selectWorkbenchCombo,
  useMaterialWorkbenchStore,
} from "../../stores/materialWorkbenchStore";
import MaterialSolverCacheStatusCard from "../MaterialSolverCacheStatusCard";
import {
  PanelIntro,
  StatusBanner,
  desktopPrimaryColumnClass,
  desktopSecondaryColumnClass,
  resolveDesktopSplitLayoutClass,
  resolvePanelSurfaceClass,
} from "../ui/panelPrimitives";
import DynamicLayerCacheCard from "./DynamicLayerCacheCard";
import MaterialComboControls from "./MaterialComboControls";
import { useSeedWorkbenchFromConverter } from "./useSeedWorkbenchFromConverter";

/**
 * Material > Solver Cache: build, inspect, and delete saved candidates for one
 * combination, in fixed (exhaustive / smart cache) or dynamic layer mode.
 *
 * 耗材 > 求解缓存：为单个组合构建、查看和删除已保存的候选，支持固定层数
 * （穷举 / 智能缓存）与动态层数模式。
 */
export default function MaterialCachePanel() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();
  useSeedWorkbenchFromConverter();
  const selection = useMaterialWorkbenchStore(useShallow(selectWorkbenchCombo));
  // Conversion always prints on the white substrate, so only white caches are ever used.
  const combo = useMemo(() => ({ ...selection, substrate: "white" as const }), [selection]);
  const hasMaterials = combo.materialDirectoryNames.length > 0;

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      data-testid="material-cache-panel"
      className={`${resolvePanelSurfaceClass(workspace.mode)} flex flex-col gap-5`}
    >
      <PanelIntro title={t("material_cache_title")} description={t("material_cache_description")} />
      <div className={resolveDesktopSplitLayoutClass(workspace.mode)}>
        <div className={desktopPrimaryColumnClass}>
          <MaterialComboControls showSubstrate={false} />
          {!hasMaterials ? (
            <StatusBanner tone="info">{t("material_workbench_empty_hint")}</StatusBanner>
          ) : null}
        </div>
        <div className={desktopSecondaryColumnClass}>
          {combo.layerMode === "dynamic" ? (
            <DynamicLayerCacheCard combo={combo} />
          ) : (
            <MaterialSolverCacheStatusCard
              materialDirectoryNames={combo.materialDirectoryNames}
              layerCount={combo.layerCount}
              layerHeightMm={combo.layerHeightMm}
              substrate={combo.substrate}
            />
          )}
        </div>
      </div>
    </motion.aside>
  );
}
