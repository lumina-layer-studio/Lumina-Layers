"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const vm = require("node:vm");
const { EventEmitter } = require("node:events");
const { createRequire } = require("node:module");
const mainPath = path.join(__dirname, "../main.cjs");
const nativeRequire = createRequire(mainPath);

async function until(check) {
  const deadline = Date.now() + 2000;
  while (!check()) {
    assert.ok(Date.now() < deadline, "desktop must reach the expected state");
    await new Promise(resolve => setImmediate(resolve));
  }
}

async function fixture(t, platform, mode = "healthy", prepareUserData = () => {}, pythonPaths = null) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "lumina-source-desktop-"));
  prepareUserData(root);
  const windows = [], children = [], dialogs = [], errors = [], commands = [], signals = [];
  const externalUrls = [];
  const timers = new Set();
  const ipcMain = new EventEmitter();
  const ipcHandlers = new Map();
  let applicationMenu;
  ipcMain.handle = (channel, handler) => { ipcHandlers.set(channel, handler); };
  ipcMain.removeHandler = channel => ipcHandlers.delete(channel);
  const event = () => ({ defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } });
  const app = new EventEmitter();
  Object.assign(app, {
    getPath: () => root, requestSingleInstanceLock: () => true,
    whenReady: () => Promise.resolve(), getVersion: () => "2.0.0", setName() {}, setAboutPanelOptions() {},
    quit() {
      const before = event();
      this.emit("before-quit", before);
      if (before.defaultPrevented) return;
      this.closingForQuit = true;
      for (const window of windows.filter(w => !w.isDestroyed())) window.close();
      this.closingForQuit = false;
      this.emit("will-quit", event());
      this.quitted = true;
    },
  });
  class Window extends EventEmitter {
    constructor(options) {
      super(); this.options = options; windows.push(this);
      this.webContents = new EventEmitter();
      this.webContents.setWindowOpenHandler = () => {};
      this.webContents.mainFrame = {};
      this.webContents.zoomFactor = options.webPreferences?.zoomFactor ?? 1;
      this.webContents.getZoomFactor = () => this.webContents.zoomFactor;
      this.webContents.setZoomFactor = factor => { this.webContents.zoomFactor = factor; };
      this.webContents.send = () => {};
    }
    loadURL(url) { this.loadedUrl = url; this.webContents.mainFrame.url = new URL(url).href; return Promise.resolve(); }
    loadFile() { return Promise.resolve(); }
    focus() {}
    getBounds() { return { x: this.options.x, y: this.options.y, width: this.options.width, height: this.options.height }; }
    maximize() { this.maximized = true; this.show(); }
    show() { this.visible = true; this.emit('show'); }
    isVisible() { return !!this.visible; }
    isDestroyed() { return Boolean(this.destroyed); }
    setTitleBarOverlay(overlay) { (this.overlays ??= []).push(overlay); }
    close() {
      const closing = event();
      this.emit("close", closing);
      if (!closing.defaultPrevented) {
        this.destroyed = true; this.emit("closed");
        if (!app.closingForQuit && windows.every(w => w.isDestroyed())) app.emit("window-all-closed");
      }
    }
  }
  const defaultSession = new EventEmitter();
  Object.assign(defaultSession, {
    webRequest: { onBeforeRequest() {} }, setPermissionRequestHandler() {}, setPermissionCheckHandler() {},
  });
  // A 1920x1080 screen at 100% system scaling with a 48 px taskbar.
  const display = {
    bounds: { x: 0, y: 0, width: 1920, height: 1080 },
    size: { width: 1920, height: 1080 },
    workArea: { x: 0, y: 0, width: 1920, height: 1032 },
  };
  const screen = new EventEmitter();
  screen.getPrimaryDisplay = () => display;
  screen.getDisplayMatching = () => display;
  let healthCallback;
  const modules = {
    electron: {
      shell: { async openExternal(url) { externalUrls.push(url); } },
      app, BrowserWindow: Window, ipcMain, Menu: { setApplicationMenu(menu) { applicationMenu = menu; }, buildFromTemplate: template => template }, screen,
      dialog: {
        showErrorBox(...args) { errors.push(args); },
        showMessageBox(_window, options) { return new Promise(resolve => dialogs.push({ options, resolve })); },
      },
      protocol: { registerSchemesAsPrivileged() {}, handle() {} },
      session: { defaultSession }, net: {}, webFrameMain: {},
    },
    "./backend-endpoint.cjs": {
      ...nativeRequire("./backend-endpoint.cjs"),
      assertPortsAvailable: async () => {},
      selectBackendEndpoint: async () => {
        if (mode === "port-busy") throw new Error("port_in_use");
        return { port: 8001, origin: "http://127.0.0.1:8001", healthUrl: "http://127.0.0.1:8001/api/health", instanceId: "source-test", previousPort: null, previousOrigin: null };
      },
    },
    child_process: {
      spawn(command, args, options) {
        const child = new EventEmitter();
        Object.assign(child, { command, args, options, stdout: new EventEmitter(), stderr: new EventEmitter(),
          pid: 24680 + children.length, exitCode: null, signalCode: null, killed: false });
        children.push(child);
        queueMicrotask(() => child.emit("spawn"));
        return child;
      },
      execSync(command) { commands.push(command); return "node\n"; },
    },
    http: { get(_url, callback) {
      healthCallback = callback;
      const request = new EventEmitter();
      request.setTimeout = () => {}; request.destroy = () => {};
      return request;
    } },
    net: { connect(_port, _host, connected) {
      const socket = new EventEmitter();
      socket.destroy = () => {}; socket.setTimeout = () => {};
      queueMicrotask(connected);
      return socket;
    } },
    fs: {
      ...fs,
      existsSync(file) {
        if (pythonPaths && /^python(?:3|\.exe)?$/.test(path.basename(file))) {
          return pythonPaths.includes(file);
        }
        return fs.existsSync(file);
      },
      createWriteStream: () => ({ write() {} }),
    },
  };
  t.after(() => {
    for (const timer of timers) clearTimeout(timer);
    for (const child of children) { child.exitCode = 0; child.emit("exit", 0); }
    fs.rmSync(root, { recursive: true, force: true });
  });
  vm.runInNewContext(fs.readFileSync(mainPath, "utf8"), {
    require: name => modules[name] || nativeRequire(name),
    __dirname: path.dirname(mainPath), console: { log() {} }, URL, Response, Headers,
    setTimeout(callback, delay) { const timer = setTimeout(callback, delay); timers.add(timer); return timer; },
    clearTimeout,
    process: { platform, env: { LUMINA_MATERIAL_REGISTRY_URL: "https://custom.example/materials" },
      kill(pid, signal) { signals.push({ pid, signal }); } },
  }, { filename: mainPath });
  await until(() => healthCallback || app.quitted);
  const mainWindow = () => windows.find(w => w.options.title === "Lumina Studio 2");
  return { app, children, dialogs, errors, commands, signals, ipcMain, ipcHandlers, mainWindow, externalUrls,
    menu: () => applicationMenu,
    portStatePath: path.join(root, "backend-port.json"),
    interfaceScalePath: path.join(root, "interface-scale.json"),
    async healthy() {
      const response = new EventEmitter();
      Object.assign(response, { statusCode: 200, headers: { "content-type": "application/json" } });
      healthCallback(response);
      response.emit("data", Buffer.from(JSON.stringify({ status: "ok", service: "lumina-studio", desktop_instance_id: "source-test" })));
      response.emit("end");
      await until(mainWindow);
      mainWindow().emit("ready-to-show");
      const splash = windows.find(w => w.options.webPreferences?.preload?.endsWith('splash-preload.cjs'));
      assert.equal(mainWindow().visible, undefined, 'main stays hidden until Studio finishes its own animation');
      ipcMain.emit('studio-splash-finished', { sender: splash.webContents, senderFrame: splash.webContents.mainFrame });
      await until(() => mainWindow().visible);
    },
  };
}

