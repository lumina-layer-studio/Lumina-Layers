import { beforeEach, describe, expect, it } from "vitest";
import { DEFAULT_STATE, useConverterStore } from "../stores/converter";

describe("fixed 30-layer unlock switch", () => {
  beforeEach(() => {
    useConverterStore.setState({ ...DEFAULT_STATE, source_version: "material" });
  });

  it("caps fixed layers at 10 while dynamic ranges allow 30 without unlocking", () => {
    const store = useConverterStore.getState();
    expect(store.materialLayersUnlocked).toBe(false);
    store.setMaterialLayerCount(30);
    store.setMaterialMaxLayerCount(35);
    store.setMaterialMinLayerCount(18);
    expect(useConverterStore.getState()).toMatchObject({
      materialLayerCount: 10, materialMaxLayerCount: 30, materialMinLayerCount: 18,
    });
  });

  it("allows up to 30 once unlocked", () => {
    const store = useConverterStore.getState();
    store.setMaterialLayersUnlocked(true);
    store.setMaterialLayerCount(40);
    store.setMaterialMaxLayerCount(30);
    expect(useConverterStore.getState()).toMatchObject({
      materialLayerCount: 30, materialMaxLayerCount: 30,
    });
  });

  it("pulls only the fixed count back to 10 when locked again", () => {
    const store = useConverterStore.getState();
    store.setMaterialLayersUnlocked(true);
    store.setMaterialLayerCount(24);
    store.setMaterialMinLayerCount(12);
    store.setMaterialMaxLayerCount(20);
    store.setMaterialLayersUnlocked(false);
    expect(useConverterStore.getState()).toMatchObject({
      materialLayersUnlocked: false,
      materialLayerCount: 10, materialMinLayerCount: 12, materialMaxLayerCount: 20,
    });
  });
});
