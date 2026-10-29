const handledErrors = new WeakSet<object>();

/** R3F reports even boundary-caught errors through window.reportError. */
export function markSceneErrorHandled(error: unknown): void {
  if (typeof error === "object" && error !== null) handledErrors.add(error);
}

export function isHandledSceneError(error: unknown): boolean {
  return typeof error === "object" && error !== null && handledErrors.has(error);
}
