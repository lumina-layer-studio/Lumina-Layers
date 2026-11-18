import { useState, type ReactNode } from "react";
import { ArrowTopRightOnSquareIcon } from "@heroicons/react/24/outline";
import type { LocalLutVersion } from "../../api/types";
import { useI18n } from "../../i18n/context";
import CalibrationThumbnail, { type CalibrationThumbnailProps } from "./CalibrationThumbnail";
import { filamentIdentity, type FilamentIdentity } from "../../utils/filamentIdentity";
import { resourceColors, resourceFilaments } from "../../utils/resourcePresentation";
import { useFilamentMarket } from "../../hooks/useFilamentMarket";
import { useSettingsStore } from "../../stores/settingsStore";
import { filamentLogoSource, POLYMAKER_PANCHROMA_LOGO } from "../../data/filamentBrands";
import ResourceLicense from "./ResourceLicense";

const brandLogoSizes = {
  sm: { frame: "h-7 w-16", image: "h-7 max-w-16" },
  md: { frame: "h-8 min-w-8", image: "h-8 max-w-[4.5rem]" },
  lg: { frame: "h-10 min-w-10", image: "h-10 max-w-24" },
};

export function LibraryBrandLogo({
  logo,
  size = "md",
}: {
  logo?: string;
  size?: keyof typeof brandLogoSizes;
}) {
  const theme = useSettingsStore((state) => state.theme);
  const [failedSource, setFailedSource] = useState<string>();
  const src = logo && filamentLogoSource(logo, theme);
  const sizing = brandLogoSizes[size];
  return src && src !== failedSource ? (
    <span
      className={`inline-flex shrink-0 items-center justify-center ${sizing.frame}`}
      aria-hidden="true"
    >
      <img
        src={src}
        alt=""
        referrerPolicy={logo === POLYMAKER_PANCHROMA_LOGO ? "no-referrer" : undefined}
        loading={logo === POLYMAKER_PANCHROMA_LOGO ? "lazy" : undefined}
        onError={() => setFailedSource(src)}
        className={`w-auto object-contain ${sizing.image}`}
      />
    </span>
  ) : null;
}

export function LibraryColorSummary({
  thumbnail,
  compact = false,
}: {
  thumbnail: CalibrationThumbnailProps;
  compact?: boolean;
}) {
  const { t, lang } = useI18n();
  const colors = resourceColors(thumbnail, lang);
  if (!colors.length) return null;
  return (
    <span
      className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[var(--surface-text-muted)]"
      aria-label={`${t("resources_used_colors")}：${colors.map((color) => color.label).join("、")}`}
    >
      {colors.map((color, index) => (
        <span key={index} title={color.label} className="inline-flex items-center gap-1">
          {color.hex && (
            <i
              aria-hidden="true"
              className="h-2.5 w-2.5 shrink-0 rounded-full border border-[var(--surface-card-outline)]"
              style={{ background: color.hex }}
            />
          )}
          {!(compact && color.hex && /^(?:通道|Channel) \d+$/.test(color.label)) && color.label}
        </span>
      ))}
    </span>
  );
}

export function LibraryCardIdentity({
  name,
  subtitle,
  logo,
  thumbnail,
  metric,
  localVersion,
}: {
  name: string;
  subtitle: string;
  logo?: string;
  thumbnail: CalibrationThumbnailProps;
  metric?: string;
  localVersion?: LocalLutVersion | null;
}) {
  const { t, lang } = useI18n();
  const versionDate =
    localVersion?.installed_at && Number.isFinite(Date.parse(localVersion.installed_at))
      ? new Date(localVersion.installed_at).toLocaleString(lang === "zh" ? "zh-CN" : "en-US", {
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        })
      : null;
  return (
    <span className="min-w-0 flex-1">
      <span className="material-library-card-name block break-words text-sm font-semibold leading-snug">
        {name}
      </span>
      <span className="mt-1.5 flex min-h-8 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[var(--surface-text-muted)]">
        <LibraryBrandLogo logo={logo} />
        <span className="min-w-0 break-words">{subtitle}</span>
      </span>
      <LibraryColorSummary thumbnail={thumbnail} compact />
      {metric && <span className="material-library-card-meta mt-1 block text-xs">{metric}</span>}
      {localVersion && (
        <span className="mt-1 block text-xs text-[var(--surface-text-muted)]">
          {t(localVersion.current ? "mat_sync_history_current" : "mat_sync_history_previous")}
          {versionDate && <span className="mt-0.5 block">{versionDate}</span>}
        </span>
      )}
    </span>
  );
}

