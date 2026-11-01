"use strict";

const crypto = require("crypto");

const MODULE_ID_SOURCE =
  "[a-z0-9]+(?:[.-][a-z0-9]+(?:[a-z0-9-]*[a-z0-9])?)*";
const SEMVER_SOURCE =
  "(?:0|[1-9]\\d*)\\.(?:0|[1-9]\\d*)\\.(?:0|[1-9]\\d*)" +
  "(?:-(?:0|[1-9]\\d*|[A-Za-z-][0-9A-Za-z-]*)" +
  "(?:\\.(?:0|[1-9]\\d*|[A-Za-z-][0-9A-Za-z-]*))*)?" +
  "(?:\\+[0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*)?";
const RUNTIME_URL_PATTERN = new RegExp(
  `^lumina-workshop://(${MODULE_ID_SOURCE})/(${SEMVER_SOURCE})/ui/index\\.html$`,
);
const BACKEND_RUNTIME_PATH_PATTERN = new RegExp(
  `^/api/workshop/v1/modules/${MODULE_ID_SOURCE}/${SEMVER_SOURCE}/runtime$`,
);
const BACKEND_BED_MODEL_PATH =
  "/api/system/machine-registry/bed-model";
const DEVICE_PROFILE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/;
const WIKI_HOST = "wiki.luminastudio.com.cn";
const WIKI_DOC_PATH_PATTERN = /^\/(?:zh|en)\/docs(?:\/|$)/;
const NON_NETWORK_RESOURCE_TYPES = new Set([
  "font",
  "image",
  "media",
  "worker",
]);
let managedDesktopHostEnabled = false;
let desktopBackendPort = "8000";

/** Enable the selected desktop frontend from the main process before navigation.
 * 主进程在导航前启用所选端口的桌面前端；不接受 renderer 提供的地址。
 */
function enableManagedDesktopHost(port = 8000) {
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new TypeError("Invalid desktop backend port.");
  desktopBackendPort = String(port);
  managedDesktopHostEnabled = true;
}

function parseUrl(value) {
  if (typeof value !== "string" || value.length === 0) {
    return null;
  }
  try {
    return new URL(value);
  } catch {
    return null;
  }
}

function isWorkshopRuntimeUrl(value) {
  return (
    typeof value === "string" &&
    RUNTIME_URL_PATTERN.test(value)
  );
}

function isTrustedHostUrl(value) {
  const parsed = parseUrl(value);
  if (parsed === null) {
    return false;
  }
  if (parsed.protocol === "file:") {
    return parsed.username === "" && parsed.password === "";
  }
  if (parsed.username !== "" || parsed.password !== "") return false;
  return (
    parsed.protocol === "http:" &&
    parsed.hostname === "127.0.0.1" &&
    (parsed.port === "4174" ||
      (managedDesktopHostEnabled && parsed.port === desktopBackendPort && parsed.pathname === "/"))
  );
}

function isOpaqueOrigin(value) {
  return value === "null";
}

function isNonNetworkModuleResource(resourceType, targetUrl) {
  if (!NON_NETWORK_RESOURCE_TYPES.has(resourceType)) {
    return false;
  }
  const parsed = parseUrl(targetUrl);
  return (
    parsed !== null &&
    (parsed.protocol === "blob:" || parsed.protocol === "data:")
  );
}

function isTrustedInternalRuntimeRequest(details) {
  if (details.trustedInternal !== true) {
    return false;
  }
  const parsed = parseUrl(details.url);
  return (
    parsed !== null &&
    parsed.protocol === "http:" &&
    parsed.hostname === "127.0.0.1" &&
    parsed.port === desktopBackendPort &&
    parsed.username === "" &&
    parsed.password === "" &&
    parsed.search === "" &&
    parsed.hash === "" &&
    BACKEND_RUNTIME_PATH_PATTERN.test(parsed.pathname)
  );
}

