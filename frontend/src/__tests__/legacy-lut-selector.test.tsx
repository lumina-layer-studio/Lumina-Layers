import { useState } from "react";
import "./communityTestMocks";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within, waitFor } from "@testing-library/react";
import LegacyLutSelector from "../components/sections/LegacyLutSelector";
import * as communityApi from "../api/community";
import * as communityAccounts from "../api/contributions";
import { useCommunityStore } from "../stores/communityStore";
import { ResourceActivityActions } from "../components/ui/ResourceActivity";

const labels = {
  manufacturer: "Brand",
  manufacturerPlaceholder: "Select a brand",
  lut: "LUT",
  lutPlaceholder: "Select a LUT",
  refreshTooltip: "Reload LUT directory",
  upload: "Upload",
  loadingHint: "Loading LUT catalog",
  noBrandHint: "Pick a brand first",
  selectedCount: "Selected",
  brandInfo: "Brand Info",
  materialType: "Material Type",
  vendor: "Vendor",
  database: "Databases",
  databasePlaceholder: "No databases selected",
  dialogTitle: "Choose LUT",
  dialogSearchPlaceholder: "Search LUTs…",
  dialogAllGroups: "All color modes",
  dialogNoMatch: "No matching LUTs",
  dialogDeselectAll: "Deselect all",
  dialogConfirm: "Confirm",
  dialogCancel: "Cancel",
  openPicker: "Choose LUT databases…",
  change: "Change",
  selectionSummary: "{count} LUTs selected",
  moreSelected: "+{count} more",
};

const manufacturerOptions = [
  { label: "Brand A", value: "Brand A" },
  { label: "Brand B", value: "Brand B" },
];

const groupedLutOptions = [
  {
    label: "4-Color",
    options: [
      { label: "A 4C", value: "a4" },
      { label: "B 4C", value: "b4" },
    ],
  },
  {
    label: "8-Color",
    options: [{ label: "A 8C", value: "a8" }],
  },
];

function renderSelector(overrides = {}) {
  return render(
    <LegacyLutSelector
      manufacturer="Brand A"
      lutName="a4"
      manufacturerOptions={manufacturerOptions}
      groupedLutOptions={groupedLutOptions}
      onManufacturerChange={() => {}}
      onLutChange={() => {}}
      onRefresh={() => {}}
      onUploadClick={() => {}}
      labels={labels}
      {...overrides}
    />,
  );
}

