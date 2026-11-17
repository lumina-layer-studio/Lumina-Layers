import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'fs'
import { resolveApiProxyTarget, resolveDevServerConfig } from './devServerConfig'

const pkg = JSON.parse(readFileSync('./package.json', 'utf-8'))

// https://vite.dev/config/
export default defineConfig({
  define: {
    __LUMINA_VERSION__: JSON.stringify(pkg.version),
  },
  plugins: [{
    name: "lumina-state-reload",
    handleHotUpdate({ file, server }) {
      // Stores and service queues must share one module generation. Fast
      // Refresh can otherwise leave mounted consumers using the old singleton.
      if (/\/src\/(?:.*\.ts|i18n\/context\.tsx)$/.test(file)
        && !/(?:\/__tests__\/|\.test\.)/.test(file)) {
        server.ws.send({ type: "full-reload" });
        return [];
      }
    },
  }, react()],
  // Pre-bundle every external npm dependency the app uses, eagerly. Vite's
  // dep optimizer normally auto-scans entry files for imports, but the
  // discovery order and even the discovered set can vary between starts
  // (especially after the dev-server is restarted while a browser tab is
  // still open with the previous hash). When that happens the browser
  // requests files like ``@dnd-kit_core.js?v=<old hash>`` which no longer
  // exist in the freshly-pre-bundled deps directory — Vite returns 504 or
  // its SPA HTML fallback, the page goes blank.
  //
  // Listing every dep explicitly forces a stable, complete pre-bundle on
  // every cold start: every entry below appears in ``deps/_metadata.json``
  // regardless of scan order, so a refresh after a restart finds the file
  // it expects. This list mirrors what the auto-scanner currently
  // discovers; keep it in sync when adding a new top-level npm dep
  // (everything ``import``ed from a non-relative path that isn't
  // ``./*``/``../*``).
  //
  // 把应用使用的每个外部 npm 依赖都显式登记，强制每次冷启动都稳定地全量预打包。
  // Vite 默认的依赖扫描器在不同启动之间可能产生不同的依赖顺序甚至漏扫，导致
  // 旧浏览器标签按旧 hash 请求的文件在新 deps 目录里不存在，触发 504 / SPA
  // HTML 兜底 → 白屏。把每条 dep 列出可彻底消除这一不确定性。
  optimizeDeps: {
    include: [
      "@lumina/workshop-sdk",
      "@dnd-kit/core",
      "@floating-ui/react",
      "@react-three/drei",
      "@react-three/fiber",
      "axios",
      "framer-motion",
      "qrcode",
      "react",
      "react-cropper",
      "react-dom",
      "react-dom/client",
      "react/jsx-dev-runtime",
      "react/jsx-runtime",
      "read-excel-file/browser",
      "three",
      "zustand",
      "zustand/middleware",
      "zustand/react/shallow",
    ],
  },
  // Keep Vite's pre-bundle cache in one stable project-local directory.
  // Combined with the explicit optimizeDeps list above, this makes local
  // restarts deterministic and prevents stale module hashes from blanking
  // the live tab.
  // 将 Vite 预打包缓存固定在项目本地目录；配合上方显式 optimizeDeps 列表，
  // 使本地重启稳定，避免旧模块 hash 触发白屏。
  cacheDir: "node_modules/.vite",
  server: {
    ...resolveDevServerConfig(process.env),
    watch: { ignored: ["**/__tests__/**", "**/*.test.*", "**/.scratch/**"] },
    proxy: {
      "/api": {
        target: resolveApiProxyTarget(process.env),
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/setupTests.ts",
    // Memory cap: bound fork pool to avoid runaway memory when multiple
    // vitest invocations stack up (especially from concurrent agent calls).
    // Default would be `maxForks = CPU count` (~10 workers * ~1GB each).
    // Override via env LUMINA_VITEST_MAX_FORKS if a release sweep needs more.
    pool: "forks",
    maxWorkers: Number(process.env.LUMINA_VITEST_MAX_FORKS ?? 2),
  },
})
