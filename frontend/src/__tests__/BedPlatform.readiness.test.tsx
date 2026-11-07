import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as THREE from "three";
import BedPlatform from "../components/BedPlatform";
import { useConverterStore } from "../stores/converter";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";
import { captureProjectSettings } from "../stores/converter/project";

const bed = vi.hoisted(() => ({
  state: {} as Record<string, unknown>,
  textures: [] as Array<{ resolve: (texture: null) => void; cancel: ReturnType<typeof vi.fn> }>,
  loadGeometry: vi.fn(),
}));
vi.mock("@react-three/fiber", () => ({
  useThree: (select: (state: Record<string, unknown>) => unknown) => select(bed.state),
}));
vi.mock("../api/system", () => ({ getMachineBedModelUrl: () => "/bed.stl" }));
vi.mock("../integrations/electron", () => ({ electronAPI: undefined }));
vi.mock("../utils/slicerBranding", () => ({ getSlicerLogoSource: () => "/slicer.png" }));
vi.mock("../components/bedPlatformGeometry", async (original) => ({
  ...await original<typeof import("../components/bedPlatformGeometry")>(),
  loadNativeBedGeometrySource: (...args: unknown[]) => bed.loadGeometry(...args),
}));
vi.mock("../components/bedPlatformTexture", async (original) => ({
  ...await original<typeof import("../components/bedPlatformTexture")>(),
  createBedTextureRequest: () => {
    let resolve!: (texture: null) => void;
    const ready = new Promise<null>((done) => { resolve = done; });
    const cancel = vi.fn(() => resolve(null));
    bed.textures.push({ resolve, cancel });
    return { ready, cancel };
  },
}));

class BedImage extends EventTarget {
  static instances: BedImage[] = [];
  src = "";
  currentSrc = "data:image/png;base64,bed";
  naturalWidth = 16;
  naturalHeight = 16;
  constructor() {
    super();
    BedImage.instances.push(this);
  }
}

beforeEach(() => {
  useSettingsStore.setState({ ...DEFAULT_SETTINGS });
  useConverterStore.setState({
    projectSettings: null,
    bed_label: "A1",
    bedSizes: [{ label: "A1", width_mm: 256, height_mm: 256, is_default: true }],
    modelUrl: null,
    previewGlbUrl: null,
    batchPreviewItems: [],
  });
  BedImage.instances = [];
  bed.textures = [];
  vi.stubGlobal("Image", BedImage);
  bed.state = {
    camera: new THREE.PerspectiveCamera(),
    controls: { target: new THREE.Vector3(), update: vi.fn() },
    invalidate: vi.fn(),
  };
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function finishTexture(): Promise<void> {
  await act(async () => { bed.textures.at(-1)!.resolve(null); });
}

describe("bed first-frame readiness", () => {
  it("loads the project's native plate even when the daily printer profile differs", async () => {
    useSettingsStore.setState({ deviceProfileId: "daily-profile", buildPlateId: "engineering-plate" });
    useConverterStore.setState({ projectSettings: {
      ...captureProjectSettings(useSettingsStore.getState()), deviceProfileId: "project-profile", buildPlateId: "textured-pei-plate",
    } });
    bed.loadGeometry.mockResolvedValue(null);
    const { unmount } = render(<BedPlatform />);
    await act(async () => {});
    expect(bed.loadGeometry).toHaveBeenLastCalledWith(expect.objectContaining({ deviceProfileId: "project-profile" }));
    expect(useSettingsStore.getState().deviceProfileId).toBe("daily-profile");
    unmount();
  });

  it("preserves the restored camera and texture when the same bed catalog is fetched again", async () => {
    bed.loadGeometry.mockResolvedValue(null);
    const onReadyChange = vi.fn();
    const { unmount } = render(<BedPlatform onReadyChange={onReadyChange} />);
    await act(async () => {
      for (const image of BedImage.instances) image.dispatchEvent(new Event("load"));
    });
    await finishTexture();
    const camera = bed.state.camera as THREE.PerspectiveCamera;
    camera.position.set(12, 34, 56);
    const textureRequests = bed.textures.length;
    act(() => {
      useConverterStore.setState({
        bedSizes: useConverterStore.getState().bedSizes.map((item) => ({ ...item })),
      });
    });
    expect(camera.position.toArray()).toEqual([12, 34, 56]);
    expect(bed.textures).toHaveLength(textureRequests);
    expect(onReadyChange).toHaveBeenLastCalledWith(true);
    unmount();
  });

  it("waits for native geometry, branding and the final texture, then requests a demand frame", async () => {
    let resolveGeometry!: (geometry: THREE.BufferGeometry | null) => void;
    bed.loadGeometry.mockImplementation(() => new Promise((resolve) => { resolveGeometry = resolve; }));
    const onReadyChange = vi.fn();
    const { unmount } = render(<BedPlatform onReadyChange={onReadyChange} />);
    await finishTexture();
    expect(onReadyChange).toHaveBeenLastCalledWith(false);
    await act(async () => {
      for (const image of BedImage.instances) image.dispatchEvent(new Event("load"));
    });
    await finishTexture();
    expect(onReadyChange).toHaveBeenLastCalledWith(false);
    await act(async () => { resolveGeometry(new THREE.BoxGeometry(256, 256, 3)); });
    expect(onReadyChange).toHaveBeenLastCalledWith(false);
    await finishTexture();
    expect(onReadyChange).toHaveBeenLastCalledWith(true);
    expect(bed.state.invalidate).toHaveBeenCalled();
    unmount();
  });

  it("releases the handoff with the existing fallback when native geometry or images fail", async () => {
    bed.loadGeometry.mockRejectedValue(new Error("missing native plate"));
    const onReadyChange = vi.fn();
    const { unmount } = render(<BedPlatform onReadyChange={onReadyChange} />);
    await act(async () => {
      for (const image of BedImage.instances) image.dispatchEvent(new Event("error"));
    });
    await finishTexture();
    expect(onReadyChange).toHaveBeenLastCalledWith(true);
    unmount();
  });

  it("cancels pending textures on departure without reporting a late ready frame", async () => {
    bed.loadGeometry.mockResolvedValue(null);
    const onReadyChange = vi.fn();
    const { unmount } = render(<BedPlatform onReadyChange={onReadyChange} />);
    const pending = bed.textures.at(-1)!;
    unmount();
    await act(async () => { pending.resolve(null); });
    expect(pending.cancel).toHaveBeenCalledOnce();
    expect(onReadyChange).not.toHaveBeenCalledWith(true);
  });
});
