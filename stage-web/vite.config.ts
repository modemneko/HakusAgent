import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { nodePolyfills } from 'vite-plugin-node-polyfills'
import path from 'path'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    nodePolyfills({
      include: ['url', 'buffer', 'process'],
      globals: {
        Buffer: true,
        process: true,
      },
    }),
    {
      name: 'live2d-sdk-inject',
      transformIndexHtml(html) {
        return html.replace(
          '<head>',
          `<head>
    <script src="https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js"></script>`
        )
      },
    },
  ],
  optimizeDeps: {
    exclude: ['pixi-live2d-display'],
    include: ['eventemitter3', 'earcut'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8080',
        ws: true,
      },
    },
  },
})