test('macOS installs a menu during startup and accepts state only from its trusted main frame', async t => {
  const f = await fixture(t, 'darwin');
  const item = id => f.menu().flatMap(entry => entry.submenu).find(entry => entry.id === id);
  assert.equal(item('settings').enabled, false);
  await f.healthy();
  const contents = f.mainWindow().webContents;
  const payload = { commands: { settings: true } };
  f.ipcMain.emit('application-menu-state', { sender: contents, senderFrame: { url: contents.mainFrame.url } }, payload);
  assert.equal(item('settings').enabled, false);
  f.ipcMain.emit('application-menu-state', { sender: contents, senderFrame: contents.mainFrame }, payload);
  assert.equal(item('settings').enabled, true);
  contents.emit('did-start-navigation', {}, 'http://127.0.0.1:4174/', false, false);
  assert.equal(item('settings').enabled, true);
  contents.emit('did-start-navigation', {}, 'http://127.0.0.1:4174/', false, true);
  assert.equal(item('settings').enabled, false);
});

test("win32 window buttons blend into the page scrim while a modal is open", async t => {
  const f = await fixture(t, "win32");
  await f.healthy();
  const window = f.mainWindow();
  const page = { sender: window.webContents, senderFrame: window.webContents.mainFrame };
  const workshopFrame = { sender: window.webContents, senderFrame: { url: "lumina-workshop://module/" } };

  f.ipcMain.emit("set-titlebar-theme", page, "light", true);
  f.ipcMain.emit("set-titlebar-theme", page, "light", false);
  f.ipcMain.emit("set-titlebar-theme", page, "dark", true);
  f.ipcMain.emit("set-titlebar-theme", page, "dark");
  f.ipcMain.emit("set-titlebar-theme", workshopFrame, "light", true);
  f.ipcMain.emit("set-titlebar-theme", page, "sepia", true);
  // main.cjs runs in its own context, so compare plain data rather than prototypes.
  assert.deepEqual(JSON.parse(JSON.stringify(window.overlays)), [
    { color: "#6c7381", symbolColor: "#6c7381" },
    { color: "#e2e8f0", symbolColor: "#334155" },
    { color: "#020617", symbolColor: "#020617" },
    { color: "#020617", symbolColor: "#cbd5e1" },
  ]);
});

