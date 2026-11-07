import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as converterApi from "../api/converter";
import type { ExportMaterialSelection } from "../api/types";
import NativeMaterialSelectionDialog from "../components/ui/NativeMaterialSelectionDialog";
import { I18nProvider } from "../i18n/context";
import { translations } from "../i18n/translations";
import { exportConverterRecipe } from "../recipe/exportRecipe";
import { DEFAULT_STATE, useConverterStore } from "../stores/converter";
import { buildGenerateParams } from "../stores/converter/requests";
import { buildConversionSourceParams } from "../stores/converter/sources";
import { DEFAULT_SETTINGS, useSettingsStore } from "../stores/settingsStore";
import { useWidgetStore } from "../stores/widgetStore";
import { collectBugReportContext } from "../utils/bugReportContext";

const deviceProfileId = "BambuStudio:bbl:bambu-lab-x2d:0.4";
const blue = "Ocean PLA · 蓝";
const white = "Ivory PLA";

function selection(names = [white, blue]): ExportMaterialSelection {
  const profile = "Generic PLA";
  return {
    ready: true, slicer_id: "BambuStudio", machine_uid: "X2D", nozzle_uid: "0.4",
    device_profile_id: deviceProfileId, machine_profile_id: "BambuStudio:bbl:bambu-lab-x2d",
    build_plate_uid: "PEI", issues: [],
    build_plates: [{ id: "pei", name: "PEI", build_plate_uid: "PEI", compatible: true }],
    materials: names.map((name) => ({
      name, material_type: "PLA", selected_profile_name: profile,
      profiles: [{ name: profile, vendor: "Generic", material_type: "PLA", available: true,
        supported_build_plate_uids: ["PEI"] }],
    })),
  };
}

function singleParams() {
  const state = useConverterStore.getState();
  return buildGenerateParams(state, useSettingsStore.getState(), buildConversionSourceParams(state)!, undefined, undefined);
}

describe("X2D external spool", () => {
  beforeEach(() => {
    useConverterStore.setState({
      ...DEFAULT_STATE, source_version: "material", selectedMaterialDirNames: ["ivory", "ocean"],
      batchMode: true, batchFiles: [new File(["img"], "image.png")],
    });
    useSettingsStore.setState({
      ...DEFAULT_SETTINGS, printerModel: "bambu-lab-x2d", deviceProfileId, buildPlateId: "pei",
    });
    useWidgetStore.setState({ activeTab: "converter" });
    vi.spyOn(useSettingsStore.getState(), "syncToBackend").mockResolvedValue();
    vi.spyOn(converterApi, "fetchExportMaterialSelection").mockResolvedValue(selection());
    vi.spyOn(converterApi, "convertBatch").mockResolvedValue({
      status: "ok", message: "", download_url: "/api/files/batch.3mf", preview_3d_url: null,
      results: [], warnings: [],
    });
  });
  afterEach(() => {
    cleanup();
    useConverterStore.getState().cancelNativeMaterialSelection();
    vi.restoreAllMocks();
  });

  it("saves the chosen material identity and uses it across single and batch output, cards and feedback", async () => {
    expect(singleParams()).not.toHaveProperty("external_spool_material");
    await useConverterStore.getState().openNativeMaterialSelection();
    render(<I18nProvider><NativeMaterialSelectionDialog /></I18nProvider>);
    fireEvent.click(screen.getByRole("combobox", { name: translations.native_material_external_spool.zh }));
    fireEvent.click(screen.getByRole("option", { name: blue }));
    fireEvent.click(screen.getByRole("button", { name: translations.native_material_edit_save.zh }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(converterApi.convertBatch).not.toHaveBeenCalled();
    await useConverterStore.getState().submitBatch();
    expect(converterApi.convertBatch).toHaveBeenCalledWith(expect.any(Array), expect.objectContaining({ external_spool_material: blue }));
    expect(singleParams().external_spool_material).toBe(blue);
    expect(exportConverterRecipe(useConverterStore.getState(), useSettingsStore.getState()).device.external_spool_material).toBe(blue);
    expect(collectBugReportContext()).toMatchObject({
      external_spool_material: blue, advanced_params: { generation: { external_spool_material: blue } },
    });

    useConverterStore.setState({ selectedMaterialDirNames: ["ocean", "ivory"] });
    expect(singleParams().external_spool_material).toBe(blue);
    useConverterStore.setState({ selectedMaterialDirNames: ["silver", "ocean"] });
    expect(singleParams()).not.toHaveProperty("external_spool_material");
    useConverterStore.setState({ selectedMaterialDirNames: ["ivory", "ocean"] });
    useSettingsStore.getState().setSlicerSoftware("OrcaSlicer");
    expect(singleParams()).not.toHaveProperty("external_spool_material");
    useSettingsStore.getState().setSlicerSoftware("BambuStudio");
    expect(singleParams().external_spool_material).toBe(blue);
    useSettingsStore.getState().setCustom3mfTemplateId("imported");
    expect(singleParams()).not.toHaveProperty("external_spool_material");
    useSettingsStore.getState().setCustom3mfTemplateId(null);
    useSettingsStore.getState().setPrinterModel("bambu-h2d");
    expect(singleParams()).not.toHaveProperty("external_spool_material");
  });

  it.each([{ names: [white] }, { names: [white, blue, blue] }])("corrects a removed or ambiguous spool before exporting $names", async ({ names }) => {
    await useConverterStore.getState().openNativeMaterialSelection();
    await useConverterStore.getState().applyNativeMaterialSelection({}, "pei", blue);
    vi.mocked(converterApi.fetchExportMaterialSelection).mockResolvedValue(selection(names));
    await useConverterStore.getState().submitBatch();
    expect(converterApi.convertBatch).not.toHaveBeenCalled();
    render(<I18nProvider><NativeMaterialSelectionDialog /></I18nProvider>);
    expect(screen.getByText(translations.native_material_external_spool_missing.zh.replace("{material}", blue))).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: translations.native_material_apply.zh }));
    await waitFor(() => expect(converterApi.convertBatch).toHaveBeenCalledOnce());
    expect(vi.mocked(converterApi.convertBatch).mock.calls[0][1]).not.toHaveProperty("external_spool_material");
  });
});
