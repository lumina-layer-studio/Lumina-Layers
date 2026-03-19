import { cx } from "./panelPrimitives";

interface DropdownProps {
  label: string;
  value: string;
  options: { label: string; value: string }[];
  onChange: (value: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export default function Dropdown({
  label,
  value,
  options,
  onChange,
  disabled = false,
  placeholder,
}: DropdownProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-sm font-medium text-slate-700 dark:text-slate-200">{label}</label>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className={cx(
          "min-h-11 w-full rounded-2xl border px-3.5 py-2 text-sm text-slate-800 outline-none transition-all duration-200",
          "border-slate-200/80 bg-white/82 shadow-[var(--shadow-control)] hover:border-slate-300 hover:shadow-[var(--shadow-control-hover)]",
          "focus:border-blue-400 focus:ring-4 focus:ring-[var(--focus-ring)] dark:border-slate-700/80 dark:bg-slate-900/72 dark:text-slate-100 dark:hover:border-slate-600",
          "disabled:cursor-not-allowed disabled:opacity-45"
        )}
      >
        {placeholder && (
          <option value="" disabled>
            {placeholder}
          </option>
        )}
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}
