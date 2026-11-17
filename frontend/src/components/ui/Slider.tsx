import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { beginDocumentGesture } from "../../stores/converter/documentGestures";
import { cx } from "./panelPrimitives";
import HelpDot from "./HelpDot";
import type { WikiDocPath } from "../../utils/wikiDocs";

interface SliderProps {
  className?: string;
  label: string;
  value: number;
  min: number;
  /** Optional data-testid forwarded to the underlying range input. */
  /** 可选的 data-testid，转发给底层 range 输入。 */
  "data-testid"?: string;
  max: number;
  /** Optional upper bound for precise text entry; defaults to the range max. */
  /** 可选的精确文本输入上限；未提供时沿用滑轨上限。 */
  inputMax?: number;
  step: number;
  onChange: (value: number) => void;
  /** Optional normalizer for committed text input before display and onChange. */
  /** 可选的文本输入标准化函数，在显示和触发 onChange 前应用。 */
  normalizeTextValue?: (value: number) => number;
  disabled?: boolean;
  unit?: string;
  tooltip?: string;
  wikiPath?: WikiDocPath;
  displayDecimals?: number;
  minInputWidthCh?: number;
}

export default function Slider(props: SliderProps) {
  const finishGesture = useRef<(() => void) | null>(null);
  const endGesture = () => { finishGesture.current?.(); finishGesture.current = null; };
  useEffect(() => () => { finishGesture.current?.(); }, []);
  const {
  className,
  label,
  value,
  min,
  max,
  inputMax,
  step,
  onChange,
  normalizeTextValue,
  disabled = false,
  unit,
  tooltip,
  wikiPath,
  displayDecimals,
  minInputWidthCh,
  } = props;
  const testId = props["data-testid"];
  const preciseInputMax = inputMax ?? max;
  // 输入框的本地文本状态，编辑时不立即同步外部 value
  const [inputText, setInputText] = useState(() => formatValue(value, step, displayDecimals));
  const [isFocused, setIsFocused] = useState(false);

  // 外部 value 变化时，如果输入框没有焦点，同步显示
  useEffect(() => {
    if (!isFocused) {
      setInputText(formatValue(value, step, displayDecimals));
    }
  }, [value, step, displayDecimals, isFocused]);

  const clampAndRound = useCallback(
    (num: number) => {
      // Clamp into [min, max] and round to the display precision. We do NOT
      // re-anchor the value to a step grid based at 0: the native
      // `<input type="range">` already anchors its step grid at `min`, which
      // yields values like 0.2, 0.28, 0.36... for min=0.2/step=0.08. Forcing
      // these onto a 0-anchored grid would bump every drag emission up by
      // half a step (e.g. 1.16 → 1.20, 1.24 → 1.28), making users feel the
      // slider "auto-adds 0.08" every time they release it.
      // 只做 [min, max] 夹紧并按显示精度取整。不再把值重新对齐到以 0 为锚点
      // 的 step 网格：原生 `<input type="range">` 自身以 `min` 为锚点（例如
      // min=0.2/step=0.08 会发出 0.2、0.28、0.36…）。若强制对齐到 0 锚点，
      // 每次拖动释放都会把值向上平移半格（1.16→1.20、1.24→1.28），用户会
      // 感觉"一放手就自动加 0.08"。
      const clamped = Math.min(max, Math.max(min, num));
      const decimals = getStepDecimals(step);
      return parseFloat(clamped.toFixed(decimals));
    },
    [min, max, step],
  );

  const commitValue = useCallback(
    (text: string) => {
      // Focusing or confirming the displayed value must not round the stored
      // value when the field shows fewer decimal places than the source.
      if (text === formatValue(value, step, displayDecimals)) return;
      const num = parseFloat(text);
      if (!Number.isFinite(num)) {
        // 无效输入，恢复为当前值
        setInputText(formatValue(value, step, displayDecimals));
        return;
      }
      // Text input is the precise-entry path: clamp to [min, inputMax] and round
      // to the display precision. Same treatment as range drag — see
      // `clampAndRound` above.
      // 文本框同样只做 [min, inputMax] 夹紧与显示精度圆整，路径与滑条拖动一致。
      const clamped = Math.min(preciseInputMax, Math.max(min, num));
      const decimals = getDisplayDecimals(step, displayDecimals);
      const final = parseFloat(clamped.toFixed(decimals));
      const normalized = normalizeTextValue?.(final) ?? final;
      onChange(normalized);
      setInputText(formatValue(normalized, step, displayDecimals));
    },
    [value, step, min, preciseInputMax, onChange, normalizeTextValue, displayDecimals],
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
      setInputText(formatValue(value, step, displayDecimals));
      (e.target as HTMLInputElement).blur();
    }
  };

  // 计算输入框宽度：根据 max 值的字符数 + unit
  const formattedCurrentValue = useMemo(
    () => formatValue(value, step, displayDecimals),
    [value, step, displayDecimals],
  );

  const inputChars = Math.max(
    formatValue(max, step, displayDecimals).length,
    formatValue(min, step, displayDecimals).length,
    formattedCurrentValue.length,
    inputText.length,
    minInputWidthCh ?? 6,
  );
  const inputWidth = `${inputChars + 1}ch`;

  // When a manually entered value is above the everyday drag range, keep the
  // thumb at the range edge while preserving the exact value in the text box.
  // 手动输入值超过日常拖动范围时，滑块停在边缘，文本框仍保留精确值。
  const rangeValue = Math.min(max, Math.max(min, value));

  return (
    <div className={cx("flex flex-col gap-1.5", className)}>
      <div className="flex min-w-0 items-center justify-between gap-3">
        {label && (
          <label className="flex min-w-0 items-center gap-1.5 text-sm font-medium text-slate-700 dark:text-slate-200">
            <span className="truncate">{label}</span>
            {tooltip && <HelpDot title={label} description={tooltip} wikiPath={wikiPath} ariaLabel={tooltip} />}
          </label>
        )}
        <div
          className={cx(
            "slider-value-field flex shrink-0 items-center gap-1 rounded-[8px] border border-transparent bg-[var(--surface-well)] pr-1.5 transition-all duration-200 hover:border-[color:var(--surface-card-outline)] focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-[var(--focus-ring)]",
            disabled && "cursor-not-allowed opacity-45",
          )}
        >
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
            className="min-w-0 bg-transparent px-1.5 py-1 text-center text-sm tabular-nums text-slate-700 outline-none disabled:cursor-not-allowed dark:text-slate-100"
            aria-label={`${label} value`}
          />
          <span className="min-w-6 shrink-0 text-[11px] font-medium text-slate-400 dark:text-slate-500">
            {unit}
          </span>
        </div>
      </div>
      <div className="flex items-center py-1.5">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={rangeValue}
          disabled={disabled}
          aria-label={label}
          data-testid={testId}
          onPointerDown={(event) => { endGesture(); finishGesture.current = beginDocumentGesture(); event.currentTarget.setPointerCapture?.(event.pointerId); }}
          onPointerUp={endGesture}
          onPointerCancel={endGesture}
          onLostPointerCapture={endGesture}
          onKeyDown={(event) => {
            if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End"].includes(event.key) && !finishGesture.current) finishGesture.current = beginDocumentGesture();
          }}
          onKeyUp={endGesture}
          onBlur={endGesture}
          onChange={(e) => onChange(clampAndRound(Number(e.target.value)))}
          className={cx(
            "slider-track w-full min-w-0 appearance-none cursor-pointer rounded-full accent-blue-500 transition-all duration-200",
            "h-1.5 bg-[var(--surface-well)] dark:bg-slate-700",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] disabled:cursor-not-allowed disabled:opacity-45"
          )}
        />
      </div>
    </div>
  );
}

/** 根据显示精度格式化数值 */
function formatValue(val: number, step: number, displayDecimals?: number): string {
  const decimals = getDisplayDecimals(step, displayDecimals);
  return val.toFixed(decimals);
}

/** 获取 step 的小数位数 */
function getStepDecimals(step: number): number {
  const s = step.toString();
  const dot = s.indexOf(".");
  return dot === -1 ? 0 : s.length - dot - 1;
}

/** 获取输入框显示所需的小数位数 */
function getDisplayDecimals(step: number, displayDecimals?: number): number {
  return displayDecimals ?? getStepDecimals(step);
}
