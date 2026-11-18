import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import LutLibraryPanel from "../components/LutLibraryPanel";
import { fetchLutDetailsCatalog, uploadLocalLut } from "../api/lut";

vi.mock("../api/lut", () => ({
  fetchLutDetails: vi.fn(),
  fetchLutDetailsCatalog: vi.fn(),
  uploadLocalLut: vi.fn(),
}));

describe("LutLibraryPanel", () => {
  it("distinguishes retained versions of the same LUT without renaming either resource", async () => {
    const baseline = await fetchLutDetailsCatalog();
    const item = baseline.groups[0].items[0];
    vi.mocked(fetchLutDetailsCatalog).mockResolvedValue({ groups: [{ manufacturer: "Cloud", items: [
      { ...item, local_version: { current: true, installed_at: "2026-11-15T03:00:00Z" } },
      { ...item, path: "Cloud/_revisions/previous.json", local_version: { current: false, installed_at: "2026-11-01T03:00:00Z" } },
    ] }] });
    render(<LutLibraryPanel />);
    fireEvent.change(await screen.findByRole("searchbox"), { target: { value: "Simulated" } });
    const cards = await screen.findAllByTestId("lut-library-card");
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveTextContent("本地当前版本");
    expect(cards[1]).toHaveTextContent("历史版本");
    expect(cards[1]).toHaveTextContent(/2026.*11.*01/);
  });

  it("retains the shared folder heading and shows the individual maker and original name for a SKU match", async () => {
    const base = { manufacturer: "Cloud", material_type: "PLA", color_mode: "4-Color", source_kind: "legacy_lookup",
      manufacturer_source: "folder", material_source: "folder", search_tokens: [] };
    vi.mocked(fetchLutDetailsCatalog).mockResolvedValue({ groups: [{ manufacturer: "Cloud", items: [
      { ...base, path: "Cloud/official/a.json", name: "a.json", display: { name: "Original table", manufacturer: "Sailner",
        market_names: { CN: "深红色表", INTL: "Garnet Table" }, sku: "SN-L10" } },
      { ...base, path: "Cloud/official/b.json", name: "b.json", display: { manufacturer: "Bambu Lab" } },
    ] }] });
    render(<LutLibraryPanel />);
    await screen.findByText("Cloud");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "SN-L10" } });
    expect(screen.getByText("Cloud")).toBeInTheDocument();
    const card = screen.getByTestId("lut-library-card");
    expect(card).toHaveTextContent("赛纳");
    expect(card).toHaveTextContent("深红色表");
    fireEvent.click(card);
    const detail = screen.getByTestId("lut-library-details");
    expect(detail).toHaveTextContent("Original table");
    expect(detail).toHaveTextContent("Cloud/official/a.json");
    expect(detail).toHaveTextContent("SN-L10");
  });

  it("keeps the last local catalog when refresh fails", async () => {
    render(<LutLibraryPanel />);
    await screen.findByText("2个 LUT · 2个品牌");
    fireEvent.click(screen.getByRole("button", { name: "全部展开" }));
    vi.mocked(fetchLutDetailsCatalog).mockRejectedValueOnce(new Error("offline"));
    fireEvent.click(screen.getByRole("button", { name: /刷新|Refresh/i }));
    await screen.findByTestId("lut-library-error");
    expect(screen.getAllByTestId("lut-library-card")).toHaveLength(2);
    expect(screen.queryByTestId("resource-library-empty")).not.toBeInTheDocument();
  });

  it("offers public resources only for a genuinely empty library", async () => {
    vi.mocked(fetchLutDetailsCatalog).mockResolvedValue({ groups: [] });
    render(<LutLibraryPanel />);
    expect(await screen.findByRole("button", { name: "去云端找 LUT" })).toBeInTheDocument();
  });

  it("distinguishes a search with no matches from an empty library", async () => {
    render(<LutLibraryPanel />);
    await screen.findByText("2个 LUT · 2个品牌");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "not-a-lut" } });
    expect(await screen.findByText("没有符合筛选条件的资源。" )).toBeInTheDocument();
    expect(screen.queryByTestId("resource-library-empty")).not.toBeInTheDocument();
  });
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.removeItem("lut-library-pins");
    localStorage.removeItem("lut-library-order");
    vi.mocked(fetchLutDetailsCatalog).mockResolvedValue({
      groups: [
        {
          manufacturer: "Cloud",
          items: [
            {
              name: "Cloud - Simulated - local_simulated_lut",
              path: "lut-preset/Cloud/Simulated/local_simulated_lut.json",
              color_mode: "4-Color (RYBW)",
              source_kind: "legacy_lookup",
              manufacturer: "Cloud",
              material_type: "Simulated",
              manufacturer_source: "folder",
              material_source: "folder",
              search_tokens: ["cloud", "simulated", "local"],
            },
          ],
        },
        {
          manufacturer: "Custom",
          items: [
            {
              name: "Custom - uploaded_lut",
              path: "lut-preset/Custom/uploaded_lut.json",
              color_mode: "6-Color",
              source_kind: "legacy_lookup",
              manufacturer: "Custom",
              material_type: "uploaded",
              manufacturer_source: "folder",
              material_source: "folder",
              search_tokens: ["custom", "uploaded"],
            },
          ],
        },
      ],
    });
    vi.mocked(uploadLocalLut).mockResolvedValue({
      status: "ok",
      message: "LUT uploaded",
      name: "Custom - uploaded_lut",
    });
  });

  it("renders a searchable grouped library and restores collapsed state", async () => {
    render(<LutLibraryPanel />);

    expect(await screen.findByTestId("lut-library-panel")).toBeInTheDocument();
    await screen.findByText("2个 LUT · 2个品牌");
    expect(screen.queryByTestId("lut-library-card")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "全部展开" }));
    expect(screen.getAllByTestId("lut-library-card")).toHaveLength(2);

    fireEvent.change(screen.getByTestId("lut-library-search-input"), {
      target: { value: "simulated" },
    });

    await waitFor(() => {
      expect(screen.getAllByTestId("lut-library-card")).toHaveLength(1);
    });
    expect(within(screen.getByTestId("lut-library-card")).getByText("Cloud - Simulated - local_simulated_lut")).toBeInTheDocument();
    expect(screen.getByText("1个 LUT · 1个品牌")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("lut-library-search-input"), { target: { value: "" } });
    expect(screen.getAllByTestId("lut-library-card")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "全部收起" }));
    fireEvent.change(screen.getByTestId("lut-library-search-input"), { target: { value: "6-color" } });
    expect(screen.getAllByTestId("lut-library-card")).toHaveLength(1);
    fireEvent.change(screen.getByTestId("lut-library-search-input"), { target: { value: "" } });
    expect(screen.queryByTestId("lut-library-card")).not.toBeInTheDocument();

  });

  it("imports a LUT file and refreshes the catalog", async () => {
    render(<LutLibraryPanel />);

    expect(await screen.findByTestId("lut-library-panel")).toBeInTheDocument();
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['{"color_mode":"4-Color (RYBW)","entries":[]}'], "new_lut.json", {
      type: "application/json",
    });

    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(uploadLocalLut).toHaveBeenCalledWith(file);
    });
    expect(fetchLutDetailsCatalog).toHaveBeenCalledTimes(2);
    expect(await screen.findByTestId("lut-library-success")).toHaveTextContent("LUT uploaded");
  });

  it("remembers pinned groups and their order and keeps detail switching in the library", async () => {
    const view = render(<LutLibraryPanel />);
    await screen.findByText("2个 LUT · 2个品牌");
    fireEvent.click(screen.getByRole("button", { name: "固定展开 Custom" }));
    fireEvent.keyDown(screen.getByRole("button", { name: /Custom.*1/ }), { key: "ArrowUp" });
    expect(screen.getAllByTestId("lut-library-brand-group")[0]).toHaveAttribute("data-brand", "Custom");
    fireEvent.click(screen.getByRole("button", { name: "全部收起" }));
    view.unmount();
    render(<LutLibraryPanel />);
    await screen.findByText("2个 LUT · 2个品牌");
    expect(screen.getAllByTestId("lut-library-brand-group")[0]).toHaveAttribute("data-brand", "Custom");
    expect(screen.getAllByTestId("lut-library-card")).toHaveLength(1);
    const card = screen.getByTestId("lut-library-card");
    fireEvent.click(card);
    expect(screen.getByTestId("lut-library-details")).toBeInTheDocument();
    fireEvent.click(card);
    expect(screen.getByTestId("lut-library-details")).toHaveAttribute("inert");
    await waitFor(() => expect(screen.queryByTestId("lut-library-details")).not.toBeInTheDocument());
    expect(card).toHaveFocus();
    fireEvent.click(card);
    fireEvent.keyDown(screen.getByTestId("lut-library-details"), { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("lut-library-details")).not.toBeInTheDocument());
    expect(card).toHaveFocus();
  });

  it("refreshes the details catalog before opening a library LUT", async () => {
    render(<LutLibraryPanel />);

    await screen.findByText("2个 LUT · 2个品牌");
    fireEvent.click(screen.getByRole("button", { name: "全部展开" }));
    const [card] = screen.getAllByTestId("lut-library-card");
    fireEvent.click(card);
    const details = screen.getByTestId("lut-library-details");
    expect(within(details).getByText("lut-preset/Cloud/Simulated/local_simulated_lut.json")).toBeInTheDocument();
    expect(fetchLutDetailsCatalog).toHaveBeenCalledTimes(1);
    fireEvent.click(within(details).getByRole("button", { name: "查看完整 LUT 分析" }));

    await waitFor(() => {
      expect(fetchLutDetailsCatalog).toHaveBeenCalledTimes(2);
    });
  });
});
