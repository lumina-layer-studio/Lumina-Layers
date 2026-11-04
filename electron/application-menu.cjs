const { stepInterfaceScalePreference } = require('./interface-scale.cjs');

const COMMANDS = ['about', 'settings', 'import', 'export', 'report', 'projectNew', 'projectOpen', 'projectSave', 'projectSaveAs'];
const DEFAULT_LABELS = {
  projectNew: 'New Project…', projectOpen: 'Open Project…', projectSave: 'Save Project', projectSaveAs: 'Save Project As…',
  about: 'About Lumina Studio', settings: 'Settings…', services: 'Services',
  hide: 'Hide Lumina Studio', hideOthers: 'Hide Others', unhide: 'Show All', quit: 'Quit Lumina Studio',
  file: 'File', import: 'Import image / SVG / share card…', export: 'Save generated file…', close: 'Close Window',
  edit: 'Edit', undo: 'Undo', redo: 'Redo', cut: 'Cut', copy: 'Copy', paste: 'Paste', selectAll: 'Select All',
  view: 'View', zoomIn: 'Zoom In', zoomOut: 'Zoom Out', resetZoom: 'Actual Size', togglefullscreen: 'Toggle Full Screen',
  window: 'Window', minimize: 'Minimize', zoom: 'Zoom', front: 'Bring All to Front',
  help: 'Help', docs: 'Lumina Studio Documentation', report: 'Report a Problem…',
};

function createApplicationMenu({ Menu, app, getWindow, getScale, openDocs, onError = () => {} }) {
  let labels = { ...DEFAULT_LABELS };
  let enabled = {};
  function rebuild() {
    const role = (name, accelerator) => ({ role: name, label: labels[name], ...(accelerator ? { accelerator } : {}) });
    const separator = { type: 'separator' };
    const command = (id, accelerator) => ({
      id, label: labels[id], enabled: enabled[id] === true, accelerator,
      click: () => {
        const window = getWindow();
        if (!enabled[id] || !window || window.isDestroyed()) return;
        if (id === 'import') {
          // File inputs require Chromium user activation, which plain IPC does not carry.
          // The script is constant and runs only in the application's main frame.
          void window.webContents.executeJavaScript(
            "window.dispatchEvent(new Event('lumina-menu-import'))", true,
          ).catch(onError);
        } else {
          window.webContents.send('application-menu-command', id);
        }
      },
    });
    const scale = (id, direction, accelerator) => ({
      label: labels[id], accelerator, enabled: Boolean(getScale()),
      click: () => {
        const controller = getScale();
        if (controller) controller.choose(stepInterfaceScalePreference(controller.preference(), direction));
      },
    });
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      { label: 'Lumina Studio', submenu: [
        { label: labels.about, click: () => {
          const window = getWindow();
          if (enabled.about && window && !window.isDestroyed()) window.webContents.send('application-menu-command', 'about');
          else app.showAboutPanel();
        } }, command('settings', 'Command+,'), separator,
        role('services'), separator, role('hide'), role('hideOthers'), role('unhide'), separator, role('quit'),
      ] },
      { label: labels.file, submenu: [command('projectNew', 'CommandOrControl+N'), command('projectOpen', 'CommandOrControl+O'), command('projectSave', 'CommandOrControl+S'), command('projectSaveAs', 'CommandOrControl+Shift+S'), separator, command('import', 'CommandOrControl+I'), command('export', 'CommandOrControl+Alt+S'), separator, role('close')] },
      { label: labels.edit, submenu: [role('undo'), role('redo'), separator, role('cut'), role('copy'), role('paste'), role('selectAll')] },
      { label: labels.view, submenu: [scale('zoomIn', 'in', 'Command+Plus'), scale('zoomOut', 'out', 'Command+-'), scale('resetZoom', 'reset', 'Command+0'), separator, role('togglefullscreen')] },
      { label: labels.window, submenu: [role('minimize'), role('zoom'), separator, role('front')] },
      { role: 'help', label: labels.help, submenu: [{ label: labels.docs, click: openDocs }, command('report')] },
    ]));
  }
  return {
    rebuild,
    reset() { enabled = {}; rebuild(); },
    update(payload) {
      if (!payload || typeof payload !== 'object') return;
      if (payload.labels && typeof payload.labels === 'object') {
        for (const key of Object.keys(DEFAULT_LABELS)) {
          const value = payload.labels[key];
          if (typeof value === 'string' && value.length > 0 && value.length < 160) labels[key] = value;
        }
      }
      if (payload.commands && typeof payload.commands === 'object') {
        for (const key of COMMANDS) enabled[key] = payload.commands[key] === true;
      }
      rebuild();
    },
  };
}

module.exports = { createApplicationMenu, DEFAULT_LABELS };
