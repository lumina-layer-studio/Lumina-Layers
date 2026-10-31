import axios from "axios";
import { createAsyncJobAdapter } from "./asyncJobAdapter";
import { postClientLog, summarizeErrorForLog } from "../utils/clientLog";
import { useActionHistoryStore } from "../stores/actionHistoryStore";
import { useErrorTicketPromptStore } from "../stores/errorTicketPromptStore";
import { tRuntime } from "../i18n/runtime";
import { rememberFeedbackSource } from "../utils/sourceFileOrigins";

export interface ApiRequestOptions {
  suppressClientLog?: boolean;
}

declare module "axios" {
  interface AxiosRequestConfig {
    suppressClientLog?: boolean;
  }
}

/**
 * Axios 实例，统一管理 API 请求基础配置。
 *
 * 注意：不设置默认 Content-Type header。
 * - 发送 JSON 时 axios 自动设置 application/json
 * - 发送 FormData 时 axios 自动设置 multipart/form-data 并附加 boundary
 * - 手动设置默认 Content-Type 会阻止 FormData 的 boundary 自动生成，导致后端 422
 */
const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "/api",
  timeout: 3_600_000,
});

// Long write requests become pollable backend jobs so reverse proxies do not
// cut them off with 504. 长请求改为后台任务轮询，避免反向代理超时。
apiClient.defaults.adapter = createAsyncJobAdapter(
  axios.getAdapter(axios.defaults.adapter),
);

function isHttpUrl(value: string): boolean {
  return /^https?:\/\//i.test(value);
}

function joinUrl(base: string, path: string): string {
  return `${base.replace(/\/+$/, "")}/${path.replace(/^\/+/, "")}`;
}

export function buildApiResourceUrl(relativePath: string): string {
  const base = apiClient.defaults.baseURL ?? "";
  if (!relativePath) return base;
  if (isHttpUrl(relativePath)) return relativePath;

  const normalizedPath = relativePath.startsWith("/")
    ? relativePath
    : `/${relativePath}`;
  if (!base) return normalizedPath;

  const normalizedBase = base.replace(/\/+$/, "");
  const baseIsAbsolute = isHttpUrl(normalizedBase);

  if (normalizedPath.startsWith("/api/")) {
    if (!baseIsAbsolute && normalizedBase === "/api") {
      return normalizedPath;
    }
    if (baseIsAbsolute) {
      try {
        const parsedBase = new URL(normalizedBase);
        const pathPrefixMatch = parsedBase.pathname.match(/^(.*)\/api$/);
        const pathPrefixRaw = pathPrefixMatch?.[1] ?? "";
        const pathPrefix = pathPrefixRaw === "/" ? "" : pathPrefixRaw.replace(/\/+$/, "");
        return `${parsedBase.origin}${pathPrefix}${normalizedPath}`;
      } catch {
        return normalizedPath;
      }
    }
  }

  return joinUrl(normalizedBase, normalizedPath);
}

function isServerErrorStatus(statusCode: number | null): boolean {
  return typeof statusCode === "number" && statusCode >= 500;
}

const HTTP_REASON_PHRASES: Record<number, string> = {
  400: "bad request",
  401: "unauthorized",
  402: "payment required",
  403: "forbidden",
  404: "not found",
  405: "method not allowed",
  408: "request timeout",
  409: "conflict",
  413: "payload too large",
  415: "unsupported media type",
  422: "unprocessable entity",
  429: "too many requests",
  500: "internal server error",
  502: "bad gateway",
  503: "service unavailable",
  504: "gateway timeout",
};

