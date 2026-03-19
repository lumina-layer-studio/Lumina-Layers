/* eslint-disable react-refresh/only-export-components */
import type { HTMLAttributes, ReactNode } from "react";

export function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export const panelSurfaceClass =
  "panel-surface w-full rounded-[28px] p-5 sm:p-6";

export const centeredPanelClass =
  `${panelSurfaceClass} mx-auto h-full max-w-3xl overflow-y-auto`;

export const sectionCardClass =
  "panel-section rounded-[24px] p-4 sm:p-5";

export const mutedSectionCardClass =
  "panel-section-muted rounded-[22px] p-4";

interface PanelIntroProps {
  title: string;
  description?: string;
  eyebrow?: string;
  action?: ReactNode;
  className?: string;
}

export function PanelIntro({
  title,
  description,
  eyebrow,
  action,
  className,
}: PanelIntroProps) {
  return (
    <div
      className={cx(
        "flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between",
        className
      )}
    >
      <div className="min-w-0">
        {eyebrow && (
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">
            {eyebrow}
          </p>
        )}
        <h2 className="mt-1 text-2xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
          {title}
        </h2>
        {description && (
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-300">
            {description}
          </p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

interface StatusBannerProps extends HTMLAttributes<HTMLDivElement> {
  tone?: "info" | "success" | "warning" | "error";
  title?: string;
  children: ReactNode;
  action?: ReactNode;
}

export function StatusBanner({
  tone = "info",
  title,
  children,
  action,
  className,
  ...props
}: StatusBannerProps) {
  return (
    <div
      {...props}
      data-tone={tone}
      className={cx(
        "status-banner flex items-start gap-3",
        className
      )}
    >
      <div className="min-w-0 flex-1">
        {title && (
          <p className="text-sm font-semibold text-slate-900 dark:text-slate-50">
            {title}
          </p>
        )}
        <div className="text-sm leading-6 text-slate-700 dark:text-slate-200">
          {children}
        </div>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
