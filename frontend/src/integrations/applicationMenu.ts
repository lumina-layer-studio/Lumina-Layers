import { useEffect, useLayoutEffect, useRef } from 'react';
import { useSettingsStore } from '../stores/settingsStore';
import { translations } from '../i18n/translations';
import { electronAPI } from './electron';

type MenuCommand = 'about' | 'settings' | 'import' | 'export' | 'report' | 'projectNew' | 'projectOpen' | 'projectSave' | 'projectSaveAs';
const handlers = new Map<MenuCommand, () => void>();

function publishCommands(): void {
  electronAPI?.setApplicationMenuState?.({
    commands: Object.fromEntries(Array.from(handlers.keys(), key => [key, true])),
  });
}

/** Register only actions available in the mounted workflow, using its existing handler. */
export function useApplicationMenuCommand(command: MenuCommand, handler: () => void, enabled = true): void {
  const latest = useRef(handler);
  useLayoutEffect(() => { latest.current = handler; });
  useEffect(() => {
    if (!enabled || !electronAPI?.onApplicationMenuCommand) return;
    const invoke = () => latest.current();
    handlers.set(command, invoke);
    const importListener = () => {
      if (handlers.get(command) === invoke) invoke();
    };
    if (command === 'import') window.addEventListener('lumina-menu-import', importListener);
    const unsubscribe = electronAPI.onApplicationMenuCommand(value => {
      if (value === command && handlers.get(command) === invoke) invoke();
    });
    publishCommands();
    return () => {
      unsubscribe();
      if (command === 'import') window.removeEventListener('lumina-menu-import', importListener);
      if (handlers.get(command) === invoke) handlers.delete(command);
      publishCommands();
    };
  }, [command, enabled]);
}

export function useApplicationMenuLanguage(): void {
  const language = useSettingsStore(state => state.language);
  useEffect(() => {
    const labels = Object.fromEntries(Object.entries(translations)
      .filter(([key]) => key.startsWith('desktop_menu_'))
      .map(([key, value]) => [key.slice('desktop_menu_'.length), value[language]]));
    electronAPI?.setApplicationMenuState?.({ labels });
  }, [language]);
}
