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
import { wellClass } from "./panelPrimitives";

const brandLogoSizes = {
  xs: { frame: "h-5 max-w-14", image: "h-5 max-w-14" },
  sm: { frame: "h-7 w-16", image: "h-7 max-w-16" },
  md: { frame: "h-8 min-w-8", image: "h-8 max-w-[4.5rem]" },
  lg: { frame: "h-10 min-w-10", image: "h-10 max-w-24" },
};

const swatchDotClass =
  "h-2.5 w-2.5 shrink-0 rounded-full border border-slate-900/20 dark:border-slate-300/45";

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
  const labelSeparator = lang === "zh" ? "：" : ": ";
  const itemSeparator = lang === "zh" ? "、" : ", ";
  return (
    <span
      className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-xs text-[var(--surface-text-muted)]"
      aria-label={`${t("resources_used_colors")}${labelSeparator}${colors.map((color) => color.label).join(itemSeparator)}`}
    >
      {colors.map((color, index) => (
        <span key={index} title={color.label} className="inline-flex items-center gap-1">
          {color.hex && (
            <i
              aria-hidden="true"
              className={swatchDotClass}
              style={{ background: color.hex }}
            />
          )}
          {!(compact && color.hex && /^(?:通道|Channel) \d+$/.test(color.label)) && color.label}
        </span>
      ))}
    </span>
  );
}

/** Full-width LUT mode and filament-color strip rendered below the card header. */
export function LibraryCardPalette({
  thumbnail,
  metric,
}: {
  thumbnail: CalibrationThumbnailProps;
  metric?: string;
}) {
  const { t, lang } = useI18n();
  const colors = resourceColors(thumbnail, lang);
  if (!metric && !colors.length) return null;
  const labelSeparator = lang === "zh" ? "：" : ": ";
  const itemSeparator = lang === "zh" ? "、" : ", ";
  if (!colors.length) {
    return (
      <span className="inline-flex self-start items-center rounded-md bg-[var(--surface-well)] px-2 py-1 text-[11px] font-medium leading-4 tabular-nums text-slate-600 dark:text-slate-300">
        {metric}
      </span>
    );
  }
  return (
    <span className="flex w-full flex-wrap items-center gap-x-2.5 gap-y-1.5 rounded-lg bg-[var(--surface-well)] px-2.5 py-1.5 text-[11px] leading-4 text-slate-600 dark:text-slate-300">
      {metric && (
        <span className="shrink-0 font-medium tabular-nums text-slate-700 dark:text-slate-200">
          {metric}
        </span>
      )}
      {metric && (
        <span aria-hidden="true" className="h-3 w-px shrink-0 bg-[var(--surface-divider)]" />
      )}
      <span
        className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1"
        aria-label={`${t("resources_used_colors")}${labelSeparator}${colors.map((color) => color.label).join(itemSeparator)}`}
      >
        {colors.map((color, index) => (
          <span key={index} title={color.label} className="inline-flex items-center gap-1">
            {color.hex && (
              <i
                aria-hidden="true"
                className={swatchDotClass}
                style={{ background: color.hex }}
              />
            )}
            {!(color.hex && /^(?:通道|Channel) \d+$/.test(color.label)) && color.label}
          </span>
        ))}
      </span>
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
  showMeta = true,
}: {
  name: string;
  subtitle: string;
  logo?: string;
  thumbnail: CalibrationThumbnailProps;
  metric?: string;
  localVersion?: LocalLutVersion | null;
  showMeta?: boolean;
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
      <span className="mt-1.5 flex min-h-5 items-center gap-1.5 text-xs text-[var(--surface-text-muted)]">
        <LibraryBrandLogo logo={logo} size="xs" />
        <span className="min-w-0 truncate">{subtitle}</span>
      </span>
      {showMeta && (
        <>
          <LibraryColorSummary thumbnail={thumbnail} compact />
          {metric && <span className="material-library-card-meta mt-1 block text-xs">{metric}</span>}
        </>
      )}
      {localVersion && (
        <span className="mt-1 block text-xs text-[var(--surface-text-muted)]">
          {t(localVersion.current ? "mat_sync_history_current" : "mat_sync_history_previous")}
          {versionDate && <span className="mt-0.5 block">{versionDate}</span>}
        </span>
      )}
    </span>
  );
}

