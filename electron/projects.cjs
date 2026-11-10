const fs = require('fs');
const path = require('path');
const { randomUUID } = require('crypto');
const { ProjectOpenBroker, MAX_PROJECT_BYTES, validateProjectPath } = require('./project-protocol.cjs');
const { isTrustedMainFrameSender } = require('./generated-file-directory.cjs');

function projectOpenFromArgv(argv) {
  const index = argv.indexOf('--open-project');
  const projectPath = index >= 0
    ? argv[index + 1]
    : argv.find(arg => typeof arg === 'string' && path.isAbsolute(arg) && /\.lum$/i.test(arg));
  if (!projectPath) return null;
  const idIndex = argv.indexOf('--project-request-id');
  const requestId = idIndex >= 0 ? argv[idIndex + 1] : undefined;
  return requestId === undefined ? { projectPath } : { projectPath, requestId };
}

async function atomicWrite(target, bytes, fileSystem = fs.promises) {
  const temporary = path.join(path.dirname(target), `.${path.basename(target)}.${randomUUID()}.tmp`);
  let handle;
  let created = false;
  try {
    handle = await fileSystem.open(temporary, 'wx', 0o600);
    created = true;
    await handle.writeFile(bytes);
    await handle.sync();
    await handle.close();
    handle = null;
    await fileSystem.rename(temporary, target);
  } finally {
    if (handle) await handle.close();
    if (created) await fileSystem.rm(temporary, { force: true });
  }
}

