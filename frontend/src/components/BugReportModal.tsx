import CloseButton from "./ui/CloseButton";
import DisclosureSummary from "./ui/DisclosureSummary";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, FormEvent, JSX } from "react";
import { createPortal } from "react-dom";
import { apiStatusCodeToVisibleMessage } from "../api/client";
import { submitBugReport } from "../api/feedback";
import type { BugReportRequestPayload, BugReportResponse } from "../api/feedback";
import { trackLuminaEvent } from "../analytics/umami";
import { useBugReportUploadStatus } from "../hooks/useBugReportUploadStatus";
import { useI18n } from "../i18n/context";
import {
  collectBugReportContext,
  collectBugReportOriginalImage,
  collectBugReportSourceFiles,
} from "../utils/bugReportContext";
import { loadPersistedLogs } from "../utils/clientLog";
import { isUnsafeVisibleErrorText } from "../utils/visibleErrorText";
import { useActionHistoryStore } from "../stores/actionHistoryStore";
import Button from "./ui/Button";
import Checkbox from "./ui/Checkbox";
import { StatusBanner, workstationInputClass } from "./ui/panelPrimitives";

const MAX_CONTACT_LENGTH = 320;
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/u;
const CONTACT_CONTROL_PATTERN = /[\p{Cc}\p{Zl}\p{Zp}]/u;

/**
 * Schedule ``callback`` on the idle-callback queue, falling back to
 * ``setTimeout(..., 0)`` when the browser does not support it (Safari as
 * of 2026 still lacks ``requestIdleCallback``). Used so the expensive
 * ``JSON.stringify(context, null, 2)`` only runs when the user opts in
 * and yields to layout/input in between.
 * 空闲调度：不支持 ``requestIdleCallback`` 时退回到 ``setTimeout(fn, 0)``。
 */
function scheduleIdle(callback: () => void): void {
  const maybeIdle = (
    globalThis as { requestIdleCallback?: (cb: () => void) => number }
  ).requestIdleCallback;
  if (typeof maybeIdle === "function") {
    try {
      maybeIdle(callback);
      return;
    } catch {
      // fall through
    }
  }
  setTimeout(callback, 0);
}

function isGenericStatusCodeMessage(message: string): boolean {
  return isUnsafeVisibleErrorText(message);
}

/**
 * Minimal 3-line snapshot header + 3 recent action entries + up to 2 recent
 * API errors. Designed to stay under ~10 DOM nodes so the modal renders in
 * the SLO 8 budget (< 50 ms at 500 client logs + 100 action entries).
 * 紧凑摘要：只显示当前工作流关键字段、最近 3 次操作、最近 2 次接口错误，
 * 避免 modal 一打开就序列化完整 context。
 */
type CompactContextSummaryProps = {
  context: ReturnType<typeof collectBugReportContext>;
  labelActiveTab: string;
  labelColorMode: string;
  labelLutName: string;
  labelRecentActions: string;
  labelRecentErrors: string;
  labelNoData: string;
};