function summarizeApiErrorData(data: unknown, statusCode: number | null = null): unknown {
  void statusCode;
  return data ?? null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function formatValidationLocation(value: unknown): string | null {
  if (!Array.isArray(value) || value.length === 0) {
    return null;
  }
  return value.map((part) => String(part)).join(".");
}

function formatValidationDetails(details: unknown[]): string | null {
  const messages = details
    .map((item) => {
      if (!isRecord(item)) {
        return typeof item === "string" ? item : null;
      }
      const message = typeof item.msg === "string" ? item.msg : null;
      if (!message) {
        return null;
      }
      const location = formatValidationLocation(item.loc);
      return location ? `${location}: ${message}` : message;
    })
    .filter((message): message is string => Boolean(message));
  return messages.length > 0 ? messages.join("; ") : null;
}

const STRUCTURED_DETAIL_TRANSLATION_KEYS: ReadonlyMap<string, string> = new Map([
  ["vector_native_requires_svg", "api_error_vector_native_requires_svg"],
  ["source_image_unreadable", "api_error_source_image_unreadable"],
  ["source_image_too_large", "api_error_source_image_too_large"],
  ["source_svg_invalid", "api_error_source_svg_invalid"],
  [
    "source_svg_no_renderable_geometry",
    "api_error_source_svg_no_renderable_geometry",
  ],
  ["model_surface_empty_geometry", "api_error_model_surface_empty_geometry"],
  ["model_surface_invalid_file", "api_error_model_surface_invalid_file"],
  [
    "model_surface_mesh_not_watertight",
    "api_error_model_surface_mesh_not_watertight",
  ],
  ["model_surface_mesh_not_volume", "api_error_model_surface_mesh_not_volume"],
  [
    "model_surface_thickness_unknown",
    "api_error_model_surface_thickness_unknown",
  ],
  [
    "model_surface_insufficient_thickness",
    "api_error_model_surface_insufficient_thickness",
  ],
  ["model_surface_boolean_failed", "api_error_model_surface_boolean_failed"],
]);

function extractReadableDetail(data: unknown): string | null {
  if (typeof data === "string" && data.trim()) {
    return data.trim();
  }
  if (!isRecord(data)) {
    return null;
  }

  const detail = data.detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail.trim();
  }
  if (Array.isArray(detail)) {
    const validationMessage = formatValidationDetails(detail);
    if (validationMessage) {
      return validationMessage;
    }
  }

  if (isRecord(detail)) {
    const detailCode =
      typeof detail.error === "string" ? detail.error : detail.code;
    if (typeof detailCode === "string") {
      const translationKey = STRUCTURED_DETAIL_TRANSLATION_KEYS.get(detailCode);
      if (translationKey) {
        return tRuntime(translationKey);
      }
    }
    const detailMessage = detail.message;
    if (typeof detailMessage === "string" && detailMessage.trim()) {
      return detailMessage.trim();
    }
  }

  const message = data.message;
  if (typeof message === "string" && message.trim()) {
    return message.trim();
  }
  return null;
}

function isGenericHttpDetail(detail: string, statusCode: number | null): boolean {
  const normalized = detail.trim().toLowerCase();
  if (!normalized) {
    return true;
  }
  if (
    /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/.test(normalized) ||
    /^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$/.test(normalized)
  ) {
    return true;
  }
  if (
    typeof statusCode === "number" &&
    new RegExp(
      `^(?:request\\s+failed\\s+with\\s+status\\s+code\\s+|` +
        `(?:http\\s*)?(?:error|status(?:\\s+code)?)\\s*)?${statusCode}$`,
    ).test(normalized)
  ) {
    return true;
  }
  if (typeof statusCode === "number") {
    const reasonPhrase = HTTP_REASON_PHRASES[statusCode];
    if (reasonPhrase) {
      const escapedReason = reasonPhrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      if (
        new RegExp(
          `^(?:request\\s+failed\\s+with\\s+status\\s+code\\s+|` +
            `(?:http\\s*)?(?:error\\s+)?|status(?:\\s+code)?\\s*)?` +
            `${statusCode}\\s*(?::|-)?\\s*${escapedReason}\\.?$`,
        ).test(normalized)
      ) {
        return true;
      }
    }
  }
  return [
    "bad request",
    "unauthorized",
    "payment required",
    "forbidden",
    "not found",
    "method not allowed",
    "request timeout",
    "conflict",
    "payload too large",
    "unsupported media type",
    "unprocessable entity",
    "too many requests",
    "internal server error",
    "internal error",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
  ].includes(normalized);
}

function withRequestId(
  message: string,
  statusCode: number | null,
  requestId: string | null = null,
): string {
  if (!requestId || !isServerErrorStatus(statusCode)) {
    return message;
  }
  return tRuntime("api_error_with_request_id", { message, requestId });
}

