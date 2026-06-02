// POST /api/auth
// Body: {password: string}
// 成功: 200 + Set-Cookie tribune_auth=<signed>
// 失敗: 401

const { verifyPassword, issueCookie, clearCookie } = require('./_lib/auth');

// 簡易 rate limit: 同一 IP からの 5 秒以内連投を 429。
const _lastAttempt = new Map();
const ATTEMPT_WINDOW_MS = 5000;

function _ip(req) {
  return (req.headers['x-forwarded-for'] || '').split(',')[0].trim()
    || req.socket?.remoteAddress
    || 'unknown';
}

async function _readBody(req) {
  if (req.body) return req.body;
  return new Promise((resolve, reject) => {
    let raw = '';
    req.on('data', (chunk) => {
      raw += chunk;
      if (raw.length > 4096) reject(new Error('payload_too_large'));
    });
    req.on('end', () => {
      try { resolve(raw ? JSON.parse(raw) : {}); }
      catch { resolve({}); }
    });
    req.on('error', reject);
  });
}

module.exports = async function handler(req, res) {
  if (req.method === 'DELETE') {
    res.setHeader('Set-Cookie', clearCookie());
    return res.status(200).json({ ok: true });
  }
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST, DELETE');
    return res.status(405).json({ error: 'method_not_allowed' });
  }

  const ip = _ip(req);
  const now = Date.now();
  const last = _lastAttempt.get(ip) || 0;
  if (now - last < ATTEMPT_WINDOW_MS) {
    return res.status(429).json({ error: 'rate_limited' });
  }
  _lastAttempt.set(ip, now);

  let body;
  try { body = await _readBody(req); }
  catch { return res.status(413).json({ error: 'payload_too_large' }); }

  const provided = body && body.password;
  let ok;
  try { ok = verifyPassword(provided || ''); }
  catch (e) {
    console.error('[auth] env error:', e.message);
    return res.status(500).json({ error: 'server_misconfigured' });
  }

  if (!ok) {
    return res.status(401).json({ error: 'invalid_password' });
  }

  res.setHeader('Set-Cookie', issueCookie());
  return res.status(200).json({ ok: true });
};
