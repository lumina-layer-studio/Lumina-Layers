import { useSettingsStore } from "../stores/settingsStore";
import { useI18n } from "../i18n/context";

export function LanguageToggle() {
  const { t } = useI18n();
  const language = useSettingsStore((s) => s.language);
  const setLanguage = useSettingsStore((s) => s.setLanguage);

  const handleToggle = () => {
    setLanguage(language === "zh" ? "en" : "zh");
  };

  return (
    <button
      onClick={handleToggle}
      aria-label={t("app_toggle_language")}
      className="px-3 py-1 rounded text-sm font-medium bg-gray-700 text-gray-300 hover:bg-gray-600 transition-colors"
    >
      {language === "zh" ? "EN" : "中"}
    </button>
  );
}
