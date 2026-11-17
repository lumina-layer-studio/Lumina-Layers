import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { CropModal } from "../CropModal";

const cropper = vi.hoisted(() => ({
  getImageData: vi.fn(() => ({ naturalWidth: 120, naturalHeight: 80 })),
  getData: vi.fn(() => ({ x: 10, y: 20, width: 120, height: 80 })),
  rotateTo: vi.fn(),
  clear: vi.fn(),
  crop: vi.fn(),
  getCanvasData: vi.fn(() => ({ width: 120, naturalWidth: 120, naturalHeight: 80 })),
  getContainerData: vi.fn(() => ({ width: 600, height: 400 })),
  zoomTo: vi.fn(),
  setCanvasData: vi.fn(),
  setData: vi.fn(),
  setAspectRatio: vi.fn(),
}));
const lifecycle = vi.hoisted(() => ({
  autoReady: true,
  ready: undefined as (() => void) | undefined,
}));

vi.mock("react-cropper", async () => {
  const { forwardRef, useEffect, useImperativeHandle } = await import("react");
  return { default: forwardRef(function MockCropper({ ready }: { ready: () => void }, ref) {
    useImperativeHandle(ref, () => ({ cropper }));
    useEffect(() => {
      lifecycle.ready = ready;
      if (lifecycle.autoReady) ready();
    }, [ready]);
    return <div data-testid="cropper-surface" />;
  }) };
});

describe("CropModal rotation drafts", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    lifecycle.autoReady = true;
    lifecycle.ready = undefined;
  });

  it("waits for image readiness before allowing rotation, crop edits and confirmation", () => {
    lifecycle.autoReady = false;
    const onConfirm = vi.fn();
    render(<CropModal open imageSrc="blob:loading" onConfirm={onConfirm} onClose={vi.fn()} onUseOriginal={vi.fn()} />);
    const rotate = screen.getByRole("button", { name: "向右旋转 90°" });
    expect(rotate).toBeDisabled();
    expect(screen.getByRole("button", { name: "应用更改" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "1:1" })).toBeDisabled();
    for (const input of screen.getAllByRole("spinbutton")) expect(input).toBeDisabled();
    fireEvent.click(rotate);
    fireEvent.wheel(screen.getByTestId("cropper-surface"), { deltaY: -100 });
    expect(cropper.rotateTo).not.toHaveBeenCalled();
    expect(cropper.zoomTo).not.toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "取消" })).toBeEnabled();
    act(() => lifecycle.ready?.());
    expect(rotate).toBeEnabled();
    fireEvent.click(rotate);
    expect(cropper.rotateTo).toHaveBeenLastCalledWith(90);
  });

  it("waits for the replacement image and ignores readiness from the previous image", () => {
    const props = { onConfirm: vi.fn(), onClose: vi.fn(), onUseOriginal: vi.fn() };
    const view = render(<CropModal {...props} open imageSrc="blob:first" />);
    const firstReady = lifecycle.ready;
    expect(screen.getByRole("button", { name: "向右旋转 90°" })).toBeEnabled();
    lifecycle.autoReady = false;
    view.rerender(<CropModal {...props} open imageSrc="blob:second" />);
    expect(screen.getByRole("button", { name: "向右旋转 90°" })).toBeDisabled();
    act(() => firstReady?.());
    expect(screen.getByRole("button", { name: "向右旋转 90°" })).toBeDisabled();
    act(() => lifecycle.ready?.());
    expect(screen.getByRole("button", { name: "向右旋转 90°" })).toBeEnabled();
    view.rerender(<CropModal {...props} open={false} imageSrc="blob:second" />);
    view.rerender(<CropModal {...props} open imageSrc="blob:second" />);
    expect(screen.getByRole("button", { name: "向右旋转 90°" })).toBeDisabled();
  });

  it("zooms smoothly around the pointer and prevents page scrolling", () => {
    render(<CropModal open imageSrc="blob:test" onConfirm={vi.fn()} onClose={vi.fn()} onUseOriginal={vi.fn()} />);
    const surface = screen.getByTestId("cropper-surface");
    const event = new WheelEvent("wheel", { deltaY: -1, clientX: 80, clientY: 40, bubbles: true, cancelable: true });
    surface.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    expect(cropper.zoomTo).toHaveBeenLastCalledWith(Math.pow(1.1, 0.01), { x: 80, y: 40 });
    fireEvent.wheel(surface, { deltaY: -10000, clientX: 80, clientY: 40 });
    expect(cropper.zoomTo).toHaveBeenLastCalledWith(1.1, { x: 80, y: 40 });
    cropper.zoomTo.mockClear();
    fireEvent.wheel(surface, { deltaY: 0, deltaX: 10 });
    expect(cropper.zoomTo).not.toHaveBeenCalled();
  });

  it("combines quarter turns with the current crop only when confirmed", () => {
    const onConfirm = vi.fn();
    render(<CropModal open imageSrc="blob:test" onConfirm={onConfirm} onClose={vi.fn()} onUseOriginal={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "向左旋转 90°" }));
    expect(cropper.rotateTo).toHaveBeenLastCalledWith(270);
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "应用更改" }));
    expect(onConfirm).toHaveBeenCalledWith({ x: 10, y: 20, width: 120, height: 80, rotation: 270 });
  });

  it("discards rotation on cancel and starts the next edit unrotated", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    const props = { imageSrc: "blob:test", onConfirm, onClose: onCancel, onUseOriginal: onCancel };
    const view = render(<CropModal {...props} open />);
    fireEvent.click(screen.getByRole("button", { name: "向右旋转 90°" }));
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(onCancel).toHaveBeenCalledOnce();
    expect(onConfirm).not.toHaveBeenCalled();
    view.rerender(<CropModal {...props} open={false} />);
    view.rerender(<CropModal {...props} open />);
    fireEvent.click(screen.getByRole("button", { name: "应用更改" }));
    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({ rotation: 0 }));
  });

  it("wraps four right turns back to the original orientation", () => {
    const onConfirm = vi.fn();
    render(<CropModal open imageSrc="blob:test" onConfirm={onConfirm} onClose={vi.fn()} onUseOriginal={vi.fn()} />);
    for (let i = 0; i < 4; i++) fireEvent.click(screen.getByRole("button", { name: "向右旋转 90°" }));
    expect(cropper.rotateTo).toHaveBeenLastCalledWith(0);
    fireEvent.click(screen.getByRole("button", { name: "应用更改" }));
    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({ rotation: 0 }));
  });
});
