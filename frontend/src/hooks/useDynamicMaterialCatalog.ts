import { useEffect, useRef } from "react";
import { useShallow } from "zustand/react/shallow";
import { prepareDynamicMaterialCatalog } from "../api/materialCache";
import { useConverterStore } from "../stores/converter";
import { boundProjectResources } from "../stores/converter/project";
import { buildMaterialSourceParams, isDynamicMaterialActive } from "../stores/converter/sources";

/** Start palette-only work while the user is setting up their image. */
export function useDynamicMaterialCatalog(enabled: boolean): void {
  const selection = useConverterStore(useShallow(state => {
    if (!enabled || !isDynamicMaterialActive(state) || !state.selectedMaterialDirNames.length) return null;
    const params = buildMaterialSourceParams(state);
    return {
      materialDirectoryNames: params.selected_materials,
      backingMaterialIndex: params.material_backing_material_index,
      layerHeightMm: params.material_layer_height_mm,
      minLayers: params.material_min_layer_count,
      maxLayers: params.material_max_layer_count,
      projectMaterials: boundProjectResources(state).materials,
    };
  }));
  const running = useRef<Promise<void> | null>(null);
  useEffect(() => {
    if (!selection) return;
    let active = true;
    const timer = window.setTimeout(async () => {
      await running.current;
      if (!active) return;
      // Preview can populate the same catalog if preparation fails.
      running.current = prepareDynamicMaterialCatalog(selection).catch(() => {});
    }, 500);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [selection]);
}
