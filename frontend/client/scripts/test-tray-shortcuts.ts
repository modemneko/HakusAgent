/**
 * Smoke test for the tray/shortcuts pure helpers.
 *
 * Doesn't actually create a Tray (needs a running Electron app) — just
 * exercises the pure functions to catch any logic errors in the
 * accelerator syntax validator.
 */

import { isValidAcceleratorSyntax, defaultAccelerator } from '../electron/shortcuts-helpers'

let pass = 0
let fail = 0

function expect(cond: boolean, label: string) {
  if (cond) {
    pass++
    console.log(`  ✓ ${label}`)
  } else {
    fail++
    console.error(`  ✗ ${label}`)
  }
}

console.log('Phase 3 — Tray + Shortcuts smoke test\n')

// Default accelerator
console.log('[1] Default accelerator:')
expect(defaultAccelerator() === 'Shift+CommandOrControl+H', 'default is Shift+CommandOrControl+H')

// Accelerator syntax validation
console.log('\n[2] Accelerator syntax validation:')
expect(isValidAcceleratorSyntax('Shift+CommandOrControl+H') === true, 'Shift+CommandOrControl+H valid')
expect(isValidAcceleratorSyntax('CommandOrControl+J') === true, 'CommandOrControl+J valid')
expect(isValidAcceleratorSyntax('Alt+F4') === true, 'Alt+F4 valid')
expect(isValidAcceleratorSyntax('Control+Shift+Alt+Delete') === true, 'Control+Shift+Alt+Delete valid')
expect(isValidAcceleratorSyntax('F11') === false, 'F11 alone invalid (no modifier)')
expect(isValidAcceleratorSyntax('A') === false, 'A alone invalid')
expect(isValidAcceleratorSyntax('') === false, 'empty string invalid')
expect(isValidAcceleratorSyntax('Foo+Bar') === false, 'Foo+Bar invalid (unknown modifier)')
expect(isValidAcceleratorSyntax('Shift+') === false, 'Shift+ invalid (no key)')
expect(isValidAcceleratorSyntax('Shift+X') === true, 'Shift+X valid')
expect(isValidAcceleratorSyntax('CmdOrCtrl+Space') === true, 'CmdOrCtrl alias valid')
expect(isValidAcceleratorSyntax('Meta+P') === true, 'Meta+P valid')
expect(isValidAcceleratorSyntax('Shift+CommandOrControl+1') === true, 'digit valid')
expect(isValidAcceleratorSyntax('Shift+CommandOrControl+F12') === true, 'F12 valid')

console.log(`\nResult: ${pass} passed, ${fail} failed`)
process.exit(fail === 0 ? 0 : 1)
