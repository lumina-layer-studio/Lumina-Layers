import { useId } from "react";

interface RadioGroupProps {
  label: string;
  value: string;
  options: { label: string; value: string }[];
  onChange: (value: string) => void;
  disabled?: boolean;
  disabledValues?: string[];
}

export default function RadioGroup({
  label,
  value,
  options,
  onChange,
  disabled = false,
  disabledValues = [],
}: RadioGroupProps) {
  const groupId = useId();

  return (
    <fieldset className="flex flex-col gap-1.5" disabled={disabled}>
      <legend className="text-sm text-gray-700 dark:text-gray-300">{label}</legend>
      <div className="flex flex-col gap-1">
        {options.map((opt) => {
          const isDisabled = disabled || disabledValues.includes(opt.value);
          return (
            <label
              key={opt.value}
              className={`flex items-center gap-2 text-sm ${isDisabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer"}`}
            >
              <input
                type="radio"
                name={`${groupId}-${label}`}
                value={opt.value}
                checked={value === opt.value}
                disabled={isDisabled}
                onChange={() => onChange(opt.value)}
                className="h-4 w-4 border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-blue-500 accent-blue-500 disabled:cursor-not-allowed"
              />
              <span className="text-gray-700 dark:text-gray-300">{opt.label}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
