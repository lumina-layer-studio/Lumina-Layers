import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as api from "../../api/materialCache";
import { useConverterStore } from "../../stores/converter";
import { converterSourceKey } from "../../stores/converter/project";
import { useDynamicMaterialCatalog } from "../useDynamicMaterialCatalog";

const original = useConverterStore.getState();
const settle = () => act(async () => { await vi.advanceTimersByTimeAsync(550); });

beforeEach(() => {
  vi.useFakeTimers();
  useConverterStore.setState({
    source_version: "material", materialDynamicLayerCountEnabled: true,
    selectedMaterialDirNames: ["brand/red", "brand/white"], materialBackingMaterialDirName: "brand/white",
    materialLayerHeightMm: 0.08, materialMinLayerCount: 5, materialMaxLayerCount: 10, imageFile: null,
  });
});

afterEach(() => {
  cleanup();
  useConverterStore.setState(original, true);
  vi.restoreAllMocks();
  vi.useRealTimers();
});

it("prepares before an image is opened and ignores edits unrelated to the catalog", async () => {
  const prepare = vi.spyOn(api, "prepareDynamicMaterialCatalog").mockResolvedValue();
  const { rerender } = renderHook(({ enabled }) => useDynamicMaterialCatalog(enabled), { initialProps: { enabled: false } });
  await settle();
  expect(prepare).not.toHaveBeenCalled();
  rerender({ enabled: true });
  await settle();
  expect(prepare).toHaveBeenCalledExactlyOnceWith({
    materialDirectoryNames: ["brand/red", "brand/white"], backingMaterialIndex: 1,
    layerHeightMm: 0.08, minLayers: 5, maxLayers: 10, projectMaterials: null,
  });
  act(() => { useConverterStore.setState({ target_width_mm: 210 }); });
  await settle();
  expect(prepare).toHaveBeenCalledTimes(1);
  act(() => { useConverterStore.setState({ materialDynamicLayerCountEnabled: false, materialMaxLayerCount: 7 }); });
  await settle();
  expect(prepare).toHaveBeenCalledTimes(1);
});

it("prepares the latest pending palette with its project archive after an earlier request fails", async () => {
  let rejectFirst!: (reason: Error) => void;
  const prepare = vi.spyOn(api, "prepareDynamicMaterialCatalog").mockResolvedValue()
    .mockImplementationOnce(() => new Promise<void>((_, reject) => { rejectFirst = reject; }));
  renderHook(() => useDynamicMaterialCatalog(true));
  await settle();
  act(() => { useConverterStore.setState({ materialMaxLayerCount: 8 }); });
  await settle();
  const archive = new File(["embedded"], "materials.zip");
  act(() => { useConverterStore.setState({
    materialMaxLayerCount: 7, projectMaterialArchiveFile: archive,
    projectSourceKey: converterSourceKey(useConverterStore.getState()),
  }); });
  await settle();
  expect(prepare).toHaveBeenCalledTimes(1);
  await act(async () => { rejectFirst(new Error("unavailable")); });
  expect(prepare).toHaveBeenCalledTimes(2);
  expect(prepare).toHaveBeenLastCalledWith(expect.objectContaining({ maxLayers: 7, projectMaterials: archive }));
});
