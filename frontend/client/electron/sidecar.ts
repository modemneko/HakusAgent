/**
 * HakusAI Python backend sidecar manager.
 *
 * When the Electron app is packaged with `extraResources: sidecar/`,
 * a PyInstaller-built `hakusai-server` binary is shipped alongside
 * the app. This module spawns it on startup and parses its stdout
 * to discover the chosen port (the server prints `HAKUSAI_PORT=8080`).
 *
 * In dev mode, if a Python interpreter and the project source are available,
 * the sidecar is launched directly from src/hakusai_server via a small wrapper
 * script. This avoids the slow PyInstaller one-file extraction and makes the
 * dev loop much faster. If neither source nor a bundled binary is available,
 * the client falls back to connecting to a separately-running server
 * (default: http://127.0.0.1:48081).
 *
 * Diagnostics:
 *   - All stdout/stderr from the sidecar is tee'd to:
 *       <userData>/sidecar.log
 *     so users can debug startup failures.
 *   - startSidecar() waits up to 30s for the HTTP /health endpoint
 *     to respond, and returns a structured result so the renderer
 *     can show a specific error (sidecar crashed vs port in use vs
 *     just slow to boot).
 */

import { spawn, type ChildProcess } from 'node:child_process'
import { join } from 'node:path'
import {
  existsSync,
  mkdirSync,
  appendFileSync,
  createWriteStream,
  statSync,
  renameSync,
  unlinkSync,
  type WriteStream,
  type Stats,
} from 'node:fs'
import { app } from 'electron'

let sidecarProcess: ChildProcess | null = null
let detectedPort: number | null = null
let logStream: WriteStream | null = null
let lastError: string | null = null
let lastExitCode: number | null = null

export interface SidecarStatus {
  available: boolean
  running: boolean
  port: number | null
  pid: number | null
  lastError: string | null
  lastExitCode: number | null
  logPath: string | null
  binaryPath: string | null
}

/** Path to the bundled sidecar binary, or null if not present. */
function getSidecarPath(): string | null {
  let dir: string
  if (app.isPackaged) {
    // In production: <Resources>/sidecar/dist/
    dir = join(process.resourcesPath, 'sidecar', 'dist')
  } else {
    // In dev: <client>/sidecar/dist/
    dir = join(__dirname, '..', 'sidecar', 'dist')
  }

  const candidates =
    process.platform === 'win32'
      ? ['hakusai-server.exe']
      : ['hakusai-server', 'hakusai-server.bin']

  for (const name of candidates) {
    const p = join(dir, name)
    if (existsSync(p)) return p
  }
  return null
}

export function isSidecarAvailable(): boolean {
  return getSidecarPath() !== null
}

/** Detect whether we can run the sidecar from Python source in dev mode. */
function getDevSourceSidecar(): { command: string; args: string[]; cwd: string; env?: Record<string, string> } | null {
  if (app.isPackaged) return null

  // Project layout: frontend/client/electron/sidecar.ts -> ../../../src
  const repoRoot = join(__dirname, '..', '..', '..')
  const srcDir = join(repoRoot, 'src')
  const serverPy = join(srcDir, 'hakusai_server', 'server.py')
  if (!existsSync(serverPy)) return null

  // Try to locate python/python3 on PATH. Use `python -m` so that
  // server.py's `if __name__ == "__main__"` block runs and prints HAKUSAI_PORT.
  // The RuntimeWarning from hakusai_server/__init__.py re-exporting .server is
  // harmless in dev mode.
  const pythonCmd = process.platform === 'win32' ? 'python' : 'python3'
  return {
    command: pythonCmd,
    args: ['-m', 'hakusai_server.server'],
    cwd: srcDir,
    // hakus/ and utils/ live at the repo root, not under src/. Add
    // both to PYTHONPATH so `from hakus.agent import AgentCore` and
    // `from utils.config import BASE_CONFIG` resolve correctly.
    env: {
      PYTHONPATH: [repoRoot, srcDir].join(process.platform === 'win32' ? ';' : ':'),
    },
  }
}

/** Resolve the command to spawn.
 *
 * Dev mode: prefer Python source (fast, no PyInstaller extraction) if available;
 * fall back to the bundled binary for quick smoke tests of the packaged build.
 * Production: always use the bundled binary.
 */
