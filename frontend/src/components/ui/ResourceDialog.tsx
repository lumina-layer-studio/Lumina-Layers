import { useEffect, useId, useRef, useState, type FormEventHandler, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { motion } from "framer-motion";
import { useDialogFocusTrap } from "../../hooks/useDialogFocusTrap";
import { useI18n } from "../../i18n/context";
import CloseButton from "./CloseButton";
import { cx } from "./panelPrimitives";

interface Props {
  title: string;
  children: ReactNode;
  footer?: ReactNode | ((close: () => void) => ReactNode);
  width?: "sm" | "md" | "lg";
  busy?: boolean;
  account?: boolean;
  onClose: () => void;
  onSubmit?: FormEventHandler<HTMLFormElement>;
}

const INITIAL_FORM_FIELD = [
  "input:not([type='hidden']):not([type='radio']):not([type='checkbox']):not([type='file']):not([disabled])",
  "textarea:not([disabled])",
  "[role='combobox']:not([disabled])",
].join(",");

/** Shared shell for resource accounts, contributions and version history. */
export default function ResourceDialog({
  title,
  children,
  footer,
  width = "md",
  busy = false,
  account = false,
  onClose,
  onSubmit,
}: Props) {
  const { t } = useI18n();
  const titleId = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latest = useRef({ busy, onClose });
  latest.current = { busy, onClose };
  const [closing, setClosing] = useState(false);

  useDialogFocusTrap(dialog, !closing, {
    initialFocus: (container) => {
      if (onSubmit) {
        for (const el of container.querySelectorAll<HTMLElement>(`[data-dialog-body] :is(${INITIAL_FORM_FIELD})`)) {
          if (!el.closest("details:not([open])")) return el;
        }
      }
      return container.querySelector<HTMLElement>("button:not([disabled])");
    },
  });

  const close = () => {
    if (latest.current.busy || timer.current !== null) return;
    setClosing(true);
    timer.current = setTimeout(() => latest.current.onClose(), 160);
  };

  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      event.stopPropagation();
      close();
    };
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("keydown", escape);
      if (timer.current !== null) clearTimeout(timer.current);
    };
  }, []);

  const content = (
    <>
      <div
        data-dialog-body
        className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto overscroll-contain px-5 py-4"
      >
        {children}
      </div>
      {footer && (
        <div className="shrink-0 border-t border-[var(--surface-divider)] px-5 py-3.5">
          {typeof footer === "function" ? footer(close) : footer}
        </div>
      )}
    </>
  );

  return createPortal(
    <motion.div
      className={cx(
        "fixed inset-0 flex items-center justify-center bg-[var(--surface-scrim)] p-3 sm:p-6",
        account ? "z-[11000]" : "z-[10000]",
      )}
      initial={{ opacity: 0 }}
      animate={{ opacity: closing ? 0 : 1 }}
      transition={{ duration: closing ? 0.16 : 0.2 }}
      onClick={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <motion.div
        ref={dialog}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        inert={closing}
        data-resource-dialog
        data-community-account-dialog={account ? "" : undefined}
        initial={{ y: 8 }}
        animate={{ y: closing ? 6 : 0 }}
        transition={{ duration: closing ? 0.16 : 0.2 }}
        className={cx(
          "flex max-h-[min(46rem,calc(100vh-2rem))] w-full min-w-0 flex-col overflow-hidden rounded-2xl border border-[var(--surface-card-outline)] bg-[var(--surface-panel-strong)] text-slate-900 dark:text-slate-100",
          width === "sm" ? "max-w-md" : width === "lg" ? "max-w-2xl" : "max-w-xl",
        )}
      >
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-[var(--surface-divider)] px-5 py-3.5">
          <h2 id={titleId} className="min-w-0 truncate text-[15px] font-semibold">
            {title}
          </h2>
          <CloseButton label={t("common_close")} onClick={close} disabled={busy} />
        </div>
        {onSubmit ? (
          <form onSubmit={onSubmit}
            onInvalidCapture={(event) => {
              if (!(event.target instanceof HTMLElement)) return;
              for (let parent = event.target.parentElement; parent && parent !== event.currentTarget; parent = parent.parentElement) {
                if (parent instanceof HTMLDetailsElement) parent.open = true;
              }
            }}
            className="flex min-h-0 flex-1 flex-col overflow-hidden">
            {content}
          </form>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">{content}</div>
        )}
      </motion.div>
    </motion.div>,
    document.body,
  );
}
