import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import ResourceSourceSetting from "../components/ResourceSourceSetting";
import { fetchResourceStatus, saveResourceSource, type ResourceStatus } from "../api/resources";
import { useResourceStore } from "../stores/resourceStore";
import { useCommunityStore } from "../stores/communityStore";

vi.mock("../api/resources", () => ({ fetchResourceStatus: vi.fn(), saveResourceSource: vi.fn() }));

function status(mode: "default" | "github" | "mirror" = "default"): ResourceStatus {
  const url = mode === "mirror" ? "https://mirror.test/public/v1" : mode === "github" ? "https://github.test/public/v1" : "https://hosted.test/api";
  return {
    materials: { configured: true, provider: mode === "default" ? "registry" : "github", seed: { available: true, state: "ready" } },
    luts: { configured: true, provider: mode === "default" ? "registry" : "github", seed: { available: true, state: "ready" } },
    source_repository: "https://github.test/repo",
    source_settings: { mode, mirror_url: mode === "mirror" ? url : "", error: null,
      urls: { materials: url, luts: url }, default_urls: { materials: "https://hosted.test/api", luts: "https://hosted.test/api" }, default_provider: "registry" },
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(fetchResourceStatus).mockResolvedValue(status());
  useResourceStore.setState({ status: status(), error: null, generation: 0, catalogHealth: {},
    catalogSource: { materials: "cloud", luts: "offline" } });
  useCommunityStore.setState({ connection: { state: "connected", subject: "maker", display_name: "Maker", web_url: "https://account.test" },
    stats: { "luts:one": { value: null, time: 1 } }, epoch: 0 });
});

it("saves the selected mirror for both catalogs and keeps the community account and offline selection", async () => {
  vi.mocked(saveResourceSource).mockResolvedValue(status("mirror"));
  render(<ResourceSourceSetting compact />);
  fireEvent.click(screen.getByRole("button", { name: "来源设置" }));
  await screen.findByRole("dialog");
  fireEvent.click(screen.getByRole("combobox", { name: "资源来源" }));
  fireEvent.click(screen.getByRole("option", { name: "自定义镜像" }));
  fireEvent.change(screen.getByRole("textbox", { name: /镜像地址/ }), { target: { value: "https://mirror.test/public/v1/" } });
  fireEvent.click(screen.getByRole("button", { name: "应用来源" }));
  await screen.findByText("已保存");
  expect(saveResourceSource).toHaveBeenCalledWith("mirror", "https://mirror.test/public/v1/");
  expect(useResourceStore.getState().generation).toBe(1);
  expect(useResourceStore.getState().catalogSource.luts).toBe("offline");
  expect(useCommunityStore.getState().connection?.subject).toBe("maker");
  expect(useCommunityStore.getState().stats).toEqual({});
  expect(screen.getByRole("button", { name: "应用来源" })).toBeDisabled();
});

it("keeps the active source and the entered mirror when saving fails", async () => {
  vi.mocked(saveResourceSource).mockRejectedValue(new Error("Disk unavailable"));
  render(<ResourceSourceSetting compact />);
  fireEvent.click(screen.getByRole("button", { name: "来源设置" }));
  await screen.findByRole("dialog");
  fireEvent.click(screen.getByRole("combobox", { name: "资源来源" }));
  fireEvent.click(screen.getByRole("option", { name: "自定义镜像" }));
  fireEvent.change(screen.getByRole("textbox", { name: /镜像地址/ }), { target: { value: "https://mirror.test/public/v1" } });
  fireEvent.click(screen.getByRole("button", { name: "应用来源" }));
  await screen.findByText("Disk unavailable");
  expect(useResourceStore.getState().generation).toBe(0);
  expect(screen.getByRole("textbox", { name: /镜像地址/ })).toHaveValue("https://mirror.test/public/v1");
  expect(screen.getByRole("button", { name: "应用来源" })).toBeEnabled();
});

it("shows the actual cached check time and ignores health from a different source", async () => {
  useResourceStore.getState().observeCatalog("materials", { sourceUrl: "https://hosted.test/api", state: "cached", fetchedAt: "2026-11-16T02:03:00Z" });
  render(<ResourceSourceSetting compact />);
  fireEvent.click(screen.getByRole("button", { name: "来源设置" }));
  await screen.findByText("当前显示本地缓存，下载需联网");
  expect(document.querySelector("time")).toHaveAttribute("datetime", "2026-11-16T02:03:00.000Z");
  useResourceStore.getState().observeCatalog("materials", { sourceUrl: "https://another.test/api", state: "ready" });
  await waitFor(() => expect(screen.getByText("待检测")).toBeInTheDocument());
  expect(document.querySelector("time")).toBeNull();
});

it("does not let an older status request overwrite a source that has just been saved", async () => {
  let resolve!: (value: ResourceStatus) => void;
  vi.mocked(fetchResourceStatus).mockReturnValue(new Promise(done => { resolve = done; }));
  const refresh = useResourceStore.getState().refresh();
  useResourceStore.getState().sourceChanged(status("mirror"));
  resolve(status());
  await refresh;
  expect(useResourceStore.getState().status?.source_settings?.mode).toBe("mirror");
  expect(useResourceStore.getState().generation).toBe(1);
});