describe("LegacyLutSelector", () => {
  it("keeps version labels when forwarding local LUT choices into the conversion picker", async () => {
    const versions = [
      { value: "a4", label: "Same LUT", brand: "Brand A", mode: "4-Color", localVersion: { current: true } },
      { value: "b4", label: "Same LUT", brand: "Brand A", mode: "4-Color", localVersion: { current: false, installed_at: "2026-11-01T03:00:00Z" } },
    ];
    renderSelector({ allLutOptions: versions, groupedLutOptions: [{ label: "4-Color", options: versions }] });
    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    const dialog = screen.getByRole("dialog", { name: "Choose LUT" });
    expect(within(dialog).getByText("本地当前版本")).toBeInTheDocument();
    expect(within(dialog).getByText("历史版本")).toBeInTheDocument();
    fireEvent.change(within(dialog).getByRole("searchbox"), { target: { value: "Same LUT" } });
    expect(within(dialog).getByText("本地当前版本")).toBeInTheDocument();
    expect(within(dialog).getByText("历史版本")).toBeInTheDocument();
  });

  it("shares account favorites across brands and cloud cards without changing selected LUTs", async () => {
    const connection = { state: "connected" as const, subject: "maker", web_url: "http://localhost:8018" };
    const ref = { resource_id: "lut-b", revision_id: "rev-b", content_hash: "b4" };
    const stats = { ...ref, likes: 0, saves: 1, downloads: 0, liked: false, saved: true, downloaded: false, revisions: [ref] };
    vi.mocked(communityAccounts.getContributionConnection).mockResolvedValue(connection);
    vi.mocked(communityApi.fetchLocalResourceReferences).mockResolvedValue({ b4: ref });
    vi.mocked(communityApi.fetchMyResourceActivity).mockResolvedValue({ items: [stats], subject: "maker" });
    vi.mocked(communityApi.fetchResourceStats).mockResolvedValue({ items: [stats], subject: "maker" });
    vi.mocked(communityApi.setResourceActivity).mockResolvedValue({ item: { ...stats, saved: false, saves: 0 }, subject: "maker" });
    useCommunityStore.getState().acceptConnection(connection);
    const confirm = vi.fn();
    renderSelector({ onLutSelectionChange: confirm,
      allLutOptions: [
        { value: "a4", label: "A 4C", brand: "Brand A", mode: "4-Color" },
        { value: "b4", label: "B 4C", brand: "Brand B", mode: "4-Color" },
      ],
    });
    render(<ResourceActivityActions kind="luts" resource={ref} />);
    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    await waitFor(() => expect(screen.getAllByRole("button", { name: "取消账号收藏" })).toHaveLength(2));
    fireEvent.click(screen.getByRole("combobox", { name: "账号资源筛选" }));
    fireEvent.click(screen.getByRole("option", { name: "我的收藏" }));
    const dialog = screen.getByRole("dialog", { name: "Choose LUT" });
    expect(within(dialog).getByRole("checkbox", { name: /B 4C/ })).toBeVisible();
    expect(within(dialog).queryByRole("checkbox", { name: /A 4C/ })).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "取消账号收藏" }));
    await waitFor(() => expect(within(dialog).queryByRole("checkbox", { name: /B 4C/ })).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "收藏到账号" })).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(confirm).toHaveBeenCalledWith(["a4"]);
  });

  it("searches international names and SKU without changing the staged LUT value", () => {
    const confirm = vi.fn();
    renderSelector({
      lutName: "",
      groupedLutOptions: [{ label: "4-Color", options: [{ value: "archive/path-key", label: "作者色表", brand: "赛纳",
        display: { market_names: { CN: "深红色表", INTL: "Garnet LUT" }, sku: "SN-L07" } }] }],
      onLutSelectionChange: confirm,
    });
    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    for (const query of ["Garnet LUT", "SN-L07", "作者色表"]) {
      fireEvent.change(screen.getByRole("searchbox"), { target: { value: query } });
      expect(screen.getByRole("checkbox", { name: /深红色表/ })).not.toHaveTextContent("作者色表");
    }
    fireEvent.click(screen.getByRole("checkbox", { name: /深红色表/ }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(confirm).toHaveBeenCalledWith(["archive/path-key"]);
  });

  it("can find and select a SKU before choosing its manufacturer", () => {
    const confirm = vi.fn();
    renderSelector({ manufacturer: "", lutName: "", groupedLutOptions: [], onLutSelectionChange: confirm,
      allLutOptions: [{ value: "stable/path", label: "原始色表", brand: "赛纳", mode: "4-Color",
        display: { localized_names: { zh: "深红色表" }, sku: "SN-404" } }] });
    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "SN-404" } });
    const result = screen.getByRole("checkbox", { name: /深红色表/ });
    expect(result).toHaveTextContent("赛纳");
    fireEvent.click(result);
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(confirm).toHaveBeenCalledWith(["stable/path"]);
  });
  it("keeps selected LUTs staged when returning from the public library", () => {
    renderSelector();
    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    fireEvent.click(screen.getByRole("checkbox", { name: /B 4C/ }));
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "4C" } });
    fireEvent.click(screen.getByRole("button", { name: "去公开库查找" }));
    expect(screen.getByRole("searchbox")).toHaveValue("4C");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "返回本地选择" }));
    expect(screen.getByRole("searchbox")).toHaveValue("4");
    expect(screen.getByRole("checkbox", { name: /A 4C/ })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("checkbox", { name: /B 4C/ })).toHaveAttribute("aria-checked", "true");
  });
  it("keeps refresh inside the picker dialog", () => {
    const onRefresh = vi.fn();
    renderSelector({ onRefresh });

    // The trigger button opens the picker dialog
    expect(screen.getByTestId("lut-picker-trigger")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reload LUT directory" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Reload LUT directory" }));
    expect(onRefresh).toHaveBeenCalledOnce();
  });

  it("shows selected metadata and color mode inside the trigger", () => {
    renderSelector({
      allLutOptions: [{ label: "A 4C", value: "a4", brand: "Brand A", materialType: "PETG" }],
      colorModeSummary: <span>4-Color (RYBW)</span>,
    });
    const trigger = screen.getByTestId("lut-picker-trigger");
    expect(trigger).toHaveTextContent("Brand A · PETG");
    expect(trigger).toHaveTextContent("4-Color (RYBW)");
    expect(trigger).toHaveTextContent("Change");
    expect(trigger).not.toHaveTextContent("Selected: 1");
  });

  it("shows the selected LUT name on the trigger", () => {
    renderSelector({ selectedLutNames: ["a4"] });
    const trigger = screen.getByTestId("lut-picker-trigger");
    expect(trigger).toHaveTextContent("A 4C");
  });

  it("summarizes multiple LUTs without expanding the full list", () => {
    renderSelector({ selectedLutNames: ["a4", "b4", "a8"] });
    const trigger = screen.getByTestId("lut-picker-trigger");
    // Only the first name remains visible; the dialog retains the full selection.
    expect(trigger).toHaveTextContent("A 4C");
    expect(trigger).not.toHaveTextContent("B 4C");
    expect(trigger).toHaveTextContent("3 LUTs selected");
    expect(trigger).toHaveTextContent("+2 more");
  });

  it("shows the LUT placeholder when brand is selected but no LUT is chosen", () => {
    renderSelector({ lutName: "", selectedLutNames: [] });
    const trigger = screen.getByTestId("lut-picker-trigger");
    expect(trigger).toHaveTextContent("Select a LUT");
  });

  it("shows the brand placeholder when no brand is selected", () => {
    renderSelector({ manufacturer: "", lutName: "", selectedLutNames: [] });
    const trigger = screen.getByTestId("lut-picker-trigger");
    expect(trigger).toHaveTextContent("Select a brand");
  });

  it("shows loading hint inside the dialog when loading", () => {
    renderSelector({ loading: true });

    // Open the dialog
    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Loading LUT catalog")).toBeInTheDocument();
  });

  it("opens the picker dialog and shows brand sidebar", () => {
    renderSelector();

    fireEvent.click(screen.getByTestId("lut-picker-trigger"));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByTestId("lut-picker-brand-sidebar")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Brand A" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Brand B" })).toBeInTheDocument();
  });

  it("shows all LUT options in the picker dialog", () => {
    renderSelector();

    fireEvent.click(screen.getByTestId("lut-picker-trigger"));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("A 4C")).toBeInTheDocument();
    expect(within(dialog).getByText("B 4C")).toBeInTheDocument();
    expect(within(dialog).getByText("A 8C")).toBeInTheDocument();
  });

  it("emits manufacturer changes when a brand is clicked in the sidebar", () => {
    const onManufacturerChange = vi.fn();
    renderSelector({ onManufacturerChange });

    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    fireEvent.click(screen.getByRole("button", { name: "Brand B" }));

    expect(onManufacturerChange).toHaveBeenCalledWith("Brand B");
  });

  it("emits multi-selected LUT names in selection order when confirm is clicked", () => {
    const onLutSelectionChange = vi.fn();
    renderSelector({ selectedLutNames: ["a4"], onLutSelectionChange });

    fireEvent.click(screen.getByTestId("lut-picker-trigger"));

    const dialog = screen.getByRole("dialog");
    // Toggle B 4C on
    const b4cOption = within(dialog)
      .getAllByRole("checkbox")
      .find((el) => el.textContent?.includes("B 4C"));
    fireEvent.click(b4cOption!);

    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));

    // a4 was pre-staged, b4 was added → grouped order a4, b4
    expect(onLutSelectionChange).toHaveBeenCalledWith(["a4", "b4"]);
  });

  it("deselects a LUT when toggled off in the dialog", () => {
    const onLutSelectionChange = vi.fn();
    renderSelector({ selectedLutNames: ["a4", "b4"], onLutSelectionChange });

    fireEvent.click(screen.getByTestId("lut-picker-trigger"));

    const dialog = screen.getByRole("dialog");
    const b4cOption = within(dialog)
      .getAllByRole("checkbox")
      .find((el) => el.textContent?.includes("B 4C"));
    fireEvent.click(b4cOption!);
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));

    expect(onLutSelectionChange).toHaveBeenCalledWith(["a4"]);
  });

  it("retains cross-brand selections through navigation, confirm and reopening", () => {
    const onLutSelectionChange = vi.fn();
    const onManufacturerChange = vi.fn();

    // Each brand exposes its own list; applied names change only on confirm.
    function Harness() {
      const [manufacturer, setManufacturer] = useState("Brand A");
      const [names, setNames] = useState<string[]>(["a4"]);
      const grouped = manufacturer === "Brand A"
        ? [{ label: "4-Color", options: [{ label: "A 4C", value: "a4" }] }]
        : [{ label: "4-Color", options: [{ label: "B 4C", value: "b4" }] }];
      return (
        <LegacyLutSelector
          manufacturer={manufacturer}
          lutName={names[0] ?? ""}
          selectedLutNames={names}
          manufacturerOptions={manufacturerOptions}
          groupedLutOptions={grouped}
          allLutOptions={groupedLutOptions.flatMap((group) => group.options)}
          onManufacturerChange={(value) => {
            setManufacturer(value);
            onManufacturerChange(value);
          }}
          onLutChange={() => {}}
          onLutSelectionChange={(next) => {
            setNames(next);
            onLutSelectionChange(next);
          }}
          onRefresh={() => {}}
          onUploadClick={() => {}}
          labels={labels}
        />
      );
    }

    render(<Harness />);
    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    const dialog = screen.getByRole("dialog");

    // Brand A's LUT arrives pre-staged from the current selection.
    expect(
      within(dialog).getAllByRole("checkbox")[0],
    ).toHaveAttribute("aria-checked", "true");

    fireEvent.click(within(dialog).getByRole("button", { name: "Brand B" }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /B 4C/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Brand A" }));
    expect(within(dialog).getByRole("checkbox", { name: /A 4C/ }))
      .toHaveAttribute("aria-checked", "true");
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm" }));

    expect(onLutSelectionChange).toHaveBeenCalledWith(["a4", "b4"]);
    expect(screen.getByTestId("lut-picker-trigger")).toHaveTextContent("2 LUTs selected");
    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    const reopened = screen.getByRole("dialog");
    fireEvent.click(within(reopened).getByRole("button", { name: "Brand B" }));
    expect(within(reopened).getByRole("checkbox", { name: /B 4C/ }))
      .toHaveAttribute("aria-checked", "true");
    fireEvent.click(within(reopened).getByRole("checkbox", { name: /B 4C/ }));
    fireEvent.click(within(reopened).getByRole("button", { name: "Confirm" }));
    expect(onLutSelectionChange).toHaveBeenLastCalledWith(["a4"]);
  });

  it("cancels without committing when Escape is pressed", () => {
    const onLutSelectionChange = vi.fn();
    renderSelector({ selectedLutNames: ["a4"], onLutSelectionChange });

    fireEvent.click(screen.getByTestId("lut-picker-trigger"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onLutSelectionChange).not.toHaveBeenCalled();
  });

  it("shows the 'no brand' hint inside the dialog when no brand is selected", () => {
    renderSelector({ manufacturer: "", lutName: "" });

    fireEvent.click(screen.getByTestId("lut-picker-trigger"));

    expect(screen.getByText("Pick a brand first")).toBeInTheDocument();
  });

  it("shows the sr-only live region with selected count", () => {
    renderSelector({ selectedLutNames: ["a4", "b4"] });

    // The sr-only region specifically
    const liveRegion = document.querySelector('[aria-live="polite"].sr-only');
    expect(liveRegion).not.toBeNull();
    expect(liveRegion!.textContent).toMatch(/2/);
  });
});
import "./communityTestMocks";
