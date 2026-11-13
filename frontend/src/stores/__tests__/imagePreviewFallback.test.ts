import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { converterDocumentHistory, DEFAULT_STATE, useConverterStore } from "../converter";
import { uploadImagePreview } from "../../api/system";

vi.mock("../../api/system", () => ({ uploadImagePreview: vi.fn() }));

const images: HTMLImageElement[] = [];
const tick = async () => { await Promise.resolve(); await Promise.resolve(); };

beforeEach(() => {
  vi.clearAllMocks();
  images.length = 0;
  vi.stubGlobal("Image", class {
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    src = "";
    constructor() { images.push(this as unknown as HTMLImageElement); }
  });
  let url = 0;
  vi.spyOn(URL, "createObjectURL").mockImplementation(() => `blob:input-${++url}`);
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  useConverterStore.setState({ ...DEFAULT_STATE, enableCrop: true });
  converterDocumentHistory.reset();
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("browser image decoding fallback", () => {
  it.each(["setImageFile", "handleFilesSelect", "removeBatchFile"] as const)(
    "%s prepares a PNG preview when the browser cannot decode the source",
    async (action) => {
      const file = new File(["HEIC bytes"], "misnamed.png", { type: "image/png" });
      vi.mocked(uploadImagePreview).mockResolvedValue({ preview_url: "/api/files/decoded", width: 600, height: 400 });
      if (action === "setImageFile") useConverterStore.getState().setImageFile(file);
      else if (action === "handleFilesSelect") useConverterStore.getState().handleFilesSelect([file]);
      else {
        useConverterStore.setState({ batchFiles: [new File([""], "remove.png"), file], batchMode: true });
        useConverterStore.getState().removeBatchFile(0);
      }
      const sourceUrl = useConverterStore.getState().imagePreviewUrl;
      images.at(-1)!.onerror?.(new Event("error"));
      await tick();
      expect(uploadImagePreview).toHaveBeenCalledExactlyOnceWith(file);
      expect(useConverterStore.getState().imageFile).toBe(file);
      expect(useConverterStore.getState().imagePreviewUrl).toBe("/api/files/decoded");
      expect(useConverterStore.getState().aspectRatio).toBe(1.5);
      expect(URL.revokeObjectURL).toHaveBeenCalledWith(sourceUrl);
    },
  );

  it("does not replace a newer image when an earlier conversion finishes", async () => {
    let resolve!: (result: Awaited<ReturnType<typeof uploadImagePreview>>) => void;
    vi.mocked(uploadImagePreview).mockReturnValue(new Promise(done => { resolve = done; }));
    useConverterStore.getState().setImageFile(new File(["HEIC"], "old.png", { type: "image/png" }));
    images.at(-1)!.onerror?.(new Event("error"));
    const newer = new File(["PNG"], "new.png", { type: "image/png" });
    useConverterStore.getState().setImageFile(newer);
    const newerUrl = useConverterStore.getState().imagePreviewUrl;
    resolve({ preview_url: "/api/files/old", width: 600, height: 400 });
    await tick();
    expect(useConverterStore.getState().imageFile).toBe(newer);
    expect(useConverterStore.getState().imagePreviewUrl).toBe(newerUrl);
  });

  it("closes the unusable cropper and reports decoding failure without losing the source", async () => {
    const file = new File(["broken"], "broken.png", { type: "image/png" });
    vi.mocked(uploadImagePreview).mockRejectedValue(new Error("无法解码图片"));
    useConverterStore.getState().setImageFile(file);
    images.at(-1)!.onerror?.(new Event("error"));
    await tick();
    expect(useConverterStore.getState().cropModalOpen).toBe(false);
    expect(useConverterStore.getState().error).toContain("无法解码图片");
    expect(useConverterStore.getState().imageFile).toBe(file);
    expect(useConverterStore.getState().imagePreviewUrl).toBeNull();
  });

  it("recovers the source preview again after undo restores a previously decoded image", async () => {
    const file = new File(["HEIC"], "original.png", { type: "image/png" });
    vi.mocked(uploadImagePreview).mockResolvedValue({ preview_url: "/api/files/decoded", width: 600, height: 400 });
    useConverterStore.getState().setImageFile(file);
    images.at(-1)!.onerror?.(new Event("error"));
    await tick();
    useConverterStore.getState().setImageFile(new File(["PNG"], "replacement.png", { type: "image/png" }));
    await converterDocumentHistory.undo();
    expect(useConverterStore.getState().imageFile).toBe(file);
    images.at(-1)!.onerror?.(new Event("error"));
    await tick();
    expect(useConverterStore.getState().imagePreviewUrl).toBe("/api/files/decoded");
    expect(useConverterStore.getState().aspectRatio).toBe(1.5);
  });
});
