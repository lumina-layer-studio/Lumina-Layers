import { useEffect, useId, useMemo, useRef, useState } from "react";
import { ArrowPathIcon, ArrowTopRightOnSquareIcon } from "@heroicons/react/24/outline";
import { apiErrorToVisibleMessage } from "../api/client";
import {
  changeContributionReview,
  fetchContributionHistory,
  prepareContribution,
  prepareContributionRevision,
  prepareQueuedContribution,
  submitContribution,
} from "../api/contributions";
import type {
  ContributionAttribution,
  ContributionProduct,
  ContributionReceipt,
  OwnedRevision,
  PreparedContribution,
  QueuedContribution,
} from "../api/contributions";
import type { ResourceKind } from "../api/resources";
import { installExtractedLut, listGradientCardMaterials } from "../api/extractor";
import type { SavedMaterialLibraryItem } from "../api/types";
import { filamentBrands } from "../data/filamentBrands";
import { bambuFilamentColors } from "../data/filamentColors";
import { useI18n } from "../i18n/context";
import { filamentIdentity } from "../utils/filamentIdentity";
import { resourceColorMode } from "../utils/resourcePresentation";
import Button from "./ui/Button";
import { CommunityConnection } from "./CommunityAccount";
import ContributionQueue from "./ContributionQueue";
import ResourceReportHistory from "./ResourceReportHistory";
import { useCommunityStore } from "../stores/communityStore";
import ResourceDialog from "./ui/ResourceDialog";
import Dropdown from "./ui/Dropdown";
import Combobox from "./ui/Combobox";
import Checkbox from "./ui/Checkbox";
import ResourceLicense, { DataLicenseLink } from "./ui/ResourceLicense";
import DisclosureSummary from "./ui/DisclosureSummary";
import CalibrationThumbnail from "./ui/CalibrationThumbnail";
import {
  actionLinkClass,
  cx,
  StatusBanner,
  wellClass,
  workstationFieldLabelClass,
  workstationInputClass,
} from "./ui/panelPrimitives";

const MATERIAL_TYPE_OPTIONS = ["PLA", "PETG", "ABS", "ASA", "TPU", "PCTG", "PA", "PC"].map(
  (item) => ({ label: item, value: item }),
);

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function submissionStatusDot(status: string): string {
  if (status === "published" || status === "approved") return "bg-emerald-500";
  if (status === "pending" || status === "queued") return "bg-amber-500";
  if (status === "needs_changes") return "bg-orange-500";
  if (status === "rejected") return "bg-red-500";
  return "bg-slate-400 dark:bg-slate-500";
}

function productFrom(display: Record<string, unknown>): ContributionProduct {
  const links = Array.isArray(display.purchase_links)
    ? display.purchase_links.filter(
        (row): row is { url?: string; market?: string; label?: string } =>
          !!row && typeof row === "object" && !Array.isArray(row),
      )
    : [];
  const names = display.market_names as { CN?: unknown; INTL?: unknown } | undefined;
  const identity = filamentIdentity(
    text(display.brand),
    text(display.material_name || display.name || display.color_name),
    "en",
    display,
    "INTL",
  );
  return {
    brand: identity.brand,
    material_type: text(display.material_type),
    series: identity.series || "",
    color_name: identity.colorName || text(display.color_name),
    color_code: text(display.color_code) || (display.sku ? "" : identity.productCode || ""),
    sku: text(display.sku),
    purchase_url: links[0]?.url || "",
    market: ["CN", "INTL", "ALL"].includes(links[0]?.market || "") ? links[0].market! : "ALL",
    material_id: text(display.material_id),
    revision_id: text(display.revision_id),
    market_names: { CN: text(names?.CN), INTL: text(names?.INTL) },
    purchase_links: links.slice(1, 8).map((link) => ({
      url: text(link.url),
      label: text(link.label),
      market: ["CN", "INTL"].includes(link.market || "") ? link.market! : "ALL",
    })),
  };
}

function formatSubmissionStatus(t: (key: string) => string, status: string): string {
  const key = `contribution_status_${status}`;
  return t(key) === key ? status : t(key);
}

