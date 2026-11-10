import type {
  HostWorkshopRpcMethod,
  WorkshopPermissionName,
} from "../contracts";
import {
  isWorkshopBackendRpcMethod,
  isWorkshopPermissionName,
} from "../contracts";


export const METHOD_PERMISSION = {
  "image.pick": "image.pick",
  "project.save": "project.storage",
  "project.load": "project.storage",
  "project.latest": "project.storage",
  "project.remove": "project.storage",
  "colorLibrary.read": "color-library.read",
  "handoff.image": "handoff.image",
  "ui.getState": null,
  "status.progress": null,
  "status.error": null,
  "status.diagnostics": null,
  "lifecycle.ready": null,
} as const satisfies Record<
  Exclude<HostWorkshopRpcMethod, `backend.${string}`>,
  WorkshopPermissionName | null
>;

export interface WorkshopMethodEligibility {
  /**
   * The exact module version declares a backend (manifest v2). Consent and
   * Registry state are enforced again by the backend API on every call.
   */
  backend: boolean;
}

export function normalizeWorkshopPermissions(
  values: ReadonlySet<string>,
): ReadonlySet<WorkshopPermissionName> {
  const permissions = new Set<WorkshopPermissionName>();
  for (const value of values) {
    if (!isWorkshopPermissionName(value)) {
      throw new TypeError(`Unknown Workshop permission: ${value}`);
    }
    permissions.add(value);
  }
  return permissions;
}

export function requiredPermission(
  method: HostWorkshopRpcMethod,
): WorkshopPermissionName | null {
  if (isWorkshopBackendRpcMethod(method)) {
    return null;
  }
  return METHOD_PERMISSION[method];
}

export function hasMethodPermission(
  permissions: ReadonlySet<WorkshopPermissionName>,
  method: HostWorkshopRpcMethod,
  eligibility: WorkshopMethodEligibility = { backend: false },
): boolean {
  if (isWorkshopBackendRpcMethod(method)) {
    return eligibility.backend;
  }
  const required = requiredPermission(method);
  return required === null || permissions.has(required);
}
