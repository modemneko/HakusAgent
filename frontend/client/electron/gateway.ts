/**
 * HakusAI Node Gateway
 *
 * Runs inside the Electron main process and proxies all renderer -> sidecar
 * traffic through a fixed local port. This lets the frontend always talk to
 * `http://127.0.0.1:23980` regardless of which ephemeral port the Python
 * sidecar binds to.
 *
 * Supports:
 *   - HTTP/REST proxy (incl. SSE streams)
 *   - WebSocket upgrade proxy
 *
 * Later phases can implement request/response transformation, caching,
 * retries, or move endpoints entirely into Node.
 */

import http from 'node:http'
import type { IncomingMessage } from 'node:http'

const DEFAULT_GATEWAY_PORT = 23980
const DEFAULT_SIDECAR_URL = 'http://127.0.0.1:48081'

let gatewayServer: http.Server | null = null
let targetBaseUrl = DEFAULT_SIDECAR_URL

export function setTargetBaseUrl(url: string): void {
  targetBaseUrl = url.replace(/\/$/, '')
}

export function getTargetBaseUrl(): string {
  return targetBaseUrl
}

export function getGatewayPort(): number {
  const addr = gatewayServer?.address()
  if (addr && typeof addr === 'object') return addr.port
  return DEFAULT_GATEWAY_PORT
}

export function getGatewayUrl(): string {
  return `http://127.0.0.1:${getGatewayPort()}`
}

function getTargetUrl(clientReq: IncomingMessage): URL {
  return new URL(clientReq.url || '/', targetBaseUrl)
}

export function startGateway(): Promise<{ port: number; url: string }> {
  return new Promise((resolve, reject) => {
    if (gatewayServer) {
      resolve({ port: getGatewayPort(), url: getGatewayUrl() })
      return
    }

    gatewayServer = http.createServer((clientReq, clientRes) => {
      const target = getTargetUrl(clientReq)
      const headers: Record<string, string | string[]> = {}
      for (const [k, v] of Object.entries(clientReq.headers)) {
        if (v === undefined) continue
        headers[k] = v
      }
      headers.host = target.host

      const proxyReq = http.request(
        {
          hostname: target.hostname,
          port: target.port,
          path: target.pathname + target.search,
          method: clientReq.method,
          headers,
        },
        (proxyRes) => {
          clientRes.writeHead(proxyRes.statusCode || 200, proxyRes.headers)
          proxyRes.pipe(clientRes, { end: true })
        },
      )

      proxyReq.on('error', (err) => {
        console.error('[gateway] proxy error:', err.message)
        if (!clientRes.headersSent) {
          clientRes.writeHead(502, { 'Content-Type': 'application/json' })
          clientRes.end(JSON.stringify({ error: 'Sidecar unavailable', message: err.message }))
        } else {
          clientRes.destroy()
        }
      })

      clientReq.pipe(proxyReq, { end: true })
    })

    // WebSocket upgrade proxy
    gatewayServer.on('upgrade', (clientReq, clientSocket, head) => {
      const target = getTargetUrl(clientReq)
      const wsBase = targetBaseUrl.replace(/^http/, 'ws')
      const wsUrl = new URL(clientReq.url || '/', wsBase)

      const headers: Record<string, string | string[]> = {}
      for (const [k, v] of Object.entries(clientReq.headers)) {
        if (v === undefined) continue
        headers[k] = v
      }
      headers.host = wsUrl.host

      const proxyReq = http.request(
        {
          hostname: wsUrl.hostname,
          port: wsUrl.port,
          path: wsUrl.pathname + wsUrl.search,
          method: clientReq.method,
          headers,
        },
        () => {
          /* upgrade response handled by 'upgrade' event */
        },
      )

      proxyReq.on('upgrade', (proxyRes, proxySocket, proxyHead) => {
        let headerLines = `HTTP/1.1 101 Switching Protocols\r\n`
        for (const [k, v] of Object.entries(proxyRes.headers)) {
          if (v === undefined) continue
          headerLines += `${k}: ${Array.isArray(v) ? v.join(', ') : v}\r\n`
        }
        headerLines += `\r\n`
        clientSocket.write(headerLines)

        proxySocket.pipe(clientSocket)
        clientSocket.pipe(proxySocket)

        if (proxyHead && proxyHead.length > 0) proxySocket.unshift(proxyHead)
        if (head && head.length > 0) clientSocket.unshift(head)

        proxySocket.on('error', (err) => {
          console.error('[gateway] ws target error:', err.message)
          clientSocket.destroy()
        })
        clientSocket.on('error', (err) => {
          console.error('[gateway] ws client error:', err.message)
          proxySocket.destroy()
        })
      })

      proxyReq.on('error', (err) => {
        console.error('[gateway] ws proxy request error:', err.message)
        clientSocket.end('HTTP/1.1 502 Bad Gateway\r\n\r\n')
      })

      clientReq.pipe(proxyReq, { end: true })
    })

    gatewayServer.listen(DEFAULT_GATEWAY_PORT, '127.0.0.1', () => {
      console.log(`[gateway] listening on ${getGatewayUrl()} -> ${targetBaseUrl}`)
      resolve({ port: getGatewayPort(), url: getGatewayUrl() })
    })

    gatewayServer.on('error', (err) => {
      console.error('[gateway] server error:', err)
      reject(err)
    })
  })
}

export function stopGateway(): void {
  if (gatewayServer) {
    gatewayServer.close()
    gatewayServer = null
  }
}
