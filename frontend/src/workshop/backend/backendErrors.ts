import { workshopBackendFailure } from "../../api/workshop";

/**
 * Translation key for why a backend management action failed and what the
 * user can do next. Unknown failures still get an actionable message.
 * 后端管理操作失败的原因与处理办法。
 */
export function backendActionErrorKey(error: unknown): string {
  const { status, code, unreachable } = workshopBackendFailure(error);
  switch (code) {
    case "backend-authorization-required":
    case "unreviewed-confirmation-required":
      return "workshop.backend.error.authorization";
    case "task-active":
      return "workshop.backend.error.taskActive";
    case "module-version-blocked":
      return "workshop.backend.blocked";
    case "backend-tool-unavailable":
      return "workshop.backend.toolUnavailable";
    case "model-not-retained":
    case "task-not-found":
    case "module-not-installed":
    case "module-version-unavailable":
      return "workshop.backend.error.gone";
    default:
      break;
  }
  if (unreachable) {
    return "workshop.backend.error.network";
  }
  return status === 409 ? "workshop.backend.error.conflict" : "workshop.backend.error.generic";
}
