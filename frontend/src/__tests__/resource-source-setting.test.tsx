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

const defaultUrls = {
  github: "https://github.test/public/v1",
  registry: "https://registry.test/api/material-registry/v1",
  disabled: "",
} as const;

type DefaultProvider = keyof typeof defaultUrls;

function statusWithDefaults(materials: DefaultProvider, luts: DefaultProvider, mode: "default" | "mirror" = "default"): ResourceStatus {
  const current = status(mode);
  const source = current.source_settings!;
  const urls = { materials: defaultUrls[materials], luts: defaultUrls[luts] };
  return {
    ...current,
    materials: mode === "default" ? { ...current.materials, provider: materials, configured: !!urls.materials } : current.materials,
    luts: mode === "default" ? { ...current.luts, provider: luts, configured: !!urls.luts } : current.luts,
    source_settings: {
      ...source,
      urls: mode === "default" ? urls : source.urls,
      default_urls: urls,
      default_provider: materials === "github" ? "github" : "registry",
    },
  };
}

it.each([
  ["materials", "github", "registry", "GitHub（默认）"],
  ["luts", "github", "registry", "耗材服务器（默认）"],
  ["materials", "registry", "github", "耗材服务器（默认）"],
  ["luts", "registry", "github", "GitHub（默认）"],
  ["materials", "disabled", "github", "停用云端目录（默认）"],
  ["luts", "github", "disabled", "停用云端目录（默认）"],
] as const)("labels the %s default with material source %s and LUT source %s", async (kind, materials, luts, label) => {
  const value = statusWithDefaults(materials, luts);
  vi.mocked(fetchResourceStatus).mockResolvedValue(value);
  useResourceStore.setState({ status: value });

  render(<ResourceSourceSetting compact kind={kind} />);
  fireEvent.click(screen.getByRole("button", { name: "来源设置" }));

  expect(await screen.findByRole("combobox", { name: "资源来源" })).toHaveTextContent(label);
});

it("keeps the LUT default label neutral when a saved mirror hides its provider", async () => {
  const value = statusWithDefaults("github", "registry", "mirror");
  vi.mocked(fetchResourceStatus).mockResolvedValue(value);
  useResourceStore.setState({ status: value });

  render(<ResourceSourceSetting compact kind="luts" />);
  fireEvent.click(screen.getByRole("button", { name: "来源设置" }));
  fireEvent.click(await screen.findByRole("combobox", { name: "资源来源" }));

  expect(screen.getByRole("option", { name: /^默认线路$/ })).toBeInTheDocument();
});

it("describes a disabled default source honestly and guides applying a new source", async () => {
  const disabled: ResourceStatus = {
    materials: { configured: false, seed: { available: false, state: "ready" } },
    luts: { configured: false, seed: { available: false, state: "ready" } },
    source_repository: "https://github.test/repo",
    source_settings: {
      mode: "default",
      mirror_url: "",
      error: null,
      urls: { materials: "", luts: "" },
      default_urls: { materials: "", luts: "" },
      default_provider: "github",
    },
  };
  vi.mocked(fetchResourceStatus).mockResolvedValue(disabled);
  useResourceStore.setState({ status: disabled, error: null, generation: 0, catalogHealth: {} });

  render(<ResourceSourceSetting />);
  expect(screen.getByText("云端目录未启用")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "来源设置" }));
  const dialog = await screen.findByRole("dialog");
  expect(dialog).toHaveTextContent("云端目录未启用");
  expect(dialog).toHaveTextContent("未配置");
  expect(dialog).toHaveTextContent("当前默认停用云端目录");
  expect(screen.queryByRole("button", { name: "测试连接" })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("combobox", { name: "资源来源" }));
  fireEvent.click(screen.getByRole("option", { name: "GitHub 目录" }));
  expect(dialog).toHaveTextContent("已修改来源，点击「应用来源」后生效。");
  expect(screen.getByRole("button", { name: "应用来源" })).toBeEnabled();
});