for (const platform of ["win32", "darwin"]) {
  test(`source desktop on ${platform} uses the project Python 3.12 environment before PATH`, async t => {
    const python = path.join(path.dirname(mainPath), "..", ".venv312",
      ...(platform === "win32" ? ["Scripts", "python.exe"] : ["bin", "python"]));
    const f = await fixture(t, platform, "healthy", () => {}, [python]);
    assert.equal(f.children[0].command, python);
    await f.healthy();
    assert.equal(f.errors.length, 0);
    assert.equal(f.mainWindow().visible, true);
  });

  test(`source desktop on ${platform} launches Python and Vite, then confirms and cleans up on exit`, async t => {
    const f = await fixture(t, platform);
    assert.equal(path.basename(f.children[0].args[0]), "api_server.py");
    assert.equal(f.children[0].options.env.LUMINA_API_PORT, "8001");
    assert.equal(f.children[0].options.env.LUMINA_MATERIAL_REGISTRY_URL, "https://custom.example/materials");
    assert.equal(fs.existsSync(f.portStatePath), false);
    await f.healthy();
    assert.deepEqual(JSON.parse(fs.readFileSync(f.portStatePath, "utf8")), { schemaVersion: 1, port: 8001 });
    assert.equal(f.children.length, 2);
    assert.equal(path.basename(f.children[1].args[0]), "vite.js");
    assert.equal(f.children[1].options.env.VITE_API_PROXY_TARGET, "http://127.0.0.1:8001");
    assert.equal(f.mainWindow().loadedUrl, "http://127.0.0.1:4174");
    assert.equal(f.mainWindow().visible, true);
    f.ipcMain.emit("set-language", {}, "en");
    f.mainWindow().close();
    assert.deepEqual(Array.from(f.dialogs[0].options.buttons), ["Cancel", "Quit"]);
    f.dialogs[0].resolve({ response: 0 });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(f.mainWindow().isDestroyed(), false);
    assert.equal(f.app.quitted, undefined);
    f.mainWindow().close();
    f.dialogs[1].resolve({ response: 1 });
    await until(() => f.app.quitted);
    assert.equal(f.mainWindow().isDestroyed(), true);
    if (platform === "win32") assert.equal(f.commands.filter(c => c.startsWith("taskkill /T /F /PID ")).length, 2);
    else assert.deepEqual(f.signals, [{ pid: -24680, signal: "SIGTERM" }, { pid: -24681, signal: "SIGTERM" }]);
  });
}

