import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { AxiosError, type AxiosResponse } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  InstalledWorkshopModule,
  InstalledWorkshopVersion,
  WorkshopBackendApi,
  WorkshopBackendProgress,
  WorkshopBackendStatus,
  WorkshopBackendTaskResponse,
  WorkshopManagerApi,
} from "../api/workshop";
import { I18nProvider } from "../i18n/context";
import { useSettingsStore } from "../stores/settingsStore";
import { WorkshopPanel } from "../workshop/WorkshopPanel";
import { BackendSetupDialog } from "../workshop/backend/BackendSetupDialog";
import type { ManagedWorkshopProjectStorage } from "../workshop/projectStorage";
import type { WorkshopFrameProps } from "../workshop/runtime/WorkshopFrame";
import { useWorkshopStore } from "../workshop/store";

const MODULE_ID = "fixture.backend";

function backendVersion(value: string): InstalledWorkshopVersion {
  return {
    version: value,
    name: { zh_cn: "后端测试模块", en_us: "Backend fixture" },
    description: { zh_cn: "用于测试", en_us: "For tests" },
    publisher: "Fixture Publisher",
    workshop_api_min: "1.1.0",
    workshop_api_max_exclusive: "2.0.0",
    lumina_version_min: "2.0.0",
    permissions: [],
    runtime_url: `/api/workshop/v1/modules/${MODULE_ID}/${value}/runtime`,
    details_url: `/api/workshop/v1/modules/${MODULE_ID}/${value}/details`,
    icon_url: `/icon-${value}.png`,
    asset_base_url: `/assets-${value}`,
    manifest_version: 2,
    backend: {
      python: "3.12",
      platforms: ["windows-x86_64"],
      capabilities: [{ name: "network", reason: "Downloads sample data." }],
      model_count: 1,
      variants: [],
    },
  };
}

function backendModule(): InstalledWorkshopModule {
  return {
    module_id: MODULE_ID,
    source: "local",
    source_repository: "local",
    official: false,
    enabled: true,
    active_version: "1.0.0",
    previous_version: null,
    candidate_version: null,
    versions: ["1.0.0"],
    official_uninstalled: false,
    consecutive_start_failures: 0,
    runtime_url: `/api/workshop/v1/modules/${MODULE_ID}/1.0.0/runtime`,
    icon_url: "/icon.png",
    asset_base_url: "/assets",
    version_details: [backendVersion("1.0.0")],
  };
}

function status(overrides: Partial<WorkshopBackendStatus> = {}): WorkshopBackendStatus {
  return {
    module_id: MODULE_ID,
    version: "1.0.0",
    platform: "windows-x86_64",
    platform_supported: true,
    tool_available: true,
    review_level: "unreviewed",
    blocked: false,
    authorization: "required",
    requires_unreviewed_confirmation: true,
    preparation: "unprepared",
    failure_code: null,
    preparation_task_id: null,
    python: "3.12",
    interpreter_download_bytes: 32 * 1024 * 1024,
    interpreter_disk_bytes: 110 * 1024 * 1024,
    capabilities: [{ name: "network", reason: "Downloads sample data." }],
    models: [{ id: "matte", file_name: "matte.onnx", bytes: 2048, license: "MIT", shared: false }],
    dependencies: {
      environment_key: "a".repeat(32),
      environment_reused: false,
      package_count: 3,
      shared_package_count: 1,
      new_download_bytes: 4096,
      shared_bytes: 1024,
      unknown_size_packages: 0,
    },
    variants: [],
    acceleration: null,
    footprint: null,
    runtime: {
      state: "stopped",
      pid: null,
      version: null,
      variant: null,
      current_task_id: null,
      queued: 0,
      last_failure: null,
    },
    ...overrides,
  };
}

function fakeApi(modules: InstalledWorkshopModule[]): WorkshopManagerApi {
  return {
    listModules: vi.fn().mockResolvedValue({ modules }),
    fetchCatalog: vi.fn().mockResolvedValue({
      source: "snapshot",
      verified: true,
      generated_at: "2026-11-04T00:00:00Z",
      modules: [],
    }),
    fetchDetails: vi.fn(),
    installRegistry: vi.fn(),
    installGithub: vi.fn(),
    installLocal: vi.fn(),
    activateModule: vi.fn(),
    rollbackModule: vi.fn(),
    setModuleEnabled: vi.fn(),
    uninstallModule: vi.fn(),
    restoreOfficialSeed: vi.fn(),
    recordRuntimeSuccess: vi.fn(),
    recordRuntimeFailure: vi.fn(),
  };
}