function CompactContextSummary({
  context,
  labelActiveTab,
  labelColorMode,
  labelLutName,
  labelRecentActions,
  labelRecentErrors,
  labelNoData,
}: CompactContextSummaryProps): JSX.Element {
  const recentActions = (context.action_history ?? []).slice(-3).reverse();
  const recentLogs = context.recent_client_logs ?? [];
  const recentApiErrors = recentLogs
    .filter(
      (log) =>
        log.method === "error" &&
        (log.scope === "api" || log.scope === "http"),
    )
    .slice(-2)
    .reverse();

  const hasAnyContent =
    context.active_tab != null ||
    context.color_mode != null ||
    context.lut_name != null ||
    recentActions.length > 0 ||
    recentApiErrors.length > 0;

  if (!hasAnyContent) {
    return (
      <p className="text-xs text-slate-500 dark:text-slate-400">{labelNoData}</p>
    );
  }

  return (
    <div
      data-testid="bug-report-context-summary"
      className="space-y-2 text-xs leading-5 text-slate-600 dark:text-slate-300"
    >
      <div className="flex flex-wrap gap-x-3 gap-y-1 font-mono">
        {context.active_tab && <span>{labelActiveTab}={context.active_tab}</span>}
        {context.color_mode && <span>{labelColorMode}={context.color_mode}</span>}
        {context.lut_name && <span>{labelLutName}={context.lut_name}</span>}
      </div>
      {recentActions.length > 0 && (
        <div>
          <div className="font-medium">{labelRecentActions}</div>
          <ul className="ml-4 list-disc font-mono">
            {recentActions.map((entry, idx) => (
              <li key={`${entry.timestamp}-${idx}`}>
                {new Date(entry.timestamp).toISOString()} · {entry.action_type}
              </li>
            ))}
          </ul>
        </div>
      )}
      {recentApiErrors.length > 0 && (
        <div>
          <div className="font-medium">{labelRecentErrors}</div>
          <ul className="ml-4 list-disc font-mono">
            {recentApiErrors.map((entry, idx) => {
              const details = entry.details as
                | {
                    status_code?: unknown;
                    path?: unknown;
                    url?: unknown;
                    error_message?: unknown;
                  }
                | null
                | undefined;
              const status =
                typeof details?.status_code === "number"
                  ? details.status_code
                  : "?";
              const message =
                typeof details?.error_message === "string" &&
                details.error_message.trim()
                  ? details.error_message.trim()
                  : "";
              const fallbackMessage = apiStatusCodeToVisibleMessage(
                typeof status === "number" ? status : null,
              );
              const primaryMessage =
                message && !isGenericStatusCodeMessage(message)
                  ? message
                  : fallbackMessage;
              const primaryText = primaryMessage || entry.label;
              return (
                <li key={`${entry.timestamp}-${idx}`}>
                  <span>{primaryText}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

interface BugReportModalProps {
  open: boolean;
  onClose: () => void;
  presetDescription?: string;
}

interface NoticeState {
  tone: "success" | "error" | "warning";
  message: string;
}

interface FailedReportState {
  text: string;
  copied: boolean;
}


function stringifyManualFallbackReport(
  payload: BugReportRequestPayload,
): string {
  return JSON.stringify(payload, null, 2);
}

function stringifyUserVisibleBugReportContext(
  context: ReturnType<typeof collectBugReportContext>,
): string {
  return JSON.stringify(context, null, 2);
}

function interpolateTicket(template: string, ticket: string): string {
  return template.replace("{{ticket}}", ticket);
}

function copyTextWithSelectionFallback(text: string): boolean {
  if (typeof document === "undefined" || typeof document.execCommand !== "function") {
    return false;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, text.length);

  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    document.body.removeChild(textarea);
  }
}

async function copyTextToClipboard(text: string): Promise<boolean> {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Clipboard API unavailable; the ticket text is still selectable in the UI.
    }
  }

  return copyTextWithSelectionFallback(text);
}

function readScreenshotAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        resolve(reader.result);
      } else {
        reject(new Error("Invalid file reader result"));
      }
    };
    reader.onerror = () => reject(reader.error ?? new Error("File reader failed"));
    reader.readAsDataURL(file);
  });
}

