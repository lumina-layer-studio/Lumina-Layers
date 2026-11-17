import apiClient from "./client";
import type {
  MaterialRegistryCatalogResponse,
  MaterialRegistryInstallRequest,
  MaterialSyncInstallResponse,
  MaterialSyncRefreshResponse,
  MaterialSyncRollbackResponse,
  MaterialSyncStatusResponse,
} from "./types";

const MATERIAL_SYNC_READ_TIMEOUT_MS = 120_000;

export interface MaterialRegistryCatalogQuery {
  limit?: number;
  offset?: number;
  q?: string;
  refresh?: boolean;
}

/**
 * Fetch local material sync-index status.
 * 获取本地耗材同步索引状态。
 */
export async function fetchMaterialSyncStatus(signal?: AbortSignal): Promise<MaterialSyncStatusResponse> {
  const response = await apiClient.get<MaterialSyncStatusResponse>(
    "/material-sync/status",
    { timeout: MATERIAL_SYNC_READ_TIMEOUT_MS, signal },
  );
  return response.data;
}

/**
 * Pull read-only material package updates from the configured Registry.
 * 从已配置的只读 Registry 拉取耗材包更新。
 */
export async function refreshMaterialSyncFromRegistry(): Promise<MaterialSyncRefreshResponse> {
  const response = await apiClient.post<MaterialSyncRefreshResponse>(
    "/material-sync/refresh",
    {},
    {
      timeout: 3_600_000,
    },
  );
  return response.data;
}

/**
 * Fetch the remote material Registry catalog without installing packages.
 * 只读取远端耗材 Registry 目录，不安装任何耗材包。
 */
export async function fetchMaterialRegistryCatalog(
  query: MaterialRegistryCatalogQuery = {},
  signal?: AbortSignal,
): Promise<MaterialRegistryCatalogResponse> {
  const response = await apiClient.get<MaterialRegistryCatalogResponse>(
    "/material-sync/catalog",
    {
      params: query,
      signal,
      timeout: MATERIAL_SYNC_READ_TIMEOUT_MS,
    },
  );
  return response.data;
}

/**
 * Install one selected material package from the remote Registry catalog.
 * 从远端 Registry 目录中安装用户选中的单个耗材包。
 */
export async function installMaterialRegistryCatalogEntry(
  entry: MaterialRegistryInstallRequest,
): Promise<MaterialSyncInstallResponse> {
  const response = await apiClient.post<MaterialSyncInstallResponse>(
    "/material-sync/install-from-registry",
    {
      material_id: entry.material_id,
      revision_id: entry.revision_id,
      package_url: entry.package_url,
      package_sha256: entry.package_sha256,
      ...(entry.account_id ? { account_id: entry.account_id } : {}),
    },
    {
      timeout: 3_600_000,
    },
  );
  return response.data;
}

/**
 * Roll a synced local material back to a previous revision.
 * 将本地已同步耗材回滚到指定历史 revision。
 */
export async function rollbackMaterialSyncRevision(
  materialId: string,
  revisionId: string,
): Promise<MaterialSyncRollbackResponse> {
  const response = await apiClient.post<MaterialSyncRollbackResponse>(
    "/material-sync/rollback",
    { material_id: materialId, revision_id: revisionId },
    {
      timeout: 60_000,
    },
  );
  return response.data;
}
