// GET  /api/comments?date=YYYY-MM-DD  → 既存 .md の content / sha を返す
// POST /api/comments  body: {date, content, sha?}  → GitHub に commit
//
// 認証必須（Cookie 検証）。書込みは payload 16 KB / 日付 ±14 日 / 同一 IP
// 10 秒連投の 3 種ガード付き。同時 push 衝突は sha mismatch を 1 回だけ
// retry で吸収（GHA cron は別パス書込なので衝突は稀）。

const { verifyAuthCookie } = require('./_lib/auth');
const { getFile, putFile } = require('./_lib/github');

const MAX_PAYLOAD_BYTES = 16 * 1024;
const DATE_WINDOW_DAYS = 14;
const POST_RATE_WINDOW_MS = 10 * 1000;
const _lastPost = new Map();

function _ip(req) {
  return (req.headers['x-forwarded-for'] || '').split(',')[0].trim()
    || req.socket?.remoteAddress
    || 'unknown';
}

function _isValidDate(s) {
  if (typeof s !== 'string') return false;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const d = new Date(s + 'T00:00:00Z');
  if (Number.isNaN(d.getTime())) return false;
  return d.toISOString().slice(0, 10) === s;
}

function _isWithinWindow(s) {
  const target = new Date(s + 'T00:00:00Z').getTime();
  const now = Date.now();
  const diffDays = Math.abs(now - target) / (24 * 60 * 60 * 1000);
  return diffDays <= DATE_WINDOW_DAYS;
}

function _commentsPath(date) {
  return `data/comments/${date}.md`;
}

async function _readBody(req) {
  if (req.body) return req.body;
  return new Promise((resolve, reject) => {
    let raw = '';
    req.on('data', (chunk) => {
      raw += chunk;
      if (raw.length > MAX_PAYLOAD_BYTES + 1024) {
        reject(new Error('payload_too_large'));
      }
    });
    req.on('end', () => {
      try { resolve(raw ? JSON.parse(raw) : {}); }
      catch { resolve({}); }
    });
    req.on('error', reject);
  });
}

async function handleGet(req, res) {
  const url = new URL(req.url, 'http://localhost');
  const date = url.searchParams.get('date');
  if (!_isValidDate(date)) {
    return res.status(400).json({ error: 'invalid_date' });
  }
  try {
    const file = await getFile(_commentsPath(date));
    if (!file) return res.status(200).json({ date, content: '', sha: null });
    return res.status(200).json({ date, content: file.content, sha: file.sha });
  } catch (e) {
    console.error('[comments GET] error:', e.message);
    return res.status(502).json({ error: 'github_fetch_failed' });
  }
}

async function handlePost(req, res) {
  const ip = _ip(req);
  const now = Date.now();
  const last = _lastPost.get(ip) || 0;
  if (now - last < POST_RATE_WINDOW_MS) {
    return res.status(429).json({ error: 'rate_limited', retry_after_ms: POST_RATE_WINDOW_MS - (now - last) });
  }
  _lastPost.set(ip, now);

  let body;
  try { body = await _readBody(req); }
  catch { return res.status(413).json({ error: 'payload_too_large' }); }

  const { date, content, sha } = body || {};
  if (!_isValidDate(date)) {
    return res.status(400).json({ error: 'invalid_date' });
  }
  if (!_isWithinWindow(date)) {
    return res.status(400).json({ error: 'date_out_of_window', window_days: DATE_WINDOW_DAYS });
  }
  if (typeof content !== 'string') {
    return res.status(400).json({ error: 'invalid_content' });
  }
  const byteLen = Buffer.byteLength(content, 'utf-8');
  if (byteLen > MAX_PAYLOAD_BYTES) {
    return res.status(413).json({ error: 'content_too_large', max_bytes: MAX_PAYLOAD_BYTES });
  }

  const path = _commentsPath(date);
  const message = `comment: ${date}`;

  // 1 回だけ sha mismatch を retry。GHA cron 中の書込衝突に備える。
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      let useSha = sha;
      if (attempt === 1 || !useSha) {
        const current = await getFile(path);
        useSha = current ? current.sha : undefined;
      }
      const result = await putFile(path, content, message, { sha: useSha });
      return res.status(200).json({ ok: true, date, sha: result.sha });
    } catch (e) {
      if (e && e.code === 'conflict' && attempt === 0) {
        // sha mismatch (someone else pushed): refetch sha and retry once.
        continue;
      }
      console.error('[comments POST] error:', e.message);
      return res.status(502).json({ error: 'github_commit_failed', detail: e.message });
    }
  }
  return res.status(409).json({ error: 'conflict_after_retry' });
}

module.exports = async function handler(req, res) {
  if (!verifyAuthCookie(req)) {
    return res.status(401).json({ error: 'auth_required' });
  }
  if (req.method === 'GET') return handleGet(req, res);
  if (req.method === 'POST') return handlePost(req, res);
  res.setHeader('Allow', 'GET, POST');
  return res.status(405).json({ error: 'method_not_allowed' });
};
