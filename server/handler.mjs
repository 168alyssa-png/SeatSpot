import { randomBytes, createHash } from 'node:crypto';

const COOKIE_FLAVORS = Object.freeze({original:'Original',choc:'Chocolate',matcha:'Matcha',red:'Red Velvet'});
const COOKIE_ORDER = Object.keys(COOKIE_FLAVORS);
const COOKIE_IDS = new Set(COOKIE_ORDER);
const STATUSES = new Set(['New', 'Preparing', 'Ready']);
const ORDER_FIELDS = 'id,customer_name,cookie_id,cookie_flavor,quantity,table_id,created_at,updated_at,status';
const INVENTORY_FIELDS = 'id,flavor,quantity_remaining,active,sold_out,updated_at';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const SESSION_COOKIE = 'seatspot_session';
const STAFF_COOKIE = 'seatspot_staff';

class ApiError extends Error {
  constructor(status, code, message) { super(message); this.status = status; this.code = code; }
}
const fail = (status, code, message) => { throw new ApiError(status, code, message); };
const digest = token => createHash('sha256').update(token).digest('hex');
// Display names follow stable IDs, including rows created before a flavor rename.
const publicInventory = item => ({...item,flavor:COOKIE_FLAVORS[item.id] ?? item.flavor});
const publicOrder = order => order ? {...Object.fromEntries(ORDER_FIELDS.split(',').map(key => [key, order[key]])),cookie_flavor:COOKIE_FLAVORS[order.cookie_id] ?? order.cookie_flavor} : null;

function cookies(req) {
  const result = {};
  for (const part of (req.headers.cookie || '').split(';')) {
    const i = part.indexOf('=');
    if (i > 0) result[part.slice(0, i).trim()] = part.slice(i + 1).trim();
  }
  return result;
}
function setCookie(req, res, name, value, maxAge) {
  const secure = req.headers['x-forwarded-proto'] === 'https' || req.socket?.encrypted || Boolean(process.env.VERCEL);
  const cookie = `${name}=${value}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${maxAge}${secure ? '; Secure' : ''}`;
  const existing = res.getHeader('Set-Cookie') || [];
  res.setHeader('Set-Cookie', [...(Array.isArray(existing) ? existing : [existing]), cookie]);
}
function checkOrigin(req) {
  const origin = req.headers.origin;
  if (req.headers['sec-fetch-site'] === 'cross-site') fail(403, 'BAD_ORIGIN', 'This request must come from SeatSpot.');
  if (!origin) fail(403, 'BAD_ORIGIN', 'This request must come from SeatSpot.');
  try {
    const expectedProtocol = req.headers['x-forwarded-proto'] === 'https' || req.socket?.encrypted ? 'https:' : 'http:';
    const parsed = new URL(origin);
    if (parsed.host !== req.headers.host || parsed.protocol !== expectedProtocol) throw new Error();
  } catch { fail(403, 'BAD_ORIGIN', 'This request must come from SeatSpot.'); }
}
async function readBody(req) {
  if (!/^application\/json(?:;|$)/i.test(req.headers['content-type'] || '')) fail(415, 'JSON_REQUIRED', 'Send a JSON request.');
  if (req.body !== undefined && req.body !== null) {
    if (Buffer.byteLength(typeof req.body === 'string' ? req.body : JSON.stringify(req.body)) > 8192) fail(413, 'BODY_TOO_LARGE', 'Request is too large.');
    try { return typeof req.body === 'string' ? JSON.parse(req.body) : req.body; }
    catch { fail(400, 'INVALID_JSON', 'Invalid JSON request.'); }
  }
  const chunks = []; let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 8192) fail(413, 'BODY_TOO_LARGE', 'Request is too large.');
    chunks.push(chunk);
  }
  try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); }
  catch { fail(400, 'INVALID_JSON', 'Invalid JSON request.'); }
}
function upstreamError(data) {
  const messages = {
    NAME_REQUIRED: [409, 'Enter your name before placing an order.'],
    INVALID_NAME: [400, 'Enter a name between 1 and 30 characters, without control characters.'],
    SOLD_OUT: [409, 'That cookie has just sold out. Choose another flavor.'],
    SESSION_EXPIRED: [409, 'Your session expired. Refresh the inventory and try again.'],
    INVALID_TABLE: [400, 'Choose a valid SeatSpot table.'],
    INVALID_COOKIE: [400, 'Choose a valid cookie flavor.'],
    INVALID_STOCK_CHANGE: [400, 'Provide a stock quantity, adjustment, or active status.'],
    INVALID_STATUS: [400, 'Choose New, Preparing, or Ready.'],
    ORDER_NOT_FOUND: [404, 'This order was not found.'],
    STAFF_REQUIRED: [403, 'Staff access is required.']
  };
  if (messages[data?.message]) {
    const [status, message] = messages[data.message];
    return new ApiError(status, data.message, message);
  }
  if (data?.code === '23514' || data?.code === '22003') return new ApiError(409, 'INVALID_STOCK', 'Stock must stay between 0 and 1,000,000.');
  return new ApiError(503, 'SERVICE_UNAVAILABLE', 'The ordering service is unavailable. Please try again.');
}

