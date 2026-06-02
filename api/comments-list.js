// GET /api/comments-list
// 認証必須。data/comments/ 配下の YYYY-MM-DD.md を全件返す。
// レスポンス: { dates: [{date, size, sha}], total: N }
// 日付降順、空ファイル (size=0) も含めて返す（UI 側でラベル分け）。

const { verifyAuthCookie } = require('./_lib/auth');
const { listDir } = require('./_lib/github');

const NAME_RE = /^(\d{4}-\d{2}-\d{2})\.md$/;

module.exports = async function handler(req, res) {
  if (!verifyAuthCookie(req)) {
    return res.status(401).json({ error: 'auth_required' });
  }
  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET');
    return res.status(405).json({ error: 'method_not_allowed' });
  }

  try {
    const entries = await listDir('data/comments');
    const dates = [];
    for (const e of entries) {
      if (e.type !== 'file') continue;
      const m = NAME_RE.exec(e.name);
      if (!m) continue;
      dates.push({ date: m[1], size: e.size, sha: e.sha });
    }
    dates.sort((a, b) => b.date.localeCompare(a.date));
    return res.status(200).json({ dates, total: dates.length });
  } catch (e) {
    console.error('[comments-list] error:', e.message);
    return res.status(502).json({ error: 'github_list_failed' });
  }
};
