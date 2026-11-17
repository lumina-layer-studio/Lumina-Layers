import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { CheckIcon, ChevronDownIcon } from "@heroicons/react/20/solid";
import { catalogFilterMenuClass, catalogFilterOptionClass, catalogFilterTriggerClass, cx, workstationFieldLabelClass, workstationInputClass } from "./panelPrimitives";
import HelpDot from "./HelpDot";
import type { WikiDocPath } from "../../utils/wikiDocs";
import { bindVerticalWheelScrollChain } from "../../utils/wheelScrollChain";

interface DropdownOption {
  label: string;
  value: string;
  leading?: ReactNode;
  description?: string;
}

interface DropdownOptionGroup {
  label: string;
  options: DropdownOption[];
}

interface DropdownProps {
  label: string;
  value: string;
  options?: DropdownOption[];
  groupedOptions?: DropdownOptionGroup[];
  onChange: (value: string) => void;
  disabled?: boolean;
  placeholder?: string;
  labelAccessory?: ReactNode;
  variant?: "field" | "inline" | "filter";
  /** Optional hint text; renders a HelpDot after the label (ignored if labelAccessory is set). */
  tooltip?: string;
  /** Optional matching article in the public Lumina Wiki. */
  wikiPath?: WikiDocPath;
}

export default function Dropdown({
  label,
  value,
  options,
  groupedOptions,
  onChange,
  disabled = false,
  placeholder,
  labelAccessory,
  variant = "field",
  tooltip,
  wikiPath,
}: DropdownProps) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number; width: number; maxHeight: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const listboxId = useId();
  const isGroupedMode = groupedOptions !== undefined;
  const isInline = variant === "inline";
  const isFilter = variant === "filter";
  const optionGroups = useMemo(() => {
    const groups = groupedOptions !== undefined
      ? groupedOptions.filter((group) => group.options.length > 0)
      : [{ label: "", options: options ?? [] }];
    let index = 0;
    return groups.map((group) => ({
      label: group.label,
      options: group.options.map((option) => ({ ...option, index: index++ })),
    }));
  }, [groupedOptions, options]);
  const flatOptions = useMemo(
    () => optionGroups.flatMap((group) => group.options),
    [optionGroups],
  );
  const visibleHeaderCount = isGroupedMode ? optionGroups.length : 0;

  if (options !== undefined && groupedOptions !== undefined) {
    console.warn(
      "Dropdown received both options and groupedOptions; groupedOptions will be used.",
    );
  }

  const selectedOption = useMemo(
    () => flatOptions.find((opt) => opt.value === value) ?? null,
    [flatOptions, value],
  );
  const activeOption = open ? flatOptions[activeIndex] : undefined;

  const updateMenuPos = useCallback(() => {
    if (!triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    const viewportPadding = 16;
    const maxMenuHeight = 288; // max-h-72 = 18rem = 288px
    // 估算实际菜单高度：每项约 44px（py-2.5 + leading-6），分组标题约 32px。
    // 选项少时远小于 maxMenuHeight，避免仅因未到 288px 就误判向上展开。
    const ITEM_HEIGHT = flatOptions.some(option => option.description) ? 80 : isFilter ? 36 : 44;
    const GROUP_HEADER_HEIGHT = 32;
    const MENU_PADDING = 16;
    const estimatedMenuHeight = Math.min(
      maxMenuHeight,
      flatOptions.length * ITEM_HEIGHT +
        visibleHeaderCount * GROUP_HEADER_HEIGHT +
        MENU_PADDING,
    );
    // 菜单宽度贴合触发器，避免在窄侧栏里被强制撑到最小宽度而溢出卡片边界。
    const maxWidth = window.innerWidth - viewportPadding * 2;
    const nextWidth = Math.min(isFilter ? Math.max(rect.width, 220) : isInline ? Math.max(rect.width, 280) : rect.width, maxWidth);
    const nextLeft = Math.min(
      Math.max(rect.left, viewportPadding),
      window.innerWidth - viewportPadding - nextWidth,
    );

    // 只有当菜单实际装不下时才考虑向上展开；并且向上要比向下空间更大才翻转。
    const spaceBelow = window.innerHeight - rect.bottom - viewportPadding;
    const spaceAbove = rect.top - viewportPadding;
    const shouldOpenUpward =
      spaceBelow < estimatedMenuHeight && spaceAbove > spaceBelow;
    const upwardHeight = Math.min(estimatedMenuHeight, Math.max(spaceAbove, 0));

    setMenuPos({
      top: shouldOpenUpward ? rect.top - upwardHeight - 6 : rect.bottom + 6,
      left: nextLeft,
      width: nextWidth,
      maxHeight: Math.max(0, Math.min(maxMenuHeight, (shouldOpenUpward ? spaceAbove : spaceBelow) - 6)),
    });
  }, [flatOptions, visibleHeaderCount, isInline, isFilter]);

  useEffect(() => {
    if (!open) return;
    updateMenuPos();
    const unbindWheel = bindVerticalWheelScrollChain(menuRef.current, triggerRef.current);
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
      unbindWheel();
      document.removeEventListener("mousedown", handleClickOutside);
      window.removeEventListener("resize", updateMenuPos);
      window.removeEventListener("scroll", updateMenuPos, true);
    };
  }, [open, updateMenuPos]);

  useEffect(() => {
    if (!activeOption) return;
    document.getElementById(`${listboxId}-option-${activeOption.index}`)
      ?.scrollIntoView({ block: "nearest" });
  }, [activeOption, listboxId]);

  const handleToggle = () => {
    if (disabled) return;
    if (!open) {
      updateMenuPos();
      setActiveIndex(selectedOption?.index ?? (flatOptions.length > 0 ? 0 : -1));
    }
    triggerRef.current?.focus();
    setOpen((prev) => !prev);
  };

  const handleSelect = (nextValue: string) => {
    onChange(nextValue);
    setOpen(false);
    triggerRef.current?.focus();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>): void => {
    if (disabled) return;
    if (event.key === "Tab") {
      setOpen(false);
      return;
    }
    if (event.key === "Escape") {
      if (open) {
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
      }
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      event.stopPropagation();
      if (open && activeOption) {
        handleSelect(activeOption.value);
      } else {
        handleToggle();
      }
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    event.stopPropagation();
    if (flatOptions.length === 0) return;
    let nextIndex: number;
    if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = flatOptions.length - 1;
    } else if (!open) {
      nextIndex = selectedOption?.index ?? (event.key === "ArrowUp" ? flatOptions.length - 1 : 0);
    } else {
      nextIndex = Math.max(0, Math.min(flatOptions.length - 1,
        activeIndex + (event.key === "ArrowDown" ? 1 : -1),
      ));
    }
    updateMenuPos();
    setActiveIndex(nextIndex);
    setOpen(true);
  };

  const triggerLabel = selectedOption?.label ?? placeholder ?? "";
  const showPlaceholder = !selectedOption && !!placeholder;

  return (
    <div className="flex min-w-0 max-w-full flex-col gap-1.5">
      {!isInline && !isFilter && (labelAccessory || tooltip ? (
        <div className="flex items-center gap-2">
          <label className={workstationFieldLabelClass}>{label}</label>
          {labelAccessory ?? <HelpDot title={label} description={tooltip ?? ""} wikiPath={wikiPath} ariaLabel={tooltip} />}
        </div>
      ) : (
        <label className={workstationFieldLabelClass}>{label}</label>
      ))}
      <button
        ref={triggerRef}
        type="button"
        role="combobox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-haspopup="listbox"
        aria-activedescendant={activeOption ? `${listboxId}-option-${activeOption.index}` : undefined}
        aria-label={label}
        data-active={isFilter && open ? "true" : undefined}
        disabled={disabled}
        onClick={handleToggle}
        onKeyDown={handleKeyDown}
        onBlur={() => setOpen(false)}
        className={cx(
          isFilter ? catalogFilterTriggerClass : isInline
            ? "min-h-8 rounded-md px-1 py-1 text-xs text-slate-600 outline-none transition-colors hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] dark:text-slate-300 dark:hover:bg-slate-800/60"
            : workstationInputClass,
          "flex w-full min-w-0 items-center justify-between overflow-hidden text-left",
          isInline || isFilter ? "gap-1.5" : "gap-3 py-2",
          showPlaceholder && "text-slate-400 dark:text-slate-500",
        )}
      >
        {selectedOption?.leading && (
          <span className="flex shrink-0 items-center">
            {selectedOption.leading}
          </span>
        )}
        {isInline && <span className="shrink-0 text-slate-400 dark:text-slate-500">{label}:</span>}
        <span className={cx("block min-w-0 flex-1 truncate", isFilter ? "text-xs leading-4" : isInline ? "text-xs leading-6" : "text-sm leading-6")}>{triggerLabel}</span>
        <span
          aria-hidden="true"
          className={cx(
            "shrink-0 text-xs text-slate-400 transition-transform duration-200 dark:text-slate-500",
            open && "rotate-180"
          )}
        >
          {isFilter ? <ChevronDownIcon className="h-4 w-4" /> : <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
            <path d="M5.23 7.21a.75.75 0 011.06.02L10 11.17l3.71-3.94a.75.75 0 111.1 1.02l-4.25 4.52a.75.75 0 01-1.1 0L5.21 8.25a.75.75 0 01.02-1.04z" />
          </svg>}
        </span>
      </button>

      {open && menuPos && createPortal(
        <div
          ref={menuRef}
          className={catalogFilterMenuClass}
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
            aria-label={label}
            className="dock-scrollbar max-h-72 overflow-y-auto p-2"
            style={{ maxHeight: menuPos.maxHeight }}
          >
            {optionGroups.map((group) => (
              <div key={group.label || "__flat__"} className="min-w-0">
                {isGroupedMode && group.label && (
                  <div className="mt-2 px-3 pb-1 text-xs font-medium text-slate-500 first:mt-0 dark:text-slate-400">
                    {group.label}
                  </div>
                )}
                {group.options.map((opt) => {
                  const isSelected = opt.value === value;
                  return (
                    <button
                      key={`${group.label}-${opt.value}`}
                      type="button"
                      role="option"
                      id={`${listboxId}-option-${opt.index}`}
                      aria-selected={isSelected}
                      tabIndex={-1}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => handleSelect(opt.value)}
                      className={cx(
                        isFilter ? catalogFilterOptionClass : "flex min-h-11 w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm leading-6 transition-colors duration-150",
                        isSelected ? "bg-[var(--surface-well)] font-medium" : "hover:bg-[var(--surface-well)]",
                        opt.index === activeIndex && "bg-[var(--surface-well)] ring-2 ring-inset ring-[var(--focus-ring)]",
                      )}
                    >
                      {opt.leading && (
                        <span className="flex shrink-0 items-center">
                          {opt.leading}
                        </span>
                      )}
                      <span className="min-w-0 flex-1">
                        <span className="block break-all">{opt.label}</span>
                        {opt.description && <span className="mt-1 block text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">{opt.description}</span>}
                      </span>
                      <CheckIcon aria-hidden="true" className={cx("h-4 w-4 shrink-0", !isSelected && "invisible")} />
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
