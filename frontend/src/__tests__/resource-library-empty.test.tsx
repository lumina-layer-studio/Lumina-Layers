import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchOfflineCatalog, fetchResourceStatus, installOfflineResource,
  type ResourceKind, type ResourceStatus,
} from "../api/resources";
import OfflineResourceCatalog from "../components/OfflineResourceCatalog";
import ResourceLibraryEmpty from "../components/ui/ResourceLibraryEmpty";
import { useResourceStore } from "../stores/resourceStore";

vi.mock("../api/resources", () => ({
  fetchResourceStatus: vi.fn(), fetchOfflineCatalog: vi.fn(), installOfflineResource: vi.fn(),
}));
const status = (available = false): ResourceStatus => ({
  materials: { configured: true, seed: { state: "uninitialized", available } },
  luts: { configured: true, seed: { state: "uninitialized", available } },
  source_repository: "https://github.com/lumina-layer-studio/Lumina-materials",
});
function renderEmpty(kind: ResourceKind = "materials", onBrowse = vi.fn()) {
  return render(<ResourceLibraryEmpty kind={kind} onBrowse={onBrowse} onImport={vi.fn()} onCalibrate={vi.fn()} />);
}

describe("choosing the first library resource", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    useResourceStore.setState({ status: null, loading: false, error: null, observedContent: {} });
    vi.mocked(fetchResourceStatus).mockResolvedValue(status());
  });

  it.each([["materials", "去云端找耗材"], ["luts", "去云端找 LUT"]] as const)(
    "opens the corresponding cloud catalog for an empty %s library", async (kind, label) => {
      const onBrowse = vi.fn();
      renderEmpty(kind, onBrowse);
      await waitFor(() => expect(useResourceStore.getState().loading).toBe(false));
      fireEvent.click(screen.getByRole("button", { name: label }));
      expect(onBrowse).toHaveBeenCalledWith("cloud");
      expect(screen.queryByRole("button", { name: "从离线包挑选" })).not.toBeInTheDocument();
      expect(installOfflineResource).not.toHaveBeenCalled();
    },
  );

  it("distinguishes new lightweight installs from libraries emptied by the user", async () => {
    const response = status();
    response.materials.seed = { state: "ready", available: false, reason: "no_bundled_seed" };
    vi.mocked(fetchResourceStatus).mockResolvedValue(response);
    renderEmpty();
    await waitFor(() => expect(useResourceStore.getState().loading).toBe(false));
    expect(screen.queryByText(/本地资源已被移除/)).not.toBeInTheDocument();
    act(() => useResourceStore.getState().observeLibrary("materials", 1));
    expect(screen.getByText(/本地资源已被移除/)).toBeInTheDocument();
  });

  it("can retry a failed status check and still browse the cloud", async () => {
    vi.mocked(fetchResourceStatus).mockRejectedValueOnce(new Error("offline"));
    renderEmpty();
    expect(await screen.findByText(/资源状态读取失败/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "去云端找耗材" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(screen.queryByText(/资源状态读取失败/)).not.toBeInTheDocument());
  });

  it("can browse a bundled catalog when the cloud is disabled", async () => {
    const response = status(true);
    response.materials.configured = false;
    vi.mocked(fetchResourceStatus).mockResolvedValue(response);
    const onBrowse = vi.fn();
    renderEmpty("materials", onBrowse);
    fireEvent.click(await screen.findByRole("button", { name: "从离线包挑选" }));
    expect(screen.getByRole("button", { name: "去云端找耗材" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "导入本地文件" })).toBeEnabled();
    expect(onBrowse).toHaveBeenCalledWith("offline");
    expect(installOfflineResource).not.toHaveBeenCalled();
  });

  it.each(["materials", "luts"] as const)("previews two %s entries and adds only the chosen revision", async (kind) => {
    const items = ["Amber", "Violet"].map((name) => ({
      name, brand: "Test Brand", resource_id: name.toLowerCase(), revision_id: "r2",
      material_type: "PLA", color_mode: null, installed: false,
    }));
    vi.mocked(fetchOfflineCatalog).mockResolvedValue({ items, dataset_version: "1" });
    const onInstalled = vi.fn();
    render(<OfflineResourceCatalog kind={kind} onInstalled={onInstalled} />);
    fireEvent.click(await screen.findByRole("button", { name: /Violet/ }));
    const details = screen.getByRole("complementary");
    expect(within(details).getByText("Violet")).toBeInTheDocument();
    expect(installOfflineResource).not.toHaveBeenCalled();
    fireEvent.click(within(details).getByRole("button", { name: "添加到本地" }));
    await waitFor(() => expect(onInstalled).toHaveBeenCalledOnce());
    expect(installOfflineResource).toHaveBeenCalledExactlyOnceWith(kind, items[1]);
    expect(within(details).getByText("已在本地")).toBeInTheDocument();
    expect(within(screen.getAllByRole("article")[0]).getByRole("button", { name: "添加到本地" })).toBeEnabled();
  });
});
