import { motion } from "framer-motion";
import { useEffect, useMemo } from "react";
import { useFiveColorStore } from "../stores/fiveColorStore";
import { useConverterStore } from "../stores/converterStore";
import Dropdown from "./ui/Dropdown";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { useI18n } from "../i18n/context";
import FiveColorCanvas from "./FiveColorCanvas";
import Button from "./ui/Button";
import { PanelIntro, StatusBanner, resolvePanelSurfaceClass, resolveSectionCardClass } from "./ui/panelPrimitives";

export default function FiveColorQueryPanel() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();
  const {
    lutName, baseColors, selectedIndices, queryResult,
    isLoading, error,
    loadBaseColors, addSelection, removeLastSelection,
    clearSelection, reverseSelection, submitQuery, clearError,
  } = useFiveColorStore();

  const lutList = useConverterStore((s) => s.lutList);
  const fetchLutList = useConverterStore((s) => s.fetchLutList);

  useEffect(() => {
    if (lutList.length === 0) void fetchLutList();
  }, [fetchLutList, lutList.length]);

  const handleLutChange = (name: string) => {
    if (name) {
      clearError();
      void loadBaseColors(name);
    }
  };

  const hasSelection = selectedIndices.length > 0;
  const isFull = selectedIndices.length === 5;

  const canvasSlices = useMemo(
    () => selectedIndices.map((idx) => {
      const c = baseColors.find((b) => b.index === idx);
      return c ? { hex: c.hex, name: c.name } : { hex: "#666666", name: "?" };
    }),
    [selectedIndices, baseColors],
  );

  return (
    <motion.div
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", damping: 25, stiffness: 300 }}
      className={`${resolvePanelSurfaceClass(workspace.mode)} flex h-full w-full flex-col gap-5 overflow-hidden text-slate-900 dark:text-white`}
    >
      <PanelIntro
        eyebrow={t("tab.fiveColor")}
        title={t("five_color_title")}
        description={t("five_color_desc")}
      />

      <div className="grid min-h-0 flex-1 gap-5 lg:grid-cols-[20%_80%] md:grid-cols-[30%_70%] grid-cols-1 lg:overflow-hidden overflow-auto">
        <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-4`}>
          <div className="flex flex-col gap-3">
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("five_color_palette")}</h3>
            <Dropdown
              label={t("five_color_lut_label")}
              value={lutName}
              options={lutList.map((n) => ({ label: n, value: n }))}
              onChange={handleLutChange}
              placeholder={t("five_color_lut_placeholder")}
            />
          </div>

          <div className="flex-1 pr-1">
            {baseColors.length > 0 ? (
              <div className="grid gap-2 grid-cols-3 sm:grid-cols-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {baseColors.map((color) => {
                  const isSelected = selectedIndices.includes(color.index);
                  const selOrder = selectedIndices.indexOf(color.index);
                  return (
                    <button
                      key={color.index}
                      onClick={() => addSelection(color.index)}
                      disabled={isFull && !isSelected}
                      className={`group relative flex flex-col items-center gap-1 rounded-[20px] border p-2 transition-all ${
                        isSelected
                          ? "border-blue-400 bg-blue-500/10 ring-2 ring-blue-500/20"
                          : "border-transparent bg-white/45 hover:border-slate-300 hover:bg-white/75 dark:bg-slate-900/45 dark:hover:border-slate-600 dark:hover:bg-slate-900/75"
                      } ${isFull && !isSelected ? "cursor-not-allowed opacity-30" : "cursor-pointer"}`}
                      aria-label={t("five_color_select_color").replace("{name}", color.name).replace("{hex}", color.hex)}
                    >
                      <div
                        className="h-11 w-11 rounded-2xl border border-slate-200/80 shadow-[var(--shadow-control)] transition-transform group-hover:scale-105 dark:border-slate-700/80"
                        style={{ backgroundColor: color.hex }}
                      />
                      {isSelected && (
                        <span className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-blue-500 text-xs font-bold text-white">
                          {selOrder + 1}
                        </span>
                      )}
                      <span className="w-full truncate text-center text-[11px] leading-tight text-slate-500 dark:text-slate-400">
                        {color.name}
                      </span>
                    </button>
                  );
                })}
              </div>
            ) : lutName ? (
              <p className="py-8 text-center text-sm text-slate-500 dark:text-slate-400">{t("five_color_no_base_colors")}</p>
            ) : (
              <p className="py-8 text-center text-sm text-slate-500 dark:text-slate-400">{t("five_color_select_lut_first")}</p>
            )}
          </div>
        </section>

        <div className="flex min-h-0 flex-1 flex-col gap-5">
          <section className={`${resolveSectionCardClass(workspace.mode)} relative flex min-h-[300px] flex-1 flex-col items-center justify-center gap-4 overflow-hidden`}>
          <div className="absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-blue-500/10 to-transparent" />
          <div className="relative flex w-full flex-1 items-center justify-center">
            <div className="h-full w-full">
              <FiveColorCanvas
                slices={canvasSlices}
                resultHex={queryResult?.found ? queryResult.result_hex : null}
                isLoading={isLoading}
              />
            </div>
          </div>
          <p className="relative text-sm text-slate-500 dark:text-slate-400">
            {baseColors.length > 0
              ? t("five_color_selection_progress").replace("{count}", String(selectedIndices.length)).replace("{total}", "5")
              : t("five_color_select_lut_first")}
          </p>
          </section>

          <div className="grid gap-5 lg:grid-cols-2 grid-cols-1">
            <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("five_color_actions")}</h3>

              <Button
                onClick={() => void submitQuery()}
                disabled={!isFull || isLoading}
                label={isLoading ? t("five_color_query_loading") : t("five_color_query")}
                className="w-full"
              />
              <Button
                onClick={removeLastSelection}
                disabled={!hasSelection}
                label={t("five_color_undo")}
                variant="secondary"
                className="w-full"
              />
              <Button
                onClick={reverseSelection}
                disabled={!isFull}
                label={t("five_color_reverse")}
                variant="secondary"
                className="w-full"
              />
              <Button
                onClick={clearSelection}
                disabled={!hasSelection}
                label={t("five_color_clear")}
                variant="secondary"
                className="w-full"
              />

              {error && (
                <StatusBanner
                  tone="error"
                  action={
                    <button
                      onClick={clearError}
                      aria-label={t("five_color_close_error")}
                      className="rounded-full border border-current/20 px-2 py-1 text-xs text-red-600 transition-colors hover:bg-red-500/10 dark:text-red-300"
                    >
                      ×
                    </button>
                  }
                >
                  {error}
                </StatusBanner>
              )}
            </section>

            <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
              {queryResult && queryResult.found && (
                <div className="flex h-full flex-col gap-3">
                  <p className="text-sm font-semibold text-slate-900 dark:text-slate-50">{t("five_color_result_panel")}</p>
                  <div
                    className="h-20 w-full rounded-[20px] border border-white/60 shadow-[var(--shadow-control)]"
                    style={{ backgroundColor: queryResult.result_hex ?? undefined }}
                  />
                  <p className="font-mono text-sm text-slate-800 dark:text-slate-100">{queryResult.result_hex}</p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    {t("five_color_result_rgb")}: {queryResult.result_rgb?.join(", ")}
                  </p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    {t("five_color_result_row")}: {queryResult.row_index}
                  </p>
                  {queryResult.source && (
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      {t("five_color_result_source")}: {queryResult.source}
                    </p>
                  )}
                </div>
              )}

              {queryResult && !queryResult.found && (
                <StatusBanner tone="warning">
                  {t("five_color_not_found")}
                </StatusBanner>
              )}
              
              {!queryResult && (
                <div className="flex h-full items-center justify-center py-8">
                  <p className="text-center text-sm text-slate-400 dark:text-slate-500">
                    {t("five_color_result_placeholder") || "查询结果将显示在这里"}
                  </p>
                </div>
              )}
            </section>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
