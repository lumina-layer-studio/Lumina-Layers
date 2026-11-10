import type { WorkshopPermissionName } from "@lumina/workshop-sdk";
import axios from "axios";

import apiClient from "./client";

export interface WorkshopLocalizedText {
  zh_cn: string;
  en_us: string;
}

export interface WorkshopPermission {
  name: WorkshopPermissionName;
  reason: string;
}

export interface WorkshopBackendSummary {
  python: string;
  platforms: string[];
  capabilities: Array<{ name: string; reason: string }>;
  model_count: number;
  variants: Array<{
    id: string;
    name: WorkshopLocalizedText;
    description: WorkshopLocalizedText;
    platforms: string[];
  }>;
}

export interface InstalledWorkshopVersion {
  version: string;
  name: WorkshopLocalizedText;
  description: WorkshopLocalizedText;
  publisher: string;
  workshop_api_min: string;
  workshop_api_max_exclusive: string;
  lumina_version_min: string;
  permissions: WorkshopPermission[];
  runtime_url: string;
  details_url: string;
  icon_url: string;
  asset_base_url: string;
  /** 2 when the version declares a host-managed backend. */
  manifest_version?: number;
  backend?: WorkshopBackendSummary | null;
  project_snapshot_protocol?: number | null;
  project_snapshot_schemas?: string[];
}

export type WorkshopInstallSource =
  | "registry"
  | "github"
  | "local"
  | "seed";

export interface InstalledWorkshopModule {
  module_id: string;
  source: WorkshopInstallSource;
  source_repository: string;
  official: boolean;
  enabled: boolean;
  active_version: string | null;
  previous_version: string | null;
  candidate_version: string | null;
  versions: string[];
  official_uninstalled: boolean;
  consecutive_start_failures: number;
  runtime_url: string | null;
  icon_url: string | null;
  asset_base_url: string | null;
  version_details: InstalledWorkshopVersion[];
}

export interface WorkshopModules {
  modules: InstalledWorkshopModule[];
}

export interface WorkshopCatalogVersion {
  version: string;
  state: "active" | "deprecated" | "blocked";
  permissions: WorkshopPermission[];
  revocation: {
    reason_code: string;
    severity: "low" | "medium" | "high" | "critical";
    message: WorkshopLocalizedText;
  } | null;
}

export interface WorkshopCatalogModule {
  module_id: string;
  repository: string;
  official: boolean;
  publisher: string;
  name: WorkshopLocalizedText;
  description: WorkshopLocalizedText;
  versions: WorkshopCatalogVersion[];
}

export interface WorkshopCatalog {
  source: "remote" | "cache" | "snapshot";
  verified: boolean;
  generated_at: string;
  modules: WorkshopCatalogModule[];
}

export interface WorkshopModuleDetails {
  module_id: string;
  version: string;
  readme_markdown: string;
  license_text: string;
  gallery_urls: string[];
}

export interface WorkshopUninstallReportItem {
  kind: string;
  label?: string;
  bytes?: number;
  count?: number;
  users?: string[];
  reason?: string;
  will_retry?: boolean;
}

export interface WorkshopUninstallReport {
  cleared: WorkshopUninstallReportItem[];
  shared: WorkshopUninstallReportItem[];
  retained: WorkshopUninstallReportItem[];
  failed: WorkshopUninstallReportItem[];
}

export interface WorkshopMutation {
  status?: "ok";
  module: InstalledWorkshopModule | null;
  uninstall_report?: WorkshopUninstallReport | null;
}

export interface WorkshopUninstallOptions {
  deleteTaskData: boolean;
  retainModels: boolean;
}

export type WorkshopReviewLevel = "official" | "reviewed" | "unreviewed";

export interface WorkshopDependencyEstimate {
  environment_key: string;
  environment_reused: boolean;
  package_count: number;
  shared_package_count: number;
  new_download_bytes: number;
  shared_bytes: number;
  unknown_size_packages: number;
}

export interface WorkshopBackendRuntimeState {
  state: "stopped" | "starting" | "ready" | "busy" | "stopping" | "failed";
  pid: number | null;
  version: string | null;
  variant: string | null;
  current_task_id: string | null;
  queued: number;
  last_failure: string | null;
}