function PurchaseLinks({ links }: { links?: FilamentIdentity["purchaseLinks"] }) {
  const { t } = useI18n();
  if (!links?.length) return null;
  return (
    <span className="flex flex-col items-end gap-1">
      {links.map((link, index) => (
        <a
          key={`${index}:${link.url}`}
          href={link.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex max-w-full items-center gap-1 break-all rounded text-xs font-medium text-blue-600 hover:underline focus-visible:outline-2 focus-visible:outline-[var(--focus-ring)] dark:text-blue-400"
        >
          <span>
            {link.label || t("resources_product_page")} · {link.host}
          </span>
          <ArrowTopRightOnSquareIcon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        </a>
      ))}
    </span>
  );
}

function ResourceAttribution({ value }: { value: unknown }) {
  const { t } = useI18n();
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const data = value as Record<string, unknown>;
  const relationship = data.relationship;
  if (
    relationship !== "original" &&
    relationship !== "adapted" &&
    relationship !== "redistributed"
  ) {
    return null;
  }
  const readText = (item: unknown) => (typeof item === "string" ? item : "");
  const source =
    data.source && typeof data.source === "object" && !Array.isArray(data.source)
      ? (data.source as Record<string, unknown>)
      : {};
  let link = "";
  try {
    const url = new URL(readText(data.source_url));
    if (["https:", "http:"].includes(url.protocol) && !url.username && !url.password) {
      link = url.href;
    }
  } catch {
    /* A resource reference may replace the external link. */
  }
  return (
    <LibraryFields
      rows={[
        { label: t("resource_origin_declaration"), value: t(`resource_origin_${relationship}`) },
        ...(relationship !== "original"
          ? [
              {
                label: t("contribution_original_author"),
                value: readText(data.original_author) || "—",
              },
              ...(link
                ? [
                    {
                      label: t("contribution_source_url"),
                      value: (
                        <a
                          href={link}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex max-w-full items-center gap-1 break-all text-xs font-medium text-blue-600 hover:underline dark:text-blue-400"
                        >
                          <span>{link}</span>
                          <ArrowTopRightOnSquareIcon
                            className="h-3.5 w-3.5 shrink-0"
                            aria-hidden="true"
                          />
                        </a>
                      ),
                    },
                  ]
                : []),
              ...(readText(source.resource_id)
                ? [
                    {
                      label: t("resource_origin_revision"),
                      value: (
                        <span className="break-all font-mono text-xs">
                          {readText(source.resource_id)} · {readText(source.revision_id)}
                        </span>
                      ),
                    },
                  ]
                : []),
              {
                label: t("contribution_rights_basis"),
                value: readText(data.rights_basis) || "—",
              },
            ]
          : []),
      ]}
    />
  );
}

export function LibraryIdentity({
  name,
  originalName,
  subtitle,
  thumbnail,
  logo,
  colorDescription,
  colorName,
  productCode,
  series,
  description,
  contributor,
  purchaseLinks,
  children,
}: {
  name: string;
  originalName?: string;
  subtitle: string;
  thumbnail: CalibrationThumbnailProps;
  logo?: string;
  colorDescription?: string;
  productCode?: string;
  series?: string;
  colorName?: string;
  description?: string;
  contributor?: string;
  purchaseLinks?: FilamentIdentity["purchaseLinks"];
  children?: ReactNode;
}) {
  const { t, lang } = useI18n();
  const market = useFilamentMarket();
  const isLut = thumbnail.kind === "luts";
  const recordedName = thumbnail.display?.original_name;
  const sourceName = (typeof recordedName === "string" && recordedName.trim()) || originalName;
  const filaments = resourceFilaments(thumbnail).map((row) => {
    const brand = typeof row.brand === "string" ? row.brand : "";
    const rowName =
      typeof row.material_name === "string"
        ? row.material_name
        : typeof row.color_name === "string"
          ? row.color_name
          : "";
    return {
      ...filamentIdentity(brand, rowName, lang, row, market),
      slot: typeof row.slot === "number" ? row.slot : undefined,
    };
  });
  const detailRows = [
    { label: t("resources_license"), value: <ResourceLicense license={thumbnail.display?.license} /> },
    ...(series ? [{ label: t("resources_series"), value: series }] : []),
    ...(logo === POLYMAKER_PANCHROMA_LOGO || filaments.some((filament) => filament.logo === POLYMAKER_PANCHROMA_LOGO)
      ? [{ label: t("resources_brand_support"), value: t("resources_polymaker_support") }]
      : []),
    ...(colorName && !isLut ? [{ label: t("resources_color_name"), value: colorName }] : []),
    ...(colorDescription
      ? [{ label: t("resources_color_description"), value: colorDescription }]
      : []),
    ...(productCode ? [{ label: t("resources_product_code"), value: productCode }] : []),
    ...(contributor ? [{ label: t("resources_contributor"), value: contributor }] : []),
    ...(description
      ? [{ label: t(isLut ? "resources_lut_description" : "resources_description"), value: description }]
      : []),
    ...(sourceName && sourceName !== name
      ? [{ label: t(isLut ? "resources_lut_original_name" : "resources_original_name"), value: sourceName }]
      : []),
    ...(purchaseLinks?.length
      ? [{ label: t("resources_purchase"), value: <PurchaseLinks links={purchaseLinks} /> }]
      : []),
  ];

  return (
    <>
      <header className="flex min-w-0 items-start gap-3.5 pr-10">
        <CalibrationThumbnail
          {...thumbnail}
          size="lg"
          renderDetails={(boardControls) => (
            <div className="min-w-0 flex-1">
              <h3 className="break-words text-[15px] font-semibold leading-snug text-slate-900 dark:text-slate-50">
                {name}
              </h3>
              {boardControls}
              <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                <LibraryBrandLogo logo={logo} size="lg" />
                <span>{subtitle}</span>
              </p>
              {children}
            </div>
          )}
        />
      </header>
      {isLut && (
        <div className="border-t panel-divider pt-3.5">
          <p className="text-xs font-medium text-slate-500 dark:text-slate-400">
            {t("resources_used_colors")}
          </p>
          <LibraryColorSummary thumbnail={thumbnail} />
          {!resourceColors(thumbnail, lang).length && (
            <p className="mt-1 text-sm text-[var(--surface-text-muted)]">
              {t("resources_colors_missing")}
            </p>
          )}
          {!!filaments.length && (
            <ol className="mt-2.5 grid gap-2">
              {filaments.map((filament, index) => (
                <li
                  key={index}
                  className="flex items-start gap-2.5 rounded-lg bg-[var(--surface-well)] px-3 py-2 text-sm"
                >
                  <span className="mt-0.5 inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded bg-[var(--surface-card)] px-1 text-[11px] font-semibold tabular-nums text-slate-600 dark:text-slate-300">
                    {filament.slot !== undefined ? filament.slot + 1 : index + 1}
                  </span>
                  <LibraryBrandLogo logo={filament.logo} />
                  <div className="min-w-0 flex-1 break-words">
                    <p className="text-xs font-medium text-slate-800 dark:text-slate-100">
                      {[filament.brand, filament.name || filament.colorName]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                    <p className="mt-0.5 text-[11px] text-[var(--surface-text-muted)]">
                      {[
                        ...new Set(
                          [
                            filament.series || filament.materialType,
                            filament.colorName,
                            filament.productCode,
                          ].filter(Boolean),
                        ),
                      ].join(" · ")}
                    </p>
                    {filament.purchaseLinks?.length ? (
                      <div className="mt-1 flex justify-start">
                        <PurchaseLinks links={filament.purchaseLinks} />
                      </div>
                    ) : null}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
      {!!detailRows.length && (
        <div className="border-t panel-divider pt-3.5">
          <LibraryFields rows={detailRows} />
        </div>
      )}
      <ResourceAttribution value={thumbnail.display?.attribution} />
    </>
  );
}

export function LibraryFields({
  rows,
}: {
  rows: { label: string; value: ReactNode; multiline?: boolean }[];
}) {
  return (
    <dl className="grid gap-2.5 text-sm">
      {rows.map(({ label, value, multiline }) => (
        <div
          key={label}
          className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-4 gap-y-1"
        >
          <dt className="shrink-0 text-xs text-slate-500 dark:text-slate-400">{label}</dt>
          <dd
            className={`ml-auto min-w-0 max-w-full text-right text-slate-800 tabular-nums dark:text-slate-100 ${
              multiline ? "break-all font-mono text-xs" : "break-words"
            }`}
          >
            {value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
