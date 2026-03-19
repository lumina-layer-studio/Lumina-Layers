interface CheckboxProps {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}

export default function Checkbox({
  label,
  checked,
  onChange,
  disabled = false,
}: CheckboxProps) {
  return (
    <label
      className={`flex items-center gap-3 rounded-2xl border px-3 py-2 text-sm transition-colors ${
        disabled
          ? "cursor-not-allowed border-slate-200/60 bg-slate-100/70 opacity-45 dark:border-slate-800/60 dark:bg-slate-900/50"
          : "cursor-pointer border-slate-200/80 bg-white/60 hover:border-slate-300 hover:bg-white/75 dark:border-slate-700/80 dark:bg-slate-900/55 dark:hover:border-slate-600 dark:hover:bg-slate-900/75"
      }`}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded border-slate-300 bg-white text-blue-500 accent-blue-500 transition-all duration-200 focus:ring-4 focus:ring-[var(--focus-ring)] outline-none disabled:cursor-not-allowed dark:border-slate-600 dark:bg-slate-800"
      />
      <span className="text-slate-700 dark:text-slate-200">{label}</span>
    </label>
  );
}
