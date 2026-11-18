import apiClient from "./client";

export type ResourceKind = "materials" | "luts";
export type ResourceSource = "cloud" | "offline";
export interface ResourceSourceSettings {
  mode: "default" | "github" | "mirror";
  mirror_url: string;
  error: string | null;
  urls: Record<ResourceKind, string>;
  default_urls: Record<ResourceKind, string>;
  default_provider: "github" | "registry";
}

export interface OfflineResource {
  resource_id: string;
  revision_id: string;
  name: string;
  brand: string | null;
  material_type: string | null;
  color_mode: string | null;
  rgb?: [number, number, number] | null;
  display?: Record<string, unknown>;
  installed: boolean;
}

export interface OfflineCatalog {
  items: OfflineResource[];
  dataset_version: string | null;
}

export interface ResourceLibraryStatus {
  configured: boolean;
  provider?: "github" | "registry" | "disabled";
  seed: {
    state: "uninitialized" | "initializing" | "ready" | "failed";
    available: boolean;
    reason?: "existing_library" | "no_bundled_seed";
    dataset_version?: string;
    installed_count?: number;
    error?: string;
    needs_restore?: boolean;
  };
}

export type ResourceStatus = Record<ResourceKind, ResourceLibraryStatus> & {
  source_repository: string;
  source_settings?: ResourceSourceSettings;
};

export async function fetchResourceStatus(): Promise<ResourceStatus> {
  return (await apiClient.get<ResourceStatus>("/resources/status")).data;
}

export async function saveResourceSource(mode: ResourceSourceSettings["mode"], mirror_url: string): Promise<ResourceStatus> {
  return (await apiClient.put<ResourceStatus>("/resources/source", { mode, mirror_url }, {
    headers: { "X-Lumina-Contribution": "1" }, suppressErrorTicket: true,
  })).data;
}

export async function checkResourceSource(kind: ResourceKind, expected_url: string) {
  return (await apiClient.post<{ sourceUrl: string; state: "ready" | "cached"; fetchedAt?: string | null }>("/resources/source/check", { kind, expected_url }, {
    headers: { "X-Lumina-Contribution": "1" }, suppressErrorTicket: true, timeout: 60_000,
  })).data;
}

export async function fetchOfflineCatalog(kind: ResourceKind): Promise<OfflineCatalog> {
  return (await apiClient.get<OfflineCatalog>(`/resources/${kind}/catalog`)).data;
}

export async function installOfflineResource(kind: ResourceKind, item: OfflineResource): Promise<void> {
  await apiClient.post(`/resources/${kind}/install`, {
    resource_id: item.resource_id,
    revision_id: item.revision_id,
  }, { timeout: 120_000 });
}
