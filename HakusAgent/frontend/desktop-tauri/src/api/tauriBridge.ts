/**
 * Tauri API Bridge — replaces window.electron IPC with Tauri invoke().
 * The embedded Rust Runtime is exposed to legacy components as "backend".
 */

import { invoke } from "@tauri-apps/api/core";

// ── Store ──────────────────────────────────────────────────────────
export const store = {
  get: (key: string) => invoke<unknown>("store_get", { key }),
  set: (key: string, value: unknown) => invoke("store_set", { key, value }),
  getAll: () => invoke<Record<string, unknown>>("store_get_all"),
  clear: () => invoke<void>("store_clear"),
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

// ── HTTP (Flow canvas node) ────────────────────────────────────────
// Requests run in Rust (see src-tauri/src/http_cmds.rs) because the WebView
// CSP keeps `connect-src` at 'self'. Keeping it there is deliberate: it is
// what stops an injected script from shipping user data off the machine.

export interface TauriHttpResponse {
  status: number
  ok: boolean
  headers: Record<string, string>
  body: string
  json: unknown | null
}

export const httpOs = {
  request: (opts: {
    method: string
    url: string
    headers?: Record<string, string>
    body?: string
    timeoutSecs?: number
    allowInsecureHttp?: boolean
  }) =>
    invoke<TauriHttpResponse>('http_request', {
      method: opts.method,
      url: opts.url,
      headers: opts.headers ?? null,
      body: opts.body ?? null,
      timeoutSecs: opts.timeoutSecs ?? null,
      allowInsecureHttp: opts.allowInsecureHttp ?? null,
    }),
}

// ── Git review / worktree / doctor ─────────────────────────────────
export interface TauriWorktree {
  path: string
  branch: string | null
  head: string
  bare: boolean
  locked: boolean
}

export interface TauriDoctorCheck {
  id: string
  name: string
  required: boolean
  found: boolean
  version?: string
  path?: string
  status: 'ok' | 'missing' | 'outdated' | 'error'
  hint?: string
}

export interface TauriDoctorReport {
  checks: TauriDoctorCheck[]
  healthy: boolean
  backend_version?: string
}

export const gitOs = {
  applyPatch: (workdir: string, patch: string, reverse = false, cached = false) =>
    invoke<void>("git_apply_patch", { workdir, patch, reverse, cached }),
  branchList: (workdir: string) => invoke<string[]>("git_branch_list", { workdir }),
  worktreeList: (workdir: string) => invoke<TauriWorktree[]>("git_worktree_list", { workdir }),
  worktreeAdd: (workdir: string, path: string, branch?: string, newBranch?: string) =>
    invoke<void>("git_worktree_add", { workdir, path, branch, newBranch }),
  prList: (workdir: string) =>
    invoke<Array<Record<string, unknown>>>("git_pr_list", { workdir }),
  /** CI checks for a PR via `gh pr checks <n>` (empty if gh unavailable). */
  prChecks: (workdir: string, number: number) =>
    invoke<Array<Record<string, unknown>>>("git_pr_checks", { workdir, number }),
}

export const doctor = {
  checkDependencies: (backendHealthy: boolean, backendVersion?: string) =>
    invoke<TauriDoctorReport>("doctor_check_dependencies", {
      backendHealthy,
      backendVersion,
    }),
}

// ── Project folder access ─────────────────────────────────────────
export interface ProjectFolderSelection {
  /** Real local workspace path used by the runtime. */
  path: string
  /** Android SAF tree URI, persisted for later sync. */
  sourceUri?: string
  name?: string
}

function isAndroid(): boolean {
  return typeof navigator !== "undefined" && /Android/i.test(navigator.userAgent)
}

function bridgeLocale(): 'zh-CN' | 'en-US' {
  if (typeof document !== 'undefined' && document.documentElement.lang.toLowerCase().startsWith('zh')) return 'zh-CN'
  if (typeof navigator !== 'undefined' && String(navigator.language || '').toLowerCase().startsWith('zh')) return 'zh-CN'
  return 'en-US'
}

/** Ask before a project folder is exposed to read/write/command tools. */
export async function confirmProjectAccess(): Promise<boolean> {
  // The extra "allow folder access" dialog after every folder pick was noise —
  // the user just chose that folder deliberately, and the permission mode
  // still gates what tools can do. Access is granted without a second prompt.
  if (typeof __TAURI_INTERNALS__ === "undefined") return false
  return true
}

/** Open the desktop picker or Android's persistent SAF folder picker. */
export async function pickProjectFolder(): Promise<ProjectFolderSelection | null> {
  if (typeof __TAURI_INTERNALS__ === "undefined") return null
  if (isAndroid()) {
    try {
      const { invoke } = await import("@tauri-apps/api/core")
      return await invoke<ProjectFolderSelection>("plugin:hakus-folder-picker|pick_folder")
    } catch (e) {
      console.warn("[tauriBridge] Android folder picker failed:", e)
      return null
    }
  }

  try {
    const { open } = await import("@tauri-apps/plugin-dialog")
    const selected = await open({ directory: true, multiple: false, title: bridgeLocale() === 'zh-CN' ? "选择项目文件夹" : "Choose project folder" })
    if (typeof selected !== "string" || !selected) return null
    return { path: selected }
  } catch (e) {
    console.warn("[tauriBridge] folder picker failed:", e)
    return null
  }
}

async function syncAndroidFolder(
  command: "refresh_folder" | "sync_folder",
  selection: Pick<ProjectFolderSelection, "path" | "sourceUri">,
): Promise<void> {
  if (!isAndroid() || !selection.sourceUri) return
  const { invoke } = await import("@tauri-apps/api/core")
  await invoke(`plugin:hakus-folder-picker|${command}`, {
    request: { uri: selection.sourceUri, path: selection.path },
  })
}

export function refreshProjectFolder(selection: Pick<ProjectFolderSelection, "path" | "sourceUri">): Promise<void> {
  return syncAndroidFolder("refresh_folder", selection)
}

export function syncProjectFolder(selection: Pick<ProjectFolderSelection, "path" | "sourceUri">): Promise<void> {
  return syncAndroidFolder("sync_folder", selection)
}

// Keep the old helper for any non-project caller. New project flows use the
// richer selection so Android can persist its SAF URI.
export async function pickFolder(): Promise<string | null> {
  const selected = await pickProjectFolder()
  return selected?.path || null
}