export function BugReportModal({
  open,
  onClose,
  presetDescription = "",
}: BugReportModalProps): JSX.Element | null {
  const { t } = useI18n();
  const [description, setDescription] = useState(presetDescription);
  const [needsReply, setNeedsReply] = useState(true);
  const [contact, setContact] = useState("");
  const [contactError, setContactError] = useState<string | null>(null);
  const contactInput = useRef<HTMLInputElement>(null);
  const [submitting, setSubmitting] = useState(false);
  const [descriptionError, setDescriptionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<NoticeState | null>(null);
  const [contextExpanded, setContextExpanded] = useState(false);
  const [submittedTicket, setSubmittedTicket] = useState<BugReportResponse | null>(null);
  const [submittedPayload, setSubmittedPayload] = useState<BugReportRequestPayload | null>(null);
  const [copied, setCopied] = useState(false);
  const [submittedReportCopied, setSubmittedReportCopied] = useState(false);
  const [failedReport, setFailedReport] = useState<FailedReportState | null>(null);
  const [screenshotDataUrl, setScreenshotDataUrl] = useState<string | null>(null);
  const [screenshotName, setScreenshotName] = useState<string | null>(null);
  const [screenshotError, setScreenshotError] = useState<string | null>(null);
  /**
   * Holds the stringified full context once the user has expanded the
   * context disclosure. Stays ``null`` until requested so a Modal open
   * with a 500-entry log buffer doesn't pay the serialization cost.
   * 仅在用户展开「完整上下文」时按需渲染；避免打开 modal 就做昂贵序列化。
   */
  const [fullContextJson, setFullContextJson] = useState<string | null>(null);
  const upload = useBugReportUploadStatus(
    submittedTicket?.ticket_id ?? null,
    submittedTicket?.submission_status ?? null,
  );

  const resetForm = useCallback(() => {
    setDescription(presetDescription);
    setNeedsReply(true);
    setContact("");
    setContactError(null);
    setSubmitting(false);
    setDescriptionError(null);
    setNotice(null);
    setContextExpanded(false);
    setFullContextJson(null);
    setSubmittedTicket(null);
    setSubmittedPayload(null);
    setCopied(false);
    setSubmittedReportCopied(false);
    setFailedReport(null);
    setScreenshotDataUrl(null);
    setScreenshotName(null);
    setScreenshotError(null);
  }, [presetDescription]);

  useEffect(() => {
    if (open) {
      setDescription((current) => (current ? current : presetDescription));
      // Lazy-load persisted buffers when the user actually opens the modal
      // so regular app usage never pays the sessionStorage read cost. Both
      // calls are swallow-safe and idempotent.
      // 打开 modal 时才从 sessionStorage 合并历史缓冲，平时零 I/O。
      try {
        useActionHistoryStore.getState().loadPersistedHistory();
      } catch {
        // ignore
      }
      try {
        loadPersistedLogs();
      } catch {
        // ignore
      }
      return;
    }
    resetForm();
  }, [open, presetDescription, resetForm]);

  useEffect(() => {
    if (!open) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        resetForm();
        onClose();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open, onClose, resetForm]);

  // Freeze sources and context together when opening the report. A later
  // workflow/session cleanup must not change the data being reported.
  // 打开工单时固定源文件和上下文，避免后续会话清理改变报错现场。
  const sources = useMemo(
    () => open ? { original: collectBugReportOriginalImage(), files: collectBugReportSourceFiles() } : null,
    [open],
  );
  const context = useMemo(
    () => (open ? collectBugReportContext() : null),
    [open],
  );

  // Kick off the expensive full-context serialization lazily when the
  // user opens the disclosure. Run it off the render path via the idle
  // queue so we never block the modal's frame budget.
  // 用户展开完整上下文时再序列化；走 idle 回调，不阻塞渲染。
  useEffect(() => {
    if (!open || !contextExpanded || context == null) {
      return;
    }
    if (fullContextJson != null) {
      return;
    }
    let cancelled = false;
    scheduleIdle(() => {
      if (cancelled) return;
      try {
        const serialized = stringifyUserVisibleBugReportContext(context);
        if (!cancelled) {
          setFullContextJson(serialized);
        }
      } catch {
        if (!cancelled) {
          setFullContextJson("// failed to serialize context");
        }
      }
    });
    return () => {
      cancelled = true;
    };
  }, [open, context, contextExpanded, fullContextJson]);

  if (!open || typeof document === "undefined" || context == null) {
    return null;
  }

  const trimmedDescription = description.trim();
  const canSubmit = trimmedDescription.length > 0 && !submitting;

  const handleDescriptionChange = (value: string) => {
    setDescription(value);
    if (descriptionError) {
      setDescriptionError(null);
    }
    if (notice?.tone === "warning") {
      setNotice(null);
    }
    if (failedReport) {
      setFailedReport(null);
    }
  };

  const handleScreenshotChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    setScreenshotDataUrl(null);
    setScreenshotName(null);
    setScreenshotError(null);

    if (!file) {
      return;
    }
    if (!file.type.startsWith("image/")) {
      setScreenshotError(t("bug_report_validation_screenshot_type"));
      event.target.value = "";
      return;
    }

    try {
      const dataUrl = await readScreenshotAsDataUrl(file);
      setScreenshotDataUrl(dataUrl);
      setScreenshotName(file.name);
    } catch {
      setScreenshotError(t("bug_report_validation_screenshot_read_failed"));
      event.target.value = "";
    }
  };

  const handleRemoveScreenshot = () => {
    setScreenshotDataUrl(null);
    setScreenshotName(null);
    setScreenshotError(null);
  };

  const handleCancel = () => {
    resetForm();
    onClose();
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!trimmedDescription) {
      setDescriptionError(t("bug_report_validation_description_required"));
      return;
    }

    const replyContact = needsReply ? contact.trim() : null;
    if (needsReply && (
      !replyContact ||
      [...replyContact.replace(/\s/gu, "")].length < 3 ||
      [...replyContact].length > MAX_CONTACT_LENGTH ||
      CONTACT_CONTROL_PATTERN.test(contact)
    )) {
      setContactError(t("bug_report_validation_contact"));
      contactInput.current?.focus();
      return;
    }

    setSubmitting(true);
    setDescriptionError(null);
    setContactError(null);
    setNotice(null);
    setFailedReport(null);

    const reportPayload: BugReportRequestPayload = {
      description: trimmedDescription,
      user_email: replyContact && EMAIL_PATTERN.test(replyContact) ? replyContact : null,
      user_contact: replyContact,
      needs_reply: needsReply,
      context,
      screenshot_data_url: screenshotDataUrl,
    };
    try {
      const response = sources?.files.length || sources?.original
        ? await submitBugReport(reportPayload, sources.original, sources.files)
        : await submitBugReport(reportPayload);
      setSubmittedTicket(response);
      setSubmittedPayload(reportPayload);
      setSubmitting(false);
      setCopied(false);
      setSubmittedReportCopied(false);
      trackLuminaEvent("lumina_bug_report_done", {
        active_tab: context.active_tab,
        has_screenshot: Boolean(screenshotDataUrl),
        delivery_status: response.submission_status,
      });
    } catch (err) {
      setNotice({
        tone: "error",
        message: t("bug_report_toast_error"),
      });
      setFailedReport({
        text: stringifyManualFallbackReport(reportPayload),
        copied: false,
      });
      setSubmitting(false);
      trackLuminaEvent("lumina_bug_report_failed", {
        active_tab: context.active_tab,
        has_screenshot: Boolean(screenshotDataUrl),
        error_type: err instanceof Error ? err.name : typeof err,
      });
    }
  };

  const handleCopyTicket = async () => {
    if (!submittedTicket) {
      return;
    }
    const copiedToClipboard = await copyTextToClipboard(submittedTicket.ticket_id);
    if (!copiedToClipboard) {
      setCopied(false);
      setNotice({
        tone: "warning",
        message: t("bug_report_success_copy_failed"),
      });
      return;
    }
    setNotice(null);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  const submittedReportText = submittedPayload
    ? stringifyManualFallbackReport(submittedPayload)
    : "";

  const handleRetryUpload = async () => {
    setNotice(null);
    await upload.retry();
  };

  const handleRecaptureReport = async () => {
    if (!submittedPayload || submitting) return;
    setSubmitting(true);
    setNotice(null);
    try {
      const response = sources?.files.length || sources?.original
        ? await submitBugReport(submittedPayload, sources.original, sources.files)
        : await submitBugReport(submittedPayload);
      setSubmittedTicket(response);
      setCopied(false);
    } catch {
      setNotice({ tone: "error", message: t("bug_report_toast_error") });
    } finally {
      setSubmitting(false);
    }
  };

  const collectionIncomplete = (
    upload.details?.assembly_status ?? submittedTicket?.assembly_status
  ) === "partial_failed";

  const handleCopySubmittedReport = async () => {
    if (!submittedReportText) {
      return;
    }
    const copiedToClipboard = await copyTextToClipboard(submittedReportText);
    if (!copiedToClipboard) {
      setSubmittedReportCopied(false);
      setNotice({
        tone: "warning",
        message: t("bug_report_fallback_copy_failed"),
      });
      return;
    }
    setNotice(null);
    setSubmittedReportCopied(true);
    window.setTimeout(() => setSubmittedReportCopied(false), 2000);
  };

  const handleCopyFailedReport = async () => {
    if (!failedReport) {
      return;
    }
    const copiedToClipboard = await copyTextToClipboard(failedReport.text);
    if (!copiedToClipboard) {
      setFailedReport({ ...failedReport, copied: false });
      setNotice({
        tone: "warning",
        message: t("bug_report_fallback_copy_failed"),
      });
      return;
    }
    setNotice(null);
    setFailedReport({ ...failedReport, copied: true });
    window.setTimeout(() => {
      setFailedReport((current) => current ? { ...current, copied: false } : current);
    }, 2000);
  };

  const buildFallbackMailto = (reportText: string, ticketId?: string): string => {
    const subject = ticketId
      ? `Lumina Studio bug report ${ticketId}`
      : "Lumina Studio bug report";
    return `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(reportText)}`;
  };

  const renderManualFallbackActions = (
    reportText: string,
    copyButton: JSX.Element,
    ticketId?: string,
  ): JSX.Element => (
    <div className="flex flex-wrap items-center gap-2">
      {copyButton}
      <a
        href={buildFallbackMailto(reportText, ticketId)}
        className="rounded-lg px-3 py-1 text-xs font-medium transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] dark:hover:bg-slate-800"
        style={{ color: "var(--surface-text-muted)" }}
      >
        {t("bug_report_fallback_mailto")}
      </a>
      <a
        href="https://mail.qq.com/"
        target="_blank"
        rel="noreferrer"
        className="rounded-lg px-3 py-1 text-xs font-medium transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] dark:hover:bg-slate-800"
        style={{ color: "var(--surface-text-muted)" }}
      >
        {t("bug_report_fallback_qq_mail")}
      </a>
    </div>
  );

  return createPortal(
    <div
      data-testid="bug-report-backdrop"
      className="fixed inset-0 z-[10000] flex items-center justify-center px-4 py-6 backdrop-blur-sm"
      style={{ background: "var(--surface-scrim)" }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t("bug_report_modal_title")}
        className="relative flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-[28px] border shadow-2xl"
        style={{
          background: "var(--surface-panel-strong)",
          borderColor: "var(--surface-outline)",
        }}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-5 py-4 dark:border-slate-700">
          <h2 className="text-base font-semibold text-slate-900 dark:text-slate-50">
            {t("bug_report_modal_title")}
          </h2>
          <CloseButton label={t("announcement_close")} onClick={handleCancel} />
        </div>

        {submittedTicket ? (
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="flex-1 space-y-4 overflow-y-auto overscroll-y-contain px-5 py-4">
              <StatusBanner
                tone={
                  collectionIncomplete || upload.status === "failed" || upload.status === "disabled"
                    ? "warning"
                    : "success"
                }
                role="status"
              >
                {interpolateTicket(
                  upload.status === "failed" || upload.status === "disabled"
                    ? t("bug_report_toast_saved_locally")
                    : t("bug_report_toast_success"),
                  submittedTicket.ticket_id,
                )}
              </StatusBanner>
              {collectionIncomplete && (
                <StatusBanner tone="warning" role="alert">
                  <p data-testid="bug-report-collection-incomplete">{t("bug_report_collection_incomplete")}</p>
                  <Button
                    label={submitting ? t("bug_report_upload_retrying") : t("bug_report_recapture")}
                    variant="secondary"
                    onClick={handleRecaptureReport}
                    disabled={submitting}
                    className="mt-2"
                  />
                </StatusBanner>
              )}
              {notice && (
                <StatusBanner
                  tone={notice.tone}
                  role={notice.tone === "success" ? "status" : "alert"}
                >
                  {notice.message}
                </StatusBanner>
              )}

              <div
                className="flex flex-wrap items-center gap-2 rounded-[18px] border px-4 py-3"
                style={{
                  borderColor: "var(--surface-outline)",
                  background:
                    "color-mix(in srgb, var(--surface-panel-strong) 68%, transparent)",
                }}
              >
                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  {t("bug_report_success_ticket_label")}:
                </span>
                <code
                  data-testid="bug-report-ticket-id"
                  className="select-all rounded px-2 py-1 font-mono text-sm"
                  style={{
                    background:
                      "color-mix(in srgb, var(--surface-panel-strong) 30%, black)",
                    color: "var(--surface-text)",
                  }}
                >
                  {submittedTicket.ticket_id}
                </code>
                <button
                  type="button"
                  data-testid="bug-report-copy-ticket"
                  onClick={handleCopyTicket}
                  className="action-control rounded-lg px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
                  style={{ color: "var(--surface-text-muted)" }}
                >
                  {copied
                    ? t("bug_report_success_copied")
                    : t("bug_report_success_copy")}
                </button>
              </div>

              <p
                data-testid="bug-report-upload-status"
                data-status={upload.status ?? "pending"}
                className="text-sm leading-6 text-slate-700 dark:text-slate-200"
              >
                {upload.status === "submitted"
                  ? t("bug_report_upload_submitted")
                  : upload.status === "failed"
                    ? t("bug_report_upload_failed")
                    : upload.status === "disabled"
                      ? t("bug_report_upload_disabled")
                      : upload.timedOut
                        ? t("bug_report_upload_pending_slow")
                        : t("bug_report_upload_pending")}
              </p>

              {upload.status === "submitted" &&
                (upload.details?.held_back_attachments.length ?? 0) > 0 && (
                <StatusBanner tone="warning" role="status">
                  <span data-testid="bug-report-upload-held-back">
                    {t("bug_report_upload_held_back").replace(
                      "{files}",
                      (upload.details?.held_back_attachments ?? [])
                        .map((item) => item.name)
                        .join(", "),
                    )}
                  </span>
                </StatusBanner>
              )}

              {upload.status === "failed" && (
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    data-testid="bug-report-upload-retry"
                    onClick={handleRetryUpload}
                    disabled={upload.retrying}
                    className="action-control rounded-lg px-3 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
                    style={{ color: "var(--surface-text-muted)" }}
                  >
                    {upload.retrying
                      ? t("bug_report_upload_retrying")
                      : t("bug_report_upload_retry")}
                  </button>
                  {upload.retryFailed && (
                    <span className="text-xs text-[var(--error-fg)]">
                      {t("bug_report_upload_retry_failed")}
                    </span>
                  )}
                </div>
              )}

              {submittedTicket.original_image_status && (
                <StatusBanner
                  tone={
                    submittedTicket.original_image_status === "attached" ||
                    submittedTicket.original_image_status === "session_fallback"
                      ? "success"
                      : "warning"
                  }
                  role="status"
                >
                  <span
                    data-testid="bug-report-original-image-status"
                    data-status={submittedTicket.original_image_status}
                  >
                    {submittedTicket.original_image_status === "attached"
                      ? t("bug_report_success_original_attached")
                      : submittedTicket.original_image_status === "session_fallback"
                        ? t("bug_report_success_original_session_fallback")
                        : submittedTicket.original_image_status === "too_large"
                          ? t("bug_report_success_original_too_large")
                          : submittedTicket.original_image_status === "failed"
                            ? t("bug_report_success_original_failed")
                            : t("bug_report_success_original_not_applicable")}
                  </span>
                </StatusBanner>
              )}

              {(upload.status === "failed" || upload.status === "disabled") &&
                submittedReportText && (
                <div
                  className="space-y-3 rounded-[18px] border px-4 py-3"
                  style={{
                    borderColor: "var(--surface-outline)",
                    background:
                      "color-mix(in srgb, var(--surface-panel-strong) 68%, transparent)",
                  }}
                >
                  <p className="text-sm leading-6 text-slate-700 dark:text-slate-200">
                    {t("bug_report_fallback_intro")}
                  </p>
                  {renderManualFallbackActions(
                    submittedReportText,
                    <button
                      type="button"
                      data-testid="bug-report-copy-submitted-report"
                      onClick={handleCopySubmittedReport}
                      className="action-control rounded-lg px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
                      style={{ color: "var(--surface-text-muted)" }}
                    >
                      {submittedReportCopied
                        ? t("bug_report_fallback_copied")
                        : t("bug_report_fallback_copy")}
                    </button>,
                    submittedTicket.ticket_id,
                  )}
                  <pre
                    data-testid="bug-report-submitted-fallback-text"
                    className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-2xl px-3 py-3 text-xs leading-5 text-slate-100"
                    style={{
                      background:
                        "color-mix(in srgb, var(--surface-panel-strong) 18%, black)",
                    }}
                  >
                    {submittedReportText}
                  </pre>
                </div>
              )}
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-slate-200 px-5 py-4 dark:border-slate-700">
              <Button
                label={t("bug_report_success_close")}
                variant="secondary"
                onClick={handleCancel}
                className="px-4"
              />
            </div>
          </div>
        ) : (
          <form className="flex min-h-0 flex-1 flex-col" onSubmit={handleSubmit} noValidate>
            <div className="flex-1 space-y-4 overflow-y-auto overscroll-y-contain px-5 py-4">
              {notice && (
                <StatusBanner
                  tone={notice.tone}
                  role={notice.tone === "success" ? "status" : "alert"}
                >
                  {notice.message}
                </StatusBanner>
              )}
              {failedReport && (
                <div
                  className="space-y-3 rounded-[18px] border px-4 py-3"
                  style={{
                    borderColor: "var(--surface-outline)",
                    background:
                      "color-mix(in srgb, var(--surface-panel-strong) 68%, transparent)",
                  }}
                >
                  <p className="text-sm leading-6 text-slate-700 dark:text-slate-200">
                    {t("bug_report_fallback_intro")}
                  </p>
                  {renderManualFallbackActions(
                    failedReport.text,
                    <button
                      type="button"
                      data-testid="bug-report-copy-failed-report"
                      onClick={handleCopyFailedReport}
                      className="action-control rounded-lg px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
                      style={{ color: "var(--surface-text-muted)" }}
                    >
                      {failedReport.copied
                        ? t("bug_report_fallback_copied")
                        : t("bug_report_fallback_copy")}
                    </button>,
                  )}
                  <pre
                    data-testid="bug-report-fallback-text"
                    className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-2xl px-3 py-3 text-xs leading-5 text-slate-100"
                    style={{
                      background:
                        "color-mix(in srgb, var(--surface-panel-strong) 18%, black)",
                    }}
                  >
                    {failedReport.text}
                  </pre>
                </div>
              )}

              <div className="space-y-2">
                <label
                  htmlFor="bug-report-description"
                  className="text-sm font-medium text-slate-700 dark:text-slate-200"
                >
                  {t("bug_report_modal_description_label")}
                </label>
                <textarea
                  id="bug-report-description"
                  value={description}
                  onChange={(event) => handleDescriptionChange(event.target.value)}
                  onBlur={() => {
                    if (!description.trim()) {
                      setDescriptionError(t("bug_report_validation_description_required"));
                    }
                  }}
                  placeholder={t("bug_report_modal_description_placeholder")}
                  autoFocus
                  rows={6}
                  className={`${workstationInputClass} min-h-[9rem] resize-y`}
                />
                {descriptionError && (
                  <p className="text-sm text-[var(--error-fg)]">{descriptionError}</p>
                )}
              </div>

              <div className="space-y-3">
                <Checkbox
                  label={t("bug_report_modal_needs_reply")}
                  checked={needsReply}
                  disabled={submitting}
                  onChange={(checked) => {
                    setNeedsReply(checked);
                    setContactError(null);
                    setFailedReport(null);
                  }}
                />
                {needsReply ? (
                  <div className="space-y-2">
                    <label
                      htmlFor="bug-report-contact"
                      className="text-sm font-medium text-slate-700 dark:text-slate-200"
                    >
                      {t("bug_report_modal_contact_label")}
                    </label>
                    <span aria-hidden="true" className="ml-1 text-[var(--error-fg)]">*</span>
                    <input
                      id="bug-report-contact"
                      ref={contactInput}
                      type="text"
                      maxLength={MAX_CONTACT_LENGTH}
                      autoCapitalize="none"
                      spellCheck={false}
                      required
                      disabled={submitting}
                      aria-invalid={contactError != null}
                      aria-describedby={contactError ? "bug-report-contact-error" : undefined}
                      value={contact}
                      onChange={(event) => {
                        setContact(event.target.value);
                        setContactError(null);
                        setFailedReport(null);
                      }}
                      className={workstationInputClass}
                    />
                    {contactError && (
                      <p id="bug-report-contact-error" role="alert" className="text-sm text-[var(--error-fg)]">
                        {contactError}
                      </p>
                    )}
                  </div>
                ) : (
                  <p role="status" className="text-sm text-slate-600 dark:text-slate-300">
                    {t("bug_report_modal_diagnostics_only")}
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <label
                  htmlFor="bug-report-screenshot"
                  className="text-sm font-medium text-slate-700 dark:text-slate-200"
                >
                  {t("bug_report_modal_screenshot_label")}
                </label>
                <input
                  id="bug-report-screenshot"
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                  onChange={handleScreenshotChange}
                  className={workstationInputClass}
                />
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {t("bug_report_modal_screenshot_hint")}
                </p>
                {screenshotError && (
                  <p className="text-sm text-[var(--error-fg)]">{screenshotError}</p>
                )}
                {screenshotName && (
                  <div
                    className="flex flex-wrap items-center gap-2 rounded-[18px] border px-3 py-2"
                    style={{
                      borderColor: "var(--surface-outline)",
                      background:
                        "color-mix(in srgb, var(--surface-panel-strong) 68%, transparent)",
                    }}
                  >
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      {t("bug_report_modal_screenshot_attached_label")}:
                    </span>
                    <span className="break-all text-sm text-slate-700 dark:text-slate-200">
                      {screenshotName}
                    </span>
                    <button
                      type="button"
                      className="action-control rounded-lg px-2 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
                      onClick={handleRemoveScreenshot}
                    >
                      {t("bug_report_modal_screenshot_remove")}
                    </button>
                  </div>
                )}
              </div>

              <CompactContextSummary
                context={context}
                labelActiveTab={t("bug_report_modal_context_active_tab")}
                labelColorMode={t("bug_report_modal_context_color_mode")}
                labelLutName={t("bug_report_modal_context_lut")}
                labelRecentActions={t("bug_report_modal_context_recent_actions")}
                labelRecentErrors={t("bug_report_modal_context_recent_errors")}
                labelNoData={t("bug_report_modal_context_summary_none")}
              />

              <details
                open={contextExpanded}
                onToggle={(event) =>
                  setContextExpanded((event.currentTarget as HTMLDetailsElement).open)
                }
                className="rounded-[22px] border px-4 py-3 shadow-[var(--shadow-control)]"
                style={{
                  borderColor: "var(--surface-outline)",
                  background:
                    "color-mix(in srgb, var(--surface-panel-strong) 68%, transparent)",
                }}
              >
                <DisclosureSummary className="cursor-pointer list-none text-sm font-medium text-slate-700 dark:text-slate-200">
                  {t("bug_report_modal_context_disclosure")}
                </DisclosureSummary>
                <pre
                  data-testid="bug-report-context-json"
                  className="mt-3 overflow-x-auto rounded-2xl px-3 py-3 text-xs leading-5 text-slate-100"
                  style={{
                    background:
                      "color-mix(in srgb, var(--surface-panel-strong) 18%, black)",
                  }}
                >
                  {fullContextJson ?? ""}
                </pre>
              </details>

              <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
                {t("bug_report_modal_privacy_note")}
              </p>
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-slate-200 px-5 py-4 dark:border-slate-700">
              <Button
                label={t("bug_report_modal_cancel")}
                variant="secondary"
                onClick={handleCancel}
                disabled={submitting}
                className="px-4"
              />
              <Button
                type="submit"
                label={t("bug_report_modal_submit")}
                variant="primary"
                onClick={() => {}}
                disabled={!canSubmit}
                loading={submitting}
                className="px-4"
              />
            </div>
          </form>
        )}
      </div>
    </div>,
    document.body,
  );
}