function getSidecarCommand(): { command: string; args: string[]; cwd?: string; env?: Record<string, string> } | null {
  if (!app.isPackaged) {
    const devSource = getDevSourceSidecar()
    if (devSource) return devSource
  }
  const binPath = getSidecarPath()
  if (binPath) {
    return { command: binPath, args: [] }
  }
  return null
}

export function isSidecarLaunchable(): boolean {
  return getSidecarCommand() !== null
}

/** Open a persistent log file under the user's userData directory. */
function getLogPath(): string {
  return join(app.getPath('userData'), 'sidecar.log')
}

// ============================================================================
// Phase 5c: Log rotation — 防止 sidecar.log 无限增长
// ============================================================================
//
// 5h SWE 任务期间, sidecar 会产生大量日志 (LLM 调用 / 工具调用 / checkpoint
// 等)。没有 rotation 的话, log 文件会涨到几个 GB, 把磁盘塞满。
//
// 策略: 每次启动 sidecar (即 ensureLogStream 第一次被调) 时检查文件大小。
// 如果 > MAX_LOG_SIZE_BYTES (10MB), 把现有的 log 重命名为 .1, .1 -> .2,
// .2 -> .3, 删除 .3。然后新建一个空的 sidecar.log。
//
// 保留最多 3 份历史 (sidecar.log + .1 + .2 + .3), 总计约 40MB。

const MAX_LOG_SIZE_BYTES = 10 * 1024 * 1024  // 10 MB
const MAX_LOG_FILES = 3  // sidecar.log.1 / .2 / .3

/**
 * 如果 sidecar.log 超过 MAX_LOG_SIZE_BYTES, 执行 rotation。
 * 顺序: 删 .3 → .2→.3 → .1→.2 → sidecar.log→.1。
 * 失败的 rename/unlink 只记录, 不抛 — 日志 rotation 失败不应该阻塞 sidecar 启动。
 */
function rotateLogIfNeeded(logPath: string): void {
  let st: Stats
  try {
    st = statSync(logPath)
  } catch {
    // 文件不存在, 不需要 rotation
    return
  }
  if (st.size < MAX_LOG_SIZE_BYTES) return

  try {
    // 从最老的开始删 / rename, 避免覆盖
    // sidecar.log.3 -> 删除
    const oldest = `${logPath}.${MAX_LOG_FILES}`
    if (existsSync(oldest)) {
      try { unlinkSync(oldest) } catch (e) { /* 可能被占用, 忽略 */ }
    }
    // .2 -> .3, .1 -> .2, ...
    for (let i = MAX_LOG_FILES - 1; i >= 1; i--) {
      const src = `${logPath}.${i}`
      const dst = `${logPath}.${i + 1}`
      if (existsSync(src)) {
        try { renameSync(src, dst) } catch (e) { /* 忽略 */ }
      }
    }
    // sidecar.log -> sidecar.log.1
    try { renameSync(logPath, `${logPath}.1`) } catch (e) { /* 忽略 */ }
    console.log(`[sidecar] log rotated: ${st.size} bytes > ${MAX_LOG_SIZE_BYTES}`)
  } catch (e) {
    console.error('[sidecar] log rotation failed (non-blocking):', e)
  }
}

function ensureLogStream(): WriteStream | null {
  if (logStream) return logStream
  try {
    const logPath = getLogPath()
    const dir = app.getPath('userData')
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true })
    // Phase 5c: 启动前检查 log 大小, 超过 10MB 就 rotate
    rotateLogIfNeeded(logPath)
    logStream = createWriteStream(logPath, { flags: 'a' })
    writeLog(`\n\n=== HakusAI sidecar session: ${new Date().toISOString()} ===\n`)
    return logStream
  } catch (e) {
    console.error('[sidecar] Failed to open log file:', e)
    return null
  }
}

function writeLog(message: string) {
  const line = `${new Date().toISOString()} ${message}`
  console.log(`[sidecar] ${message}`)
  const stream = ensureLogStream()
  if (stream) {
    try {
      stream.write(line + '\n')
    } catch {
      /* ignore */
    }
  }
  // Also append to a buffer for IPC retrieval
  logBuffer.push(line)
  if (logBuffer.length > 500) logBuffer.shift()
}

const logBuffer: string[] = []

