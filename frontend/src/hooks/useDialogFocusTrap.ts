import { useEffect, useRef } from "react";
import type { RefObject } from "react";

const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

export interface DialogFocusTrapOptions {
  /**
   * Element to focus when the trap activates; defaults to the container.
   * 激活时优先聚焦的元素；默认聚焦容器本身。
   */
  initialFocus?: (container: HTMLElement) => HTMLElement | null;
}

function listFocusable(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(`${FOCUSABLE_SELECTOR}, summary`)).filter(element => {
    if (element.closest("[inert], [hidden]")) return false;
    const folded = element.closest("details:not([open])");
    return !folded || folded.querySelector(":scope > summary")?.contains(element);
  });
}

/**
 * Keep keyboard focus inside a modal dialog while it is open.
 * 模态对话框打开期间，把键盘焦点限制在对话框内。
 *
 * On activation, focuses `initialFocus` (or the container). Tab / Shift+Tab
 * wrap between the first and last focusable elements, and focus that has
 * escaped the dialog is pulled back in. The previously focused element is
 * restored on deactivation.
 * 激活时聚焦 `initialFocus`（或容器）；Tab / Shift+Tab 在首尾可聚焦元素间循环，
 * 已离开对话框的焦点会被拉回；停用时恢复原先的焦点。
 *
 * Args:
 *     containerRef (RefObject<HTMLElement | null>): Dialog element. 对话框元素。
 *     active (boolean): Whether the trap is on. 是否启用。
 *     options (DialogFocusTrapOptions): Optional initial focus. 可选的初始焦点。
 */
export function useDialogFocusTrap(
  containerRef: RefObject<HTMLElement | null>,
  active: boolean,
  options: DialogFocusTrapOptions = {},
): void {
  const optionsRef = useRef(options);
  optionsRef.current = options;

  useEffect(() => {
    if (!active) {
      return;
    }
    const previous =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const container = containerRef.current;
    if (container) {
      const initial = optionsRef.current.initialFocus?.(container) ?? container;
      initial.focus({ preventScroll: true });
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Tab") {
        return;
      }
      const dialog = containerRef.current;
      if (!dialog) {
        return;
      }
      const focusable = listFocusable(dialog);
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus({ preventScroll: true });
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const current = document.activeElement;
      const inside = current instanceof Node && dialog.contains(current);

      if (event.shiftKey) {
        if (!inside || current === first || current === dialog) {
          event.preventDefault();
          last.focus();
        }
      } else if (!inside || current === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown, true);
    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
      if (previous && previous.isConnected) {
        previous.focus({ preventScroll: true });
      }
    };
  }, [active, containerRef]);
}