function fakeBackend(initial: WorkshopBackendStatus): WorkshopBackendApi {
  let current = initial;
  return {
    status: vi.fn(async () => current),
    authorize: vi.fn(async () => {
      current = { ...current, authorization: "granted", requires_unreviewed_confirmation: false };
      return current;
    }),
    prepare: vi.fn(async () => ({
      task_id: "b".repeat(32),
      module_id: MODULE_ID,
      module_version: "1.0.0",
      kind: "prepare" as const,
      operation: "prepare",
      status: "running" as const,
      progress: { completed: 1, total: 4, phase: "environment" },
      error: null,
      inputs: [],
      outputs: [],
      variant: null,
      created_at: "",
      updated_at: "",
      started_at: null,
      finished_at: null,
    })),
    task: vi.fn(async () => {
      current = { ...current, preparation: "prepared" };
      return {
        task_id: "b".repeat(32),
        module_id: MODULE_ID,
        module_version: "1.0.0",
        kind: "prepare" as const,
        operation: "prepare",
        status: "succeeded" as const,
        progress: { completed: 4, total: 4, phase: "self-check" },
        error: null,
        inputs: [],
        outputs: [],
        variant: null,
        created_at: "",
        updated_at: "",
        started_at: null,
        finished_at: "",
      };
    }),
    setAcceleration: vi.fn(),
    stop: vi.fn().mockResolvedValue(undefined),
    presence: vi.fn().mockResolvedValue(undefined),
    submit: vi.fn(),
    tasks: vi.fn().mockResolvedValue([]),
    cancel: vi.fn(),
    remove: vi.fn(),
    output: vi.fn(),
    storage: vi.fn().mockResolvedValue({
      environments: [
        { key: "a".repeat(32), python: "3.12", packages: 3, exclusive_bytes: 2048, logical_bytes: 4096, users: [MODULE_ID] },
      ],
      interpreters: [{ key: "managed-3.12", python: "3.12", managed: true }],
      shared_store: { objects: 2, bytes: 8192 },
      models: [],
      retained_models: [
        { sha256: "c".repeat(64), file_name: "matte.onnx", module_id: "fixture.old", size_bytes: 2048, retained_at: "" },
      ],
      task_data: [{ module_id: MODULE_ID, task_count: 2, bytes: 4096 }],
      pending: [],
      tool_available: true,
    }),
    deleteRetainedModel: vi.fn().mockResolvedValue(undefined),
    deleteTaskData: vi.fn().mockResolvedValue(undefined),
  };
}

/** A refused host request carrying the backend's ``{code, message}``. */
function refused(status: number, code: string): AxiosError {
  return new AxiosError("Request failed", "ERR_BAD_REQUEST", undefined, undefined, {
    status,
    statusText: "",
    headers: {},
    config: {} as AxiosResponse["config"],
    data: { detail: { code, message: code } },
  } as AxiosResponse);
}

function unreachable(): AxiosError {
  return new AxiosError("Network Error", "ERR_NETWORK");
}

function prepareTask(statusValue: WorkshopBackendTaskResponse["status"]): WorkshopBackendTaskResponse {
  return {
    task_id: "b".repeat(32),
    module_id: MODULE_ID,
    module_version: "1.0.0",
    kind: "prepare",
    operation: "prepare",
    status: statusValue,
    progress: { completed: 1, total: 4, phase: "models" },
    error: null,
    inputs: [],
    outputs: [],
    variant: null,
    created_at: "",
    updated_at: "",
    started_at: null,
    finished_at: null,
  };
}

const RUNNING = {
  state: "busy" as const,
  pid: 42,
  version: "1.0.0",
  variant: null,
  current_task_id: "x",
  queued: 0,
  last_failure: null,
};

function storage(): ManagedWorkshopProjectStorage {
  return {
    save: vi.fn(),
    load: vi.fn(),
    latest: vi.fn().mockResolvedValue(null),
    remove: vi.fn(),
    snapshotModule: vi.fn().mockResolvedValue("snapshot-1"),
    restoreSnapshot: vi.fn(),
    deleteSnapshot: vi.fn(),
    deleteModuleProjects: vi.fn(),
  };
}

