import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "./communityTestMocks";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import MaterialCloudSyncPanel from "../components/MaterialCloudSyncPanel";
import {
  fetchMaterialRegistryCatalog,
  fetchMaterialSyncStatus,
  installMaterialRegistryCatalogEntry,
  rollbackMaterialSyncRevision,
} from "../api/materialSync";
import type {
  MaterialRegistryCatalogEntry,
  MaterialSyncInstalledEntry,
  MaterialSyncStatusResponse,
} from "../api/types";

vi.mock("../api/materialSync", () => ({
  fetchMaterialRegistryCatalog: vi.fn(),
  fetchMaterialSyncStatus: vi.fn(),
  installMaterialRegistryCatalogEntry: vi.fn(),
  rollbackMaterialSyncRevision: vi.fn(),
}));

type CatalogResponse = Awaited<ReturnType<typeof fetchMaterialRegistryCatalog>>;
type CatalogQuery = Parameters<typeof fetchMaterialRegistryCatalog>[0];

const PAGE_SIZE = 24;

const makeEntry = (
  materialId: string,
  materialName: string,
  overrides: Partial<MaterialRegistryCatalogEntry> = {},
): MaterialRegistryCatalogEntry => ({
  material_id: materialId,
  revision_id: `rev_${materialId}`,
  content_hash: `sha256:${materialId}`,
  channel: "official",
  visibility: "official",
  local_directory: `BrandA/${materialId}`,
  display: { brand: "BrandA", material_name: materialName },
  compatibility: {},
  package_url: `/v1/packages/${materialId}.zip`,
  package_sha256: materialId.padEnd(64, "0").slice(0, 64),
  package_bytes: 1024,
  ...overrides,
});

const makeInstalled = (
  materialId: string,
  overrides: Partial<MaterialSyncInstalledEntry> = {},
): MaterialSyncInstalledEntry => ({
  material_id: materialId,
  revision_id: `rev_${materialId}`,
  content_hash: `sha256:${materialId}`,
  channel: "official",
  source: "package",
  local_directory: `BrandA/${materialId}`,
  display_brand: "BrandA",
  display_name: materialId,
  installed_at: "2026-06-08T01:02:03Z",
  updated_at: "2026-06-08T01:02:03Z",
  local_exists: true,
  material_file_exists: true,
  available_revisions: [`rev_${materialId}`],
  ...overrides,
});

const statusWith = (installed: MaterialSyncInstalledEntry[]): MaterialSyncStatusResponse => ({
  status: "ok",
  message: "Material sync status loaded",
  schema_version: "1.0",
  index_state: "ready",
  last_sync_at: "2026-06-08T01:02:03Z",
  registries: {},
  installed_count: installed.filter((entry) => entry.local_exists).length,
  installed,
  local_overrides_count: 0,
});

const catalogPage = (
  materials: MaterialRegistryCatalogEntry[],
  { offset = 0, totalCount = materials.length }: { offset?: number; totalCount?: number } = {},
): CatalogResponse => ({
  schema_version: "1.0",
  channels: ["official", "community"],
  count: materials.length,
  total_count: totalCount,
  offset,
  limit: PAGE_SIZE,
  materials,
});

/** Emulates the Registry: server-side search, then offset/limit paging. */
const serveCatalog = (entries: MaterialRegistryCatalogEntry[]) =>
  async (query: CatalogQuery = {}): Promise<CatalogResponse> => {
    const needle = (query.q ?? "").toLowerCase();
    const matched = needle
      ? entries.filter((entry) => JSON.stringify(entry.display).toLowerCase().includes(needle))
      : entries;
    const offset = query.offset ?? 0;
    const page = query.limit === undefined
      ? matched.slice(offset)
      : matched.slice(offset, offset + query.limit);
    return catalogPage(page, { offset, totalCount: matched.length });
  };

const manyEntries = (count: number): MaterialRegistryCatalogEntry[] =>
  Array.from({ length: count }, (_, index) => makeEntry(
    `mat_${String(index).padStart(2, "0")}`,
    `Item ${String(index).padStart(2, "0")} PLA`,
  ));

const defaultInstalled = (): MaterialSyncInstalledEntry[] => [
  makeInstalled("mat_test", {
    revision_id: "rev_new",
    content_hash: "sha256:new",
    local_directory: "BrandA/pla-basic",
    display_name: "PLA Basic",
    available_revisions: ["rev_old", "rev_new"],
  }),
  makeInstalled("mat_update", {
    revision_id: "rev_1",
    content_hash: "sha256:old",
    local_directory: "BrandA/pla-pro",
    display_name: "PLA Pro",
    available_revisions: ["rev_1"],
  }),
];

const defaultCatalog = (): MaterialRegistryCatalogEntry[] => [
  makeEntry("mat_test", "PLA Basic", {
    revision_id: "rev_new",
    content_hash: "sha256:new",
    local_directory: "BrandA/pla-basic",
    package_url: "/v1/packages/mat_test/rev_new.zip",
    package_sha256: "a".repeat(64),
    package_bytes: 2048,
  }),
  makeEntry("mat_update", "PLA Pro", {
    revision_id: "rev_2",
    content_hash: "sha256:newer",
    local_directory: "BrandA/pla-pro",
    package_url: "/v1/packages/mat_update/rev_2.zip",
    package_sha256: "b".repeat(64),
    package_bytes: 4096,
  }),
  makeEntry("mat_cloud", "Silk PETG", {
    revision_id: "rev_cloud",
    content_hash: "sha256:cloud",
    channel: "community",
    visibility: "community",
    local_directory: "BrandB/petg-silk",
    display: { brand: "BrandB", material_name: "Silk PETG", estimated_rgb: [20, 120, 220] },
    package_url: "/v1/packages/mat_cloud/rev_cloud.zip",
    package_sha256: "c".repeat(64),
    package_bytes: 8192,
    card_metadata: { mean_delta_e: 4.873, verification_count: 2, layer_height_mm: 0.08 },
  }),
];

