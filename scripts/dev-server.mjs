import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
if (existsSync(path.join(root, '.env.local'))) process.loadEnvFile(path.join(root, '.env.local'));
const { default: api } = await import('../api/seatspot.js');
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.png': 'image/png', '.txt': 'text/plain; charset=utf-8', '.md': 'text/plain; charset=utf-8' };
export const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname === '/api/seatspot') return await api(req, res);
    if (!['GET', 'HEAD'].includes(req.method)) { res.writeHead(405); return res.end(); }
    let name = decodeURIComponent(url.pathname);
    if (name === '/' || name === '/index.html') name = '/index.html';
    else if (['/admin', '/admin/', '/admin/index.html'].includes(name)) name = '/admin/index.html';
    else if (!name.startsWith('/assets/')) { res.writeHead(404); return res.end('Not found'); }
    const file = path.resolve(root, '.' + name);
    if (file !== path.join(root, 'index.html') && file !== path.join(root, 'admin/index.html') && !file.startsWith(path.join(root, 'assets') + path.sep)) { res.writeHead(404); return res.end('Not found'); }
    if (!(await stat(file)).isFile()) throw new Error('Not found');
    res.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream');
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('Permissions-Policy', 'camera=(self), microphone=()');
    if (req.method === 'HEAD') return res.end();
    res.end(await readFile(file));
  } catch { res.writeHead(404); res.end('Not found'); }
});
server.listen(Number(process.env.PORT || 4173), process.env.HOST || '127.0.0.1', () => {
  console.log(`SeatSpot development server listening on port ${server.address().port}`);
});