function isTrustedInternalBedModelRequest(details) {
  if (
    details.trustedInternal !== true ||
    (details.method !== undefined && details.method !== "GET")
  ) {
    return false;
  }
  const parsed = parseUrl(details.url);
  if (
    parsed === null ||
    parsed.protocol !== "http:" ||
    parsed.hostname !== "127.0.0.1" ||
    parsed.port !== desktopBackendPort ||
    parsed.username !== "" ||
    parsed.password !== "" ||
    parsed.pathname !== BACKEND_BED_MODEL_PATH ||
    parsed.hash !== ""
  ) {
    return false;
  }
  const parameters = [...parsed.searchParams.entries()];
  return (
    parameters.length === 1 &&
    parameters[0][0] === "device_profile_id" &&
    DEVICE_PROFILE_ID_PATTERN.test(parameters[0][1])
  );
}

function createWorkshopSessionToken() {
  return crypto.randomBytes(32).toString("base64url");
}

function resolveWorkshopRuntimeRequest(
  value,
  backendOrigin = "http://127.0.0.1:8000",
) {
  if (typeof value !== "string") {
    return null;
  }
  const match = RUNTIME_URL_PATTERN.exec(value);
  if (match === null) {
    return null;
  }
  const origin = parseUrl(backendOrigin);
  if (
    origin === null ||
    origin.protocol !== "http:" ||
    origin.hostname !== "127.0.0.1" ||
    origin.username !== "" ||
    origin.password !== "" ||
    origin.pathname !== "/" ||
    origin.search !== "" ||
    origin.hash !== ""
  ) {
    return null;
  }
  const moduleId = match[1];
  const version = match[2];
  return {
    moduleId,
    version,
    backendUrl:
      `${origin.origin}/api/workshop/v1/modules/` +
      `${moduleId}/${version}/runtime`,
  };
}

function isAllowedWorkshopRequest(details) {
  if (
    isTrustedInternalRuntimeRequest(details) ||
    isTrustedInternalBedModelRequest(details)
  ) {
    return true;
  }

  const frameIsModule = isWorkshopRuntimeUrl(details.frameUrl);
  const parentFrameIsHost = isTrustedHostUrl(details.parentFrameUrl);
  const initiatorIsModule = isWorkshopRuntimeUrl(details.initiator);
  const initiatorIsHost = isTrustedHostUrl(details.initiator);
  if (
    isWorkshopRuntimeUrl(details.url) &&
    details.resourceType === "subFrame" &&
    (initiatorIsHost || parentFrameIsHost)
  ) {
    return true;
  }
  if (
    isTrustedHostUrl(details.url) &&
    details.resourceType === "mainFrame" &&
    !frameIsModule &&
    !initiatorIsModule &&
    !isOpaqueOrigin(details.initiator)
  ) {
    return true;
  }
  if (frameIsModule || initiatorIsModule) {
    return isNonNetworkModuleResource(
      details.resourceType,
      details.url,
    );
  }

  const frameIsHost = isTrustedHostUrl(details.frameUrl);
  if (frameIsHost || initiatorIsHost) {
    if (isWorkshopRuntimeUrl(details.url)) {
      return details.resourceType === "subFrame";
    }
    return true;
  }

  // Opaque or missing renderer identity is never enough authority to reach
  // the network or to create a module frame.
  if (
    isOpaqueOrigin(details.initiator) ||
    details.frameUrl == null ||
    details.initiator == null
  ) {
    return false;
  }
  return false;
}

function shouldBlockWorkshopNavigation(details) {
  if (
    isWorkshopRuntimeUrl(details.frameUrl) ||
    isWorkshopRuntimeUrl(details.initiatorUrl) ||
    isOpaqueOrigin(details.initiatorUrl)
  ) {
    return true;
  }

  if (isWorkshopRuntimeUrl(details.targetUrl)) {
    return !(
      details.isMainFrame === false &&
      isTrustedHostUrl(details.initiatorUrl)
    );
  }
  return false;
}

