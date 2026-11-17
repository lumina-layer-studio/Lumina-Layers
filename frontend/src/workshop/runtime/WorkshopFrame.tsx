import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { useI18n } from "../../i18n/context";
import { createRandomId } from "../../utils/randomId";
import { registerWorkshopProject, workshopProjectChanged } from "../../project/workshopRuntime";
import { WorkshopProjectChannel } from "./projectChannel";
import {
  type WorkshopPermissionName,
  type WorkshopUiState,
} from "../contracts";
import {
  canRunWorkshopInBrowser,
  desktopModuleUrl,
  injectWorkshopRuntimeCsp,
  isWorkshopApiCompatible,
  negotiateReady,
  WORKSHOP_HANDSHAKE_TIMEOUT_MS,
  type WorkshopApiRange,
  type WorkshopInstallSource,
  type WorkshopRuntimeMode,
  type WorkshopStartupFailure,
  type WorkshopStartupFailureReason,
} from "./health";
import {
  createWorkshopRpcHost,
  type WorkshopMessagePort,
  type WorkshopRpcHandler,
  type WorkshopRpcHandlers,
  type WorkshopRpcHost,
} from "./rpcHost";

export interface WorkshopFrameModule {
  moduleId: string;
  moduleVersion: string;
  displayName: string;
  source: WorkshopInstallSource;
  official: boolean;
  enabled: boolean;
  runtimeUrl: string | null;
  browserRuntimeHtml?: string | null;
  workshopApi: WorkshopApiRange;
  permissions: readonly WorkshopPermissionName[];
  candidate: boolean;
  previousVersion: string | null;
  consecutiveStartFailures: number;
  /** The exact version declares a host-managed backend (manifest v2). */
  hasBackend?: boolean;
  projectSnapshotProtocol?: number | null;
  projectSnapshotSchemas?: readonly string[];
}

const BACKEND_PRESENCE_INTERVAL_MS = 30_000;

export interface WorkshopFrameChannel {
  port1: WorkshopMessagePort;
  port2: MessagePort;
}

export interface WorkshopFrameProps {
  module: WorkshopFrameModule;
  runtimeMode?: WorkshopRuntimeMode;
  handlers?: WorkshopRpcHandlers;
  uiState?: WorkshopUiState;
  syntheticHandlers?: WorkshopRpcHandlers;
  createChannel?: () => WorkshopFrameChannel;
  loadBrowserRuntime?: (url: string) => Promise<string>;
  prepareCandidate?: (
    moduleId: string,
    moduleVersion: string,
  ) => void | Promise<void>;
  activateCandidate?: (
    moduleId: string,
    moduleVersion: string,
  ) => void | Promise<void>;
  onStartSuccess?: (
    moduleId: string,
    moduleVersion: string,
  ) => void | Promise<void>;
  onStartFailure?: (
    failure: WorkshopStartupFailure,
  ) => void | Promise<void>;
  disableVersion?: (
    moduleId: string,
    moduleVersion: string,
  ) => void | Promise<void>;
  /** Heartbeat while a backend module's UI is open (extends idle time). */
  onBackendPresence?: (moduleId: string) => void | Promise<void>;
}

type RuntimePhase =
  | "preparing"
  | "loading"
  | "handshaking"
  | "connected"
  | "ready"
  | "failed"
  | "desktop-required"
  | "disabled"
  | "incompatible";

interface RuntimeDocument {
  src?: string;
  srcDoc?: string;
}

interface RuntimeProgress {
  phase: string;
  completed: number;
  total: number;
}

interface RuntimeError {
  code: string;
  message: string;
  retryable: boolean;
}

const EMPTY_HANDLERS: WorkshopRpcHandlers = Object.freeze({});

function defaultCreateChannel(): WorkshopFrameChannel {
  const channel = new MessageChannel();
  return {
    port1: channel.port1,
    port2: channel.port2,
  };
}

async function defaultLoadBrowserRuntime(
  url: string,
): Promise<string> {
  const response = await fetch(url, {
    cache: "no-store",
    credentials: "same-origin",
    redirect: "error",
  });
  if (!response.ok) {
    throw new Error(
      `Workshop runtime returned HTTP ${response.status}.`,
    );
  }
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().includes("text/html")) {
    throw new Error("Workshop runtime did not return HTML.");
  }
  return response.text();
}

