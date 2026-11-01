import { useEffect } from "react";
import { useSettingsStore } from "../stores/settingsStore";

interface ElectronAPI {
  platform?: string;
  alignTrafficLights?: (centerY: number, controlsHeight: number) => Promise<null>;
  setTitlebarTheme?: (theme: "light" | "dark", scrimmed?: boolean) => void;
  setApplicationMenuState?: (state: { commands?: Record<string, boolean>; labels?: Record<string, string> }) => void;
  onApplicationMenuCommand?: (listener: (command: string) => void) => () => void;
  setLanguage: (lang: string) => void;
  getAppVersion: () => Promise<string>;
  getNativeBedModel?: (
    deviceProfileId: string,
  ) => Promise<ArrayBuffer | Uint8Array | null>;
  pickWorkshopImage?: () => Promise<{
    name: string;
    mimeType: string;
    bytes: ArrayBuffer | Uint8Array;
  } | null>;
  setGeneratedFileDirectory?: (
    directory: string,
  ) => Promise<{ status: string; directory?: string }>;
  pickGeneratedFileDirectory?: () => Promise<{
    status: "selected" | "canceled" | "error";
    directory?: string;
    code?: string;
  }>;
  getInterfaceScale?: () => Promise<InterfaceScaleResult>;
  setInterfaceScale?: (preference: string) => Promise<InterfaceScaleResult>;
  onInterfaceScaleChanged?: (
    listener: (payload: { preference: string }) => void,
  ) => () => void;
}

type InterfaceScaleResult =
  | { status: "ok"; preference: string }
  | { status: "error"; code: string };

export const electronAPI: ElectronAPI | null =
  (window as unknown as { electronAPI?: ElectronAPI }).electronAPI ?? null;

/**
 * Interface scales the desktop host accepts, smallest first. Each one is a
 * direct multiple of the size the system gives the page, so 100% matches the
 * other apps on the same screen.
 * 桌面版可选的界面缩放，从小到大。每档都是系统给页面的尺寸的直接倍数，100% 与同屏其他软件一样大。
 */
export const INTERFACE_SCALE_PREFERENCES = [
  "80",
  "90",
  "100",
  "110",
  "125",
  "150",
  "175",
] as const;

export type InterfaceScalePreference =
  (typeof INTERFACE_SCALE_PREFERENCES)[number];

export function isInterfaceScalePreference(
  value: unknown,
): value is InterfaceScalePreference {
  return (
    typeof value === "string" &&
    (INTERFACE_SCALE_PREFERENCES as readonly string[]).includes(value)
  );
}

/**
 * Whether this runtime lets the page choose the interface scale (desktop only;
 * browsers keep their own zoom).
 * 当前运行环境是否支持选择界面缩放（仅桌面版，浏览器使用自带缩放）。
 */
export function canChooseInterfaceScale(): boolean {
  return typeof electronAPI?.setInterfaceScale === "function";
}

function interfaceScaleFrom(
  result: InterfaceScaleResult | undefined,
): InterfaceScalePreference {
  if (result?.status === "ok" && isInterfaceScalePreference(result.preference)) {
    return result.preference;
  }
  throw new Error(result?.status === "error" ? result.code : "unavailable");
}

/**
 * Read the saved interface scale; throws when the desktop host refuses.
 * 读取已保存的界面缩放；桌面主进程拒绝时抛错。
 */
export async function getInterfaceScale(): Promise<InterfaceScalePreference> {
  return interfaceScaleFrom(await electronAPI?.getInterfaceScale?.());
}

/**
 * Apply and save an interface scale; resolves to the scale now in effect.
 * 应用并保存界面缩放，返回当前生效的档位。
 */
export async function setInterfaceScale(
  preference: InterfaceScalePreference,
): Promise<InterfaceScalePreference> {
  return interfaceScaleFrom(await electronAPI?.setInterfaceScale?.(preference));
}

/**
 * Follow scale changes made elsewhere, such as the Ctrl +/-/0 shortcuts.
 * 跟随其他途径（如 Ctrl 加减号、Ctrl 0 快捷键）带来的缩放变化。
 */
export function onInterfaceScaleChanged(
  listener: (preference: InterfaceScalePreference) => void,
): () => void {
  const unsubscribe = electronAPI?.onInterfaceScaleChanged?.(({ preference }) => {
    if (isInterfaceScalePreference(preference)) listener(preference);
  });
  return unsubscribe ?? (() => {});
}

export function useElectronLanguageSync(): void {
  useEffect(() => {
    if (!electronAPI) return;

    const language = useSettingsStore.getState().language;
    electronAPI.setLanguage(language);

    const unsub = useSettingsStore.subscribe((state, prev) => {
      if (state.language !== prev.language) {
        electronAPI?.setLanguage(state.language);
      }
    });

    return unsub;
  }, []);
}

/**
 * Whether this runtime can choose a default folder for generated-file dialogs.
 * 当前运行环境是否支持选择生成文件保存对话框的默认文件夹（仅桌面版）。
 */
export function canPickGeneratedFileDirectory(): boolean {
  return typeof electronAPI?.pickGeneratedFileDirectory === "function";
}

/**
 * Open the native folder picker; return null on cancel and throw on failure.
 * 打开系统文件夹选择器；取消时返回 null，失败时抛错供界面显示提示。
 */
export async function pickGeneratedFileDirectory(): Promise<string | null> {
  const result = await electronAPI?.pickGeneratedFileDirectory?.();
  if (result?.status === "error") {
    throw new Error(result.code ?? "dialog-failed");
  }
  return result?.status === "selected" && result.directory ? result.directory : null;
}

/**
 * Keep the desktop main process in sync with the saved default folder.
 * 将设置中的默认保存文件夹同步给桌面主进程。
 */
export function useElectronGeneratedFileDirectorySync(): void {
  useEffect(() => {
    const setDirectory = electronAPI?.setGeneratedFileDirectory;
    if (!setDirectory) return;
    const push = (directory: string) => {
      void setDirectory(directory).catch(() => {
        // Best effort: the dialog falls back to the OS default folder.
      });
    };
    push(useSettingsStore.getState().generatedFileDirectory);
    return useSettingsStore.subscribe((state, prev) => {
      if (state.generatedFileDirectory !== prev.generatedFileDirectory) {
        push(state.generatedFileDirectory);
      }
    });
  }, []);
}