function fallbackHttpStatusMessage(
  statusCode: number | null,
  requestId: string | null = null,
): string {
  switch (statusCode) {
    case 400:
      return tRuntime("api_error_http_400");
    case 401:
      return tRuntime("api_error_http_401");
    case 402:
      return tRuntime("api_error_http_402");
    case 403:
      return tRuntime("api_error_http_403");
    case 404:
      return tRuntime("api_error_http_404");
    case 405:
      return tRuntime("api_error_http_405");
    case 408:
      return tRuntime("api_error_http_408");
    case 409:
      return tRuntime("api_error_http_409");
    case 413:
      return tRuntime("api_error_http_413");
    case 415:
      return tRuntime("api_error_http_415");
    case 422:
      return tRuntime("api_error_http_422");
    case 429:
      return tRuntime("api_error_http_429");
    case 500:
      if (requestId) {
        return tRuntime("api_error_http_500_with_request_id", { requestId });
      }
      return tRuntime("api_error_http_500");
    case 502:
      return withRequestId(tRuntime("api_error_http_502"), statusCode, requestId);
    case 503:
      return withRequestId(tRuntime("api_error_http_503"), statusCode, requestId);
    case 504:
      return withRequestId(tRuntime("api_error_http_504"), statusCode, requestId);
    default:
      if (typeof statusCode !== "number") {
        return tRuntime("api_error_no_response");
      }
      if (statusCode >= 400 && statusCode < 500) {
        return tRuntime("api_error_http_client_default");
      }
      if (statusCode >= 500 && statusCode < 600) {
        return withRequestId(
          tRuntime("api_error_http_server_default"),
          statusCode,
          requestId,
        );
      }
      return tRuntime("api_error_http_default");
  }
}

export function apiStatusCodeToVisibleMessage(
  statusCode: number | null,
  requestId: string | null = null,
): string {
  return fallbackHttpStatusMessage(statusCode, requestId);
}

function readableApiErrorMessage(
  data: unknown,
  statusCode: number | null,
  error: unknown,
  requestId: string | null = null,
): string {
  const detail = extractReadableDetail(data);
  if (
    detail &&
    !isGenericHttpDetail(detail, statusCode)
  ) {
    return detail;
  }
  const fallback = fallbackHttpStatusMessage(statusCode, requestId);
  if (fallback) {
    return fallback;
  }
  return error instanceof Error ? error.message : String(error ?? "API request failed");
}

function errorMessageFromUnknown(error: unknown): string {
  if (error instanceof Error) {
    return error.message.trim();
  }
  if (typeof error === "string") {
    return error.trim();
  }
  return String(error ?? "").trim();
}

function extractStatusCodeFromGenericErrorMessage(message: string): number | null {
  const match = message
    .trim()
    .toLowerCase()
    .match(
      /(?:request\s+failed\s+with\s+status\s+code|http(?:\s+error)?|(?:error|status(?:\s+code)?))\s*(\d{3})\b/,
    );
  if (!match) {
    return null;
  }
  const statusCode = Number(match[1]);
  return Number.isInteger(statusCode) ? statusCode : null;
}

function cleanHttpStatusSuffix(suffix: string): string {
  const trimmed = suffix.trim();
  if (!trimmed) {
    return "";
  }
  const symbolSeparated = trimmed.match(/^(?::|-)\s*(.*)$/);
  if (symbolSeparated) {
    return symbolSeparated[1]?.trim() ?? "";
  }
  const wordSeparated = trimmed.match(/^(?:at|for)\s+(.+)$/i);
  if (wordSeparated) {
    return wordSeparated[1]?.trim() ?? "";
  }
  return trimmed;
}

function statusPrefixedErrorVisibleMessage(
  message: string,
  statusCode: number | null,
  requestId: string | null = null,
): string | null {
  if (typeof statusCode !== "number") {
    return null;
  }
  const escapedStatus = String(statusCode).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = message.trim().match(
    new RegExp(
      `^(?:axioserror:\\s*)?` +
        `(?:request\\s+failed\\s+with\\s+status\\s+code|` +
        `http(?:\\s+error)?|status(?:\\s+code)?)` +
        `\\s*${escapedStatus}\\b` +
        `(.*)$`,
      "i",
    ),
  );
  if (!match) {
    return null;
  }

  const suffix = cleanHttpStatusSuffix(match[1] ?? "");
  if (
    !suffix ||
    isGenericHttpDetail(suffix, statusCode)
  ) {
    return fallbackHttpStatusMessage(statusCode, requestId);
  }
  return suffix;
}

