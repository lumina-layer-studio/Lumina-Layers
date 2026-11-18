import { useEffect, useId, useRef, useState } from "react";
import { isAxiosError } from "axios";
import { ChatBubbleLeftRightIcon, PhotoIcon, XMarkIcon } from "@heroicons/react/24/outline";
import { apiErrorToVisibleMessage } from "../api/client";
import {
  fetchMyResourceReports,
  fetchResourceContributor,
  submitResourceReport,
} from "../api/community";
import type { ResourceContributor, ResourceReference, ResourceReport } from "../api/community";
import type { ResourceKind } from "../api/resources";
import { useI18n } from "../i18n/context";
import { useCommunityStore } from "../stores/communityStore";
import { MAX_FEEDBACK_IMAGES, prepareFeedbackImage } from "../utils/feedbackImages";
import { CommunityConnection } from "./CommunityAccount";
import { ResourceReportCard } from "./ResourceReportSupplements";
import Button from "./ui/Button";
import DisclosureSummary from "./ui/DisclosureSummary";
import Dropdown from "./ui/Dropdown";
import ResourceDialog from "./ui/ResourceDialog";
import {
  cx,
  StatusBanner,
  wellClass,
  workstationFieldLabelClass,
  workstationInputClass,
} from "./ui/panelPrimitives";

const requestId = () => crypto.randomUUID().replaceAll("-", "");
const categories = ["attribution", "incorrect_data", "unsafe_link", "other"] as const;