function createProjectsHost({ app, ipcMain, dialog, shell, getWindow, getTrustedUrl, env = process.env }) {
  const broker = new ProjectOpenBroker();
  let entries = null;
  let catalogLoad = null;
  let catalogQueue = Promise.resolve();
  const pickerRequests = new Set();
  let dirty = false;
  let pendingClose = null;
  let rendererAvailable = true;
  let trackedContents = null;
  function watchRenderer() {
    const contents = getWindow()?.webContents;
    if (!contents || trackedContents === contents) return;
    trackedContents = contents;
    const unavailable = () => {
      rendererAvailable = false;
      broker.appReady = false;
      delivered.clear();
      const pending = pendingClose;
      pendingClose = null;
      pending?.resolve(null);
    };
    contents.on?.('render-process-gone', unavailable);
    contents.on?.('unresponsive', unavailable);
    contents.on?.('responsive', () => { rendererAvailable = true; broker.markAppReady(); });
    contents.on?.('destroyed', unavailable);
    contents.on?.('did-navigate', unavailable);
  }
  const managed = path.isAbsolute(env.LUMINA_MANAGED_USER_DATA || '') && /^[a-zA-Z0-9_-]{1,128}$/.test(env.LUMINA_MANAGED_RUNTIME_KEY || '');
  const projectRoot = () => path.join(managed ? env.LUMINA_MANAGED_USER_DATA : app.getPath('userData'), 'projects');
  const catalogPath = () => path.join(projectRoot(), 'catalog.json');
  let receiptQueue = Promise.resolve();
  const delivered = new Set();
  const catalog = async () => {
    if (entries) return entries;
    catalogLoad ??= (async () => {
      try {
        if ((await fs.promises.stat(catalogPath())).size > 16 * 1024 * 1024) throw new Error('Project catalog exceeds its size limit');
        const data = JSON.parse(await fs.promises.readFile(catalogPath(), 'utf8'));
        entries = Array.isArray(data) ? data.filter(item => item && typeof item.fileEntryId === 'string' && typeof item.path === 'string') : [];
      } catch (error) {
        if (error.code !== 'ENOENT') { catalogLoad = null; throw error; }
        entries = [];
      }
      return entries;
    })();
    return catalogLoad;
  };
  const persist = async () => {
    const bytes = Buffer.from(JSON.stringify(entries));
    catalogQueue = catalogQueue.catch(() => {}).then(async () => {
      await fs.promises.mkdir(path.dirname(catalogPath()), { recursive: true });
      await atomicWrite(catalogPath(), bytes);
    });
    await catalogQueue;
  };
  const remember = async (filePath, metadata = {}) => {
    const resolved = await fs.promises.realpath(validateProjectPath(filePath));
    const rows = await catalog();
    let entry = rows.find(item => item.path === resolved);
    if (!entry) { entry = { fileEntryId: randomUUID(), path: resolved, pinned: false }; rows.push(entry); }
    for (const key of ['projectId', 'revisionId', 'name', 'modifiedAt']) {
      if (typeof metadata[key] === 'string') entry[key] = metadata[key].slice(0, 512);
    }
    if (Array.isArray(metadata.workflowKinds)) entry.workflowKinds = metadata.workflowKinds.filter(item => typeof item === 'string').slice(0, 64);
    if (typeof metadata.thumbnailDataUrl === 'string' && metadata.thumbnailDataUrl.length <= 96000 && /^data:image\/png;base64,[a-zA-Z0-9+/=]+$/.test(metadata.thumbnailDataUrl)) entry.thumbnailDataUrl = metadata.thumbnailDataUrl;
    entry.lastOpenedAt = new Date().toISOString();
    const older = rows.filter(item => item !== entry).sort((a, b) => Number(b.pinned) - Number(a.pinned) || String(b.lastOpenedAt).localeCompare(String(a.lastOpenedAt)));
    entries = [entry, ...older.slice(0, 127)];
    try { await persist(); }
    catch (error) { return { ...entry, catalogWarning: `Project catalog update failed: ${error.message}` }; }
    return { ...entry };
  };
  function trusted(event) {
    if (!isTrustedMainFrameSender(event, getWindow(), getTrustedUrl())) throw new Error('Project access denied');
  }
  function handle(channel, action) { ipcMain.handle(channel, (event, ...args) => { trusted(event); return action(...args); }); }
  broker.on('state', value => {
    if (managed) {
      const receipt = Buffer.from(JSON.stringify({ protocol: 1, requestId: value.requestId, state: value.state, runtimeKey: env.LUMINA_MANAGED_RUNTIME_KEY }));
      receiptQueue = receiptQueue.catch(() => {}).then(async () => {
        const directory = path.join(projectRoot(), 'open-requests');
        await fs.promises.mkdir(directory, { recursive: true });
        await atomicWrite(path.join(directory, `${value.requestId}.json`), receipt);
      });
      void receiptQueue.catch(() => {});
    }
    if ((value.state === 'opening' && value.result?.bytes) || value.state === 'failed') {
      if (!delivered.has(value.requestId) && !pickerRequests.has(value.requestId)) getWindow()?.webContents.send('project-open', value);
      delivered.add(value.requestId);
    }
  });
  async function request(filePath, requestId = randomUUID()) {
    validateProjectPath(filePath);
    if ([...broker.entries.values()].filter(entry => ['received', 'awaiting-user', 'opening'].includes(entry.state)).length >= 16) throw new Error('Too many pending project opens');
    for (const [id, entry] of broker.entries) {
      if (broker.entries.size <= 64) break;
      if (['opened', 'limited', 'failed', 'cancelled'].includes(entry.state)) { broker.entries.delete(id); delivered.delete(id); }
    }
    const result = await broker.request({ projectPath: filePath, requestId });
    return result;
  }
  function enqueueProject(open) {
    if (!open) return;
    void request(open.projectPath, open.requestId).catch(error => {
      getWindow()?.webContents.send('project-open', { state: 'failed', error: error.message });
    });
  }
  function enqueueArgv(argv) { enqueueProject(projectOpenFromArgv(argv)); }
  app.on('open-file', (event, filePath) => {
    if (/\.lum$/i.test(filePath)) {
      event.preventDefault();
      enqueueProject({ projectPath: filePath });
    }
  });
  handle('projects-ready', () => {
    watchRenderer(); rendererAvailable = true;
    broker.markAppReady();
    // Navigation can interrupt the renderer between receipt and commit.
    for (const entry of broker.entries.values()) {
      if (entry.result?.bytes && !delivered.has(entry.requestId) && !pickerRequests.has(entry.requestId)
        && ['opening', 'awaiting-user'].includes(entry.state)) {
        getWindow()?.webContents.send('project-open', { ...broker.get(entry.requestId), state: 'opening' });
        delivered.add(entry.requestId);
      }
    }
    return true;
  });
  handle('projects-progress', (id, state) => broker.progress(id, state));
  handle('projects-dirty', value => { dirty = value === true; return true; });
  handle('projects-close-answer', (id, accepted) => {
    if (!pendingClose || pendingClose.id !== id) return false;
    const pending = pendingClose;
    pendingClose = null;
    pending.resolve(accepted === true);
    return true;
  });
  handle('projects-open', async requestId => {
    const result = await dialog.showOpenDialog(getWindow(), { properties: ['openFile'], filters: [{ name: 'Lumina project', extensions: ['lum'] }] });
    if (result.canceled || !result.filePaths[0]) return { state: 'cancelled' };
    requestId = requestId || randomUUID();
    pickerRequests.add(requestId);
    try { return await request(result.filePaths[0], requestId); }
    finally { pickerRequests.delete(requestId); }
  });
  handle('projects-open-entry', async fileEntryId => {
    const entry = (await catalog()).find(item => item.fileEntryId === fileEntryId);
    if (!entry) throw new Error('Unknown project file');
    const requestId = randomUUID();
    pickerRequests.add(requestId);
    try { return await request(entry.path, requestId); }
    finally { pickerRequests.delete(requestId); }
  });
  handle('projects-complete', async (requestId, state, metadata) => {
    const response = broker.get(requestId);
    if (!response || !['opened', 'limited', 'failed', 'cancelled'].includes(state)) return false;
    if (state === 'cancelled') {
      const accepted = broker.cancel(requestId);
      if (accepted) releaseBytes(requestId);
      return accepted;
    }
    const accepted = broker.complete(requestId, { state });
    if (accepted && ['opened', 'limited'].includes(state)) {
      const filePath = response.result.path;
      releaseBytes(requestId, filePath);
      const entry = await remember(filePath, metadata);
      return entry;
    }
    if (accepted) releaseBytes(requestId);
    return accepted;
  });
  handle('projects-save', async ({ bytes, fileEntryId, suggestedName, metadata, bundle = false }) => {
    if (!(bytes instanceof Uint8Array) || bytes.byteLength > MAX_PROJECT_BYTES || bytes.byteLength < 4 || bytes[0] !== 0x50 || bytes[1] !== 0x4b) throw new Error('Invalid project bytes');
    // Read the catalog before touching the destination, so a corrupt index
    // cannot turn an already-written project into an unacknowledged save.
    const rows = bundle ? [] : await catalog();
    const entry = fileEntryId ? rows.find(item => item.fileEntryId === fileEntryId) : null;
    if (fileEntryId && !entry) throw new Error('Unknown project file');
    let target = entry?.path;
    if (!target) {
      const result = await dialog.showSaveDialog(getWindow(), { defaultPath: path.basename(suggestedName || 'Untitled.lum'), filters: [{ name: bundle ? 'Lumina bundle' : 'Lumina project', extensions: [bundle ? 'zip' : 'lum'] }] });
      if (result.canceled || !result.filePath) return { state: 'cancelled' };
      target = result.filePath;
    }
    if (!bundle) validateProjectPath(target);
    await atomicWrite(target, Buffer.from(bytes));
    return { state: 'saved', entry: bundle ? null : await remember(target, metadata) };
  });
  handle('projects-catalog', async () => (await catalog()).map(item => ({ ...item })));
  handle('projects-update-entry', async (fileEntryId, change) => {
    const rows = await catalog();
    const entry = rows.find(item => item.fileEntryId === fileEntryId);
    if (!entry) return;
    if (change === 'remove') entries = rows.filter(item => item !== entry);
    else if (change === 'pin') entry.pinned = !entry.pinned;
    else if (change === 'locate') { shell.showItemInFolder(entry.path); return; }
    else throw new Error('Invalid project catalog action');
    await persist();
  });
  function releaseBytes(id, filePath) {
    const entry = broker.entries.get(id);
    entry.result = filePath ? { path: filePath } : null;
    entry.promise = Promise.resolve(broker.get(id));
    entry.resolveInitial = null;
  }
  function confirmProjectClose() {
    watchRenderer();
    if (!dirty || !rendererAvailable || getWindow()?.webContents.isCrashed?.()) return Promise.resolve(null);
    if (pendingClose) return pendingClose.promise;
    const id = randomUUID();
    let resolve;
    const promise = new Promise(done => { resolve = done; });
    pendingClose = { id, resolve, promise };
    const window = getWindow();
    if (!window || window.isDestroyed()) { pendingClose = null; resolve(false); }
    else {
      const cancelled = () => { if (pendingClose?.id === id) { pendingClose = null; resolve(false); } };
      window.webContents.once?.('destroyed', cancelled);
      void promise.finally(() => window.webContents.removeListener?.('destroyed', cancelled));
      window.webContents.send('project-close-request', id);
    }
    return promise;
  }
  return { enqueueArgv, enqueueProject, broker, confirmProjectClose, flushReceipts: () => receiptQueue };
}

module.exports = { createProjectsHost, projectOpenFromArgv, atomicWrite };
