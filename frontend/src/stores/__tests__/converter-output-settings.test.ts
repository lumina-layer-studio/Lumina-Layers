import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StructureMode } from "../../api/types";
import { uploadImagePreview } from "../../api/system";
import { fetchBedSizes } from "../../api/converter";
import { captureProjectSettings } from "../converter/project";

vi.mock("../../api/system", () => ({ uploadImagePreview: vi.fn() }));
vi.mock("../../api/converter", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../api/converter")>(),
  fetchBedSizes: vi.fn(),
}));

const beds = [
  { label: "Small", printer_id: "small", width_mm: 180, height_mm: 200, is_default: false },
  { label: "Large", printer_id: "large", width_mm: 500, height_mm: 300, is_default: false },
];

class TestImage {
  naturalWidth = 200;
  naturalHeight = 400;
  src = "";
  onload: (() => void) | null = null;
  constructor() { images.push(this); }
}
let images: TestImage[] = [];

async function startConverter() {
  vi.resetModules();
  const { useConverterStore: store } = await import("../converter");
  const { useSettingsStore: settings } = await import("../settingsStore");
  return { store, settings };
}

beforeEach(() => {
  localStorage.clear();
  images = [];
  vi.stubGlobal("Image", TestImage);
  vi.spyOn(URL, "createObjectURL").mockImplementation(() => `blob:image-${images.length}`);
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  vi.mocked(uploadImagePreview).mockReset();
  vi.mocked(fetchBedSizes).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("printer-dependent output dimensions", () => {
  it("restores the project printer's bed instead of the default bed label", async () => {
    const { store, settings } = await startConverter();
    settings.getState().setPrinterModel("large");
    store.setState({ bedSizes: beds });
    const projectSettings = { ...captureProjectSettings(settings.getState()), printerModel: "small" };
    store.getState().commitProjectRestore({
      ...store.getState(), projectSettings, bedSizes: beds, bed_label: "256×256 mm",
      target_width_mm: 120, target_height_mm: 160,
    });
    expect(store.getState()).toMatchObject({ bed_label: "Small", target_width_mm: 120, target_height_mm: 160 });
    expect(settings.getState().printerModel).toBe("large");
  });

  it("uses the project printer when its bed catalog arrives after restoration", async () => {
    const { store, settings } = await startConverter();
    settings.getState().setPrinterModel("large");
    store.setState({ projectSettings: { ...captureProjectSettings(settings.getState()), printerModel: "small" }, bedSizes: [] });
    vi.mocked(fetchBedSizes).mockResolvedValue({ beds });
    await store.getState().fetchBedSizes();
    expect(store.getState().bed_label).toBe("Small");
    expect(settings.getState().printerModel).toBe("large");
  });

  it("keeps a project's bed independent of daily settings until its device settings change", async () => {
    const { store, settings } = await startConverter();
    settings.getState().setPrinterModel("large");
    const projectSettings = { ...captureProjectSettings(settings.getState()), printerModel: "small" };
    store.setState({ bedSizes: beds, bed_label: "Small", projectSettings });
    settings.getState().setPrinterModel("large");
    expect(store.getState().bed_label).toBe("Small");
    store.setState({ projectSettings: captureProjectSettings(settings.getState()) });
    expect(store.getState().bed_label).toBe("Large");
    settings.getState().setPrinterModel("small");
    expect(store.getState().bed_label).toBe("Large");
    store.setState({ projectSettings: null });
    expect(store.getState().bed_label).toBe("Small");
  });

  it("uses both bed axes and allows printers larger than 400 mm", async () => {
    const { store, settings } = await startConverter();
    store.setState({ bedSizes: beds });
    settings.getState().setPrinterModel("small");
    store.getState().setTargetWidthMm(999);
    store.getState().setTargetHeightMm(999);
    expect(store.getState()).toMatchObject({ target_width_mm: 180, target_height_mm: 200 });

    settings.getState().setPrinterModel("large");
    store.getState().setTargetWidthMm(999);
    store.getState().setTargetHeightMm(999);
    expect(store.getState()).toMatchObject({ target_width_mm: 500, target_height_mm: 300 });
  });

  it.each([
    [2, 500, 250],
    [0.5, 150, 300],
  ])("keeps ratio %s inside a rectangular bed", async (ratio, width, height) => {
    const { store, settings } = await startConverter();
    store.setState({ bedSizes: beds, aspectRatio: ratio });
    settings.getState().setPrinterModel("large");
    store.getState().setTargetWidthMm(999);
    expect(store.getState()).toMatchObject({ target_width_mm: width, target_height_mm: height });
    store.getState().setTargetHeightMm(999);
    expect(store.getState()).toMatchObject({ target_width_mm: width, target_height_mm: height });
  });

  it("shrinks proportionally when switching to a smaller printer", async () => {
    const { store, settings } = await startConverter();
    store.setState({ bedSizes: beds, aspectRatio: 2, target_width_mm: 480, target_height_mm: 240 });
    settings.getState().setPrinterModel("small");
    expect(store.getState()).toMatchObject({ target_width_mm: 180, target_height_mm: 90 });
  });

  it("still reapplies ordinary printer bounds when selecting the current printer again", async () => {
    const { store, settings } = await startConverter();
    store.setState({ bedSizes: beds });
    settings.getState().setPrinterModel("small");
    store.setState({ target_width_mm: 360, target_height_mm: 200, aspectRatio: 1.8 });
    settings.getState().setPrinterModel("small");
    expect(store.getState()).toMatchObject({ target_width_mm: 180, target_height_mm: 100 });
  });

  it("keeps extremely narrow artwork within the existing minimum and bed maximum", async () => {
    const { store, settings } = await startConverter();
    store.setState({ bedSizes: beds, aspectRatio: 1000 });
    settings.getState().setPrinterModel("small");
    store.getState().setTargetWidthMm(999);
    expect(store.getState()).toMatchObject({ target_width_mm: 180, target_height_mm: 10 });
    store.getState().setTargetHeightMm(999);
    expect(store.getState()).toMatchObject({ target_width_mm: 180, target_height_mm: 10 });
  });

  it("fits remembered dimensions when the printer catalog finishes loading", async () => {
    localStorage.setItem("lumina_outputDimensions", JSON.stringify({ target_width_mm: 360, target_height_mm: 240 }));
    const { store, settings } = await startConverter();
    settings.getState().setPrinterModel("small");
    vi.mocked(fetchBedSizes).mockResolvedValue({ beds });
    await store.getState().fetchBedSizes();
    expect(store.getState()).toMatchObject({ bed_label: "Small", target_width_mm: 180, target_height_mm: 200 });
  });

  it("keeps large-format dimensions until returning to a single bed", async () => {
    const { store, settings } = await startConverter();
    store.setState({ bedSizes: beds, aspectRatio: 2 });
    settings.getState().setPrinterModel("small");
    store.getState().setLargeFormatEnabled(true);
    store.getState().setTargetWidthMm(1000);
    expect(store.getState()).toMatchObject({ target_width_mm: 1000, target_height_mm: 500 });
    store.getState().setLargeFormatEnabled(false);
    expect(store.getState()).toMatchObject({ target_width_mm: 180, target_height_mm: 90 });
  });

  it("clears previous missing tiles when changing the tiling configuration", async () => {
    const { store } = await startConverter();
    const changes = [
      () => store.getState().setLargeFormatEnabled(false),
      () => store.getState().setTileWidthMm(100),
      () => store.getState().setTileHeightMm(120),
      () => store.getState().setPuzzleEnabled(true),
    ];
    for (const change of changes) {
      store.setState({ largeFormatFailedTiles: ["R1C2"], largeFormatWarnings: ["old result"] });
      change();
      expect(store.getState().largeFormatFailedTiles).toEqual([]);
      expect(store.getState().largeFormatWarnings).toEqual([]);
    }
  });
});

describe("remembered output settings", () => {
  it("restores dimensions, thickness, infill and the manually selected structure after restart", async () => {
    const { store } = await startConverter();
    store.getState().setTargetWidthMm(160);
    store.getState().setTargetHeightMm(80);
    store.getState().setSpacerThick(2.4);
    store.getState().setBackingInfillDensityPercent(35);
    store.getState().setStructureMode(StructureMode.DOUBLE_SIDED);
    const { store: restarted } = await startConverter();
    expect(restarted.getState()).toMatchObject({
      target_width_mm: 160, target_height_mm: 80,
      spacer_thick: 2.4, base_spacer_thick: 2.4,
      backing_infill_density_percent: 35, structure_mode: StructureMode.DOUBLE_SIDED,
    });
  });

  it.each(["setImageFile", "loadVectorizedSvgIntoConverter", "handleFilesSelect"] as const)(
    "%s applies the previous longer edge to a new portrait and landscape",
    async (action) => {
      const { store } = await startConverter();
      store.setState({ target_width_mm: 160, target_height_mm: 80, enableCrop: false });
      const file = new File(["svg"], "image.svg", { type: "image/svg+xml" });
      if (action === "handleFilesSelect") store.getState()[action]([file]);
      else store.getState()[action](file);
      images.at(-1)!.onload!();
      expect(store.getState()).toMatchObject({ target_width_mm: 80, target_height_mm: 160 });

      store.getState().setImageFile(null);
      store.getState().setImageFile(new File(["png"], "landscape.png", { type: "image/png" }));
      images.at(-1)!.naturalWidth = 400;
      images.at(-1)!.naturalHeight = 200;
      images.at(-1)!.onload!();
      expect(store.getState()).toMatchObject({ target_width_mm: 160, target_height_mm: 80 });
    },
  );

  it("applies longer-edge sizing to RAW previews", async () => {
    const { store } = await startConverter();
    store.setState({ target_width_mm: 160, target_height_mm: 80, enableCrop: false });
    vi.mocked(uploadImagePreview).mockResolvedValue({ preview_url: "/api/files/raw.png", width: 200, height: 400 });
    store.getState().setImageFile(new File(["raw"], "photo.cr2"));
    await vi.waitFor(() => expect(store.getState().aspectRatio).toBe(0.5));
    expect(store.getState()).toMatchObject({ target_width_mm: 80, target_height_mm: 160 });
  });

  it("keeps magnet cavities within the resized image", async () => {
    const { store } = await startConverter();
    store.setState({ target_width_mm: 160, target_height_mm: 80, enableCrop: false });
    store.getState().setEnableFridgeMagnet(true);
    expect(store.getState().fridge_magnets.length).toBeGreaterThan(0);
    store.getState().setImageFile(new File(["png"], "portrait.png", { type: "image/png" }));
    images.at(-1)!.onload!();
    const state = store.getState();
    for (const magnet of state.fridge_magnets) {
      const width = magnet.shape === "round" ? magnet.diameter_mm! : magnet.width_mm!;
      const height = magnet.shape === "round" ? magnet.diameter_mm! : magnet.height_mm!;
      expect(Math.abs(magnet.center_x_mm) + width / 2).toBeLessThanOrEqual(state.target_width_mm / 2);
      expect(Math.abs(magnet.center_y_mm) + height / 2).toBeLessThanOrEqual(state.target_height_mm / 2);
    }
  });

  it("keeps explicit project dimensions after its embedded image loads", async () => {
    const { store } = await startConverter();
    store.getState().importRecipeState(
      { target_width_mm: 120.5, target_height_mm: 80.25 },
      new File(["png"], "project.png", { type: "image/png" }),
    );
    images.at(-1)!.onload!();
    expect(store.getState()).toMatchObject({ target_width_mm: 120.5, target_height_mm: 80.25 });
  });

  it.each(["setEnableRelief", "setModelSurfaceEnabled"] as const)(
    "%s keeps the remembered infill while requiring solid backing",
    async (action) => {
      const { store } = await startConverter();
      store.getState().setBackingInfillDensityPercent(35);
      store.getState()[action](true);
      expect(store.getState().backing_infill_density_percent).toBe(100);
      expect(localStorage.getItem("lumina_backingInfillDensityPercent")).toBe("35");
      store.getState()[action](false);
      expect(store.getState().backing_infill_density_percent).toBe(35);
      const { store: restarted } = await startConverter();
      expect(restarted.getState().backing_infill_density_percent).toBe(35);
    },
  );

  it("ignores malformed preferences and uses single-sided on first use", async () => {
    localStorage.setItem("lumina_outputDimensions", '{"target_width_mm":null}');
    localStorage.setItem("lumina_backingThickness", "Infinity");
    const { store } = await startConverter();
    expect(store.getState()).toMatchObject({ target_width_mm: 60, target_height_mm: 60, spacer_thick: 1.2, structure_mode: StructureMode.SINGLE_SIDED });
  });

  it("keeps editing working when saving preferences fails", async () => {
    const { store } = await startConverter();
    vi.spyOn(localStorage, "setItem").mockImplementation(() => { throw new Error("Storage unavailable"); });
    expect(() => store.getState().setTargetWidthMm(150)).not.toThrow();
    expect(() => store.getState().setSpacerThick(2.4)).not.toThrow();
    expect(store.getState()).toMatchObject({ target_width_mm: 150, spacer_thick: 2.4 });
  });
});
