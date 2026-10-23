import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Vendor chunks change far less often than app code, so splitting them keeps
// the browser cache warm across deploys. Leaflet is only needed by map views,
// which are lazy-loaded, so it never blocks the shell's first paint.
function vendorChunk(id: string): string | undefined {
  if (!id.includes('node_modules')) return undefined
  if (/[\\/]node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id)) return 'react'
  if (/[\\/]node_modules[\\/](leaflet|react-leaflet|@react-leaflet)[\\/]/.test(id)) return 'leaflet'
  if (/[\\/]node_modules[\\/]lucide-react[\\/]/.test(id)) return 'icons'
  return undefined
}

export default defineConfig({
  plugins: [
    tailwindcss(),
    react(),
  ],
  build: {
    target: 'es2022',
    rollupOptions: {
      output: { manualChunks: vendorChunk },
    },
  },
})
