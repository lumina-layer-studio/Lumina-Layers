import { useId } from "react";
import {
  cx,
  workstationChoiceRowActiveClass,
  workstationChoiceRowClass,
  workstationChoiceRowDisabledClass,
  workstationFieldLabelClass,
} from "./panelPrimitives";
import HelpDot from "./HelpDot";
import type { WikiDocPath } from "../../utils/wikiDocs";

interface RadioGroupProps {
  label: string;
  value: string;
  options: { label: string; value: string }[];
  onChange: (value: string) => void;
  disabled?: boolean;
  disabledValues?: string[];
  columns?: 1 | 2;
  /** Optional hint text; renders a HelpDot after the group label. */
  tooltip?: string;
  /** Optional matching article in the public Lumina Wiki. */
  wikiPath?: WikiDocPath;
}

export function RadioIndicator({ checked }: { checked: boolean }) {
  return <span aria-hidden="true" className={cx(
    "flex h-5 w-5 shrink-0 items-center justify-center rounded-full border transition-colors duration-200 peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-[var(--focus-ring)]",
    checked ? "border-blue-500 bg-blue-500" : "border-slate-300/80 bg-white dark:border-slate-600/80 dark:bg-slate-800",
  )}>
    <span className={cx("h-2.5 w-2.5 rounded-full", checked ? "bg-white" : "bg-transparent")} />
  </span>;
}

export default function RadioGroup({
  label,
  value,
  options,
  onChange,
  disabled = false,
  disabledValues = [],
  columns = 1,
  tooltip,
  wikiPath,
}: RadioGroupProps) {
  const groupId = useId();
  const labelId = `${groupId}-label`;

  return (
    <fieldset
      className="flex flex-col gap-1.5"
      disabled={disabled}
      aria-labelledby={labelId}
    >
      <div className="flex items-center gap-1.5">
        <span id={labelId} className={workstationFieldLabelClass}>{label}</span>
        {tooltip && <HelpDot title={label} description={tooltip} wikiPath={wikiPath} ariaLabel={tooltip} />}
      </div>
      <div className={cx("grid gap-y-2", columns === 2 ? "grid-cols-2 gap-x-6" : "grid-cols-1")}>
        {options.map((opt) => {
          const isDisabled = disabled || disabledValues.includes(opt.value);
          const isActive = value === opt.value;
          return (
            <label
              key={opt.value}
              className={cx(
                "flex min-w-0 items-center gap-3 py-2 text-sm",
                workstationChoiceRowClass,
                !isDisabled && workstationChoiceRowActiveClass,
                isDisabled && workstationChoiceRowDisabledClass,
              )}
            >
              <input
                type="radio"
                name={`${groupId}-${label}`}
                value={opt.value}
                checked={isActive}
                disabled={isDisabled}
                onChange={() => onChange(opt.value)}
                className="peer sr-only"
              />
              <RadioIndicator checked={isActive} />
              <span className="min-w-0 break-words font-medium text-slate-700 dark:text-slate-200">{opt.label}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