export interface WorkshopBackendStatus {
  module_id: string;
  version: string;
  platform: string | null;
  platform_supported: boolean;
  tool_available: boolean;
  review_level: WorkshopReviewLevel;
  blocked: boolean;
  authorization: "granted" | "inherited" | "required";
  requires_unreviewed_confirmation: boolean;
  preparation: "unprepared" | "preparing" | "prepared" | "failed";
  failure_code: string | null;
  preparation_task_id: string | null;
  python: string;
  interpreter_download_bytes: number;
  interpreter_disk_bytes: number;
  capabilities: Array<{ name: string; reason: string }>;
  models: Array<{
    id: string;
    file_name: string;
    bytes: number;
    license: string;
    shared: boolean;
  }>;
  dependencies: WorkshopDependencyEstimate | null;
  variants: Array<{
    id: string;
    name: { "zh-CN": string; "en-US": string };
    description: { "zh-CN": string; "en-US": string };
    available: boolean;
    prepared: boolean;
    failure_code: string | null;
    dependencies: WorkshopDependencyEstimate | null;
  }>;
  acceleration: string | null;
  footprint: {
    environment_new_bytes: number;
    environment_shared_bytes: number;
    model_new_bytes: number;
    model_shared_bytes: number;
    reused_environment: boolean;
  } | null;
  runtime: WorkshopBackendRuntimeState;
}

export interface WorkshopBackendTaskResponse {
  task_id: string;
  module_id: string;
  module_version: string;
  kind: "operation" | "prepare";
  operation: string;
  status:
    | "queued"
    | "running"
    | "succeeded"
    | "failed"
    | "cancelled"
    | "interrupted";
  progress: { completed: number; total: number; phase: string } | null;
  error: { code: string; message: string } | null;
  inputs: Array<{ name: string; file_name: string; mime_type: string; size_bytes: number }>;
  outputs: Array<{ name: string; file_name: string; mime_type: string; size_bytes: number }>;
  variant: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
}

/** Why a backend request failed: HTTP status, stable code, or no response. */
export interface WorkshopBackendFailure {
  status: number | null;
  code: string | null;
  /** No response arrived: the local service is unreachable or timed out. */
  unreachable: boolean;
}

export function workshopBackendFailure(error: unknown): WorkshopBackendFailure {
  if (!axios.isAxiosError(error)) {
    return { status: null, code: null, unreachable: false };
  }
  const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
  const code =
    typeof detail === "object" &&
    detail !== null &&
    typeof (detail as { code?: unknown }).code === "string"
      ? (detail as { code: string }).code
      : null;
  return {
    status: error.response?.status ?? null,
    code,
    unreachable: error.response === undefined,
  };
}

export interface WorkshopBackendStorage {
  environments: Array<{
    key: string;
    python: string;
    packages: number;
    exclusive_bytes: number;
    logical_bytes: number;
    users: string[];
  }>;
  interpreters: Array<{ key: string; python: string; managed: boolean }>;
  shared_store: { objects: number; bytes: number };
  /** Model views that are full copies (drive without hard links). */
  model_copies?: { files: number; bytes: number };
  models: Array<{ sha256: string; users: string[]; bytes?: number }>;
  retained_models: Array<{
    sha256: string;
    file_name: string;
    module_id: string;
    size_bytes: number;
    retained_at: string;
  }>;
  task_data: Array<{ module_id: string; task_count: number; bytes: number }>;
  pending: Array<{ path: string; reason: string; since: string }>;
  tool_available: boolean;
}

export interface WorkshopBackendTaskInput {
  name: string;
  fileName: string;
  mimeType: string;
  bytes: ArrayBuffer;
}

/** Host-owned backend task API. 宿主托管的后端任务接口。 */
export interface WorkshopBackendApi {
  status(moduleId: string, version: string): Promise<WorkshopBackendStatus>;
  authorize(
    moduleId: string,
    version: string,
    acknowledgeUnreviewed: boolean,
  ): Promise<WorkshopBackendStatus>;
  prepare(moduleId: string, version: string): Promise<WorkshopBackendTaskResponse>;
  setAcceleration(
    moduleId: string,
    variant: string | null,
  ): Promise<WorkshopBackendStatus>;
  stop(moduleId: string): Promise<void>;
  presence(moduleId: string): Promise<void>;
  submit(
    moduleId: string,
    version: string,
    request: {
      operation: string;
      params: Record<string, unknown>;
      inputs: WorkshopBackendTaskInput[];
      idempotencyKey?: string;
    },
  ): Promise<WorkshopBackendTaskResponse>;
  task(moduleId: string, taskId: string): Promise<WorkshopBackendTaskResponse>;
  tasks(moduleId: string): Promise<WorkshopBackendTaskResponse[]>;
  cancel(moduleId: string, taskId: string): Promise<WorkshopBackendTaskResponse>;
  remove(moduleId: string, taskId: string): Promise<void>;
  output(moduleId: string, taskId: string, name: string): Promise<ArrayBuffer>;
  storage(): Promise<WorkshopBackendStorage>;
  deleteRetainedModel(sha256: string): Promise<void>;
  deleteTaskData(moduleId: string): Promise<void>;
}