test("source desktop reports port conflicts before spawning children", async t => {
  const f = await fixture(t, "darwin", "port-busy");
  assert.equal(f.children.length, 0);
  assert.equal(f.errors.length, 1);
  assert.equal(f.app.quitted, true);
});

test("source desktop reports an exited backend and quits", async t => {
  const f = await fixture(t, "darwin");
  f.children[0].exitCode = 1;
  f.children[0].emit("exit", 1);
  await until(() => f.app.quitted);
  assert.equal(f.errors[0][0], "Backend Unavailable");
  assert.equal(f.mainWindow(), undefined);
});

test("source desktop opens at native scale and only its page may change it", async t => {
  const f = await fixture(t, "win32");
  await f.healthy();
  const window = f.mainWindow();
  assert.equal(window.options.webPreferences.zoomFactor, 1);
  assert.equal(window.maximized, undefined);
  assert.equal(window.visible, true);

  const page = { sender: window.webContents, senderFrame: window.webContents.mainFrame };
  const workshopFrame = { sender: window.webContents, senderFrame: { url: "lumina-workshop://module/" } };
  const getScale = f.ipcHandlers.get("get-interface-scale");
  const setScale = f.ipcHandlers.get("set-interface-scale");
  assert.deepEqual(await getScale(page), { status: "ok", preference: "100" });
  assert.deepEqual(await setScale(workshopFrame, "150"), { status: "error", code: "denied" });
  assert.deepEqual(await setScale(page, "150"), { status: "ok", preference: "150" });
  assert.equal(window.webContents.zoomFactor, 1.5);
  assert.deepEqual(JSON.parse(fs.readFileSync(f.interfaceScalePath, "utf8")), { schemaVersion: 1, preference: "150" });
});

test("source desktop reopens at the interface scale saved last time", async t => {
  const f = await fixture(t, "win32", "healthy", root => {
    fs.writeFileSync(path.join(root, "interface-scale.json"), JSON.stringify({ schemaVersion: 1, preference: "80" }));
  });
  await f.healthy();
  const window = f.mainWindow();
  assert.equal(window.options.webPreferences.zoomFactor, 0.8);
  assert.deepEqual(
    [window.options.x, window.options.y, window.options.width, window.options.height],
    [384, 156, 1152, 720],
  );
  assert.equal(window.maximized, undefined);
});

 test("gradient model links open externally only for trusted UI and approved URLs", async t => {
  const f = await fixture(t, "darwin");
  await f.healthy();
  const contents = f.mainWindow().webContents;
  const sender = { sender: contents, senderFrame: contents.mainFrame };
  const open = f.ipcHandlers.get("open-gradient-model");
  const urls = [
    "https://makerworld.com.cn/zh/models/2394753-lumina2-0-ti-xing-xiao-se-se-qia-0-08ceng-gao-15ce#profileId-2721317",
    "https://makerworld.com.cn/zh/models/2400920-can-shu-hua-lumina-2-0ti-du-se-qia-zi-ding-yi-shou#profileId-2729620",
  ];
  for (const url of urls) await open(sender, url);
  assert.deepEqual(f.externalUrls, urls);
  await assert.rejects(open(sender, "https://example.com"), /denied/);
  await assert.rejects(open({ sender: contents, senderFrame: { url: contents.mainFrame.url } }, urls[0]), /denied/);
  assert.equal(f.externalUrls.length, 2);
});
