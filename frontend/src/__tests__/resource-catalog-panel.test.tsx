import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ResourceCatalogPanel from "../components/ResourceCatalogPanel";
import { fetchOfflineCatalog, fetchResourceStatus, installOfflineResource, type ResourceKind } from "../api/resources";
import { fetchCloudLutRegistryCatalog, fetchCloudLutRegistryStatus, installCloudLut } from "../api/lut";
import { fetchMaterialRegistryCatalog, fetchMaterialSyncStatus, installMaterialRegistryCatalogEntry } from "../api/materialSync";
import { useResourceStore } from "../stores/resourceStore";

vi.mock("../api/resources", () => ({
  fetchResourceStatus: vi.fn(), fetchOfflineCatalog: vi.fn(), installOfflineResource: vi.fn(),
}));
vi.mock("../api/lut", () => ({
  fetchCloudLutRegistryCatalog: vi.fn(), fetchCloudLutRegistryStatus: vi.fn(),
  fetchCloudLutPreviews: vi.fn(), installCloudLut: vi.fn(),
}));
vi.mock("../api/materialSync", () => ({
  fetchMaterialRegistryCatalog: vi.fn(), fetchMaterialSyncStatus: vi.fn(),
  installMaterialRegistryCatalogEntry: vi.fn(), rollbackMaterialSyncRevision: vi.fn(),
}));