function shouldBlockWorkshopRedirect(details) {
  if (
    isWorkshopRuntimeUrl(details.frameUrl) ||
    isWorkshopRuntimeUrl(details.initiatorUrl) ||
    isOpaqueOrigin(details.initiatorUrl)
  ) {
    return true;
  }
  return isWorkshopRuntimeUrl(details.targetUrl);
}

function shouldRetryFrontendLoad(details) {
  return (
    details.isMainFrame === true &&
    isTrustedHostUrl(details.validatedUrl)
  );
}

function isAllowedWorkshopIpcSender(frameUrl) {
  return isTrustedHostUrl(frameUrl);
}

/**
 * Accept only the public documentation surface of the official Wiki.
 *
 * The renderer may provide the locale, path, and hash, but the main process
 * still validates the complete URL before it reaches the system browser.
 */
function isAllowedWikiUrl(value) {
  const parsed = parseUrl(value);
  return (
    parsed !== null &&
    parsed.protocol === "https:" &&
    parsed.hostname === WIKI_HOST &&
    parsed.port === "" &&
    parsed.username === "" &&
    parsed.password === "" &&
    WIKI_DOC_PATH_PATTERN.test(parsed.pathname)
  );
}

/**
 * Require the current trusted main window and its top-level frame for Wiki IPC.
 *
 * Workshop iframes deliberately do not satisfy this contract, and a missing
 * frame URL is never treated as an authority signal.
 */
function isAllowedWikiIpcSender(details) {
  return (
    details !== null &&
    typeof details === "object" &&
    details.isMainFrame === true &&
    Number.isInteger(details.senderWebContentsId) &&
    details.senderWebContentsId === details.trustedWebContentsId &&
    typeof details.senderFrameUrl === "string" &&
    details.senderFrameUrl === details.trustedMainFrameUrl &&
    isTrustedHostUrl(details.senderFrameUrl)
  );
}

function isAllowedWorkshopPopup(details) {
  if (
    !isTrustedHostUrl(details.openerUrl) ||
    isWorkshopRuntimeUrl(details.targetUrl)
  ) {
    return false;
  }
  const target = parseUrl(details.targetUrl);
  return (
    target !== null &&
    (target.protocol === "http:" || target.protocol === "https:")
  );
}

function isAllowedWorkshopPermission(details) {
  return (
    isTrustedHostUrl(details.frameUrl) &&
    !isOpaqueOrigin(details.requestingOrigin) &&
    !isWorkshopRuntimeUrl(details.requestingOrigin)
  );
}

function isAllowedWorkshopDownload(details) {
  if (!isTrustedHostUrl(details.frameUrl)) {
    return false;
  }
  const target = parseUrl(details.url);
  return (
    target !== null &&
    (target.protocol === "http:" || target.protocol === "https:" ||
      (target.protocol === "blob:" &&
        target.origin !== "null" &&
        target.origin === parseUrl(details.frameUrl).origin))
  );
}

function isWorkshopFrameProcessIsolated(mainProcessId, moduleProcessId) {
  return (
    Number.isInteger(mainProcessId) &&
    mainProcessId > 0 &&
    Number.isInteger(moduleProcessId) &&
    moduleProcessId > 0 &&
    mainProcessId !== moduleProcessId
  );
}

module.exports = {
  enableManagedDesktopHost,
  createWorkshopSessionToken,
  isAllowedWorkshopDownload,
  isAllowedWorkshopIpcSender,
  isAllowedWorkshopPermission,
  isAllowedWorkshopPopup,
  isAllowedWorkshopRequest,
  isAllowedWikiIpcSender,
  isAllowedWikiUrl,
  isWorkshopFrameProcessIsolated,
  resolveWorkshopRuntimeRequest,
  shouldBlockWorkshopNavigation,
  shouldBlockWorkshopRedirect,
  shouldRetryFrontendLoad,
};
