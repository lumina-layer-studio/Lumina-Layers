/**
 * SettingsPanel - System settings panel displayed in FullScreenModal.
 * 系统设置面板，以全屏弹窗形式展示，包含缓存清理功能。
 */

import { motion } from "framer-motion";
import { useState } from "react";
import { useI18n } from "../i18n/context";
import { clearCache } from "../api/system";
import Button from "./ui/Button";

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
      setCacheResult("Error");
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
      className="w-full max-w-2xl mx-auto h-full overflow-y-auto bg-white/85 dark:bg-gray-900/85 backdrop-blur-2xl border border-white/40 dark:border-gray-700/50 shadow-2xl rounded-2xl p-6 flex flex-col gap-6"
    >
      <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
        {t("settings.title")}
      </h3>

      {/* Cache Management / 缓存管理 */}
      <section className="flex flex-col gap-2">
        <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300">
          {t("settings.cache")}
        </h4>
        <p className="text-xs text-gray-500 dark:text-gray-400">
          {t("settings.clear_cache_desc")}
        </p>
        <div className="flex items-center gap-3">
          <Button
            label={t("settings.clear_cache")}
            onClick={handleClearCache}
            loading={clearing}
            variant="secondary"
          />
          {cacheResult && (
            <span className="text-sm text-green-600 dark:text-green-400">
              {cacheResult}
            </span>
          )}
        </div>
      </section>
    </motion.aside>
  );
}