export default function ResourceFeedback({
  kind,
  resource,
}: {
  kind: ResourceKind;
  resource: ResourceReference;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        label={t("resource_feedback_open")}
        variant="ghost"
        size="sm"
        leadingIcon={<ChatBubbleLeftRightIcon className="h-4 w-4" />}
        className="w-full justify-center"
        onClick={() => setOpen(true)}
      />
      {open && (
        <FeedbackDialog
          key={`${kind}:${resource.resource_id}:${resource.revision_id}:${resource.content_hash}`}
          kind={kind}
          resource={resource}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

export function FeedbackDialog({
  kind,
  resource,
  onClose,
}: {
  kind: ResourceKind;
  resource: ResourceReference;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const messageInputId = useId();
  const evidenceInputId = useId();
  const connection = useCommunityStore((state) => state.connection);
  const subject = connection?.state === "connected" ? connection.subject : undefined;
  const verified = Boolean(subject && connection?.email_verified);
  const [contributor, setContributor] = useState<ResourceContributor | null>();
  const [contributorError, setContributorError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [reports, setReports] = useState<ResourceReport[]>([]);
  const [reportsSubject, setReportsSubject] = useState<string>();
  const [category, setCategory] = useState<ResourceReport["category"]>("attribution");
  const [message, setMessage] = useState("");
  const [evidence, setEvidence] = useState("");
  const [supplementsOpen, setSupplementsOpen] = useState(false);
  const [images, setImages] = useState<{ key: string; data: string }[]>([]);
  const [preparingImages, setPreparingImages] = useState(false);
  const imageInput = useRef<HTMLInputElement>(null);
  const formEpoch = useRef(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [id, setId] = useState(requestId);
  const mounted = useRef(false);
  const { resource_id, revision_id, content_hash } = resource;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    setContributorError("");
    void fetchResourceContributor(kind, { resource_id, revision_id, content_hash })
      .then((result) => {
        if (active) setContributor(result.contributor);
      })
      .catch((err) => {
        if (active) setContributorError(apiErrorToVisibleMessage(err, t("resource_feedback_load_failed")));
      });
    return () => {
      active = false;
    };
  }, [kind, resource_id, revision_id, content_hash, t, attempt]);

  useEffect(() => {
    let active = true;
    formEpoch.current += 1;
    setReports([]);
    setError("");
    setMessage("");
    setEvidence("");
    setImages([]);
    setPreparingImages(false);
    setSupplementsOpen(false);
    setId(requestId());
    if (subject) {
      void fetchMyResourceReports(kind, { resource_id, revision_id, content_hash })
        .then((result) => {
          if (
            active &&
            result.subject === subject &&
            useCommunityStore.getState().connection?.subject === subject
          ) {
            setReports(result.items);
            setReportsSubject(subject);
          }
        })
        .catch((err) => {
          if (active) setError(apiErrorToVisibleMessage(err, t("resource_feedback_load_failed")));
        });
    }
    return () => {
      active = false;
    };
  }, [subject, kind, resource_id, revision_id, content_hash, t]);

  const visibleReports = reportsSubject === subject ? reports : [];
  const openReport = visibleReports.some((row) => row.status === "open");
  const trimmedLength = message.trim().length;

  const addImages = async (files: File[]) => {
    if (!files.length || busy || preparingImages) return;
    setSupplementsOpen(true);
    if (images.length + files.length > MAX_FEEDBACK_IMAGES) {
      setError(t("resource_feedback_image_limit"));
      return;
    }
    const epoch = formEpoch.current;
    setPreparingImages(true);
    setError("");
    try {
      const prepared: { key: string; data: string }[] = [];
      for (const file of files) {
        prepared.push({ key: requestId(), data: await prepareFeedbackImage(file) });
      }
      if (mounted.current && epoch === formEpoch.current) {
        setImages((previous) => [...previous, ...prepared]);
        setId(requestId());
      }
    } catch (err) {
      if (mounted.current && epoch === formEpoch.current) {
        setError(
          t(
            err instanceof Error && err.message.startsWith("resource_feedback_image_")
              ? err.message
              : "resource_feedback_image_failed",
          ),
        );
      }
    } finally {
      if (mounted.current && epoch === formEpoch.current) setPreparingImages(false);
    }
  };

  return (
    <ResourceDialog
      title={t("resource_feedback_title")}
      onClose={onClose}
      busy={busy || preparingImages}
      footer={
        subject && verified && !openReport ? (
          <div className="flex justify-end">
            <Button
              label={t("resource_feedback_submit")}
              type="submit"
              variant="primary"
              className="w-full sm:w-auto"
              loading={busy}
              disabled={busy || preparingImages || trimmedLength < 10}
            />
          </div>
        ) : undefined
      }
      onSubmit={async (event) => {
        event.preventDefault();
        if (!subject || !verified || busy || preparingImages || openReport || trimmedLength < 10) {
          return;
        }
        setBusy(true);
        setError("");
        try {
          const result = await submitResourceReport(kind, resource, {
            account_id: subject,
            request_id: id,
            category,
            message: message.trim(),
            evidence_url: evidence.trim(),
            ...(images.length ? { images: images.map((image) => image.data) } : {}),
          });
          if (
            mounted.current &&
            result.subject === subject &&
            useCommunityStore.getState().connection?.subject === subject
          ) {
            setReports((rows) => [
              result.item,
              ...rows.filter((row) => row.report_id !== result.item.report_id),
            ]);
            setReportsSubject(subject);
            setMessage("");
            setEvidence("");
            setImages([]);
            setSupplementsOpen(false);
            setId(requestId());
          }
        } catch (err) {
          if (mounted.current && useCommunityStore.getState().connection?.subject === subject) {
            setError(
              images.length && isAxiosError(err) && [413, 422].includes(err.response?.status || 0)
                ? t("resource_feedback_image_upload_failed")
                : apiErrorToVisibleMessage(err, t("resource_feedback_submit_failed")),
            );
          }
        } finally {
          if (mounted.current) setBusy(false);
        }
      }}
    >
      <section className={`${wellClass} flex min-w-0 flex-col gap-2.5 px-3.5 py-3`}>
        {contributor === undefined && !contributorError && (
          <p role="status" className="text-xs text-slate-500 dark:text-slate-400">
            {t("common_loading")}
          </p>
        )}
        {contributor && (
          <div className="min-w-0">
            <span className="text-[11px] text-slate-500 dark:text-slate-400">
              {t("resource_feedback_contributor")}
            </span>
            <p className="min-w-0 break-words text-sm font-semibold text-slate-900 dark:text-slate-100">
              {contributor.display_name}
            </p>
          </div>
        )}
        {contributor === null && (
          <div>
            <span className="text-[11px] text-slate-500 dark:text-slate-400">
              {t("resource_feedback_contributor")}
            </span>
            <p className="text-sm text-slate-600 dark:text-slate-300">
              {t("resource_feedback_legacy")}
            </p>
          </div>
        )}
        {contributorError && (
          <StatusBanner
            tone="warning"
            action={
              <Button
                label={t("resources_retry")}
                variant="ghost"
                size="sm"
                onClick={() => setAttempt((value) => value + 1)}
              />
            }
          >
            {contributorError}
          </StatusBanner>
        )}
        <details className="min-w-0 border-t border-[var(--surface-divider)] pt-2 text-xs text-slate-500 dark:text-slate-400">
          <DisclosureSummary className="py-0.5 text-[11px]">
            {t("resource_feedback_meta_toggle")}
          </DisclosureSummary>
          <dl className="mt-2 grid gap-1.5 text-[11px]">
            {contributor && (
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <dt className="text-slate-500 dark:text-slate-400">
                  {t("resource_feedback_identity")}
                </dt>
                <dd className="select-all break-all font-mono text-slate-700 dark:text-slate-300">
                  {contributor.id}
                </dd>
              </div>
            )}
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <dt className="text-slate-500 dark:text-slate-400">{t("resource_feedback_target")}</dt>
              <dd className="select-all break-all font-mono text-right text-slate-700 dark:text-slate-300">
                {resource.resource_id} · {resource.revision_id}
              </dd>
            </div>
          </dl>
        </details>
      </section>

      {visibleReports.length > 0 && (
        <div className="flex flex-col gap-2.5" aria-label={t("resource_feedback_receipts")}>
          {visibleReports.map((row) => (
            <ResourceReportCard
              key={row.report_id}
              report={row}
              subtitle={t(`resource_feedback_category_${row.category}`)}
            />
          ))}
        </div>
      )}

      {!subject || !verified ? (
        <div className="flex flex-col gap-2.5 border-t border-[var(--surface-divider)] pt-3">
          {subject && (
            <p className="text-xs font-medium text-amber-600 dark:text-amber-400">
              {t("resource_feedback_verify_email")}
            </p>
          )}
          <CommunityConnection disabled={busy || preparingImages} requireVerifiedEmail />
        </div>
      ) : (
        !openReport && (
          <section
            className={cx(
              "flex min-w-0 flex-col gap-4",
              visibleReports.length > 0 && "border-t border-[var(--surface-divider)] pt-4",
            )}
            onPaste={(event) => {
              const files = Array.from(event.clipboardData.files).filter((file) =>
                file.type.startsWith("image/"),
              );
              if (files.length) {
                event.preventDefault();
                void addImages(files);
              }
            }}
            onDragOver={(event) => {
              if (event.dataTransfer.types.includes("Files")) event.preventDefault();
            }}
            onDrop={(event) => {
              if (event.dataTransfer.files.length) {
                event.preventDefault();
                void addImages(Array.from(event.dataTransfer.files));
              }
            }}
          >
            <Dropdown
              label={t("resource_feedback_category")}
              value={category}
              disabled={busy || preparingImages}
              options={categories.map((value) => ({
                value,
                label: t(`resource_feedback_category_${value}`),
              }))}
              onChange={(value) => {
                setCategory(value as ResourceReport["category"]);
                setId(requestId());
              }}
            />
            <div className="flex min-w-0 flex-col gap-1.5">
              <div className="flex items-baseline justify-between gap-2">
                <label htmlFor={messageInputId} className={workstationFieldLabelClass}>
                  {t("resource_feedback_message")}
                </label>
                <span className="text-xs tabular-nums text-slate-400 dark:text-slate-500">
                  {trimmedLength > 0 && trimmedLength < 10
                    ? `${trimmedLength} / 10`
                    : t("resource_feedback_min_length")}
                </span>
              </div>
              <textarea
                id={messageInputId}
                name="feedback_message"
                className={`${workstationInputClass} min-h-24 resize-y`}
                required
                minLength={10}
                maxLength={2000}
                placeholder={t("resource_feedback_message_placeholder")}
                value={message}
                disabled={busy || preparingImages}
                onChange={(event) => {
                  setMessage(event.target.value);
                  setId(requestId());
                }}
              />
            </div>
            <details
              open={supplementsOpen}
              onToggle={(event) => {
                if (event.target === event.currentTarget) {
                  setSupplementsOpen(event.currentTarget.open);
                }
              }}
              className={`${wellClass} min-w-0 px-3.5 py-2.5 text-sm`}
            >
              <DisclosureSummary className="py-0.5 text-xs font-medium text-slate-600 dark:text-slate-300">
                {t("resource_feedback_supplements")}
              </DisclosureSummary>
              <div className="mt-3 flex min-w-0 flex-col gap-3.5 border-t border-[var(--surface-divider)] pt-3">
                <div className="flex flex-wrap items-center gap-2.5">
                  <input
                    ref={imageInput}
                    type="file"
                    accept="image/jpeg,image/png,image/webp"
                    multiple
                    className="hidden"
                    aria-label={t("resource_feedback_add_image")}
                    disabled={busy || preparingImages}
                    onChange={(event) => {
                      const files = Array.from(event.target.files || []);
                      event.target.value = "";
                      void addImages(files);
                    }}
                  />
                  <Button
                    label={t("resource_feedback_add_image")}
                    variant="secondary"
                    size="sm"
                    leadingIcon={<PhotoIcon className="h-4 w-4" />}
                    loading={preparingImages}
                    disabled={busy || preparingImages || images.length >= MAX_FEEDBACK_IMAGES}
                    onClick={() => imageInput.current?.click()}
                  />
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    {t("resource_feedback_image_hint")}
                  </span>
                </div>
                {images.length > 0 && (
                  <div className="grid grid-cols-3 gap-2.5">
                    {images.map((image, index) => (
                      <figure
                        key={image.key}
                        className="group relative overflow-hidden rounded-lg bg-[var(--surface-card)] p-1"
                      >
                        <img
                          src={`data:image/jpeg;base64,${image.data}`}
                          alt={t("resource_feedback_image_number").replace(
                            "{number}",
                            String(index + 1),
                          )}
                          className="h-24 w-full rounded object-contain"
                        />
                        <button
                          type="button"
                          aria-label={t("resource_feedback_remove_image")}
                          disabled={busy || preparingImages}
                          onClick={() => {
                            setImages((previous) =>
                              previous.filter((value) => value.key !== image.key),
                            );
                            setId(requestId());
                          }}
                          className="absolute right-1.5 top-1.5 inline-flex h-6 w-6 items-center justify-center rounded-full bg-slate-900/70 text-slate-50 transition-colors hover:bg-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] disabled:opacity-45"
                        >
                          <XMarkIcon className="h-3.5 w-3.5" aria-hidden="true" />
                        </button>
                      </figure>
                    ))}
                  </div>
                )}
                <div className="flex min-w-0 flex-col gap-1.5">
                  <label htmlFor={evidenceInputId} className={workstationFieldLabelClass}>
                    {t("resource_feedback_evidence")}
                  </label>
                  <input
                    id={evidenceInputId}
                    name="evidence_url"
                    autoCorrect="off"
                    autoCapitalize="none"
                    spellCheck={false}
                    className={workstationInputClass}
                    type="url"
                    pattern="https://.*"
                    maxLength={2048}
                    value={evidence}
                    disabled={busy || preparingImages}
                    placeholder={t("resource_feedback_url_example")}
                    onInvalid={() => setSupplementsOpen(true)}
                    onChange={(event) => {
                      setEvidence(event.target.value);
                      setId(requestId());
                    }}
                  />
                </div>
              </div>
            </details>
          </section>
        )
      )}
      {error && <StatusBanner tone="error">{error}</StatusBanner>}
    </ResourceDialog>
  );
}
