/**
 * NavTabStrip - Tab strip shared by the primary and secondary navigation.
 * 主导航与子导航共用的标签条。
 *
 * The strip scrolls sideways only when a narrow window cannot hold its tabs
 * and never shows a scrollbar, so a vertical mouse wheel scrolls it
 * horizontally; trackpads and keyboard focus keep their native behaviour.
 * 只有窗口过窄放不下标签时才可横向滚动，且不显示滚动条，因此鼠标竖向滚轮会
 * 改为横向滚动；触控板和键盘聚焦保持原生行为。
 */
import type { AriaRole, ReactNode, Ref, WheelEvent } from "react";
import { NAV_TAB_STRIP_CLASS } from "./navTabStyles";

const DOM_DELTA_LINE = 1;
const DOM_DELTA_PAGE = 2;
const WHEEL_LINE_HEIGHT_PX = 16;

function wheelDeltaScale(event: WheelEvent<HTMLElement>): number {
  if (event.deltaMode === DOM_DELTA_LINE) {
    return WHEEL_LINE_HEIGHT_PX;
  }
  if (event.deltaMode === DOM_DELTA_PAGE) {
    return event.currentTarget.clientWidth;
  }
  return 1;
}

function scrollStripWithWheel(event: WheelEvent<HTMLElement>): void {
  const strip = event.currentTarget;
  if (strip.scrollWidth <= strip.clientWidth) {
    return;
  }
  if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) {
    return;
  }
  strip.scrollLeft += event.deltaY * wheelDeltaScale(event);
}

interface NavTabStripProps {
  children: ReactNode;
  /** Extra classes for the strip itself, not the row around it. */
  className?: string;
  navRef?: Ref<HTMLElement>;
  role?: AriaRole;
  tutorialAnchor?: string;
}

export default function NavTabStrip({
  children,
  className,
  navRef,
  role,
  tutorialAnchor,
}: NavTabStripProps) {
  return (
    <nav
      ref={navRef}
      role={role}
      data-tutorial={tutorialAnchor}
      className={className ? `${NAV_TAB_STRIP_CLASS} ${className}` : NAV_TAB_STRIP_CLASS}
      onWheel={scrollStripWithWheel}
    >
      <div className="flex min-w-max items-center gap-1">{children}</div>
    </nav>
  );
}
