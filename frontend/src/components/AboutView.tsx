import { useAboutStore } from "../stores/aboutStore";
import { useI18n } from "../i18n/context";
import Button from "./ui/Button";

export default function AboutView() {
  const { t } = useI18n();
  const { loading, notification, clearCache, dismissNotification } =
    useAboutStore();

  return (
    <aside
      data-testid="about-panel"
      className="w-[350px] h-full overflow-y-auto bg-gray-800 p-4 flex flex-col gap-4"
    >
      <div>
        <h2 className="text-lg font-semibold text-gray-100">
          {t("about_title")}
        </h2>
        <p className="text-xs text-gray-400 mt-1">{t("about_desc")}</p>
      </div>

      <Button
        label={loading ? t("about_clear_cache_loading") : t("about_clear_cache")}
        variant="primary"
        onClick={() => void clearCache()}
        disabled={loading}
        loading={loading}
      />

      {notification && (
        <div
          data-testid="cache-notification"
          role="status"
          className={`rounded-md p-3 text-xs flex items-start gap-2 ${
            notification.type === "success"
              ? "bg-green-900/30 border border-green-700 text-green-300"
              : "bg-red-900/30 border border-red-700 text-red-300"
          }`}
        >
          <span>{notification.type === "success" ? "✓" : "✗"}</span>
          <span>{notification.message}</span>
          <button
            onClick={dismissNotification}
            className={`ml-auto shrink-0 ${
              notification.type === "success"
                ? "text-green-400 hover:text-green-200"
                : "text-red-400 hover:text-red-200"
            }`}
            aria-label={t("about_close_notification")}
          >
            ×
          </button>
        </div>
      )}
    </aside>
  );
}
