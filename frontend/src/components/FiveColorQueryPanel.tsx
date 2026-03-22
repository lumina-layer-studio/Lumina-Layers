import { motion } from "framer-motion";
import { useEffect, useMemo } from "react";
import { useFiveColorStore } from "../stores/fiveColorStore";
import { useConverterStore } from "../stores/converterStore";
import Dropdown from "./ui/Dropdown";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { useI18n } from "../i18n/context";
import FiveColorCanvas from "./FiveColorCanvas";
import Button from "./ui/Button";
import {
  PanelIntro,
  StatusBanner,
  resolvePanelSurfaceClass,
  resolveSectionCardClass,
  resolveDesktopSplitLayoutClass,
  desktopPrimaryColumnClass,
  desktopSecondaryColumnClass,
} from "./ui/panelPrimitives";

export default function FiveColorQueryPanel() {
  const { t } = useI18n();
  const workspace = useWorkspaceMode();
  const {
    lutName, baseColors, combinations, selectedIndices, queryResult,
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

  const validNextIndices = useMemo(() => {
    if (isFull) return null;
    // 如果 combinations 还没加载或者为空（说明不支持预判或者全可选），直接允许所有
    if (!combinations || combinations.length === 0) return null;
    
    const len = selectedIndices.length;
    const valid = new Set<number>();
    
    for (const combo of combinations) {
      let match = true;
      for (let i = 0; i < len; i++) {
        if (combo[i] !== selectedIndices[i]) {
          match = false;
          break;
        }
      }
      // 如果前面选的都匹配，就把这个组合在当前要选的位置（索引为 len）的颜色设为合法
      if (match && len < 5) {
        valid.add(combo[len]);
      }
    }
    return Array.from(valid);
  }, [combinations, selectedIndices, isFull]);

  const canvasSlices = useMemo(
    () => selectedIndices.map((idx) => {
      const c = baseColors.find((b) => b.index === idx);
      return c ? { hex: c.hex, name: c.name } : { hex: "#666666", name: "?" };
    }),
    [selectedIndices, baseColors],
  );

  return (
    <motion.div
      initial={{ opacity: 0, x: -30 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ type: "spring", damping: 25, stiffness: 300 }}
      className="flex h-full w-full min-h-0"
    >
      <aside className={`${resolvePanelSurfaceClass(workspace.mode)} h-auto w-full overflow-y-auto xl:h-full xl:w-[400px] xl:shrink-0 2xl:w-[480px]`}>
        <div className="flex flex-col gap-5">
          <PanelIntro
            eyebrow={t("tab.fiveColor")}
            title={t("five_color_title")}
            description={t("five_color_desc")}
          />

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

            <div className="pr-1">
              {baseColors.length > 0 ? (
                <div className="flex flex-col gap-3">
                  {combinations && combinations.length > 0 && (
                    <div className="flex flex-col gap-1 px-2">
                      <div className="text-xs text-blue-600 dark:text-blue-400 font-medium">
                        ✓ 已加载 {combinations.length} 种有效组合
                      </div>
                      <div className="text-xs text-slate-500 dark:text-slate-400">
                        灰色颜色表示无法形成有效组合（智能过滤已启用）
                      </div>
                    </div>
                  )}
                  <div className={`grid gap-2 ${workspace.isCompact ? "grid-cols-2" : "grid-cols-2 sm:grid-cols-3 xl:grid-cols-2 2xl:grid-cols-3"}`}>
                    {baseColors.map((color) => {
                      const isSelected = selectedIndices.includes(color.index);
                      const selOrder = selectedIndices.indexOf(color.index);
                      const isValidNext = validNextIndices === null || validNextIndices.includes(color.index);
                      const disabled = isFull || !isValidNext;

                      return (
                        <button
                          key={color.index}
                          onClick={() => addSelection(color.index)}
                          disabled={disabled}
                          className={`group relative flex flex-col items-center gap-1 rounded-[20px] border p-2 transition-all ${
                            isSelected
                              ? disabled
                                ? "border-blue-400/50 bg-blue-500/5 ring-2 ring-blue-500/10 opacity-60"
                                : "border-blue-400 bg-blue-500/10 ring-2 ring-blue-500/20"
                              : isValidNext
                                ? "border-transparent bg-white/45 hover:border-slate-300 hover:bg-white/75 dark:bg-slate-900/45 dark:hover:border-slate-600 dark:hover:bg-slate-900/75"
                                : "border-transparent bg-slate-100/30 opacity-40 grayscale"
                          } ${disabled ? "cursor-not-allowed" : "cursor-pointer"}`}
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
                </div>
              ) : lutName ? (
                <p className="py-8 text-center text-sm text-slate-500 dark:text-slate-400">{t("five_color_no_base_colors")}</p>
              ) : (
                <p className="py-8 text-center text-sm text-slate-500 dark:text-slate-400">{t("five_color_select_lut_first")}</p>
              )}
            </div>
          </section>

          <section className={`${resolveSectionCardClass(workspace.mode)} flex flex-col gap-3`}>
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50">{t("five_color_actions")}</h3>

            <div className={`grid gap-2 ${workspace.isCompact ? "grid-cols-1" : "grid-cols-2"}`}>
              <Button
                onClick={() => void submitQuery()}
                disabled={!isFull || isLoading}
                label={isLoading ? t("five_color_query_loading") : t("five_color_query")}
                className={workspace.isCompact ? "" : "col-span-2"}
              />
              <Button
                onClick={removeLastSelection}
                disabled={!hasSelection}
                label={t("five_color_undo")}
                variant="secondary"
              />
              <Button
                onClick={reverseSelection}
                disabled={!isFull}
                label={t("five_color_reverse")}
                variant="secondary"
              />
              <Button
                onClick={clearSelection}
                disabled={!hasSelection}
                label={t("five_color_clear")}
                variant="secondary"
                className={workspace.isCompact ? "" : "col-span-2"}
              />
            </div>
          </section>
        </div>
      </aside>

      <div className={`relative min-h-0 flex-1 overflow-hidden border-slate-200/70 dark:border-slate-800/80 flex flex-col bg-slate-50 dark:bg-slate-950 ${workspace.isWide ? "border-t 2xl:border-l 2xl:border-t-0" : "border-t"}`}>
        {/* Top bar for results (similar to action bar or result banner) */}
        {(error || queryResult) && (
          <div className="flex-none p-4 sm:p-5 lg:p-7 border-b border-slate-200/70 dark:border-slate-800/80 bg-white/50 dark:bg-slate-900/50">
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

            {queryResult && queryResult.found && (
              <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
                <StatusBanner tone="success" className="w-full sm:w-auto flex-1">
                  {t("five_color_result_panel")}
                </StatusBanner>
                
                <div className="flex items-center gap-3 bg-white dark:bg-slate-900 rounded-2xl p-2.5 border border-slate-200 dark:border-slate-700 shadow-sm shrink-0">
                  <div
                    className="h-10 w-16 sm:w-20 rounded-[12px] border border-slate-200 dark:border-slate-700 shadow-[var(--shadow-control)]"
                    style={{ backgroundColor: queryResult.result_hex ?? undefined }}
                  />
                  <div className="flex flex-col">
                    <span className="font-mono text-sm font-semibold text-slate-800 dark:text-slate-100">{queryResult.result_hex}</span>
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      {t("five_color_result_row")}: {queryResult.row_index}
                    </span>
                  </div>
                </div>
              </div>
            )}

            {queryResult && !queryResult.found && (
              <div className="flex flex-col gap-2">
                <StatusBanner tone="warning">
                  {t("five_color_not_found")}
                </StatusBanner>
                <div className="text-xs text-slate-600 dark:text-slate-400 bg-slate-50 dark:bg-slate-900/50 rounded-lg p-3 border border-slate-200 dark:border-slate-700">
                  <div className="font-medium mb-1">💡 建议尝试：</div>
                  <ul className="list-disc list-inside space-y-0.5 ml-1">
                    <li>点击"反转"按钮尝试相反的颜色顺序</li>
                    <li>更换不同的颜色组合</li>
                    <li>注意灰色颜色表示该位置无法形成有效组合</li>
                  </ul>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Main Canvas Area */}
        <div className="relative flex-1 min-h-0 flex flex-col items-center justify-center overflow-hidden p-4 sm:p-8 pt-12 sm:pt-16">
          <div className="absolute inset-x-0 top-0 h-40 bg-gradient-to-b from-blue-500/5 to-transparent pointer-events-none" />
          <div className="relative flex w-full max-w-2xl flex-1 items-center justify-center translate-y-4">
            <div className="h-full w-full">
              <FiveColorCanvas
                slices={canvasSlices}
                resultHex={queryResult?.found ? queryResult.result_hex : null}
                isLoading={isLoading}
              />
            </div>
          </div>
          <p className="relative mt-8 mb-4 text-sm font-medium text-slate-500 dark:text-slate-400 bg-slate-100/80 dark:bg-slate-800/80 px-4 py-2 rounded-full shadow-sm backdrop-blur-sm border border-slate-200/50 dark:border-slate-700/50">
            {baseColors.length > 0
              ? t("five_color_selection_progress").replace("{count}", String(selectedIndices.length)).replace("{total}", "5")
              : t("five_color_select_lut_first")}
          </p>
        </div>
      </div>
    </motion.div>
  );
}
