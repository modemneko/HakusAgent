import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

// ── Tauri Bridge: wire window.electron to tauriBridge.invoke() ──────
// In Tauri desktop mode, legacy components reference window.electron.
// We bridge them to the Tauri invoke() API so everything works unchanged.
if (typeof __TAURI_INTERNALS__ !== "undefined") {
  // Lazy import to avoid circular deps and only load in Tauri context
  const {
    store: tauriStore,
    window: tauriWindow,
    backend: tauriBackend,
    tray: tauriTray,
    shortcuts: tauriShortcuts,
    updater: tauriUpdater,
    voice: tauriVoice,
    platform: tauriPlatform,
  } = await import("@/api/tauriBridge");

  (window as any).electron = {
    store: tauriStore,
    window: tauriWindow,
    backend: {
      ...tauriBackend,
      // Legacy Electron API had restart returning { ok, port, error, logPath }
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
      ...tauriTray,
      // Legacy onNewChat — handled by Tauri event listener in App.tsx
      onNewChat: (_cb: () => void) => () => {},
    },
    shortcuts: tauriShortcuts,
    updater: {
      ...tauriUpdater,
      onStatusChange: (_cb: (s: any) => void) => () => {},
    },
    voice: tauriVoice,
    platform: tauriPlatform.os() as NodeJS.Platform,
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
