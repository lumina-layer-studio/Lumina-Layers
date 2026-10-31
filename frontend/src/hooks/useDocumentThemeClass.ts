import { useLayoutEffect } from "react";
import { useSettingsStore } from "../stores/settingsStore";
import { electronAPI } from "../integrations/electron";
import { useModalOpen } from "./useModalOpen";

/**
 * Mirror the persisted theme onto the root element's ``dark`` class.
 * 将持久化的主题同步到根元素的 dark 类。
 *
 * Must stay mounted for the whole app lifetime; the theme switch itself
 * lives in a collapsible header menu that is not always rendered. A layout
 * effect sets the class before first paint and before any child's passive
 * effect, which can read it (the five-color canvas draws on mount).
 * 需在应用整个生命周期内保持挂载；主题开关位于可折叠的顶栏菜单中，并非一直渲染。
 * 使用 layout effect，保证在首次绘制和任何子组件的普通 effect 之前设置好该类
 * （五色查询画布在挂载时就会读取它来绘制）。
 *
 * On Windows the native window buttons sit above the page, so a modal's scrim
 * cannot cover them; the title bar is told to blend into the scrim while one
 * is open.
 * Windows 原生窗口按钮画在页面之上，弹窗遮罩盖不住；有弹窗时让按钮区与遮罩同色。
 */
export function useDocumentThemeClass(): void {
  const theme = useSettingsStore((s) => s.theme);
  const modalOpen = useModalOpen(electronAPI?.platform === "win32");

  useLayoutEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  useLayoutEffect(() => {
    if (electronAPI?.platform === "win32") electronAPI.setTitlebarTheme?.(theme, modalOpen);
  }, [theme, modalOpen]);
}
