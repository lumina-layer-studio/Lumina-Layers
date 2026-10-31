const {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  Menu,
  net: electronNet,
  protocol,
  screen,
  session,
  shell,
  webFrameMain,
} = require("electron");
const { spawn, execSync } = require("child_process");
const http = require("http");
const nodeNet = require("net");
const fs = require("fs");
const path = require("path");
const { createLauncherStartup } = require('./launcher-startup.cjs');
const { createSplashController } = require('./splash-controller.cjs');
const launcherStartup = createLauncherStartup();
if (launcherStartup.enabled) {
  launcherStartup.checkpoint(0);
  app.on('will-quit', () => launcherStartup.failed());
}
const { saveGeneratedFile } = require("./generated-file-save.cjs");
const { createApplicationMenu } = require("./application-menu.cjs");
const {
  createGeneratedFileDirectoryState,
  pickGeneratedFileDirectory,
  resolveDefaultSavePath,
  setGeneratedFileDirectory,
  isTrustedMainFrameSender,
} = require("./generated-file-directory.cjs");
const { assertPortsAvailable, selectBackendEndpoint, commitBackendEndpoint, validateHealthResponse } = require("./backend-endpoint.cjs");
const {
  createInterfaceScaleController,
  getInterfaceScale,
  setInterfaceScale,
} = require("./interface-scale.cjs");
const {
  fetchNativeBedModel,
  isAllowedBedModelIpcSender,
} = require("./bed-model-bridge.cjs");
const {
  createWorkshopSessionToken,
  enableManagedDesktopHost,
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
} = require("./workshop-security.cjs");
const {
  loadWorkshopImageFile,
} = require("./workshop-file-picker.cjs");

// ═══════════════════════════════════════════════════════════
//  Constants
// ═══════════════════════════════════════════════════════════

let backendEndpoint;
const FRONTEND_PORT = 4174;
const FRONTEND_URL = `http://127.0.0.1:${FRONTEND_PORT}`;
// Cold native dependency loading can exceed 30 seconds on a clean Windows guest.
// Health and process ownership remain mandatory throughout this bounded wait.
const HEALTH_TIMEOUT_MS = 180000;
const PORT_TIMEOUT_MS = 30000;
const POLL_INTERVAL_MS = 500;
const WORKSHOP_SCHEME = "lumina-workshop";
const WORKSHOP_RUNTIME_HEADER_NAMES = [
  "cache-control",
  "content-security-policy",
  "content-type",
  "permissions-policy",
  "referrer-policy",
  "x-content-type-options",
];

const ROOT_DIR = path.join(__dirname, "..");
const IS_WIN = process.platform === "win32";
const IS_MAC = process.platform === "darwin";
const workshopSessionToken = createWorkshopSessionToken();
let workshopSafeMode = false;

protocol.registerSchemesAsPrivileged([
  {
    scheme: WORKSHOP_SCHEME,
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: false,
      corsEnabled: false,
      allowServiceWorkers: false,
      codeCache: false,
    },
  },
]);

// Window and Dock icons.
const ICON_PATH = (() => {
  if (IS_WIN) return path.join(ROOT_DIR, "icon.ico");
  return path.join(__dirname, "assets", "icon.png");
})();

// ═══════════════════════════════════════════════════════════
//  Quit dialog i18n
// ═══════════════════════════════════════════════════════════

const QUIT_DIALOG = {
  zh: {
    title: "\u9000\u51FA\u786E\u8BA4",
    message: "\u786E\u5B9A\u8981\u9000\u51FA Lumina Studio \u5417\uFF1F",
    detail: "\u9000\u51FA\u540E\u6240\u6709\u672A\u4FDD\u5B58\u7684\u64CD\u4F5C\u5C06\u4E22\u5931\u3002",
    quit: "\u9000\u51FA",
    cancel: "\u53D6\u6D88",
  },
  en: {
    title: "Quit Confirmation",
    message: "Are you sure you want to quit Lumina Studio?",
    detail: "All unsaved changes will be lost.",
    quit: "Quit",
    cancel: "Cancel",
  },
};

let currentLang = "zh";

// ═══════════════════════════════════════════════════════════
//  Logging
// ═══════════════════════════════════════════════════════════

let logStream = null;

function initLog() {
  const logDir = app.getPath("logs");
  try {
    fs.mkdirSync(logDir, { recursive: true });
  } catch (_) {}
  const logFile = path.join(logDir, "lumina-electron.log");
  logStream = fs.createWriteStream(logFile, { flags: "a" });
}

