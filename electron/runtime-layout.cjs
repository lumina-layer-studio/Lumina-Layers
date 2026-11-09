"use strict";
/**
 * Runtime layout for the desktop host.
 *
 * "dev" keeps the source workflow (repository checkout, project venv, Vite dev
 * server on 4174). "dist" is used by the packaged Windows build and by
 * `LUMINA_ELECTRON_FRONTEND=dist`: the backend serves the built frontend from
 * its own port and runs on a bundled Python runtime, so neither Node nor Vite
 * is needed at runtime.
 *
 * 桌面宿主的运行布局：dev 沿用源码开发流程；dist 用于打包版（或显式
 * LUMINA_ELECTRON_FRONTEND=dist），由后端同源托管前端构建产物、使用内置 Python。
 */
const path = require("node:path");

function isDistMode({ isPackaged, env }) {
  if (env && env.LUMINA_ELECTRON_FRONTEND === "dev") return false;
  return Boolean(isPackaged) || Boolean(env && env.LUMINA_ELECTRON_FRONTEND === "dist");
}

/**
 * @param {{ isPackaged?: boolean, resourcesPath?: string, electronDir: string, env?: Record<string,string|undefined>, platform: string }} options
 */
function resolveRuntimeLayout({ isPackaged, resourcesPath, electronDir, env = {}, platform }) {
  const dist = isDistMode({ isPackaged, env });
  const packagedRoot = isPackaged && resourcesPath ? path.join(resourcesPath, "app") : null;
  const rootDir = packagedRoot || path.join(electronDir, "..");
  const isWin = platform === "win32";
  const bundledPythonDir = isPackaged && resourcesPath ? path.join(resourcesPath, "python") : null;
  const bundledPython = bundledPythonDir
    ? (isWin ? path.join(bundledPythonDir, "python.exe") : path.join(bundledPythonDir, "bin", "python3"))
    : null;
  return {
    mode: dist ? "dist" : "dev",
    rootDir,
    frontendDistDir: env.LUMINA_FRONTEND_DIST_DIR || path.join(rootDir, "frontend", "dist"),
    pythonOverride: env.LUMINA_PYTHON || null,
    bundledPython,
  };
}

/**
 * Writable data locations for the dist build. Every directory lives under the
 * Electron userData folder so reinstalling or updating the app keeps the
 * user's settings, materials, LUTs and caches. Values already present in the
 * environment win, so power users can still redirect any of them.
 *
 * 打包版的可写目录全部放在 userData 下，重装/升级不丢数据；已有环境变量优先。
 */
function distDataEnv({ userData, env = {} }) {
  const defaults = {
    LUMINA_SERVE_FRONTEND_DIST: "1",
    LUMINA_SETTINGS_PATH: path.join(userData, "user_settings.json"),
    LUMINA_OUTPUT_DIR: path.join(userData, "output"),
    LUMINA_RUNTIME_CACHE_DIR: path.join(userData, "runtime-cache"),
    LUMINA_CUSTOM_LUT_DIR: path.join(userData, "lut", "Custom"),
    LUMINA_CLOUD_LUT_DIR: path.join(userData, "lut", "Cloud"),
    LUMINA_LOG_DIR: path.join(userData, "backend-logs"),
    LUMINA_FEEDBACK_DUMP_DIR: path.join(userData, "feedback"),
    NUMBA_CACHE_DIR: path.join(userData, "numba-cache"),
    // Personal build: keep bug reports on this computer unless the user opts in.
    LUMINA_FEEDBACK_SERVER_URL: "off",
    PYTHONUTF8: "1",
    PYTHONDONTWRITEBYTECODE: "1",
  };
  const result = {};
  for (const [key, value] of Object.entries(defaults)) {
    result[key] = env[key] ? env[key] : value;
  }
  return result;
}

module.exports = { isDistMode, resolveRuntimeLayout, distDataEnv };
