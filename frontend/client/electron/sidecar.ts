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
 */

import { spawn, type ChildProcess } from 'node:child_process'
import { join } from 'node:path'
import { existsSync } from 'node:fs'
import { app } from 'electron'

let sidecarProcess: ChildProcess | null = null
let detectedPort: number | null = null

/** Path to the bundled sidecar binary, or null if not present. */
function getSidecarPath(): string | null {
  let dir: string
  if (app.isPackaged) {
    // In production: <Resources>/sidecar/
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

/** Spawn the sidecar and resolve once `HAKUSAI_PORT=...` is printed. */
export function startSidecar(): Promise<number | null> {
  const binPath = getSidecarPath()
  if (!binPath) {
    return Promise.resolve(null)
  }

  return new Promise((resolve) => {
    let portFound = false

    sidecarProcess = spawn(binPath, [], {
      env: {
        ...process.env,
        HAKUSAI_PORT: process.env.HAKUSAI_PORT || '8080',
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    })

    const onLine = (line: string) => {
      console.log(`[sidecar] ${line}`)
      const m = line.match(/HAKUSAI_PORT=(\d+)/)
      if (m && !portFound) {
        portFound = true
        detectedPort = Number(m[1])
        resolve(detectedPort)
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
        console.error(`[sidecar:err] ${chunk.toString().trim()}`)
      })
    }

    sidecarProcess.on('exit', (code, signal) => {
      console.log(`[sidecar] exited code=${code} signal=${signal}`)
      sidecarProcess = null
      if (!portFound) resolve(null)
    })

    // Timeout — if no port after 10s, give up (server may still be starting)
    setTimeout(() => {
      if (!portFound) {
        console.warn('[sidecar] Timed out waiting for HAKUSAI_PORT — assuming 8080')
        detectedPort = 8080
        portFound = true
        resolve(8080)
      }
    }, 10000)
  })
}

export function stopSidecar(): void {
  if (sidecarProcess) {
    console.log('[sidecar] Stopping...')
    try {
      sidecarProcess.kill('SIGTERM')
      // Force-kill after 3s if still alive
      setTimeout(() => {
        if (sidecarProcess) {
          sidecarProcess.kill('SIGKILL')
        }
      }, 3000)
    } catch (e) {
      console.error('[sidecar] Failed to stop:', e)
    }
    sidecarProcess = null
  }
}

export function getDetectedPort(): number | null {
  return detectedPort
}
