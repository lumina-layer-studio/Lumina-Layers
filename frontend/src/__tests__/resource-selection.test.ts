import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ColorMode } from "../api/types";
import { DEFAULT_STATE, useConverterStore } from "../stores/converter";
import { beginResourceCalibration, createResourceSelectionIntent, discardResourceCalibration, restoreTrialLut, returnFromResourceCalibration, takeResourceCalibrationReturn, useMaterialTrialStore, useResourceCalibrationStore } from "../stores/converter/resourceSelection";
import { installExtractedLut } from "../api/extractor";
import { useWidgetStore } from "../stores/widgetStore";

vi.mock("../api/lut", async (original) => ({ ...await original<typeof import("../api/lut")>(), fetchLutInfo: vi.fn(() => new Promise(() => {})) }));
vi.mock("../api/converter", async (original) => ({ ...await original<typeof import("../api/converter")>(), fetchLutColors: vi.fn(() => new Promise(() => {})) }));
vi.mock("../api/extractor", async (original) => ({ ...await original<typeof import("../api/extractor")>(), installExtractedLut: vi.fn() }));

describe("resource selection intent", () => {
  const intents: ReturnType<typeof createResourceSelectionIntent>[] = [];
  const intent = () => { const result = createResourceSelectionIntent(); intents.push(result); return result; };
  beforeEach(() => {
    useMaterialTrialStore.setState({ backup: null });
    useConverterStore.setState({ ...DEFAULT_STATE, source_version: "legacy", color_mode: ColorMode.FOUR_COLOR_RYBW, lutListFull: [
      { name: "red", path: "red.json", color_mode: ColorMode.FOUR_COLOR_RYBW },
      { name: "blue", path: "blue.json", color_mode: ColorMode.FOUR_COLOR_RYBW },
      { name: "cmyw", path: "cmyw.json", color_mode: ColorMode.FOUR_COLOR_CMYW },
    ], lut_names: ["red"], lut_name: "red" } as never);
  });
  it("keeps LUTs while browsing, then applies a trial and restores its original layer settings", () => {
    useConverterStore.setState({ color_layers: 7, layer_height_mm: 0.1, target_width_mm: 143 });
    const trial = createResourceSelectionIntent({ materialTrial: true, initialQuery: "Aliz" });
    intents.push(trial);
    expect(useConverterStore.getState().source_version).toBe("legacy");
    expect(trial.applyMaterials([])).toBe("material_guide_select_required");
    expect(trial.applyMaterials(["red-profile", "white-profile"])).toBeNull();
    expect(useConverterStore.getState()).toMatchObject({
      source_version: "material", lut_names: ["red"], selectedMaterialDirNames: ["red-profile", "white-profile"],
      target_width_mm: 143,
    });
    restoreTrialLut();
    expect(useConverterStore.getState()).toMatchObject({
      source_version: "legacy", lut_names: ["red"], color_layers: 7, layer_height_mm: 0.1, target_width_mm: 143,
    });
  });
  it("retains a LUT trial across calibration and rejects it when the original task changes", async () => {
    const trial = createResourceSelectionIntent({ materialTrial: true, initialQuery: "Aliz" });
    intents.push(trial);
    beginResourceCalibration("materials", ["existing"], trial);
    await returnFromResourceCalibration("materials", "new");
    const returned = takeResourceCalibrationReturn("materials")!;
    expect(returned.intent.materialTrial).toBe(true);
    expect(returned.intent.initialQuery).toBe("Aliz");
    expect(returned.selected).toEqual(["existing", "new"]);
    useConverterStore.setState({ imageFile: new File(["other"], "other.png") });
    expect(returned.intent.applyMaterials(returned.selected)).toBe("resources_task_changed");
    expect(useConverterStore.getState().source_version).toBe("legacy");
  });
  it("does not restore a trial's LUT into a different image", () => {
    const trial = createResourceSelectionIntent({ materialTrial: true });
    intents.push(trial);
    trial.applyMaterials(["red-profile"]);
    useConverterStore.setState({ imageFile: new File(["other"], "other.png") });
    restoreTrialLut();
    expect(useConverterStore.getState().source_version).toBe("material");
  });
  afterEach(() => { discardResourceCalibration(); intents.splice(0).forEach((item) => item.dispose()); vi.restoreAllMocks(); });

  it("returns calibrated materials as an appended draft with the original intent, only once", async () => {
    useConverterStore.setState({ source_version: "material", selectedMaterialDirNames: ["applied"] });
    const original = intent();
    beginResourceCalibration("materials", ["applied", "draft"], original);
    await returnFromResourceCalibration("materials", "calibrated");
    expect(useWidgetStore.getState().activeTab).toBe("converter");
    expect(useConverterStore.getState().selectedMaterialDirNames).toEqual(["applied"]);
    expect(takeResourceCalibrationReturn("luts")).toBeNull();
    const returned = takeResourceCalibrationReturn("materials");
    expect(returned?.selected).toEqual(["applied", "draft", "calibrated"]);
    expect(returned?.intent).toBe(original);
    expect(takeResourceCalibrationReturn("materials")).toBeNull();
  });

  it("installs the confirmed extraction session, refreshes inventory and never applies it automatically", async () => {
    vi.mocked(installExtractedLut).mockResolvedValue({ name: "blue" });
    const refresh = vi.spyOn(useConverterStore.getState(), "refreshResourceCatalog").mockResolvedValue();
    beginResourceCalibration("luts", ["red"], intent());
    await returnFromResourceCalibration("luts", "confirmed-session");
    expect(installExtractedLut).toHaveBeenCalledWith("confirmed-session");
    expect(refresh).toHaveBeenCalledOnce();
    expect(takeResourceCalibrationReturn("luts")?.selected).toEqual(["red", "blue"]);
    expect(useConverterStore.getState().lut_names).toEqual(["red"]);
  });

  it("keeps an installed calibration in the library but rejects returning to a changed task", async () => {
    let resolve!: (value: { name: string }) => void;
    vi.mocked(installExtractedLut).mockReturnValue(new Promise((done) => { resolve = done; }));
    vi.spyOn(useConverterStore.getState(), "refreshResourceCatalog").mockResolvedValue();
    beginResourceCalibration("luts", ["red"], intent());
    const returning = returnFromResourceCalibration("luts", "old-session");
    useConverterStore.setState({ sessionId: "new-task" });
    resolve({ name: "blue" });
    await returning;
    expect(takeResourceCalibrationReturn("luts")).toBeNull();
    expect(useResourceCalibrationStore.getState().error).toBeTruthy();
    expect(useConverterStore.getState().lut_names).toEqual(["red"]);
  });

  it("keeps the image and conversion parameters when confirming additional compatible LUTs", () => {
    const file = new File(["image"], "image.png");
    useConverterStore.setState({ imageFile: file, target_width_mm: 143, spacer_thick: 2.2 });
    expect(intent().applyLuts(["red", "blue"])).toBeNull();
    expect(useConverterStore.getState()).toMatchObject({ imageFile: file, target_width_mm: 143, spacer_thick: 2.2, lut_names: ["red", "blue"] });
  });

  it.each(["image", "session", "mode"])("rejects a stale picker after changing %s and changing back", (change) => {
    const selection = intent();
    const original = useConverterStore.getState();
    useConverterStore.setState(change === "image" ? { imageFile: new File(["other"], "other.png") }
      : change === "session" ? { sessionId: "new-session" } : { color_mode: ColorMode.BW });
    useConverterStore.setState({ imageFile: original.imageFile, sessionId: original.sessionId, color_mode: original.color_mode });
    expect(selection.applyLuts(["blue"])).toBe("resources_task_changed");
    expect(useConverterStore.getState().lut_names).toEqual(["red"]);
  });

  it("requires an explicit mode change and rejects mixed incompatible LUTs", () => {
    const selection = intent();
    expect(selection.checkLuts(["cmyw"])).toEqual({ modeChange: ColorMode.FOUR_COLOR_CMYW });
    expect(selection.applyLuts(["cmyw"])).toBe("resources_incompatible_lut");
    expect(selection.checkLuts(["red", "cmyw"]).error).toBe("resources_incompatible_lut");
    expect(selection.applyLuts(["cmyw"], true)).toBeNull();
    expect(useConverterStore.getState().color_mode).toBe(ColorMode.FOUR_COLOR_CMYW);
  });
});
