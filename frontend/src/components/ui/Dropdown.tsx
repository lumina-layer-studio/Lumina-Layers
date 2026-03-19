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
    <div className="flex flex-col gap-1">
      <label className="text-sm text-gray-700 dark:text-gray-300">{label}</label>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white/90 dark:bg-gray-800/90 px-3 py-1.5 text-sm text-gray-800 dark:text-gray-200 outline-none transition-all duration-200 hover:shadow-sm hover:border-gray-400 dark:hover:border-gray-500 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/40 disabled:opacity-40 disabled:cursor-not-allowed"
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