export function createHandler({ env = process.env, fetchImpl = fetch } = {}) {
  return async function handle(req, res) {
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.setHeader('Cache-Control', 'no-store, private');
    res.setHeader('Vary', 'Cookie');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    const send = (status, payload) => { res.statusCode = status; res.end(JSON.stringify(payload)); };
    try {
      if (!['GET', 'POST'].includes(req.method)) {
        res.setHeader('Allow', 'GET, POST');
        fail(405, 'METHOD_NOT_ALLOWED', 'This method is not supported.');
      }
      if (req.method === 'POST') checkOrigin(req);
      if (!env.SUPABASE_URL || !env.SUPABASE_SERVICE_ROLE_KEY) fail(503, 'SETUP_REQUIRED', 'Cookie ordering is not available yet. Please try again later.');
      const base = new URL(env.SUPABASE_URL);
      const local = ['localhost', '127.0.0.1', '[::1]'].includes(base.hostname);
      if (base.username || base.password || (base.protocol !== 'https:' && !(base.protocol === 'http:' && local))) throw new Error('Invalid server configuration');
      const key = env.SUPABASE_SERVICE_ROLE_KEY;
      const request = async (path, { method = 'GET', body, token = key, extraHeaders = {} } = {}) => {
        let response;
        try {
          response = await fetchImpl(new URL(path, base.origin), {
            method,
            headers: { apikey: key, Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...extraHeaders },
            ...(body === undefined ? {} : { body: JSON.stringify(body) }),
            signal: AbortSignal.timeout(10000)
          });
        } catch { fail(503, 'SERVICE_UNAVAILABLE', 'The ordering service is unavailable. Please try again.'); }
        let data;
        try { data = await response.json(); } catch { data = {}; }
        if (!response.ok) {
          if (path.startsWith('/auth/')) fail(401, 'SIGN_IN_REQUIRED', 'Sign in with an authorized staff account.');
          throw upstreamError(data);
        }
        return data;
      };
      const rest = (resource, options) => request(`/rest/v1/${resource}`, options);
      const rpc = (name, body) => rest(`rpc/${name}`, { method: 'POST', body });
      const inventory = async () => (await rest(`cookie_inventory?select=${INVENTORY_FIELDS}&order=id.asc`)).map(publicInventory).sort((a,b)=>COOKIE_ORDER.indexOf(a.id)-COOKIE_ORDER.indexOf(b.id));
      const cookieValues = cookies(req);
      async function session(create = false) {
        const token = cookieValues[SESSION_COOKIE];
        if (token && /^[A-Za-z0-9_-]{43}$/.test(token)) {
          const hash = digest(token);
          const rows = await rest(`cookie_sessions?session_hash=eq.${hash}&select=session_hash,expires_at,customer_name&limit=1`);
          if (rows[0] && new Date(rows[0].expires_at).getTime() > Date.now()) return rows[0];
        }
        if (!create) fail(409, 'SESSION_REQUIRED', 'Refresh the inventory before placing your order.');
        const tokenNew = randomBytes(32).toString('base64url');
        const rows = await rest('cookie_sessions?select=session_hash,expires_at,customer_name', {
          method: 'POST', body: { session_hash: digest(tokenNew) }, extraHeaders: { Prefer: 'return=representation' }
        });
        if (!rows[0]?.expires_at) fail(503, 'SERVICE_UNAVAILABLE', 'The ordering service is unavailable. Please try again.');
        setCookie(req, res, SESSION_COOKIE, tokenNew, Math.max(1, Math.min(86400, Math.floor((new Date(rows[0].expires_at).getTime() - Date.now()) / 1000))));
        return rows[0];
      }
      async function requireStaff(token = cookieValues[STAFF_COOKIE]) {
        if (!token || token.length > 8192 || /[\s;]/.test(token)) fail(401, 'SIGN_IN_REQUIRED', 'Sign in with an authorized staff account.');
        const user = await request('/auth/v1/user', { token });
        if (!UUID.test(user.id || '')) fail(401, 'SIGN_IN_REQUIRED', 'Sign in with an authorized staff account.');
        const rows = await rest(`staff_members?user_id=eq.${user.id}&select=user_id&limit=1`);
        if (!rows.length) fail(403, 'STAFF_REQUIRED', 'This account does not have staff access.');
        return { id: user.id, email: user.email || '' };
      }
      const url = new URL(req.url, 'http://seatspot.local');
      const action = url.searchParams.get('action') || 'state';
      if (req.method === 'GET') {
        if (action === 'state') {
          const current = await session(true);
          const [stock, orders] = await Promise.all([
            inventory(),
            rest(`cookie_orders?session_hash=eq.${current.session_hash}&select=${ORDER_FIELDS}&limit=1`)
          ]);
          return send(200, { inventory: stock, order: publicOrder(orders[0]), customer_name: current.customer_name, session_expires_at: current.expires_at });
        }
        if (action === 'staff-state') {
          const staff = await requireStaff();
          const stock = await inventory();
          // Supabase caps each response; paginate so older exhibition orders are
          // not silently omitted. The next poll reconciles concurrent inserts.
          const orders = new Map();
          for (let offset = 0; ; offset += 1000) {
            const page = await rest(`cookie_orders?select=${ORDER_FIELDS}&order=created_at.desc,id.desc&limit=1000&offset=${offset}`);
            for (const order of page) orders.set(order.id, publicOrder(order));
            if (page.length < 1000) break;
          }
          return send(200, { staff: { email: staff.email }, inventory: stock, orders: [...orders.values()] });
        }
        fail(404, 'NOT_FOUND', 'This endpoint was not found.');
      }
      const body = await readBody(req);
      if (!body || Array.isArray(body) || typeof body !== 'object') fail(400, 'INVALID_BODY', 'Send a JSON object.');
      if (action === 'welcome') {
        const name = typeof body.customer_name === 'string' ? body.customer_name.trim() : '';
        if (!name || name.length > 30 || /[\u0000-\u001f\u007f]/u.test(name)) fail(400, 'INVALID_NAME', 'Enter a name between 1 and 30 characters, without control characters.');
        const current = await session();
        const saved = await rpc('set_customer_name', {p_session_hash:current.session_hash,p_customer_name:name});
        return send(200, {customer_name:saved,session_expires_at:current.expires_at});
      }
      if (action === 'order') {
        if (body.catalog_version !== 'four-flavors-v1') fail(409, 'CATALOG_UPDATED', 'The cookie menu has changed. Refresh this page before ordering.');
        if (!COOKIE_IDS.has(body.cookie_id)) fail(400, 'INVALID_COOKIE', 'Choose a valid cookie flavor.');
        if (body.quantity !== undefined && body.quantity !== 1) fail(400, 'ONE_COOKIE_ONLY', 'You may order one cookie per session.');
        const table = body.table_id ?? null;
        if (table !== null && (typeof table !== 'string' || !/^[ABC]([1-9]|1[0-2])$/.test(table))) fail(400, 'INVALID_TABLE', 'Choose a valid SeatSpot table.');
        const current = await session();
        const result = await rpc('place_named_cookie_order', { p_session_hash: current.session_hash, p_cookie_id: body.cookie_id, p_table_id: table });
        return send(200, { inventory: await inventory(), order: publicOrder(result.order), already_ordered: result.already_ordered, customer_name: current.customer_name, session_expires_at: current.expires_at });
      }
      if (action === 'staff-login') {
        if (typeof body.email !== 'string' || typeof body.password !== 'string' || body.email.length > 320 || body.password.length > 1000 || !body.email || !body.password) fail(400, 'CREDENTIALS_REQUIRED', 'Enter your staff email and password.');
        const auth = await request('/auth/v1/token?grant_type=password', { method: 'POST', body: { email: body.email, password: body.password } });
        if (typeof auth.access_token !== 'string' || !auth.access_token) fail(401, 'SIGN_IN_REQUIRED', 'Sign in with an authorized staff account.');
        const staff = await requireStaff(auth.access_token);
        setCookie(req, res, STAFF_COOKIE, auth.access_token, Math.min(Number(auth.expires_in) || 3600, 3600));
        return send(200, { staff: { email: staff.email } });
      }
      if (action === 'staff-logout') {
        setCookie(req, res, STAFF_COOKIE, '', 0);
        return send(200, { ok: true });
      }
      const staff = await requireStaff();
      if (action === 'inventory') {
        if (!COOKIE_IDS.has(body.cookie_id)) fail(400, 'INVALID_COOKIE', 'Choose a valid cookie flavor.');
        const quantity = body.quantity ?? null;
        const adjustment = body.adjustment ?? null;
        const active = body.active ?? null;
        if ((quantity !== null && (!Number.isInteger(quantity) || quantity < 0 || quantity > 1000000)) ||
            (adjustment !== null && (!Number.isInteger(adjustment) || Math.abs(adjustment) > 1000000)) ||
            (active !== null && typeof active !== 'boolean') || (quantity !== null && adjustment !== null) ||
            (quantity === null && adjustment === null && active === null)) fail(400, 'INVALID_STOCK_CHANGE', 'Enter a valid stock quantity or adjustment.');
        const stock = await rpc('set_cookie_inventory', { p_staff_id: staff.id, p_cookie_id: body.cookie_id, p_quantity: quantity, p_adjustment: adjustment, p_active: active });
        return send(200, { inventory: publicInventory(stock) });
      }
      if (action === 'order-status') {
        if (!UUID.test(body.order_id || '') || !STATUSES.has(body.status)) fail(400, 'INVALID_STATUS', 'Choose an order and New, Preparing, or Ready.');
        const order = await rpc('set_cookie_order_status', { p_staff_id: staff.id, p_order_id: body.order_id, p_status: body.status });
        return send(200, { order: publicOrder(order) });
      }
      fail(404, 'NOT_FOUND', 'This endpoint was not found.');
    } catch (error) {
      if (!(error instanceof ApiError)) console.error('SeatSpot API failure: internal configuration or unexpected response');
      send(error instanceof ApiError ? error.status : 503, {
        error: { code: error instanceof ApiError ? error.code : 'SERVICE_UNAVAILABLE', message: error instanceof ApiError ? error.message : 'The ordering service is unavailable. Please try again.' }
      });
    }
  };
}