function log(tag, msg) {
  const ts = new Date().toISOString().slice(11, 19);
  const line = `${ts} [${tag}] ${msg}`;
  if (logStream) {
    logStream.write(line + "\n");
  }
  console.log(line);
}

function logSys(m) { log("SYS", m); }
function logOk(m) { log(" OK", m); }
function logErr(m) { log("ERR", m); }
function logBe(m) { log("  B", m); }
function logFe(m) { log("  F", m); }

// ═══════════════════════════════════════════════════════════
//  Child process management
// ═══════════════════════════════════════════════════════════

const children = [];

function spawnChild(name, cmd, args, cwd, envExtra = {}) {
  return new Promise((resolve, reject) => {
    const logFn = name.includes("Backend") ? logBe : logFe;
    try {
      const proc = spawn(cmd, args, {
        cwd,
        env: { ...process.env, ...envExtra },
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
        // mac/linux: detach 让子进程拥有独立进程组，退出时一并 kill 整个组，
        // 避免 vite/uvicorn 的 fork worker 残留占住端口。
        detached: !IS_WIN,
      });

      proc.stdout.on("data", (data) => {
        const lines = data.toString("utf-8").split("\n").filter(Boolean);
        for (const line of lines) {
          logFn(line);
        }
      });

      proc.stderr.on("data", (data) => {
        const lines = data.toString("utf-8").split("\n").filter(Boolean);
        for (const line of lines) {
          logFn(line);
        }
      });

      proc.on("error", (err) => {
        logErr(`${name} spawn error: ${err.message}`);
        reject(err);
      });

      proc.on("exit", (code) => {
        logFn(`${name} exited with code ${code}`);
        const idx = children.indexOf(proc);
        if (idx !== -1) children.splice(idx, 1);
      });

      children.push(proc);
      proc.once("spawn", () => {
        logOk(`${name} started (pid=${proc.pid})`);
        resolve(proc);
      });
    } catch (err) {
      logErr(`${name} failed to start: ${err.message}`);
      reject(err);
    }
  });
}

function killChild(proc) {
  if (!proc || proc.exitCode !== null) return;
  try {
    if (IS_WIN) {
      execSync(`taskkill /T /F /PID ${proc.pid}`, {
        windowsHide: true,
        stdio: "ignore",
      });
    } else {
      // detached spawn 后 pid === pgid，传负号给 process.kill 杀整个进程组，
      // 这样 vite worker / uvicorn reload 子进程也会跟着退出。
      try {
        process.kill(-proc.pid, "SIGTERM");
      } catch (_) {
        proc.kill("SIGTERM");
      }
    }
  } catch (_) {}
}

function killAllChildren() {
  for (const proc of children) {
    killChild(proc);
  }
  children.length = 0;
}

// ═══════════════════════════════════════════════════════════
//  Health / port probes
// ═══════════════════════════════════════════════════════════

function waitForHealth(url, timeoutMs, ownedChild = null) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let request = null;
    let retry = null;
    const timeout = setTimeout(() => finish(new Error("startup_backend_timeout")), timeoutMs);
    function finish(error) {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      clearTimeout(retry);
      ownedChild?.off("exit", exited);
      ownedChild?.off("error", exited);
      request?.destroy();
      if (error) reject(error); else resolve();
    }
    function exited() { finish(new Error("startup_backend_exited")); }
    function schedule() {
      if (settled || retry !== null) return;
      retry = setTimeout(() => { retry = null; probe(); }, POLL_INTERVAL_MS);
    }
    function probe() {
      if (settled) return;
      const probeRequest = http.get(url, (res) => {
        if (settled || request !== probeRequest) return;
        validateHealthResponse(res, backendEndpoint.instanceId, valid => {
          if (settled || request !== probeRequest) return;
          if (valid) finish(); else retryProbe();
        });
      });
      request = probeRequest;
      function retryProbe() {
        if (settled || request !== probeRequest) return;
        request = null;
        probeRequest.destroy();
        schedule();
      }
      probeRequest.on("error", retryProbe);
      probeRequest.setTimeout(3000, retryProbe);
    }
    ownedChild?.once("exit", exited);
    ownedChild?.once("error", exited);
    if (ownedChild && (ownedChild.exitCode !== null || ownedChild.signalCode !== null || ownedChild.killed)) {
      exited(); return;
    }
    probe();
  });
}