function Frame(props: WorkshopFrameProps) {
  return <p>{`opened ${props.module.moduleId}@${props.module.moduleVersion} backend=${props.module.hasBackend}`}</p>;
}

function renderPanel(api: WorkshopManagerApi, backendApi: WorkshopBackendApi) {
  return render(
    <I18nProvider>
      <WorkshopPanel
        api={api}
        backendApi={backendApi}
        projectStorage={storage()}
        runtimeMode="desktop-secure"
        FrameComponent={Frame}
      />
    </I18nProvider>,
  );
}

describe("Workshop backend management UI", () => {
  beforeEach(() => {
    localStorage.clear();
    useSettingsStore.setState({ language: "zh", theme: "light" });
    useWorkshopStore.setState({
      view: "installed",
      activeModule: null,
      activeRuntimeContext: null,
      catalogStatus: "idle",
      runtimeMode: "desktop-secure",
      pendingRecipeSource: null,
      diagnostics: null,
    });
  });

  it("requires explicit risk confirmation before preparing unreviewed backend code", async () => {
    const api = fakeApi([backendModule()]);
    const backend = fakeBackend(status());
    renderPanel(api, backend);

    fireEvent.click(await screen.findByRole("button", { name: "打开" }));
    const dialog = await screen.findByRole("dialog", { name: "运行本机后端" });
    expect(within(dialog).getByText("未审核：此版本没有审核记录。")).toBeInTheDocument();
    expect(within(dialog).getByText("联网")).toBeInTheDocument();
    expect(within(dialog).getByRole("alert")).toHaveAttribute("data-tone", "error");
    expect(within(dialog).getByText(/以你的账户权限运行，可以读取、修改或删除/)).toBeInTheDocument();
    const confirm = within(dialog).getByRole("button", { name: "允许并安装" });
    expect(confirm).toBeDisabled();
    expect(backend.authorize).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("checkbox", { name: /我信任发布者/ }));
    fireEvent.click(confirm);
    await waitFor(() => expect(backend.authorize).toHaveBeenCalledWith(MODULE_ID, "1.0.0", true));
    await waitFor(() => expect(backend.prepare).toHaveBeenCalledWith(MODULE_ID, "1.0.0"));
    expect(await screen.findByText(`opened ${MODULE_ID}@1.0.0 backend=true`)).toBeInTheDocument();
  });

  it("displays download failure details from the preparation task", async () => {
    const backend = fakeBackend(status({
      review_level: "reviewed",
      requires_unreviewed_confirmation: false,
    }));
    const task = await backend.prepare(MODULE_ID, "1.0.0");
    const detail = "Could not verify demo.whl. files.example returned HTTP 503.";
    vi.mocked(backend.task).mockResolvedValue({
      ...task,
      status: "failed",
      error: { code: "dependency-install-failed", message: detail },
    });
    renderPanel(fakeApi([backendModule()]), backend);

    fireEvent.click(await screen.findByRole("button", { name: "打开" }));
    const dialog = await screen.findByRole("dialog", { name: "运行本机后端" });
    fireEvent.click(within(dialog).getByRole("button", { name: "允许并安装" }));
    expect(await within(dialog).findByText(detail)).toBeInTheDocument();
  });

  it.each(["official", "reviewed"] as const)("uses localized capability text and the chosen model source for %s code", async (reviewLevel) => {
    const api = fakeApi([backendModule()]);
    const backend = fakeBackend(status({
      review_level: reviewLevel,
      requires_unreviewed_confirmation: false,
      capabilities: [{
        name: "network",
        reason: "Download data.",
        reason_i18n: { zh_cn: "下载检测数据", en_us: "Download detection data." },
      }],
      download_sources: { python: [], wheels: [], models: ["huggingface.co", "modelscope.cn"], artifacts: [] },
    }));
    renderPanel(api, backend);

    fireEvent.click(await screen.findByRole("button", { name: "打开" }));
    const dialog = await screen.findByRole("dialog", { name: "运行本机后端" });
    expect(within(dialog).queryByRole("alert")).toBeNull();
    expect(within(dialog).getByText("下载检测数据")).toBeInTheDocument();
    expect(within(dialog).queryByText("Download data.")).toBeNull();
    fireEvent.change(within(dialog).getByRole("combobox", { name: "模型" }), { target: { value: "modelscope.cn" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "允许并安装" }));
    await waitFor(() => expect(backend.prepare).toHaveBeenCalledWith(MODULE_ID, "1.0.0", { models: "modelscope.cn" }));
  });

  it("shows the module declaration and updates the expected sources before starting preparation", async () => {
    const backend = fakeBackend(status({
      capabilities: [],
      download_plan: {
        python: [{ original: "github.com", sources: ["github.com"], count: 1, bytes: 32 * 1024 * 1024 }],
        wheels: [
          {
            original: "files.pythonhosted.org", sources: ["pypi.tuna.tsinghua.edu.cn", "files.pythonhosted.org"],
            count: 2, bytes: 2048, unknown_size_count: 1,
          },
          { original: "download.pytorch.org", sources: ["download.pytorch.org"], count: 1, bytes: 4096 },
        ],
        models: [
          { original: "huggingface.co", sources: ["modelscope.cn", "huggingface.co"], count: 3, bytes: 3072 },
          { original: "huggingface.co", sources: ["huggingface.co"], count: 6, bytes: 6144 },
        ],
        artifacts: [],
      },
    }));
    renderPanel(fakeApi([backendModule()]), backend);

    fireEvent.click(await screen.findByRole("button", { name: "打开" }));
    const dialog = within(await screen.findByRole("dialog", { name: "运行本机后端" }));
    expect(dialog.getByRole("heading", { name: "模块声明" })).toBeInTheDocument();
    expect(dialog.getByText("模块声明不会联网、启动其他程序或访问任务文件夹以外的文件。")).toBeInTheDocument();
    expect(dialog.getByRole("alert")).toHaveAttribute("data-tone", "error");
    expect(dialog.getByRole("heading", { name: "预计首选下载源" })).toBeInTheDocument();
    expect(dialog.getByText("GitHub · 1 个文件 · 约 32 MB")).toBeInTheDocument();
    expect(dialog.getByText("清华 PyPI 镜像 · 2 个文件 · 已知部分约 2.0 KB")).toBeInTheDocument();
    expect(dialog.getByText("PyTorch · 1 个文件 · 约 4.0 KB")).toBeInTheDocument();
    expect(dialog.getByText("ModelScope · 3 个文件 · 约 3.0 KB")).toBeInTheDocument();
    expect(dialog.getByText("Hugging Face · 6 个文件 · 约 6.0 KB")).toBeInTheDocument();

    const wheels = dialog.getByRole("combobox", { name: "Python 依赖包" });
    expect(within(wheels).getByRole("option", { name: "清华 PyPI 镜像" })).toBeInTheDocument();
    expect(within(wheels).queryByRole("option", { name: "PyTorch" })).toBeNull();
    fireEvent.change(wheels, { target: { value: "original" } });
    fireEvent.change(dialog.getByRole("combobox", { name: "模型" }), { target: { value: "original" } });
    expect(dialog.getByText("PyPI · 2 个文件 · 已知部分约 2.0 KB")).toBeInTheDocument();
    expect(dialog.getByText("Hugging Face · 9 个文件 · 约 9.0 KB")).toBeInTheDocument();
    expect(backend.prepare).not.toHaveBeenCalled();

    fireEvent.click(dialog.getByRole("checkbox", { name: /我信任发布者/ }));
    fireEvent.click(dialog.getByRole("button", { name: "允许并安装" }));
    await waitFor(() => expect(backend.prepare).toHaveBeenCalledWith(
      MODULE_ID, "1.0.0", { wheels: "original", models: "original" },
    ));
  });

  it("stabilizes both remaining times and keeps the overall and stage bars through each step", () => {
    const props = {
      moduleName: "Backend fixture",
      status: status({ download_estimate: { bytes: 8192, incomplete: false } }),
      phase: "preparing" as const,
      failureCode: null, onConfirm: vi.fn(), onRetry: vi.fn(), onCancel: vi.fn(),
    };
    const viewOf = (progress: WorkshopBackendProgress | null) => (
      <I18nProvider>
        <BackendSetupDialog {...props} progress={progress} />
      </I18nProvider>
    );
    const view = render(viewOf(null));
    const dialog = within(screen.getByRole("dialog", { name: "正在安装后端" }));
    const speed = dialog.getByText("下载速度").nextElementSibling;
    const phaseTime = dialog.getByText("本阶段剩余").nextElementSibling;
    const totalTime = dialog.getByText("全部下载剩余").nextElementSibling;
    expect(speed).toHaveTextContent("测速中");
    expect(phaseTime).toHaveTextContent("计算中");
    expect(totalTime).toHaveTextContent("计算中");
    expect(dialog.queryByText(/此版本没有审核记录/)).toBeNull();

    const transfer = {
      file_name: "demo.whl", source: "pypi.tuna.tsinghua.edu.cn", file_index: 1, file_count: 2,
      received_bytes: 1024, total_bytes: 4096, bytes_per_second: 1024, eta_seconds: 3,
    };
    const progress = {
      completed: 1, total: 5, phase: "wheel-download", downloaded_bytes: 2048, download: transfer,
    };
    const early = {
      ...progress, downloaded_bytes: 1536,
      download: { ...transfer, received_bytes: 512, bytes_per_second: 16 * 1024, eta_seconds: 1 },
    };
    view.rerender(viewOf(early));
    expect(phaseTime).toHaveTextContent("计算中");
    expect(totalTime).toHaveTextContent("计算中");
    view.rerender(viewOf({ ...early }));
    view.rerender(viewOf({
      ...progress, downloaded_bytes: 1792,
      download: { ...transfer, received_bytes: 768, eta_seconds: 4 },
    }));
    expect(phaseTime).toHaveTextContent("计算中");
    expect(totalTime).toHaveTextContent("计算中");

    view.rerender(viewOf(progress));
    expect(dialog.getByText("demo.whl")).toBeInTheDocument();
    expect(dialog.getByText("清华 PyPI 镜像")).toBeInTheDocument();
    expect(dialog.getByText("本阶段已下载").nextElementSibling).toHaveTextContent("1.0 KB / 4.0 KB");
    expect(speed).toHaveTextContent("1.0 KB/秒");
    expect(phaseTime).toHaveTextContent("约 3 秒");
    expect(totalTime).toHaveTextContent("约 6 秒");
    expect(dialog.getByRole("progressbar", { name: "安装总进度" })).toHaveAttribute("value", "20");
    expect(dialog.getByRole("progressbar", { name: "下载运行库" })).toHaveAttribute("value", "25");

    view.rerender(viewOf({
      ...progress, downloaded_bytes: 2304,
      download: { ...transfer, received_bytes: 1280, bytes_per_second: 1, eta_seconds: 2816 },
    }));
    expect(phaseTime).toHaveTextContent(/^约 [34] 秒$/);
    expect(totalTime).toHaveTextContent(/^约 [67] 秒$/);
    const lastPhase = phaseTime?.textContent;
    const lastTotal = totalTime?.textContent;

    view.rerender(viewOf({ ...progress, download: {
      ...transfer, file_name: "different.whl", source: "files.pythonhosted.org",
      file_index: 2, bytes_per_second: null, eta_seconds: null,
    } }));
    expect(dialog.getByText("different.whl")).toBeInTheDocument();
    expect(speed).toHaveTextContent("测速中");
    expect(phaseTime?.textContent).toBe(lastPhase);
    expect(totalTime?.textContent).toBe(lastTotal);

    view.rerender(viewOf({ completed: 1, total: 5, phase: "environment", downloaded_bytes: 5120 }));
    expect(screen.getByRole("status")).toHaveTextContent("安装运行库");
    expect(dialog.getByText("合计已下载").nextElementSibling).toHaveTextContent("5.0 KB / 约 8.0 KB");
    expect(dialog.getByRole("progressbar", { name: "安装总进度" })).toHaveAttribute("value", "20");
    expect(dialog.getByRole("progressbar", { name: "安装运行库" })).not.toHaveAttribute("value");
    expect(phaseTime).toHaveTextContent("—");
    expect(speed).toHaveTextContent("—");

    view.rerender(viewOf({ completed: 3, total: 5, phase: "self-check", downloaded_bytes: 5120 }));
    expect(totalTime?.textContent).toBe(lastTotal);
    view.rerender(viewOf({ completed: 4, total: 5, phase: "variant-check", downloaded_bytes: 8192 }));
    expect(totalTime).toHaveTextContent("下载已完成");
    expect(dialog.getByRole("button", { name: "取消安装" })).toBeEnabled();
  });

  it("opens a prepared, authorized backend without asking again", async () => {
    const api = fakeApi([backendModule()]);
    const backend = fakeBackend(
      status({ authorization: "granted", requires_unreviewed_confirmation: false, preparation: "prepared" }),
    );
    renderPanel(api, backend);
    fireEvent.click(await screen.findByRole("button", { name: "打开" }));
    expect(await screen.findByText(`opened ${MODULE_ID}@1.0.0 backend=true`)).toBeInTheDocument();
    expect(backend.authorize).not.toHaveBeenCalled();
    expect(backend.prepare).not.toHaveBeenCalled();
  });

  it("offers backend data choices on uninstall and shows the report", async () => {
    const api = fakeApi([backendModule()]);
    vi.mocked(api.uninstallModule).mockResolvedValue({
      module: null,
      uninstall_report: {
        cleared: [{ kind: "environments", count: 1, bytes: 4096 }],
        shared: [{ kind: "shared-files", bytes: 1024, users: ["fixture.other"] }],
        retained: [{ kind: "projects" }],
        failed: [],
      },
    });
    renderPanel(api, fakeBackend(status({ preparation: "prepared", authorization: "granted" })));
    fireEvent.click(await screen.findByRole("button", { name: "卸载" }));
    const dialog = screen.getByRole("dialog", { name: "卸载模块" });
    expect(within(dialog).getByRole("checkbox", { name: "保留已下载的模型，重装时直接复用" })).not.toBeChecked();
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "同时删除原图副本和处理结果" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "确认卸载" }));
    await waitFor(() =>
      expect(api.uninstallModule).toHaveBeenCalledWith(MODULE_ID, false, {
        deleteTaskData: true,
        retainModels: false,
      }),
    );
    const report = await screen.findByRole("dialog", { name: "卸载结果" });
    expect(within(report).getByText(/运行环境 · 4.0 KB/)).toBeInTheDocument();
    expect(within(report).getByText(/使用者：fixture.other/)).toBeInTheDocument();
  });

  it("shows a running backend with a stop action", async () => {
    const backend = fakeBackend(
      status({
        authorization: "granted",
        preparation: "prepared",
        runtime: { state: "busy", pid: 42, version: "1.0.0", variant: null, current_task_id: "x", queued: 0, last_failure: null },
      }),
    );
    renderPanel(fakeApi([backendModule()]), backend);
    expect(await screen.findByText("后端正在处理任务，停止会取消任务")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "停止后端" }));
    await waitFor(() => expect(backend.stop).toHaveBeenCalledWith(MODULE_ID));
  });

  it("lists backend storage and deletes retained data on request", async () => {
    const backend = fakeBackend(status());
    renderPanel(fakeApi([]), backend);
    fireEvent.click(await screen.findByRole("button", { name: "存储" }));
    const section = await screen.findByRole("region", { name: "后端存储" });
    expect(within(section).getByText(/matte.onnx/)).toBeInTheDocument();
    const deletes = within(section).getAllByRole("button", { name: "删除" });
    fireEvent.click(deletes[0]);
    await waitFor(() => expect(backend.deleteRetainedModel).toHaveBeenCalledWith("c".repeat(64)));
    fireEvent.click(deletes[1]);
    await waitFor(() => expect(backend.deleteTaskData).toHaveBeenCalledWith(MODULE_ID));
  });
});

