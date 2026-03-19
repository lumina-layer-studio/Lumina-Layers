/**
 * SettingsPanel - System settings page.
 * 系统设置页面，包含缓存清理功能。
 */

import { motion } from "framer-motion";
import { useState } from "react";
import { useI18n } from "../i18n/context";
import { clearCache } from "../api/system";
import Button from "./ui/Button";
import { PanelIntro, StatusBanner, centeredPanelClass, sectionCardClass } from "./ui/panelPrimitives";

export default function SettingsPanel() {
  const { t } = useI18n();

  const [clearing, setClearing] = useState(false);
  const [cacheResult, setCacheResult] = useState<string | null>(null);

  const handleClearCache = async () => {
    setClearing(true);
    setCacheResult(null);
    try {
      const res = await clearCache();
      const size = res.freed_bytes < 1024 * 1024
        ? `${(res.freed_bytes / 1024).toFixed(1)} KB`
        : `${(res.freed_bytes / (1024 * 1024)).toFixed(1)} MB`;
      setCacheResult(
        t("settings.cache_cleared_detail")
          .replace("{count}", String(res.deleted_files))
          .replace("{size}", size)
      );
    } catch {
      setCacheResult(t("settings.cache_clear_failed"));
    } finally {
      setClearing(false);
    }
  };

  return (
    <motion.aside
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", damping: 25, stiffness: 300 }}
      data-testid="settings-panel"
      className={`${centeredPanelClass} flex max-w-3xl flex-col gap-5`}
    >
      <PanelIntro
        eyebrow={t("tab.settings")}
        title={t("settings.title")}
        description={t("settings.desc")}
      />

      <section className={`${sectionCardClass} flex flex-col gap-4`}>
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
            {t("settings.maintenance")}
          </p>
          <h4 className="mt-1 text-base font-semibold text-slate-900 dark:text-slate-50">
            {t("settings.cache")}
          </h4>
        </div>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {t("settings.cache_summary")}
        </p>
        <StatusBanner tone="info">{t("settings.clear_cache_desc")}</StatusBanner>
        <div className="flex items-center gap-3">
          <Button
            label={t("settings.clear_cache")}
            onClick={handleClearCache}
            loading={clearing}
            variant="secondary"
          />
        </div>
        {cacheResult && (
          <StatusBanner tone={cacheResult === t("settings.cache_clear_failed") ? "error" : "success"}>
            {cacheResult}
          </StatusBanner>
        )}
      </section>
    </motion.aside>
  );
}
