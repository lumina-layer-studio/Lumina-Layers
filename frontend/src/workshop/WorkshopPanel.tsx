import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
} from "react";

import {
  workshopApi,
  workshopBackendApi,
  type InstalledWorkshopModule,
  type InstalledWorkshopVersion,
  type WorkshopBackendApi,
  type WorkshopBackendStatus,
  type WorkshopCatalog,
  type WorkshopCatalogModule,
  type WorkshopCatalogVersion,
  type WorkshopManagerApi,
  type WorkshopUninstallReport,
} from "../api/workshop";
import {
  BackendSetupError,
  authorizeAndPrepare,
  backendNeedsSetup,
} from "./backend/backendSetup";
import {
  BackendSetupDialog,
  type BackendSetupPhase,
} from "./backend/BackendSetupDialog";
import { backendActionErrorKey } from "./backend/backendErrors";
import { BackendStatusRow } from "./backend/BackendStatusRow";
import { StorageOverview } from "./backend/StorageOverview";
import { UninstallReportDialog } from "./backend/UninstallReportDialog";
import Button from "../components/ui/Button";
import { retainWorkshopProject } from "../project/workshopRuntime";
import CloseButton from "../components/ui/CloseButton";
import {
  PanelIntro,
  StatusBanner,
  cx,
  resolvePanelSurfaceClass,
  resolveSectionCardClass,
  workstationInputClass,
} from "../components/ui/panelPrimitives";
import { useWorkspaceMode } from "../hooks/useWorkspaceMode";
import { useI18n } from "../i18n/context";
import { useSettingsStore } from "../stores/settingsStore";
import ModuleDetails from "./ModuleDetails";
import {
  createWorkshopProjectStorage,
  type ManagedWorkshopProjectStorage,
  type WorkshopProjectStorageResult,
} from "./projectStorage";
import {
  WorkshopFrame,
  type WorkshopFrameProps,
} from "./runtime/WorkshopFrame";
import {
  canRunWorkshopInBrowser,
  compareWorkshopSemver,
  isBrowserTrustedWorkshopModule,
  WORKSHOP_RUNTIME_CLOSE_GRACE_MS,
  type WorkshopRuntimeMode,
} from "./runtime/health";
import {
  createSyntheticWorkshopHandlers,
  createWorkshopManagerHandlers,
  createWorkshopUiState,
} from "./runtime/handlers";
import {
  type WorkshopAuditStatus,
  useWorkshopStore,
} from "./store";

interface PermissionPrompt {
  kind: "staged" | "update";
  added: InstalledWorkshopVersion["permissions"];
  confirm(): void;
}

interface UninstallPrompt {
  module: InstalledWorkshopModule;
  deleteProjects: boolean;
  deleteTaskData: boolean;
  retainModels: boolean;
}

interface BackendSetupState {
  module: InstalledWorkshopModule;
  version: string;
  status: WorkshopBackendStatus;
  phase: BackendSetupPhase;
  progress: { completed: number; total: number; phase: string } | null;
  failureCode: string | null;
  taskId: string | null;
  /** Translation key of a cancel request that did not go through. */
  cancelErrorKey?: string | null;
  proceed(): void;
}

function moduleHasBackend(module: InstalledWorkshopModule): boolean {
  return module.version_details.some((detail) => Boolean(detail.backend));
}

function moduleDisplayName(
  module: InstalledWorkshopModule,
  version: string,
  language: "zh" | "en",
): string {
  const detail = module.version_details.find((item) => item.version === version);
  if (detail === undefined) {
    return module.module_id;
  }
  return language === "zh" ? detail.name.zh_cn : detail.name.en_us;
}

interface DesktopRuntimeInfo {
  mode: "desktop-secure";
  safeMode: boolean;
}

let defaultStorageResult: WorkshopProjectStorageResult | null = null;

function defaultProjectStorage(): ManagedWorkshopProjectStorage {
  defaultStorageResult ??= createWorkshopProjectStorage();
  return defaultStorageResult.storage;
}

function upsertModule(
  modules: InstalledWorkshopModule[],
  incoming: InstalledWorkshopModule,
): InstalledWorkshopModule[] {
  const next = modules.filter(
    (module) => module.module_id !== incoming.module_id,
  );
  next.push(incoming);
  return next.sort((left, right) =>
    left.module_id.localeCompare(right.module_id),
  );
}

function localized(
  value: { zh_cn: string; en_us: string },
  language: "zh" | "en",
): string {
  return language === "zh" ? value.zh_cn : value.en_us;
}

function moduleVersion(
  module: InstalledWorkshopModule,
  version: string | null,
): InstalledWorkshopVersion | null {
  if (version === null) {
    return null;
  }
  return (
    module.version_details.find(
      (detail) => detail.version === version,
    ) ?? null
  );
}

function newestInstallableVersion(
  module: WorkshopCatalogModule | undefined,
  activeVersion: string | null,
): WorkshopCatalogVersion | null {
  if (module === undefined) {
    return null;
  }
  const candidates = module.versions
    .filter((version) => version.state === "active")
    .filter((version) => {
      if (activeVersion === null) {
        return true;
      }
      return (
        compareWorkshopSemver(version.version, activeVersion) === 1
      );
    })
    .sort((left, right) =>
      compareWorkshopSemver(right.version, left.version) ?? 0,
    );
  return candidates[0] ?? null;
}

function sourceKey(
  module: InstalledWorkshopModule,
): "official" | "community" | "unreviewed" {
  if (
    isBrowserTrustedWorkshopModule(
      module.source,
      module.official,
    )
  ) {
    return "official";
  }
  return module.source === "registry"
    ? "community"
    : "unreviewed";
}

function moduleAuditStatus(
  module: InstalledWorkshopModule,
  catalog: WorkshopCatalog | null,
  version: string,
): WorkshopAuditStatus {
  const catalogVersion = catalog?.verified
    ? catalog.modules
        .find((item) => item.module_id === module.module_id)
        ?.versions.find((item) => item.version === version)
    : undefined;
  if (
    catalogVersion?.state === "blocked" ||
    (catalogVersion?.revocation !== null &&
      catalogVersion?.revocation !== undefined)
  ) {
    return "blocked";
  }
  if (catalogVersion?.state === "deprecated") {
    return "deprecated";
  }
  if (catalogVersion?.state === "active") {
    return "verified";
  }
  if (
    isBrowserTrustedWorkshopModule(
      module.source,
      module.official,
    )
  ) {
    return "official";
  }
  if (module.source === "github" || module.source === "local") {
    return "unreviewed";
  }
  return "unknown";
}

