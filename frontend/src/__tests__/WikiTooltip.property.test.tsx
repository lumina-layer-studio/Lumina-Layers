/**
 * Property-Based Tests for WikiTooltip component.
 *
 * Uses fast-check to generate random inputs and verify universal properties
 * across all valid input combinations.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, act } from "@testing-library/react";
import * as fc from "fast-check";
import type { ReactNode } from "react";

// ---------------------------------------------------------------------------
// Capture args passed to useFloating / useHover so we can assert on them
// ---------------------------------------------------------------------------
let capturedFloatingArgs: Record<string, unknown> = {};
let capturedHoverArgs: Record<string, unknown> = {};

// Force tooltip open: call onOpenChange(true) synchronously so the component
// re-renders with isOpen=true on the next React commit.
vi.mock("@floating-ui/react", () => {
  const setRef = vi.fn();
  const fakeContext = {};

  return {
    useFloating: (opts: Record<string, unknown>) => {
      capturedFloatingArgs = opts;
      // Schedule state update to force tooltip visible
      if (typeof opts.onOpenChange === "function") {
        queueMicrotask(() => (opts.onOpenChange as (v: boolean) => void)(true));
      }
      return {
        refs: { setReference: setRef, setFloating: setRef },
        floatingStyles: {},
        context: fakeContext,
      };
    },
    useHover: (_ctx: unknown, opts: Record<string, unknown>) => {
      capturedHoverArgs = opts ?? {};
      return {};
    },
    useDismiss: () => ({}),
    useRole: () => ({}),
    useInteractions: () => ({
      getReferenceProps: () => ({}),
      getFloatingProps: () => ({}),
    }),
    offset: () => null,
    flip: () => null,
    shift: () => null,
    autoUpdate: () => () => {},
    FloatingPortal: ({ children }: { children: ReactNode }) => children,
  };
});

// Mock framer-motion to render children immediately (no animation)
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
// Generators
// ---------------------------------------------------------------------------

/** Non-empty printable string for text props */
const arbText = fc
  .string({ minLength: 1, maxLength: 60 })
  .map((s) => s.replace(/[<>&\n\r\t]/g, "a"))
  .filter((s) => s.trim().length > 0);

/** URL-like string for wikiUrl prop */
const arbUrl = fc.webUrl().filter((u) => u.length > 0);

/** Delay integer in valid range */
const arbDelay = fc.integer({ min: 100, max: 5000 });

/** All 12 Placement values supported by @floating-ui/react */
const ALL_PLACEMENTS = [
  "top",
  "top-start",
  "top-end",
  "bottom",
  "bottom-start",
  "bottom-end",
  "left",
  "left-start",
  "left-end",
  "right",
  "right-start",
  "right-end",
] as const;

const arbPlacement = fc.constantFrom(...ALL_PLACEMENTS);

// ---------------------------------------------------------------------------
// Helper: render WikiTooltip and flush microtask to force open state
// ---------------------------------------------------------------------------
async function renderOpen(
  props: {
    title: string;
    description: string;
    wikiUrl?: string;
    placement?: (typeof ALL_PLACEMENTS)[number];
    delay?: number;
  },
  childText = "trigger-child"
) {
  let result: ReturnType<typeof render>;
  await act(async () => {
    result = render(
      <WikiTooltip {...props}>
        <button>{childText}</button>
      </WikiTooltip>
    );
    // Flush the queueMicrotask that calls onOpenChange(true)
    await new Promise((r) => setTimeout(r, 0));
  });
  return result!;
}

// ---------------------------------------------------------------------------
// Setup / Teardown
// ---------------------------------------------------------------------------
beforeEach(() => {
  capturedFloatingArgs = {};
  capturedHoverArgs = {};
});

afterEach(() => {
  cleanup();
});

