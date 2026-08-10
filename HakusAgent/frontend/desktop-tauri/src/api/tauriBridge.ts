/**
 * Tauri API Bridge — replaces window.electron IPC with Tauri invoke().
 *
 * NO "backend" naming anywhere. The Python server is called "backend".
 * NO connection error banners — if the backend isn't ready, we just wait.
 */

import { invoke } from "@tauri-apps/api/core";

// ── Store ──────────────────────────────────────────────────────────
export const store = {
  get: (key: string) => invoke<unknown>("store_get", { key }),
  set: (key: string, value: unknown) => invoke("store_set", { key, value }),
  getAll: () => invoke<Record<string, unknown>>("store_get_all"),
};

// ── Window ─────────────────────────────────────────────────────────
export const window = {
  minimize: () => invoke<boolean>("window_minimize"),
  toggleMaximize: () => invoke<boolean>("window_toggle_maximize"),
  close: () => invoke<boolean>("window_close"),
  isMaximized: () => invoke<boolean>("window_is_maximized"),
};

// ── Backend (was "backend" — NEVER use that word again) ───────────
export const backend = {
  status: () =>
    invoke<{ running: boolean; port: number | null }>("backend_status"),
  logs: () => invoke<string[]>("backend_logs"),
  start: () =>
    invoke<{ ok: boolean; port: number | null }>("backend_start"),
  stop: () => invoke<{ ok: boolean }>("backend_stop"),
  restart: () =>
    invoke<{ ok: boolean; port: number | null }>("backend_restart"),
  health: () =>
    invoke<{ healthy: boolean; port?: number; reason?: string }>(
      "backend_health",
    ),
};

// ── Tray ───────────────────────────────────────────────────────────
export const tray = {
  getConfig: () =>
    invoke<{ enabled: boolean; minimizeToTray: boolean }>("tray_get_config"),
  setEnabled: (enabled: boolean) =>
    invoke<{ enabled: boolean; minimizeToTray: boolean }>("tray_set_enabled", {
      enabled,
    }),
  setMinimizeToTray: (enabled: boolean) =>
    invoke<{ enabled: boolean; minimizeToTray: boolean }>(
      "tray_set_minimize_to_tray",
      { enabled },
    ),
};

// ── Shortcuts ──────────────────────────────────────────────────────
export const shortcuts = {
  getConfig: () =>
    invoke<{ accelerator: string; default: string }>("shortcuts_get_config"),
  setAccelerator: (accelerator: string) =>
    invoke<{ ok: boolean; accelerator?: string; error?: string }>(
      "shortcuts_set_accelerator",
      { accelerator },
    ),
  validate: (accelerator: string) =>
    invoke<{ valid: boolean }>("shortcuts_validate", { accelerator }),
};

// ── Platform info ──────────────────────────────────────────────────
export const platform = {
  os: () => {
    if (typeof navigator !== "undefined") {
      const ua = navigator.userAgent.toLowerCase();
      if (ua.includes("mac")) return "darwin";
      if (ua.includes("win")) return "win32";
      if (ua.includes("linux")) return "linux";
    }
    return "unknown";
  },
};

// ── Updater ────────────────────────────────────────────────────────
export const updater = {
  getStatus: () => invoke("updater_get_status"),
  check: () => invoke("updater_check"),
  download: () => invoke("updater_download"),
  install: () => invoke("updater_install"),
  setAutoDownload: (enabled: boolean) =>
    invoke("updater_set_auto_download", { enabled }),
  setAutoInstallOnAppQuit: (enabled: boolean) =>
    invoke("updater_set_auto_install_on_app_quit", { enabled }),
};

// ── Voice ──────────────────────────────────────────────────────────
export const voice = {
  status: () => invoke("voice_status"),
  startCelia: (options?: Record<string, unknown>) =>
    invoke("voice_start_celia", { options }),
  stopCelia: () => invoke("voice_stop_celia"),
};
