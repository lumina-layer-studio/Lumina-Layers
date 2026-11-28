import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import VectorizerPanel from "../components/VectorizerPanel"
import { useVectorizerStore } from "../stores/vectorizerStore"

vi.mock("../i18n/context", () => ({
  useI18n: () => ({ t: (key: string) => key, lang: "zh" as const }),
}))

const RESULT = {
  status: "ok",
  message: "",
  svg_url: "/files/vectorized.svg",
  width: 100,
  height: 80,
  num_shapes: 12,
  num_colors: 4,
  palette: ["#111111", "#222222"],
}

function renderWithResult(): HTMLElement {
  useVectorizerStore.setState({
    imagePreviewUrl: "/files/source.png",
    result: RESULT,
    isProcessing: false,
    error: null,
  })
  render(<VectorizerPanel />)
  return screen.getByTestId("vectorizer-compare-divider")
}

describe("VectorizerPanel comparison slider", () => {
  beforeEach(() => {
    useVectorizerStore.getState().reset()
  })

  it("wipes between the original and the vectorized SVG", () => {
    const divider = renderWithResult()

    expect(screen.getByAltText("vec.original")).toHaveAttribute("src", "/files/source.png")
    expect(screen.getByAltText("vec.svg_preview")).toHaveAttribute("src", "/files/vectorized.svg")
    expect(divider).toHaveStyle({ left: "50%" })
    // The overlay palette comes from tokens, not raw colours.
    expect(divider).toHaveClass("image-compare-divider")
    expect(divider.firstElementChild).toHaveClass("image-compare-divider-line")
    expect(screen.getByTestId("zoom-viewport-comparison")).toHaveStyle({
      clipPath: "inset(0 0 0 50%)",
    })
  })

  it("moves the split when the divider is dragged", () => {
    const divider = renderWithResult()
    const wrapper = divider.parentElement as HTMLElement
    vi.spyOn(wrapper, "getBoundingClientRect").mockReturnValue({
      left: 0, top: 0, width: 400, height: 300,
      right: 400, bottom: 300, x: 0, y: 0, toJSON: () => ({}),
    } as DOMRect)

    fireEvent.pointerDown(divider, { button: 0, pointerId: 3, clientX: 200 })
    expect(divider).toHaveStyle({ left: "50%" })
    fireEvent.pointerMove(divider, { pointerId: 3, clientX: 100 })
    expect(divider).toHaveStyle({ left: "25%" })
    expect(screen.getByTestId("zoom-viewport-comparison")).toHaveStyle({
      clipPath: "inset(0 0 0 25%)",
    })
    fireEvent.pointerMove(divider, { pointerId: 3, clientX: 900 })
    expect(divider).toHaveStyle({ left: "100%" })
    fireEvent.pointerUp(divider, { pointerId: 3, clientX: 900 })
  })

  it("nudges the split with the keyboard", () => {
    const divider = renderWithResult()

    fireEvent.keyDown(divider, { key: "ArrowLeft" })
    expect(divider).toHaveStyle({ left: "48%" })
    fireEvent.keyDown(divider, { key: "ArrowRight", shiftKey: true })
    expect(divider).toHaveStyle({ left: "58%" })
    fireEvent.keyDown(divider, { key: "Home" })
    expect(divider).toHaveStyle({ left: "0%" })
    fireEvent.keyDown(divider, { key: "End" })
    expect(divider).toHaveStyle({ left: "100%" })
  })
})