// ---------------------------------------------------------------------------
// Property 1: Content Rendering Completeness
// ---------------------------------------------------------------------------
describe("Feature: wiki-tooltip, Property 1: Content rendering completeness", () => {
  /**
   * **Validates: Requirements 3.1, 3.2, 5.1**
   *
   * For any valid title and description strings, when WikiTooltip is visible,
   * both title and description SHALL appear in the DOM, and children SHALL
   * appear in the trigger wrapper.
   */
  it("renders title, description, and children for any valid input", async () => {
    await fc.assert(
      fc.asyncProperty(arbText, arbText, async (title, description) => {
        cleanup();
        capturedFloatingArgs = {};

        const { unmount, container } = await renderOpen({
          title,
          description,
        });

        // Tooltip bubble should be rendered
        const bubble = container.querySelector('[data-testid="tooltip-bubble"]');
        expect(bubble).not.toBeNull();

        // Title: first child div inside bubble
        const titleEl = bubble!.querySelector(
          ".text-sm.font-semibold"
        );
        expect(titleEl).not.toBeNull();
        expect(titleEl!.textContent).toBe(title);

        // Description: second child div inside bubble
        const descEl = bubble!.querySelector(
          ".text-xs.text-gray-300"
        );
        expect(descEl).not.toBeNull();
        expect(descEl!.textContent).toBe(description);

        // Children must be rendered as trigger
        const triggerBtn = container.querySelector("button");
        expect(triggerBtn).not.toBeNull();
        expect(triggerBtn!.textContent).toBe("trigger-child");

        unmount();
      }),
      { numRuns: 100 }
    );
  }, 30000);
});

// ---------------------------------------------------------------------------
// Property 2: Wiki Link Correctness
// ---------------------------------------------------------------------------
describe("Feature: wiki-tooltip, Property 2: Wiki link correctness", () => {
  /**
   * **Validates: Requirements 3.3, 3.4**
   *
   * For any non-empty wikiUrl, when WikiTooltip is visible, the Tooltip_Bubble
   * SHALL contain an <a> element whose href equals the wikiUrl and target is "_blank".
   */
  it("renders correct wiki link href and target for any URL", async () => {
    await fc.assert(
      fc.asyncProperty(arbUrl, async (url) => {
        cleanup();
        capturedFloatingArgs = {};

        const { unmount, container } = await renderOpen({
          title: "Title",
          description: "Desc",
          wikiUrl: url,
        });

        const bubble = container.querySelector('[data-testid="tooltip-bubble"]');
        expect(bubble).not.toBeNull();

        const link = bubble!.querySelector("a");
        expect(link).not.toBeNull();
        expect(link!.getAttribute("href")).toBe(url);
        expect(link!.getAttribute("target")).toBe("_blank");

        unmount();
      }),
      { numRuns: 100 }
    );
  }, 30000);
});

// ---------------------------------------------------------------------------
// Property 3: Custom Delay Forwarding
// ---------------------------------------------------------------------------
describe("Feature: wiki-tooltip, Property 3: Custom delay forwarding", () => {
  /**
   * **Validates: Requirements 1.5**
   *
   * For any positive integer delay (100-5000), WikiTooltip SHALL pass that
   * value as the hover open delay to useHover.
   */
  it("forwards custom delay to useHover for any value in [100, 5000]", () => {
    fc.assert(
      fc.property(arbDelay, (delay) => {
        cleanup();
        capturedHoverArgs = {};

        const { unmount } = render(
          <WikiTooltip title="T" description="D" delay={delay}>
            <span>trigger</span>
          </WikiTooltip>
        );

        const hoverDelay = capturedHoverArgs.delay as
          | { open: number; close: number }
          | undefined;
        expect(hoverDelay).toBeDefined();
        expect(hoverDelay!.open).toBe(delay);

        unmount();
      }),
      { numRuns: 100 }
    );
  });
});

// ---------------------------------------------------------------------------
// Property 4: Placement Forwarding
// ---------------------------------------------------------------------------
describe("Feature: wiki-tooltip, Property 4: Placement forwarding", () => {
  /**
   * **Validates: Requirements 2.5**
   *
   * For any valid Placement value (12 directions), WikiTooltip SHALL pass
   * that value as the preferred positioning direction to useFloating.
   */
  it("forwards placement to useFloating for any of the 12 directions", () => {
    fc.assert(
      fc.property(arbPlacement, (placement) => {
        cleanup();
        capturedFloatingArgs = {};

        const { unmount } = render(
          <WikiTooltip title="T" description="D" placement={placement}>
            <span>trigger</span>
          </WikiTooltip>
        );

        expect(capturedFloatingArgs.placement).toBe(placement);

        unmount();
      }),
      { numRuns: 100 }
    );
  });
});
