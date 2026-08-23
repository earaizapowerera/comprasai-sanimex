import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { defineConfig, searchForWorkspaceRoot } from 'vite'
import react from '@vitejs/plugin-react'

const rootDir = fileURLToPath(new URL('.', import.meta.url))
const repoDir = path.resolve(rootDir, '..')

// design-tokens.css / components.css (fuente de verdad: T2, carpeta ../design)
// se importan como módulos CSS normales desde src/main.jsx. Vite las bundlea
// junto al resto del CSS de la app (un solo archivo con hash de cache-busting
// en el build final) — no requiere un paso de copia aparte ni <link> manual.
export default defineConfig({
  plugins: [react()],
  base: '/comprasAI/',
  build: {
    outDir: '../frontend_static',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    fs: {
      allow: [searchForWorkspaceRoot(rootDir), repoDir],
    },
    // El cliente llama a `${BASE_URL}/api/...` (p.ej. /comprasAI/api/kpis) para que
    // las rutas funcionen igual en dev y detrás de nginx en prod. El backend (T3)
    // sirve en /api/... a secas, así que aquí quitamos el prefijo /comprasAI antes
    // de reenviar. Aplica también a `vite preview`.
    proxy: {
      '/comprasAI/api': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://localhost:8010',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/comprasAI/, ''),
      },
    },
  },
  preview: {
    port: 4173,
    proxy: {
      '/comprasAI/api': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://localhost:8010',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/comprasAI/, ''),
      },
    },
  },
})
