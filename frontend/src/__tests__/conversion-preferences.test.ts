import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useConverterStore, DEFAULT_STATE } from "../stores/converter";
import { useSettingsStore, DEFAULT_SETTINGS } from "../stores/settingsStore";
import { StructureMode } from "../api/types";
import {
  captureConversionParameters,
  applyConversionParameters,
  normalizeConversionPreferences,
} from "../stores/conversionPreferences";
import { bindConversionPreferences } from "../hooks/useConversionPreferences";

describe("conversion preferences", () => {
  beforeEach(() => {
    localStorage.clear();
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
    useConverterStore.setState({ ...DEFAULT_STATE, lut_name: "", lut_names: [] });
  });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("defaults to material archives when no preferences are saved", () => {
    const stop = bindConversionPreferences();
    try {
      expect(useConverterStore.getState().source_version).toBe("material");
    } finally { stop(); }
  });

  it.each(["legacy", "material"] as const)("restores a remembered %s source", async (source) => {
    const stop = bindConversionPreferences();
    useConverterStore.getState().setSourceVersion(source);
    stop();
    const stored = localStorage.getItem("lumina-settings")!;
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
    localStorage.setItem("lumina-settings", stored);
    await useSettingsStore.persist.rehydrate();
    useConverterStore.setState({ ...DEFAULT_STATE });
    const stopAgain = bindConversionPreferences();
    try {
      expect(useConverterStore.getState().source_version).toBe(source);
    } finally { stopAgain(); }
  });

  it("remembers 30-layer settings and the unlock switch", async () => {
    const stop = bindConversionPreferences();
    const store = useConverterStore.getState();
    store.setSourceVersion("material");
    store.setMaterialLayersUnlocked(true);
    store.setMaterialLayerCount(30);
    store.setMaterialLayerHeightMm(0.04);
    store.setTargetWidthMm(180);
    stop();
    const stored = localStorage.getItem("lumina-settings")!;
    expect(JSON.parse(stored).state.conversionPreferences.last).toMatchObject({
      materialLayersUnlocked: true, materialLayerCount: 30, materialLayerHeightMm: 0.04, size_mm: 180,
    });

    // Reload: a fresh store starts locked at 10 layers, then restores everything.
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
    localStorage.setItem("lumina-settings", stored);
    await useSettingsStore.persist.rehydrate();
    useConverterStore.setState({ ...DEFAULT_STATE });
    const stopAgain = bindConversionPreferences();
    try {
      expect(useConverterStore.getState()).toMatchObject({
        materialLayersUnlocked: true, materialLayerCount: 30, materialLayerHeightMm: 0.04, target_width_mm: 180,
      });
    } finally { stopAgain(); }
  });

  it("unlocks deep layer counts from records saved before the switch existed", () => {
    const prefs = normalizeConversionPreferences({ last: {
      ...captureConversionParameters({ ...DEFAULT_STATE, source_version: "material" } as never),
      materialLayerCount: 24, materialLayersUnlocked: undefined,
    } });
    expect(prefs.last?.materialLayerCount).toBe(24);
    applyConversionParameters(useConverterStore.getState, prefs.last!);
    expect(useConverterStore.getState()).toMatchObject({ materialLayersUnlocked: true, materialLayerCount: 24 });
  });

  it("restores saved inputs after reconnecting without persisting session data", async () => {
    const stop = bindConversionPreferences();
    useConverterStore.getState().setStructureMode(StructureMode.SINGLE_SIDED);
    useConverterStore.getState().setTargetWidthMm(225);
    useConverterStore.getState().setEnableCoating(true);
    useConverterStore.setState({ sessionId: "private-session", imagePreviewUrl: "/api/files/private" });
    stop();
    const stored = JSON.parse(localStorage.getItem("lumina-settings")!);
    expect(stored.state.conversionPreferences.last).toMatchObject({
      structure_mode: StructureMode.SINGLE_SIDED, size_mm: 225, enable_coating: true,
    });
    expect(JSON.stringify(stored.state.conversionPreferences)).not.toContain("private");
    useSettingsStore.setState({ ...DEFAULT_SETTINGS });
    localStorage.setItem("lumina-settings", JSON.stringify(stored));
    await useSettingsStore.persist.rehydrate();
    useConverterStore.setState({ ...DEFAULT_STATE });
    const stopAgain = bindConversionPreferences();
    expect(useConverterStore.getState()).toMatchObject({
      structure_mode: StructureMode.SINGLE_SIDED, target_width_mm: 225, enable_coating: true,
    });
    stopAgain();
  });

  it("restores backend defaults on a fresh origin and includes them in settings synchronization", async () => {
    const original = captureConversionParameters(useConverterStore.getState());
    const stop = bindConversionPreferences();
    const saved = { last: { ...original, size_mm: 230 }, presets: [
      { id: "art", name: "常用板画", parameters: original },
    ] };
    useSettingsStore.getState().hydrateDeviceSettingsFromBackend({ conversion_preferences: saved });
    expect(useConverterStore.getState().target_width_mm).toBe(230);
    const system = await import("../api/system");
    const save = vi.spyOn(system, "saveSettings").mockResolvedValue({ status: "success", message: "saved" });
    await useSettingsStore.getState().syncToBackend();
    expect(save).toHaveBeenCalledWith(expect.objectContaining({ conversion_preferences: expect.objectContaining(saved) }));
    stop();
  });

  it("keeps a named preset unchanged until explicitly updated", () => {
    const stop = bindConversionPreferences();
    const original = captureConversionParameters(useConverterStore.getState());
    useSettingsStore.getState().setConversionPreferences({
      last: original, presets: [{ id: "art", name: "常用板画", parameters: original }],
    });
    useConverterStore.getState().setTargetWidthMm(180);
    expect(useSettingsStore.getState().conversionPreferences.presets[0].parameters.size_mm).toBe(60);
    expect(useSettingsStore.getState().conversionPreferences.last?.size_mm).toBe(180);
    stop();
  });

  it.each([
    [500, 500, 450], [180, 180, 180], [500, 300, 450],
  ])("fits saved defaults after the real %i × %i mm printer bed loads", (bedWidth, bedHeight, expectedSize) => {
    const original = captureConversionParameters(useConverterStore.getState());
    const stop = bindConversionPreferences();
    try {
      useSettingsStore.getState().hydrateDeviceSettingsFromBackend({
        conversion_preferences: { last: { ...original, size_mm: 450 }, presets: [] },
      });
      expect(useSettingsStore.getState().conversionPreferences.last?.size_mm).toBe(450);
      expect(useConverterStore.getState().target_width_mm).toBe(450);
      useConverterStore.setState({ bedSizes: [{ label: "Selected printer", width_mm: bedWidth,
        height_mm: bedHeight, is_default: true, printer_id: useSettingsStore.getState().printerModel }] });
      useConverterStore.getState().setBedLabel("Selected printer");
      expect(useConverterStore.getState().target_width_mm).toBe(expectedSize);
      expect(useSettingsStore.getState().conversionPreferences.last?.size_mm).toBe(expectedSize);
    } finally { stop(); }
  });

  it("does not replace defaults while importing or editing an existing project", () => {
    const stop = bindConversionPreferences();
    useConverterStore.getState().setTargetWidthMm(225);
    const saved = useSettingsStore.getState().conversionPreferences.last;
    const project = new File(["project"], "project.png", { type: "image/png" });
    useConverterStore.getState().importRecipeState({ target_width_mm: 93,
      target_height_mm: 71, enable_coating: true }, project);
    expect(useConverterStore.getState().target_width_mm).toBe(93);
    useConverterStore.getState().setTargetWidthMm(94);
    expect(useSettingsStore.getState().conversionPreferences.last).toEqual(saved);
    useConverterStore.getState().setImageFile(null);
    expect(useConverterStore.getState().target_width_mm).toBe(225);
    stop();
  });

  it.each([90, 180, 270] as const)("keeps imported printing parameters when rotating the project's SVG by %i degrees", async (degrees) => {
    const pendingLoads: Array<{ naturalWidth: number; naturalHeight: number; onload: (() => void) | null }> = [];
    vi.stubGlobal("Image", class {
      naturalWidth = 160;
      naturalHeight = 100;
      onload: (() => void) | null = null;
      set src(_value: string) { pendingLoads.push(this); }
    });
    const finishImageLoad = (width: number, height: number) => {
      expect(pendingLoads).toHaveLength(1);
      const image = pendingLoads.shift()!;
      image.naturalWidth = width;
      image.naturalHeight = height;
      image.onload!();
    };
    const stop = bindConversionPreferences();
    try {
      useConverterStore.getState().setTargetWidthMm(225);
      useConverterStore.getState().setStructureMode(StructureMode.DOUBLE_SIDED);
      useConverterStore.getState().setSpacerThick(1.2);
      useConverterStore.getState().saveConversionPreset("日常默认");
      const remembered = useSettingsStore.getState().conversionPreferences;
      const source = new File([
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 100"><rect width="80" height="100" fill="red"/><rect x="80" width="80" height="100" fill="blue"/></svg>',
      ], "project.svg", { type: "image/svg+xml" });
      useConverterStore.getState().importRecipeState({ target_width_mm: 93, target_height_mm: 58.125,
        structure_mode: StructureMode.SINGLE_SIDED, base_spacer_thick: 3, spacer_thick: 3 }, source);
      finishImageLoad(160, 100);

      await useConverterStore.getState().rotateImageForExport(degrees);
      const swapsAxes = degrees !== 180;
      finishImageLoad(swapsAxes ? 100 : 160, swapsAxes ? 160 : 100);

      const rotated = useConverterStore.getState();
      expect(rotated.imageFile).not.toBe(source);
      expect(await rotated.imageFile!.text()).toContain(`rotate(${degrees})`);
      expect(rotated).toMatchObject({ target_width_mm: swapsAxes ? 58.125 : 93,
        target_height_mm: swapsAxes ? 93 : 58.125,
        structure_mode: StructureMode.SINGLE_SIDED, base_spacer_thick: 3, spacer_thick: 3,
        conversionParameterContext: "project", error: null });
      expect(useSettingsStore.getState().conversionPreferences).toEqual(remembered);

      // A second edit still belongs to this project; a newly selected file does not,
      // even if its filename and bytes match the imported source.
      await rotated.rotateImageForExport(90);
      finishImageLoad(swapsAxes ? 160 : 100, swapsAxes ? 100 : 160);
      expect(useConverterStore.getState()).toMatchObject({ target_width_mm: swapsAxes ? 93 : 58.125,
        target_height_mm: swapsAxes ? 58.125 : 93,
        structure_mode: StructureMode.SINGLE_SIDED, base_spacer_thick: 3, conversionParameterContext: "project" });
      useConverterStore.getState().setImageFile(new File([await source.text()], source.name, { type: source.type }));
      finishImageLoad(160, 100);
      expect(useConverterStore.getState()).toMatchObject({ target_width_mm: 225,
        structure_mode: StructureMode.DOUBLE_SIDED, base_spacer_thick: 1.2, conversionParameterContext: "defaults" });
      expect(useSettingsStore.getState().conversionPreferences.selectedPresetId).toBe(remembered.selectedPresetId);
    } finally { stop(); }
  });

  it.each([
    [160, 100, 93, 58.125],
    [60, 200, 60.5, 201.6666667],
  ])("preserves exact project dimensions through four loaded quarter turns (%i × %i pixels)", async (pixelWidth, pixelHeight, width, height) => {
    const pendingLoads: Array<{ naturalWidth: number; naturalHeight: number; onload: (() => void) | null }> = [];
    vi.stubGlobal("Image", class {
      naturalWidth = pixelWidth;
      naturalHeight = pixelHeight;
      onload: (() => void) | null = null;
      set src(_value: string) { pendingLoads.push(this); }
    });
    const source = new File([
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${pixelWidth} ${pixelHeight}"><rect width="30" height="50"/></svg>`,
    ], "precise.svg", { type: "image/svg+xml" });
    useConverterStore.getState().importRecipeState({ target_width_mm: width, target_height_mm: height }, source);
    pendingLoads.shift()!.onload!();
    await useConverterStore.getState().rotateImageForExport(180);
    pendingLoads.shift()!.onload!();
    expect(useConverterStore.getState()).toMatchObject({ target_width_mm: width, target_height_mm: height });
    for (let turn = 1; turn <= 4; turn += 1) {
      await useConverterStore.getState().rotateImageForExport(90);
      expect(pendingLoads).toHaveLength(1);
      const image = pendingLoads.shift()!;
      image.naturalWidth = turn % 2 ? pixelHeight : pixelWidth;
      image.naturalHeight = turn % 2 ? pixelWidth : pixelHeight;
      image.onload!();
      expect(useConverterStore.getState()).toMatchObject({
        target_width_mm: turn % 2 ? height : width,
        target_height_mm: turn % 2 ? width : height,
        conversionParameterContext: "project",
      });
    }
  });

  it("remembers the final long edge regardless of the manually edited dimension", async () => {
    const stop = bindConversionPreferences();
    useConverterStore.setState({ aspectRatio: 2 });
    useConverterStore.getState().setTargetHeightMm(100);
    const saved = useSettingsStore.getState().conversionPreferences.last!;
    expect(saved).toMatchObject({ size_axis: "long_edge", size_mm: 200 });
    vi.stubGlobal("Image", class {
      naturalWidth = 100;
      naturalHeight = 200;
      onload: (() => void) | null = null;
      set src(_value: string) { queueMicrotask(() => this.onload?.()); }
    });
    useConverterStore.getState().setImageFile(new File(["image"], "new.png", { type: "image/png" }));
    await Promise.resolve();
    expect(useConverterStore.getState()).toMatchObject({ target_height_mm: 200, target_width_mm: 100 });
    stop();
  });

  it("keeps the remembered long edge when a new image changes orientation", async () => {
    const stop = bindConversionPreferences();
    try {
      useConverterStore.getState().setTargetHeightMm(150);
      vi.stubGlobal("Image", class {
        naturalWidth = 200;
        naturalHeight = 100;
        onload: (() => void) | null = null;
        set src(_value: string) { queueMicrotask(() => this.onload?.()); }
      });
      useConverterStore.getState().setImageFile(new File(["image"], "wide.png", { type: "image/png" }));
      await Promise.resolve();
      expect(useConverterStore.getState()).toMatchObject({
        target_width_mm: 150, target_height_mm: 75,
      });
    } finally { stop(); }
  });

  it("keeps a remembered height as the exact long edge when a new landscape image has a rounded short edge", async () => {
    const stop = bindConversionPreferences();
    try {
      useConverterStore.getState().setTargetHeightMm(225);
      vi.stubGlobal("Image", class {
        naturalWidth = 160;
        naturalHeight = 100;
        onload: (() => void) | null = null;
        set src(_value: string) { queueMicrotask(() => this.onload?.()); }
      });
      useConverterStore.getState().setImageFile(new File(["image"], "wide.png", { type: "image/png" }));
      await Promise.resolve();
      expect(useConverterStore.getState()).toMatchObject({ target_width_mm: 225, target_height_mm: 141 });
      expect(useSettingsStore.getState().conversionPreferences.last?.size_mm).toBe(225);
    } finally { stop(); }
  });

  it.each([
    [1.5, 150, 100], [2 / 3, 100, 150], [1, 150, 150],
  ])("applies the same long edge at aspect ratio %s", (ratio, width, height) => {
    const parameters = { ...captureConversionParameters(useConverterStore.getState()), size_mm: 150 };
    useConverterStore.setState({ aspectRatio: ratio });
    applyConversionParameters(useConverterStore.getState, parameters);
    expect(useConverterStore.getState()).toMatchObject({ target_width_mm: width, target_height_mm: height });
  });

  it("captures identical sizes independently of the last edited axis", () => {
    useConverterStore.setState({ aspectRatio: 1.5 });
    useConverterStore.getState().setTargetWidthMm(150);
    const fromWidth = captureConversionParameters(useConverterStore.getState());
    useConverterStore.getState().setTargetHeightMm(100);
    expect(captureConversionParameters(useConverterStore.getState())).toEqual(fromWidth);
  });

  it.each(["width", "height"])("migrates old %s presets without losing their saved value", axis => {
    const old = { ...captureConversionParameters(useConverterStore.getState()), size_axis: axis, size_mm: 180 };
    const restored = normalizeConversionPreferences({ last: old, presets: [{ id: "old", name: "Old", parameters: old }] });
    expect(restored.last).toMatchObject({ size_axis: "long_edge", size_mm: 180 });
    expect(restored.presets[0].parameters).toEqual(restored.last);
  });

  it("constrains a preset's long edge to the bed while preserving image proportions", () => {
    const parameters = { ...captureConversionParameters(useConverterStore.getState()), size_mm: 400 };
    useConverterStore.setState({ aspectRatio: 2, bedSizes: [{ label: "Default bed", width_mm: 256,
      height_mm: 256, is_default: true, printer_id: useSettingsStore.getState().printerModel }] });
    applyConversionParameters(useConverterStore.getState, parameters);
    expect(useConverterStore.getState()).toMatchObject({ target_width_mm: 256, target_height_mm: 128 });
  });

  it("excludes optional settings by default and preserves them when applying or updating", () => {
    useConverterStore.setState({ enable_cleanup: false, enable_outline: true, outline_width: 3,
      enable_coating: true, coating_height_mm: 0.12 });
    const saved = useConverterStore.getState().saveConversionPreset("Base only");
    if (!("id" in saved)) throw new Error("Save failed");
    const parameters = useSettingsStore.getState().conversionPreferences.presets[0].parameters;
    for (const key of ["enable_cleanup", "enable_outline", "outline_width", "enable_coating", "coating_height_mm"]) {
      expect(parameters).not.toHaveProperty(key);
    }
    useConverterStore.setState({ enable_cleanup: true, enable_outline: false, outline_width: 5,
      enable_coating: false, coating_height_mm: 0.04 });
    useConverterStore.getState().applyConversionPreset(saved.id);
    expect(useConverterStore.getState()).toMatchObject({ enable_cleanup: true, enable_outline: false,
      outline_width: 5, enable_coating: false, coating_height_mm: 0.04 });
    useConverterStore.getState().updateConversionPreset(saved.id);
    expect(useSettingsStore.getState().conversionPreferences.presets[0].parameters).not.toHaveProperty("enable_coating");
  });

  it.each(["advanced", "outline", "coating"] as const)("round-trips only the selected %s group", group => {
    useConverterStore.setState({ enable_cleanup: false, chroma_gate: 12, enable_outline: true,
      outline_width: 3, enable_coating: true, coating_height_mm: 0.12 });
    const result = useConverterStore.getState().saveConversionPreset("Selected", {
      advanced: group === "advanced", outline: group === "outline", coating: group === "coating",
    });
    if (!("id" in result)) throw new Error("Save failed");
    const restored = normalizeConversionPreferences(JSON.parse(JSON.stringify(useSettingsStore.getState().conversionPreferences)));
    useSettingsStore.getState().setConversionPreferences(restored);
    useConverterStore.setState({ enable_cleanup: true, chroma_gate: 20, enable_outline: false,
      outline_width: 5, enable_coating: false, coating_height_mm: 0.04 });
    useConverterStore.getState().applyConversionPreset(result.id);
    expect(useConverterStore.getState()).toMatchObject({
      enable_cleanup: group !== "advanced", chroma_gate: group === "advanced" ? 12 : 20,
      enable_outline: group === "outline", outline_width: group === "outline" ? 3 : 5,
      enable_coating: group === "coating", coating_height_mm: group === "coating" ? 0.12 : 0.04,
    });
  });

  it("keeps factory inputs when the first action is importing someone else's project", () => {
    const stop = bindConversionPreferences();
    useConverterStore.getState().importRecipeState({ target_width_mm: 93 },
      new File(["project"], "project.png", { type: "image/png" }));
    useConverterStore.getState().setImageFile(null);
    expect(useConverterStore.getState().target_width_mm).toBe(60);
    stop();
  });

  it("restores large-format dimensions without clamping them to the ordinary size limit", () => {
    const stop = bindConversionPreferences();
    useConverterStore.getState().setLargeFormatEnabled(true);
    useConverterStore.getState().setTileWidthMm(210);
    useConverterStore.getState().setTargetWidthMm(700);
    stop();
    useConverterStore.setState({ ...DEFAULT_STATE });
    const stopAgain = bindConversionPreferences();
    expect(useConverterStore.getState()).toMatchObject({ largeFormatEnabled: true,
      target_width_mm: 700, tileWidthMm: 210 });
    stopAgain();
  });

  it("hydrates backend preferences but does not override edits made while loading", () => {
    const original = captureConversionParameters(useConverterStore.getState());
    const stop = bindConversionPreferences();
    useConverterStore.getState().setTargetWidthMm(190);
    useSettingsStore.getState().hydrateDeviceSettingsFromBackend({
      conversion_preferences: { last: { ...original, size_mm: 250 }, presets: [] },
    });
    expect(useConverterStore.getState().target_width_mm).toBe(190);
    stop();
  });

  it("discards invalid saved values and never restores arbitrary converter keys", () => {
    expect(normalizeConversionPreferences({ last: { size_mm: NaN }, presets: [] }).last).toBeNull();
    const valid = captureConversionParameters(useConverterStore.getState());
    const result = normalizeConversionPreferences({ last: { ...valid, sessionId: "private" },
      presets: [{ id: "bad", name: "", parameters: valid }] });
    expect(result.last).not.toHaveProperty("sessionId");
    expect(result.presets).toEqual([]);
  });

  it("restores an unset backing selection after material selection changes it", () => {
    useConverterStore.setState({ source_version: "material", selectedMaterialDirNames: ["old"],
      materialBackingMaterialDirName: null });
    const target = { ...captureConversionParameters(useConverterStore.getState()), selectedMaterialDirNames: ["new"] };
    applyConversionParameters(useConverterStore.getState, target);
    expect(useConverterStore.getState().materialBackingMaterialDirName).toBeNull();
  });

  it("does not reapply current settings or invalidate output when only renaming a preset", () => {
    const parameters = captureConversionParameters(useConverterStore.getState());
    useSettingsStore.getState().setConversionPreferences({ last: parameters, selectedPresetId: "art",
      presets: [{ id: "art", name: "常用板画", parameters }] });
    const stop = bindConversionPreferences();
    useConverterStore.setState({ downloadUrl: "/api/files/existing.3mf" });
    try {
      expect(useConverterStore.getState().renameConversionPreset("art", "新名字")).toBeNull();
      expect(useConverterStore.getState().downloadUrl).toBe("/api/files/existing.3mf");
    } finally { stop(); }
  });

  it("does not reapply parameters or invalidate output when saving the first preset", () => {
    const stop = bindConversionPreferences();
    useConverterStore.setState({ downloadUrl: "/api/files/existing.3mf" });
    try {
      expect(useConverterStore.getState().saveConversionPreset("常用板画")).toHaveProperty("id");
      expect(useConverterStore.getState().downloadUrl).toBe("/api/files/existing.3mf");
    } finally { stop(); }
  });

  it("restores a native database subset after changing its brand populates default databases", () => {
    const brand = (key: string, names: string[]) => ({ brand_key: key, material_type: "PLA", vendor: key,
      display_name: key, db_options: names.map(name => ({ name, path: name, color_mode: "4-Color" })),
      default_db_names: names, supported_modes: [] });
    useConverterStore.setState({ source_version: "native", selectedNativeBrandKey: "old",
      selectedNativeDbNames: ["shared"], nativeBrandGroups: [brand("old", ["shared"]), brand("new", ["shared", "extra"])] });
    const target = { ...captureConversionParameters(useConverterStore.getState()), selectedNativeBrandKey: "new" };
    applyConversionParameters(useConverterStore.getState, target);
    expect(useConverterStore.getState().selectedNativeDbNames).toEqual(["shared"]);
  });

  it("persists only the completed snapshot when applying a preset with linked changes", () => {
    const initial = captureConversionParameters(useConverterStore.getState());
    const target = { ...initial, source_version: "material" as const, selectedMaterialDirNames: ["white"],
      size_mm: 225, structure_mode: StructureMode.SINGLE_SIDED, enable_coating: true };
    useSettingsStore.getState().setConversionPreferences({ last: initial,
      presets: [{ id: "art", name: "常用板画", parameters: target }] });
    const stop = bindConversionPreferences();
    const writes: unknown[] = [];
    const stopWrites = useSettingsStore.subscribe((state, previous) => {
      if (JSON.stringify(state.conversionPreferences.last) !== JSON.stringify(previous.conversionPreferences.last)) {
        writes.push(state.conversionPreferences.last);
      }
    });
    try {
      expect(useConverterStore.getState().applyConversionPreset("art")).toBe(true);
      expect(writes).toEqual([target]);
      expect(useConverterStore.getState().conversionParameterContext).toBe("defaults");
      expect(useSettingsStore.getState().conversionPreferences.selectedPresetId).toBe("art");
    } finally { stopWrites(); stop(); }
  });

  it("validates preset mutations even without a mounted UI or persistence binding", () => {
    const actions = useConverterStore.getState();
    expect(actions.saveConversionPreset("  ")).toEqual({ error: "invalid-name" });
    expect(actions.saveConversionPreset("x".repeat(41))).toEqual({ error: "invalid-name" });
    const result = actions.saveConversionPreset(" 常用板画 ");
    expect(result).toHaveProperty("id");
    if (!("id" in result)) throw new Error("Expected a saved preset");
    expect(actions.saveConversionPreset("常用板画")).toEqual({ error: "duplicate-name" });
    const second = actions.saveConversionPreset("挂件");
    if (!("id" in second)) throw new Error("Expected a second preset");
    expect(actions.renameConversionPreset(second.id, "常用板画")).toBe("duplicate-name");
    expect(actions.renameConversionPreset(result.id, " 常用板画 ")).toBeNull();
    expect(actions.applyConversionPreset("missing")).toBe(false);
    expect(actions.updateConversionPreset("missing")).toBe(false);
    expect(actions.renameConversionPreset("missing", "名称")).toBe("missing-preset");
    actions.setTargetWidthMm(180);
    expect(actions.applyConversionPreset(result.id)).toBe(true);
    actions.deleteConversionPreset(result.id);
    expect(useConverterStore.getState().target_width_mm).toBe(60);
    expect(useSettingsStore.getState().conversionPreferences.selectedPresetId).toBeNull();
    expect(useSettingsStore.getState().conversionPreferences.last?.size_mm).toBe(60);
  });

  it("preserves remembered defaults when saving an imported project's settings as a new preset", () => {
    const stop = bindConversionPreferences();
    try {
      useConverterStore.getState().setTargetWidthMm(225);
      useConverterStore.getState().importRecipeState({ target_width_mm: 93 },
        new File(["project"], "project.png", { type: "image/png" }));
      expect(useSettingsStore.getState().conversionPreferences.last?.size_mm).toBe(225);
      const result = useConverterStore.getState().saveConversionPreset("导入的板画");
      if (!("id" in result)) throw new Error("Expected a saved preset");
      expect(useSettingsStore.getState().conversionPreferences).toMatchObject({ selectedPresetId: result.id,
        last: { size_mm: 93 }, presets: [{ parameters: { size_mm: 93 } }] });
      expect(useConverterStore.getState().conversionParameterContext).toBe("defaults");
    } finally { stop(); }
  });
});