function PurchaseLinks({
  links,
  align = "end",
}: {
  links?: FilamentIdentity["purchaseLinks"];
  align?: "start" | "end";
}) {
  const { t } = useI18n();
  if (!links?.length) return null;
  return (
    <span className={`flex flex-col gap-1 ${align === "start" ? "items-start" : "items-end"}`}>
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
    <div className="border-t panel-divider pt-3.5">
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
                        stacked: true,
                        value: (
                          <a
                            href={link}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex max-w-full items-center gap-1 break-all text-xs font-medium text-blue-600 hover:underline focus-visible:outline-2 focus-visible:outline-[var(--focus-ring)] dark:text-blue-400"
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
                        multiline: true,
                        value: `${readText(source.resource_id)} · ${readText(source.revision_id)}`,
                      },
                    ]
                  : []),
                {
                  label: t("contribution_rights_basis"),
                  stacked: true,
                  value: readText(data.rights_basis) || "—",
                },
              ]
            : []),
        ]}
      />
    </div>
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
  const hasPolymakerSupport =
    logo === POLYMAKER_PANCHROMA_LOGO ||
    filaments.some((filament) => filament.logo === POLYMAKER_PANCHROMA_LOGO);
  const detailRows: LibraryFieldRow[] = [
    ...(series ? [{ label: t("resources_series"), value: series }] : []),
    ...(colorName && !isLut ? [{ label: t("resources_color_name"), value: colorName }] : []),
    ...(productCode ? [{ label: t("resources_product_code"), value: productCode }] : []),
    ...(colorDescription
      ? [
          {
            label: t("resources_color_description"),
            value: colorDescription,
            stacked: colorDescription.length > 18,
          },
        ]
      : []),
    ...(description
      ? [
          {
            label: t(isLut ? "resources_lut_description" : "resources_description"),
            value: description,
            stacked: true,
          },
        ]
      : []),
    ...(purchaseLinks?.length
      ? [
          {
            label: t("resources_purchase"),
            stacked: purchaseLinks.length > 1,
            value: (
              <PurchaseLinks
                links={purchaseLinks}
                align={purchaseLinks.length > 1 ? "start" : "end"}
              />
            ),
          },
        ]
      : []),
    ...(contributor ? [{ label: t("resources_contributor"), value: contributor }] : []),
    { label: t("resources_license"), value: <ResourceLicense license={thumbnail.display?.license} /> },
    ...(sourceName && sourceName !== name
      ? [
          {
            label: t(isLut ? "resources_lut_original_name" : "resources_original_name"),
            value: sourceName,
            stacked: sourceName.length > 22,
          },
        ]
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
      {hasPolymakerSupport && (
        <div className={`${wellClass} px-3 py-2.5 text-xs leading-5`}>
          <p className="font-medium text-slate-700 dark:text-slate-200">
            {t("resources_brand_support")}
          </p>
          <p className="mt-0.5 text-slate-600 dark:text-slate-300">
            {t("resources_polymaker_support")}
          </p>
          <p className="mt-1.5 border-t panel-divider pt-1.5 text-[11px] leading-4 text-slate-500 dark:text-slate-400">
            {t("resources_polymaker_disclaimer")}
          </p>
        </div>
      )}
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
                  <LibraryBrandLogo logo={filament.logo} size="xs" />
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
                        <PurchaseLinks links={filament.purchaseLinks} align="start" />
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

export interface LibraryFieldRow {
  label: string;
  value: ReactNode;
  multiline?: boolean;
  stacked?: boolean;
}

export function LibraryFields({ rows }: { rows: LibraryFieldRow[] }) {
  return (
    <dl className="grid gap-2.5 text-sm">
      {rows.map(({ label, value, multiline, stacked }) =>
        multiline || stacked ? (
          <div key={label} className="flex min-w-0 flex-col gap-1">
            <dt className="text-xs text-slate-500 dark:text-slate-400">{label}</dt>
            <dd
              className={
                multiline
                  ? "min-w-0 break-all font-mono text-xs leading-5 text-slate-700 dark:text-slate-200"
                  : "min-w-0 break-words text-xs leading-5 text-slate-700 dark:text-slate-200"
              }
            >
              {value}
            </dd>
          </div>
        ) : (
          <div
            key={label}
            className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-4 gap-y-1"
          >
            <dt className="shrink-0 text-xs text-slate-500 dark:text-slate-400">{label}</dt>
            <dd className="ml-auto min-w-0 max-w-full break-words text-right text-slate-800 tabular-nums dark:text-slate-100">
              {value}
            </dd>
          </div>
        ),
      )}
    </dl>
  );
}
