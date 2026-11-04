import type { WorkshopPermissionName } from "@lumina/workshop-sdk";

import apiClient from "./client";

export interface WorkshopLocalizedText {
  zh_cn: string;
  en_us: string;
}

export interface WorkshopPermission {
  name: WorkshopPermissionName;
  reason: string;
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

export interface WorkshopMutation {
  status?: "ok";
  module: InstalledWorkshopModule | null;
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

  async uninstallModule(moduleId, deleteProjects) {
    const response = await apiClient.delete<WorkshopMutation>(
      `/workshop/v1/modules/${encoded(moduleId)}`,
      { data: { delete_projects: deleteProjects } },
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
