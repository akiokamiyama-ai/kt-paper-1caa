// C37 (Sprint 9, 2026-06-02): Tribune コメント UI の認証ヘルパー.
//
// 設計
// ----
// - 共有パスワード方式（神山さん 1 ユーザー前提）。Vercel env var
//   TRIBUNE_AUTH_PASSWORD と timing-safe 比較。
// - 成功時に HMAC-SHA256 署名付き Cookie を発行（HttpOnly / Secure /
//   SameSite=Strict / 30 日）。署名鍵は同じ TRIBUNE_AUTH_PASSWORD を流用
//   （password rotate ですべての既存 Cookie を無効化できる）。
// - Cookie value = `<issued_at_ms>.<hex_hmac>`。issued_at が 30 日より
//   古ければ拒否。
//
// 使い方:
//   const ok = verifyAuthCookie(req)
//   if (!ok) return res.status(401).json({error: 'auth_required'})

const crypto = require('crypto');

const COOKIE_NAME = 'tribune_auth';
const MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000; // 30 日

function _getSecret() {
  const s = process.env.TRIBUNE_AUTH_PASSWORD;
  if (!s || typeof s !== 'string' || s.length < 8) {
    throw new Error('TRIBUNE_AUTH_PASSWORD env var missing or too short (need >=8 chars)');
  }
  return s;
}

function verifyPassword(provided) {
  const expected = _getSecret();
  if (typeof provided !== 'string') return false;
  const a = Buffer.from(provided, 'utf8');
  const b = Buffer.from(expected, 'utf8');
  if (a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}

function issueCookie() {
  const secret = _getSecret();
  const ts = Date.now().toString();
  const sig = crypto.createHmac('sha256', secret).update(ts).digest('hex');
  const value = `${ts}.${sig}`;
  const maxAgeSec = Math.floor(MAX_AGE_MS / 1000);
  return `${COOKIE_NAME}=${value}; Path=/; Max-Age=${maxAgeSec}; HttpOnly; Secure; SameSite=Strict`;
}

function clearCookie() {
  return `${COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict`;
}

function _parseCookieHeader(header) {
  const out = {};
  if (!header || typeof header !== 'string') return out;
  for (const part of header.split(';')) {
    const eq = part.indexOf('=');
    if (eq < 0) continue;
    const k = part.slice(0, eq).trim();
    const v = part.slice(eq + 1).trim();
    if (k) out[k] = decodeURIComponent(v);
  }
  return out;
}

function verifyAuthCookie(req) {
  let secret;
  try { secret = _getSecret(); } catch { return false; }
  const cookies = _parseCookieHeader(req.headers && req.headers.cookie);
  const val = cookies[COOKIE_NAME];
  if (!val || typeof val !== 'string') return false;
  const dot = val.lastIndexOf('.');
  if (dot < 0) return false;
  const ts = val.slice(0, dot);
  const sig = val.slice(dot + 1);
  const tsNum = parseInt(ts, 10);
  if (!Number.isFinite(tsNum)) return false;
  if (Date.now() - tsNum > MAX_AGE_MS) return false;
  const expected = crypto.createHmac('sha256', secret).update(ts).digest('hex');
  const a = Buffer.from(sig, 'hex');
  const b = Buffer.from(expected, 'hex');
  if (a.length !== b.length) return false;
  try {
    return crypto.timingSafeEqual(a, b);
  } catch {
    return false;
  }
}

module.exports = {
  COOKIE_NAME,
  verifyPassword,
  issueCookie,
  clearCookie,
  verifyAuthCookie,
};