function progressValue(value: unknown): RuntimeProgress | null {
  if (value === null) {
    return null;
  }
  return value as RuntimeProgress;
}

function errorValue(value: unknown): RuntimeError | null {
  if (value === null) {
    return null;
  }
  return value as RuntimeError;
}

export function WorkshopFrame({
  module,
  runtimeMode = "browser",
  handlers = EMPTY_HANDLERS,
  uiState,
  syntheticHandlers = EMPTY_HANDLERS,
  createChannel = defaultCreateChannel,
  loadBrowserRuntime = defaultLoadBrowserRuntime,
  prepareCandidate,
  activateCandidate,
  onStartSuccess,
  onStartFailure,
  disableVersion,
  onBackendPresence,
}: WorkshopFrameProps) {
  const { t } = useI18n();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const handshakeTimerRef = useRef<ReturnType<
    typeof setTimeout
  > | null>(null);
  const hostRef = useRef<WorkshopRpcHost | null>(null);
  const detachPortRef = useRef<(() => void) | null>(null);
  const detachProjectRef = useRef<(() => void) | null>(null);
  const handshakeAcceptedRef = useRef(false);
  const failureHandledRef = useRef(false);
  const mountedRef = useRef(true);
  const prepareCandidateRef = useRef(prepareCandidate);
  const onStartFailureRef = useRef(onStartFailure);
  const disableVersionRef = useRef(disableVersion);
  const candidatePropRef = useRef(module.candidate);
  // Activation updates the prop mid-connection; keep startup intent separate.
  const sessionCandidateRef = useRef(module.candidate);
  const [runtimeDocument, setRuntimeDocument] =
    useState<RuntimeDocument | null>(null);
  const [phase, setPhase] = useState<RuntimePhase>("preparing");
  const [failureReason, setFailureReason] =
    useState<WorkshopStartupFailureReason | null>(null);
  const [progress, setProgress] =
    useState<RuntimeProgress | null>(null);
  const [moduleError, setModuleError] =
    useState<RuntimeError | null>(null);
  const runtimeModuleId = module.moduleId;
  const runtimeModuleVersion = module.moduleVersion;
  const runtimeApiMin = module.workshopApi.min;
  const runtimeApiMaxExclusive =
    module.workshopApi.maxExclusive;
  const runtimePermissionsJson = JSON.stringify(
    module.permissions,
  );
  const snapshotSchemasJson = JSON.stringify(module.projectSnapshotSchemas ?? []);
  const snapshotProtocol = module.projectSnapshotProtocol;

  useEffect(() => {
    candidatePropRef.current = module.candidate;
  }, [module.candidate]);

  useEffect(() => {
    prepareCandidateRef.current = prepareCandidate;
  }, [prepareCandidate]);

  useEffect(() => {
    onStartFailureRef.current = onStartFailure;
    disableVersionRef.current = disableVersion;
  }, [disableVersion, onStartFailure]);

  const clearHandshakeTimer = useCallback(() => {
    if (handshakeTimerRef.current === null) {
      return;
    }
    clearTimeout(handshakeTimerRef.current);
    handshakeTimerRef.current = null;
  }, []);

  const closeConnection = useCallback(() => {
    clearHandshakeTimer();
    detachProjectRef.current?.();
    detachProjectRef.current = null;
    const detach = detachPortRef.current;
    detachPortRef.current = null;
    detach?.();
    hostRef.current?.close();
    hostRef.current = null;
  }, [clearHandshakeTimer]);

  useEffect(() => {
    if (uiState !== undefined) {
      hostRef.current?.emit("ui.stateChanged", uiState);
    }
  }, [uiState]);

  const failStartup = useCallback(
    (reason: WorkshopStartupFailureReason) => {
      if (failureHandledRef.current) {
        return;
      }
      failureHandledRef.current = true;
      closeConnection();
      setRuntimeDocument(null);
      setFailureReason(reason);
      setPhase("failed");
      const consecutiveFailures = Math.min(
        3,
        module.consecutiveStartFailures + 1,
      );
      const failure: WorkshopStartupFailure = {
        moduleId: module.moduleId,
        moduleVersion: module.moduleVersion,
        reason,
        consecutiveFailures,
      };
      void Promise.resolve(
        onStartFailureRef.current?.(failure),
      ).finally(() => {
        if (
          consecutiveFailures >= 3 &&
          module.previousVersion === null
        ) {
          void disableVersionRef.current?.(
            module.moduleId,
            module.moduleVersion,
          );
        }
      });
    },
    [
      closeConnection,
      module.consecutiveStartFailures,
      module.moduleId,
      module.moduleVersion,
      module.previousVersion,
    ],
  );

  useEffect(() => {
    const sessionCandidate = candidatePropRef.current;
    sessionCandidateRef.current = sessionCandidate;
    mountedRef.current = true;
    handshakeAcceptedRef.current = false;
    failureHandledRef.current = false;
    setRuntimeDocument(null);
    setFailureReason(null);
    setProgress(null);
    setModuleError(null);

    let cancelled = false;
    const prepare = async () => {
      if (!module.enabled) {
        setPhase("disabled");
        return;
      }
      if (
        !isWorkshopApiCompatible({
          min: runtimeApiMin,
          maxExclusive: runtimeApiMaxExclusive,
        })
      ) {
        setPhase("incompatible");
        return;
      }
      if (
        !canRunWorkshopInBrowser(
          module.source,
          module.official,
          runtimeMode,
        )
      ) {
        setPhase("desktop-required");
        return;
      }
      setPhase("preparing");
      if (sessionCandidate) {
        if (prepareCandidateRef.current === undefined) {
          failStartup("candidate-prepare-failed");
          return;
        }
        try {
          await prepareCandidateRef.current(
            module.moduleId,
            module.moduleVersion,
          );
        } catch {
          failStartup("candidate-prepare-failed");
          return;
        }
      }
      if (cancelled) {
        return;
      }
      setPhase("loading");
      if (runtimeMode === "desktop-secure") {
        setRuntimeDocument({
          src: desktopModuleUrl(
            module.moduleId,
            module.moduleVersion,
          ),
        });
        return;
      }
      try {
        const html =
          module.browserRuntimeHtml ??
          (module.runtimeUrl === null
            ? null
            : await loadBrowserRuntime(module.runtimeUrl));
        if (html === null) {
          throw new Error("Workshop runtime HTML is unavailable.");
        }
        const srcDoc = injectWorkshopRuntimeCsp(html);
        if (!cancelled) {
          setRuntimeDocument({ srcDoc });
        }
      } catch {
        if (!cancelled) {
          failStartup("runtime-load-failed");
        }
      }
    };

    void prepare();
    return () => {
      cancelled = true;
      mountedRef.current = false;
      closeConnection();
    };
  }, [
    closeConnection,
    failStartup,
    loadBrowserRuntime,
    module.browserRuntimeHtml,
    module.enabled,
    module.moduleId,
    module.moduleVersion,
    module.official,
    module.runtimeUrl,
    module.source,
    runtimeApiMaxExclusive,
    runtimeApiMin,
    runtimeMode,
  ]);

  const handleFrameLoad = useCallback(() => {
    if (
      runtimeDocument === null ||
      failureHandledRef.current ||
      handshakeAcceptedRef.current
    ) {
      return;
    }
    setPhase("handshaking");
    clearHandshakeTimer();
    handshakeTimerRef.current = setTimeout(() => {
      failStartup("handshake-timeout");
    }, WORKSHOP_HANDSHAKE_TIMEOUT_MS);
  }, [
    clearHandshakeTimer,
    failStartup,
    runtimeDocument,
  ]);

  const hasBackend = module.hasBackend === true;
  const presenceRef = useRef(onBackendPresence);
  useEffect(() => {
    presenceRef.current = onBackendPresence;
  }, [onBackendPresence]);

  useEffect(() => {
    // Presence only extends the idle window; leaving stops the heartbeat
    // but never cancels submitted tasks.
    if (!hasBackend || phase !== "ready") {
      return;
    }
    const beat = () => {
      void Promise.resolve(presenceRef.current?.(runtimeModuleId)).catch(
        () => undefined,
      );
    };
    beat();
    const timer = setInterval(beat, BACKEND_PRESENCE_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [hasBackend, phase, runtimeModuleId]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const handshake = negotiateReady(
        event.data,
        runtimeModuleId,
        runtimeModuleVersion,
      );
      const supportedEvents = handshake?.events ?? null;
      // Runtimes post ready once and Chromium can deliver it before the
      // frame's load event, so trust the current frame window, not load order.
      const frameWindow = iframeRef.current?.contentWindow ?? null;
      if (
        frameWindow === null ||
        handshakeAcceptedRef.current ||
        failureHandledRef.current ||
        event.source !== frameWindow ||
        supportedEvents === null ||
        !isWorkshopApiCompatible({
          min: runtimeApiMin,
          maxExclusive: runtimeApiMaxExclusive,
        })
      ) {
        return;
      }
      handshakeAcceptedRef.current = true;
      clearHandshakeTimer();

      const selectedHandlers =
        runtimeMode === "browser-unsafe-development"
          ? syntheticHandlers
          : handlers;
      const upstreamProgress = selectedHandlers[
        "status.progress"
      ] as WorkshopRpcHandler | undefined;
      const upstreamError = selectedHandlers[
        "status.error"
      ] as WorkshopRpcHandler | undefined;
      const upstreamReady = selectedHandlers[
        "lifecycle.ready"
      ] as WorkshopRpcHandler | undefined;
      const projectChannel = snapshotProtocol === 1 && event.data?.projectSnapshotProtocol === 1 && (JSON.parse(runtimePermissionsJson) as string[]).includes("project.storage")
        ? new WorkshopProjectChannel({ moduleId: runtimeModuleId, moduleVersion: runtimeModuleVersion }, JSON.parse(snapshotSchemasJson) as string[], workshopProjectChanged)
        : undefined;
      const runtimeHandlers: WorkshopRpcHandlers = {
        ...selectedHandlers,
        "status.progress": async (payload, context) => {
          if (mountedRef.current) {
            setProgress(progressValue(payload));
          }
          return upstreamProgress?.(payload, context);
        },
        "status.error": async (payload, context) => {
          if (mountedRef.current) {
            setModuleError(errorValue(payload));
          }
          return upstreamError?.(payload, context);
        },
        "lifecycle.ready": async (payload, context) => {
          await upstreamReady?.(payload, context);
          try {
            if (sessionCandidateRef.current) {
              if (activateCandidate === undefined) {
                throw new Error(
                  "Candidate activation is unavailable.",
                );
              }
              await activateCandidate(
                runtimeModuleId,
                runtimeModuleVersion,
              );
            }
            await onStartSuccess?.(
              runtimeModuleId,
              runtimeModuleVersion,
            );
          } catch (error) {
            failStartup("activation-failed");
            throw error;
          }
          if (mountedRef.current) {
            setProgress(null);
            setPhase("ready");
            if (projectChannel && !detachProjectRef.current) {
              detachProjectRef.current = registerWorkshopProject(projectChannel);
            }
          }
          return undefined;
        },
      };

      let host: WorkshopRpcHost | null = null;
      let channel: WorkshopFrameChannel | null = null;
      try {
        host = createWorkshopRpcHost({
          identity: {
            moduleId: runtimeModuleId,
            moduleVersion: runtimeModuleVersion,
          },
          permissions: new Set(
            JSON.parse(
              runtimePermissionsJson,
            ) as WorkshopPermissionName[],
          ),
          handlers: runtimeHandlers,
          supportedEvents: supportedEvents ?? undefined,
          // Backend RPC needs both a declared backend and the module's
          // request in the handshake; the API re-checks consent per call.
          backendEnabled: hasBackend && handshake?.backendRequested === true,
          projectChannel,
        });
        channel = createChannel();
        detachPortRef.current = host.attach(channel.port1);
        hostRef.current = host;
        iframeRef.current?.contentWindow?.postMessage(
          {
            type: "lumina.workshop.connect",
            sessionId: createRandomId(),
          },
          "*",
          [channel.port2],
        );
        setPhase("connected");
      } catch {
        host?.close();
        channel?.port2.close();
        failStartup("runtime-load-failed");
      }
    };

    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
    };
  }, [
    activateCandidate,
    clearHandshakeTimer,
    createChannel,
    failStartup,
    handlers,
    hasBackend,
    onStartSuccess,
    runtimeApiMaxExclusive,
    runtimeApiMin,
    runtimeModuleId,
    runtimeModuleVersion,
    runtimePermissionsJson,
    snapshotSchemasJson,
    snapshotProtocol,
    runtimeMode,
    syntheticHandlers,
  ]);

  const statusLabel =
    phase === "ready"
      ? t("workshop_runtime_running")
      : phase === "connected"
        ? t("workshop_runtime_waiting_ready")
        : phase === "handshaking"
          ? t("workshop_runtime_handshaking")
          : phase === "loading"
            ? t("workshop_runtime_loading")
            : t("workshop_runtime_preparing");
  const terminalStatusClassName =
    "m-3 mt-16 rounded-lg border border-[color:var(--surface-outline)] bg-[color:var(--surface-section-muted)] p-4 text-sm text-slate-600 dark:text-slate-300";

  if (phase === "desktop-required") {
    return (
      <div role="status" className={terminalStatusClassName}>
        {t("workshop_runtime_desktop_required")}
      </div>
    );
  }
  if (phase === "disabled") {
    return (
      <div role="status" className={terminalStatusClassName}>
        {t("workshop_runtime_disabled")}
      </div>
    );
  }
  if (phase === "incompatible") {
    return (
      <div role="alert" className={terminalStatusClassName}>
        {t("workshop_runtime_incompatible")}
      </div>
    );
  }
  if (phase === "failed") {
    const failureLabel =
      failureReason === "handshake-timeout"
        ? t("workshop_runtime_handshake_timeout")
        : failureReason === "candidate-prepare-failed"
          ? t("workshop_runtime_snapshot_failed")
          : failureReason === "activation-failed"
            ? t("workshop_runtime_activation_failed")
            : t("workshop_runtime_load_failed");
    return (
      <div role="alert" className={terminalStatusClassName}>
        {failureLabel}
      </div>
    );
  }

  return (
    <div className="relative flex h-full min-h-0 flex-1 overflow-hidden">
      <div className="pointer-events-none absolute right-3 top-3 z-10 flex max-w-[20rem] flex-col items-end gap-2">
        {phase !== "ready" || progress ? (
          <div className="flex min-h-7 items-center gap-3 rounded-xl border border-[color:var(--surface-outline)] bg-[color:var(--surface-section-muted)] px-3 py-2 text-xs text-slate-500 shadow-[var(--shadow-control)] dark:text-slate-400">
            <span>{statusLabel}</span>
            {progress ? (
              <span
                role="status"
                className="flex min-w-0 items-center gap-2"
              >
                <span className="max-w-48 truncate">{progress.phase}</span>
                <span>
                  {progress.completed} / {progress.total}
                </span>
              </span>
            ) : null}
          </div>
        ) : null}
        {moduleError ? (
          <div
            role="alert"
            className="rounded-lg border border-[color:var(--surface-outline)] bg-[color:var(--surface-section-muted)] px-3 py-2 text-xs text-slate-600 shadow-[var(--shadow-control)] dark:text-slate-300"
          >
            {moduleError.message}
          </div>
        ) : null}
      </div>
      {runtimeDocument ? (
        <iframe
          ref={iframeRef}
          key={`${module.moduleId}@${module.moduleVersion}`}
          title={module.displayName}
          src={runtimeDocument.src}
          srcDoc={runtimeDocument.srcDoc}
          sandbox="allow-scripts"
          referrerPolicy="no-referrer"
          loading="eager"
          onLoad={handleFrameLoad}
          className="h-full min-h-0 w-full flex-1 rounded-none border-0 bg-[color:var(--surface-panel)]"
        />
      ) : null}
    </div>
  );
}
