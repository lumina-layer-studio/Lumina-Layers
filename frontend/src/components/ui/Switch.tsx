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
      className={`
        relative inline-flex items-center h-6 rounded-full transition-colors duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40
        ${disabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer"}
        ${checked ? "bg-blue-500" : "bg-gray-300 dark:bg-gray-600"}
        ${checkedLabel || uncheckedLabel ? "min-w-[72px] px-2" : "w-10"}
      `}
    >
      {(checkedLabel || uncheckedLabel) && (
        <span
          className={`
            text-[11px] font-medium select-none transition-opacity duration-200 w-full
            ${checked ? "text-white pr-5" : "text-gray-600 dark:text-gray-300 pl-5"}
            ${checked ? "text-left" : "text-right"}
          `}
        >
          {checked ? checkedLabel : uncheckedLabel}
        </span>
      )}
      <span
        className={`
          absolute top-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-transform duration-200
          ${checked ? "right-0.5" : "left-0.5"}
        `}
      />
    </button>
  );
}
