/**
 * HakusAI Python backend sidecar manager.
 *
 * When the Electron app is packaged with `extraResources: sidecar/`,
 * a PyInstaller-built `hakusai-server` binary is shipped alongside
 * the app. This module spawns it on startup and parses its stdout
 * to discover the chosen port (the server prints `HAKUSAI_PORT=8080`).
 *
 * In dev mode (no sidecar binary present), this is a no-op and the
 * client falls back to connecting to a separately-running server
 * (default: http://localhost:8080).
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
import { existsSync, mkdirSync, appendFileSync, createWriteStream, type WriteStream } from 'node:fs'
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

/** Open a persistent log file under the user's userData directory. */
function getLogPath(): string {
  return join(app.getPath('userData'), 'sidecar.log')
}

function ensureLogStream(): WriteStream | null {
  if (logStream) return logStream
  try {
    const logPath = getLogPath()
    const dir = app.getPath('userData')
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true })
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
  const binPath = getSidecarPath()
  const logPath = getLogPath()

  if (!binPath) {
    lastError = 'Sidecar binary not found (no hakusai-server in resources/sidecar/dist)'
    writeLog(lastError)
    return Promise.resolve({ port: null, error: lastError, logPath })
  }

  writeLog(`Binary path: ${binPath}`)

  return new Promise((resolve) => {
    let portFound = false
    let resolved = false
    const finish = (port: number | null, error: string | null) => {
      if (resolved) return
      resolved = true
      resolve({ port, error, logPath })
    }

    try {
      sidecarProcess = spawn(binPath, [], {
        env: {
          ...process.env,
          HAKUSAI_PORT: process.env.HAKUSAI_PORT || '8080',
        },
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
        // Phase 1: timeout reduced from 30s → 15s, because /health now returns
        // 200 within ~1s of the Python process starting (AI init is async).
        // If we get to 15s without healthy/degraded/failed, something is
        // genuinely wrong (e.g. Python crash, port conflict).
        waitForHealth(detectedPort!, 15000).then((ok) => {
          if (ok) {
            // Even if status=failed, we still resolve OK so the UI can load
            // and surface /api/diagnostics. lastError is preserved for
            // getSidecarStatus() to expose.
            finish(detectedPort, lastError)
          } else {
            // True timeout — /health never reached a terminal state.
            lastError = lastError
              ? `Sidecar health check failed: ${lastError}`
              : `Sidecar started on port ${detectedPort} but /health did not reach a terminal state within 15s. Check ${getLogPath()} for details.`
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
