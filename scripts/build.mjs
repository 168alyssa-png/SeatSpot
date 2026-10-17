import { cp, mkdir } from 'node:fs/promises';

await mkdir('public', { recursive: true });
await cp('index.html', 'public/index.html');
await cp('assets', 'public/assets', { recursive: true });
await cp('admin', 'public/admin', { recursive: true });
// No environment values are embedded into public files. API code remains
// outside public/ and is deployed as a Vercel Node function.
console.log('Built public HTML, styles, scanner, customer, and staff assets.');
