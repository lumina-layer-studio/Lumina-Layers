import { useId } from "react";
import {
  cx,
  workstationChoiceRowActiveClass,
  workstationChoiceRowClass,
  workstationChoiceRowDisabledClass,
} from "./panelPrimitives";
import HelpDot from "./HelpDot";
import { SwitchTrack } from "./Switch";
import type { WikiDocPath } from "../../utils/wikiDocs";

interface CheckboxProps {
  label: React.ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  /** Optional hover hint. Rendered via the canonical WikiTooltip popover
   *  (NOT native `title`) so the visual style matches the rest of the app. */
  tooltip?: string;
  /** Optional tooltip title override. Defaults to the string form of `label`
   *  when `tooltip` is set; pass this when `label` is a non-string ReactNode. */
  tooltipTitle?: string;
  /** Optional matching article in the public Lumina Wiki. */
  wikiPath?: WikiDocPath;
  /** `switch` (default) is an on/off setting; `checkbox` is one item in a
   *  multi-select list, where a pill per row would read as many settings. */
  appearance?: "switch" | "checkbox";
}

export function CheckboxIndicator({ checked }: { checked: boolean }) {
  return <span aria-hidden="true" className={cx(
    "flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-colors duration-200 peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-[var(--focus-ring)]",
    checked ? "border-blue-500 bg-blue-500" : "border-slate-300/80 bg-white dark:border-slate-600/80 dark:bg-slate-800",
  )}>
    <span className={cx("h-2.5 w-2.5 rounded-sm", checked ? "bg-white" : "bg-transparent")} />
  </span>;
}

export default function Checkbox({
  label,
  checked,
  onChange,
  disabled = false,
  tooltip,
  tooltipTitle,
  wikiPath,
  appearance = "switch",
}: CheckboxProps) {
  const inputId = useId();
  const helpDot = tooltip ? (
    <HelpDot
      title={tooltipTitle ?? (typeof label === "string" ? label : "")}
      description={tooltip}
      wikiPath={wikiPath}
      ariaLabel={tooltip}
    />
  ) : null;
  const rowClass = cx(
    "items-center gap-3 py-2 text-sm",
    workstationChoiceRowClass,
    !disabled && workstationChoiceRowActiveClass,
    disabled && workstationChoiceRowDisabledClass,
  );
  const labelTextClass =
    "min-w-0 whitespace-normal break-words font-medium text-slate-700 dark:text-slate-200";

  if (appearance === "switch") {
    const cursorClass = disabled ? "cursor-not-allowed" : "cursor-pointer";
    // The HelpDot must stay outside both <label>s or its text joins the
    // switch's accessible name, so gaps in the row toggle via this handler.
    const toggleFromRowGap = (event: React.MouseEvent<HTMLDivElement>) => {
      if (!disabled && event.target === event.currentTarget) onChange(!checked);
    };
    return (
      <div className={cx(rowClass, cursorClass)} onClick={toggleFromRowGap}>
        <label htmlFor={inputId} className={cx(labelTextClass, cursorClass)}>
          {label}
        </label>
        {helpDot && <span className="flex h-4 w-4 shrink-0 items-center">{helpDot}</span>}
        <label className={cx("flex flex-1 justify-end self-stretch items-center", cursorClass)}>
          <input
            id={inputId}
            type="checkbox"
            role="switch"
            checked={checked}
            disabled={disabled}
            onChange={(e) => onChange(e.target.checked)}
            className="peer sr-only"
          />
          <span className="inline-flex rounded-full peer-focus-visible:ring-4 peer-focus-visible:ring-[var(--focus-ring)]">
            <SwitchTrack checked={checked} />
          </span>
        </label>
      </div>
    );
  }

  return (
    <div className="relative">
      <label className={rowClass}>
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
          className="peer sr-only"
        />
        <CheckboxIndicator checked={checked} />
        <span className={cx("flex-1", labelTextClass)}>{label}</span>
        {tooltip && <span aria-hidden="true" className="h-4 w-4 shrink-0" />}
      </label>
      {tooltip && (
        <div className="absolute right-3.5 top-1/2 z-10 h-4 w-4 -translate-y-1/2">{helpDot}</div>
      )}
    </div>
  );
}
