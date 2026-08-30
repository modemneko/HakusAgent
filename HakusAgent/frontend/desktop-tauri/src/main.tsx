import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import {
  backend as tauriBackend,
  platform as tauriPlatform,
  shortcuts as tauriShortcuts,
  store as tauriStore,
  tray as tauriTray,
  updater as tauriUpdater,
  voice as tauriVoice,
  window as tauriWindow,
} from "@/api/tauriBridge";

const isAndroidRuntime =
  typeof navigator !== "undefined" && /Android/i.test(navigator.userAgent);

// ── Tauri Bridge: wire window.electron to tauriBridge.invoke() ──────
// In Tauri desktop mode, legacy components reference window.electron.
// We bridge them to the Tauri invoke() API so everything works unchanged.
// Install the bridge before React mounts. Settings are loaded from the bridge
// during the first effect; a lazy dynamic import could race that effect and
// send the first read/write to the browser-only localStorage fallback.
if (typeof __TAURI_INTERNALS__ !== "undefined") {
  const isAndroid = isAndroidRuntime;

    const mobileWindow = {
      minimize: async () => false,
      toggleMaximize: async () => false,
      close: async () => false,
      isMaximized: async () => false,
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
        ...tauriBackend,
        restart: async () => {
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
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