function frameRuntimeMode(
  value:
    | "desktop-secure"
    | "browser-restricted"
    | "unsafe-development",
): WorkshopRuntimeMode {
  if (value === "desktop-secure") {
    return "desktop-secure";
  }
  return value === "unsafe-development"
    ? "browser-unsafe-development"
    : "browser";
}

function canOpenModule(
  module: InstalledWorkshopModule,
  runtimeMode:
    | "desktop-secure"
    | "browser-restricted"
    | "unsafe-development",
  catalogModule?: WorkshopCatalogModule,
  version?: string | null,
): boolean {
  const catalogVersion = catalogModule?.versions.find(
    (candidate) => candidate.version === version,
  );
  if (
    module.source === "registry" &&
    (catalogVersion?.state === "blocked" ||
      catalogVersion?.revocation != null)
  ) {
    return false;
  }
  return canRunWorkshopInBrowser(
    module.source,
    module.official,
    frameRuntimeMode(runtimeMode),
  );
}

function permissionTranslationKey(name: string): string {
  return `workshop.manager.permission.${name}`;
}

function ModuleIcon({
  source,
  iconUrl,
}: {
  source: ReturnType<typeof sourceKey>;
  iconUrl: string | null;
}) {
  if (iconUrl) {
    return (
      <img
        src={iconUrl}
        alt=""
        className="h-14 w-14 rounded-[18px] border border-[color:var(--surface-outline)] object-cover"
      />
    );
  }
  return (
    <div
      aria-hidden="true"
      className={cx(
        "flex h-14 w-14 items-center justify-center rounded-[18px] text-xl font-semibold",
        source === "official"
          ? "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300"
          : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
      )}
    >
      ◫
    </div>
  );
}

interface InstalledCardProps {
  module: InstalledWorkshopModule;
  catalogModule: WorkshopCatalogModule | undefined;
  retained: boolean;
  runtimeMode:
    | "desktop-secure"
    | "browser-restricted"
    | "unsafe-development";
  busy: boolean;
  backendApi: WorkshopBackendApi;
  backendRefreshKey: number;
  onOpen(version: string): void;
  onOpenCandidate(): void;
  onDetails(url: string): void;
  onUpdate(version: WorkshopCatalogVersion): void;
  onRollback(): void;
  onToggle(): void;
  onUninstall(): void;
  onRestore(): void;
  onPrepareBackend(version: string, status: WorkshopBackendStatus): void;
}

