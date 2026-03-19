import { useEffect } from "react";
import { useLutManagerStore } from "../stores/lutManagerStore";
import { useI18n } from "../i18n/context";
import Dropdown from "./ui/Dropdown";
import Slider from "./ui/Slider";
import Button from "./ui/Button";
import { motion } from "framer-motion";

export default function LutManagerPanel() {
  const { t } = useI18n();
  const {
    lutList,
    lutListLoading,
    primaryName,
    primaryInfo,
    primaryLoading,
    secondaryNames,
    secondaryInfos,
    filteredSecondaryOptions,
    dedupThreshold,
    merging,
    mergeResult,
    error,
    fetchLutList,
    selectPrimary,
    setSecondaryNames,
    setDedupThreshold,
    executeMerge,
    clearError,
  } = useLutManagerStore();

  useEffect(() => {
    void fetchLutList();
  }, [fetchLutList]);

  const allDisabled = merging;

  const primaryOptions = lutList.map((lut) => ({
    label: lut.name,
    value: lut.name,
  }));

  const isPrimaryModeInvalid =
    primaryInfo !== null &&
    !primaryInfo.color_mode.startsWith("6-Color") &&
    !primaryInfo.color_mode.startsWith("8-Color");

  const mergeDisabled =
    merging ||
    !primaryName ||
    secondaryNames.length === 0 ||
    isPrimaryModeInvalid;

  const handleSecondaryToggle = (name: string) => {
    if (allDisabled) return;
    const updated = secondaryNames.includes(name)
      ? secondaryNames.filter((n) => n !== name)
      : [...secondaryNames, name];
    setSecondaryNames(updated);
  };

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", damping: 25, stiffness: 300 }}
      data-testid="lut-manager-panel"
      className="w-full max-w-2xl mx-auto h-full overflow-y-auto bg-white/85 dark:bg-gray-900/85 backdrop-blur-2xl border border-white/40 dark:border-gray-700/50 shadow-2xl rounded-2xl p-6 flex flex-col gap-4"
    >
      <div>
        <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-100">{t("lut_manager_title")}</h2>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
          {t("lut_manager_desc")}
        </p>
      </div>

      {/* Primary LUT 选择 */}
      <div data-testid="primary-dropdown">
        <Dropdown
          label={t("lut_manager_primary_label")}
          value={primaryName}
          options={primaryOptions}
          onChange={(v) => void selectPrimary(v)}
          disabled={allDisabled || lutListLoading}
          placeholder={t("lut_manager_primary_placeholder")}
        />
        {primaryLoading && (
          <p data-testid="loading-indicator" className="text-xs text-gray-400 mt-1">
            {t("lut_manager_loading")}
          </p>
        )}
        {primaryInfo && (
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            Mode: {primaryInfo.color_mode} ({primaryInfo.color_count} colors)
          </p>
        )}
        {isPrimaryModeInvalid && (
          <p className="text-xs text-yellow-400 mt-1">
            {t("lut_manager_primary_mode_invalid")}
          </p>
        )}
      </div>

      {/* Secondary LUT 多选 */}
      <div data-testid="secondary-list" className="flex flex-col gap-1">
        <label className="text-sm text-gray-700 dark:text-gray-300">{t("lut_manager_secondary_label")}</label>
        <div className="max-h-40 overflow-y-auto rounded-md border border-gray-300 dark:border-gray-600 bg-gray-100 dark:bg-gray-700 p-2 flex flex-col gap-1">
          {filteredSecondaryOptions.length === 0 ? (
            <p className="text-xs text-gray-400 dark:text-gray-500">
              {primaryName ? t("lut_manager_no_secondary") : t("lut_manager_select_primary_first")}
            </p>
          ) : (
            filteredSecondaryOptions.map((name) => {
              const info = secondaryInfos.get(name);
              return (
                <label
                  key={name}
                  className="flex items-center gap-2 text-xs text-gray-700 dark:text-gray-200 cursor-pointer hover:bg-gray-200 dark:hover:bg-gray-600 rounded px-1 py-0.5"
                >
                  <input
                    type="checkbox"
                    checked={secondaryNames.includes(name)}
                    onChange={() => handleSecondaryToggle(name)}
                    disabled={allDisabled}
                    className="accent-blue-500"
                  />
                  <span className="truncate">{name}</span>
                  {info && (
                    <span className="text-gray-500 dark:text-gray-400 ml-auto shrink-0">
                      {info.color_mode} ({info.color_count})
                    </span>
                  )}
                </label>
              );
            })
          )}
        </div>
      </div>

      {/* Dedup Threshold 滑块 */}
      <div>
        <Slider
          label={t("lut_manager_dedup_label")}
          value={dedupThreshold}
          min={0}
          max={20}
          step={0.5}
          onChange={setDedupThreshold}
          disabled={allDisabled}
        />
        <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
          {t("lut_manager_dedup_hint")}
        </p>
      </div>

      {/* Merge & Save 按钮 */}
      <Button
        label={t("lut_manager_merge_btn")}
        variant="primary"
        onClick={() => void executeMerge()}
        disabled={mergeDisabled}
        loading={merging}
      />

      {/* 合并结果 */}
      {mergeResult && (
        <div data-testid="merge-result" className="rounded-md bg-green-900/30 border border-green-700 p-3 text-xs text-green-300 flex flex-col gap-1">
          <p>{t("lut_manager_merge_success")}</p>
          <p>
            {t("lut_manager_merge_before")}: {mergeResult.stats.total_before} → {t("lut_manager_merge_after")}: {mergeResult.stats.total_after}
          </p>
          <p>
            {t("lut_manager_exact_dupes")}: {mergeResult.stats.exact_dupes} | {t("lut_manager_similar_removed")}: {mergeResult.stats.similar_removed}
          </p>
          <p>{t("lut_manager_file")}: {mergeResult.filename}</p>
        </div>
      )}

      {/* 错误消息 */}
      {error && (
        <div data-testid="error-message" className="rounded-md bg-red-900/30 border border-red-700 p-3 text-xs text-red-300 flex items-start gap-2">
          <span className="shrink-0">✗</span>
          <span>{error}</span>
          <button
            onClick={clearError}
            className="ml-auto text-red-400 hover:text-red-200 shrink-0"
            aria-label={t("lut_manager_close_error")}
          >
            ×
          </button>
        </div>
      )}
    </motion.aside>
  );
}
