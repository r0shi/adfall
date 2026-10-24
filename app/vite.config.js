import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// Host check: Vite refuses requests whose Host header it doesn't know (DNS-rebinding protection for dev
// servers). For a local/tailnet prototype we allow any host by default; set ALLOWED_HOSTS to narrow it:
//   ALLOWED_HOSTS=ix.carp-gopher.ts.net,localhost npm run preview -- --host
const allowedHosts = process.env.ALLOWED_HOSTS ? process.env.ALLOWED_HOSTS.split(',').map(s => s.trim()) : true;

export default defineConfig({
  plugins: [sveltekit()],
  server: { fs: { allow: ['..'] }, allowedHosts },
  preview: { allowedHosts }
});
