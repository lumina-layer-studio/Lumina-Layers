const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  platform: process.platform,
  projects: {
    ready: () => ipcRenderer.invoke('projects-ready'),
    progress: (id, state) => ipcRenderer.invoke('projects-progress', id, state),
    setDirty: (dirty) => ipcRenderer.invoke('projects-dirty', dirty),
    closeAnswer: (id, accepted) => ipcRenderer.invoke('projects-close-answer', id, accepted),
    onClose: (listener) => {
      const handler = (_event, id) => listener(id);
      ipcRenderer.on('project-close-request', handler);
      return () => ipcRenderer.removeListener('project-close-request', handler);
    },
    open: (requestId) => ipcRenderer.invoke('projects-open', requestId),
    openEntry: (fileEntryId) => ipcRenderer.invoke('projects-open-entry', fileEntryId),
    complete: (requestId, state, metadata) => ipcRenderer.invoke('projects-complete', requestId, state, metadata),
    save: (payload) => ipcRenderer.invoke('projects-save', payload),
    catalog: () => ipcRenderer.invoke('projects-catalog'),
    updateEntry: (id, change) => ipcRenderer.invoke('projects-update-entry', id, change),
    onOpen: (listener) => {
      const forward = (_event, value) => listener(value);
      ipcRenderer.on('project-open', forward);
      return () => ipcRenderer.removeListener('project-open', forward);
    },
  },
  alignTrafficLights: (centerY, controlsHeight) => ipcRenderer.invoke("align-traffic-lights", centerY, controlsHeight),
  setTitlebarTheme: (theme, scrimmed) => ipcRenderer.send("set-titlebar-theme", theme, scrimmed === true),
  setApplicationMenuState: (state) => ipcRenderer.send("application-menu-state", state),
  onApplicationMenuCommand: (listener) => {
    const forward = (_event, command) => listener(command);
    ipcRenderer.on("application-menu-command", forward);
    return () => ipcRenderer.removeListener("application-menu-command", forward);
  },
  saveGeneratedFile: (payload) => ipcRenderer.invoke("save-generated-file", payload),
  setGeneratedFileDirectory: (directory) =>
    ipcRenderer.invoke("set-generated-file-directory", directory),
  pickGeneratedFileDirectory: () =>
    ipcRenderer.invoke("pick-generated-file-directory"),
  getInterfaceScale: () => ipcRenderer.invoke("get-interface-scale"),
  setInterfaceScale: (preference) =>
    ipcRenderer.invoke("set-interface-scale", preference),
  onInterfaceScaleChanged: (listener) => {
    const forward = (_event, payload) => listener(payload);
    ipcRenderer.on("interface-scale-changed", forward);
    return () => ipcRenderer.removeListener("interface-scale-changed", forward);
  },
  setLanguage: (lang) => ipcRenderer.send("set-language", lang),
  getAppVersion: () => ipcRenderer.invoke("get-app-version"),
  getNativeBedModel: (deviceProfileId) =>
    ipcRenderer.invoke("get-native-bed-model", deviceProfileId),
  getWorkshopRuntimeMode: () =>
    ipcRenderer.invoke("get-workshop-runtime-mode"),
  openWiki: (url) => ipcRenderer.invoke("open-wiki", url),
  openGradientModel: (url) => ipcRenderer.invoke("open-gradient-model", url),
  pickWorkshopImage: () =>
    ipcRenderer.invoke("pick-workshop-image"),
});
