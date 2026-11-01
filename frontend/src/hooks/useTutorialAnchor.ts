import { useEffect, useState } from "react";
import type { TutorialRect } from "../components/tutorial/tutorialPlacement";

export type TutorialAnchorStatus = "searching" | "found" | "missing";

export interface TutorialAnchorState {
  status: TutorialAnchorStatus;
  rect: TutorialRect | null;
}

/** How long to wait for a panel to mount/expand before giving up. 等待面板挂载/展开的上限。 */
export const TUTORIAL_ANCHOR_TIMEOUT_MS = 800;

function findVisibleRect(
  anchors: readonly string[],
): { element: HTMLElement; rect: TutorialRect } | null {
  // The first anchor that is mounted and visible wins, so a step can point at
  // a precise control and fall back to its surrounding section.
  // 取第一个已渲染且可见的锚点：步骤可以先指向具体控件，找不到时退回所在区块。
  for (const anchor of anchors) {
    const element = document.querySelector<HTMLElement>(`[data-tutorial="${anchor}"]`);
    if (!element) {
      continue;
    }
    const box = element.getBoundingClientRect();
    if (box.width <= 0 || box.height <= 0) {
      continue;
    }
    return {
      element,
      rect: { top: box.top, left: box.left, width: box.width, height: box.height },
    };
  }
  return null;
}

/**
 * The element a step's anchor currently resolves to (first visible candidate).
 * 步骤锚点当前对应的元素（第一个可见的候选）。
 */
export function findTutorialAnchorElement(
  anchor: string | readonly string[] | null,
): HTMLElement | null {
  if (anchor === null) return null;
  return findVisibleRect(typeof anchor === "string" ? [anchor] : anchor)?.element ?? null;
}

function sameRect(a: TutorialRect | null, b: TutorialRect | null): boolean {
  if (a === null || b === null) {
    return a === b;
  }
  return (
    Math.abs(a.top - b.top) < 0.5 &&
    Math.abs(a.left - b.left) < 0.5 &&
    Math.abs(a.width - b.width) < 0.5 &&
    Math.abs(a.height - b.height) < 0.5
  );
}

/**
 * Track the on-screen rect of a `data-tutorial` anchor every animation frame.
 * 逐帧跟踪 `data-tutorial` 锚点在屏幕上的位置。
 *
 * Panels can animate, be dragged, or scroll, so the rect is re-read each frame
 * and state only changes when it moves. The anchor is scrolled into view once
 * when first found. After the timeout without a visible anchor the status
 * becomes "missing" so the card can fall back to the center.
 * 面板可能在动画、被拖动或滚动，因此逐帧读取位置，只有变化时才更新状态；
 * 首次找到时滚动到可见区域；超时仍找不到则标记为 missing，卡片改为居中。
 *
 * Args:
 *     anchor (string | readonly string[] | null): `data-tutorial` value, or
 *         candidates tried in order; null means no anchor. 锚点值或按顺序尝试的候选列表。
 *
 * Returns:
 *     TutorialAnchorState: Current status and rect. 当前状态与位置。
 */
export function useTutorialAnchor(
  anchor: string | readonly string[] | null,
): TutorialAnchorState {
  const anchors: readonly string[] =
    anchor === null ? [] : typeof anchor === "string" ? [anchor] : anchor;
  // Stable effect dependency even when a new array instance is passed.
  const anchorKey = anchors.join("\n");

  const [state, setState] = useState<TutorialAnchorState>(() => ({
    status: anchors.length > 0 ? "searching" : "missing",
    rect: null,
  }));

  useEffect(() => {
    const candidates = anchorKey ? anchorKey.split("\n") : [];
    if (candidates.length === 0) {
      setState({ status: "missing", rect: null });
      return;
    }

    setState({ status: "searching", rect: null });
    const startedAt = performance.now();
    let scrolled = false;
    let lastStatus: TutorialAnchorStatus = "searching";
    let lastRect: TutorialRect | null = null;
    let frame = 0;

    const tick = () => {
      const found = findVisibleRect(candidates);
      if (found && !scrolled) {
        scrolled = true;
        found.element.scrollIntoView?.({ block: "nearest", inline: "nearest" });
      }

      const nextRect = found ? found.rect : null;
      const nextStatus: TutorialAnchorStatus = found
        ? "found"
        : lastStatus === "found" || performance.now() - startedAt >= TUTORIAL_ANCHOR_TIMEOUT_MS
          ? "missing"
          : "searching";

      if (nextStatus !== lastStatus || !sameRect(nextRect, lastRect)) {
        lastStatus = nextStatus;
        lastRect = nextRect;
        setState({ status: nextStatus, rect: nextRect });
      }
      frame = window.requestAnimationFrame(tick);
    };

    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [anchorKey]);

  return state;
}
