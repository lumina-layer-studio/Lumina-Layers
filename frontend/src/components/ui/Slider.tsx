import { useId } from "react";

interface SliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  disabled?: boolean;
  unit?: string;
}

export default function Slider({
  label,
  value,
  min,
  max,
  step,
  onChange,
  disabled = false,
  unit,
}: SliderProps) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      {label && (
        <div className="flex items-center justify-between text-sm">
          <label htmlFor={id} className="text-gray-700 dark:text-gray-300">{label}</label>
          <span className="text-gray-500 dark:text-gray-400 tabular-nums">
            {typeof value === 'number' ? Number(value.toFixed(2)) : value}
            {unit ? ` ${unit}` : ""}
          </span>
        </div>
      )}
      <div className="flex items-center gap-2">
        <input
          id={id}
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(Number(e.target.value))}
          className="flex-1 h-1.5 rounded-full appearance-none cursor-pointer bg-gray-300 dark:bg-gray-700 accent-blue-500 disabled:opacity-40 disabled:cursor-not-allowed"
        />
        {!label && (
          <span className="text-[10px] text-gray-400 tabular-nums shrink-0 w-14 text-right">
            {typeof value === 'number' ? value.toFixed(2) : value}
            {unit ? ` ${unit}` : ""}
          </span>
        )}
      </div>
    </div>
  );
}