const openLocalRevisions = () => {
  fireEvent.click(screen.getByRole("button", { name: /本地历史版本|Local Version History/ }));
};

afterEach(() => {
  vi.useRealTimers();
});

describe("MaterialCloudSyncPanel", () => {
  it("reuses the complete scoped index for repeated queries without additional catalog requests", async () => {
    const entry = makeEntry("bambu", "PLA Basic 黑色", {
      display: { brand: "Bambu Lab", material_name: "PLA Basic 黑色", material_type: "PLA" },
    });
    const serve = serveCatalog([...manyEntries(30), entry]);
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue({ ...statusWith([]), source_scope: "same-source" });
    vi.mocked(fetchMaterialRegistryCatalog).mockImplementation(async (query) => ({ ...await serve(query), source_scope: "same-source" }));
    render(<MaterialCloudSyncPanel />);
    await screen.findByText("Item 00 PLA");
    fireEvent.click(screen.getByRole("button", { name: "品牌" }));
    await screen.findByRole("checkbox", { name: /拓竹/ });
    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    vi.mocked(fetchMaterialRegistryCatalog).mockClear();
    for (const query of ["10101", "拓竹PLA黑色", "Bambu black"]) {
      fireEvent.change(screen.getByRole("searchbox"), { target: { value: query } });
      await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(1));
      expect(screen.getByRole("button", { name: /PLA Basic 黑色/ })).toBeInTheDocument();
    }
    expect(fetchMaterialRegistryCatalog).not.toHaveBeenCalled();
    expect(installMaterialRegistryCatalogEntry).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /刷新云端目录/ }));
    await waitFor(() => expect(fetchMaterialRegistryCatalog).toHaveBeenCalled());
  });

  it("aborts an obsolete page request when the search changes", async () => {
    let signal: AbortSignal | undefined;
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue(statusWith([]));
    vi.mocked(fetchMaterialRegistryCatalog).mockImplementation((_params, currentSignal) => {
      signal = currentSignal;
      return new Promise(() => {});
    });
    render(<MaterialCloudSyncPanel />);
    await waitFor(() => expect(signal).toBeDefined());
    expect(signal?.aborted).toBe(false);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "new query" } });
    expect(signal?.aborted).toBe(true);
  });

  it("filters the complete metadata catalog across pages and combines brand, material and text", async () => {
    const target = makeEntry("bambu", "PLA Basic 黑色", {
      display: { brand: "Bambu Lab", material_name: "PLA Basic 黑色", material_type: "PLA", series: "Basic" },
    });
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue(statusWith([]));
    vi.mocked(fetchMaterialRegistryCatalog).mockImplementation(serveCatalog([...manyEntries(48), target]));
    render(<MaterialCloudSyncPanel />);
    await screen.findByText("Item 00 PLA");
    fireEvent.click(screen.getByRole("button", { name: "品牌" }));
    fireEvent.click(await screen.findByRole("checkbox", { name: /拓竹/ }));
    expect(await screen.findByRole("button", { name: /PLA Basic 黑色/ })).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(1);
    fireEvent.keyDown(screen.getByRole("checkbox", { name: /拓竹/ }), { key: "Escape" });
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "10101" } });
    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(1));
    expect(installMaterialRegistryCatalogEntry).not.toHaveBeenCalled();
  });

  it("merges native results with SKU matches beyond a capped first page and installs only the inspected revision", async () => {
    const profile = makeEntry("actual-id", "Bambu PLA Basic 黑色", {
      display: { brand: "拓竹", material_name: "Bambu PLA Basic 黑色" },
    });
    const entries = [...manyEntries(PAGE_SIZE), profile];
    const nativeHit = makeEntry("native", "Registry keyword result");
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue(statusWith([]));
    vi.mocked(fetchMaterialRegistryCatalog).mockImplementation(async (params = {}) => {
      if (params.q) return { ...catalogPage([nativeHit]), source_scope: "catalog-a" };
      const offset = params.offset ?? 0;
      return { ...catalogPage(entries.slice(offset, offset + PAGE_SIZE), { offset, totalCount: entries.length }), source_scope: "catalog-a" };
    });
    render(<MaterialCloudSyncPanel />);
    await screen.findByText("Item 00 PLA");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "10101" } });
    // This includes the search debounce and a complete metadata merge/render.
    const card = await screen.findByRole("button", { name: /PLA Basic 黑色/ }, { timeout: 3000 });
    expect(screen.getByText("Registry keyword result")).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(2);
    fireEvent.click(card);
    const detail = screen.getByRole("complementary");
    expect(detail).toHaveTextContent("Bambu PLA Basic 黑色");
    expect(detail).toHaveTextContent("10101");
    expect(detail.querySelector("img")).toBeInTheDocument();
    expect(installMaterialRegistryCatalogEntry).not.toHaveBeenCalled();
    fireEvent.click(within(detail).getByRole("button", { name: /下载到本地|download/i }));
    await waitFor(() => expect(installMaterialRegistryCatalogEntry).toHaveBeenCalledTimes(1));
    expect(installMaterialRegistryCatalogEntry).toHaveBeenCalledWith({
      material_id: profile.material_id, revision_id: profile.revision_id,
      package_url: profile.package_url, package_sha256: profile.package_sha256,
    });
  });

  it("discards an indexed private source when a new source has the same channels", async () => {
    const privateRow = makeEntry("private", "Private material", {
      display: { brand: "Private", material_name: "Private material", aliases: ["secret alias"] },
    });
    let publicSource = false;
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue(statusWith([]));
    vi.mocked(fetchMaterialRegistryCatalog).mockImplementation(async () => ({
      ...catalogPage(publicSource ? [] : [privateRow]), source_scope: publicSource ? "public" : "private",
    }));
    render(<MaterialCloudSyncPanel />);
    await screen.findByText("Private material");
    publicSource = true;
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "secret alias" } });
    await screen.findByText(/没有匹配的云端耗材/);
    expect(screen.queryByText("Private material")).not.toBeInTheDocument();
  });
  it("keeps the successful directory visible if a refresh fails", async () => {
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue(statusWith([]));
    vi.mocked(fetchMaterialRegistryCatalog).mockResolvedValue(catalogPage([makeEntry("kept", "Kept material")]));
    render(<MaterialCloudSyncPanel />);
    await screen.findByRole("button", { name: /Kept material/ });
    vi.mocked(fetchMaterialRegistryCatalog).mockRejectedValueOnce(new Error("offline"));
    fireEvent.click(screen.getByRole("button", { name: /刷新|Refresh/ }));
    await screen.findByTestId("material-cloud-sync-error");
    expect(screen.getByRole("button", { name: /Kept material/ })).toBeInTheDocument();
    expect(screen.getByText(/当前显示上次缓存的目录/)).toBeInTheDocument();
  });

  it("clears cached rows when the active source changed and the new one is offline", async () => {
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue({ ...statusWith([]), source_scope: "one" });
    vi.mocked(fetchMaterialRegistryCatalog).mockResolvedValue({ ...catalogPage([makeEntry("old", "Private profile")]), source_scope: "one" });
    render(<MaterialCloudSyncPanel />);
    const card = await screen.findByRole("button", { name: /Private profile/ });
    fireEvent.click(card);
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue({ ...statusWith([]), source_scope: "two" });
    vi.mocked(fetchMaterialRegistryCatalog).mockRejectedValue(new Error("offline"));
    fireEvent.click(screen.getByRole("button", { name: /刷新|Refresh/ }));
    await screen.findByTestId("material-cloud-sync-error");
    expect(screen.queryByText("Private profile")).not.toBeInTheDocument();
  });

  it("labels an offline directory without downloading packages", async () => {
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue(statusWith([]));
    vi.mocked(fetchMaterialRegistryCatalog).mockResolvedValue({ ...catalogPage([makeEntry("cached", "Cached material")]), cached: true, fetched_at: "2026-11-05T00:00:00Z" });
    render(<MaterialCloudSyncPanel />);
    expect(await screen.findByText(/当前显示本地缓存目录/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Cached material/ })).toBeInTheDocument();
    expect(installMaterialRegistryCatalogEntry).not.toHaveBeenCalled();
  });
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue(statusWith(defaultInstalled()));
    vi.mocked(fetchMaterialRegistryCatalog).mockImplementation(serveCatalog(defaultCatalog()));
    vi.mocked(installMaterialRegistryCatalogEntry).mockResolvedValue({
      status: "ok",
      message: "installed",
      installed_count: 1,
      installed_materials: [],
    });
    vi.mocked(rollbackMaterialSyncRevision).mockResolvedValue({
      status: "ok",
      message: "rolled back",
      material_id: "mat_test",
      revision_id: "rev_old",
      content_hash: "sha256:old",
      channel: "official",
      local_directory: "BrandA/pla-basic",
    });
  });

  it("keeps the new view inspectable without installing and has no comparison tabs", async () => {
    render(<MaterialCloudSyncPanel />);
    const card = await screen.findByRole("button", { name: /Silk PETG/ });
    fireEvent.click(card);
    expect(installMaterialRegistryCatalogEntry).not.toHaveBeenCalled();
    const close = screen.getByRole("button", { name: /关闭|Close/i });
    expect(close).toHaveFocus();
    fireEvent.click(close);
    expect(card).toHaveFocus();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Silk PETG/ })).toBeInTheDocument();
  });

  it("opens local history as a date-based modal in the new view", async () => {
    render(<MaterialCloudSyncPanel />);
    await screen.findByRole("button", { name: /Silk PETG/ });
    const trigger = screen.getByRole("button", { name: /本地历史版本|Local Version History/ });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: /本地历史版本|Local Version History/ });
    expect(dialog).not.toHaveTextContent(/rev_old|rev_new|sha256/);
    fireEvent.click(within(dialog).getAllByRole("radio")[0]);
    fireEvent.click(within(dialog).getByRole("button", { name: /恢复所选版本|Restore selected/ }));
    await waitFor(() => expect(rollbackMaterialSyncRevision).toHaveBeenCalledWith("mat_test", "rev_old"));
    await waitFor(() => expect(dialog).toHaveTextContent(/耗材版本已回滚|Material revision rolled back/i));
    expect(dialog).not.toHaveTextContent("rolled back mat_test to rev_old");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it("renders the cloud catalog and installs a selected material", async () => {
    render(<MaterialCloudSyncPanel />);

    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(await screen.findByText("Silk PETG")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: /可更新|Updates/i })).toHaveTextContent("1"));

    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "PETG" },
    });
    await waitFor(() => {
      expect(fetchMaterialRegistryCatalog).toHaveBeenCalledWith({
        limit: PAGE_SIZE,
        offset: 0,
        q: "PETG",
      }, expect.any(AbortSignal));
    });
    await waitFor(() => {
      expect(screen.getAllByRole("article")).toHaveLength(1);
    });
    expect(within(screen.getAllByRole("article")[0]).getByText("Silk PETG")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /下载到本地|download/i }));

    await waitFor(() => {
      expect(installMaterialRegistryCatalogEntry).toHaveBeenCalledWith({
        material_id: "mat_cloud",
        revision_id: "rev_cloud",
        package_url: "/v1/packages/mat_cloud/rev_cloud.zip",
        package_sha256: "c".repeat(64),
      });
    });
    await waitFor(() => {
      expect(fetchMaterialSyncStatus).toHaveBeenCalledTimes(3);
    });
    expect(await screen.findByTestId("material-cloud-sync-success")).toHaveTextContent("已将「Silk PETG」添加到本地");
  });

  it("shows readable install failures without raw status-code wording", async () => {
    vi.mocked(installMaterialRegistryCatalogEntry).mockRejectedValueOnce(
      new Error("Request failed with status code 500"),
    );

    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByText("Silk PETG")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /下载到本地|download/i }));

    const banner = await screen.findByTestId("material-cloud-sync-error");
    expect(banner).toHaveTextContent(/服务器发生内部错误|server hit an internal error/i);
    expect(banner).not.toHaveTextContent("Request failed with status code 500");

    fireEvent.click(within(banner).getByRole("button", { name: /关闭提示|dismiss/i }));
    expect(screen.queryByTestId("material-cloud-sync-error")).not.toBeInTheDocument();
  });

  it("uses install fallback when the selected cloud package is stale", async () => {
    const staleCatalogDetail =
      "Selected material registry package is not in current material registry catalog";
    vi.mocked(installMaterialRegistryCatalogEntry).mockRejectedValueOnce(
      Object.assign(new Error("Request failed with status code 422"), {
        response: { status: 422, data: { detail: staleCatalogDetail } },
      }),
    );

    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByText("Silk PETG")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /下载到本地|download/i }));

    const banner = await screen.findByTestId("material-cloud-sync-error");
    expect(banner).toHaveTextContent(/耗材下载失败|Material download failed/i);
    expect(banner).not.toHaveTextContent(staleCatalogDetail);
    expect(banner).not.toHaveTextContent("Request failed with status code 422");
  });

  it("reloads the cloud catalog without exposing an official password", async () => {
    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByText("Silk PETG")).toBeInTheDocument();
    vi.mocked(fetchMaterialRegistryCatalog).mockClear();
    fireEvent.click(screen.getByRole("button", { name: /刷新云端目录|refresh catalog/i }));

    await waitFor(() => {
      expect(fetchMaterialRegistryCatalog).toHaveBeenCalledWith({ limit: PAGE_SIZE, offset: 0, refresh: true }, expect.any(AbortSignal));
    });
    expect(screen.queryByTestId("material-cloud-official-password-input")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /上传耗材包|upload material package/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /批准|approve/i })).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "PETG" },
    });
    await waitFor(() => {
      expect(fetchMaterialRegistryCatalog).toHaveBeenCalledWith({ limit: PAGE_SIZE, offset: 0, q: "PETG" }, expect.any(AbortSignal));
    });
  });

  it("keeps fit error in details and reserves cards for community activity", async () => {
    render(<MaterialCloudSyncPanel />);
    const card = await screen.findByRole("button", { name: /Silk PETG/ });
    expect(card).not.toHaveTextContent("4.87");
    expect(card).toHaveTextContent("BrandB");
    fireEvent.click(card);
    expect(screen.getByText("4.87")).toBeInTheDocument();
    expect(screen.getByText(/社区频道|Community/i)).toBeInTheDocument();
    expect(screen.getByText("0.08 mm")).toBeInTheDocument();
  });

  it("turns server pages instead of appending more entries", async () => {
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue(statusWith([]));
    vi.mocked(fetchMaterialRegistryCatalog).mockImplementation(serveCatalog(manyEntries(30)));

    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByText("Item 00 PLA")).toBeInTheDocument();
    expect(fetchMaterialRegistryCatalog).toHaveBeenCalledWith({ limit: PAGE_SIZE, offset: 0 }, expect.any(AbortSignal));
    expect(screen.getAllByRole("article")).toHaveLength(PAGE_SIZE);
    expect(screen.queryByRole("button", { name: /加载更多|load more/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /上一页|previous/i })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /下一页|next/i }));

    await waitFor(() => {
      expect(fetchMaterialRegistryCatalog).toHaveBeenCalledWith({ limit: PAGE_SIZE, offset: PAGE_SIZE }, expect.any(AbortSignal));
    });
    expect(await screen.findByText("Item 24 PLA")).toBeInTheDocument();
    expect(screen.queryByText("Item 00 PLA")).not.toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(6);
    expect(screen.getByRole("button", { name: /第 2 页|page 2/i })).toHaveAttribute("aria-current", "page");

    fireEvent.click(screen.getByRole("button", { name: /第 1 页|page 1/i }));
    expect(await screen.findByText("Item 00 PLA")).toBeInTheDocument();
    expect(screen.queryByText("Item 24 PLA")).not.toBeInTheDocument();
  });

  it("fills five-column pages and retains the inspected entry when details reduce the column count", async () => {
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue(statusWith([]));
    vi.mocked(fetchMaterialRegistryCatalog).mockImplementation(serveCatalog(manyEntries(82)));
    let columns = 5;
    const observers = new Set<() => void>();
    const computedStyle = window.getComputedStyle.bind(window);
    const styleSpy = vi.spyOn(window, "getComputedStyle").mockImplementation((element) => {
      const style = computedStyle(element);
      return new Proxy(style, { get: (target, property) => property === "gridTemplateColumns"
        ? Array(columns).fill("250px").join(" ") : Reflect.get(target, property) });
    });
    const OriginalObserver = globalThis.ResizeObserver;
    globalThis.ResizeObserver = class {
      constructor(callback: () => void) { observers.add(callback); }
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
    try {
      render(<MaterialCloudSyncPanel />);
      await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(25));
      fireEvent.click(screen.getByRole("button", { name: /下一页|next page/i }));
      expect(await screen.findByText("Item 25 PLA")).toBeInTheDocument();
      expect(screen.getByText("Item 49 PLA")).toBeInTheDocument();
      expect(fetchMaterialRegistryCatalog).toHaveBeenLastCalledWith({ limit: 25, offset: 25 }, expect.any(AbortSignal));
      fireEvent.click(screen.getByRole("button", { name: /Item 49 PLA/ }));
      columns = 4;
      act(() => { observers.forEach((callback) => callback()); });
      await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(24));
      expect(within(screen.getByRole("complementary")).getByRole("heading", { name: "Item 49 PLA" })).toBeInTheDocument();
      expect(fetchMaterialRegistryCatalog).toHaveBeenLastCalledWith({ limit: 24, offset: 48 }, expect.any(AbortSignal));
      let finishNavigation!: (response: CatalogResponse) => void;
      vi.mocked(fetchMaterialRegistryCatalog).mockImplementationOnce(() => new Promise((resolve) => { finishNavigation = resolve; }));
      fireEvent.click(screen.getByRole("button", { name: /下一页|next page/i }));
      // Closing details expands the grid before the next server page arrives.
      columns = 5;
      act(() => { observers.forEach((callback) => callback()); });
      await act(async () => finishNavigation(await serveCatalog(manyEntries(82))({ limit: 24, offset: 72 })));
      await waitFor(() => expect(fetchMaterialRegistryCatalog).toHaveBeenLastCalledWith({ limit: 25, offset: 50 }, expect.any(AbortSignal)));
      expect(screen.getByText("Item 72 PLA")).toBeInTheDocument();
      expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /下一页|next page/i }));
      await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(7));
      expect(screen.getByText("Item 81 PLA")).toBeInTheDocument();
      fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Item 00" } });
      columns = 7;
      act(() => { observers.forEach((callback) => callback()); });
      expect(await screen.findByText("Item 00 PLA")).toBeInTheDocument();
      await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(1));
      expect(fetchMaterialRegistryCatalog).toHaveBeenCalledWith({ limit: 28, offset: 0, q: "Item 00" }, expect.any(AbortSignal));
    } finally {
      styleSpy.mockRestore();
      globalThis.ResizeObserver = OriginalObserver;
    }
  });

  it("clamps page navigation to the last page when the catalog shrinks", async () => {
    const liveEntries = manyEntries(50);
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue(statusWith([]));
    vi.mocked(fetchMaterialRegistryCatalog).mockImplementation(serveCatalog(liveEntries));

    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByText("Item 00 PLA")).toBeInTheDocument();
    liveEntries.splice(PAGE_SIZE);
    fireEvent.click(screen.getByRole("button", { name: /第 3 页|page 3/i }));

    await waitFor(() => {
      expect(fetchMaterialRegistryCatalog).toHaveBeenCalledWith({ limit: PAGE_SIZE, offset: PAGE_SIZE * 2 }, expect.any(AbortSignal));
    });
    await waitFor(() => {
      expect(screen.getAllByRole("article")).toHaveLength(24);
    });
    expect(screen.getByText("Item 00 PLA")).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(PAGE_SIZE);
    expect(screen.queryByText(/没有匹配的云端耗材|No matching cloud materials/i)).not.toBeInTheDocument();
  });

  it("does not fetch the full catalog when nothing is installed locally", async () => {
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue(statusWith([]));
    vi.mocked(fetchMaterialRegistryCatalog).mockImplementation(serveCatalog(manyEntries(30)));

    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByText("Item 00 PLA")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /可更新|Updates/i })).toHaveTextContent("0");

    fireEvent.click(screen.getByRole("button", { name: /可更新|Updates/i }));
    expect(await screen.findByText(/没有匹配的云端耗材|No matching cloud materials/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "清除筛选" }));
    expect(await screen.findByText("Item 00 PLA")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /全部/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: "清除筛选" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /未安装|Not installed/i }));
    expect(await screen.findByText("Item 00 PLA")).toBeInTheDocument();
    expect(fetchMaterialRegistryCatalog).not.toHaveBeenCalledWith({}, expect.any(AbortSignal));
  });

  it("uses the full catalog for exact update counts, state filters, and local paging", async () => {
    const entries = manyEntries(30);
    entries[27] = { ...entries[27], revision_id: "rev_newer", content_hash: "sha256:newer" };
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue(statusWith([
      makeInstalled("mat_03"),
      makeInstalled("mat_27", { display_name: "Item 27 PLA" }),
    ]));
    vi.mocked(fetchMaterialRegistryCatalog).mockImplementation(serveCatalog(entries));

    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByText("Item 00 PLA")).toBeInTheDocument();
    await waitFor(() => {
      expect(fetchMaterialRegistryCatalog).toHaveBeenCalledWith({}, expect.any(AbortSignal));
    });
    await waitFor(() => expect(screen.getByRole("button", { name: /可更新|Updates/i })).toHaveTextContent("1"));
    expect(screen.getByRole("button", { name: /已安装|Installed/i })).toHaveTextContent("1");
    expect(screen.getByRole("button", { name: /未安装|Not installed/i })).toHaveTextContent("28");

    vi.mocked(fetchMaterialRegistryCatalog).mockClear();
    fireEvent.click(screen.getByRole("button", { name: /下一页|next/i }));
    expect(await screen.findByText("Item 29 PLA")).toBeInTheDocument();
    expect(fetchMaterialRegistryCatalog).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /可更新|Updates/i }));
    await waitFor(() => {
      expect(screen.getAllByRole("article")).toHaveLength(1);
    });
    expect(screen.getByText("Item 27 PLA")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("offers a retry when the full catalog cannot be loaded for a state filter", async () => {
    const serve = serveCatalog([...defaultCatalog(), ...manyEntries(30)]);
    let failFullCatalog = true;
    vi.mocked(fetchMaterialRegistryCatalog).mockImplementation(async (query) => {
      if (query?.limit === undefined && failFullCatalog) {
        throw new Error("full catalog unavailable");
      }
      return serve(query);
    });

    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByText("Silk PETG")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /可更新|Updates/i }));
    const warning = await screen.findByTestId("material-cloud-full-catalog-failed");

    failFullCatalog = false;
    fireEvent.click(within(warning).getByRole("button", { name: /重试|retry/i }));

    await waitFor(() => {
      expect(screen.getAllByRole("article")).toHaveLength(1);
    });
    expect(screen.getByText("PLA Pro")).toBeInTheDocument();
  });

  it("reloads the first cloud catalog page when searching", async () => {
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue(statusWith([]));
    vi.mocked(fetchMaterialRegistryCatalog).mockImplementation(serveCatalog([
      ...manyEntries(30),
      makeEntry("mat_petg", "Silk PETG", { local_directory: "BrandB/petg-silk" }),
    ]));

    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByText("Item 00 PLA")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /下一页|next/i }));
    expect(await screen.findByText("Item 24 PLA")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "PETG" },
    });

    await waitFor(() => {
      expect(fetchMaterialRegistryCatalog).toHaveBeenCalledWith({ limit: PAGE_SIZE, offset: 0, q: "PETG" }, expect.any(AbortSignal));
    });
    await waitFor(() => {
      expect(screen.getAllByRole("article")).toHaveLength(1);
    });
    expect(screen.getByText("Silk PETG")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("debounces rapid typing while keeping refresh and clear immediate", async () => {
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue(statusWith([]));
    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByText("Silk PETG")).toBeInTheDocument();
    vi.mocked(fetchMaterialRegistryCatalog).mockClear();
    vi.useFakeTimers();

    const searchInput = screen.getByRole("searchbox");
    fireEvent.change(searchInput, { target: { value: "P" } });
    fireEvent.change(searchInput, { target: { value: "PE" } });
    fireEvent.change(searchInput, { target: { value: "PETG" } });

    expect(fetchMaterialRegistryCatalog).not.toHaveBeenCalled();
    await act(async () => {
      vi.advanceTimersByTime(399);
      await Promise.resolve();
    });
    expect(fetchMaterialRegistryCatalog).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(1);
      await Promise.resolve();
    });
    expect(fetchMaterialRegistryCatalog).toHaveBeenCalledTimes(1);
    expect(fetchMaterialRegistryCatalog).toHaveBeenLastCalledWith({ limit: PAGE_SIZE, offset: 0, q: "PETG" }, expect.any(AbortSignal));

    vi.mocked(fetchMaterialRegistryCatalog).mockClear();
    fireEvent.change(searchInput, { target: { value: "PLA" } });
    fireEvent.click(screen.getByRole("button", { name: /刷新云端目录|refresh catalog/i }));
    await act(async () => {
      await Promise.resolve();
    });
    const refreshedRequests = [[{ limit: PAGE_SIZE, offset: 0, q: "PLA", refresh: true }, expect.any(AbortSignal)], [{}, expect.any(AbortSignal)]];
    expect(vi.mocked(fetchMaterialRegistryCatalog).mock.calls).toEqual(refreshedRequests);

    await act(async () => {
      vi.advanceTimersByTime(400);
      await Promise.resolve();
    });
    expect(vi.mocked(fetchMaterialRegistryCatalog).mock.calls).toEqual(refreshedRequests);

    vi.mocked(fetchMaterialRegistryCatalog).mockClear();
    fireEvent.change(searchInput, { target: { value: "" } });
    await act(async () => {
      await Promise.resolve();
    });
    expect(fetchMaterialRegistryCatalog).toHaveBeenCalledTimes(1);
    expect(fetchMaterialRegistryCatalog).toHaveBeenLastCalledWith({ limit: PAGE_SIZE, offset: 0 }, expect.any(AbortSignal));
  });

  it("refreshes the metadata index to show a newly published foreign alias", async () => {
    const first = makeEntry("first", "First material");
    const published = makeEntry("published", "新增材料", { display: { material_name: "新增材料", aliases: ["Fresh alias"] } });
    const entries = [first];
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue(statusWith([]));
    vi.mocked(fetchMaterialRegistryCatalog).mockImplementation(async (params = {}) => catalogPage(params.q ? [] : [...entries]));
    render(<MaterialCloudSyncPanel />);
    await screen.findByText("First material");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Fresh alias" } });
    await screen.findByText(/没有匹配的云端耗材/);
    entries.push(published);
    fireEvent.click(screen.getByRole("button", { name: /刷新云端目录|refresh catalog/i }));
    expect(await screen.findByRole("button", { name: /新增材料/ })).toBeInTheDocument();
    expect(installMaterialRegistryCatalogEntry).not.toHaveBeenCalled();
  });

  it("refreshes the latest query when installation finishes during debounce", async () => {
    type InstallResponse = Awaited<ReturnType<typeof installMaterialRegistryCatalogEntry>>;
    let resolveInstall!: (value: InstallResponse) => void;
    const pendingInstall = new Promise<InstallResponse>((resolve) => {
      resolveInstall = resolve;
    });
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue(statusWith([]));
    vi.mocked(installMaterialRegistryCatalogEntry).mockReturnValueOnce(pendingInstall);

    render(<MaterialCloudSyncPanel />);
    expect(await screen.findByText("Silk PETG")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: /下载到本地|download/i })[0]);
    await waitFor(() => {
      expect(installMaterialRegistryCatalogEntry).toHaveBeenCalledTimes(1);
    });

    vi.mocked(fetchMaterialRegistryCatalog).mockClear();
    vi.useFakeTimers();
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "PLA" },
    });
    expect(fetchMaterialRegistryCatalog).not.toHaveBeenCalled();

    await act(async () => {
      resolveInstall({ status: "ok", message: "installed", installed_count: 1, installed_materials: [] });
      await pendingInstall;
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(fetchMaterialRegistryCatalog).toHaveBeenCalledTimes(1);
    expect(fetchMaterialRegistryCatalog).toHaveBeenLastCalledWith({ limit: PAGE_SIZE, offset: 0, q: "PLA" }, expect.any(AbortSignal));

    await act(async () => {
      vi.advanceTimersByTime(400);
      await Promise.resolve();
    });
    expect(fetchMaterialRegistryCatalog).toHaveBeenCalledTimes(1);
  });

  it("ignores an older search response that resolves after the latest query", async () => {
    let resolveOlder!: (value: CatalogResponse) => void;
    let resolveLatest!: (value: CatalogResponse) => void;
    const olderResponse = new Promise<CatalogResponse>((resolve) => {
      resolveOlder = resolve;
    });
    const latestResponse = new Promise<CatalogResponse>((resolve) => {
      resolveLatest = resolve;
    });
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue(statusWith([]));

    render(<MaterialCloudSyncPanel />);
    expect(await screen.findByText("Silk PETG")).toBeInTheDocument();

    vi.useFakeTimers();
    vi.mocked(fetchMaterialRegistryCatalog).mockImplementation((query) => {
      if (query?.q === "P") {
        return olderResponse;
      }
      if (query?.q === "PLA") {
        return latestResponse;
      }
      throw new Error(`unexpected query: ${query?.q ?? ""}`);
    });

    const searchInput = screen.getByRole("searchbox");
    fireEvent.change(searchInput, { target: { value: "P" } });
    await act(async () => {
      vi.advanceTimersByTime(400);
      await Promise.resolve();
    });
    fireEvent.change(searchInput, { target: { value: "PLA" } });
    await act(async () => {
      vi.advanceTimersByTime(400);
      await Promise.resolve();
    });

    await act(async () => {
      resolveLatest(catalogPage([makeEntry("mat_latest", "Latest PLA")]));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText("Latest PLA")).toBeInTheDocument();

    await act(async () => {
      resolveOlder(catalogPage([makeEntry("mat_older", "Stale PLA")]));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText("Latest PLA")).toBeInTheDocument();
    expect(screen.queryByText("Stale PLA")).not.toBeInTheDocument();
  });

  it("ignores a stale page response after a new search", async () => {
    let resolveOlderPage!: (value: CatalogResponse) => void;
    let resolveLatestSearch!: (value: CatalogResponse) => void;
    const olderPage = new Promise<CatalogResponse>((resolve) => {
      resolveOlderPage = resolve;
    });
    const latestSearch = new Promise<CatalogResponse>((resolve) => {
      resolveLatestSearch = resolve;
    });
    const serveFirstPage = serveCatalog(manyEntries(30));
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue(statusWith([]));
    vi.mocked(fetchMaterialRegistryCatalog).mockImplementation((query) => {
      if (query?.q === "Fresh") {
        return latestSearch;
      }
      if (query?.offset === PAGE_SIZE) {
        return olderPage;
      }
      return serveFirstPage(query);
    });

    render(<MaterialCloudSyncPanel />);
    expect(await screen.findByText("Item 00 PLA")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /下一页|next/i }));
    await waitFor(() => {
      expect(fetchMaterialRegistryCatalog).toHaveBeenCalledWith({ limit: PAGE_SIZE, offset: PAGE_SIZE }, expect.any(AbortSignal));
    });

    vi.useFakeTimers();
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "Fresh" },
    });
    await act(async () => {
      vi.advanceTimersByTime(400);
      await Promise.resolve();
    });
    expect(fetchMaterialRegistryCatalog).toHaveBeenCalledWith({ limit: PAGE_SIZE, offset: 0, q: "Fresh" }, expect.any(AbortSignal));

    await act(async () => {
      resolveLatestSearch(catalogPage([makeEntry("mat_fresh", "Fresh PLA")]));
      await latestSearch;
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText("Fresh PLA")).toBeInTheDocument();

    await act(async () => {
      resolveOlderPage(catalogPage(
        [makeEntry("mat_stale_page", "Stale Page PETG")],
        { offset: PAGE_SIZE, totalCount: 30 },
      ));
      await olderPage;
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText("Fresh PLA")).toBeInTheDocument();
    expect(screen.queryByText("Stale Page PETG")).not.toBeInTheDocument();
  });

  it("updates an installed material when the catalog revision is newer", async () => {
    render(<MaterialCloudSyncPanel />);

    expect((await screen.findAllByText("PLA Pro")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: /^(更新|Update)$/i }));

    await waitFor(() => {
      expect(installMaterialRegistryCatalogEntry).toHaveBeenCalledWith({
        material_id: "mat_update",
        revision_id: "rev_2",
        package_url: "/v1/packages/mat_update/rev_2.zip",
        package_sha256: "b".repeat(64),
      });
    });
    expect(await screen.findByText("已更新「PLA Pro」")).toBeInTheDocument();
  });

  it("offers recovery for missing files and hides redundant uninstalled card status", async () => {
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue(statusWith([
      makeInstalled("mat_test", { revision_id: "rev_new", material_file_exists: false, local_exists: false }),
    ]));
    render(<MaterialCloudSyncPanel />);
    const missing = (await screen.findByText("PLA Basic")).closest("article")!;
    expect(missing).toHaveTextContent("本地文件缺失");
    fireEvent.click(within(missing).getByRole("button", { name: "重新下载" }));
    expect(await screen.findByText("已重新下载「PLA Basic」")).toBeInTheDocument();
    const other = screen.getByText("PLA Pro").closest("article")!;
    expect(other).not.toHaveTextContent("未安装");
    expect(within(other).getByRole("button", { name: "下载到本地" })).toBeInTheDocument();
  });

  it("does not count locally available historical catalog revisions as updates", async () => {
    const [plaBasic, ...rest] = defaultCatalog();
    vi.mocked(fetchMaterialRegistryCatalog).mockImplementation(serveCatalog([
      { ...plaBasic, revision_id: "rev_old", content_hash: "sha256:old", package_sha256: "d".repeat(64) },
      ...rest,
    ]));

    render(<MaterialCloudSyncPanel />);

    expect((await screen.findAllByText("PLA Basic")).length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.getByRole("button", { name: /可更新|Updates/i })).toHaveTextContent("1"));
    expect(screen.getByText("PLA Basic").closest("article")).not.toHaveTextContent(/有新版本|update available/i);
    expect(screen.queryByRole("button", { name: /更新到 old|update to old/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^(更新|Update)$/i })).toBeInTheDocument();
  });

  it("treats matching local directory and content hash as installed when material ids differ", async () => {
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue(statusWith([
      makeInstalled("mat_local_identity", {
        revision_id: "rev_local",
        content_hash: "sha256:exact",
        channel: "local",
        source: "local",
        local_directory: "BrandC/pla-local",
        display_name: "PLA Local",
        available_revisions: ["rev_local"],
      }),
    ]));
    vi.mocked(fetchMaterialRegistryCatalog).mockImplementation(serveCatalog([
      makeEntry("mat_cloud_identity", "PLA Local", {
        revision_id: "rev_cloud",
        content_hash: "sha256:exact",
        local_directory: "BrandC/pla-local",
      }),
    ]));

    render(<MaterialCloudSyncPanel />);

    expect((await screen.findAllByText("PLA Local")).length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.getByRole("button", { name: /可更新|Updates/i })).toHaveTextContent("0"));
    expect(screen.getByText("PLA Local").closest("article")).toHaveTextContent(/已安装|installed/i);
    expect(screen.queryByRole("button", { name: /^(已安装|Installed)$/i })).not.toBeInTheDocument();
    expect(screen.queryByTestId("material-cloud-local-installed-section")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /下载到本地|download/i })).not.toBeInTheDocument();
  });

  it("does not render missing sync-index entries in the local revision notice", async () => {
    vi.mocked(fetchMaterialSyncStatus).mockResolvedValue(statusWith([
      makeInstalled("mat_missing", {
        display_name: "Missing PLA",
        local_exists: false,
        material_file_exists: false,
        available_revisions: ["rev_missing", "rev_older"],
      }),
    ]));
    vi.mocked(fetchMaterialRegistryCatalog).mockImplementation(serveCatalog([]));

    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByText(/没有匹配的云端耗材|No matching cloud materials/i)).toBeInTheDocument();
    expect(screen.queryByTestId("material-cloud-local-installed-section")).not.toBeInTheDocument();
    expect(screen.queryByText("Missing PLA")).not.toBeInTheDocument();
  });

  it("keeps local history closed until requested", async () => {
    render(<MaterialCloudSyncPanel />);
    await screen.findByText("Silk PETG");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    openLocalRevisions();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("PLA Basic");
    expect(within(dialog).getAllByRole("radio")).toHaveLength(1);
  });

  it("rolls back from the local revision notice when catalog search hides the card", async () => {
    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByText("Silk PETG")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "Silk" },
    });
    await waitFor(() => {
      expect(screen.getAllByRole("article")).toHaveLength(1);
    });

    openLocalRevisions();
    fireEvent.click(screen.getAllByRole("radio")[0]);
    fireEvent.click(screen.getByRole("button", { name: /恢复所选版本|Restore selected/ }));

    await waitFor(() => {
      expect(rollbackMaterialSyncRevision).toHaveBeenCalledWith("mat_test", "rev_old");
    });
  });

  it("keeps local rollback controls available when catalog loading fails", async () => {
    vi.mocked(fetchMaterialRegistryCatalog).mockRejectedValue(new Error("catalog unavailable"));

    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByTestId("material-cloud-sync-error")).toHaveTextContent("catalog unavailable");

    openLocalRevisions();
    fireEvent.click(screen.getAllByRole("radio")[0]);
    fireEvent.click(screen.getByRole("button", { name: /恢复所选版本|Restore selected/ }));

    await waitFor(() => {
      expect(rollbackMaterialSyncRevision).toHaveBeenCalledWith("mat_test", "rev_old");
    });
  });

  it("shows an offline notice when the cloud registry URL is not configured", async () => {
    vi.mocked(fetchMaterialRegistryCatalog).mockRejectedValue(Object.assign(
      new Error("Request failed with status code 422"),
      { response: { status: 422, data: { detail: "Material registry URL is not configured" } } },
    ));

    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByTestId("material-cloud-sync-notice")).toHaveTextContent(/未配置|not configured/i);
    expect(screen.queryByTestId("material-cloud-sync-error")).not.toBeInTheDocument();
    expect(screen.queryByText("Request failed with status code 422")).not.toBeInTheDocument();
    expect(screen.queryByText(/没有匹配的云端耗材|No matching cloud materials/i)).not.toBeInTheDocument();

    openLocalRevisions();
    expect(screen.getAllByRole("radio")[0]).toBeEnabled();
  });

  it("renders installed catalog status and rolls back a previous revision", async () => {
    render(<MaterialCloudSyncPanel />);

    expect(await screen.findByText("PLA Basic")).toBeInTheDocument();
    expect(screen.queryByTestId("material-cloud-filter-official")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^(已安装|Installed)$/i })).not.toBeInTheDocument();

    openLocalRevisions();
    fireEvent.click(screen.getAllByRole("radio")[0]);
    fireEvent.click(screen.getByRole("button", { name: /恢复所选版本|Restore selected/ }));

    await waitFor(() => {
      expect(rollbackMaterialSyncRevision).toHaveBeenCalledWith("mat_test", "rev_old");
    });
    await waitFor(() => {
      expect(fetchMaterialSyncStatus).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByTestId("material-cloud-sync-success")).toHaveTextContent(/耗材版本已回滚|Material revision rolled back/i);
  });
});
