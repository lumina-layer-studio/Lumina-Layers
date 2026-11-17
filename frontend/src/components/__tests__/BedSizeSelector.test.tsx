import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { I18nProvider } from "../../i18n/context";
import { translations } from "../../i18n/translations";
import { DEFAULT_STATE, useConverterStore } from "../../stores/converter";
import {
  DEFAULT_SETTINGS,
  useSettingsStore,
} from "../../stores/settingsStore";
import { useWidgetStore } from "../../stores/widgetStore";
import BedSizeSelector from "../sections/BedSizeSelector";

vi.mock("../../api/system", async (original) => ({
  ...await original<typeof import("../../api/system")>(),
  getSlicers: vi.fn().mockResolvedValue([{ id: "BambuStudio", display_name: "Bambu Studio" }]),
  getPrinters: vi.fn().mockResolvedValue([{
    id: "bambu-h2d", display_name: "Bambu Lab H2D", brand: "Bambu Lab", bed_width: 350, bed_depth: 320,
    supported_nozzle_sizes: ["0.2", "0.4"], supported_slicers: ["BambuStudio"],
    device_profiles: [{ device_profile_id: "BambuStudio:bbl:bambu-lab-h2d:0.2", machine_profile_id: "bambu-h2d", slicer_id: "BambuStudio", nozzle_size: "0.2", supported: true }],
  }]),
}));

function renderSelector() {
  return render(
    <I18nProvider>
      <BedSizeSelector />
    </I18nProvider>,
  );
}

describe("BedSizeSelector printer context", () => {
  beforeEach(() => {
    useSettingsStore.setState({
      ...DEFAULT_SETTINGS,
      language: "zh",
      printerModel: "bambu-p1s",
    });
    useConverterStore.setState({
      ...DEFAULT_STATE,
      bed_label: "Bambu Lab P1S",
      bedSizes: [
        {
          label: "Bambu Lab P1S",
          width_mm: 256,
          height_mm: 256,
          is_default: false,
          printer_id: "bambu-p1s",
        },
      ],
      bedSizesLoading: false,
    });
    useWidgetStore.setState({ activeTab: "converter" });
  });

  it("distinguishes the LUT brand from the configured printer bed", () => {
    expect(translations.basic_lut_manufacturer_label).toEqual({
      zh: "选择LUT",
      en: "Select LUT",
    });

    renderSelector();

    expect(screen.getByText("打印机热床")).toBeInTheDocument();
    expect(
      screen.getByText("Bambu Lab P1S · 256×256 毫米"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "工程设备设置" }),
    ).toBeInTheDocument();
  });

  it("does not repeat a custom bed label after localizing the unit", () => {
    useConverterStore.setState({
      bed_label: "256×256 mm",
      bedSizes: [
        {
          label: "256×256 mm",
          width_mm: 256,
          height_mm: 256,
          is_default: true,
          printer_id: null,
        },
      ],
    });

    renderSelector();

    expect(screen.getByText("256×256 mm")).toBeInTheDocument();
    expect(
      screen.queryByText("256×256 mm · 256×256 毫米"),
    ).not.toBeInTheDocument();
  });

  it("edits the project machine in place without changing daily defaults", async () => {
    renderSelector();

    fireEvent.click(
      screen.getByRole("button", { name: "工程设备设置" }),
    );

    const machine = await screen.findByTestId("machine-adapter-nozzle-bambu-h2d-0_2");
    await waitFor(() => expect(machine).toBeEnabled());
    fireEvent.click(machine);
    expect(useWidgetStore.getState().activeTab).toBe("converter");
    expect(useSettingsStore.getState().printerModel).toBe("bambu-p1s");
    expect(useConverterStore.getState().projectSettings).toMatchObject({ printerModel: "bambu-h2d", nozzleSize: "0.2" });
  });
});
