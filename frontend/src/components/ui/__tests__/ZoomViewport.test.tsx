import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import ZoomViewport from "../ZoomViewport"

const mouseHandlers = {
  onMouseDown: vi.fn(),
  onMouseMove: vi.fn(),
  onMouseUp: vi.fn(),
  onMouseLeave: vi.fn(),
}

describe("ZoomViewport", () => {
  it("clips the comparison image to the right of the divider with the same transform", () => {
    render(
      <ZoomViewport
        src="/original.png"
        alt="Original"
        comparisonSrc="/vectorized.svg"
        comparisonAlt="SVG"
        comparisonSplit={0.25}
        scale={2}
        translate={{ x: 12, y: -4 }}
        zoom={vi.fn()}
        mouseHandlers={mouseHandlers}
      />,
    )

    const original = screen.getByAltText("Original")
    const comparison = screen.getByAltText("SVG")
    expect(original).toHaveStyle({ transform: "translate(12px, -4px) scale(2)" })
    expect(comparison).toHaveStyle({ transform: "translate(12px, -4px) scale(2)" })
    expect(screen.getByTestId("zoom-viewport-comparison")).toHaveStyle({
      clipPath: "inset(0 0 0 25%)",
    })
  })

  it("hides the comparison layer until both a source and a split are provided", () => {
    const { rerender } = render(
      <ZoomViewport
        src="/original.png"
        alt="Original"
        comparisonSrc="/vectorized.svg"
        scale={1}
        translate={{ x: 0, y: 0 }}
        zoom={vi.fn()}
        mouseHandlers={mouseHandlers}
      />,
    )
    expect(screen.queryByTestId("zoom-viewport-comparison")).not.toBeInTheDocument()

    rerender(
      <ZoomViewport
        src="/original.png"
        alt="Original"
        comparisonSplit={null}
        scale={1}
        translate={{ x: 0, y: 0 }}
        zoom={vi.fn()}
        mouseHandlers={mouseHandlers}
      />,
    )
    expect(screen.queryByTestId("zoom-viewport-comparison")).not.toBeInTheDocument()

    rerender(
      <ZoomViewport
        src="/original.png"
        alt="Original"
        comparisonSrc="/vectorized.svg"
        comparisonAlt="SVG"
        comparisonSplit={1}
        scale={1}
        translate={{ x: 0, y: 0 }}
        zoom={vi.fn()}
        mouseHandlers={mouseHandlers}
      />,
    )
    expect(screen.getByTestId("zoom-viewport-comparison")).toHaveStyle({
      clipPath: "inset(0 0 0 100%)",
    })
  })
})