export interface WorkshopManagerApi {
  listModules(): Promise<WorkshopModules>;
  fetchCatalog(): Promise<WorkshopCatalog>;
  fetchDetails(url: string): Promise<WorkshopModuleDetails>;
  installRegistry(
    moduleId: string,
    version: string,
  ): Promise<WorkshopMutation>;
  installGithub(
    repositoryUrl: string,
    version: string,
  ): Promise<WorkshopMutation>;
  installLocal(file: File): Promise<WorkshopMutation>;
  activateModule(
    moduleId: string,
    version: string,
  ): Promise<WorkshopMutation>;
  rollbackModule(moduleId: string): Promise<WorkshopMutation>;
  setModuleEnabled(
    moduleId: string,
    enabled: boolean,
  ): Promise<WorkshopMutation>;
  uninstallModule(
    moduleId: string,
    deleteProjects: boolean,
    options?: WorkshopUninstallOptions,
  ): Promise<WorkshopMutation>;
  restoreOfficialSeed(moduleId: string): Promise<WorkshopMutation>;
  recordRuntimeSuccess(moduleId: string): Promise<WorkshopMutation>;
  recordRuntimeFailure(moduleId: string): Promise<WorkshopMutation>;
}

const MUTATION_TIMEOUT_MS = 3_600_000;

function encoded(value: string): string {
  return encodeURIComponent(value);
}

function apiClientPath(value: string): string {
  if (/^https?:\/\//i.test(value)) {
    return value;
  }
  return value.startsWith("/api/") ? value.slice(4) : value;
}

export const workshopApi: WorkshopManagerApi = {
  async listModules() {
    const response = await apiClient.get<WorkshopModules>(
      "/workshop/v1/modules",
    );
    return response.data;
  },

  async fetchCatalog() {
    const response = await apiClient.get<WorkshopCatalog>(
      "/workshop/v1/catalog",
      { timeout: 120_000 },
    );
    return response.data;
  },

  async fetchDetails(url) {
    const response = await apiClient.get<WorkshopModuleDetails>(
      apiClientPath(url),
    );
    return response.data;
  },

  async installRegistry(moduleId, version) {
    const response = await apiClient.post<WorkshopMutation>(
      "/workshop/v1/install/registry",
      { module_id: moduleId, version },
      { timeout: MUTATION_TIMEOUT_MS },
    );
    return response.data;
  },

  async installGithub(repositoryUrl, version) {
    const response = await apiClient.post<WorkshopMutation>(
      "/workshop/v1/install/github",
      { repository_url: repositoryUrl, version },
      { timeout: MUTATION_TIMEOUT_MS },
    );
    return response.data;
  },

  async installLocal(file) {
    const payload = new FormData();
    payload.append("archive", file, file.name);
    const response = await apiClient.post<WorkshopMutation>(
      "/workshop/v1/install/local",
      payload,
      { timeout: MUTATION_TIMEOUT_MS },
    );
    return response.data;
  },

  async activateModule(moduleId, version) {
    const response = await apiClient.post<WorkshopMutation>(
      `/workshop/v1/modules/${encoded(moduleId)}/activate`,
      { version },
    );
    return response.data;
  },

  async rollbackModule(moduleId) {
    const response = await apiClient.post<WorkshopMutation>(
      `/workshop/v1/modules/${encoded(moduleId)}/rollback`,
      {},
    );
    return response.data;
  },

  async setModuleEnabled(moduleId, enabled) {
    const response = await apiClient.patch<WorkshopMutation>(
      `/workshop/v1/modules/${encoded(moduleId)}/enabled`,
      { enabled },
    );
    return response.data;
  },

  async uninstallModule(moduleId, deleteProjects, options) {
    const response = await apiClient.delete<WorkshopMutation>(
      `/workshop/v1/modules/${encoded(moduleId)}`,
      {
        data: {
          delete_projects: deleteProjects,
          ...(options === undefined
            ? {}
            : {
                delete_task_data: options.deleteTaskData,
                retain_models: options.retainModels,
              }),
        },
        timeout: MUTATION_TIMEOUT_MS,
      },
    );
    return response.data;
  },

  async restoreOfficialSeed(moduleId) {
    const response = await apiClient.post<WorkshopMutation>(
      `/workshop/v1/modules/${encoded(moduleId)}/restore-seed`,
      {},
      { timeout: MUTATION_TIMEOUT_MS },
    );
    return response.data;
  },

  async recordRuntimeSuccess(moduleId) {
    const response = await apiClient.post<WorkshopMutation>(
      `/workshop/v1/modules/${encoded(moduleId)}/runtime-success`,
      {},
    );
    return response.data;
  },

  async recordRuntimeFailure(moduleId) {
    const response = await apiClient.post<WorkshopMutation>(
      `/workshop/v1/modules/${encoded(moduleId)}/runtime-failure`,
      {},
    );
    return response.data;
  },
};

