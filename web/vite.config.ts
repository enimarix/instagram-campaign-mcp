/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // `ig-campaign serve` listens here
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
  test: {
    environment: 'jsdom',
  },
})
