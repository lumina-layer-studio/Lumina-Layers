import { beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import MaterialLibraryPanel from "../components/MaterialLibraryPanel";
import {
  deleteGradientCardMaterial,
  exportGradientCardMaterials,
  importGradientCardMaterials,
  listGradientCardMaterials,
  updateGradientCardMaterial,
} from "../api/extractor";
import { useSingleStageStore } from "../stores/singleStageStore";
import { useWidgetStore } from "../stores/widgetStore";

vi.mock("../api/extractor", () => ({
  colorcheckerConfirm: vi.fn(),
  colorcheckerRelease: vi.fn(),
  colorcheckerTouch: vi.fn(() => Promise.resolve()),
  deleteGradientCardMaterial: vi.fn(),
  exportGradientCardMaterials: vi.fn(),
  importGradientCardMaterials: vi.fn(),
  listGradientCardMaterials: vi.fn(),
  updateGradientCardMaterial: vi.fn(),
}));

describe("MaterialLibraryPanel", () => {
  it("preserves local materials after a failed refresh and never reports a false empty library", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({ status: "ok", message: "ok", materials: [{ material_name: "Kept PLA", directory_name: "kept", material_file_url: "/materials/kept.json", estimated_rgb: [1, 2, 3] }] });
    render(<MaterialLibraryPanel />);
    fireEvent.click(await screen.findByTestId("material-library-brand-group-toggle"));
    expect(screen.getByText("Kept PLA")).toBeInTheDocument();
    vi.mocked(listGradientCardMaterials).mockRejectedValueOnce(new Error("offline"));
    fireEvent.click(screen.getByRole("button", { name: /刷新|Refresh/ }));
    await screen.findByTestId("material-library-error");
    expect(screen.getByText("Kept PLA")).toBeInTheDocument();
    expect(screen.queryByTestId("resource-library-empty")).not.toBeInTheDocument();
  });
  const expandAllMaterialLibraryGroups = () => {
    for (const toggle of screen.getAllByTestId("material-library-brand-group-toggle")) {
      if (toggle.getAttribute("aria-expanded") === "false") {
        fireEvent.click(toggle);
      }
    }
  };

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.removeItem("lumina-material-library-pinned-brands");
    localStorage.removeItem("lumina-material-library-brand-order");
    useWidgetStore.setState({ activeTab: "material-library" });
    useSingleStageStore.setState({
      materialName: "",
      verificationTargetDirectoryName: null,
      verificationTargetCount: 0,
    });
  });

  it("renders saved materials from the material library API", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          material_type: "PETG",
          directory_name: "pla-basic",
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          material_file_url: "/api/files/material-json",
          stage_a_params_url: "/api/files/stage-a-json",
          estimated_rgb: [100, 120, 140],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
          verification_history: [
            {
              verification_index: 1,
              captured_at: "2026-04-16T10:00:00Z",
              mean_delta_e: 1.5,
              rmse_linear: 0.015,
              estimated_rgb: [96, 112, 132],
              estimated_k: [1.1, 1.2, 1.3],
              e_values: [0.21, 0.31, 0.41],
              k_values: [1.1, 1.2, 1.3],
              white_c0_values: [0.91, 0.92, 0.93],
              black_c0_values: [0.11, 0.12, 0.13],
              white_detected_orientation: "identity",
              black_detected_orientation: "rotate_90_cw",
            },
          ],
          sync_material_id: "mat_official",
          sync_revision_id: "rev_official",
          sync_channel: "official",
          sync_official: true,
        },
      ],
    });

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("material-library-panel")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByTestId("material-library-brand-group-toggle")).toHaveAttribute("aria-expanded", "false");
    });
    expect(screen.queryByText("PLA Basic")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("material-library-brand-group-toggle"));
    expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    expect(screen.queryByText(/下载 material\.json|download material\.json/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/下载 stage_A_parameters\.json|download stage_a_parameters\.json/i)).not.toBeInTheDocument();
    expect(screen.getAllByTestId("material-library-item")).toHaveLength(1);
    expect(screen.getByText("PETG")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /编辑信息|edit details/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /导出所选耗材|export selected/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByTestId("material-library-item")[0]);
    expect(screen.getByTestId("material-library-official-badge")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("material-library-item"));
    expect(screen.getByTestId("material-library-details")).toHaveAttribute("inert");
    await waitFor(() => expect(screen.queryByTestId("material-library-details")).not.toBeInTheDocument());
    fireEvent.click(screen.getByTestId("material-library-item"));
    fireEvent.keyDown(screen.getByTestId("material-library-details"), { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("material-library-details")).not.toBeInTheDocument());
    expect(screen.getByTestId("material-library-item")).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: /选择耗材|select materials/i }));
    fireEvent.click(screen.getByTestId("material-library-item"));
    expect(screen.getByTestId("material-library-item")).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByTestId("material-library-details")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /完成选择|done selecting/i }));
    expect(screen.getByTestId("material-library-item")).not.toHaveAttribute("aria-pressed");
  });

  it("groups saved materials by brand without repeating brand tags on cards", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 4 saved materials",
      materials: [
        {
          material_name: "PLA Red",
          directory_name: "brand-a-red",
          brand: "Brand A",
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          material_file_url: "/api/files/material-json-a",
          stage_a_params_url: "/api/files/stage-a-json-a",
          estimated_rgb: [200, 30, 40],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
        {
          material_name: "PLA Blue",
          directory_name: "brand-b-blue",
          brand: "Brand B",
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          material_file_url: "/api/files/material-json-b",
          stage_a_params_url: "/api/files/stage-a-json-b",
          estimated_rgb: [30, 80, 200],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
        {
          material_name: "PLA Yellow",
          directory_name: "brand-a-yellow",
          brand: "Brand A",
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          material_file_url: "/api/files/material-json-c",
          stage_a_params_url: "/api/files/stage-a-json-c",
          estimated_rgb: [220, 180, 30],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
        {
          material_name: "PLA Natural",
          directory_name: "unassigned-natural",
          brand: null,
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          material_file_url: "/api/files/material-json-d",
          stage_a_params_url: "/api/files/stage-a-json-d",
          estimated_rgb: [220, 220, 210],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
      ],
    });

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getAllByTestId("material-library-brand-group")).toHaveLength(3);
    });

    let groups = screen.getAllByTestId("material-library-brand-group");
    expect(groups).toHaveLength(3);
    expect(groups.map((group) => group.getAttribute("data-brand"))).toEqual([
      "Brand A",
      "Brand B",
      "",
    ]);

    let firstGroupToggle = within(groups[0]).getByTestId("material-library-brand-group-toggle");
    let secondGroupToggle = within(groups[1]).getByTestId("material-library-brand-group-toggle");
    let unassignedToggle = within(groups[2]).getByTestId("material-library-brand-group-toggle");
    expect(firstGroupToggle).toHaveAttribute("aria-expanded", "false");
    expect(secondGroupToggle).toHaveAttribute("aria-expanded", "false");
    expect(unassignedToggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "全部展开" })).toBeEnabled();
    expect(within(groups[0]).queryByText("PLA Red")).not.toBeInTheDocument();

    const search = screen.getByRole("searchbox", { name: "搜索耗材名称、品牌、类型…" });
    fireEvent.change(search, { target: { value: "pla red" } });
    expect(screen.getAllByTestId("material-library-brand-group")).toHaveLength(1);
    expect(screen.getByText("PLA Red")).toBeInTheDocument();
    expect(screen.getByText("1种耗材 · 1个品牌")).toBeInTheDocument();
    fireEvent.change(search, { target: { value: "Brand A" } });
    expect(screen.getAllByTestId("material-library-item")).toHaveLength(2);
    fireEvent.change(search, { target: { value: "no-such-material" } });
    expect(screen.getByText("没有找到匹配的耗材，试试其他关键词。")).toBeInTheDocument();
    fireEvent.change(search, { target: { value: "" } });
    expect(screen.getAllByTestId("material-library-brand-group-toggle").every((toggle) => toggle.getAttribute("aria-expanded") === "false")).toBe(true);
    groups = screen.getAllByTestId("material-library-brand-group");
    [firstGroupToggle, secondGroupToggle, unassignedToggle] = screen.getAllByTestId("material-library-brand-group-toggle");

    fireEvent.click(screen.getByRole("button", { name: "全部展开" }));

    expect(within(groups[0]).getByText("PLA Red")).toBeInTheDocument();
    expect(within(groups[0]).getByText("PLA Yellow")).toBeInTheDocument();
    expect(within(groups[1]).getByText("PLA Blue")).toBeInTheDocument();
    expect(within(groups[2]).getByText("PLA Natural")).toBeInTheDocument();

    expect(screen.queryByTestId("material-library-brand-tag")).not.toBeInTheDocument();

    fireEvent.click(firstGroupToggle);
    expect(firstGroupToggle).toHaveAttribute("aria-expanded", "false");
    expect(within(groups[0]).queryByText("PLA Red")).not.toBeInTheDocument();
    expect(within(groups[0]).queryByText("PLA Yellow")).not.toBeInTheDocument();
    expect(within(groups[1]).getByText("PLA Blue")).toBeInTheDocument();

    fireEvent.click(firstGroupToggle);
    expect(firstGroupToggle).toHaveAttribute("aria-expanded", "true");
    expect(within(groups[0]).getByText("PLA Red")).toBeInTheDocument();
    expect(within(groups[0]).getByText("PLA Yellow")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "全部收起" }));
    for (const toggle of [firstGroupToggle, secondGroupToggle, unassignedToggle]) {
      expect(toggle).toHaveAttribute("aria-expanded", "false");
    }
    expect(screen.queryByTestId("material-library-item")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "全部展开" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "全部展开" }));
    for (const toggle of [firstGroupToggle, secondGroupToggle, unassignedToggle]) {
      expect(toggle).toHaveAttribute("aria-expanded", "true");
    }
    expect(within(groups[0]).getByText("2种")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "固定展开 Brand A" }));
    expect(screen.getByRole("button", { name: "取消固定 Brand A" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "全部收起" }));
    cleanup();
    render(<MaterialLibraryPanel />);
    await waitFor(() => expect(screen.getAllByTestId("material-library-brand-group")).toHaveLength(3));
    const restored = screen.getAllByTestId("material-library-brand-group-toggle");
    expect(restored[0]).toHaveAttribute("aria-expanded", "true");
    expect(restored[1]).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(screen.getByRole("button", { name: "取消固定 Brand A" }));
    cleanup();
    render(<MaterialLibraryPanel />);
    await waitFor(() => expect(screen.getAllByTestId("material-library-brand-group")).toHaveLength(3));
    expect(screen.getAllByTestId("material-library-brand-group-toggle")[0]).toHaveAttribute("aria-expanded", "false");
    const rectSpy = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      const group = this.closest('[data-testid="material-library-brand-group"]');
      const index = group ? screen.getAllByTestId("material-library-brand-group").indexOf(group as HTMLElement) : 0;
      return { x: 0, y: index * 80, left: 0, top: index * 80, right: 600, bottom: index * 80 + 40, width: 600, height: 40, toJSON: () => ({}) };
    });
    const originalPointerEvent = window.PointerEvent;
    class TestPointerEvent extends MouseEvent {
      pointerId = 1;
      isPrimary = true;
    }
    window.PointerEvent = TestPointerEvent as typeof PointerEvent;
    try {
      const brandBar = screen.getAllByTestId("material-library-brand-group-toggle")[1];
      fireEvent.pointerDown(brandBar, { clientX: 100, clientY: 100, button: 0 });
      fireEvent.pointerMove(document, { clientX: 100, clientY: 90 });
      await waitFor(() => expect(document.querySelector('[aria-hidden="true"] .material-library-group')).toBeInTheDocument());
      fireEvent.pointerMove(document, { clientX: 100, clientY: 20 });
      await waitFor(() => expect(screen.getAllByTestId("material-library-brand-group")[0].style.transform).not.toBe(""));
      fireEvent.pointerUp(document, { clientX: 100, clientY: 20 });
      // dnd-kit briefly suppresses the click emitted after a pointer drop.
      await new Promise((resolve) => setTimeout(resolve, 60));
    } finally {
      window.PointerEvent = originalPointerEvent;
      rectSpy.mockRestore();
    }
    expect(screen.getAllByTestId("material-library-brand-group").map((group) => group.getAttribute("data-brand"))).toEqual(["Brand B", "Brand A", ""]);
    cleanup();
    render(<MaterialLibraryPanel />);
    await waitFor(() => expect(screen.getAllByTestId("material-library-brand-group")).toHaveLength(3));
    expect(screen.getAllByTestId("material-library-brand-group")[0]).toHaveAttribute("data-brand", "Brand B");
    fireEvent.keyDown(screen.getAllByTestId("material-library-brand-group-toggle")[0], { key: "ArrowDown" });
    expect(screen.getAllByTestId("material-library-brand-group")[0]).toHaveAttribute("data-brand", "Brand A");
  });

  it("edits a saved material name and brand from the library", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "pla-basic",
          brand: null,
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          material_file_url: "/api/files/material-json",
          stage_a_params_url: "/api/files/stage-a-json",
          estimated_rgb: [100, 120, 140],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
      ],
    });
    vi.mocked(updateGradientCardMaterial).mockResolvedValue({
      status: "ok",
      message: "updated",
      material: {
        material_name: "PLA Matte",
        directory_name: "pla-basic",
        brand: "Bambu Lab",
        created_at: "2026-04-16T10:00:00Z",
        updated_at: "2026-04-17T11:00:00Z",
        material_file_url: "/api/files/material-json-updated",
        stage_a_params_url: "/api/files/stage-a-json-updated",
        estimated_rgb: [100, 120, 140],
        layer_height_mm: 0.04,
        mean_delta_e: 1.23,
        verification_count: 3,
        verification_history: [],
      },
    });

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("material-library-brand-group")).toBeInTheDocument();
    });

    expandAllMaterialLibraryGroups();

    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });

    fireEvent.click(screen.getAllByTestId("material-library-item")[0]);
    fireEvent.click(screen.getByRole("button", { name: /编辑信息|edit details/i }));

    expect(screen.getByTestId("material-library-edit-dialog")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("material-library-edit-name-input"), {
      target: { value: "PLA Matte" },
    });
    fireEvent.change(screen.getByTestId("material-library-edit-brand-input"), {
      target: { value: "Bambu Lab" },
    });
    fireEvent.click(screen.getByRole("button", { name: /保存修改|save changes/i }));

    await waitFor(() => {
      expect(updateGradientCardMaterial).toHaveBeenCalledWith("pla-basic", {
        materialName: "PLA Matte",
        brand: "Bambu Lab",
        estimatedRgb: [100, 120, 140],
      });
    });

    expandAllMaterialLibraryGroups();

    await waitFor(() => {
      expect(within(screen.getByTestId("material-library-details")).getByText("PLA Matte")).toBeInTheDocument();
    });
    expect(within(screen.getByTestId("material-library-details")).getByText(/拓竹 ·/)).toBeInTheDocument();
  });

  it("edits the display color via hex input from the library", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "pla-basic",
          brand: null,
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          material_file_url: "/api/files/material-json",
          stage_a_params_url: "/api/files/stage-a-json",
          estimated_rgb: [100, 120, 140],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
      ],
    });
    vi.mocked(updateGradientCardMaterial).mockResolvedValue({
      status: "ok",
      message: "updated",
      material: {
        material_name: "PLA Basic",
        directory_name: "pla-basic",
        brand: null,
        created_at: "2026-04-16T10:00:00Z",
        updated_at: "2026-04-17T11:00:00Z",
        material_file_url: "/api/files/material-json-updated",
        stage_a_params_url: "/api/files/stage-a-json-updated",
        estimated_rgb: [255, 128, 0],
        layer_height_mm: 0.04,
        mean_delta_e: 1.23,
        verification_count: 3,
        verification_history: [],
      },
    });

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("material-library-brand-group")).toBeInTheDocument();
    });

    expandAllMaterialLibraryGroups();

    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });

    fireEvent.click(screen.getAllByTestId("material-library-item")[0]);
    fireEvent.click(screen.getByRole("button", { name: /编辑信息|edit details/i }));

    const hexInput = screen.getByTestId("material-library-edit-color-hex-input") as HTMLInputElement;
    expect(hexInput.value.toUpperCase()).toBe("#64788C");

    fireEvent.change(hexInput, { target: { value: "#FF8000" } });

    const picker = screen.getByTestId("material-library-edit-color-picker") as HTMLInputElement;
    expect(picker.value.toLowerCase()).toBe("#ff8000");

    fireEvent.click(screen.getByRole("button", { name: /保存修改|save changes/i }));

    await waitFor(() => {
      expect(updateGradientCardMaterial).toHaveBeenCalledWith("pla-basic", {
        materialName: "PLA Basic",
        brand: null,
        estimatedRgb: [255, 128, 0],
      });
    });
  });

  it("rejects invalid hex input in the edit dialog", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "pla-basic",
          brand: null,
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          material_file_url: "/api/files/material-json",
          stage_a_params_url: "/api/files/stage-a-json",
          estimated_rgb: [100, 120, 140],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
      ],
    });

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("material-library-brand-group")).toBeInTheDocument();
    });

    expandAllMaterialLibraryGroups();

    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });

    fireEvent.click(screen.getAllByTestId("material-library-item")[0]);
    fireEvent.click(screen.getByRole("button", { name: /编辑信息|edit details/i }));

    const hexInput = screen.getByTestId("material-library-edit-color-hex-input") as HTMLInputElement;
    fireEvent.change(hexInput, { target: { value: "not-a-color" } });

    expect(screen.getByTestId("material-library-edit-color-hex-error")).toBeInTheDocument();
  });

  it("opens saved material verification history in a dialog", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "pla-basic",
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          material_file_url: "/api/files/material-json",
          stage_a_params_url: "/api/files/stage-a-json",
          estimated_rgb: [100, 120, 140],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
          verification_history: [
            {
              verification_index: 1,
              captured_at: "2026-04-16T10:00:00Z",
              mean_delta_e: 1.5,
              rmse_linear: 0.015,
              estimated_rgb: [96, 112, 132],
              estimated_k: [1.1, 1.2, 1.3],
              e_values: [0.21, 0.31, 0.41],
              k_values: [1.1, 1.2, 1.3],
              white_c0_values: [0.91, 0.92, 0.93],
              black_c0_values: [0.11, 0.12, 0.13],
              white_detected_orientation: "identity",
              black_detected_orientation: "rotate_90_cw",
            },
          ],
        },
      ],
    });

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("material-library-brand-group")).toBeInTheDocument();
    });

    expandAllMaterialLibraryGroups();

    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });

    fireEvent.click(screen.getAllByTestId("material-library-item")[0]);
    fireEvent.click(screen.getByRole("button", { name: /展开验证历史|show verification history/i }));

    expect(screen.getByTestId("material-library-history-dialog")).toBeInTheDocument();
    expect(screen.getByText(/第 1 次验证|Run 1/i)).toBeInTheDocument();
    expect(screen.getByText("0.0150")).toBeInTheDocument();
    expect(screen.getByText(/0.210, 0.310, 0.410/)).toBeInTheDocument();
    expect(screen.getByText(/White identity \/ Black rotate_90_cw|白底 identity \/ 黑底 rotate_90_cw/i)).toBeInTheDocument();

    fireEvent.click(within(screen.getByTestId("material-library-history-dialog")).getByRole("button", { name: /关闭|close/i }));

    await waitFor(() => {
      expect(screen.queryByTestId("material-library-history-dialog")).not.toBeInTheDocument();
    });
  });

  it("starts material re-verification and routes back to the extract tab", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "pla-basic",
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          material_file_url: "/api/files/material-json",
          stage_a_params_url: "/api/files/stage-a-json",
          estimated_rgb: [100, 120, 140],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
      ],
    });

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("material-library-brand-group")).toBeInTheDocument();
    });

    expandAllMaterialLibraryGroups();

    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });

    fireEvent.click(screen.getAllByTestId("material-library-item")[0]);
    fireEvent.click(screen.getByRole("button", { name: /再次验证|re-verify/i }));

    expect(useWidgetStore.getState().activeTab).toBe("gradient-card-extract");
    expect(useSingleStageStore.getState().materialName).toBe("PLA Basic");
    expect(useSingleStageStore.getState().verificationTargetDirectoryName).toBe("pla-basic");
    expect(useSingleStageStore.getState().verificationTargetCount).toBe(3);
  });

  it("deletes a saved material from the library after confirmation", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "pla-basic",
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          material_file_url: "/api/files/material-json",
          stage_a_params_url: "/api/files/stage-a-json",
          estimated_rgb: [100, 120, 140],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
      ],
    });
    vi.mocked(deleteGradientCardMaterial).mockResolvedValue({
      status: "ok",
      message: "deleted",
      directory_name: "pla-basic",
      material_name: "PLA Basic",
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("material-library-brand-group")).toBeInTheDocument();
    });

    expandAllMaterialLibraryGroups();

    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });

    fireEvent.click(screen.getAllByTestId("material-library-item")[0]);
    fireEvent.click(screen.getByRole("button", { name: /删除耗材|delete material/i }));

    await waitFor(() => {
      expect(deleteGradientCardMaterial).toHaveBeenCalledWith("pla-basic");
    });
    expect(screen.queryByText("PLA Basic")).not.toBeInTheDocument();
  });

  it("shows duplicate dates and fit error while keeping directories in details and delete confirmation", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 2 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "Brand/PLA Basic_20260709_145858",
          brand: "Brand",
          created_at: "2026-07-09T14:58:58Z",
          updated_at: "2026-07-09T15:30:00Z",
          material_file_url: "/api/files/material-json-new",
          stage_a_params_url: "/api/files/stage-a-json-new",
          estimated_rgb: [100, 120, 140],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
          verification_history: [
            {
              verification_index: 3,
              captured_at: "2026-07-09T14:59:00Z",
              mean_delta_e: 1.23,
              estimated_rgb: [100, 120, 140],
              estimated_k: [1.1, 1.2, 1.3],
              e_values: [0.21, 0.31, 0.41],
              k_values: [1.1, 1.2, 1.3],
              white_c0_values: [0.91, 0.92, 0.93],
              black_c0_values: [0.11, 0.12, 0.13],
            },
          ],
        },
        {
          material_name: "PLA Basic",
          directory_name: "Brand/PLA Basic_20260521_161941",
          brand: "Brand",
          created_at: "2026-05-21T16:19:41Z",
          updated_at: "2026-05-21T16:30:00Z",
          material_file_url: "/api/files/material-json-old",
          stage_a_params_url: "/api/files/stage-a-json-old",
          estimated_rgb: [90, 110, 130],
          layer_height_mm: 0.04,
          mean_delta_e: 2.34,
          verification_count: 1,
          verification_history: [
            {
              verification_index: 1,
              captured_at: "2026-05-21T16:19:50Z",
              mean_delta_e: 2.34,
              estimated_rgb: [90, 110, 130],
              estimated_k: [1.0, 1.1, 1.2],
              e_values: [0.2, 0.3, 0.4],
              k_values: [1.0, 1.1, 1.2],
              white_c0_values: [0.9, 0.91, 0.92],
              black_c0_values: [0.1, 0.11, 0.12],
            },
          ],
        },
      ],
    });
    vi.mocked(deleteGradientCardMaterial).mockResolvedValue({
      status: "ok",
      message: "deleted",
      directory_name: "Brand/PLA Basic_20260521_161941",
      material_name: "PLA Basic",
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("material-library-brand-group")).toBeInTheDocument();
    });

    expandAllMaterialLibraryGroups();

    await waitFor(() => {
      expect(screen.getAllByTestId("material-library-item")).toHaveLength(2);
    });

    const cards = screen.getAllByTestId("material-library-item");
    expect(within(cards[0]).getByTestId("material-library-duplicate-badge")).toHaveTextContent("2026");
    expect(within(cards[1]).getByTestId("material-library-duplicate-badge")).toHaveTextContent("2026");
    expect(within(cards[0]).getByTestId("material-library-card-fit-error")).toHaveTextContent("拟合误差");
    expect(cards[0]).not.toHaveTextContent("PLA Basic_");
    fireEvent.click(cards[0]);
    expect(within(screen.getByTestId("material-library-details")).getByText("Brand/PLA Basic_20260709_145858")).toBeInTheDocument();
    fireEvent.click(cards[1]);
    fireEvent.click(screen.getByRole("button", { name: /删除耗材|delete material/i }));

    await waitFor(() => {
      expect(deleteGradientCardMaterial).toHaveBeenCalledWith("Brand/PLA Basic_20260521_161941");
    });
    const confirmMessage = String(confirmSpy.mock.calls[0]?.[0] ?? "");
    expect(confirmMessage).toContain("PLA Basic");
    expect(confirmMessage).toContain("Brand/PLA Basic_20260521_161941");
    expect(confirmMessage).toMatch(/最近更新|Last updated/);
    expect(confirmMessage).not.toMatch(/最近验证|Last verified/);
    expect(confirmMessage).toContain("2026");
  });

  it("shows the empty state when no materials exist", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 0 saved materials",
      materials: [],
    });

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(
        screen.getByText(/本地暂无耗材档案|No local material profiles/i),
      ).toBeInTheDocument();
    });
  });

  it("shows readable material library load failures instead of raw HTTP status text", async () => {
    vi.mocked(listGradientCardMaterials).mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    render(<MaterialLibraryPanel />);

    const error = await screen.findByTestId("material-library-error");
    expect(error).toHaveTextContent("服务器发生内部错误。请稍后重试；如果问题持续，请提交反馈。");
    expect(error).not.toHaveTextContent("Request failed with status code 500");
  });

  it("exports selected materials as one ZIP archive", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "pla-basic",
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          material_file_url: "/api/files/material-json",
          stage_a_params_url: "/api/files/stage-a-json",
          estimated_rgb: [100, 120, 140],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
      ],
    });
    vi.mocked(exportGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Exported 1 saved materials",
      download_url: "/api/files/material-export",
      filename: "materials.zip",
      exported_count: 1,
      exported_directory_names: ["pla-basic"],
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("material-library-brand-group")).toBeInTheDocument();
    });

    expandAllMaterialLibraryGroups();

    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /选择耗材|select materials/i }));
    fireEvent.click(screen.getAllByTestId("material-library-item")[0]);
    fireEvent.click(screen.getByRole("button", { name: /导出所选耗材|export selected/i }));

    await waitFor(() => {
      expect(exportGradientCardMaterials).toHaveBeenCalledWith(["pla-basic"]);
    });
    expect(screen.getByTestId("material-library-success")).toBeInTheDocument();
  });

  it("shows readable material export failures instead of raw HTTP status text", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "pla-basic",
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          material_file_url: "/api/files/material-json",
          stage_a_params_url: "/api/files/stage-a-json",
          estimated_rgb: [100, 120, 140],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
      ],
    });
    vi.mocked(exportGradientCardMaterials).mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("material-library-brand-group")).toBeInTheDocument();
    });
    expandAllMaterialLibraryGroups();
    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /选择耗材|select materials/i }));
    fireEvent.click(screen.getAllByTestId("material-library-item")[0]);
    fireEvent.click(screen.getByRole("button", { name: /导出所选耗材|export selected/i }));

    const error = await screen.findByTestId("material-library-error");
    expect(error).toHaveTextContent("服务器发生内部错误。请稍后重试；如果问题持续，请提交反馈。");
    expect(error).not.toHaveTextContent("Request failed with status code 500");
  });

  it("does not expose cloud upload controls in the distribution UI", async () => {
    vi.mocked(listGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Loaded 1 saved materials",
      materials: [
        {
          material_name: "PLA Basic",
          directory_name: "BrandA/pla-basic",
          brand: "BrandA",
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
          material_file_url: "/api/files/material-json",
          stage_a_params_url: "/api/files/stage-a-json",
          estimated_rgb: [100, 120, 140],
          layer_height_mm: 0.04,
          mean_delta_e: 1.23,
          verification_count: 3,
        },
      ],
    });

    render(<MaterialLibraryPanel />);

    await screen.findByTestId("material-library-brand-group-toggle");
    expandAllMaterialLibraryGroups();

    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: /上传到云端|upload to cloud/i })).not.toBeInTheDocument();
  });

  it("imports multiple ZIP archives and selects newly imported materials", async () => {
    vi.mocked(listGradientCardMaterials)
      .mockResolvedValueOnce({
        status: "ok",
        message: "Loaded 0 saved materials",
        materials: [],
      })
      .mockResolvedValueOnce({
        status: "ok",
        message: "Loaded 1 saved materials",
        materials: [
          {
            material_name: "PLA Basic",
            directory_name: "pla-basic",
            created_at: "2026-04-16T10:00:00Z",
            updated_at: "2026-04-16T11:00:00Z",
            material_file_url: "/api/files/material-json",
            stage_a_params_url: "/api/files/stage-a-json",
            estimated_rgb: [100, 120, 140],
            layer_height_mm: 0.04,
            mean_delta_e: 1.23,
            verification_count: 3,
          },
        ],
      });
    vi.mocked(importGradientCardMaterials).mockResolvedValue({
      status: "ok",
      message: "Imported 1 saved materials",
      imported_count: 1,
      imported_materials: [
        {
          material_name: "PLA Basic",
          directory_name: "pla-basic",
          brand: null,
          verification_count: 3,
          created_at: "2026-04-16T10:00:00Z",
          updated_at: "2026-04-16T11:00:00Z",
        },
      ],
    });

    render(<MaterialLibraryPanel />);

    await waitFor(() => {
      expect(screen.getByText(/本地暂无耗材档案|No local material profiles/i)).toBeInTheDocument();
    });

    const importInput = screen.getByTestId("material-library-import-input");
    const zipA = new File(["zip-a"], "materials-a.zip", { type: "application/zip" });
    const zipB = new File(["zip-b"], "materials-b.zip", { type: "application/zip" });
    fireEvent.change(importInput, { target: { files: [zipA, zipB] } });

    await waitFor(() => {
      expect(importGradientCardMaterials).toHaveBeenCalledWith([zipA, zipB]);
    });

    await waitFor(() => {
      expect(screen.getByTestId("material-library-brand-group")).toBeInTheDocument();
    });

    expandAllMaterialLibraryGroups();

    await waitFor(() => {
      expect(screen.getByText("PLA Basic")).toBeInTheDocument();
    });
    expect(screen.getByTestId("material-library-success")).toBeInTheDocument();
    expect(screen.getByTestId("material-library-item")).toHaveAttribute("aria-pressed", "true");
  });

});
