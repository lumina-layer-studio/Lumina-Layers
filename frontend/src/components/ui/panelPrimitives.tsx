/* eslint-disable react-refresh/only-export-components */
import type { HTMLAttributes, ReactNode } from "react";
import type { WorkspaceMode } from "../../types/workspace";

export function cx(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

// Page roots own the native scroll chain; nested lists can still chain into them.
export const panelSurfaceClass =
  "panel-surface h-full w-full overflow-auto overscroll-y-contain px-3 py-3 sm:px-5 sm:py-4 lg:px-7 lg:py-5";

export const centeredPanelClass =
  `${panelSurfaceClass}`;

export const sectionCardClass =
  "panel-section rounded-[28px] px-4 py-4 sm:px-5 sm:py-5";

export const mutedSectionCardClass =
  "panel-section-muted rounded-[22px] px-4 py-3";

export const workstationPanelCardClass =
  "panel-section-muted h-full rounded-[28px] px-4 py-4";

export const workstationInsetCardClass =
  "panel-section-muted rounded-[22px] px-4 py-3";

export const workstationShellClass =
  "rounded-t-[28px]";

/* ========== Hierarchy v2 primitives ==========
 * One bordered card level per page; inside a card only wells (tinted,
 * borderless) and hairline dividers. Radii step down 16 → 10 → 6 px so
 * outer/inner shapes stop competing.
 * 层级 v2：每页只有一层带边框卡片；卡片内只用“凹槽”和分割线表达分组，
 * 圆角按 16 → 10 → 6 px 递减，外壳与内部控件不再抢层级。 */

export const cardClass = "panel-card rounded-2xl";

export const cardPadClass = `${cardClass} px-5 py-5`;

export const wellClass = "panel-well rounded-[10px]";

export const wellPadClass = `${wellClass} px-3 py-2.5`;

/** Hairline divider between groups inside a card. 卡内分组分割线。 */
export const cardDividerClass =
  "panel-divider border-t";

/** Group header inside a card: small caps eyebrow, optionally with a tint dot.
 * 卡内组标题：小型大写字距标题，可带彩色圆点替代彩色边框。 */
export const groupHeaderClass =
  "flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400";

/** Settings sections use one continuous tinted surface around their controls. */
export const settingsGroupClass =
  "settings-group flex min-w-0 flex-col gap-3 rounded-[10px] bg-[var(--surface-well)] p-3";

export const settingsGroupHeadingClass =
  "text-sm font-semibold text-slate-800 dark:text-slate-100";

export const workstationFieldLabelClass =
  "text-sm font-medium text-slate-700 dark:text-slate-200";

/** Field shell: filled at rest, boundary appears on hover, blue on focus.
 * 输入框外壳：静止时只有浅灰底，悬停才出现细边框，聚焦转蓝并加焦点环。 */
const workstationFieldShellClass =
  "min-h-11 w-full rounded-[10px] border border-transparent bg-[var(--surface-well)] px-3.5 py-2 text-sm text-slate-800 outline-none transition-all duration-200 hover:border-[color:var(--surface-card-outline)] disabled:cursor-not-allowed disabled:opacity-45 dark:text-slate-100";

export const workstationInputClass =
  `${workstationFieldShellClass} workstation-field-validate focus:border-blue-400 focus:ring-2 focus:ring-[var(--focus-ring)]`;

/** Picker buttons show a focus ring only for keyboard navigation. */
export const workstationPickerTriggerClass =
  `${workstationFieldShellClass} focus-visible:border-blue-400 focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]`;

/** Standalone text input (no min-height, no vertical padding): same field
 *  treatment for compact search / hex rows. 紧凑输入框，沿用同一套字段样式。 */
export const compactFieldClass =
  "w-full rounded-[10px] border border-transparent bg-[var(--surface-well)] px-3 py-2 text-sm text-slate-800 outline-none transition-all duration-200 hover:border-[color:var(--surface-card-outline)] focus:border-blue-400 focus:ring-2 focus:ring-[var(--focus-ring)] disabled:cursor-not-allowed disabled:opacity-45 dark:text-slate-100";

/** Selectable row (checkbox / radio option): borderless at rest and on hover.
 *  The negative inline margin lets the hover fill extend slightly past the
 *  text while the label text stays aligned with the rows above it.
 *  可选行：静止和悬停均无可见边框；负外边距让
 *  悬停底色向外伸出，文字仍与其它控件左对齐。
 *  `rounded-[10px]` is part of the public contract (tests locate rows by it). */
export const workstationChoiceRowClass =
  "-mx-2 flex rounded-[10px] border border-transparent px-2 py-1.5 transition-colors duration-150";

export const workstationChoiceRowActiveClass =
  "hover:bg-[var(--nav-chip-hover)]";

export const workstationChoiceRowDisabledClass = "cursor-not-allowed opacity-45";

/** Sub-settings revealed by a parent control (a switch inside a card that
 *  unlocks more fields). Indented behind a hairline rule instead of being
 *  wrapped in another bordered box. 从属缩进：父级开关展开的子设置，用一条
 *  细竖线加缩进表达从属关系，不再套一层带边框的盒子。 */
export const dependentGroupClass =
  "flex flex-col gap-3 border-l-2 border-[color:var(--surface-divider)] py-1 pl-3";

/** Ghost button/icon-button class for raw <button> elements that do not go
 *  through the shared Button component. 原生按钮使用的幽灵按钮样式。 */
export const ghostControlClass = "ghost-control";

/** Navigation links use the same control tokens while preserving link semantics. */
export const actionLinkClass =
  "inline-flex min-h-9 min-w-0 items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium leading-5 transition-colors duration-150";

/** Shared shell for catalog scope selectors and searchable facet menus. */
export const catalogFilterTriggerClass =
  "ghost-control inline-flex min-h-8 max-w-full items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]";

export const catalogFilterMenuClass =
  "z-[10010] overflow-hidden rounded-[10px] border border-[var(--surface-card-outline)] bg-[var(--surface-panel-strong)] text-slate-800 dark:text-slate-100";

export const catalogFilterOptionClass =
  "flex min-h-9 w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-[var(--surface-well)]";

export const desktopSplitLayoutClass =
  "grid min-h-0 gap-5 xl:grid-cols-[minmax(18rem,24rem)_minmax(0,1fr)] xl:items-start 2xl:grid-cols-[minmax(22rem,27.5rem)_minmax(0,1fr)]";

export const desktopPrimaryColumnClass =
  "flex min-w-0 flex-col gap-5";

export const desktopSecondaryColumnClass =
  "flex min-w-0 flex-col gap-5";

export function resolvePanelSurfaceClass(mode: WorkspaceMode) {
  return cx(
    panelSurfaceClass,
    mode === "compact" && "px-3 py-3 sm:px-4 sm:py-4",
    mode === "wide" && "xl:px-7 xl:py-5"
  );
}

export function resolveSectionCardClass(mode: WorkspaceMode) {
  return cx(
    sectionCardClass,
    mode === "compact" && "rounded-[24px] px-3.5 py-3.5 sm:px-4 sm:py-4"
  );
}

export function resolveDesktopSplitLayoutClass(mode: WorkspaceMode) {
  if (mode === "compact") {
    return "grid min-h-0 gap-4";
  }

  if (mode === "wide") {
    return desktopSplitLayoutClass;
  }

  return "grid min-h-0 gap-5 2xl:grid-cols-[minmax(20rem,24rem)_minmax(0,1fr)] 2xl:items-start";
}

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

export function reportStatusBadgeClass(status: "open" | "resolved" | "dismissed" | string): string {
  if (status === "resolved") {
    return "bg-emerald-500/12 text-emerald-700 dark:bg-emerald-400/15 dark:text-emerald-300";
  }
  if (status === "open") {
    return "bg-amber-500/12 text-amber-700 dark:bg-amber-400/15 dark:text-amber-300";
  }
  return "bg-slate-500/12 text-slate-700 dark:bg-slate-400/15 dark:text-slate-300";
}