/** Spawn the sidecar and resolve once /health responds (or timeout). */
export function startSidecar(): Promise<{
  port: number | null
  error: string | null
  logPath: string
}> {
  const cmd = getSidecarCommand()
  const logPath = getLogPath()

  if (!cmd) {
    lastError = 'Sidecar not found: no bundled binary and no Python source available'
    writeLog(lastError)
    return Promise.resolve({ port: null, error: lastError, logPath })
  }

  writeLog(`Launch command: ${cmd.command} ${cmd.args.join(' ')}${cmd.cwd ? ` (cwd: ${cmd.cwd})` : ''}`)

  return new Promise((resolve) => {
    let portFound = false
    let resolved = false
    const finish = (port: number | null, error: string | null) => {
      if (resolved) return
      resolved = true
      resolve({ port, error, logPath })
    }

    try {
      sidecarProcess = spawn(cmd.command, cmd.args, {
        env: {
          ...process.env,
          ...cmd.env,
          HAKUSAI_PORT: process.env.HAKUSAI_PORT || '48081',
        },
        cwd: cmd.cwd,
        stdio: ['ignore', 'pipe', 'pipe'],
      })
    } catch (e: any) {
      lastError = `Failed to spawn sidecar: ${e?.message || String(e)}`
      writeLog(lastError)
      return finish(null, lastError)
    }

    writeLog(`Spawned sidecar PID=${sidecarProcess.pid}`)

    const onLine = (line: string) => {
      writeLog(line)
      const m = line.match(/HAKUSAI_PORT=(\d+)/)
      if (m && !portFound) {
        portFound = true
        detectedPort = Number(m[1])
        writeLog(`Detected port: ${detectedPort}`)
        // Now wait for /health to actually respond before resolving.
        // In dev mode the Python source import can take 20-30s on first boot
        // (heavy AI libs). Allow up to 60s for /health to reach a terminal
        // state before treating the sidecar as failed.
        waitForHealth(detectedPort!, 60000).then((ok) => {
          if (ok) {
            // Even if status=failed, we still resolve OK so the UI can load
            // and surface /api/diagnostics. lastError is preserved for
            // getSidecarStatus() to expose.
            finish(detectedPort, lastError)
          } else {
            // True timeout — /health never reached a terminal state.
            lastError = lastError
              ? `Sidecar health check failed: ${lastError}`
              : `Sidecar started on port ${detectedPort} but /health did not reach a terminal state within 60s. Check ${getLogPath()} for details.`
            writeLog(lastError)
            finish(null, lastError)
          }
        })
      }
    }

    if (sidecarProcess.stdout) {
      let buf = ''
      sidecarProcess.stdout.on('data', (chunk) => {
        buf += chunk.toString()
        const lines = buf.split('\n')
        buf = lines.pop() || ''
        for (const line of lines) onLine(line.trim())
      })
    }

    if (sidecarProcess.stderr) {
      sidecarProcess.stderr.on('data', (chunk) => {
        const text = chunk.toString().trim()
        if (text) writeLog(`[stderr] ${text}`)
      })
    }

    sidecarProcess.on('exit', (code, signal) => {
      writeLog(`exited code=${code} signal=${signal}`)
      lastExitCode = code
      sidecarProcess = null
      if (!portFound) {
        lastError = `Sidecar exited before printing HAKUSAI_PORT (code=${code} signal=${signal}). Check ${logPath} for details.`
        finish(null, lastError)
      }
    })

    sidecarProcess.on('error', (err) => {
      writeLog(`spawn error: ${err.message}`)
      lastError = `Spawn error: ${err.message}`
      finish(null, lastError)
    })

    // Timeout — if no HAKUSAI_PORT after 15s, assume sidecar is hung
    setTimeout(() => {
      if (!portFound && !resolved) {
        lastError = 'Sidecar did not print HAKUSAI_PORT within 15s — likely crashed during Python init'
        writeLog(lastError)
        // Try to kill the process so it doesn't linger
        try {
          sidecarProcess?.kill('SIGKILL')
        } catch {
          /* ignore */
        }
        finish(null, lastError)
      }
    }, 15000)
  })
}

