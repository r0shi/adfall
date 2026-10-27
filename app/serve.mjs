// Serve app/build the way a static host would, reading the folder live.
// `vite preview` indexes the build directory once at startup: after post_batch.sh (or `npm run build`) rewrites it, the
// running preview serves the new index.html but answers 404 for every new chunk until someone restarts it, and the
// site is blank until then. This uses sirv (the static server inside Vite) in dev mode, which looks each file up per
// request, answers Range requests (PMTiles needs them) and sends an ETag with Cache-Control: no-cache, so browsers
// revalidate every file instead of guessing how long it stays fresh.
//   npm --prefix app run serve -- --host 0.0.0.0 --port 4173
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import sirv from 'sirv';

const arg = (k, d) => { const i = process.argv.indexOf(k); return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : d; };
const host = arg('--host', '127.0.0.1'), port = Number(arg('--port', 4173));
const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), 'build');
const serve = sirv(dir, { dev: true, etag: true, single: 'index.html', extensions: ['html'] });   // single: unknown routes get the SPA shell
const dataDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '../web/data');          // /data is web/data itself, not a copy (vite.config.js says why)
const data = sirv(dataDir, { dev: true, etag: true });
const notFound = (res) => { res.statusCode = 404; res.end('not found'); };
http.createServer((req, res) => {
  if (req.url.startsWith('/data/')) { req.url = req.url.slice(5); return data(req, res, () => notFound(res)); }
  serve(req, res, () => notFound(res));
})
  .listen(port, host, () => console.log(`adfall: serving ${dir} at http://${host}:${port}`));
