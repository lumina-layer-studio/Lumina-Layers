import { beforeEach, describe, expect, it, vi } from "vitest";
import "./communityTestMocks";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import LutCloudSyncPanel from "../components/LutCloudSyncPanel";
import {
  fetchCloudLutRegistryCatalog,
  fetchCloudLutRegistryStatus,
  fetchCloudLutPreviews,
  installCloudLut,
  restoreCloudLutRevision,
} from "../api/lut";

vi.mock("../api/lut", () => ({
  fetchCloudLutRegistryCatalog: vi.fn(),
  fetchCloudLutRegistryStatus: vi.fn(),
  fetchCloudLutPreviews: vi.fn(),
  installCloudLut: vi.fn(),
  restoreCloudLutRevision: vi.fn(),
}));

describe("LutCloudSyncPanel", () => {
  it("recognizes a single declared color mode from the public compatibility list", async () => {
    const baseline = await fetchCloudLutRegistryCatalog();
    vi.mocked(fetchCloudLutRegistryCatalog).mockResolvedValue({ ...baseline, total: 1, items: [{
      ...baseline.items[0], lut_id: "plural-mode", display: { name: "Plural mode calibration", manufacturer: "Lumina Demo", material_type: "PLA" },
      compatibility: { color_modes: ["5-Color Extended"] },
    }] });
    render(<LutCloudSyncPanel />);
    const card = (await screen.findByText("Plural mode calibration")).closest("article")!;
    expect(card).toHaveTextContent("5 色");
    expect(card).not.toHaveTextContent("未知");
  });

  it("distinguishes download, update and recovery without redundant not-downloaded labels", async () => {
    const baseline = await fetchCloudLutRegistryCatalog();
    const states = ["not_installed", "installed", "update_available", "local_missing", "local_modified", "local_available"];
    vi.mocked(fetchCloudLutRegistryCatalog).mockResolvedValue({
      ...baseline, total: states.length, items: states.map(local_state => ({
        ...baseline.items[0], lut_id: local_state, local_state, display: { name: local_state },
      })),
    });
    render(<LutCloudSyncPanel />);
    const first = (await screen.findByText("not_installed")).closest("article")!;
    expect(first).not.toHaveTextContent("未下载");
    expect(within(first).getByRole("button", { name: "下载到本地" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^可更新/ }));
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(screen.getByRole("article")).toHaveTextContent("与本地当前版本不同");
    fireEvent.click(screen.getByRole("button", { name: "更新" }));
    await waitFor(() => expect(installCloudLut).toHaveBeenCalledWith(expect.objectContaining({ lut_id: "update_available" })));
    expect(await screen.findByText("已更新「update_available」")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^未安装/ }));
    const missing = screen.getByText("local_missing").closest("article")!;
    fireEvent.click(within(missing).getByRole("button", { name: "重新下载" }));
    await waitFor(() => expect(installCloudLut).toHaveBeenCalledWith(expect.objectContaining({ lut_id: "local_missing" })));
    expect(await screen.findByText("已重新下载「local_missing」")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^已安装/ }));
    expect(screen.getAllByRole("article")).toHaveLength(2);
  });

  it("restores verified local LUT history even when the remote catalog is offline", async () => {
    const baseline = await fetchCloudLutRegistryStatus();
    vi.mocked(fetchCloudLutRegistryStatus).mockResolvedValue({ ...baseline, history: [{
      resource_id: "lut-1", name: "Historical LUT", current_revision: "new",
      revisions: [
        { revision_id: "new", installed_at: "2026-11-15T10:00:00Z", available: true },
        { revision_id: "old", installed_at: "2026-11-01T10:00:00Z", available: true },
        { revision_id: "missing", installed_at: "2026-10-01T10:00:00Z", available: false },
      ],
    }] });
    vi.mocked(fetchCloudLutRegistryCatalog).mockRejectedValue(new Error("offline"));
    vi.mocked(restoreCloudLutRevision).mockResolvedValue({} as Awaited<ReturnType<typeof restoreCloudLutRevision>>);
    render(<LutCloudSyncPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "本地历史版本" }));
    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByText("Historical LUT")).toBeInTheDocument();
    const radios = within(dialog).getAllByRole("radio");
    expect(radios[1]).toBeDisabled();
    fireEvent.click(radios[0]);
    fireEvent.click(within(dialog).getByRole("button", { name: "恢复所选版本" }));
    await waitFor(() => expect(restoreCloudLutRevision).toHaveBeenCalledWith("lut-1", "old"));
    expect(installCloudLut).not.toHaveBeenCalled();
    expect(dialog).not.toHaveTextContent("sha256");
  });

  const previewPng = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGN4qGsEAAMzAUGNjL54AAAAAElFTkSuQmCC";

  async function preparePreviewCatalog(count: number) {
    const catalog = await fetchCloudLutRegistryCatalog();
    const items = Array.from({ length: count }, (_, i) => ({
      ...catalog.items[0], lut_id: `preview_${i}`,
      display: { name: `Preview ${i}`, lut_board_available: true },
    }));
    vi.mocked(fetchCloudLutRegistryCatalog).mockClear().mockResolvedValue({
      ...catalog, source_scope: "preview-source", items, total: items.length,
    });
    vi.mocked(fetchCloudLutPreviews).mockReset().mockImplementation(async (ids) => ({
      source_scope: "preview-source", previews: items.filter((row) => ids.includes(row.lut_id)).map((row) => ({
        lut_id: row.lut_id, revision_id: row.revision_id, content_hash: row.content_hash,
        display: { lut_board_preview: { family: "board", set_size: 1, pages: [
          { number: 1, rows: 32, cols: 32, padding: 1, count: 1024, png: previewPng },
        ] } },
      })),
    }));
    return items;
  }

  it("fetches one page of preview colors and reuses them when returning to a page", async () => {
    await preparePreviewCatalog(30);
    const { container } = render(<LutCloudSyncPanel />);
    await waitFor(() => expect(container.querySelectorAll(".calibration-thumbnail")).toHaveLength(24));
    expect(screen.getAllByRole("article")).toHaveLength(24);
    expect(fetchCloudLutPreviews).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fetchCloudLutPreviews).mock.calls[0][0]).toHaveLength(24);
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() => expect(container.querySelectorAll(".calibration-thumbnail")).toHaveLength(6));
    expect(fetchCloudLutPreviews).toHaveBeenCalledTimes(2);
    expect(vi.mocked(fetchCloudLutPreviews).mock.calls[1][0]).toHaveLength(6);
    fireEvent.click(screen.getByRole("button", { name: "上一页" }));
    expect(container.querySelectorAll(".calibration-thumbnail")).toHaveLength(24);
    expect(fetchCloudLutPreviews).toHaveBeenCalledTimes(2);
    expect(installCloudLut).not.toHaveBeenCalled();
  });

  it("lets a failed preview page retry without downloading a LUT or restarting the directory", async () => {
    await preparePreviewCatalog(1);
    vi.mocked(fetchCloudLutPreviews).mockRejectedValueOnce(new Error("offline"));
    const { container } = render(<LutCloudSyncPanel />);
    await screen.findByText("色卡加载失败，可以重试。");
    expect(container.querySelector(".calibration-thumbnail")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(container.querySelector(".calibration-thumbnail")).toBeInTheDocument());
    expect(fetchCloudLutRegistryCatalog).toHaveBeenCalledTimes(1);
    expect(installCloudLut).not.toHaveBeenCalled();
  });

  it("adapts cloud LUT pages to the grid while reusing the catalog and keeping the selected LUT", async () => {
    await preparePreviewCatalog(60);
    let columns = 5;
    let resized: () => void = () => {};
    const computedStyle = window.getComputedStyle.bind(window);
    const styleSpy = vi.spyOn(window, "getComputedStyle").mockImplementation((element) =>
      new Proxy(computedStyle(element), { get: (target, key) => key === "gridTemplateColumns"
        ? Array(columns).fill("250px").join(" ") : Reflect.get(target, key) }));
    const OriginalObserver = globalThis.ResizeObserver;
    globalThis.ResizeObserver = class {
      constructor(callback: () => void) { resized = callback; }
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
    try {
      const { container } = render(<LutCloudSyncPanel />);
      await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(25));
      await waitFor(() => expect(container.querySelectorAll("article .calibration-thumbnail")).toHaveLength(25));
      fireEvent.click(screen.getByRole("button", { name: "下一页" }));
      await waitFor(() => expect(container.querySelectorAll("article .calibration-thumbnail")).toHaveLength(25));
      const selectedName = screen.getAllByRole("article")[24].querySelector("button")!.textContent!;
      fireEvent.click(within(screen.getAllByRole("article")[24]).getAllByRole("button")[0]);
      const heading = within(screen.getByRole("complementary")).getByRole("heading").textContent;
      columns = 4;
      act(() => resized());
      expect(screen.getAllByRole("article")).toHaveLength(12);
      await waitFor(() => expect(container.querySelectorAll("article .calibration-thumbnail")).toHaveLength(12));
      expect(within(screen.getByRole("complementary")).getByRole("heading")).toHaveTextContent(heading!);
      expect(screen.getAllByRole("article").some((card) => card.querySelector("button")?.textContent === selectedName)).toBe(true);
      expect(fetchCloudLutRegistryCatalog).toHaveBeenCalledTimes(1);
      expect(installCloudLut).not.toHaveBeenCalled();
    } finally {
      styleSpy.mockRestore();
      globalThis.ResizeObserver = OriginalObserver;
    }
  });

  it("rejects artwork returned for a different source", async () => {
    await preparePreviewCatalog(1);
    vi.mocked(fetchCloudLutPreviews).mockResolvedValueOnce({ source_scope: "other-source", previews: [] });
    const { container } = render(<LutCloudSyncPanel />);
    await screen.findByText("色卡加载失败，可以重试。");
    expect(container.querySelector(".calibration-thumbnail")).toBeNull();
    expect(installCloudLut).not.toHaveBeenCalled();
  });

  it.each(["missing", "different-revision"])("keeps a %s preview retryable instead of caching an empty board", async (failure) => {
    const [entry] = await preparePreviewCatalog(1);
    const validResponse = await fetchCloudLutPreviews([entry.lut_id], ["official"], new AbortController().signal);
    vi.mocked(fetchCloudLutPreviews).mockClear().mockResolvedValueOnce({
      ...validResponse,
      previews: failure === "missing" ? [] : validResponse.previews.map((row) => ({ ...row, revision_id: "other" })),
    });
    const { container } = render(<LutCloudSyncPanel />);
    await screen.findByText("色卡加载失败，可以重试。");
    expect(container.querySelector(".calibration-thumbnail")).toBeNull();
    expect(fetchCloudLutPreviews).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(container.querySelector(".calibration-thumbnail")).toBeInTheDocument());
    expect(fetchCloudLutPreviews).toHaveBeenCalledTimes(2);
    expect(installCloudLut).not.toHaveBeenCalled();
  });

  it("finds international aliases and the package code while keeping the original LUT identity on install", async () => {
    const catalog = await fetchCloudLutRegistryCatalog();
    const entry = { ...catalog.items[0], display: { name: "作者色表", manufacturer: "赛纳",
      market_names: { CN: "深红色表", INTL: "Deep Red Table" }, sku: "SN-001", aliases: ["Dark garnet"] } };
    vi.mocked(fetchCloudLutRegistryCatalog).mockResolvedValue({ ...catalog, items: [entry], total: 1 });
    render(<LutCloudSyncPanel />);
    await screen.findByText("深红色表");
    for (const query of ["Deep Red Table", "Dark garnet", "SN-001"]) {
      fireEvent.change(screen.getByRole("searchbox"), { target: { value: query } });
      expect(screen.getByRole("button", { name: /深红色表/ })).toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole("button", { name: /深红色表/ }));
    const detail = screen.getByRole("complementary");
    expect(detail).toHaveTextContent("作者色表");
    expect(detail).toHaveTextContent("SN-001");
    expect(installCloudLut).not.toHaveBeenCalled();
    fireEvent.click(within(detail).getByRole("button", { name: /下载到本地/ }));
    await waitFor(() => expect(installCloudLut).toHaveBeenCalledWith(entry));
    expect(installCloudLut).toHaveBeenCalledTimes(1);
  });
  it("retains the successful catalog and does not announce success after a failed refresh", async () => {
    render(<LutCloudSyncPanel />);
    await screen.findByRole("button", { name: /Official CMYW LUT/ });
    vi.mocked(fetchCloudLutRegistryCatalog).mockRejectedValueOnce(new Error("offline"));
    fireEvent.click(screen.getByRole("button", { name: /刷新|Refresh/i }));
    await waitFor(() => expect(screen.getByText(/offline/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /Official CMYW LUT/ })).toBeInTheDocument();
    expect(screen.queryByText(/目录已刷新|Catalog refreshed/i)).not.toBeInTheDocument();
  });
  it("identifies offline catalog snapshots while keeping downloads explicit", async () => {
    const response = await fetchCloudLutRegistryCatalog();
    vi.mocked(fetchCloudLutRegistryCatalog).mockResolvedValue({ ...response, cached: true, fetched_at: "2026-11-05T00:00:00Z" });
    render(<LutCloudSyncPanel />);
    expect(await screen.findByText(/当前显示本地缓存目录/)).toHaveTextContent(/下载新资源需联网/);
    expect(installCloudLut).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /Official CMYW LUT/ })).toBeInTheDocument();
  });
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchCloudLutRegistryStatus).mockResolvedValue({
      configured: true,
      base_url: "https://registry.example.test",
      channels: ["official", "community"],
      installed_count: 1,
    });
    vi.mocked(fetchCloudLutRegistryCatalog).mockResolvedValue({
      configured: true,
      channels: ["official", "community"],
      total: 2,
      items: [
        {
          lut_id: "lut_4c_cmyw",
          revision_id: "rev_a",
          content_hash: "a".repeat(64),
          package_url: "/luts/lut_4c_cmyw.zip",
          package_sha256: "b".repeat(64),
          package_bytes: 2048,
          local_path: "Official/CMYW.json",
          channel: "official",
          visibility: "official",
          display: {
            name: "Official CMYW LUT",
            manufacturer: "Lumina",
          },
          compatibility: {
            color_mode: "4-Color (CMYW)",
          },
        },
        {
          lut_id: "lut_bw",
          revision_id: "rev_b",
          content_hash: "c".repeat(64),
          package_url: "/luts/lut_bw.zip",
          package_sha256: "d".repeat(64),
          package_bytes: 1024,
          local_path: "Community/BW.json",
          channel: "community",
          visibility: "community",
          display: {
            name: "BW LUT",
            manufacturer: "Lumina",
          },
          compatibility: {
            color_mode: "BW (Black & White)",
          },
        },
      ],
    });
    vi.mocked(installCloudLut).mockResolvedValue({
      lut_id: "lut_4c_cmyw",
      revision_id: "rev_a",
      content_hash: "a".repeat(64),
      package_url: "/luts/lut_4c_cmyw.zip",
      package_sha256: "b".repeat(64),
      package_bytes: 2048,
      local_path: "Official/CMYW.json",
      installed_path: "Cloud/Official/CMYW.json",
      installed_at: "2026-06-24T01:02:03Z",
    });
  });

  it("opens details without installing and keeps search available without comparison tabs", async () => {
    render(<LutCloudSyncPanel />);
    const card = await screen.findByRole("button", { name: /Official CMYW LUT/ });
    fireEvent.click(card);
    expect(installCloudLut).not.toHaveBeenCalled();
    expect(screen.queryByText("Official/CMYW.json")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /关闭|Close/i })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("button", { name: /关闭|Close/i }), { key: "Escape" });
    expect(card).toHaveFocus();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "BW LUT" } });
    expect(screen.queryByRole("button", { name: /Official CMYW LUT/ })).not.toBeInTheDocument();
    expect(screen.getByRole("searchbox")).toHaveValue("BW LUT");
    expect(screen.getByRole("searchbox")).toHaveValue("BW LUT");
  });

  it("loads remaining catalog pages in the new view so search finds later entries", async () => {
    const baseline = await fetchCloudLutRegistryCatalog();
    vi.mocked(fetchCloudLutRegistryCatalog).mockClear();
    vi.mocked(fetchCloudLutRegistryCatalog)
      .mockResolvedValueOnce({ ...baseline, total: 2, items: [baseline.items[0]] })
      .mockResolvedValueOnce({ ...baseline, total: 2, items: [baseline.items[1]] });
    render(<LutCloudSyncPanel />);
    await waitFor(() => expect(fetchCloudLutRegistryCatalog).toHaveBeenCalledWith(expect.objectContaining({ offset: 1 })));
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "BW LUT" } });
    expect(await screen.findByRole("button", { name: /BW LUT/ })).toBeInTheDocument();
  });

  it("keeps a missing search provisional until the remaining index arrives", async () => {
    const baseline = await fetchCloudLutRegistryCatalog();
    let finish!: (value: typeof baseline) => void;
    vi.mocked(fetchCloudLutRegistryCatalog).mockClear()
      .mockResolvedValueOnce({ ...baseline, total: 2, items: [baseline.items[0]] })
      .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    render(<LutCloudSyncPanel initialQuery="BW LUT" />);
    await waitFor(() => expect(fetchCloudLutRegistryCatalog).toHaveBeenCalledTimes(2));
    expect(screen.getByText("已加载的条目中暂未找到，完整目录仍在加载。")).toBeInTheDocument();
    expect(screen.queryByText(/没有匹配的云端 LUT/)).not.toBeInTheDocument();
    finish({ ...baseline, total: 2, items: [baseline.items[1]] });
    expect(await screen.findByRole("button", { name: /BW LUT/ })).toBeInTheDocument();
    expect(screen.queryByText("已加载的条目中暂未找到，完整目录仍在加载。")).not.toBeInTheDocument();
    expect(installCloudLut).not.toHaveBeenCalled();
  });

  it("shows a clear notice when the cloud LUT registry is not configured", async () => {
    vi.mocked(fetchCloudLutRegistryStatus).mockResolvedValueOnce({
      configured: false,
      base_url: null,
      channels: ["official", "community"],
      installed_count: 0,
    });

    render(<LutCloudSyncPanel />);

    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(await screen.findByText(/尚未配置云端 LUT 库|not configured/i)).toHaveTextContent(/尚未配置云端 LUT 库|not configured/i);
    expect(screen.queryByText(/没有匹配的云端 LUT|No matching cloud LUTs/i)).not.toBeInTheDocument();
    expect(fetchCloudLutRegistryCatalog).not.toHaveBeenCalled();
  });

  it("renders cloud LUT catalog cards and installs a selected LUT", async () => {
    render(<LutCloudSyncPanel />);

    expect(await screen.findByText("Official CMYW LUT")).toBeInTheDocument();
    expect(screen.queryByText("community")).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "CMYW" },
    });

    await waitFor(() => {
      expect(screen.getAllByRole("article")).toHaveLength(1);
    });
    const card = screen.getByRole("article");
    expect(within(card).getByText("Official CMYW LUT")).toBeInTheDocument();
    expect(within(card).getByText("4 色 (CMYW)")).toBeInTheDocument();
    expect(within(card).queryByText("Official/CMYW.json")).not.toBeInTheDocument();

    fireEvent.click(within(card).getByRole("button", { name: /下载到本地|download/i }));

    await waitFor(() => {
      expect(installCloudLut).toHaveBeenCalledWith(
        expect.objectContaining({
          lut_id: "lut_4c_cmyw",
          revision_id: "rev_a",
        }),
      );
    });
    expect(await screen.findByText("已将「Official CMYW LUT」添加到本地。")).toBeInTheDocument();
  });

  it("marks a cloud LUT as installed when the matching preset exists locally", async () => {
    vi.mocked(fetchCloudLutRegistryCatalog).mockResolvedValueOnce({
      configured: true,
      channels: ["official"],
      total: 1,
      items: [
        {
          lut_id: "lut_existing",
          revision_id: "rev_existing",
          content_hash: "e".repeat(64),
          package_url: "/luts/existing.zip",
          package_sha256: "f".repeat(64),
          package_bytes: 1024,
          local_path: "Official/Test/Readable LUT.json",
          local_state: "local_available",
          local_exists: true,
          local_match_path: "Cloud/Actual/Readable LUT.json",
          channel: "official",
          visibility: "official",
          display: {
            name: "Readable LUT",
            manufacturer: "Lumina",
          },
          compatibility: {
            color_mode: "4-Color (RYBW)",
          },
        },
      ],
    });

    render(<LutCloudSyncPanel />);

    const card = await screen.findByRole("article");
    expect(within(card).getByText("Readable LUT")).toBeInTheDocument();
    expect(card).toHaveTextContent(/已安装|installed/i);
    expect(within(card).queryByRole("button", { name: /下载到本地|download/i })).not.toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: /Readable LUT/ }));
    expect(screen.getByText("Cloud/Actual/Readable LUT.json")).toBeInTheDocument();
    expect(screen.queryByText("Official/Test/Readable LUT.json")).not.toBeInTheDocument();
    expect(installCloudLut).not.toHaveBeenCalled();
  });
});
