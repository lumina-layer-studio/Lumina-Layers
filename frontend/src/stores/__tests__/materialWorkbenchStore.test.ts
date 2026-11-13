import { beforeEach, describe, expect, it } from "vitest";

import {
  comboFromConverter,
  resolveBackingDirName,
  selectWorkbenchCombo,
  useMaterialWorkbenchStore,
  workbenchComboKey,
  type ConverterMaterialSnapshot,
} from "../materialWorkbenchStore";

const INITIAL = useMaterialWorkbenchStore.getState();

const snapshot = (overrides: Partial<ConverterMaterialSnapshot> = {}): ConverterMaterialSnapshot => ({
  selectedMaterialDirNames: ["Brand/Red", "Brand/White PLA", "Brand/Blue"],
  materialDynamicLayerCountEnabled: false,
  materialLayerCount: 7,
  materialMinLayerCount: 6,
  materialMaxLayerCount: 9,
  materialLayerHeightMm: 0.04,
  materialBackingMaterialDirName: null,
  ...overrides,
});

describe("materialWorkbenchStore", () => {
  beforeEach(() => {
    useMaterialWorkbenchStore.setState(INITIAL, true);
  });

  it("maps converter settings and infers the white backing material", () => {
    const combo = comboFromConverter(snapshot({ materialDynamicLayerCountEnabled: true }));

    expect(combo).toEqual({
      materialDirectoryNames: ["Brand/Red", "Brand/White PLA", "Brand/Blue"],
      layerMode: "dynamic",
      layerCount: 7,
      minLayerCount: 6,
      maxLayerCount: 9,
      layerHeightMm: 0.04,
      substrate: "white",
      backingDirName: "Brand/White PLA",
    });
  });

  it("keeps an explicit backing only while it is still selected", () => {
    const names = ["A", "B"];
    expect(resolveBackingDirName(names, "B")).toBe("B");
    expect(resolveBackingDirName(names, "Gone")).toBe("A");
    expect(resolveBackingDirName([], null)).toBeNull();
  });

  it("seeds from the converter once and never overwrites a user choice", () => {
    const store = useMaterialWorkbenchStore.getState();
    store.ensureInitialized(comboFromConverter(snapshot()));
    expect(useMaterialWorkbenchStore.getState().layerCount).toBe(7);

    useMaterialWorkbenchStore.getState().setLayerCount(9);
    useMaterialWorkbenchStore.getState().ensureInitialized(comboFromConverter(snapshot()));

    expect(useMaterialWorkbenchStore.getState().layerCount).toBe(9);
  });

  it("waits for a nonempty converter combination before initializing", () => {
    const store = useMaterialWorkbenchStore.getState();
    store.ensureInitialized(comboFromConverter(snapshot({ selectedMaterialDirNames: [] })));
    expect(useMaterialWorkbenchStore.getState().initialized).toBe(false);
    store.ensureInitialized(comboFromConverter(snapshot()));
    expect(useMaterialWorkbenchStore.getState().materialDirectoryNames).toEqual(snapshot().selectedMaterialDirNames);
  });

  it("keeps the dynamic range ordered and within 5..10", () => {
    const store = useMaterialWorkbenchStore.getState();
    store.setMaxLayerCount(6);
    store.setMinLayerCount(8);
    let state = useMaterialWorkbenchStore.getState();
    expect([state.minLayerCount, state.maxLayerCount]).toEqual([8, 8]);

    state.setMaxLayerCount(3);
    state = useMaterialWorkbenchStore.getState();
    expect([state.minLayerCount, state.maxLayerCount]).toEqual([5, 5]);

    state.setLayerCount(42);
    expect(useMaterialWorkbenchStore.getState().layerCount).toBe(10);
  });

  it("combo key ignores fields the current layer mode does not use", () => {
    const fixed = comboFromConverter(snapshot());
    expect(workbenchComboKey({ ...fixed, minLayerCount: 9, backingDirName: "Brand/Red" })).toBe(
      workbenchComboKey(fixed),
    );
    expect(workbenchComboKey({ ...fixed, layerCount: 8 })).not.toBe(workbenchComboKey(fixed));

    const dynamic = { ...fixed, layerMode: "dynamic" as const };
    expect(workbenchComboKey({ ...dynamic, layerCount: 10 })).toBe(workbenchComboKey(dynamic));
    expect(workbenchComboKey({ ...dynamic, backingDirName: "Brand/Red" })).not.toBe(
      workbenchComboKey(dynamic),
    );
  });

  it("selectWorkbenchCombo resolves the backing material", () => {
    useMaterialWorkbenchStore.getState().applySelection({
      ...comboFromConverter(snapshot()),
      backingDirName: null,
    });

    expect(selectWorkbenchCombo(useMaterialWorkbenchStore.getState()).backingDirName).toBe(
      "Brand/White PLA",
    );
  });
});
