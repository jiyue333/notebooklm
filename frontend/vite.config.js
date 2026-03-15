import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

const FRONTEND_DIR = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(FRONTEND_DIR, '..')

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, REPO_ROOT, '')
  const proxyTarget = env.VITE_DEV_PROXY_TARGET

  return {
    envDir: REPO_ROOT,
    plugins: [react()],
    server: proxyTarget
      ? {
          proxy: {
            '/api': {
              target: proxyTarget,
              changeOrigin: true,
            },
          },
        }
      : undefined,
  }
})
