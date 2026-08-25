import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

// ── Tauri Bridge: wire window.electron to tauriBridge.invoke() ──────
// In Tauri desktop mode, legacy components reference window.electron.
// We bridge them to the Tauri invoke() API so everything works unchanged.
// NOTE: Do NOT use top-level await here — it blocks React mount and causes
// a white flash. Instead, fire-and-forget the dynamic import.
if (typeof __TAURI_INTERNALS__ !== "undefined") {
  import("@/api/tauriBridge").then((mod) => {
    const isAndroid = /Android/i.test(navigator.userAgent);
    const {
      store: tauriStore,
      window: tauriWindow,
      backend: tauriBackend,
      tray: tauriTray,
      shortcuts: tauriShortcuts,
      updater: tauriUpdater,
      voice: tauriVoice,
      platform: tauriPlatform,
    } = mod;

    const mobileWindow = {
      minimize: async () => false,
      toggleMaximize: async () => false,
      close: async () => false,
      isMaximized: async () => false,
    };
    const mobileBackend = {
      status: async () => ({ running: false, port: null }),
      logs: async () => [],
      start: async () => ({ ok: false, port: null }),
      stop: async () => ({ ok: true }),
      restart: async () => ({ ok: false, port: null }),
      health: async () => ({ healthy: false, reason: "Android 使用远程服务" }),
    };
    const mobileUpdater = {
      getStatus: async () => ({ status: "not-available", info: null, progress: null, error: "Android APK 暂不支持桌面自动更新", autoDownload: false, autoInstallOnAppQuit: false, currentVersion: "0.3.0", isPackaged: true }),
      check: async () => ({ status: "not-available", info: null, progress: null, error: "Android APK 暂不支持桌面自动更新", autoDownload: false, autoInstallOnAppQuit: false, currentVersion: "0.3.0", isPackaged: true }),
      download: async () => ({ status: "not-available", info: null, progress: null, error: "Android APK 暂不支持桌面自动更新", autoDownload: false, autoInstallOnAppQuit: false, currentVersion: "0.3.0", isPackaged: true }),
      install: async () => ({ ok: false }),
      setAutoDownload: async () => ({ status: "not-available" }),
      setAutoInstallOnAppQuit: async () => ({ status: "not-available" }),
    };
    const mobileVoice = {
      status: async () => ({ running: false, pid: null, startedAt: null, lastError: "Android 暂不支持桌面 Celia 进程" }),
      startCelia: async () => ({ ok: false, running: false, pid: null, error: "Android 暂不支持桌面 Celia 进程" }),
      stopCelia: async () => ({ ok: true, running: false, pid: null, error: null }),
    };

    (window as any).electron = {
      store: tauriStore,
      window: isAndroid ? mobileWindow : tauriWindow,
      backend: {
        ...(isAndroid ? mobileBackend : tauriBackend),
        restart: async () => {
          if (isAndroid) return { ok: false, port: null, error: "Android 使用远程服务", logPath: null };
          try {
            const r = await tauriBackend.restart();
            return { ok: r.ok, port: r.port, error: null, logPath: null };
          } catch (e: any) {
            return { ok: false, port: null, error: e?.message || String(e), logPath: null };
          }
        },
      },
      tray: {
        ...(isAndroid
          ? {
              getConfig: async () => ({ enabled: false, minimizeToTray: false }),
              setEnabled: async () => ({ enabled: false, minimizeToTray: false }),
              setMinimizeToTray: async () => ({ enabled: false, minimizeToTray: false }),
            }
          : tauriTray),
        onNewChat: (_cb: () => void) => () => {},
      },
      shortcuts: isAndroid
        ? {
            getConfig: async () => ({ accelerator: "", default: "" }),
            setAccelerator: async () => ({ ok: false, error: "Android 不支持全局快捷键" }),
            validate: async () => ({ valid: false }),
          }
        : tauriShortcuts,
      updater: {
        ...(isAndroid ? mobileUpdater : tauriUpdater),
        onStatusChange: (_cb: (s: any) => void) => () => {},
      },
      voice: isAndroid ? mobileVoice : tauriVoice,
      // Tauri doesn't ship @types/node; use a literal union matching
      // tauriBridge.platform.os() return values instead of NodeJS.Platform.
      platform: (isAndroid ? "android" : tauriPlatform.os()) as "aix" | "android" | "darwin" | "freebsd" | "linux" | "openbsd" | "sunos" | "win32" | "unknown",
      versions: {
        electron: "tauri-v2",
        chrome: navigator.userAgent.match(/Chrome\/(\d+)/)?.[1] || "unknown",
        node: "tauri",
      },
    };

    console.log("[Tauri] window.electron bridge installed");
  });
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
