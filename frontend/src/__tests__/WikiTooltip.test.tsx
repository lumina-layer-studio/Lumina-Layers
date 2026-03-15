/**
 * Unit tests for WikiTooltip component.
 *
 * Validates specific interaction scenarios, edge cases, and accessibility
 * attributes that complement the property-based tests.
 *
 * Requirements covered: 1.1, 1.2, 3.5, 6.2, 6.3
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, act } from "@testing-library/react";
import type { ReactNode } from "react";

// ---------------------------------------------------------------------------
// Capture onOpenChange + useHover args for controlling tooltip state in tests
// ---------------------------------------------------------------------------
let capturedOnOpenChange: ((open: boolean) => void) | null = null;
let capturedHoverOpts: Record<string, unknown> = {};

vi.mock("@floating-ui/react", () => {
  const setRef = vi.fn();
  const fakeContext = {};

  return {
    useFloating: (opts: Record<string, unknown>) => {
      capturedOnOpenChange =
        (opts.onOpenChange as (v: boolean) => void) ?? null;
      return {
        refs: { setReference: setRef, setFloating: setRef },
        floatingStyles: {},
        context: fakeContext,
      };
    },
    useHover: (_ctx: unknown, opts: Record<string, unknown>) => {
      capturedHoverOpts = opts ?? {};
      return {};
    },
    useDismiss: () => ({}),
    useRole: () => ({}),
    useInteractions: () => ({
      getReferenceProps: () => ({}),
      getFloatingProps: () => ({ role: "tooltip" }),
    }),
    offset: () => null,
    flip: () => null,
    shift: () => null,
    autoUpdate: () => () => {},
    FloatingPortal: ({ children }: { children: ReactNode }) => children,
  };
});

// Mock framer-motion to render immediately without animation
vi.mock("framer-motion", () => ({
  AnimatePresence: ({ children }: { children: ReactNode }) => children,
  motion: {
    div: ({
      children,
      initial: _i,
      animate: _a,
      exit: _e,
      transition: _t,
      ...rest
    }: Record<string, unknown> & { children?: ReactNode }) => {
      const { ref, style, className, ...htmlProps } = rest as Record<
        string,
        unknown
      >;
      return (
        <div
          ref={ref as React.Ref<HTMLDivElement>}
          style={style as React.CSSProperties}
          className={className as string}
          data-testid="tooltip-bubble"
          {...(htmlProps as React.HTMLAttributes<HTMLDivElement>)}
        >
          {children}
        </div>
      );
    },
  },
}));

import WikiTooltip from "../components/ui/WikiTooltip";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Render WikiTooltip and optionally force it open via onOpenChange(true). */
async function renderAndOpen(
  props: {
    title: string;
    description: string;
    wikiUrl?: string;
    delay?: number;
  },
  open = true
) {
  let result: ReturnType<typeof render>;
  await act(async () => {
    result = render(
      <WikiTooltip {...props}>
        <button>Trigger</button>
      </WikiTooltip>
    );
  });

  if (open && capturedOnOpenChange) {
    await act(async () => {
      capturedOnOpenChange!(true);
    });
  }

  return result!;
}

// ---------------------------------------------------------------------------
// Setup / Teardown
// ---------------------------------------------------------------------------
beforeEach(() => {
  capturedOnOpenChange = null;
  capturedHoverOpts = {};
});

afterEach(() => {
  cleanup();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("WikiTooltip unit tests", () => {
  /**
   * Requirement 1.1: WHEN user hovers on Trigger_Element for > 600ms,
   * tooltip SHALL appear.
   *
   * We verify that useHover receives the correct default delay config (600ms)
   * and that calling onOpenChange(true) makes the tooltip visible.
   */
  it("shows tooltip after 600ms hover delay (default config)", async () => {
    const { container } = await renderAndOpen({
      title: "Test Title",
      description: "Test Description",
    });

    // Verify useHover received the default 600ms open delay
    const hoverDelay = capturedHoverOpts.delay as {
      open: number;
      close: number;
    };
    expect(hoverDelay).toBeDefined();
    expect(hoverDelay.open).toBe(600);

    // Tooltip bubble should be visible after onOpenChange(true)
    const bubble = container.querySelector('[data-testid="tooltip-bubble"]');
    expect(bubble).not.toBeNull();
    expect(bubble!.textContent).toContain("Test Title");
    expect(bubble!.textContent).toContain("Test Description");
  });

  /**
   * Requirement 1.2: WHEN user leaves Trigger_Element within 600ms,
   * tooltip SHALL remain hidden.
   *
   * We verify that without calling onOpenChange(true), the tooltip stays hidden.
   */
  it("does not show tooltip when onOpenChange is not triggered", async () => {
    const { container } = await renderAndOpen(
      {
        title: "Hidden Title",
        description: "Hidden Description",
      },
      false // do NOT force open
    );

    // Tooltip bubble should NOT be in the DOM
    const bubble = container.querySelector('[data-testid="tooltip-bubble"]');
    expect(bubble).toBeNull();

    // Content should not appear anywhere
    expect(container.textContent).not.toContain("Hidden Title");
  });

  /**
   * Requirement 3.5: WHEN wikiUrl is not provided,
   * tooltip SHALL NOT render the wiki link button.
   */
  it("does not render wiki link when wikiUrl is not provided", async () => {
    const { container } = await renderAndOpen({
      title: "No Link",
      description: "No wiki URL here",
    });

    const bubble = container.querySelector('[data-testid="tooltip-bubble"]');
    expect(bubble).not.toBeNull();

    // No <a> element should exist inside the bubble
    const link = bubble!.querySelector("a");
    expect(link).toBeNull();
  });

  /**
   * Requirement 6.2: Tooltip_Bubble SHALL have role="tooltip".
   *
   * Our mock's getFloatingProps returns { role: "tooltip" }, which gets
   * spread onto the motion.div. Verify the attribute is present.
   */
  it("has role='tooltip' accessibility attribute on the bubble", async () => {
    const { container } = await renderAndOpen({
      title: "Accessible",
      description: "With role",
    });

    // role="tooltip" is on the outer positioning div (from getFloatingProps),
    // which is the parent of the motion.div (data-testid="tooltip-bubble")
    const bubble = container.querySelector('[data-testid="tooltip-bubble"]');
    expect(bubble).not.toBeNull();
    const positioningDiv = bubble!.parentElement;
    expect(positioningDiv).not.toBeNull();
    expect(positioningDiv!.getAttribute("role")).toBe("tooltip");
  });

  /**
   * Requirement 6.3: Wiki link SHALL be keyboard-focusable via Tab.
   *
   * An <a> element with href is natively focusable. We verify the link
   * exists and can receive focus.
   */
  it("wiki link is keyboard-focusable when wikiUrl is provided", async () => {
    const { container } = await renderAndOpen({
      title: "Keyboard Test",
      description: "Focus the link",
      wikiUrl: "https://example.com/wiki",
    });

    const bubble = container.querySelector('[data-testid="tooltip-bubble"]');
    expect(bubble).not.toBeNull();

    const link = bubble!.querySelector("a");
    expect(link).not.toBeNull();
    expect(link!.getAttribute("href")).toBe("https://example.com/wiki");

    // <a> with href is natively focusable — verify it can receive focus
    link!.focus();
    expect(document.activeElement).toBe(link);
  });
});
