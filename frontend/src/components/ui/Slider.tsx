import { useState, useEffect, useCallback } from "react";
import { cx } from "./panelPrimitives";

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
  // 输入框的本地文本状态，编辑时不立即同步外部 value
  const [inputText, setInputText] = useState(() => formatValue(value, step));
  const [isFocused, setIsFocused] = useState(false);

  // 外部 value 变化时，如果输入框没有焦点，同步显示
  useEffect(() => {
    if (!isFocused) {
      setInputText(formatValue(value, step));
    }
  }, [value, step, isFocused]);

  const commitValue = useCallback(
    (text: string) => {
      const num = parseFloat(text);
      if (isNaN(num)) {
        // 无效输入，恢复为当前值
        setInputText(formatValue(value, step));
        return;
      }
      // clamp 到 min/max 范围，并对齐 step
      const clamped = Math.min(max, Math.max(min, num));
      const aligned = Math.round(clamped / step) * step;
      // 修正浮点精度
      const decimals = getDecimals(step);
      const final = parseFloat(aligned.toFixed(decimals));
      onChange(final);
      setInputText(formatValue(final, step));
    },
    [value, min, max, step, onChange],
  );

  const handleBlur = () => {
    setIsFocused(false);
    commitValue(inputText);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      commitValue(inputText);
      (e.target as HTMLInputElement).blur();
    } else if (e.key === "Escape") {
      setInputText(formatValue(value, step));
      (e.target as HTMLInputElement).blur();
    }
  };

  // 计算输入框宽度：根据 max 值的字符数 + unit
  const maxChars = Math.max(
    formatValue(max, step).length,
    formatValue(min, step).length,
    4,
  );
  const inputWidth = `${maxChars + 1}ch`;

  return (
    <div className="flex flex-col gap-1.5">
      {label && (
        <label className="text-sm font-medium text-slate-700 dark:text-slate-200">
          {label}
        </label>
      )}
      <div className="flex items-center gap-3 rounded-2xl border border-slate-200/80 bg-white/58 px-3 py-2 shadow-[var(--shadow-control)] dark:border-slate-700/80 dark:bg-slate-900/48">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(Number(e.target.value))}
          className={cx(
            "slider-track flex-1 appearance-none cursor-pointer rounded-full accent-blue-500 transition-all duration-200",
            "h-1.5 bg-slate-200 dark:bg-slate-700",
            "focus:outline-none focus:ring-4 focus:ring-[var(--focus-ring)] disabled:cursor-not-allowed disabled:opacity-45"
          )}
        />
        <div className="flex items-center gap-0.5 shrink-0">
          <input
            type="text"
            inputMode="decimal"
            value={inputText}
            disabled={disabled}
            onChange={(e) => setInputText(e.target.value)}
            onFocus={() => setIsFocused(true)}
            onBlur={handleBlur}
            onKeyDown={handleKeyDown}
            style={{ width: inputWidth }}
            className="rounded-xl border border-slate-200/80 bg-white/90 px-2 py-1 text-right text-xs tabular-nums text-slate-700 shadow-[var(--shadow-control)] focus:border-blue-400 focus:outline-none focus:ring-4 focus:ring-[var(--focus-ring)] disabled:cursor-not-allowed disabled:opacity-45 dark:border-slate-700/80 dark:bg-slate-900 dark:text-slate-100"
            aria-label={`${label} value`}
          />
          {unit && (
            <span className="text-[11px] font-medium text-slate-400 dark:text-slate-500">
              {unit}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/** 根据 step 精度格式化数值 */
function formatValue(val: number, step: number): string {
  const decimals = getDecimals(step);
  return val.toFixed(decimals);
}

/** 获取 step 的小数位数 */
function getDecimals(step: number): number {
  const s = step.toString();
  const dot = s.indexOf(".");
  return dot === -1 ? 0 : s.length - dot - 1;
}
