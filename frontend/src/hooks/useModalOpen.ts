import { useEffect, useState } from "react";

const MODAL_SELECTOR = '[aria-modal="true"]';

function hasOpenModal(): boolean {
  return document.querySelector(MODAL_SELECTOR) !== null;
}

/**
 * Whether any modal dialog (``aria-modal="true"``) is currently in the page.
 * 页面中是否有打开的模态弹窗（aria-modal="true"）。
 *
 * Dialogs are spread across many components and portals, so the document is
 * watched instead of asking each dialog to report itself.
 * 弹窗分散在许多组件和 portal 中，因此直接监听文档，而不是让每个弹窗自行上报。
 */
export function useModalOpen(enabled: boolean): boolean {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    const update = () => setOpen(hasOpenModal());
    update();
    const observer = new MutationObserver(update);
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["aria-modal"],
    });
    return () => observer.disconnect();
  }, [enabled]);

  return enabled && open;
}