const BACKEND_TRANSFER_TIMEOUT_MS = 120_000;

function backendVersionPath(moduleId: string, version: string): string {
  return `/workshop/v1/modules/${encoded(moduleId)}/${encoded(version)}/backend`;
}

function backendTasksPath(moduleId: string): string {
  return `/workshop/v1/modules/${encoded(moduleId)}/backend/tasks`;
}

export const workshopBackendApi: WorkshopBackendApi = {
  async status(moduleId, version) {
    const response = await apiClient.get<WorkshopBackendStatus>(
      backendVersionPath(moduleId, version),
    );
    return response.data;
  },

  async authorize(moduleId, version, acknowledgeUnreviewed) {
    const response = await apiClient.post<WorkshopBackendStatus>(
      `${backendVersionPath(moduleId, version)}/authorize`,
      { acknowledge_unreviewed: acknowledgeUnreviewed },
    );
    return response.data;
  },

  async prepare(moduleId, version) {
    const response = await apiClient.post<WorkshopBackendTaskResponse>(
      `${backendVersionPath(moduleId, version)}/prepare`,
      {},
    );
    return response.data;
  },

  async setAcceleration(moduleId, variant) {
    const response = await apiClient.put<WorkshopBackendStatus>(
      `/workshop/v1/modules/${encoded(moduleId)}/backend/acceleration`,
      { variant },
    );
    return response.data;
  },

  async stop(moduleId) {
    await apiClient.post(`/workshop/v1/modules/${encoded(moduleId)}/backend/stop`, {});
  },

  async presence(moduleId) {
    await apiClient.post(`/workshop/v1/modules/${encoded(moduleId)}/backend/presence`, {});
  },

  async submit(moduleId, version, request) {
    const form = new FormData();
    form.append("version", version);
    form.append("operation", request.operation);
    form.append("params", JSON.stringify(request.params));
    form.append(
      "inputs_meta",
      JSON.stringify(
        request.inputs.map((input) => ({
          name: input.name,
          fileName: input.fileName,
          mimeType: input.mimeType,
        })),
      ),
    );
    if (request.idempotencyKey !== undefined) {
      form.append("idempotency_key", request.idempotencyKey);
    }
    for (const input of request.inputs) {
      form.append(
        "files",
        new Blob([input.bytes], { type: input.mimeType }),
        input.fileName,
      );
    }
    const response = await apiClient.post<WorkshopBackendTaskResponse>(
      backendTasksPath(moduleId),
      form,
      { timeout: BACKEND_TRANSFER_TIMEOUT_MS },
    );
    return response.data;
  },

  async task(moduleId, taskId) {
    const response = await apiClient.get<WorkshopBackendTaskResponse>(
      `${backendTasksPath(moduleId)}/${encoded(taskId)}`,
    );
    return response.data;
  },

  async tasks(moduleId) {
    const response = await apiClient.get<{ tasks: WorkshopBackendTaskResponse[] }>(
      backendTasksPath(moduleId),
    );
    return response.data.tasks;
  },

  async cancel(moduleId, taskId) {
    const response = await apiClient.post<WorkshopBackendTaskResponse>(
      `${backendTasksPath(moduleId)}/${encoded(taskId)}/cancel`,
      {},
    );
    return response.data;
  },

  async remove(moduleId, taskId) {
    await apiClient.delete(`${backendTasksPath(moduleId)}/${encoded(taskId)}`);
  },

  async output(moduleId, taskId, name) {
    const response = await apiClient.get<ArrayBuffer>(
      `${backendTasksPath(moduleId)}/${encoded(taskId)}/outputs/${encoded(name)}`,
      { responseType: "arraybuffer", timeout: BACKEND_TRANSFER_TIMEOUT_MS },
    );
    return response.data;
  },

  async storage() {
    const response = await apiClient.get<WorkshopBackendStorage>(
      "/workshop/v1/backend/storage",
    );
    return response.data;
  },

  async deleteRetainedModel(sha256) {
    await apiClient.delete(`/workshop/v1/backend/storage/models/${encoded(sha256)}`);
  },

  async deleteTaskData(moduleId) {
    await apiClient.delete(`/workshop/v1/backend/storage/tasks/${encoded(moduleId)}`);
  },
};