function isGenericNoResponseErrorMessage(message: string): boolean {
  const normalized = message.trim().toLowerCase();
  if (!normalized) {
    return false;
  }
  return (
    normalized === "network error" ||
    normalized === "failed to fetch" ||
    normalized.includes("networkerror when attempting to fetch resource") ||
    /^timeout of \d+ms exceeded$/.test(normalized) ||
    normalized === "econnaborted" ||
    normalized.includes("econnaborted")
  );
}

export function apiErrorToVisibleMessage(
  error: unknown,
  fallback: string = tRuntime("api_error_http_default"),
): string {
  const response = isRecord(error) && isRecord(error.response) ? error.response : null;
  const statusCode =
    typeof response?.status === "number"
      ? response.status
      : extractStatusCodeFromGenericErrorMessage(errorMessageFromUnknown(error));
  const requestId = getResponseHeaderValue(response?.headers, "x-request-id");
  if (response) {
    return readableApiErrorMessage(response.data, statusCode, error, requestId);
  }

  const rawMessage = errorMessageFromUnknown(error);
  if (!(error instanceof Error)) {
    if (
      typeof statusCode === "number" &&
      isGenericHttpDetail(rawMessage, statusCode)
    ) {
      return fallbackHttpStatusMessage(statusCode, requestId);
    }
    if (isGenericNoResponseErrorMessage(rawMessage)) {
      return fallbackHttpStatusMessage(null);
    }
    return fallback;
  }
  const statusPrefixedMessage = statusPrefixedErrorVisibleMessage(
    rawMessage,
    statusCode,
    requestId,
  );
  if (statusPrefixedMessage) {
    return statusPrefixedMessage;
  }
  if (
    typeof statusCode === "number" &&
    isGenericHttpDetail(rawMessage, statusCode)
  ) {
    return fallbackHttpStatusMessage(statusCode, requestId);
  }
  if (isGenericNoResponseErrorMessage(rawMessage)) {
    return fallbackHttpStatusMessage(null);
  }
  return rawMessage || fallback;
}

function getResponseHeaderValue(
  headers: unknown,
  name: string,
): string | null {
  if (!headers) {
    return null;
  }
  const lowerName = name.toLowerCase();
  if (
    typeof (headers as { get?: unknown }).get === "function"
  ) {
    const value = (headers as { get: (headerName: string) => unknown }).get(name);
    return typeof value === "string" && value.trim() ? value.trim() : null;
  }
  if (isRecord(headers)) {
    for (const [key, value] of Object.entries(headers)) {
      if (key.toLowerCase() !== lowerName) {
        continue;
      }
      return typeof value === "string" && value.trim() ? value.trim() : null;
    }
  }
  return null;
}

function recordApiFailure({
  method,
  url,
  statusCode,
  requestId,
  responseDetailForLog,
  error,
  readableMessage,
}: {
  method: string | null;
  url: string | null;
  statusCode: number | null;
  requestId: string | null;
  responseDetailForLog: unknown;
  error: unknown;
  readableMessage: string;
}): void {
  postClientLog("api: request failed", {
    scope: "api",
    phase: "request-failed",
    method: "error",
    dedupeMs: 500,
    details: {
      method,
      url,
      status_code: statusCode,
      request_id: requestId,
      response_detail: responseDetailForLog,
      ...summarizeErrorForLog(error),
      error,
      error_message: readableMessage,
    },
  });
  // Mirror the failure into the action history bundle so a bug report
  // submitted minutes later still sees the recent 4xx/5xx context.
  // 同步写入操作历史，便于后续提交 Bug 报告时仍能带上最近的 API 错误。
  if (typeof statusCode === "number" && statusCode >= 400) {
    try {
      useActionHistoryStore.getState().pushAction({
        action_type: "api_error",
        error: {
          status_code: statusCode,
          path: typeof url === "string" ? url : String(url ?? ""),
          ...(requestId ? { request_id: requestId } : {}),
          error_message: readableMessage,
        },
      });
    } catch {
      // Action history must never propagate failure into the HTTP layer.
      // 即便历史记录失败，也不得影响 HTTP 调用链。
    }
  }
  // Offer a bug-report ticket for unexpected server failures (5xx only).
  // 服务端意外错误（仅 5xx）时提示用户是否提交工单。
  useErrorTicketPromptStore.getState().reportApiError({
    statusCode,
    path: url,
    requestId,
    message: readableMessage,
  });
}