function waitForPort(port, timeoutMs) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    function probe() {
      if (Date.now() - start > timeoutMs) {
        reject(new Error(`Port ${port} timeout after ${timeoutMs}ms`));
        return;
      }
      const sock = nodeNet.connect(port, "127.0.0.1", () => {
        sock.destroy();
        resolve();
      });
      sock.on("error", () => {
        sock.destroy();
        setTimeout(probe, POLL_INTERVAL_MS);
      });
      sock.setTimeout(2000, () => {
        sock.destroy();
        setTimeout(probe, POLL_INTERVAL_MS);
      });
    }
    probe();
  });
}

// ═══════════════════════════════════════════════════════════
//  Find executables
// ═══════════════════════════════════════════════════════════

function findPython() {
  // Windows: venv 下的可执行文件叫 python.exe;mac/linux 在 bin/python。
  const candidates = IS_WIN
    ? [
        path.join(ROOT_DIR, "venv", "Scripts", "python.exe"),
        path.join(ROOT_DIR, ".venv", "Scripts", "python.exe"),
        path.join(ROOT_DIR, ".venv312", "Scripts", "python.exe"),
      ]
    : [
        path.join(ROOT_DIR, ".venv", "bin", "python"),
        path.join(ROOT_DIR, "venv", "bin", "python"),
        path.join(ROOT_DIR, ".venv312", "bin", "python"),
        path.join(ROOT_DIR, ".venv", "bin", "python3"),
        path.join(ROOT_DIR, "venv", "bin", "python3"),
        path.join(ROOT_DIR, ".venv312", "bin", "python3"),
      ];
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  // PATH 回退:mac 上系统通常只有 python3,Windows 一般是 python。
  return IS_WIN ? "python" : "python3";
}

function findNode() {
  const lookupCmd = IS_WIN ? "where node" : "which node";
  try {
    const out = execSync(lookupCmd, {
      windowsHide: true,
      encoding: "utf-8",
    });
    const lines = out.trim().split("\n");
    if (lines.length > 0 && lines[0].trim()) return lines[0].trim();
  } catch (_) {}
  return "node";
}

function backendRuntimeEnv() {
  const env = {
    LUMINA_MATERIALS_DIR: path.join(app.getPath("userData"), "materials"),
    LUMINA_WORKSHOP_DATA_DIR: path.join(
      app.getPath("userData"),
      "workshop",
    ),
    LUMINA_WORKSHOP_DESKTOP_TOKEN: workshopSessionToken,
    LUMINA_API_HOST: "127.0.0.1",
    LUMINA_API_PORT: String(backendEndpoint.port),
    LUMINA_DESKTOP_INSTANCE_ID: backendEndpoint.instanceId,
    LUMINA_CLEAR_CACHE_ALLOWED_LOCAL_PORTS: [process.env.LUMINA_CLEAR_CACHE_ALLOWED_LOCAL_PORTS, backendEndpoint.port].filter(Boolean).join(","),
    LUMINA_MATERIAL_LIBRARY_ALLOWED_LOCAL_PORTS: [process.env.LUMINA_MATERIAL_LIBRARY_ALLOWED_LOCAL_PORTS, backendEndpoint.port].filter(Boolean).join(","),
  };
  return env;
}

// ═══════════════════════════════════════════════════════════
//  Single instance lock
// ═══════════════════════════════════════════════════════════

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });
}

// ═══════════════════════════════════════════════════════════
//  Window management
// ═══════════════════════════════════════════════════════════

let win = null;
let trafficLightButtonHeight = null;
let interfaceScale = null;
let applicationMenu = null;
const generatedFileDirectory = createGeneratedFileDirectoryState();
let splashWin = null;
let splashController = null;
let isQuitting = false;
let quitConfirmationPending = false;
let trustedMainFrameUrl = null;

async function confirmQuit() {
  if (isQuitting || quitConfirmationPending) return;
  quitConfirmationPending = true;
  const dlg = QUIT_DIALOG[currentLang] || QUIT_DIALOG.zh;
  try {
    const { response } = await dialog.showMessageBox(win, {
      type: "question",
      title: dlg.title,
      message: dlg.message,
      detail: dlg.detail,
      buttons: [dlg.cancel, dlg.quit],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
    });
    if (response === 1) {
      isQuitting = true;
      app.quit();
    }
  } catch (error) {
    logErr(`Quit confirmation failed: ${error.message}`);
  } finally {
    quitConfirmationPending = false;
  }
}

