import { create } from "zustand";
import { clearCache as clearCacheApi } from "../api/system";

// ========== State Interface ==========

export interface AboutState {
  loading: boolean;
  notification: { type: "success" | "error"; message: string } | null;
}

// ========== Actions Interface ==========

export interface AboutActions {
  clearCache: () => Promise<void>;
  dismissNotification: () => void;
}

// ========== Default State ==========

const DEFAULT_STATE: AboutState = {
  loading: false,
  notification: null,
};

// ========== Store ==========

export const useAboutStore = create<AboutState & AboutActions>((set) => ({
  ...DEFAULT_STATE,

  clearCache: async () => {
    set({ loading: true, notification: null });
    try {
      const response = await clearCacheApi();
      const freed =
        response.freed_bytes >= 1024 * 1024
          ? `${(response.freed_bytes / (1024 * 1024)).toFixed(1)} MB`
          : response.freed_bytes >= 1024
            ? `${(response.freed_bytes / 1024).toFixed(1)} KB`
            : `${response.freed_bytes} B`;
      set({
        loading: false,
        notification: {
          type: "success",
          message: `清理完成，共删除 ${response.deleted_files} 个文件，腾出 ${freed} 空间`,
        },
      });
    } catch (err) {
      set({
        loading: false,
        notification: {
          type: "error",
          message:
            err instanceof Error ? err.message : "缓存清理失败，请重试",
        },
      });
    }
    // 3 秒后自动消除通知
    setTimeout(() => {
      set({ notification: null });
    }, 3000);
  },

  dismissNotification: () => set({ notification: null }),
}));
