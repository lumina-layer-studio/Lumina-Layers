import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cx, workstationFieldLabelClass, workstationInputClass } from "./panelPrimitives";

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
  const [open, setOpen] = useState(false);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number; width: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const listboxId = useId();

  const selectedOption = useMemo(
    () => options.find((opt) => opt.value === value) ?? null,
    [options, value],
  );

  const updateMenuPos = useCallback(() => {
    if (!triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    const viewportPadding = 16;
    const maxMenuHeight = 288; // max-h-72 = 18rem = 288px
    const preferredWidth = Math.max(rect.width, 420);
    const maxWidth = window.innerWidth - viewportPadding * 2;
    const nextWidth = Math.min(preferredWidth, maxWidth);
    const nextLeft = Math.min(
      Math.max(rect.left, viewportPadding),
      window.innerWidth - viewportPadding - nextWidth,
    );
    
    // 检查下方空间是否足够，不够则向上展开
    const spaceBelow = window.innerHeight - rect.bottom - viewportPadding;
    const spaceAbove = rect.top - viewportPadding;
    const shouldOpenUpward = spaceBelow < maxMenuHeight && spaceAbove > spaceBelow;
    
    setMenuPos({
      top: shouldOpenUpward ? rect.top - maxMenuHeight - 6 : rect.bottom + 6,
      left: nextLeft,
      width: nextWidth,
    });
  }, []);

  useEffect(() => {
    if (!open) return;
    updateMenuPos();
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node;
      if (
        triggerRef.current && !triggerRef.current.contains(target) &&
        menuRef.current && !menuRef.current.contains(target)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    window.addEventListener("resize", updateMenuPos);
    window.addEventListener("scroll", updateMenuPos, true);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      window.removeEventListener("resize", updateMenuPos);
      window.removeEventListener("scroll", updateMenuPos, true);
    };
  }, [open, updateMenuPos]);

  const handleToggle = () => {
    if (disabled) return;
    if (!open) updateMenuPos();
    setOpen((prev) => !prev);
  };

  const handleSelect = (nextValue: string) => {
    onChange(nextValue);
    setOpen(false);
  };

  const triggerLabel = selectedOption?.label ?? placeholder ?? "";
  const showPlaceholder = !selectedOption && !!placeholder;

  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label className={workstationFieldLabelClass}>{label}</label>
      <button
        ref={triggerRef}
        type="button"
        role="combobox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-label={label}
        disabled={disabled}
        onClick={handleToggle}
        className={cx(
          workstationInputClass,
          "flex w-full min-w-0 items-center justify-between gap-3 overflow-hidden py-2.5 text-left",
          showPlaceholder && "text-slate-400 dark:text-slate-500",
        )}
      >
        <span className="block min-w-0 flex-1 truncate text-sm leading-6">{triggerLabel}</span>
        <span
          aria-hidden="true"
          className={cx(
            "shrink-0 text-xs text-slate-400 transition-transform duration-200 dark:text-slate-500",
            open && "rotate-180"
          )}
        >
          v
        </span>
      </button>

      {open && menuPos && createPortal(
        <div
          ref={menuRef}
          className="z-[1200] overflow-hidden rounded-[24px] border border-slate-200/85 bg-white/96 shadow-[var(--shadow-control)] backdrop-blur-xl dark:border-slate-700/85 dark:bg-slate-950/96"
          style={{
            position: "fixed",
            top: `${menuPos.top}px`,
            left: `${menuPos.left}px`,
            width: `${menuPos.width}px`,
          }}
        >
          <div
            id={listboxId}
            role="listbox"
            className="dock-scrollbar max-h-72 overflow-y-auto p-2"
          >
            {options.map((opt) => {
              const isSelected = opt.value === value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => handleSelect(opt.value)}
                  className={cx(
                    "flex w-full items-start rounded-[18px] px-3 py-2.5 text-left text-sm leading-6 transition-colors duration-150",
                    isSelected
                      ? "bg-blue-50 text-blue-700 dark:bg-blue-500/15 dark:text-blue-200"
                      : "text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-900"
                  )}
                >
                  <span className="min-w-0 flex-1 break-all">{opt.label}</span>
                </button>
              );
            })}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
