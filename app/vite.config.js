import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import sirv from 'sirv';

// /data is web/data, served here rather than copied: it is 1 GB and 90k files, which a static build must not carry
// (Cloudflare Pages caps a deployment at 20,000 files and 25 MB each). The build serves it through app/serve.mjs, and
// scripts/publish.sh points the app at R2 instead (src/lib/base.js).
const dataDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../web/data');
const serveData = { name: 'adfall-data', configureServer: s => { s.middlewares.use('/data', sirv(dataDir, { dev: true, etag: true })); },
                    configurePreviewServer: s => { s.middlewares.use('/data', sirv(dataDir, { dev: true, etag: true })); } };

// Host check: Vite refuses requests whose Host header it doesn't know (DNS-rebinding protection for dev
// servers). For a local/tailnet prototype we allow any host by default; set ALLOWED_HOSTS to narrow it:
//   ALLOWED_HOSTS=ix.carp-gopher.ts.net,localhost npm run preview -- --host
const allowedHosts = process.env.ALLOWED_HOSTS ? process.env.ALLOWED_HOSTS.split(',').map(s => s.trim()) : true;

export default defineConfig({
  plugins: [sveltekit(), serveData],
  server: { fs: { allow: ['..'] }, allowedHosts },
  preview: { allowedHosts }
});
