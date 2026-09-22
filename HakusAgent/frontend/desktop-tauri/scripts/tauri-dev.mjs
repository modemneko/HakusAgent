/**
 * Launch the Tauri dev CLI with an explicit PATH.
 *
 * This environment's shell shim strips PATH before spawning children, so
 * `tauri dev` cannot find `cargo`. Setting PATH on the node process itself
 * makes it visible to every child tauri spawns (cargo + npm run dev).
 */
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const projectDir = path.resolve(scriptDir, '..')

const extra = [
  'C:/Users/Think/.cargo/bin',
  'C:/Program Files/nodejs',
  'C:/Windows/System32',
  'C:/Windows',
  'C:/Windows/System32/Wbem',
]
process.env.PATH = [...extra, process.env.PATH || ''].filter(Boolean).join(';')

// Also pin the tools tauri shells out to, so a broken PATH cannot bite again.
process.env.CARGO = process.env.CARGO || 'C:/Users/Think/.cargo/bin/cargo.exe'
process.env.npm_execpath = process.env.npm_execpath || 'C:/Program Files/nodejs/npm.cmd'

const require = createRequire(path.join(projectDir, 'package.json'))
const cli = path.join(projectDir, 'node_modules/@tauri-apps/cli/tauri.js')
process.chdir(projectDir)
require(cli)