async function readResourceErrorData(response: Response): Promise<unknown> {
  const contentType = getResponseHeaderValue(response.headers, "content-type");
  if (contentType?.toLowerCase().includes("json")) {
    try {
      return await response.json();
    } catch {
      return null;
    }
  }

  try {
    const text = await response.text();
    return text.trim() ? text.trim() : null;
  } catch {
    return null;
  }
}

function buildResourceDownloadError(
  url: string,
  response: Response,
  data: unknown,
): Error {
  const statusCode =
    typeof response.status === "number" ? response.status : null;
  const requestId = getResponseHeaderValue(response.headers, "x-request-id");
  const readableMessage = readableApiErrorMessage(
    data,
    statusCode,
    new Error(`Resource download failed: ${url}`),
    requestId,
  );
  const responseData = data;
  const error = new Error(readableMessage) as Error & {
    response?: {
      status: number | null;
      data: unknown;
      headers: Headers;
    };
  };
  error.response = {
    status: statusCode,
    data: responseData,
    headers: response.headers,
  };
  recordApiFailure({
    method: "GET",
    url,
    statusCode,
    requestId,
    responseDetailForLog: summarizeApiErrorData(data, statusCode),
    error,
    readableMessage,
  });
  return error;
}

function buildResourceNetworkError(
  url: string,
  cause: unknown,
): Error {
  const readableMessage = readableApiErrorMessage(null, null, cause);
  const responseData = { detail: readableMessage, url };
  const error = new Error(readableMessage, { cause }) as Error & {
    response?: {
      status: number | null;
      data: unknown;
      headers: Headers;
    };
  };
  error.response = {
    status: null,
    data: responseData,
    headers: new Headers(),
  };
  recordApiFailure({
    method: "GET",
    url,
    statusCode: null,
    requestId: null,
    responseDetailForLog: responseData,
    error,
    readableMessage,
  });
  return error;
}

export async function downloadResourceBlob(
  url: string,
  init?: RequestInit,
): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    throw buildResourceNetworkError(url, error);
  }
  const failed =
    response.ok === false ||
    (typeof response.ok !== "boolean" &&
      typeof response.status === "number" &&
      response.status >= 400);
  if (failed) {
    const data = await readResourceErrorData(response);
    throw buildResourceDownloadError(url, response, data);
  }
  try {
    return await response.blob();
  } catch (error) {
    throw buildResourceNetworkError(url, error);
  }
}

export async function assertResourceDownloadAvailable(
  url: string,
  init?: RequestInit,
): Promise<void> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Range")) {
    headers.set("Range", "bytes=0-0");
  }
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers,
    });
  } catch (error) {
    throw buildResourceNetworkError(url, error);
  }
  const failed =
    response.ok === false ||
    (typeof response.ok !== "boolean" &&
      typeof response.status === "number" &&
      response.status >= 400);
  if (failed) {
    const data = await readResourceErrorData(response);
    throw buildResourceDownloadError(url, response, data);
  }
  try {
    await response.body?.cancel();
  } catch {
    // The validation request only needs headers/status. Ignore body cleanup failures.
  }
}

apiClient.interceptors.request.use((config) => {
  if (config.data instanceof FormData && !config.url?.includes("/feedback/")) {
    for (const value of config.data.values()) {
      if (typeof File !== "undefined" && value instanceof File) rememberFeedbackSource(value);
    }
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (axios.isCancel(error) || error?.code === "ERR_CANCELED") {
      return Promise.reject(error);
    }
    const response = error?.response;
    const config = error?.config;
    const suppressClientLog = config?.suppressClientLog === true;
    const method =
      typeof config?.method === "string" ? config.method.toUpperCase() : null;
    const url = config?.url ?? null;
    const statusCode: number | null = response?.status ?? null;
    const requestId = getResponseHeaderValue(response?.headers, "x-request-id");
    const readableMessage = readableApiErrorMessage(
      response?.data,
      statusCode,
      error,
      requestId,
    );
    const responseDetailForLog = summarizeApiErrorData(
      response?.data,
      statusCode,
    );
    if (!suppressClientLog) {
      recordApiFailure({
        method,
        url,
        statusCode,
        requestId,
        responseDetailForLog,
        error,
        readableMessage,
      });
    }
    if (error && typeof error === "object") {
      try {
        (error as { message?: string }).message = readableMessage;
      } catch {
        // Preserve the original error object if a runtime marks message read-only.
      }
    }
    return Promise.reject(error);
  },
);

export default apiClient;
