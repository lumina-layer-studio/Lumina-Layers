const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { createProjectsHost, atomicWrite } = require('../projects.cjs');

const bytes = new Uint8Array([0x50, 0x4b, 3, 4, 1, 2, 3]);
async function setup(t, managed = false) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'lumina-project-host-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const app = new EventEmitter();
  app.getPath = () => root;
  const handlers = new Map();
  const sent = [];
  const mainFrame = { url: 'file:///app/index.html' };
  const window = { isDestroyed: () => false, webContents: { mainFrame, send: (...args) => sent.push(args) } };
  const event = { sender: window.webContents, senderFrame: mainFrame };
  const dialog = { showSaveDialog: async () => ({ canceled: true }), showOpenDialog: async () => ({ canceled: true }) };
  const host = createProjectsHost({ app, ipcMain: { handle: (name, handler) => handlers.set(name, handler) }, dialog, shell: { showItemInFolder() {} }, getWindow: () => window, getTrustedUrl: () => mainFrame.url, env: managed ? { LUMINA_MANAGED_USER_DATA: path.join(root, 'shared'), LUMINA_MANAGED_RUNTIME_KEY: 'test-runtime' } : {} });
  return { root, host, handlers, sent, event, dialog, call: (name, ...args) => handlers.get(name)(event, ...args) };
}

test('two files carrying the same project identity are distinct recent entries; Save uses the active path', async t => {
  const s = await setup(t);
  const metadata = { projectId: 'same-project', revisionId: 'r1', name: 'Artwork', workflowKinds: ['converter'] };
  s.dialog.showSaveDialog = async () => ({ filePath: path.join(s.root, 'a.lum') });
  const first = await s.call('projects-save', { bytes, metadata });
  s.dialog.showSaveDialog = async () => ({ filePath: path.join(s.root, 'b.lum') });
  const second = await s.call('projects-save', { bytes, metadata });
  assert.notEqual(first.entry.fileEntryId, second.entry.fileEntryId);
  assert.equal((await s.call('projects-catalog')).length, 2);
  s.dialog.showSaveDialog = () => assert.fail('Save must use the existing file capability');
  const changed = new Uint8Array([...bytes, 4, 5]);
  await s.call('projects-save', { bytes: changed, fileEntryId: first.entry.fileEntryId, metadata: { ...metadata, revisionId: 'r2' } });
  assert.deepEqual(new Uint8Array(await fs.readFile(first.entry.path)), changed);
  assert.deepEqual(new Uint8Array(await fs.readFile(second.entry.path)), bytes);
  await s.call('projects-update-entry', first.entry.fileEntryId, 'remove');
  assert.equal((await s.call('projects-catalog')).length, 1);
  assert.ok(await fs.stat(first.entry.path));
});

test('startup open waits for renderer readiness and only becomes opened after restore acknowledgement', async t => {
  const s = await setup(t);
  const target = path.join(s.root, 'startup.lum');
  await fs.writeFile(target, bytes);
  s.host.enqueueArgv(['app', '--open-project', target, '--project-request-id', 'launcher-1']);
  assert.equal(s.host.broker.get('launcher-1').state, 'awaiting-user');
  assert.equal(s.sent.length, 0);
  await s.call('projects-ready');
  const response = await s.host.broker.entries.get('launcher-1').promise;
  assert.equal(response.state, 'opening');
  assert.equal(s.sent[0][0], 'project-open');
  await s.call('projects-complete', 'launcher-1', 'opened', { name: 'Startup', projectId: 'project' });
  assert.equal(s.host.broker.get('launcher-1').state, 'opened');
  assert.equal(s.host.broker.get('launcher-1').result.bytes, undefined);
});

test('project IPC denies module frames and arbitrary file entry IDs', async t => {
  const s = await setup(t);
  assert.throws(() => s.handlers.get('projects-catalog')({ sender: s.event.sender, senderFrame: {} }), /denied/);
  await assert.rejects(s.call('projects-open-entry', '../outside'), /Unknown/);
});

test('managed Launcher receives correlated progress and restored receipts in the shared root', async t => {
  const s = await setup(t, true);
  const target = path.join(s.root, 'managed.lum');
  await fs.writeFile(target, bytes);
  s.host.enqueueArgv(['app', '--open-project', target, '--project-request-id', 'launcher-managed']);
  await s.host.flushReceipts();
  const receipt = () => fs.readFile(path.join(s.root, 'shared/projects/open-requests/launcher-managed.json'), 'utf8').then(JSON.parse);
  assert.deepEqual(await receipt(), { protocol: 1, requestId: 'launcher-managed', state: 'awaiting-user', runtimeKey: 'test-runtime' });
  await s.call('projects-ready');
  await s.host.broker.entries.get('launcher-managed').promise;
  await s.call('projects-progress', 'launcher-managed', 'awaiting-user');
  await s.host.flushReceipts();
  assert.equal((await receipt()).state, 'awaiting-user');
  await s.call('projects-complete', 'launcher-managed', 'limited', { name: 'Partially supported', projectId: 'p' });
  await s.host.flushReceipts();
  assert.equal((await receipt()).state, 'limited');
  assert.equal(JSON.parse(await fs.readFile(path.join(s.root, 'shared/projects/catalog.json'), 'utf8'))[0].name, 'Partially supported');
});

test('window close waits for the matching renderer save/discard/cancel decision', async t => {
  const s = await setup(t);
  assert.equal(await s.host.confirmProjectClose(), null);
  await s.call('projects-dirty', true);
  const pending = s.host.confirmProjectClose();
  const [event, id] = s.sent.at(-1);
  assert.equal(event, 'project-close-request');
  assert.equal(await s.call('projects-close-answer', 'wrong-request', true), false);
  assert.equal(s.host.confirmProjectClose(), pending);
  await s.call('projects-close-answer', id, false);
  assert.equal(await pending, false);
  const retry = s.host.confirmProjectClose();
  await s.call('projects-close-answer', s.sent.at(-1)[1], true);
  assert.equal(await retry, true);
});

test('an interrupted atomic replacement keeps the previous project and removes only its own temporary file', async t => {
  const s = await setup(t);
  const target = path.join(s.root, 'art.lum');
  await fs.writeFile(target, 'old');
  await assert.rejects(atomicWrite(target, bytes, { ...fs, rename: async () => { throw new Error('disk error'); } }), /disk error/);
  assert.equal(await fs.readFile(target, 'utf8'), 'old');
  assert.deepEqual(await fs.readdir(s.root), ['art.lum']);
  let removed = false;
  await assert.rejects(atomicWrite(target, bytes, { ...fs, open: async () => { throw new Error('collision'); }, rm: async () => { removed = true; } }), /collision/);
  assert.equal(removed, false);
});