/** Poll /health until it returns a terminal status (healthy|degraded|failed) or timeout.
 *
 * Phase 1 change: server now always returns 200 with a `status` field:
 *   - "starting" | "initializing": keep polling (AI init still in progress)
 *   - "healthy" | "degraded":      success — core chat is usable
 *   - "failed":                    success — HTTP is up, but AI init failed
 *                                  (e.g. missing API key). The UI can still
 *                                  load; it should query /api/diagnostics
 *                                  and show a configuration dialog so the
 *                                  user can fix the issue without restarting.
 *
 * This means the sidecar will be detected as ready within ~1s of the Python
 * process starting, regardless of AI init outcome. The 30s timeout is gone.
 */
async function waitForHealth(port: number, timeoutMs: number): Promise<boolean> {
  const url = `http://127.0.0.1:${port}/health`
  const deadline = Date.now() + timeoutMs
  writeLog(`Waiting for ${url} to respond...`)
  let lastStatus: string | null = null
  let lastError: string | null = null
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url, {
        signal: AbortSignal.timeout(2000),
      })
      if (res.ok) {
        const body = (await res.json().catch(() => ({}))) as {
          status?: string
          error?: string
          ready?: boolean
        }
        const status = body.status ?? 'unknown'
        if (status !== lastStatus) {
          writeLog(`Health status: ${status}${body.error ? ` (error: ${body.error})` : ''}`)
          lastStatus = status
          if (body.error) lastError = body.error
        }
        // healthy / degraded: HTTP & core components are usable
        if (status === 'healthy' || status === 'degraded') {
          writeLog(`Health check OK (status=${status})`)
          return true
        }
        // failed: HTTP is up but AI components couldn't init. We still return
        // true so the UI can load and show /api/diagnostics to the user —
        // they can then configure API key from inside the app instead of
        // staring at a "sidecar 30s timeout" error.
        if (status === 'failed') {
          writeLog(`Health check: sidecar HTTP up but AI init FAILED — letting UI load so user can see diagnostics.`)
          if (body.error) lastError = body.error
          // Stash the structured error so getSidecarStatus() can expose it
          lastError = `[status=failed] ${body.error || 'AI init failed — see /api/diagnostics'}`
          return true
        }
        // starting / initializing / unknown: keep polling
      } else {
        // Non-200 — server is up but returned an error code. Keep polling,
        // since this can happen briefly during startup.
        writeLog(`Health check returned ${res.status}, retrying...`)
      }
    } catch (e: any) {
      // Connection refused is expected during startup; only log every 5th attempt
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  if (lastError) {
    writeLog(`Health check timed out after ${timeoutMs}ms. Last status: ${lastStatus}, last error: ${lastError}`)
  } else {
    writeLog(`Health check timed out after ${timeoutMs}ms. Last status: ${lastStatus ?? 'never responded'}`)
  }
  return false
}

export function stopSidecar(): void {
  if (sidecarProcess) {
    writeLog('Stopping...')
    try {
      sidecarProcess.kill('SIGTERM')
      // Force-kill after 3s if still alive
      setTimeout(() => {
        if (sidecarProcess) {
          sidecarProcess.kill('SIGKILL')
        }
      }, 3000)
    } catch (e: any) {
      writeLog(`Failed to stop: ${e?.message || e}`)
    }
    sidecarProcess = null
  }
  if (logStream) {
    try {
      logStream.end()
    } catch {
      /* ignore */
    }
    logStream = null
  }
}

/** Restart the sidecar: stop the current process (if any) and start a fresh one. */
export async function restartSidecar(): Promise<{
  port: number | null
  error: string | null
  logPath: string
}> {
  writeLog('Restart requested...')
  stopSidecar()
  // Give the OS a moment to release the port
  await new Promise((r) => setTimeout(r, 500))
  lastError = null
  lastExitCode = null
  detectedPort = null
  return startSidecar()
}

export function getDetectedPort(): number | null {
  return detectedPort
}

export function getSidecarStatus(): SidecarStatus {
  return {
    available: isSidecarAvailable(),
    running: sidecarProcess !== null && !sidecarProcess.killed,
    port: detectedPort,
    pid: sidecarProcess?.pid ?? null,
    lastError,
    lastExitCode,
    logPath: getLogPath(),
    binaryPath: getSidecarPath(),
  }
}

export function getSidecarLogBuffer(): string[] {
  return logBuffer.slice()
}
