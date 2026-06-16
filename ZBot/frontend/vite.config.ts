import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * Vite dev 配置
 *
 * - /api 代理到后端 :8000
 * - SSE 友好:用 configure 钩子(http-proxy 实例)设 Connection: keep-alive,
 *   避免代理层因默认 Connection: close 提前关流。
 */
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
        configure: (proxy) => {
          // http-proxy 实例,TS 类型不暴露 on,这里运行时安全
          (proxy as unknown as { on: (e: string, cb: (req: { setHeader: (k: string, v: string) => void }) => void) => void })
            .on('proxyReq', (proxyReq) => {
              proxyReq.setHeader('Connection', 'keep-alive');
            });
        },
      },
    },
  },
})