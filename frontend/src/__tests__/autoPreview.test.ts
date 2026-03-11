import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useConverterStore } from "../stores/converterStore";
import { useAutoPreview } from "../hooks/useAutoPreview";

// Helper: create a fake File object
function fakeFile(name = "test.png"): File {
  return new File(["pixels"], name, { type: "image/png" });
}

describe("useAutoPreview", () => {
  const mockSubmitPreview = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();

    // Reset store to a clean baseline with mocked submitPreview
    useConverterStore.setState({
      imageFile: null,
      lut_name: "",
      cropModalOpen: false,
      submitPreview: mockSubmitPreview,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // --- Req 1.1, 2.1: imageFile + lut_name ready → trigger after 300ms ---
  it("triggers submitPreview 300ms after imageFile and lut_name are both set", () => {
    const { unmount } = renderHook(() => useAutoPreview());

    act(() => {
      useConverterStore.setState({
        imageFile: fakeFile(),
        lut_name: "my-lut",
      });
    });

    // Not yet — still within debounce window
    expect(mockSubmitPreview).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(mockSubmitPreview).toHaveBeenCalledTimes(1);
    unmount();
  });

  // --- Req 1.3: missing lut_name → no trigger ---
  it("does NOT trigger submitPreview when lut_name is empty", () => {
    const { unmount } = renderHook(() => useAutoPreview());

    act(() => {
      useConverterStore.setState({
        imageFile: fakeFile(),
        lut_name: "",
      });
    });

    act(() => {
      vi.advanceTimersByTime(500);
    });

    expect(mockSubmitPreview).not.toHaveBeenCalled();
    unmount();
  });

  // --- Req 1.2: cropModalOpen blocks trigger; closing resumes ---
  it("does NOT trigger while cropModalOpen is true, triggers after it closes", () => {
    const { unmount } = renderHook(() => useAutoPreview());

    const file = fakeFile();

    // Set all conditions but cropModalOpen = true
    act(() => {
      useConverterStore.setState({
        imageFile: file,
        lut_name: "my-lut",
        cropModalOpen: true,
      });
    });

    act(() => {
      vi.advanceTimersByTime(500);
    });

    expect(mockSubmitPreview).not.toHaveBeenCalled();

    // Close crop modal
    act(() => {
      useConverterStore.setState({ cropModalOpen: false });
    });

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(mockSubmitPreview).toHaveBeenCalledTimes(1);
    unmount();
  });

  // --- Req 2.2: rapid lut_name switches → debounce fires only last ---
  it("debounces rapid lut_name changes and only triggers for the last one", () => {
    const { unmount } = renderHook(() => useAutoPreview());

    const file = fakeFile();
    act(() => {
      useConverterStore.setState({ imageFile: file });
    });

    // Rapid LUT switches
    act(() => {
      useConverterStore.setState({ lut_name: "lut-A" });
    });
    act(() => {
      vi.advanceTimersByTime(100);
    });

    act(() => {
      useConverterStore.setState({ lut_name: "lut-B" });
    });
    act(() => {
      vi.advanceTimersByTime(100);
    });

    act(() => {
      useConverterStore.setState({ lut_name: "lut-C" });
    });

    // No call yet
    expect(mockSubmitPreview).not.toHaveBeenCalled();

    // Wait full debounce from last change
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(mockSubmitPreview).toHaveBeenCalledTimes(1);
    unmount();
  });

  // --- Req 1.4: uploading a new image re-triggers ---
  it("re-triggers submitPreview when a new imageFile is uploaded", () => {
    const { unmount } = renderHook(() => useAutoPreview());

    const file1 = fakeFile("img1.png");
    const file2 = fakeFile("img2.png");

    // First image + LUT
    act(() => {
      useConverterStore.setState({ imageFile: file1, lut_name: "my-lut" });
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(mockSubmitPreview).toHaveBeenCalledTimes(1);

    // Upload new image
    act(() => {
      useConverterStore.setState({ imageFile: file2 });
    });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(mockSubmitPreview).toHaveBeenCalledTimes(2);
    unmount();
  });
});