function fixedWorkshopResponse(status, message) {
  return new Response(message, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Security-Policy": "default-src 'none'",
      "Content-Type": "text/plain; charset=utf-8",
      "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
      "Referrer-Policy": "no-referrer",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

async function handleWorkshopProtocol(request) {
  if (workshopSafeMode) {
    return fixedWorkshopResponse(
      503,
      "Workshop runtime isolation unavailable.",
    );
  }
  if (request.method !== "GET") {
    return fixedWorkshopResponse(405, "Method not allowed.");
  }
  const runtime = resolveWorkshopRuntimeRequest(request.url, backendEndpoint.origin);
  if (runtime === null) {
    return fixedWorkshopResponse(404, "Workshop runtime not found.");
  }
  try {
    const upstream = await electronNet.fetch(runtime.backendUrl, {
      headers: {
        "X-Lumina-Workshop-Desktop-Token": workshopSessionToken,
      },
      redirect: "error",
    });
    if (!upstream.ok) {
      const status =
        upstream.status >= 400 && upstream.status <= 599
          ? upstream.status
          : 502;
      return fixedWorkshopResponse(
        status,
        "Workshop runtime unavailable.",
      );
    }
    const headers = new Headers();
    for (const name of WORKSHOP_RUNTIME_HEADER_NAMES) {
      const value = upstream.headers.get(name);
      if (value !== null) {
        headers.set(name, value);
      }
    }
    return new Response(await upstream.arrayBuffer(), {
      status: upstream.status,
      headers,
    });
  } catch (err) {
    logErr(`Workshop protocol proxy failed: ${err.name}`);
    return fixedWorkshopResponse(502, "Workshop runtime unavailable.");
  }
}

function installWorkshopSessionSecurity() {
  protocol.handle("lumina-workshop", handleWorkshopProtocol);

  session.defaultSession.webRequest.onBeforeRequest(
    { urls: ["<all_urls>"] },
    (details, callback) => {
      const trustedInternal =
        details.webContentsId === undefined &&
        details.webContents === undefined &&
        details.frame == null;
      const allowed = isAllowedWorkshopRequest({
        frameUrl: details.frame?.url ?? null,
        initiator: details.referrer || null,
        method: details.method,
        parentFrameUrl: details.frame?.parent?.url ?? null,
        resourceType: details.resourceType,
        trustedInternal,
        url: details.url,
      });
      callback({ cancel: !allowed });
    },
  );

  session.defaultSession.setPermissionRequestHandler(
    (webContents, _permission, callback, details) => {
      callback(
        isAllowedWorkshopPermission({
          frameUrl:
            details?.requestingUrl ??
            webContents?.getURL() ??
            null,
          requestingOrigin:
            details?.securityOrigin ??
            details?.requestingUrl ??
            null,
        }),
      );
    },
  );
  session.defaultSession.setPermissionCheckHandler(
    (webContents, _permission, requestingOrigin, details) =>
      isAllowedWorkshopPermission({
        frameUrl:
          details?.requestingUrl ??
          webContents?.getURL() ??
          null,
        requestingOrigin,
      }),
  );
}

function createSplash() {
  splashController = createSplashController({ BrowserWindow, ipcMain, app,
    language: currentLang, onProgress: value => launcherStartup.checkpoint(value) });
  splashWin = splashController.window;
}

function closeSplash() {
  splashController?.close();
  splashController = null;
  if (splashWin && !splashWin.isDestroyed()) {
    splashWin.close();
    splashWin = null;
  }
}

function createWindow() {
  trafficLightButtonHeight = null;
  interfaceScale = createInterfaceScaleController({
    screen,
    stateFile: path.join(app.getPath("userData"), "interface-scale.json"),
    log: logSys,
    logError: logErr,
  });
  const placement = interfaceScale.initialPlacement();
  const windowOptions = {
    ...placement.bounds,
    title: "Lumina Studio 2",
    // Keep macOS traffic lights while the renderer paints the title bar.
    ...(process.platform === "darwin" ? {
      titleBarStyle: "hidden",
      titleBarOverlay: true,
      // With zero vertical margin, WCO reports the actual native button height.
      trafficLightPosition: { x: 16, y: 0 },
    } : {}),
    ...(process.platform === "win32" ? {
      titleBarStyle: "hidden",
      autoHideMenuBar: true,
      titleBarOverlay: { color: "#e2e8f0", symbolColor: "#334155", height: 40 },
    } : {}),
    icon: fs.existsSync(ICON_PATH) ? ICON_PATH : undefined,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.cjs"),
      sandbox: false,
      zoomFactor: placement.zoomFactor,
    },
    // Matches the app background so the hidden window does not flash white
    // while the page loads.
    backgroundColor: "#f1f5f9",
    show: false,
  };

  win = new BrowserWindow(windowOptions);
  interfaceScale.attach(win);
  // macOS maximize() also reveals a hidden window. Defer it until the splash finishes.
  const mainWindow = win;
  win.once("ready-to-show", () => {
    void (async () => {
      await splashController?.complete();
      if (mainWindow.isDestroyed()) return;
      if (placement.maximize) mainWindow.maximize();
      await launcherStartup.present(mainWindow);
      closeSplash();
    })().catch(error => {
      logErr(`Window presentation failed: ${error.message}`);
      closeSplash();
      if (!mainWindow.isDestroyed()) mainWindow.show();
    });
  });

  applicationMenu?.rebuild();
  win.webContents.on("did-start-navigation", (_event, _url, isInPlace, isMainFrame) => {
    if (isMainFrame && !isInPlace) applicationMenu?.reset();
  });
  win.webContents.on("render-process-gone", () => applicationMenu?.reset());

  win.webContents.setWindowOpenHandler(({ url, referrer }) => {
    const openerUrl = referrer?.url || null;
    if (!isAllowedWorkshopPopup({ openerUrl, targetUrl: url })) {
      return { action: "deny" };
    }
    if (url.includes("/api/") || url.includes("/files/")) {
      win.webContents.downloadURL(url);
      return { action: "deny" };
    }
    return { action: "allow" };
  });

  session.defaultSession.on("will-download", (event, item, webContents) => {
    if (
      !isAllowedWorkshopDownload({
        frameUrl: webContents?.getURL() ?? null,
        url: item.getURL(),
      })
    ) {
      event.preventDefault();
      return;
    }
    const filename = item.getFilename();
    const savePath = dialog.showSaveDialogSync(win, {
      defaultPath: resolveDefaultSavePath(generatedFileDirectory.get(), filename),
      filters: [{ name: "All Files", extensions: ["*"] }],
    });
    if (savePath) {
      item.setSavePath(savePath);
    } else {
      event.preventDefault();
    }
  });

  win.webContents.on("will-frame-navigate", (details) => {
    if (
      shouldBlockWorkshopNavigation({
        frameUrl: details.frame?.url ?? null,
        initiatorUrl: details.initiator?.url ?? null,
        isMainFrame: details.isMainFrame,
        targetUrl: details.url,
      })
    ) {
      details.preventDefault();
    }
  });

  win.webContents.on("will-redirect", (details) => {
    if (
      shouldBlockWorkshopRedirect({
        frameUrl: details.frame?.url ?? null,
        initiatorUrl: details.initiator?.url ?? null,
        targetUrl: details.url,
      })
    ) {
      details.preventDefault();
    }
  });

  win.webContents.on(
    "did-frame-navigate",
    (
      _event,
      url,
      _httpResponseCode,
      _httpStatusText,
      isMainFrame,
      frameProcessId,
      frameRoutingId,
    ) => {
      if (isMainFrame || resolveWorkshopRuntimeRequest(url) === null) {
        return;
      }
      if (
        isWorkshopFrameProcessIsolated(
          win.webContents.getProcessId(),
          frameProcessId,
        )
      ) {
        return;
      }
      workshopSafeMode = true;
      logErr(
        "runtime-isolation-unavailable: Workshop safe mode enabled",
      );
      const frame = webFrameMain.fromId(
        frameProcessId,
        frameRoutingId,
      );
      void frame
        ?.executeJavaScript(
          "window.stop();document.documentElement.replaceChildren();",
        )
        .catch(() => {});
    },
  );

  win.on("close", (e) => {
    if (isQuitting) return;
    e.preventDefault();
    void confirmQuit();
  });

  trustedMainFrameUrl = new URL(FRONTEND_URL).href;
  const initialLoad = win.loadURL(FRONTEND_URL);
  void initialLoad.catch(error => {
    logErr(`Main window load failed: ${error.code || error.name}`);
  });

  win.webContents.on(
    "did-fail-load",
    (
      _event,
      _errorCode,
      _errorDescription,
      validatedUrl,
      isMainFrame,
    ) => {
      if (
        !shouldRetryFrontendLoad({
          isMainFrame,
          validatedUrl,
        })
      ) {
        return;
      }
      logErr("Frontend failed to load, retrying in 2s...");
      setTimeout(() => {
        if (win && !win.isDestroyed()) {
          win.loadURL(FRONTEND_URL);
        }
      }, 2000);
    },
  );
}

// ═══════════════════════════════════════════════════════════
//  IPC handlers
// ═══════════════════════════════════════════════════════════

ipcMain.on("application-menu-state", (event, payload) => {
  if (isTrustedMainFrameSender(event, win, `${FRONTEND_URL}/`)) applicationMenu?.update(payload);
});

// Window buttons per theme. "scrimmed" is the title bar color under the page's
// modal scrim (--surface-scrim over the bar); symbols take the same color so
// the buttons disappear into the scrim instead of floating above it.
const TITLE_BAR_OVERLAYS = {
  light: { color: "#e2e8f0", symbolColor: "#334155", scrimmed: "#6c7381" },
  dark: { color: "#020617", symbolColor: "#cbd5e1", scrimmed: "#020617" },
};

ipcMain.on("set-titlebar-theme", (event, theme, scrimmed) => {
  if (process.platform !== "win32" || !isTrustedMainFrameSender(event, win, `${FRONTEND_URL}/`)) return;
  if (theme !== "light" && theme !== "dark") return;
  const overlay = TITLE_BAR_OVERLAYS[theme];
  win.setTitleBarOverlay(scrimmed === true
    ? { color: overlay.scrimmed, symbolColor: overlay.scrimmed }
    : { color: overlay.color, symbolColor: overlay.symbolColor });
});

ipcMain.handle("align-traffic-lights", (event, centerY, controlsHeight) => {
  if (process.platform !== "darwin" || !isTrustedMainFrameSender(event, win, `${FRONTEND_URL}/`)) return null;
  if (typeof centerY !== "number" || !Number.isFinite(centerY) || centerY < 0 || centerY > 200) return null;
  const zoom = win.webContents.getZoomFactor();
  if (trafficLightButtonHeight === null) {
    if (typeof controlsHeight !== "number" || !Number.isFinite(controlsHeight) || controlsHeight <= 0 || controlsHeight > 200) return null;
    // Capture before the first move: subsequent WCO heights include our margins.
    trafficLightButtonHeight = controlsHeight * zoom;
  }
  // CSS pixels become window points through page zoom, not devicePixelRatio.
  win.setWindowButtonPosition({
    x: 16,
    y: Math.max(0, Math.round(centerY * zoom - trafficLightButtonHeight / 2)),
  });
  return null;
});

ipcMain.on("set-language", (_event, lang) => {
  if (lang === "zh" || lang === "en") {
    currentLang = lang;
    logSys(`Language set to ${lang}`);
  }
});

ipcMain.handle("get-app-version", () => {
  return app.getVersion();
});

ipcMain.handle("open-gradient-model", async (event, url) => {
  const modelUrls = [
    "https://makerworld.com.cn/zh/models/2394753-lumina2-0-ti-xing-xiao-se-se-qia-0-08ceng-gao-15ce#profileId-2721317",
    "https://makerworld.com.cn/zh/models/2400920-can-shu-hua-lumina-2-0ti-du-se-qia-zi-ding-yi-shou#profileId-2729620",
  ];
  if (!isTrustedMainFrameSender(event, win, trustedMainFrameUrl) || !modelUrls.includes(url)) {
    throw new Error("Model external link denied.");
  }
  await shell.openExternal(url);
  return { opened: true };
});

ipcMain.handle("open-wiki", async (event, url) => {
  const senderFrame = event.senderFrame ?? null;
  if (
    event.sender !== win?.webContents ||
    !isAllowedWikiIpcSender({
      isMainFrame:
        senderFrame !== null && senderFrame === event.sender.mainFrame,
      senderWebContentsId: event.sender.id,
      trustedWebContentsId: win?.webContents?.id ?? null,
      senderFrameUrl: senderFrame?.url ?? null,
      trustedMainFrameUrl,
    }) ||
    !isAllowedWikiUrl(url)
  ) {
    throw new Error("Wiki external link denied.");
  }
  await shell.openExternal(url);
  return { opened: true };
});

ipcMain.handle("save-generated-file", (event, payload) => saveGeneratedFile({
  event,
  window: win,
  trustedUrl: trustedMainFrameUrl,
  payload,
  showSaveDialog: (owner, options) => dialog.showSaveDialog(owner, options),
  defaultDirectory: generatedFileDirectory.get(),
}));

ipcMain.handle("set-generated-file-directory", (event, directory) =>
  setGeneratedFileDirectory({
    event,
    window: win,
    trustedUrl: trustedMainFrameUrl,
    state: generatedFileDirectory,
    directory,
  }));

ipcMain.handle("pick-generated-file-directory", (event) =>
  pickGeneratedFileDirectory({
    event,
    window: win,
    trustedUrl: trustedMainFrameUrl,
    state: generatedFileDirectory,
    showOpenDialog: (owner, options) => dialog.showOpenDialog(owner, options),
  }));

ipcMain.handle("get-interface-scale", (event) =>
  getInterfaceScale({
    event,
    window: win,
    trustedUrl: trustedMainFrameUrl,
    controller: interfaceScale,
  }));

ipcMain.handle("set-interface-scale", (event, preference) =>
  setInterfaceScale({
    event,
    window: win,
    trustedUrl: trustedMainFrameUrl,
    controller: interfaceScale,
    preference,
  }));

ipcMain.handle("get-native-bed-model", async (event, deviceProfileId) => {
  const senderFrame = event.senderFrame ?? null;
  if (
    !isAllowedBedModelIpcSender({
      isMainFrame:
        senderFrame !== null && senderFrame === event.sender.mainFrame,
      senderFrameUrl: senderFrame?.url ?? null,
      trustedMainFrameUrl,
    })
  ) {
    throw new Error("Native bed model access denied for this frame.");
  }
  try {
    return await fetchNativeBedModel({
      deviceProfileId,
      fetchImpl: electronNet.fetch,
      backendOrigin: backendEndpoint.origin,
    });
  } catch (_) {
    logErr("Native bed model unavailable; using Lumina fallback.");
    return null;
  }
});

ipcMain.handle("get-workshop-runtime-mode", () => ({
  mode: "desktop-secure",
  safeMode: workshopSafeMode,
}));

ipcMain.handle("pick-workshop-image", async (event) => {
  const senderUrl = event.senderFrame?.url ?? null;
  if (!isAllowedWorkshopIpcSender(senderUrl)) {
    throw new Error("Workshop image picker denied for this frame.");
  }
  const options = {
    title: "Select a Workshop image",
    properties: ["openFile"],
    filters: [
      {
        name: "Images",
        extensions: ["png", "jpg", "jpeg", "webp"],
      },
    ],
  };
  const result =
    win && !win.isDestroyed()
      ? await dialog.showOpenDialog(win, options)
      : await dialog.showOpenDialog(options);
  if (result.canceled || result.filePaths.length !== 1) {
    return null;
  }
  return loadWorkshopImageFile(result.filePaths[0]);
});

// ═══════════════════════════════════════════════════════════
//  App lifecycle
// ═══════════════════════════════════════════════════════════

app.on("before-quit", (event) => {
  if (!isQuitting && win && !win.isDestroyed()) {
    event.preventDefault();
    void confirmQuit();
  }
});

app.on("will-quit", () => {
  killAllChildren();
});

app.on("window-all-closed", () => {
  // macOS 习惯:关掉所有窗口应用仍驻留 Dock,Cmd+Q 才真正退出。
  // 但本应用是单窗口工具,而且 close 时已经走了"是否退出"的确认对话框,
  // 用户选了关闭就是想退出,所以这里和 Windows 一样直接 quit。
  app.quit();
});

app.whenReady().then(async () => {
  if (!gotLock) return;
  initLog();
  logSys("Lumina Studio Electron starting...");
  // 让 about 面板 / app.getName() / 部分 macOS 系统提示显示正确的名字。
  app.setName("Lumina Studio 2");
  if (IS_MAC) {
    app.setAboutPanelOptions({
      applicationName: "Lumina Studio 2",
      applicationVersion: app.getVersion(),
      copyright: "© Lumina Studio",
      iconPath: ICON_PATH,
    });
  }

  // macOS: 让 Dock 显示 Lumina 自己的图标而不是默认 Electron 图标。
  if (IS_MAC && app.dock && fs.existsSync(ICON_PATH)) {
    try {
      app.dock.setIcon(ICON_PATH);
    } catch (err) {
      logErr(`Dock icon set failed: ${err.message}`);
    }
  }

  if (IS_MAC) {
    applicationMenu = createApplicationMenu({
      Menu, app, getWindow: () => win, getScale: () => interfaceScale,
      onError: (error) => logErr(`Menu import could not open: ${error.message}`),
      openDocs: () => { void shell.openExternal(`https://wiki.luminastudio.com.cn/${currentLang}/`).catch((error) => logErr(`Documentation could not open: ${error.message}`)); },
    });
    applicationMenu.rebuild();
  } else {
    Menu.setApplicationMenu(null);
  }

  createSplash();

  try {
    backendEndpoint = await selectBackendEndpoint({
      portFile: path.join(app.getPath("userData"), "backend-port.json"),
      allowEphemeralFallback: true,
    });
    enableManagedDesktopHost(backendEndpoint.port);
    await assertPortsAvailable([FRONTEND_PORT]);
  } catch (error) {
    closeSplash();
    dialog.showErrorBox("Lumina Studio", currentLang === "zh"
      ? "没有可用的本地启动端口。请关闭多余的本地服务后重试；启动器不会终止其它进程。"
      : "No local startup port is available. Close unused local services and retry. Other processes will not be terminated.");
    app.quit();
    return;
  }

  // ── Start backend ──
  splashController?.checkpoint(2);
  let backendProc;
  const python = findPython();
  const apiServer = path.join(ROOT_DIR, "api_server.py");
  logSys(`Starting backend: ${python} ${apiServer}`);
  try {
    backendProc = await spawnChild(
      "Backend",
      python,
      [apiServer],
      ROOT_DIR,
      backendRuntimeEnv(),
    );
  } catch (err) {
    dialog.showErrorBox(
      "Backend Start Failed",
      `Failed to start backend: ${err.message}`,
    );
    app.quit();
    return;
  }

  // ── Wait for backend health ──
  logSys("Waiting for backend health...");
  try {
    await waitForHealth(backendEndpoint.healthUrl, HEALTH_TIMEOUT_MS, backendProc);
    logOk("Backend is healthy");
    splashController?.checkpoint(5);
    commitBackendEndpoint({
      portFile: path.join(app.getPath("userData"), "backend-port.json"),
      endpoint: backendEndpoint,
    });
  } catch (err) {
    const failureCode = ["startup_backend_timeout", "startup_backend_exited"].includes(err.message)
      ? err.message : "startup_failed";
    logErr(`Backend health check failed: ${err.message}`);
    dialog.showErrorBox("Backend Unavailable",
      failureCode === "startup_backend_timeout"
        ? `Backend did not respond within ${HEALTH_TIMEOUT_MS / 1000}s. Please check logs.`
        : `Backend startup failed: ${failureCode}. Please check logs.`);
    app.quit();
    return;
  }

  // ── Start Vite dev server ──
  const node = findNode();
  const viteJs = path.join(
    ROOT_DIR,
    "frontend",
    "node_modules",
    "vite",
    "bin",
    "vite.js",
  );
  const frontendDir = path.join(ROOT_DIR, "frontend");
  logSys(`Starting Vite: ${node} ${viteJs}`);
  try {
    await spawnChild("Frontend", node, [viteJs], frontendDir, { VITE_API_PROXY_TARGET: backendEndpoint.origin });
  } catch (err) {
    logErr(`Vite start failed: ${err.message}`);
  }

  logSys("Waiting for Vite dev server...");
  try {
    await waitForPort(FRONTEND_PORT, PORT_TIMEOUT_MS);
    logOk("Vite dev server is ready");
  } catch (err) {
    logErr(`Vite port check failed: ${err.message}`);
  }

  installWorkshopSessionSecurity();

  // ── Create main window ──
  splashController?.checkpoint(7);
  createWindow();
}).catch(error => {
  logErr(`Desktop startup failed: ${error.code || error.message}`);
  closeSplash();
  dialog.showErrorBox("Lumina Studio", currentLang === "zh"
    ? "软件未能完成启动。请打开此版本日志查看详情，再联系支持。"
    : "Startup could not finish. Open this version's logs for details and contact support.");
  app.quit();
});