describe("Workshop backend management errors", () => {
  beforeEach(() => {
    localStorage.clear();
    useSettingsStore.setState({ language: "zh", theme: "light" });
    useWorkshopStore.setState({
      view: "installed",
      activeModule: null,
      activeRuntimeContext: null,
      catalogStatus: "idle",
      runtimeMode: "desktop-secure",
      pendingRecipeSource: null,
      diagnostics: null,
    });
  });

  it("keeps a failed stop beside the action after the status refreshes", async () => {
    const backend = fakeBackend(status({ authorization: "granted", preparation: "prepared", runtime: RUNNING }));
    vi.mocked(backend.stop).mockRejectedValue(unreachable());
    renderPanel(fakeApi([backendModule()]), backend);
    const row = await screen.findByTestId(`workshop-backend-${MODULE_ID}`);
    fireEvent.click(await within(row).findByRole("button", { name: "停止后端" }));
    const statusCalls = vi.mocked(backend.status).mock.calls.length;
    expect(await within(row).findByRole("alert")).toHaveTextContent(
      "后端未停止：Lumina 没有响应。请稍后重试；如果一直这样，请重启 Lumina。",
    );
    // The follow-up status request succeeds; the failure must stay visible.
    await waitFor(() => expect(vi.mocked(backend.status).mock.calls.length).toBeGreaterThan(statusCalls));
    expect(within(row).getByRole("alert")).toHaveTextContent("后端未停止");
  });

  it("explains an acceleration change refused because consent must be renewed", async () => {
    const backend = fakeBackend(
      status({
        authorization: "granted",
        requires_unreviewed_confirmation: false,
        preparation: "prepared",
        variants: [
          {
            id: "accel",
            name: { "zh-CN": "合成加速", "en-US": "Synthetic acceleration" },
            description: { "zh-CN": "仅测试", "en-US": "Test only" },
            available: true,
            prepared: false,
            failure_code: null,
            dependencies: null,
          },
        ],
      }),
    );
    vi.mocked(backend.setAcceleration).mockRejectedValue(refused(409, "backend-authorization-required"));
    renderPanel(fakeApi([backendModule()]), backend);
    const row = await screen.findByTestId(`workshop-backend-${MODULE_ID}`);
    fireEvent.change(within(row).getByRole("combobox"), { target: { value: "accel" } });
    expect(await within(row).findByRole("alert")).toHaveTextContent(
      "加速设置未更改：需要你重新允许后端运行。点击“安装后端”，确认后再试。",
    );
    expect(within(row).getByRole("combobox")).toHaveValue("");
  });

  it("follows the download task when an installed backend enables GPU acceleration", async () => {
    const prepared = status({
      authorization: "granted",
      preparation: "prepared",
      requires_unreviewed_confirmation: false,
      variants: [{
        id: "accel", name: { "zh-CN": "GPU 加速", "en-US": "GPU acceleration" },
        description: { "zh-CN": "测试", "en-US": "Test" },
        available: true, prepared: false, failure_code: null, dependencies: null,
      }],
    });
    const backend = fakeBackend(prepared);
    const task = prepareTask("running");
    vi.mocked(backend.setAcceleration).mockResolvedValue({
      ...prepared, acceleration: "accel", preparation_task_id: task.task_id,
      download_estimate: { bytes: 4096, incomplete: false },
    });
    vi.mocked(backend.task).mockResolvedValue({
      ...task, progress: {
        completed: 4, total: 5, phase: "variant-download", downloaded_bytes: 1024,
        download: {
          source: "download.pytorch.org", file_name: "gpu.whl", file_index: 1, file_count: 1,
          received_bytes: 1024, total_bytes: 4096, bytes_per_second: 1024, eta_seconds: 3,
        },
      },
    });
    renderPanel(fakeApi([backendModule()]), backend);
    const row = await screen.findByTestId(`workshop-backend-${MODULE_ID}`);
    fireEvent.change(within(row).getByRole("combobox"), { target: { value: "accel" } });

    expect(await within(row).findByText(/下载加速运行库/)).toBeInTheDocument();
    expect(within(row).getByText("本阶段已下载").nextElementSibling).toHaveTextContent("1.0 KB / 4.0 KB");
    expect(within(row).getByText("全部下载剩余").nextElementSibling).toHaveTextContent("计算中");
    expect(backend.task).toHaveBeenCalledWith(MODULE_ID, task.task_id);
    expect(within(row).getByRole("combobox")).toBeDisabled();

    vi.mocked(backend.cancel).mockResolvedValue(prepareTask("cancelled"));
    vi.mocked(backend.status).mockResolvedValue({
      ...prepared, acceleration: "accel", failure_code: "cancelled",
    });
    fireEvent.click(within(row).getByRole("button", { name: "取消安装" }));
    expect(await within(row).findByText("已取消加速准备，当前可使用 CPU。")).toBeInTheDocument();
    fireEvent.click(within(row).getByRole("button", { name: "重试加速安装" }));
    expect(backend.setAcceleration).toHaveBeenCalledTimes(2);
    expect(backend.setAcceleration).toHaveBeenLastCalledWith(MODULE_ID, "accel");
  });

  it("keeps a refused deletion beside its item after the list refreshes", async () => {
    const backend = fakeBackend(status());
    vi.mocked(backend.deleteTaskData).mockRejectedValue(refused(409, "task-active"));
    renderPanel(fakeApi([]), backend);
    fireEvent.click(await screen.findByRole("button", { name: "存储" }));
    const section = await screen.findByRole("region", { name: "后端存储" });
    const loads = vi.mocked(backend.storage).mock.calls.length;
    fireEvent.click(within(section).getAllByRole("button", { name: "删除" })[1]);
    await waitFor(() => expect(vi.mocked(backend.storage).mock.calls.length).toBeGreaterThan(loads));
    const alert = await within(section).findByRole("alert");
    expect(alert).toHaveTextContent("未删除：还有任务在运行。等任务完成或停止后端后再试。");
    // The refreshed list still shows the data; nothing pretends it was deleted.
    expect(within(alert.closest("li") as HTMLElement).getByText(/fixture.backend：2 个任务/)).toBeInTheDocument();
  });

  it("tells the user when cancelling a preparation did not go through", async () => {
    const backend = fakeBackend(status());
    let taskStatus: WorkshopBackendTaskResponse["status"] = "running";
    vi.mocked(backend.task).mockImplementation(async () => prepareTask(taskStatus));
    vi.mocked(backend.cancel).mockRejectedValue(unreachable());
    renderPanel(fakeApi([backendModule()]), backend);
    fireEvent.click(await screen.findByRole("button", { name: "打开" }));
    const dialog = await screen.findByRole("dialog", { name: "运行本机后端" });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /我信任发布者/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "允许并安装" }));
    await waitFor(() => expect(backend.task).toHaveBeenCalled());
    fireEvent.click(within(dialog).getByRole("button", { name: "取消安装" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("未能取消，安装仍在继续");
    expect(within(dialog).getByRole("button", { name: "取消安装" })).toBeInTheDocument();
    taskStatus = "cancelled";
  });

  it("does not start downloading when cancelled while authorizing", async () => {
    const backend = fakeBackend(status());
    let finishAuthorization: (() => void) | undefined;
    vi.mocked(backend.authorize).mockImplementation(() => new Promise((resolve) => {
      finishAuthorization = () => resolve(status({ authorization: "granted" }));
    }));
    renderPanel(fakeApi([backendModule()]), backend);
    fireEvent.click(await screen.findByRole("button", { name: "打开" }));
    const dialog = await screen.findByRole("dialog", { name: "运行本机后端" });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /我信任发布者/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "允许并安装" }));
    await waitFor(() => expect(backend.authorize).toHaveBeenCalled());
    fireEvent.click(within(dialog).getByRole("button", { name: "取消安装" }));
    finishAuthorization?.();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(backend.prepare).not.toHaveBeenCalled();
    expect(screen.queryByText(/^opened /)).toBeNull();
  });

  it("cancels a task whose ID arrives after the user stops preparation", async () => {
    const backend = fakeBackend(status());
    let finishSubmission: (() => void) | undefined;
    vi.mocked(backend.prepare).mockImplementation(() => new Promise((resolve) => {
      finishSubmission = () => resolve(prepareTask("running"));
    }));
    vi.mocked(backend.cancel).mockResolvedValue(prepareTask("cancelled"));
    vi.mocked(backend.task).mockResolvedValue(prepareTask("succeeded"));
    renderPanel(fakeApi([backendModule()]), backend);
    fireEvent.click(await screen.findByRole("button", { name: "打开" }));
    const dialog = await screen.findByRole("dialog", { name: "运行本机后端" });
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /我信任发布者/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "允许并安装" }));
    await waitFor(() => expect(backend.prepare).toHaveBeenCalled());
    fireEvent.click(within(dialog).getByRole("button", { name: "取消安装" }));
    finishSubmission?.();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(backend.cancel).toHaveBeenCalledWith(MODULE_ID, prepareTask("running").task_id);
    expect(screen.queryByText(/^opened /)).toBeNull();
  });
});
