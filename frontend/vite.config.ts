import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  define: {
    'process.env.NODE_ENV': JSON.stringify('production'),
  },
  build: {
    lib: {
      entry: 'src/main.tsx',
      name: 'ClawWebUI',
      formats: ['iife'],
      fileName: () => 'clawweb-ui.js',
    },
    outDir: '../static',
    emptyOutDir: false,
    cssCodeSplit: false,
    rollupOptions: {
      // React is bundled into the IIFE, no externals needed
    },
  },
});
