import WikiTooltip from "./WikiTooltip";

interface CheckboxProps {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  tooltip?: string;
}

export default function Checkbox({
  label,
  checked,
  onChange,
  disabled = false,
  tooltip,
}: CheckboxProps) {
  const labelSpan = tooltip ? (
    <WikiTooltip title={label} description={tooltip} placement="top" delay={400}>
      <span className="text-gray-700 dark:text-gray-300 cursor-help border-b border-dashed border-gray-400 dark:border-gray-500">
        {label}
      </span>
    </WikiTooltip>
  ) : (
    <span className="text-gray-700 dark:text-gray-300">{label}</span>
  );

  return (
    <label
      className={`flex items-center gap-2 text-sm ${disabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer"}`}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-blue-500 accent-blue-500 transition-all duration-200 hover:scale-110 focus:ring-2 focus:ring-blue-500/40 outline-none disabled:cursor-not-allowed"
      />
      {labelSpan}
    </label>
  );
}
