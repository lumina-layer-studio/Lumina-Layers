import axios, { type AxiosAdapter, type InternalAxiosRequestConfig } from "axios";
import { retryAsync } from "../utils/retryAsync";

const CATALOG_PATHS = new Set([
  "/system/printers",
  "/system/slicers",
  "/system/3mf-templates",
  "/extractor/gradient-card-materials",
]);
const STATELESS_IMAGE_PATHS = new Set(["/convert/crop", "/convert/auto-detect-colors"]);

function hasBatchCommitIdentity(config: InternalAxiosRequestConfig): boolean {
  if (config.method?.toLowerCase() !== "post" || config.url !== "/convert/replace-colors-batch") return false;
  try {
    const data = typeof config.data === "string" ? JSON.parse(config.data) : config.data;
    return typeof data?.session_id === "string" && data.session_id.trim().length > 0
      && typeof data?.operation_id === "string" && data.operation_id.trim().length > 0;
  } catch {
    return false;
  }
}

function isInterruptedRequest(error: unknown): boolean {
  if (!axios.isAxiosError(error) || axios.isCancel(error)) return false;
  if (error.response) {
    return [502, 503, 504].includes(error.response.status)
      && !Object.keys(error.response.headers).some((name) => name.toLowerCase() === "retry-after");
  }
  return ["ERR_NETWORK", "ECONNRESET", "ECONNABORTED", "ETIMEDOUT"].includes(error.code ?? "");
}

export function createRequestRetryAdapter(baseAdapter: AxiosAdapter): AxiosAdapter {
  return (config) => {
    const method = config.method?.toLowerCase() ?? "get";
    const path = config.url ?? "";
    const canRetry = (method === "get" && CATALOG_PATHS.has(path))
      || (method === "post" && STATELESS_IMAGE_PATHS.has(path))
      || hasBatchCommitIdentity(config);
    if (!canRetry) return baseAdapter(config);
    // Catalog reads and independent image processing do not edit sessions.
    // Batch edits retain the exact body/operation id; the backend rejects a
    // duplicate commit with 409 for the store's existing receipt reconciliation.
    return retryAsync(() => {
      config.cancelToken?.throwIfRequested();
      if (config.signal?.aborted) throw new axios.CanceledError(undefined, config);
      return baseAdapter(config);
    }, { attempts: 2, delayMs: 500, shouldRetry: isInterruptedRequest });
  };
}
