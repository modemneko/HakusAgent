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

    (window as any).electron = {
      store: tauriStore,
      window: tauriWindow,
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
        ...tauriTray,
        onNewChat: (_cb: () => void) => () => {},
      },
      shortcuts: tauriShortcuts,
      updater: {
        ...tauriUpdater,
        onStatusChange: (_cb: (s: any) => void) => () => {},
      },
      voice: tauriVoice,
      // Tauri doesn't ship @types/node; use a literal union matching
      // tauriBridge.platform.os() return values instead of NodeJS.Platform.
      platform: tauriPlatform.os() as "aix" | "darwin" | "freebsd" | "linux" | "openbsd" | "sunos" | "win32" | "unknown",
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