describe("continuing a resource search between catalogs", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    useResourceStore.setState({
      status: null, loading: false, error: null,
      catalogSource: { materials: "cloud", luts: "cloud" },
    });
    vi.mocked(fetchResourceStatus).mockResolvedValue({
      materials: { configured: true, seed: { state: "uninitialized", available: true } },
      luts: { configured: true, seed: { state: "uninitialized", available: true } },
      source_repository: "",
    });
    vi.mocked(fetchOfflineCatalog).mockResolvedValue({
      dataset_version: "test.1",
      items: [{
        resource_id: "one", revision_id: "one", name: "Aliz Red", brand: "Aliz",
        material_type: "PLA", color_mode: null, rgb: [200, 20, 30],
        display: {}, installed: false,
      }],
    });
    vi.mocked(fetchCloudLutRegistryStatus).mockResolvedValue({
      configured: true, base_url: null, channels: ["official"], installed_count: 0,
    });
    vi.mocked(fetchCloudLutRegistryCatalog).mockResolvedValue({
      configured: true, channels: ["official"], items: [], total: 0,
    });
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue({
      status: "ok", message: "", schema_version: "1.0", index_state: "ready",
      last_sync_at: null, registries: {}, installed_count: 0, installed: [], local_overrides_count: 0,
    });
    vi.mocked(fetchMaterialRegistryCatalog).mockResolvedValue({
      schema_version: "1.0", channels: ["official"], materials: [], count: 0,
      total_count: 0, offset: 0, limit: 24,
    });
  });

  it("identifies the GitHub source without showing an unavailable offline pack", async () => {
    vi.mocked(fetchResourceStatus).mockResolvedValue({
      materials: { configured: true, provider: "github", seed: { state: "uninitialized", available: false } },
      luts: { configured: true, provider: "github", seed: { state: "uninitialized", available: false } },
      source_repository: "",
    });
    render(<ResourceCatalogPanel kind="materials" />);
    expect(await screen.findByText("GitHub 目录")).toBeVisible();
    expect(screen.queryByRole("button", { name: "离线包" })).not.toBeInTheDocument();
    expect(installMaterialRegistryCatalogEntry).not.toHaveBeenCalled();
  });

  it.each<ResourceKind>(["materials", "luts"])("preserves the %s search in both directions without installing", async (kind) => {
    const onQueryChange = vi.fn();
    render(<ResourceCatalogPanel kind={kind} initialQuery="Bambu" onQueryChange={onQueryChange} />);
    expect(screen.getByRole("searchbox")).toHaveValue("Bambu");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Aliz" } });
    fireEvent.click(await screen.findByRole("button", { name: "离线包" }));
    expect(screen.getByRole("searchbox")).toHaveValue("Aliz");
    expect(await screen.findByRole("button", { name: /Red/ })).toBeInTheDocument();
    expect(screen.getByRole("article")).not.toHaveTextContent("可离线添加");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Aliz Red" } });
    fireEvent.click(screen.getByRole("button", { name: "云端目录" }));
    expect(screen.getByRole("searchbox")).toHaveValue("Aliz Red");
    expect(onQueryChange).toHaveBeenLastCalledWith("Aliz Red");
    await waitFor(() => expect(kind === "materials" ? fetchMaterialRegistryCatalog : fetchCloudLutRegistryCatalog).toHaveBeenCalled());
    expect(installOfflineResource).not.toHaveBeenCalled();
    expect(installCloudLut).not.toHaveBeenCalled();
    expect(installMaterialRegistryCatalogEntry).not.toHaveBeenCalled();
  });

  it.each<ResourceKind>(["materials", "luts"])("keeps selected %s facets when switching between cloud and offline", async (kind) => {
    render(<ResourceCatalogPanel kind={kind} initialSource="offline" />);
    fireEvent.click(await screen.findByRole("button", { name: "品牌" }));
    fireEvent.click(await screen.findByRole("checkbox", { name: /爱丽兹/ }));
    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    fireEvent.click(screen.getByRole("button", { name: "云端目录" }));
    await waitFor(() => expect(kind === "materials" ? fetchMaterialRegistryCatalog : fetchCloudLutRegistryCatalog).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "离线包" }));
    expect(await screen.findByRole("button", { name: /Red/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "品牌" }));
    expect(await screen.findByRole("checkbox", { name: /爱丽兹/ })).toBeChecked();
    expect(installOfflineResource).not.toHaveBeenCalled();
  });

  it.each<ResourceKind>(["materials", "luts"])("offers the bundled %s search when the network fails", async (kind) => {
    vi.mocked(fetchMaterialRegistryCatalog).mockRejectedValue(new Error("Connection unavailable"));
    vi.mocked(fetchCloudLutRegistryCatalog).mockRejectedValue(new Error("Connection unavailable"));
    render(<ResourceCatalogPanel kind={kind} initialQuery="Aliz" />);
    fireEvent.click(await screen.findByRole("button", { name: "从离线包挑选" }));
    expect(screen.getByRole("searchbox")).toHaveValue("Aliz");
    expect(await screen.findByRole("button", { name: /Red/ })).toBeInTheDocument();
    expect(installOfflineResource).not.toHaveBeenCalled();
  });

  it.each<ResourceKind>(["materials", "luts"])("offers offline %s resources while showing a cached directory", async (kind) => {
    const materialCatalog = await fetchMaterialRegistryCatalog();
    const lutCatalog = await fetchCloudLutRegistryCatalog();
    vi.mocked(fetchMaterialRegistryCatalog).mockResolvedValue({ ...materialCatalog, cached: true });
    vi.mocked(fetchCloudLutRegistryCatalog).mockResolvedValue({ ...lutCatalog, cached: true });
    render(<ResourceCatalogPanel kind={kind} initialQuery="Aliz" />);
    fireEvent.click(await screen.findByRole("button", { name: "从离线包挑选" }));
    expect(screen.getByRole("searchbox")).toHaveValue("Aliz");
    expect(await screen.findByRole("button", { name: /Red/ })).toBeInTheDocument();
    expect(installOfflineResource).not.toHaveBeenCalled();
  });

  it("clears an empty offline search and keeps that change when returning online", async () => {
    const onQueryChange = vi.fn();
    render(<ResourceCatalogPanel kind="luts" initialSource="offline" initialQuery="Missing" onQueryChange={onQueryChange} />);
    fireEvent.click(await screen.findByRole("button", { name: "清空搜索" }));
    expect(screen.getByRole("searchbox")).toHaveValue("");
    expect(screen.getByRole("button", { name: /Aliz Red/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "云端目录" }));
    expect(screen.getByRole("searchbox")).toHaveValue("");
    expect(onQueryChange).toHaveBeenLastCalledWith("");
    await waitFor(() => expect(fetchCloudLutRegistryCatalog).toHaveBeenCalled());
  });

  it("does not offer an offline route without an installed bundle", async () => {
    const status = await fetchResourceStatus();
    status.luts.seed.available = false;
    vi.mocked(fetchResourceStatus).mockResolvedValue(status);
    vi.mocked(fetchCloudLutRegistryCatalog).mockRejectedValue(new Error("Connection unavailable"));
    render(<ResourceCatalogPanel kind="luts" />);
    await screen.findByText("Connection unavailable");
    expect(screen.queryByRole("button", { name: "从离线包挑选" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "离线包" })).not.toBeInTheDocument();
  });

  it.each<ResourceKind>(["materials", "luts"])("reflows offline %s pages without losing the inspected item or fetching again", async (kind) => {
    const baseline = await fetchOfflineCatalog(kind);
    vi.mocked(fetchOfflineCatalog).mockClear().mockResolvedValue({
      ...baseline, items: Array.from({ length: 82 }, (_, index) => ({
        ...baseline.items[0], resource_id: `item-${index}`, name: `Sample ${String(index).padStart(2, "0")}`,
      })),
    });
    let columns = 5;
    const observers = new Set<() => void>();
    const computedStyle = window.getComputedStyle.bind(window);
    const styleSpy = vi.spyOn(window, "getComputedStyle").mockImplementation((element) =>
      new Proxy(computedStyle(element), { get: (target, key) => key === "gridTemplateColumns"
        ? Array(columns).fill("250px").join(" ") : Reflect.get(target, key) }));
    const OriginalObserver = globalThis.ResizeObserver;
    globalThis.ResizeObserver = class {
      private callback: () => void;
      constructor(callback: () => void) { this.callback = callback; observers.add(callback); }
      observe() {}
      unobserve() {}
      disconnect() { observers.delete(this.callback); }
    } as unknown as typeof ResizeObserver;
    try {
      render(<ResourceCatalogPanel kind={kind} initialSource="offline" />);
      await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(25));
      fireEvent.click(screen.getByRole("button", { name: "下一页" }));
      fireEvent.click(screen.getByRole("button", { name: /Sample 49/ }));
      for (const [nextColumns, count] of [[7, 28], [1, 24], [9, 27]]) {
        columns = nextColumns;
        act(() => observers.forEach((callback) => callback()));
        expect(screen.getAllByRole("article")).toHaveLength(count);
        expect(within(screen.getByRole("complementary")).getByRole("heading", { name: "Sample 49" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Sample 49/ })).toHaveAttribute("aria-expanded", "true");
      }
      fireEvent.click(screen.getByRole("button", { name: "第 4 页" }));
      expect(screen.getAllByRole("article")).toHaveLength(1);
      expect(screen.getByRole("button", { name: /Sample 81/ })).toBeInTheDocument();
      expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
      fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Missing" } });
      expect(screen.queryAllByRole("article")).toHaveLength(0);
      fireEvent.click(screen.getByRole("button", { name: "清空搜索" }));
      expect(screen.getAllByRole("article")).toHaveLength(27);
      expect(screen.getByRole("button", { name: /Sample 00/ })).toBeInTheDocument();
      expect(fetchOfflineCatalog).toHaveBeenCalledTimes(1);
      expect(installOfflineResource).not.toHaveBeenCalled();
    } finally {
      styleSpy.mockRestore();
      globalThis.ResizeObserver = OriginalObserver;
    }
  });
});
