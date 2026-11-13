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
  WorkshopBackendStatus,
  WorkshopBackendTaskResponse,
  WorkshopManagerApi,
} from "../api/workshop";
import { I18nProvider } from "../i18n/context";
import { useSettingsStore } from "../stores/settingsStore";
import { WorkshopPanel } from "../workshop/WorkshopPanel";
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
    expect(within(dialog).getByText(/权限与你的账户相同/)).toBeInTheDocument();
    const confirm = within(dialog).getByRole("button", { name: "允许并安装" });
    expect(confirm).toBeDisabled();
    expect(backend.authorize).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("checkbox", { name: /我信任发布者/ }));
    fireEvent.click(confirm);
    await waitFor(() => expect(backend.authorize).toHaveBeenCalledWith(MODULE_ID, "1.0.0", true));
    await waitFor(() => expect(backend.prepare).toHaveBeenCalledWith(MODULE_ID, "1.0.0"));
    expect(await screen.findByText(`opened ${MODULE_ID}@1.0.0 backend=true`)).toBeInTheDocument();
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
});
