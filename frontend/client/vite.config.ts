import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import electron from 'vite-plugin-electron'
import renderer from 'vite-plugin-electron-renderer'
import path from 'node:path'

// https://vite.dev/config/
export default defineConfig(({ command, mode }) => {
  const enableElectron = command === 'build' || mode === 'electron'

  // 仅首次启动 Electron；代码变更后不再自动重启窗口，保留渲染进程 HMR。
  let electronStarted = false

  return {
    plugins: [
      react(),
      ...(enableElectron
        ? [
            electron([
              {
                entry: 'electron/main.ts',
                onstart({ startup }) {
                  if (!electronStarted) {
                    startup()
                    electronStarted = true
                  }
                },
                vite: {
                  build: {
                    outDir: 'dist-electron',
                    rollupOptions: {
                      external: ['electron', 'electron-store'],
                    },
                  },
                },
              },
              {
                entry: 'electron/preload.ts',
                onstart({ startup }) {
                  if (!electronStarted) {
                    startup()
                    electronStarted = true
                  }
                },
                vite: {
                  build: {
                    outDir: 'dist-electron',
                    lib: {
                      entry: 'electron/preload.ts',
                      formats: ['cjs'],
                      fileName: () => 'preload',
                    },
                    rollupOptions: {
                      external: ['electron', 'electron-store'],
                      output: {
                        // Preload scripts run as CommonJS in Electron. Because this
                        // package is "type: module", keep the .cjs suffix explicit.
                        format: 'cjs',
                        entryFileNames: 'preload.cjs',
                      },
                    },
                  },
                },
              },
            ]),
            renderer(),
          ]
        : []),
    ],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      host: '127.0.0.1',
      port: 1421,
      strictPort: true,
    },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
    },
  }
})
