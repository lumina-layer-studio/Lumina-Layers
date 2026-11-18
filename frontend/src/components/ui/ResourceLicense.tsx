import { useI18n } from "../../i18n/context";

export default function ResourceLicense({ license }: { license?: unknown }) {
  const { t } = useI18n();
  const id = typeof license === "string" ? license.trim() : "";
  const links: Record<string, string> = {
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC-BY-SA-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "LicenseRef-Lumina-Data-1.0": "/data-license.html",
  };
  const href = id ? links[id] : "/data-license.html";
  const label = id === "LicenseRef-Lumina-Data-1.0" || !id ? t("resources_data_license") : id;
  return href ? (
    <a href={href} target="_blank" rel="noopener noreferrer"
      className="rounded text-xs text-blue-600 hover:underline focus-visible:outline-2 focus-visible:outline-[var(--focus-ring)] dark:text-blue-400">
      {label}
    </a>
  ) : <span>{label}</span>;
}
