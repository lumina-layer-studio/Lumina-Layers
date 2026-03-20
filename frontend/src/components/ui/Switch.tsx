import { cx } from "./panelPrimitives";

interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  checkedLabel?: string;
  uncheckedLabel?: string;
  disabled?: boolean;
}

export default function Switch({
  checked,
  onChange,
  checkedLabel,
  uncheckedLabel,
  disabled = false,
}: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx(
        "relative inline-flex min-h-11 items-center rounded-[22px] border px-3 py-2 transition-all duration-200 focus:outline-none focus-visible:ring-4 focus-visible:ring-[var(--focus-ring)]",
        checked
          ? "border-blue-400 bg-white/92 dark:border-blue-400/80 dark:bg-slate-900/82"
          : "border-slate-200/80 bg-white/60 dark:border-slate-700/80 dark:bg-slate-900/55",
        disabled
          ? "cursor-not-allowed opacity-40"
          : "cursor-pointer hover:border-slate-300 hover:bg-white/75 dark:hover:border-slate-600 dark:hover:bg-slate-900/75",
        checkedLabel || uncheckedLabel ? "min-w-[clamp(5.5rem,10vw,7rem)] justify-between gap-2.5" : "w-[clamp(3.75rem,6vw,4.5rem)] justify-end"
      )}
    >
      {(checkedLabel || uncheckedLabel) && (
        <span
          className={cx(
            "w-full select-none text-[11px] font-medium transition-colors duration-200",
            checked ? "text-blue-700 dark:text-blue-200" : "text-slate-500 dark:text-slate-300",
            checked ? "text-left" : "text-right"
          )}
        >
          {checked ? checkedLabel : uncheckedLabel}
        </span>
      )}
      <span
        aria-hidden="true"
        className={cx(
          "relative inline-flex h-6 w-11 shrink-0 rounded-full border transition-colors duration-200",
          checked
            ? "border-blue-500 bg-blue-500"
            : "border-slate-300 bg-slate-200 dark:border-slate-600 dark:bg-slate-700"
        )}
      >
        <span
          className={cx(
            "absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all duration-200",
            checked ? "right-0.5" : "left-0.5"
          )}
        />
      </span>
    </button>
  );
}