function InstalledCard({
  module,
  catalogModule,
  retained,
  runtimeMode,
  busy,
  backendApi,
  backendRefreshKey,
  onOpen,
  onOpenCandidate,
  onDetails,
  onUpdate,
  onRollback,
  onToggle,
  onUninstall,
  onRestore,
  onPrepareBackend,
}: InstalledCardProps) {
  const { t, lang } = useI18n();
  const detail =
    moduleVersion(module, module.active_version) ??
    module.version_details.at(-1) ??
    null;
  const source = sourceKey(module);
  const update = newestInstallableVersion(
    catalogModule,
    module.active_version,
  );
  const activeOpenAllowed = canOpenModule(
    module,
    runtimeMode,
    catalogModule,
    module.active_version,
  );
  const candidateOpenAllowed = canOpenModule(
    module,
    runtimeMode,
    catalogModule,
    module.candidate_version,
  );
  const activeBlocked =
    module.source === "registry" &&
    !activeOpenAllowed &&
    canRunWorkshopInBrowser(
      module.source,
      module.official,
      frameRuntimeMode(runtimeMode),
    );
  const candidateBlocked =
    module.source === "registry" &&
    !candidateOpenAllowed &&
    canRunWorkshopInBrowser(
      module.source,
      module.official,
      frameRuntimeMode(runtimeMode),
    );
  const title = detail
    ? localized(detail.name, lang)
    : module.module_id;
  const backendVersion = detail?.backend ? detail.version : null;

  return (
    <article
      className={cx(
        resolveSectionCardClass("standard"),
        "flex min-h-72 flex-col gap-4",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <ModuleIcon source={source} iconUrl={detail?.icon_url ?? module.icon_url} />
        <span className="rounded-full border border-[color:var(--surface-outline)] bg-[color:var(--surface-section-muted)] px-2.5 py-1 text-[11px] font-semibold text-slate-700 dark:text-slate-200">
          {t(`workshop.manager.source.${source}`)}
        </span>
      </div>

      <div className="min-w-0 flex-1">
        <h3 className="text-xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
          {title}
        </h3>
        {detail ? (
          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
            {localized(detail.description, lang)}
          </p>
        ) : null}
        <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500 dark:text-slate-400">
          <span>
            {module.enabled
              ? t("workshop.manager.enabled")
              : t("workshop.manager.disabled")}
          </span>
          {module.active_version ? (
            <span>
              {t("workshop.manager.currentVersion").replace(
                "{version}",
                module.active_version,
              )}
            </span>
          ) : null}
          {module.candidate_version ? (
            <span>
              {t("workshop.manager.candidateVersion").replace(
                "{version}",
                module.candidate_version,
              )}
            </span>
          ) : null}
          {update ? (
            <span>
              {t("workshop.manager.updateAvailable").replace(
                "{version}",
                update.version,
              )}
            </span>
          ) : null}
        </div>
        {retained ? (
          <p className="mt-3 text-xs font-medium text-slate-600 dark:text-slate-300">
            {t("workshop.manager.projectsRetained")}
          </p>
        ) : null}
        {module.official_uninstalled ? (
          <StatusBanner tone="info" className="mt-3">
            {t("workshop.manager.officialUninstalled")}
          </StatusBanner>
        ) : null}
        {backendVersion !== null && !module.official_uninstalled ? (
          <BackendStatusRow
            moduleId={module.module_id}
            version={backendVersion}
            api={backendApi}
            refreshKey={backendRefreshKey}
            onPrepare={(status) => onPrepareBackend(backendVersion, status)}
          />
        ) : null}
      </div>

      {module.official_uninstalled ? (
        <Button
          label={t("workshop.manager.restoreSeed")}
          onClick={onRestore}
          loading={busy}
          className="w-full"
        />
      ) : (
        <div className="flex flex-wrap gap-2">
          {module.active_version ? (
            <Button
              label={
                activeBlocked
                  ? t("workshop.manager.blocked")
                  : activeOpenAllowed
                  ? t("workshop.manager.open")
                  : t("workshop.manager.desktopOnly")
              }
              onClick={() => onOpen(module.active_version as string)}
              disabled={!module.enabled || !activeOpenAllowed}
              className="flex-1"
            />
          ) : null}
          {module.candidate_version ? (
            <Button
              label={
                candidateBlocked
                  ? t("workshop.manager.blocked")
                  : candidateOpenAllowed
                  ? t("workshop.manager.reviewCandidate")
                  : t("workshop.manager.desktopOnly")
              }
              onClick={onOpenCandidate}
              disabled={!module.enabled || !candidateOpenAllowed}
              variant="secondary"
              className="flex-1"
            />
          ) : null}
          {detail ? (
            <Button
              label={t("workshop.manager.details")}
              variant="secondary"
              onClick={() => onDetails(detail.details_url)}
            />
          ) : null}
          {update ? (
            <Button
              label={t("workshop.manager.update")}
              variant="secondary"
              onClick={() => onUpdate(update)}
              loading={busy}
            />
          ) : null}
          {module.previous_version ? (
            <Button
              label={t("workshop.manager.rollback")}
              variant="secondary"
              onClick={onRollback}
              loading={busy}
            />
          ) : null}
          {module.active_version ? (
            <Button
              label={t(
                module.enabled
                  ? "workshop.manager.disable"
                  : "workshop.manager.enable",
              )}
              variant="secondary"
              onClick={onToggle}
              loading={busy}
            />
          ) : null}
          <Button
            label={t("workshop.manager.uninstall")}
            variant="secondary"
            onClick={onUninstall}
            disabled={busy}
            tone="danger"
          />
        </div>
      )}
    </article>
  );
}

export interface WorkshopPanelProps {
  api?: WorkshopManagerApi;
  backendApi?: WorkshopBackendApi;
  projectStorage?: ManagedWorkshopProjectStorage;
  runtimeMode?:
    | "desktop-secure"
    | "browser-restricted"
    | "unsafe-development";
  FrameComponent?: ComponentType<WorkshopFrameProps>;
}

export function WorkshopPanel({
  api = workshopApi,
  backendApi = workshopBackendApi,
  projectStorage = defaultProjectStorage(),
  runtimeMode: runtimeModeOverride,
  FrameComponent = WorkshopFrame,
}: WorkshopPanelProps) {
  const { t } = useI18n();
  const language = useSettingsStore((state) => state.language);
  const lang = language;
  const theme = useSettingsStore((state) => state.theme);
  const workspace = useWorkspaceMode();
  const view = useWorkshopStore((state) => state.view);
  const activeModule = useWorkshopStore(
    (state) => state.activeModule,
  );
  const catalogStatus = useWorkshopStore(
    (state) => state.catalogStatus,
  );
  const runtimeMode = useWorkshopStore(
    (state) => state.runtimeMode,
  );
  const pendingRecipeSource = useWorkshopStore(
    (state) => state.pendingRecipeSource,
  );
  const setView = useWorkshopStore((state) => state.setView);
  const openModule = useWorkshopStore((state) => state.openModule);
  const returnHome = useWorkshopStore((state) => state.returnHome);
  const setCatalogStatus = useWorkshopStore(
    (state) => state.setCatalogStatus,
  );
  const setRuntimeMode = useWorkshopStore(
    (state) => state.setRuntimeMode,
  );
  const setActiveRuntimeContext = useWorkshopStore(
    (state) => state.setActiveRuntimeContext,
  );
  const clearPendingRecipe = useWorkshopStore(
    (state) => state.clearPendingRecipe,
  );
  const setDiagnostics = useWorkshopStore(
    (state) => state.setDiagnostics,
  );

  const [modules, setModules] = useState<InstalledWorkshopModule[]>([]);
  const [catalog, setCatalog] = useState<WorkshopCatalog | null>(null);
  const [retainedProjects, setRetainedProjects] = useState<
    ReadonlySet<string>
  >(new Set());
  const [loadingModules, setLoadingModules] = useState(true);
  const [operationError, setOperationError] = useState<string | null>(
    null,
  );
  const [busyModuleId, setBusyModuleId] = useState<string | null>(
    null,
  );
  const [detailsUrl, setDetailsUrl] = useState<string | null>(null);
  const [permissionPrompt, setPermissionPrompt] =
    useState<PermissionPrompt | null>(null);
  const [uninstallPrompt, setUninstallPrompt] =
    useState<UninstallPrompt | null>(null);
  const [githubRepository, setGithubRepository] = useState("");
  const [githubVersion, setGithubVersion] = useState("");
  const [returningHome, setReturningHome] = useState(false);
  const [backendSetup, setBackendSetup] = useState<BackendSetupState | null>(null);
  const [backendRefreshKey, setBackendRefreshKey] = useState(0);
  const [uninstallReport, setUninstallReport] =
    useState<WorkshopUninstallReport | null>(null);
  const backendSetupCancelled = useRef(false);
  const returnHomeTimerRef = useRef<number | null>(null);
  const snapshotIds = useRef(new Map<string, string>());

  /**
   * Gate opening a backend version on consent and successful preparation.
   * Frontend-only versions open immediately as before.
   * 后端版本需先授权并准备成功才打开；纯前端版本行为不变。
   */
  const ensureBackendReady = useCallback(
    async (
      module: InstalledWorkshopModule,
      version: string,
      proceed: () => void,
    ) => {
      const detail = moduleVersion(module, version);
      if (!detail?.backend) {
        proceed();
        return;
      }
      try {
        const status = await backendApi.status(module.module_id, version);
        if (!backendNeedsSetup(status)) {
          proceed();
          return;
        }
        backendSetupCancelled.current = false;
        setBackendSetup({
          module,
          version,
          status,
          phase: "review",
          progress: null,
          failureCode: null,
          taskId: status.preparation_task_id,
          proceed,
        });
      } catch {
        setOperationError(t("workshop.manager.operationError"));
      }
    },
    [backendApi, t],
  );

  const confirmBackendSetup = useCallback(
    (acknowledgeUnreviewed: boolean) => {
      const setup = backendSetup;
      if (setup === null) {
        return;
      }
      setBackendSetup({ ...setup, phase: "preparing" });
      void authorizeAndPrepare(
        backendApi,
        setup.module.module_id,
        setup.version,
        acknowledgeUnreviewed,
        {
          onTask: (taskId) =>
            setBackendSetup((current) =>
              current === null ? current : { ...current, taskId },
            ),
          onProgress: (task) =>
            setBackendSetup((current) =>
              current === null ? current : { ...current, progress: task.progress },
            ),
        },
      )
        .then(() => {
          setBackendSetup(null);
          setBackendRefreshKey((value) => value + 1);
          setup.proceed();
        })
        .catch((error: unknown) => {
          setBackendRefreshKey((value) => value + 1);
          if (backendSetupCancelled.current) {
            setBackendSetup(null);
            return;
          }
          setBackendSetup((current) =>
            current === null
              ? current
              : {
                  ...current,
                  phase: "failed",
                  failureCode:
                    error instanceof BackendSetupError ? error.code : "request-failed",
                },
          );
        });
    },
    [backendApi, backendSetup],
  );

  const cancelBackendSetup = useCallback(() => {
    const setup = backendSetup;
    if (setup === null) {
      return;
    }
    if (setup.phase === "preparing" && setup.taskId !== null) {
      // Cancels the host preparation task; its rollback runs on the host.
      backendSetupCancelled.current = true;
      setBackendSetup((current) => (current === null ? current : { ...current, cancelErrorKey: null }));
      void backendApi.cancel(setup.module.module_id, setup.taskId).catch((error: unknown) => {
        // The preparation keeps running; say so beside the cancel action.
        backendSetupCancelled.current = false;
        setBackendSetup((current) =>
          current === null ? current : { ...current, cancelErrorKey: backendActionErrorKey(error) },
        );
      });
      return;
    }
    setBackendSetup(null);
  }, [backendApi, backendSetup]);

  const handleReturnHome = useCallback(() => {
    if (returnHomeTimerRef.current !== null) return;
    setReturningHome(true);
    returnHomeTimerRef.current = window.setTimeout(() => {
      returnHomeTimerRef.current = null;
      void retainWorkshopProject().then(returnHome).catch((error) => {
        setOperationError(error instanceof Error ? error.message : String(error));
      }).finally(() => setReturningHome(false));
    }, WORKSHOP_RUNTIME_CLOSE_GRACE_MS);
  }, [returnHome]);

  useEffect(
    () => () => {
      if (returnHomeTimerRef.current !== null) {
        window.clearTimeout(returnHomeTimerRef.current);
      }
    },
    [],
  );

  const applyMutation = useCallback(
    (module: InstalledWorkshopModule | null) => {
      if (module === null) {
        return;
      }
      setModules((current) => upsertModule(current, module));
    },
    [],
  );

  const loadModules = useCallback(async () => {
    setLoadingModules(true);
    try {
      const result = await api.listModules();
      if (!Array.isArray(result.modules)) {
        throw new Error("Invalid Workshop module-list response");
      }
      setModules(result.modules);
      setOperationError(null);
    } catch {
      setOperationError(t("workshop.manager.loadError"));
    } finally {
      setLoadingModules(false);
    }
  }, [api, t]);

  const loadCatalog = useCallback(async () => {
    setCatalogStatus("loading");
    try {
      const result = await api.fetchCatalog();
      setCatalog(result);
      setCatalogStatus(result.verified ? "ready" : "error");
    } catch {
      setCatalog(null);
      setCatalogStatus("error");
    }
  }, [api, setCatalogStatus]);

  useEffect(() => {
    void loadModules();
    void loadCatalog();
  }, [loadCatalog, loadModules]);

  useEffect(() => {
    if (runtimeModeOverride !== undefined) {
      setRuntimeMode(runtimeModeOverride);
      return;
    }
    const electronApi = (
      window as unknown as {
        electronAPI?: {
          getWorkshopRuntimeMode?: () => Promise<DesktopRuntimeInfo>;
        };
      }
    ).electronAPI;
    if (electronApi?.getWorkshopRuntimeMode === undefined) {
      setRuntimeMode("browser-restricted");
      return;
    }
    let cancelled = false;
    void electronApi
      .getWorkshopRuntimeMode()
      .then((result) => {
        if (!cancelled) {
          setRuntimeMode(
            result.mode === "desktop-secure" && !result.safeMode
              ? "desktop-secure"
              : "browser-restricted",
          );
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRuntimeMode("browser-restricted");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [runtimeModeOverride, setRuntimeMode]);

  useEffect(() => {
    let cancelled = false;
    void Promise.all(
      modules.map(async (module) => {
        try {
          const project = await projectStorage.latest(
            module.module_id,
          );
          return project === null ? null : module.module_id;
        } catch {
          return null;
        }
      }),
    ).then((ids) => {
      if (!cancelled) {
        setRetainedProjects(
          new Set(ids.filter((id): id is string => id !== null)),
        );
      }
    });
    return () => {
      cancelled = true;
    };
  }, [modules, projectStorage]);

  useEffect(() => {
    if (
      activeModule === null ||
      pendingRecipeSource === null ||
      activeModule.moduleId !== pendingRecipeSource.moduleId
    ) {
      return;
    }
    let cancelled = false;
    const timestamp = new Date().toISOString();
    void projectStorage
      .save({
        moduleId: activeModule.moduleId,
        projectId: `lumina-recipe-import-${Date.now()}`,
        schemaVersion: "lumina-recipe-import/v1",
        createdAt: timestamp,
        updatedAt: timestamp,
        project: {
          kind: "lumina-recipe-import",
          source: pendingRecipeSource,
        },
      })
      .then(() => {
        if (!cancelled) {
          clearPendingRecipe();
        }
      })
      .catch(() => {
        if (!cancelled) {
          setOperationError(
            t("workshop.manager.recipeImportSaveError"),
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [
    activeModule,
    clearPendingRecipe,
    pendingRecipeSource,
    projectStorage,
    t,
  ]);

  const catalogById = useMemo(
    () =>
      new Map(
        catalog?.verified
          ? catalog.modules.map((module) => [
              module.module_id,
              module,
            ])
          : [],
      ),
    [catalog],
  );

  const selectedModule = activeModule
    ? modules.find(
        (module) => module.module_id === activeModule.moduleId,
      ) ?? null
    : null;
  const selectedVersion =
    selectedModule && activeModule
      ? moduleVersion(selectedModule, activeModule.version)
      : null;

  useEffect(() => {
    if (
      activeModule === null ||
      selectedModule === null ||
      selectedVersion === null
    ) {
      setActiveRuntimeContext(null);
      return;
    }
    setActiveRuntimeContext({
      installSource: selectedModule.source,
      auditStatus: moduleAuditStatus(
        selectedModule,
        catalog,
        selectedVersion.version,
      ),
    });
  }, [
    activeModule,
    catalog,
    selectedModule,
    selectedVersion,
    setActiveRuntimeContext,
  ]);

  const handlers = useMemo(
    () =>
      createWorkshopManagerHandlers({
        storage: projectStorage,
        locale: () =>
          useSettingsStore.getState().language === "zh"
            ? "zh-CN"
            : "en-US",
        theme: () => useSettingsStore.getState().theme,
        onDiagnostics: setDiagnostics,
        backend: backendApi,
      }),
    [backendApi, projectStorage, setDiagnostics],
  );
  const syntheticHandlers = useMemo(
    () => createSyntheticWorkshopHandlers(),
    [],
  );
  const uiState = useMemo(
    () =>
      createWorkshopUiState(
        language === "zh" ? "zh-CN" : "en-US",
        theme,
      ),
    [language, theme],
  );

  const runModuleMutation = useCallback(
    async (
      moduleId: string,
      operation: () => Promise<{
        module: InstalledWorkshopModule | null;
      }>,
    ) => {
      setBusyModuleId(moduleId);
      setOperationError(null);
      try {
        const result = await operation();
        if (result.module === null) {
          setModules((current) =>
            current.filter(
              (module) => module.module_id !== moduleId,
            ),
          );
        } else {
          applyMutation(result.module);
        }
        return result.module;
      } catch {
        setOperationError(t("workshop.manager.operationError"));
        return null;
      } finally {
        setBusyModuleId(null);
      }
    },
    [applyMutation, t],
  );

  const installUpdate = useCallback(
    async (
      module: InstalledWorkshopModule,
      version: WorkshopCatalogVersion,
    ) => {
      const installed = await runModuleMutation(
        module.module_id,
        () =>
          api.installRegistry(module.module_id, version.version),
      );
      if (
        installed?.candidate_version &&
        canOpenModule(
          installed,
          runtimeMode,
          catalogById.get(installed.module_id),
          installed.candidate_version,
        )
      ) {
        const candidateVersion = installed.candidate_version;
        void ensureBackendReady(installed, candidateVersion, () =>
          openModule(installed.module_id, candidateVersion),
        );
      }
    },
    [
      api,
      catalogById,
      ensureBackendReady,
      openModule,
      runModuleMutation,
      runtimeMode,
    ],
  );

  const requestStagedCandidate = useCallback(
    (module: InstalledWorkshopModule) => {
      const candidateVersion = module.candidate_version;
      if (
        candidateVersion === null ||
        !canOpenModule(
          module,
          runtimeMode,
          catalogById.get(module.module_id),
          candidateVersion,
        )
      ) {
        return;
      }
      const candidate = moduleVersion(module, candidateVersion);
      if (candidate === null) {
        setOperationError(t("workshop.manager.operationError"));
        return;
      }
      const currentPermissions = new Set(
        moduleVersion(
          module,
          module.active_version,
        )?.permissions.map((permission) => permission.name) ?? [],
      );
      const added = candidate.permissions.filter(
        (permission) => !currentPermissions.has(permission.name),
      );
      const confirm = () =>
        void ensureBackendReady(module, candidateVersion, () =>
          openModule(module.module_id, candidateVersion),
        );
      if (added.length > 0) {
        setPermissionPrompt({
          kind: "staged",
          added,
          confirm,
        });
        return;
      }
      confirm();
    },
    [catalogById, ensureBackendReady, openModule, runtimeMode, t],
  );

  const requestUpdate = useCallback(
    (
      module: InstalledWorkshopModule,
      version: WorkshopCatalogVersion,
    ) => {
      const currentPermissions = new Set(
        moduleVersion(module, module.active_version)?.permissions.map(
          (permission) => permission.name,
        ) ?? [],
      );
      const added = version.permissions.filter(
        (permission) => !currentPermissions.has(permission.name),
      );
      if (added.length > 0) {
        setPermissionPrompt({
          kind: "update",
          added,
          confirm: () => {
            void installUpdate(module, version);
          },
        });
        return;
      }
      void installUpdate(module, version);
    },
    [installUpdate],
  );

  const openView = useCallback(
    (
      next: "installed" | "discover" | "developer" | "storage",
    ) => {
      setView(next);
      if (next === "discover") {
        void loadCatalog();
      }
    },
    [loadCatalog, setView],
  );

  const prepareCandidate = useCallback(
    async (moduleId: string, moduleVersionValue: string) => {
      const module = modules.find(
        (item) => item.module_id === moduleId,
      );
      const snapshotId = await projectStorage.snapshotModule(
        moduleId,
        module?.active_version ?? moduleVersionValue,
      );
      snapshotIds.current.set(moduleId, snapshotId);
    },
    [modules, projectStorage],
  );

  const activateCandidate = useCallback(
    async (moduleId: string, version: string) => {
      const result = await api.activateModule(moduleId, version);
      if (result.module) {
        applyMutation(result.module);
      }
      const snapshotId = snapshotIds.current.get(moduleId);
      if (snapshotId) {
        await projectStorage.deleteSnapshot(moduleId, snapshotId);
        snapshotIds.current.delete(moduleId);
      }
    },
    [api, applyMutation, projectStorage],
  );

  const handleRuntimeFailure = useCallback(
    async (failure: { moduleId: string }) => {
      const snapshotId = snapshotIds.current.get(failure.moduleId);
      if (snapshotId) {
        await projectStorage.restoreSnapshot(
          failure.moduleId,
          snapshotId,
        );
        await projectStorage.deleteSnapshot(
          failure.moduleId,
          snapshotId,
        );
        snapshotIds.current.delete(failure.moduleId);
      }
      const result = await api.recordRuntimeFailure(
        failure.moduleId,
      );
      if (result.module) {
        applyMutation(result.module);
      }
    },
    [api, applyMutation, projectStorage],
  );

  const handleRuntimeSuccess = useCallback(
    async (moduleId: string) => {
      const result = await api.recordRuntimeSuccess(moduleId);
      if (result.module) {
        applyMutation(result.module);
      }
    },
    [api, applyMutation],
  );

  const confirmUninstall = useCallback(async () => {
    if (uninstallPrompt === null) {
      return;
    }
    const { module, deleteProjects, deleteTaskData, retainModels } =
      uninstallPrompt;
    setUninstallPrompt(null);
    const result = await runModuleMutation(module.module_id, async () => {
      if (!moduleHasBackend(module)) {
        return api.uninstallModule(module.module_id, deleteProjects);
      }
      const response = await api.uninstallModule(
        module.module_id,
        deleteProjects,
        { deleteTaskData, retainModels },
      );
      if (response.uninstall_report) {
        setUninstallReport(response.uninstall_report);
      }
      return response;
    });
    if (deleteProjects) {
      await projectStorage.deleteModuleProjects(module.module_id);
      setRetainedProjects((current) => {
        const next = new Set(current);
        next.delete(module.module_id);
        return next;
      });
    }
    if (result?.official_uninstalled) {
      applyMutation(result);
    }
  }, [
    api,
    applyMutation,
    projectStorage,
    runModuleMutation,
    uninstallPrompt,
  ]);

  const installLocal = useCallback(
    async (file: File | undefined) => {
      if (
        file === undefined ||
        !file.name.toLowerCase().endsWith(".lumina-workshop")
      ) {
        setOperationError(t("workshop.manager.localInvalid"));
        return;
      }
      const result = await runModuleMutation("local-install", () =>
        api.installLocal(file),
      );
      if (result !== null) {
        requestStagedCandidate(result);
      }
    },
    [api, requestStagedCandidate, runModuleMutation, t],
  );

  const installGithub = useCallback(async () => {
    if (
      !/^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(
        githubRepository,
      ) ||
      !/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.test(
        githubVersion,
      )
    ) {
      setOperationError(t("workshop.manager.githubInvalid"));
      return;
    }
    const result = await runModuleMutation("github-install", () =>
      api.installGithub(githubRepository, githubVersion),
    );
    if (result !== null) {
      requestStagedCandidate(result);
    }
  }, [
    api,
    githubRepository,
    githubVersion,
    requestStagedCandidate,
    runModuleMutation,
    t,
  ]);

  const installRegistry = useCallback(
    async (moduleId: string, version: string) => {
      const result = await runModuleMutation(moduleId, () =>
        api.installRegistry(moduleId, version),
      );
      if (result !== null) {
        requestStagedCandidate(result);
      }
    },
    [api, requestStagedCandidate, runModuleMutation],
  );

  const restoreOfficialSeed = useCallback(
    async (moduleId: string) => {
      const result = await runModuleMutation(moduleId, () =>
        api.restoreOfficialSeed(moduleId),
      );
      if (result !== null) {
        requestStagedCandidate(result);
      }
    },
    [api, requestStagedCandidate, runModuleMutation],
  );

  if (selectedModule && selectedVersion && activeModule) {
    return (
      <div
        data-testid="workshop-runtime-shell"
        className="flex h-full min-h-0 w-full overflow-hidden"
      >
        <nav
          aria-label={t("workshop.title")}
          className="relative z-20 flex w-9 shrink-0 items-start justify-center border-r border-[color:var(--surface-outline)] bg-[color:var(--surface-section-muted)] pt-1"
        >
          <button
            type="button"
            onClick={handleReturnHome}
            disabled={returningHome}
            className="inline-grid size-8 shrink-0 place-items-center rounded-lg text-slate-600 transition-colors hover:bg-[color:var(--surface-panel)] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--focus-ring)] dark:text-slate-300"
            aria-label={t("workshop.back")}
            title={t("workshop.back")}
          >
            <span aria-hidden="true">←</span>
          </button>
        </nav>
        <div
          data-testid="workshop-module-viewport"
          className="h-full min-h-0 min-w-0 flex-1 overflow-hidden"
        >
          <FrameComponent
            module={{
              moduleId: activeModule.moduleId,
              moduleVersion: activeModule.version,
              displayName: localized(selectedVersion.name, lang),
              source: selectedModule.source,
              official: selectedModule.official,
              enabled: selectedModule.enabled,
              runtimeUrl: selectedVersion.runtime_url,
              workshopApi: {
                min: selectedVersion.workshop_api_min,
                maxExclusive:
                  selectedVersion.workshop_api_max_exclusive,
              },
              permissions: selectedVersion.permissions.map(
                (permission) => permission.name,
              ),
              candidate:
                selectedModule.candidate_version ===
                activeModule.version,
              previousVersion: selectedModule.previous_version,
              consecutiveStartFailures:
                selectedModule.consecutive_start_failures,
              hasBackend: Boolean(selectedVersion.backend),
              projectSnapshotProtocol: selectedVersion.project_snapshot_protocol,
              projectSnapshotSchemas: selectedVersion.project_snapshot_schemas,
            }}
            onBackendPresence={(moduleId) => backendApi.presence(moduleId)}
            runtimeMode={frameRuntimeMode(runtimeMode)}
            handlers={handlers}
            uiState={uiState}
            syntheticHandlers={syntheticHandlers}
            prepareCandidate={prepareCandidate}
            activateCandidate={activateCandidate}
            onStartSuccess={handleRuntimeSuccess}
            onStartFailure={handleRuntimeFailure}
            disableVersion={(moduleId) =>
              api
                .setModuleEnabled(moduleId, false)
                .then((result) => {
                  if (result.module) {
                    applyMutation(result.module);
                  }
                })
            }
          />
        </div>
      </div>
    );
  }

  return (
    <div
      className={cx(
        resolvePanelSurfaceClass(workspace.mode),
        "flex flex-col gap-5",
      )}
    >
      <div className="mx-auto flex w-full max-w-[96rem] flex-col gap-5">
        <PanelIntro
          eyebrow={t("workshop.manager.eyebrow")}
          title={t("workshop.title")}
          description={t("workshop.manager.description")}
        />

        <nav
          aria-label={t("workshop.manager.navigation")}
          className="inline-flex w-fit rounded-2xl border border-[color:var(--surface-outline)] bg-[color:var(--surface-section-muted)] p-1"
        >
          {(["installed", "discover", "developer", "storage"] as const).map(
            (item) => (
              <button
                key={item}
                type="button"
                aria-current={view === item ? "page" : undefined}
                onClick={() => openView(item)}
                className={cx(
                  "min-h-9 rounded-xl px-4 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--focus-ring)]",
                  view === item
                    ? "bg-white text-slate-900 shadow-[var(--shadow-control)] dark:bg-slate-800 dark:text-slate-50"
                    : "text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-slate-50",
                )}
              >
                {t(`workshop.manager.view.${item}`)}
              </button>
            ),
          )}
        </nav>

        <StatusBanner
          tone={
            runtimeMode === "desktop-secure"
              ? "success"
              : runtimeMode === "unsafe-development"
                ? "warning"
                : "info"
          }
        >
          {t(`workshop.manager.runtime.${runtimeMode}`)}
        </StatusBanner>

        {operationError ? (
          <StatusBanner tone="error">{operationError}</StatusBanner>
        ) : null}

        {!loadingModules &&
        activeModule !== null &&
        (selectedModule === null || selectedVersion === null) ? (
          <StatusBanner tone="warning">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span>
                {t("workshop.manager.recipeModuleMissing")
                  .replace("{id}", activeModule.moduleId)
                  .replace("{version}", activeModule.version)}
              </span>
              <Button
                label={t(
                  "workshop.manager.recipeModuleDiscover",
                )}
                variant="secondary"
                onClick={() => openView("discover")}
              />
            </div>
          </StatusBanner>
        ) : null}

        {view === "installed" ? (
          loadingModules ? (
            <p role="status" className="text-sm text-slate-500 dark:text-slate-400">
              {t("workshop.manager.loading")}
            </p>
          ) : modules.length === 0 ? (
            <StatusBanner tone="info">
              {t("workshop.manager.noInstalled")}
            </StatusBanner>
          ) : (
            <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              {modules.map((module) => (
                <InstalledCard
                  key={module.module_id}
                  module={module}
                  catalogModule={catalogById.get(module.module_id)}
                  retained={retainedProjects.has(module.module_id)}
                  runtimeMode={runtimeMode}
                  busy={busyModuleId === module.module_id}
                  onOpen={(version) =>
                    void ensureBackendReady(module, version, () =>
                      openModule(module.module_id, version),
                    )
                  }
                  onOpenCandidate={() =>
                    requestStagedCandidate(module)
                  }
                  onDetails={setDetailsUrl}
                  onUpdate={(version) =>
                    requestUpdate(module, version)
                  }
                  onRollback={() =>
                    void runModuleMutation(module.module_id, () =>
                      api.rollbackModule(module.module_id),
                    )
                  }
                  onToggle={() =>
                    void runModuleMutation(module.module_id, () =>
                      api.setModuleEnabled(
                        module.module_id,
                        !module.enabled,
                      ),
                    )
                  }
                  onUninstall={() =>
                    setUninstallPrompt({
                      module,
                      deleteProjects: false,
                      deleteTaskData: false,
                      retainModels: false,
                    })
                  }
                  onRestore={() =>
                    void restoreOfficialSeed(module.module_id)
                  }
                  backendApi={backendApi}
                  backendRefreshKey={backendRefreshKey}
                  onPrepareBackend={(version, status) => {
                    backendSetupCancelled.current = false;
                    setBackendSetup({
                      module,
                      version,
                      status,
                      phase: "review",
                      progress: null,
                      failureCode: null,
                      taskId: status.preparation_task_id,
                      proceed: () => undefined,
                    });
                  }}
                />
              ))}
            </div>
          )
        ) : null}

        {view === "discover" ? (
          catalogStatus === "loading" ? (
            <p role="status" className="text-sm text-slate-500 dark:text-slate-400">
              {t("workshop.manager.catalogLoading")}
            </p>
          ) : catalogStatus === "error" || !catalog?.verified ? (
            <StatusBanner
              tone="error"
              action={
                <Button
                  label={t("workshop.manager.retry")}
                  variant="secondary"
                  size="sm"
                  onClick={() => void loadCatalog()}
                />
              }
            >
              {t("workshop.manager.catalogInvalid")}
            </StatusBanner>
          ) : (
            <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
              {catalog.modules.map((module) => {
                const candidate = newestInstallableVersion(
                  module,
                  modules.find(
                    (installedModule) =>
                      installedModule.module_id === module.module_id,
                  )?.active_version ?? null,
                );
                return (
                  <article
                    key={module.module_id}
                    className={cx(
                      resolveSectionCardClass("standard"),
                      "flex min-h-64 flex-col gap-4",
                    )}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <ModuleIcon
                        source={
                          module.official ? "official" : "community"
                        }
                        iconUrl={null}
                      />
                      <span className="rounded-full border border-[color:var(--surface-outline)] px-2.5 py-1 text-[11px] font-semibold text-slate-600 dark:text-slate-300">
                        {t(
                          `workshop.manager.source.${
                            module.official
                              ? "official"
                              : "community"
                          }`,
                        )}
                      </span>
                    </div>
                    <div className="flex-1">
                      <h3 className="text-xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
                        {localized(module.name, lang)}
                      </h3>
                      <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                        {localized(module.description, lang)}
                      </p>
                      <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
                        {module.publisher}
                      </p>
                    </div>
                    {candidate ? (
                      <Button
                        label={t("workshop.manager.install")}
                        onClick={() => {
                          const installedModule = modules.find(
                            (item) =>
                              item.module_id === module.module_id,
                          );
                          if (installedModule) {
                            requestUpdate(
                              installedModule,
                              candidate,
                            );
                          } else {
                            void installRegistry(
                              module.module_id,
                              candidate.version,
                            );
                          }
                        }}
                      />
                    ) : (
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        {t("workshop.manager.installedCurrent")}
                      </p>
                    )}
                  </article>
                );
              })}
            </div>
          )
        ) : null}

        {view === "storage" ? <StorageOverview api={backendApi} /> : null}

        {view === "developer" ? (
          <div className="grid gap-5 lg:grid-cols-2">
            <section className={resolveSectionCardClass("standard")}>
              <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
                {t("workshop.manager.localTitle")}
              </h3>
              <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
                {t("workshop.manager.localDescription")}
              </p>
              <label className="mt-5 block text-sm font-medium text-slate-700 dark:text-slate-200">
                <span>{t("workshop.manager.localPackage")}</span>
                <input
                  type="file"
                  accept=".lumina-workshop"
                  className="mt-2 block w-full text-sm text-slate-600 file:mr-3 file:rounded-xl file:border-0 file:bg-blue-600 file:px-3 file:py-2 file:text-white dark:text-slate-300"
                  onChange={(event) =>
                    void installLocal(event.target.files?.[0])
                  }
                />
              </label>
            </section>

            <section className={resolveSectionCardClass("standard")}>
              <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-50">
                {t("workshop.manager.githubTitle")}
              </h3>
              <div className="mt-5 flex flex-col gap-4">
                <label className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  <span>{t("workshop.manager.githubRepository")}</span>
                  <input
                    type="url"
                    value={githubRepository}
                    onChange={(event) =>
                      setGithubRepository(event.target.value)
                    }
                    className={cx(workstationInputClass, "mt-2")}
                    placeholder={t(
                      "workshop.manager.githubPlaceholder",
                    )}
                  />
                </label>
                <label className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  <span>{t("workshop.manager.exactVersion")}</span>
                  <input
                    type="text"
                    value={githubVersion}
                    onChange={(event) =>
                      setGithubVersion(event.target.value)
                    }
                    className={cx(workstationInputClass, "mt-2")}
                    placeholder="1.0.0"
                  />
                </label>
                <Button
                  label={t("workshop.manager.installGithub")}
                  onClick={() => void installGithub()}
                  loading={busyModuleId === "github-install"}
                  variant="primary"
                />
              </div>
            </section>
          </div>
        ) : null}
      </div>

      {detailsUrl ? (
        <ModuleDetails
          detailsUrl={detailsUrl}
          api={api}
          onClose={() => setDetailsUrl(null)}
        />
      ) : null}

      {backendSetup ? (
        <BackendSetupDialog
          moduleName={moduleDisplayName(
            backendSetup.module,
            backendSetup.version,
            lang,
          )}
          status={backendSetup.status}
          phase={backendSetup.phase}
          progress={backendSetup.progress}
          failureCode={backendSetup.failureCode}
          cancelError={
            backendSetup.cancelErrorKey
              ? t("workshop.backend.cancelFailed").replace("{reason}", t(backendSetup.cancelErrorKey))
              : null
          }
          onConfirm={confirmBackendSetup}
          onCancel={cancelBackendSetup}
        />
      ) : null}

      {uninstallReport ? (
        <UninstallReportDialog
          report={uninstallReport}
          onClose={() => setUninstallReport(null)}
        />
      ) : null}

      {permissionPrompt ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={t(
            permissionPrompt.kind === "staged"
              ? "workshop.manager.permissionInstallTitle"
              : "workshop.manager.permissionTitle",
          )}
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4 backdrop-blur-sm"
        >
          <section className="panel-section w-full max-w-lg rounded-[28px] p-5 shadow-2xl" style={{ background: "var(--surface-panel-strong)" }}>
            <div className="flex items-start justify-between gap-3">
              <h2 className="text-xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
                {t(
                  permissionPrompt.kind === "staged"
                    ? "workshop.manager.permissionInstallTitle"
                    : "workshop.manager.permissionTitle",
                )}
              </h2>
              <CloseButton label={t("common_close")} onClick={() => setPermissionPrompt(null)} />
            </div>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {t(
                permissionPrompt.kind === "staged"
                  ? "workshop.manager.permissionInstallDescription"
                  : "workshop.manager.permissionDescription",
              )}
            </p>
            <h3 className="mt-5 text-sm font-semibold text-slate-900 dark:text-slate-50">
              {t(
                permissionPrompt.kind === "staged"
                  ? "workshop.manager.requestedPermissions"
                  : "workshop.manager.newPermissions",
              )}
            </h3>
            <ul className="mt-2 flex flex-col gap-2">
              {permissionPrompt.added.map((permission) => (
                <li
                  key={permission.name}
                  className="rounded-2xl border border-[color:var(--surface-outline)] p-3"
                >
                  <p className="text-sm font-semibold text-slate-900 dark:text-slate-50">
                    {t(permissionTranslationKey(permission.name))}
                  </p>
                  <p className="mt-1 text-xs leading-5 text-slate-600 dark:text-slate-300">
                    {permission.reason}
                  </p>
                </li>
              ))}
            </ul>
            <div className="mt-5 flex justify-end gap-2">
              <Button
                label={t("workshop.manager.cancel")}
                variant="secondary"
                onClick={() => setPermissionPrompt(null)}
              />
              <Button
                label={t(
                  permissionPrompt.kind === "staged"
                    ? "workshop.manager.confirmPermissionsAndOpen"
                    : "workshop.manager.confirmPermissions",
                )}
                onClick={() => {
                  const prompt = permissionPrompt;
                  setPermissionPrompt(null);
                  prompt.confirm();
                }}
                variant="primary"
              />
            </div>
          </section>
        </div>
      ) : null}

      {uninstallPrompt ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={t("workshop.manager.uninstallTitle")}
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4 backdrop-blur-sm"
        >
          <section className="panel-section w-full max-w-lg rounded-[28px] p-5 shadow-2xl" style={{ background: "var(--surface-panel-strong)" }}>
            <div className="flex items-start justify-between gap-3">
              <h2 className="text-xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
                {t("workshop.manager.uninstallTitle")}
              </h2>
              <CloseButton label={t("common_close")} onClick={() => setUninstallPrompt(null)} />
            </div>
            <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
              {t("workshop.manager.uninstallDescription")}
            </p>
            <label className="mt-5 flex items-start gap-3 rounded-2xl border border-[color:var(--surface-outline)] p-3 text-sm text-slate-700 dark:text-slate-200">
              <input
                type="checkbox"
                checked={uninstallPrompt.deleteProjects}
                onChange={(event) =>
                  setUninstallPrompt({
                    ...uninstallPrompt,
                    deleteProjects: event.target.checked,
                  })
                }
                className="mt-0.5 h-4 w-4"
              />
              <span>{t("workshop.manager.deleteProjects")}</span>
            </label>
            {moduleHasBackend(uninstallPrompt.module) ? (
              <>
                <label className="mt-3 flex items-start gap-3 rounded-2xl border border-[color:var(--surface-outline)] p-3 text-sm text-slate-700 dark:text-slate-200">
                  <input
                    type="checkbox"
                    checked={uninstallPrompt.deleteTaskData}
                    onChange={(event) =>
                      setUninstallPrompt({
                        ...uninstallPrompt,
                        deleteTaskData: event.target.checked,
                      })
                    }
                    className="mt-0.5 h-4 w-4"
                  />
                  <span>{t("workshop.manager.deleteTaskData")}</span>
                </label>
                <label className="mt-3 flex items-start gap-3 rounded-2xl border border-[color:var(--surface-outline)] p-3 text-sm text-slate-700 dark:text-slate-200">
                  <input
                    type="checkbox"
                    checked={uninstallPrompt.retainModels}
                    onChange={(event) =>
                      setUninstallPrompt({
                        ...uninstallPrompt,
                        retainModels: event.target.checked,
                      })
                    }
                    className="mt-0.5 h-4 w-4"
                  />
                  <span>{t("workshop.manager.retainModels")}</span>
                </label>
                <p className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
                  {t("workshop.manager.uninstallBackendNote")}
                </p>
              </>
            ) : null}
            <div className="mt-5 flex justify-end gap-2">
              <Button
                label={t("workshop.manager.cancel")}
                variant="secondary"
                onClick={() => setUninstallPrompt(null)}
              />
              <Button
                label={t("workshop.manager.confirmUninstall")}
                onClick={() => void confirmUninstall()}
                tone="danger"
              />
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}

export default WorkshopPanel;
