import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useImageThumbnail } from "../useImageThumbnail";

class FakeImage {
  static instances: FakeImage[] = [];
  onload: (() => void) | null = null;
  src = "";
  naturalWidth = 0;
  naturalHeight = 0;

  constructor() {
    FakeImage.instances.push(this);
  }

  finishLoading(width: number, height: number) {
    this.naturalWidth = width;
    this.naturalHeight = height;
    this.onload?.();
  }
}

describe("useImageThumbnail", () => {
  const drawImage = vi.fn();
  const createObjectURL = vi.fn();
  const revokeObjectURL = vi.fn();
  let getContext: ReturnType<typeof vi.spyOn>;
  let pendingBlobCallbacks: BlobCallback[];
  let canvases: HTMLCanvasElement[];

  const lastImage = () => FakeImage.instances[FakeImage.instances.length - 1];
  const finishEncoding = () => {
    act(() => {
      pendingBlobCallbacks.shift()?.(new Blob(["thumbnail"], { type: "image/png" }));
    });
  };

  beforeEach(() => {
    FakeImage.instances = [];
    pendingBlobCallbacks = [];
    canvases = [];
    drawImage.mockReset();
    createObjectURL.mockReset();
    revokeObjectURL.mockReset();
    let nextUrl = 0;
    createObjectURL.mockImplementation(() => `blob:thumbnail-${++nextUrl}`);

    vi.stubGlobal("Image", FakeImage);
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL }));
    getContext = vi
      .spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockImplementation(function getFakeContext(this: HTMLCanvasElement) {
        canvases.push(this);
        return { drawImage, imageSmoothingQuality: "low" } as unknown as CanvasRenderingContext2D;
      } as unknown as typeof HTMLCanvasElement.prototype.getContext);
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((callback) => {
      pendingBlobCallbacks.push(callback);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("shows the source until a thumbnail bounded to the long edge is ready", () => {
    const { result } = renderHook(() => useImageThumbnail("blob:source"));
    expect(result.current).toBe("blob:source");
    expect(lastImage().src).toBe("blob:source");

    act(() => lastImage().finishLoading(6000, 4000));
    expect(result.current).toBe("blob:source");
    expect(canvases[0].width).toBe(768);
    expect(canvases[0].height).toBe(512);
    expect(drawImage).toHaveBeenCalledWith(lastImage(), 0, 0, 768, 512);

    finishEncoding();
    expect(result.current).toBe("blob:thumbnail-1");
  });

  it("bounds portrait images by their height", () => {
    renderHook(() => useImageThumbnail("blob:portrait"));
    act(() => lastImage().finishLoading(2150, 3024));
    expect(canvases[0].width).toBe(546);
    expect(canvases[0].height).toBe(768);
  });

  it("keeps the source for images that are already small", () => {
    const { result } = renderHook(() => useImageThumbnail("blob:small"));
    act(() => lastImage().finishLoading(768, 400));
    expect(getContext).not.toHaveBeenCalled();
    expect(result.current).toBe("blob:small");
  });

  it("keeps the source when the image cannot be drawn", () => {
    drawImage.mockImplementation(() => {
      throw new DOMException("tainted", "SecurityError");
    });
    const { result } = renderHook(() => useImageThumbnail("blob:tainted"));
    act(() => lastImage().finishLoading(4000, 4000));
    expect(pendingBlobCallbacks).toHaveLength(0);
    expect(result.current).toBe("blob:tainted");
  });

  it("switches to a new source at once and revokes the old thumbnail", () => {
    const { result, rerender } = renderHook(
      ({ source }: { source: string | null }) => useImageThumbnail(source),
      { initialProps: { source: "blob:first" as string | null } },
    );
    act(() => lastImage().finishLoading(4000, 4000));
    finishEncoding();
    expect(result.current).toBe("blob:thumbnail-1");

    rerender({ source: "blob:second" });
    expect(result.current).toBe("blob:second");
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:thumbnail-1");

    rerender({ source: null });
    expect(result.current).toBeNull();
  });

  it("does not regenerate a stale thumbnail when returning to an earlier source", () => {
    const { result, rerender } = renderHook(
      ({ source }: { source: string }) => useImageThumbnail(source),
      { initialProps: { source: "/api/files/first" } },
    );
    act(() => lastImage().finishLoading(4000, 4000));
    finishEncoding();

    rerender({ source: "/api/files/second" });
    rerender({ source: "/api/files/first" });
    expect(result.current).toBe("/api/files/first");
  });

  it("drops an encode that finishes after the source changed", () => {
    const { result, rerender } = renderHook(
      ({ source }: { source: string }) => useImageThumbnail(source),
      { initialProps: { source: "blob:first" } },
    );
    act(() => lastImage().finishLoading(4000, 4000));

    rerender({ source: "blob:second" });
    finishEncoding();
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(result.current).toBe("blob:second");
  });

  it("revokes the thumbnail on unmount", () => {
    const { unmount } = renderHook(() => useImageThumbnail("blob:source"));
    act(() => lastImage().finishLoading(4000, 4000));
    finishEncoding();

    unmount();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:thumbnail-1");
  });
});
