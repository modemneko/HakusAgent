/**
 * Tauri API Bridge — replaces window.electron IPC with Tauri invoke().
 * The Python server is called "backend".
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

// ── Backend ────────────────────────────────────────────────────────
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

// ── Dialog (folder picker for project creation) ───────────────────
/**
 * Open the native OS folder picker and return the selected path, or
 * null if the user cancelled.
 *
 * Uses dynamic import so the dialog plugin is only loaded when the
 * user actually clicks "新建项目" — this keeps the initial bundle
 * smaller and means web-mode (non-Tauri) doesn't crash on import.
 */
export async function pickFolder(): Promise<string | null> {
  if (typeof __TAURI_INTERNALS__ === "undefined") return null;
  try {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const selected = await open({
      directory: true,
      multiple: false,
      title: "选择项目文件夹",
    });
    if (typeof selected !== "string" || !selected) return null;
    return selected;
  } catch (e) {
    console.warn("[tauriBridge] folder picker failed:", e);
    return null;
  }
}