export default function ResourceContribution({
  kind,
  resourceKey,
  initialDisplay,
  queueId,
}: {
  kind: ResourceKind;
  resourceKey?: string;
  initialDisplay?: Record<string, unknown>;
  queueId?: string;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        label={t(resourceKey ? "contribution_open" : "contribution_history")}
        className={resourceKey ? "w-full" : undefined}
        onClick={() => setOpen(true)}
      />
      {open && (
        <ContributionDialog
          kind={kind}
          resourceKey={resourceKey}
          initialDisplay={initialDisplay}
          queueId={queueId}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

export function ExtractedLutContribution({ sessionId }: { sessionId: string }) {
  const { t } = useI18n();
  const [resource, setResource] = useState<string | null>(null);
  const [queueId, setQueueId] = useState<string>();
  const [queued, setQueued] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <div className="grid gap-2">
      <Button
        label={t("contribution_save_lut")}
        loading={busy}
        onClick={() => {
          setBusy(true);
          setError("");
          setQueued(false);
          setQueueId(undefined);
          void installExtractedLut(sessionId)
            .then((result) => {
              if (result.contribution?.state === "queued") {
                setQueued(true);
                return;
              }
              if (result.contribution?.state === "needs_attention") {
                setError(t("contribution_snapshot_failed"));
              }
              setQueueId(result.contribution?.id);
              setResource(result.name);
            })
            .catch((err) => setError(apiErrorToVisibleMessage(err, t("contribution_failed"))))
            .finally(() => setBusy(false));
        }}
      />
      {error && <StatusBanner tone="error">{error}</StatusBanner>}
      {queued && (
        <p role="status" className="text-xs text-[var(--surface-text-muted)]">
          {t("contribution_queue_confirmed")}
        </p>
      )}
      {resource && (
        <ContributionDialog
          kind="luts"
          resourceKey={resource}
          queueId={queueId}
          onClose={() => setResource(null)}
        />
      )}
    </div>
  );
}

function FormField({
  label,
  value,
  onChange,
  required = false,
  disabled = false,
  type = "text",
  identifier = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  disabled?: boolean;
  type?: "text" | "url";
  identifier?: boolean;
}) {
  const id = useId();
  const noAutoCorrect = identifier || type === "url";
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={id} className={workstationFieldLabelClass}>
        {label}
        {required ? " *" : ""}
      </label>
      <input
        id={id}
        className={`${workstationInputClass} w-full min-w-0`}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        required={required}
        disabled={disabled}
        type={type}
        autoCorrect={noAutoCorrect ? "off" : undefined}
        autoCapitalize={noAutoCorrect ? "none" : undefined}
        spellCheck={noAutoCorrect ? false : undefined}
        maxLength={type === "url" ? 2048 : 200}
      />
    </div>
  );
}

function ProductFields({
  value,
  onChange,
  disabled,
  slot = false,
  brandOptions,
  seriesByBrand,
}: {
  value: ContributionProduct;
  onChange: (product: ContributionProduct) => void;
  disabled: boolean;
  slot?: boolean;
  brandOptions: { value: string; label: string; keywords: string }[];
  seriesByBrand: ReadonlyMap<string, string[]>;
}) {
  const { t } = useI18n();
  const change = (key: keyof ContributionProduct) => (next: string) =>
    onChange({ ...value, material_id: "", revision_id: "", [key]: next });
  const regionalName = (market: "CN" | "INTL", nextName: string) =>
    onChange({
      ...value,
      material_id: "",
      revision_id: "",
      market_names: { ...value.market_names, [market]: nextName },
    });
  const knownSeries =
    value.brand === "Bambu Lab"
      ? Object.keys(bambuFilamentColors).filter(
          (series) =>
            !value.material_type ||
            series.toUpperCase().startsWith(value.material_type.toUpperCase()),
        )
      : [];
  const localSeries = seriesByBrand.get(value.brand) || [];
  const seriesOptions = [
    ...new Set([...knownSeries, ...localSeries, ...(value.series ? [value.series] : [])]),
  ];
  const changeLink = (
    index: number,
    patch: Partial<NonNullable<ContributionProduct["purchase_links"]>[number]>,
  ) =>
    onChange({
      ...value,
      material_id: "",
      revision_id: "",
      purchase_links: value.purchase_links?.map((link, position) =>
        position === index ? { ...link, ...patch } : link,
      ),
    });
  const marketOptions = [
    { value: "ALL", label: t("contribution_market_all") },
    { value: "CN", label: t("contribution_market_cn") },
    { value: "INTL", label: t("contribution_market_intl") },
  ];

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <Combobox
        label={t("resources_filter_brand")}
        value={value.brand}
        onChange={change("brand")}
        required
        disabled={disabled}
        customHint={t("contribution_custom_value")}
        options={brandOptions}
      />
      <Combobox
        label={t("resources_filter_material")}
        value={value.material_type}
        onChange={change("material_type")}
        required
        disabled={disabled}
        customHint={t("contribution_custom_value")}
        options={MATERIAL_TYPE_OPTIONS}
      />
      <Combobox
        label={t("resources_series")}
        value={value.series}
        onChange={change("series")}
        disabled={disabled}
        customHint={t("contribution_custom_value")}
        options={seriesOptions.map((series) => ({ value: series, label: series }))}
      />
      <FormField
        label={t("resources_color_name")}
        value={value.color_name}
        onChange={change("color_name")}
        required={slot}
        disabled={disabled}
      />
      <FormField
        label={t("resources_product_code")}
        value={value.color_code}
        onChange={change("color_code")}
        disabled={disabled}
        identifier
      />
      <FormField
        label={t("contribution_sku")}
        value={value.sku}
        onChange={change("sku")}
        disabled={disabled}
        identifier
      />
      <details className="sm:col-span-2">
        <DisclosureSummary className="py-1 text-xs font-medium text-slate-600 dark:text-slate-300">
          {t("contribution_regional_names")}
        </DisclosureSummary>
        <div className="mt-2.5 grid gap-3 sm:grid-cols-2">
          <FormField
            label={t("contribution_name_cn")}
            value={value.market_names?.CN || ""}
            onChange={(nextName) => regionalName("CN", nextName)}
            disabled={disabled}
          />
          <FormField
            label={t("contribution_name_intl")}
            value={value.market_names?.INTL || ""}
            onChange={(nextName) => regionalName("INTL", nextName)}
            disabled={disabled}
          />
        </div>
      </details>
      <details className="sm:col-span-2">
        <DisclosureSummary className="py-1 text-xs font-medium text-slate-600 dark:text-slate-300">
          {t("contribution_product_link")}
        </DisclosureSummary>
        <div className="mt-2.5 flex flex-col gap-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField
              label={t("resources_product_page")}
              value={value.purchase_url}
              onChange={change("purchase_url")}
              disabled={disabled}
              type="url"
            />
            <Dropdown
              label={t("contribution_market")}
              value={value.market}
              disabled={disabled}
              onChange={change("market")}
              options={marketOptions}
            />
          </div>
          {value.purchase_links?.map((link, index) => (
            <div
              key={index}
              className="flex min-w-0 flex-col gap-2.5 rounded-[10px] bg-[var(--surface-card)] p-3"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
                  {t("contribution_link_item").replace("{number}", String(index + 2))}
                </span>
                <Button
                  label={t("contribution_remove_link")}
                  variant="ghost"
                  tone="danger"
                  size="sm"
                  disabled={disabled}
                  onClick={() =>
                    onChange({
                      ...value,
                      purchase_links: value.purchase_links?.filter(
                        (_, position) => position !== index,
                      ),
                    })
                  }
                />
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <FormField
                  label={t("resources_product_page")}
                  value={link.url}
                  onChange={(url) => changeLink(index, { url })}
                  required
                  disabled={disabled}
                  type="url"
                />
                <Dropdown
                  label={t("contribution_market")}
                  value={link.market}
                  disabled={disabled}
                  onChange={(market) => changeLink(index, { market })}
                  options={marketOptions}
                />
                <div className="sm:col-span-2">
                  <FormField
                    label={t("contribution_link_label")}
                    value={link.label || ""}
                    onChange={(label) => changeLink(index, { label })}
                    disabled={disabled}
                  />
                </div>
              </div>
            </div>
          ))}
          <div>
            <Button
              label={t("contribution_add_link")}
              variant="secondary"
              size="sm"
              disabled={disabled || (value.purchase_links?.length || 0) >= 7}
              onClick={() =>
                onChange({
                  ...value,
                  purchase_links: [...(value.purchase_links || []), { url: "", market: "ALL" }],
                })
              }
            />
          </div>
        </div>
      </details>
    </div>
  );
}

function ContributionHistoryDialog({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const connection = useCommunityStore((state) => state.connection);
  const [history, setHistory] = useState<ContributionReceipt[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reviewItem, setReviewItem] = useState<QueuedContribution | null>(null);
  const [editingRevision, setEditingRevision] = useState<OwnedRevision | null>(null);
  const [withdrawTarget, setWithdrawTarget] = useState<string | null>(null);
  const [editAfterWithdraw, setEditAfterWithdraw] = useState(false);

  useEffect(() => {
    setHistory([]);
    setWithdrawTarget(null);
  }, [connection?.subject]);

  useEffect(() => {
    if (connection?.state !== "connected") return;
    let active = true;
    setHistoryLoading(true);
    void fetchContributionHistory()
      .then((value) => {
        if (active) setHistory(value);
      })
      .catch((err) => {
        if (active) setError(apiErrorToVisibleMessage(err, t("contribution_failed")));
      })
      .finally(() => {
        if (active) setHistoryLoading(false);
      });
    return () => {
      active = false;
    };
  }, [connection?.state, connection?.subject, t]);

  async function reloadHistory() {
    const subject = useCommunityStore.getState().connection?.subject;
    const rows = await fetchContributionHistory();
    if (subject && useCommunityStore.getState().connection?.subject === subject) setHistory(rows);
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (err) {
      setError(apiErrorToVisibleMessage(err, t("contribution_failed")));
    } finally {
      setBusy(false);
    }
  }

  if (reviewItem) {
    return (
      <ContributionFormDialog
        key={reviewItem.id}
        kind={reviewItem.kind}
        resourceKey={reviewItem.resource_key}
        queueId={reviewItem.id}
        onClose={() => setReviewItem(null)}
      />
    );
  }

  if (editingRevision) {
    return (
      <ContributionFormDialog
        key={`${editingRevision.resource_id}:${editingRevision.revision_id}`}
        kind={editingRevision.kind}
        resourceKey={`revision:${editingRevision.resource_id}:${editingRevision.revision_id}`}
        revision={editingRevision}
        onClose={() => {
          setEditingRevision(null);
          void reloadHistory().catch((err) =>
            setError(apiErrorToVisibleMessage(err, t("contribution_failed"))),
          );
        }}
      />
    );
  }

  return (
    <ResourceDialog title={t("contribution_history")} width="lg" busy={busy} onClose={onClose}>
      <CommunityConnection disabled={busy} />
      <ContributionQueue onReview={setReviewItem} />
      <ResourceReportHistory />

      {error && (
        <StatusBanner tone="error" role="alert">
          <p>{error}</p>
        </StatusBanner>
      )}

      {connection?.state === "connected" && (
        <div className="flex flex-col gap-2.5 border-t border-[var(--surface-divider)] pt-3.5">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
              {t("contribution_history_section")}
            </h3>
            <Button
              label={t("contribution_refresh")}
              variant="ghost"
              size="sm"
              leadingIcon={<ArrowPathIcon className="h-4 w-4" />}
              disabled={busy || historyLoading}
              loading={busy || historyLoading}
              onClick={() => void run(reloadHistory)}
            />
          </div>
          {!historyLoading && !error && history.length === 0 && (
            <p className="py-4 text-center text-xs text-slate-500 dark:text-slate-400">
              {t("contribution_history_empty")}
            </p>
          )}
          {history.map((row) => {
            const rowKey = `${row.kind}:${row.submission_id || row.lut_id}:${row.revision_id}`;
            return (
              <div key={rowKey} className={`${wellClass} flex min-w-0 flex-col gap-2 px-3.5 py-3`}>
                <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                  <p className="min-w-0 flex-1 break-words text-sm font-semibold text-slate-900 dark:text-slate-100">
                    {text(row.display?.material_name || row.display?.name) ||
                      row.lut_id ||
                      row.submission_id}
                  </p>
                  <p className="inline-flex shrink-0 items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
                    <span
                      aria-hidden="true"
                      className={cx("h-2 w-2 rounded-full", submissionStatusDot(row.status))}
                    />
                    <span>
                      {t(row.kind === "materials" ? "contribution_material" : "contribution_lut")} ·{" "}
                      {formatSubmissionStatus(t, row.status)}
                    </span>
                  </p>
                </div>
                {row.latest_decision?.comment && (
                  <p className="rounded-r-lg border-l-2 border-amber-400/70 bg-[var(--surface-card)] px-3 py-2 text-xs leading-5 text-slate-700 dark:text-slate-200">
                    {row.latest_decision.comment}
                  </p>
                )}
                <div className="flex flex-wrap items-center justify-between gap-2 pt-0.5">
                  <a
                    href={`${connection.web_url}/#/${row.kind === "luts" ? "luts" : "submissions"}`}
                    target="_blank"
                    rel="noreferrer"
                    className={`${actionLinkClass} ghost-control -ml-2.5 min-h-8 px-2.5 py-1 text-xs`}
                  >
                    <ArrowTopRightOnSquareIcon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                    {t("contribution_manage")}
                  </a>
                  {row.revision_id && (row.material_id || row.lut_id) && (
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Button
                        label={t("contribution_edit_revision")}
                        variant="ghost"
                        size="sm"
                        disabled={busy || historyLoading}
                        onClick={() => {
                          if (row.status === "pending") {
                            setEditAfterWithdraw(true);
                            setWithdrawTarget(rowKey);
                          } else {
                            setEditingRevision({
                              kind: row.kind,
                              resource_id: row.material_id || row.lut_id!,
                              revision_id: row.revision_id!,
                            });
                          }
                        }}
                      />
                      {row.status === "pending" && (
                        <Button
                          label={t("contribution_withdraw")}
                          variant="ghost"
                          size="sm"
                          disabled={busy || historyLoading}
                          onClick={() => {
                            setEditAfterWithdraw(false);
                            setWithdrawTarget(rowKey);
                          }}
                        />
                      )}
                      {["draft", "withdrawn"].includes(row.status) && (
                        <Button
                          label={t("contribution_resubmit")}
                          variant="secondary"
                          size="sm"
                          disabled={busy || historyLoading}
                          onClick={() =>
                            void run(async () => {
                              const subject = connection.subject;
                              if (!subject) return;
                              await changeContributionReview(
                                {
                                  kind: row.kind,
                                  resource_id: row.material_id || row.lut_id!,
                                  revision_id: row.revision_id!,
                                },
                                subject,
                                "submit",
                              );
                              await reloadHistory();
                            })
                          }
                        />
                      )}
                    </div>
                  )}
                </div>
                {withdrawTarget === rowKey && (
                  <div className="mt-1 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-[var(--surface-card)] px-3 py-2.5">
                    <p className="text-xs leading-5 text-slate-600 dark:text-slate-300">
                      {t("contribution_withdraw_hint")}
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      <Button
                        label={t("common_cancel")}
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        onClick={() => setWithdrawTarget(null)}
                      />
                      <Button
                        label={t("contribution_withdraw_confirm")}
                        tone="danger"
                        size="sm"
                        loading={busy}
                        onClick={() =>
                          void run(async () => {
                            const subject = connection.subject;
                            if (!subject) return;
                            await changeContributionReview(
                              {
                                kind: row.kind,
                                resource_id: row.material_id || row.lut_id!,
                                revision_id: row.revision_id!,
                              },
                              subject,
                              "withdraw",
                            );
                            setWithdrawTarget(null);
                            await reloadHistory();
                            if (
                              editAfterWithdraw &&
                              useCommunityStore.getState().connection?.subject === subject
                            ) {
                              setEditingRevision({
                                kind: row.kind,
                                resource_id: row.material_id || row.lut_id!,
                                revision_id: row.revision_id!,
                              });
                            }
                          })
                        }
                      />
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </ResourceDialog>
  );
}

function ContributionFormDialog({
  kind,
  resourceKey,
  initialDisplay,
  onClose,
  queueId,
  revision,
}: {
  kind: ResourceKind;
  resourceKey: string;
  initialDisplay?: Record<string, unknown>;
  onClose: () => void;
  queueId?: string;
  revision?: OwnedRevision;
}) {
  const { t, lang } = useI18n();
  const descriptionId = useId();
  const rightsBasisId = useId();
  const initial = useRef(initialDisplay);
  const connection = useCommunityStore((state) => state.connection);
  const [prepared, setPrepared] = useState<PreparedContribution | null>(null);
  const [prepareAttempt, setPrepareAttempt] = useState(0);
  const [product, setProduct] = useState<ContributionProduct>(() => productFrom({}));
  const [filaments, setFilaments] = useState<ContributionProduct[]>([]);
  const [openSlots, setOpenSlots] = useState<Record<number, boolean>>({});
  const [localMaterials, setLocalMaterials] = useState<SavedMaterialLibraryItem[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [attribution, setAttribution] = useState<ContributionAttribution | null>(null);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [receipt, setReceipt] = useState<ContributionReceipt | null>(null);
  const [profileSelections, setProfileSelections] = useState<Record<number, string>>({});
  const [updatesResourceId, setUpdatesResourceId] = useState("");
  const [updateHistory, setUpdateHistory] = useState<ContributionReceipt[] | null>(null);
  const [updateHistoryLoading, setUpdateHistoryLoading] = useState(false);
  const revisionAccount = revision ? connection?.subject : undefined;

  const brandOptions = useMemo(
    () =>
      filamentBrands.map((brand) => ({
        value: brand.intl,
        label:
          lang === "zh" && brand.cn !== brand.intl ? `${brand.cn} · ${brand.intl}` : brand.intl,
        keywords: [brand.cn, ...(brand.aliases || [])].join(" "),
      })),
    [lang],
  );

  const seriesByBrand = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const row of localMaterials) {
      const series = text(row.display?.series);
      if (!series) continue;
      const brand = productFrom({ ...row, ...row.display }).brand;
      const list = map.get(brand);
      if (list) {
        if (!list.includes(series)) list.push(series);
      } else {
        map.set(brand, [series]);
      }
    }
    return map;
  }, [localMaterials]);

  useEffect(() => {
    let active = true;
    if (revision && !revisionAccount) {
      setPrepared(null);
      return;
    }
    setError("");
    if (revision) setPrepared(null);
    void (revision
      ? prepareContributionRevision(revision, revisionAccount!)
      : queueId
        ? prepareQueuedContribution(queueId)
        : prepareContribution(kind, resourceKey)
    )
      .then((value) => {
        if (!active) return;
        const display = { ...value.display, ...initial.current };
        setPrepared(value);
        setProduct(productFrom(display));
        setName(text(display.material_name || display.name) || resourceKey);
        setDescription(text(display.description));
        const prior = value.display.attribution as Record<string, unknown> | undefined;
        setAttribution(
          value.origin
            ? {
                relationship: value.origin.modified ? "adapted" : "redistributed",
                original_author: text(prior?.original_author) || value.origin.original_author,
                source_url: text(prior?.source_url),
                rights_basis: text(prior?.rights_basis) || value.origin.rights_basis,
              }
            : (queueId || revision) && prior?.relationship === "original"
              ? { relationship: "original" }
              : null,
        );
        const parsedSlots = value.display.filaments || [];
        const suppliedSlots = Array.isArray(initial.current?.filaments)
          ? initial.current.filaments.filter(
              (row): row is Record<string, unknown> =>
                !!row && typeof row === "object" && !Array.isArray(row),
            )
          : [];
        const slotIds = suppliedSlots.map((row) => row.slot);
        const bySlot =
          suppliedSlots.length === parsedSlots.length &&
          new Set(slotIds).size === parsedSlots.length &&
          slotIds.every(
            (slot) =>
              typeof slot === "number" &&
              Number.isInteger(slot) &&
              slot >= 0 &&
              slot < parsedSlots.length,
          )
            ? new Map(suppliedSlots.map((row) => [row.slot, row]))
            : new Map();
        const nextFilaments = parsedSlots.map((parsedSlot) => {
          const slot = { ...parsedSlot, ...bySlot.get(parsedSlot.slot) };
          return productFrom({
            ...display,
            ...slot,
            material_name: "",
            name: "",
            purchase_links: slot.purchase_links,
          });
        });
        setFilaments(nextFilaments);
        setOpenSlots(
          Object.fromEntries(
            nextFilaments.map((slot, index) => [
              index,
              nextFilaments.length <= 2 || index === 0 || !slot.brand || !slot.color_name,
            ]),
          ),
        );
      })
      .catch((err) => {
        if (!active) return;
        setError(
          err?.response?.status === 422
            ? t("contribution_prepare_invalid")
            : apiErrorToVisibleMessage(err, t("contribution_failed")),
        );
      });
    void listGradientCardMaterials()
      .then((value) => {
        if (active) setLocalMaterials(value.materials);
      })
      .catch(() => {
        /* Manual product fields remain available. */
      });
    return () => {
      active = false;
    };
  }, [kind, resourceKey, queueId, t, prepareAttempt, revision, revisionAccount]);

  useEffect(() => {
    setConsent(false);
    setReceipt(null);
    setUpdateHistory(null);
    setUpdatesResourceId("");
  }, [connection?.subject]);

  const fieldDisabled = busy || !!receipt;
  const attributionReady =
    attribution &&
    (attribution.relationship === "original" ||
      (attribution.original_author?.trim() &&
        attribution.rights_basis?.trim() &&
        (prepared?.origin?.reference || attribution.source_url?.trim())));
  const changeAttribution = (next: ContributionAttribution) => {
    setAttribution(next);
    setConsent(false);
  };

  return (
    <ResourceDialog
      title={t(revision ? "contribution_edit_revision" : "contribution_open")}
      width="lg"
      busy={busy}
      onClose={onClose}
      onSubmit={(event) => {
        event.preventDefault();
        const accountId = connection?.subject;
        if (!prepared || !consent || !attribution || !attributionReady || !accountId || busy || receipt) {
          return;
        }
        setBusy(true);
        setError("");
        void submitContribution({
          kind,
          key: prepared.key,
          fingerprint: prepared.fingerprint,
          name,
          description,
          product,
          filaments,
          consent: true,
          account_id: accountId,
          attribution,
          ...(queueId ? { queue_id: queueId } : {}),
          ...(revision ? { revision } : {}),
          ...(updatesResourceId ? { updates_resource_id: updatesResourceId } : {}),
        })
          .then((result) => {
            if (useCommunityStore.getState().connection?.subject === accountId) setReceipt(result);
          })
          .catch((err) => setError(apiErrorToVisibleMessage(err, t("contribution_failed"))))
          .finally(() => setBusy(false));
      }}
      footer={
        !receipt ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            {connection?.web_url ? (
              <a
                href={`${connection.web_url}/#/${kind === "luts" ? "luts" : "submissions"}`}
                target="_blank"
                rel="noreferrer"
                className={`${actionLinkClass} ghost-control -ml-2.5 min-h-8 px-2.5 py-1 text-xs`}
              >
                <ArrowTopRightOnSquareIcon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                {t("contribution_web_history")}
              </a>
            ) : (
              <span />
            )}
            <Button
              label={t("contribution_submit")}
              variant="primary"
              type="submit"
              className="w-full sm:w-auto"
              loading={busy}
              disabled={!prepared || !attributionReady || !consent || connection?.state !== "connected"}
            />
          </div>
        ) : undefined
      }
    >
      <CommunityConnection disabled={busy} compact />

      {error && (
        <StatusBanner tone="error" role="alert">
          <p>{error}</p>
          {!prepared && (
            <Button
              label={t("contribution_retry_prepare")}
              variant="ghost"
              size="sm"
              className="mt-2"
              onClick={() => setPrepareAttempt((value) => value + 1)}
            />
          )}
        </StatusBanner>
      )}

      {receipt ? (
        <StatusBanner tone="success">
          <p>
            {t(receipt.status === "queued" ? "contribution_queue_confirmed" : "contribution_received")} ·{" "}
            {formatSubmissionStatus(t, receipt.status)}
          </p>
        </StatusBanner>
      ) : prepared ? (
        <>
          <div
            className={`${wellClass} flex min-w-0 flex-col items-start gap-3.5 px-4 py-3.5 sm:flex-row sm:items-center`}
          >
            <CalibrationThumbnail
              kind={kind}
              name={prepared.key}
              resourceKey={prepared.key}
              size="md"
              mode={text(prepared.compatibility.color_mode)}
              rgb={prepared.display.estimated_rgb}
              display={{ ...prepared.display, ...initial.current }}
            />
            <div className="min-w-0 flex-1 space-y-1">
              <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
                {name || prepared.key}
              </p>
              <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-slate-500 dark:text-slate-400">
                <span>{t(kind === "materials" ? "contribution_material" : "contribution_lut")}</span>
                <span>·</span>
                <span>
                  {t("contribution_size").replace("{size}", (prepared.bytes / 1024).toFixed(1))}
                </span>
                {text(prepared.compatibility.color_mode) && (
                  <>
                    <span>·</span>
                    <span>
                      {resourceColorMode(text(prepared.compatibility.color_mode), lang) ||
                        text(prepared.compatibility.color_mode)}
                    </span>
                  </>
                )}
                {typeof prepared.compatibility.layer_height_mm === "number" && (
                  <>
                    <span>·</span>
                    <span>
                      {t("contribution_layer_height").replace(
                        "{height}",
                        String(prepared.compatibility.layer_height_mm),
                      )}
                    </span>
                  </>
                )}
              </p>
            </div>
          </div>

          <FormField
            label={t("contribution_name")}
            value={name}
            onChange={setName}
            required
            disabled={fieldDisabled}
          />

          {kind === "materials" && (
            <ProductFields
              value={product}
              onChange={setProduct}
              disabled={fieldDisabled}
              brandOptions={brandOptions}
              seriesByBrand={seriesByBrand}
            />
          )}

          {kind === "luts" && (
            <div className="flex flex-col gap-2.5 border-t border-[var(--surface-divider)] pt-4">
              <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                {t("resources_used_colors")}
              </p>
              {filaments.map((slot, index) => {
                const slotSummary = [slot.brand, slot.material_type, slot.series]
                  .filter(Boolean)
                  .join(" · ");
                return (
                  <details
                    key={index}
                    open={Boolean(openSlots[index])}
                    onToggle={(event) => {
                      if (event.target === event.currentTarget) {
                        const isOpen = event.currentTarget.open;
                        setOpenSlots((rows) => ({ ...rows, [index]: isOpen }));
                      }
                    }}
                    className={`${wellClass} px-3.5 py-2.5`}
                  >
                    <DisclosureSummary className="py-1 text-sm font-medium text-slate-800 dark:text-slate-100">
                      <span className="flex min-w-0 flex-wrap items-center gap-2">
                        <span className="inline-flex h-5 min-w-5 items-center justify-center rounded bg-[var(--surface-card)] px-1.5 text-xs font-semibold tabular-nums text-slate-600 dark:text-slate-300">
                          {index + 1}
                        </span>
                        <span className="font-medium">
                          {slot.color_name || t("resources_colors_missing")}
                        </span>
                        {slotSummary && (
                          <span className="truncate text-xs font-normal text-slate-500 dark:text-slate-400">
                            {slotSummary}
                          </span>
                        )}
                      </span>
                    </DisclosureSummary>
                    <div className="mt-3 flex flex-col gap-3 border-t border-[var(--surface-divider)] pt-3">
                      {localMaterials.length > 0 && (
                        <Dropdown
                          label={t("contribution_use_profile")}
                          value={profileSelections[index] || ""}
                          disabled={fieldDisabled}
                          onChange={(value) => {
                            setProfileSelections((rows) => ({ ...rows, [index]: value }));
                            const item = localMaterials.find((row) => row.directory_name === value);
                            if (item) {
                              setFilaments((rows) =>
                                rows.map((row, position) =>
                                  position === index
                                    ? productFrom({
                                        ...item,
                                        ...item.display,
                                        material_id: item.sync_material_id,
                                        revision_id: item.sync_revision_id,
                                      })
                                    : row,
                                ),
                              );
                            }
                          }}
                          options={[
                            { value: "", label: t("contribution_manual") },
                            ...localMaterials.map((item) => ({
                              value: item.directory_name,
                              label: `${item.brand} · ${item.material_name}`,
                            })),
                          ]}
                        />
                      )}
                      <ProductFields
                        value={slot}
                        onChange={(next) => {
                          setProfileSelections((rows) => ({ ...rows, [index]: "" }));
                          setFilaments((rows) =>
                            rows.map((row, position) => (position === index ? next : row)),
                          );
                        }}
                        disabled={fieldDisabled}
                        slot
                        brandOptions={brandOptions}
                        seriesByBrand={seriesByBrand}
                      />
                    </div>
                  </details>
                );
              })}
            </div>
          )}

          <div className="flex min-w-0 flex-col gap-1.5">
            <label htmlFor={descriptionId} className={workstationFieldLabelClass}>
              {t("resources_description")}
            </label>
            <textarea
              id={descriptionId}
              rows={3}
              maxLength={2000}
              className={workstationInputClass}
              value={description}
              disabled={fieldDisabled}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>

          <div className="flex flex-col gap-3 border-t border-[var(--surface-divider)] pt-4">
            <Dropdown
              label={t("contribution_origin")}
              value={attribution?.relationship || ""}
              disabled={fieldDisabled}
              placeholder={t("contribution_origin_choose")}
              onChange={(relationship) =>
                changeAttribution({
                  ...attribution,
                  relationship: relationship as ContributionAttribution["relationship"],
                })
              }
              options={[
                ...(!prepared.origin
                  ? [{ value: "original", label: t("contribution_origin_original") }]
                  : []),
                { value: "adapted", label: t("contribution_origin_adapted") },
                { value: "redistributed", label: t("contribution_origin_redistributed") },
              ]}
            />
            {prepared.origin &&
              (prepared.origin.reference ? (
                <details className="text-xs text-slate-500 dark:text-slate-400">
                  <DisclosureSummary className="py-0.5">
                    {t("contribution_origin_linked")}
                  </DisclosureSummary>
                  <p className="mt-1.5 select-all break-all font-mono text-[11px]">
                    {prepared.origin.reference.resource_id} · {prepared.origin.reference.revision_id}
                  </p>
                </details>
              ) : (
                <p className="text-xs text-amber-600 dark:text-amber-400">
                  {t("contribution_origin_ambiguous")}
                </p>
              ))}
            {attribution && attribution.relationship !== "original" && (
              <div className={`${wellClass} grid gap-3 p-3.5 sm:grid-cols-2`}>
                <FormField
                  label={t("contribution_original_author")}
                  value={attribution.original_author || ""}
                  onChange={(original_author) => changeAttribution({ ...attribution, original_author })}
                  required
                  disabled={fieldDisabled}
                />
                <FormField
                  label={t("contribution_source_url")}
                  value={attribution.source_url || ""}
                  onChange={(source_url) => changeAttribution({ ...attribution, source_url })}
                  required={!prepared.origin?.reference}
                  disabled={fieldDisabled}
                  type="url"
                />
                <div className="flex min-w-0 flex-col gap-1.5 sm:col-span-2">
                  <label htmlFor={rightsBasisId} className={workstationFieldLabelClass}>
                    {t("contribution_rights_basis")} *
                  </label>
                  <textarea
                    id={rightsBasisId}
                    rows={2}
                    maxLength={1000}
                    required
                    className={workstationInputClass}
                    value={attribution.rights_basis || ""}
                    disabled={fieldDisabled}
                    onChange={(event) =>
                      changeAttribution({ ...attribution, rights_basis: event.target.value })
                    }
                  />
                </div>
              </div>
            )}
          </div>

          {!revision && !queueId && connection?.state === "connected" && (
            <details
              className={`${wellClass} px-3.5 py-2.5 text-sm`}
              onToggle={(event) => {
                if (
                  event.target !== event.currentTarget ||
                  !event.currentTarget.open ||
                  updateHistory ||
                  updateHistoryLoading
                ) {
                  return;
                }
                setUpdateHistoryLoading(true);
                const subject = connection.subject;
                void fetchContributionHistory()
                  .then((rows) => {
                    if (useCommunityStore.getState().connection?.subject === subject) {
                      setUpdateHistory(rows);
                    }
                  })
                  .catch((err) =>
                    setError(apiErrorToVisibleMessage(err, t("contribution_failed"))),
                  )
                  .finally(() => setUpdateHistoryLoading(false));
              }}
            >
              <DisclosureSummary className="py-0.5 text-xs font-medium text-slate-600 dark:text-slate-300">
                {t("contribution_update_existing")}
              </DisclosureSummary>
              <div className="mt-2.5 flex flex-col gap-2 border-t border-[var(--surface-divider)] pt-2.5">
                <Dropdown
                  label={t("contribution_update_target")}
                  value={updatesResourceId}
                  disabled={fieldDisabled || updateHistoryLoading}
                  onChange={(value) => {
                    setUpdatesResourceId(value);
                    setConsent(false);
                  }}
                  options={[
                    { value: "", label: t("contribution_new_resource") },
                    ...Array.from(
                      new Map(
                        (updateHistory || [])
                          .filter((row) => row.kind === kind && (row.material_id || row.lut_id))
                          .map((row) => [row.material_id || row.lut_id!, row]),
                      ).values(),
                    ).map((row) => ({
                      value: row.material_id || row.lut_id!,
                      label:
                        text(row.display?.material_name || row.display?.name) ||
                        row.material_id ||
                        row.lut_id!,
                    })),
                  ]}
                />
                <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">
                  {t("contribution_update_hint")}
                </p>
              </div>
            </details>
          )}

          <div className="border-t border-[var(--surface-divider)] pt-3">
            <Checkbox
              label={t(attribution?.relationship === "original" && !text(prepared?.display.license).trim()
                ? "contribution_original_consent" : "contribution_consent")}
              appearance="checkbox"
              checked={consent}
              onChange={setConsent}
              disabled={fieldDisabled}
            />
            <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
              {t("resources_license")}：{" "}
              <ResourceLicense license={prepared?.display.license || (attribution?.relationship === "original" ? "LicenseRef-Lumina-Data-1.0" : undefined)} />
            </div>
            <div className="mt-2"><DataLicenseLink /></div>
            {revision && (
              <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">
                {t("contribution_revision_hint")}
              </p>
            )}
          </div>
        </>
      ) : !error ? (
        <p role="status" className="py-6 text-center text-sm text-slate-500 dark:text-slate-400">
          {t("contribution_preparing")}
        </p>
      ) : null}
    </ResourceDialog>
  );
}

export function ContributionDialog({
  kind,
  resourceKey,
  initialDisplay,
  onClose,
  queueId,
  revision,
}: {
  kind: ResourceKind;
  resourceKey?: string;
  initialDisplay?: Record<string, unknown>;
  onClose: () => void;
  queueId?: string;
  revision?: OwnedRevision;
}) {
  if (!resourceKey) {
    return <ContributionHistoryDialog onClose={onClose} />;
  }
  return (
    <ContributionFormDialog
      kind={kind}
      resourceKey={resourceKey}
      initialDisplay={initialDisplay}
      onClose={onClose}
      queueId={queueId}
      revision={revision}
    />
  );
}
