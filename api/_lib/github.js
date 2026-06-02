// C37 (Sprint 9, 2026-06-02): GitHub Contents API の薄いラッパー.
//
// Fine-grained PAT (`TRIBUNE_GITHUB_PAT`) で
// data/comments/YYYY-MM-DD.md の GET / PUT / LIST を行う。
// Octokit は使わず fetch 直叩きで依存ゼロ、将来 Edge 移植も容易。

const REPO_DEFAULT = 'akiokamiyama-ai/kt-paper-1caa';
const BRANCH_DEFAULT = 'main';
const AUTHOR_NAME = 'Akio Kamiyama';
const AUTHOR_EMAIL = 'akio.kamiyama@cocolomi.co.jp';

function _getRepo() {
  return process.env.TRIBUNE_GITHUB_REPO || REPO_DEFAULT;
}

function _getBranch() {
  return process.env.TRIBUNE_GITHUB_BRANCH || BRANCH_DEFAULT;
}

function _getPat() {
  const t = process.env.TRIBUNE_GITHUB_PAT;
  if (!t || typeof t !== 'string') {
    throw new Error('TRIBUNE_GITHUB_PAT env var missing');
  }
  return t;
}

function _headers() {
  return {
    'Accept': 'application/vnd.github+json',
    'Authorization': `Bearer ${_getPat()}`,
    'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': 'tribune-comment-ui',
  };
}

// GET file content. Returns {content, sha} or null when 404.
async function getFile(path) {
  const repo = _getRepo();
  const branch = _getBranch();
  const url = `https://api.github.com/repos/${repo}/contents/${encodeURIComponent(path).replace(/%2F/g, '/')}?ref=${encodeURIComponent(branch)}`;
  const res = await fetch(url, { method: 'GET', headers: _headers() });
  if (res.status === 404) return null;
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`GitHub getFile failed ${res.status}: ${text.slice(0, 200)}`);
  }
  const data = await res.json();
  const buf = Buffer.from(data.content || '', data.encoding || 'base64');
  return { content: buf.toString('utf-8'), sha: data.sha };
}

// PUT file. If sha provided, treats as update; otherwise create.
// Returns {sha} of the new content.
async function putFile(path, content, message, { sha } = {}) {
  const repo = _getRepo();
  const branch = _getBranch();
  const url = `https://api.github.com/repos/${repo}/contents/${encodeURIComponent(path).replace(/%2F/g, '/')}`;
  const body = {
    message,
    content: Buffer.from(content, 'utf-8').toString('base64'),
    branch,
    committer: { name: AUTHOR_NAME, email: AUTHOR_EMAIL },
    author: { name: AUTHOR_NAME, email: AUTHOR_EMAIL },
  };
  if (sha) body.sha = sha;
  const res = await fetch(url, {
    method: 'PUT',
    headers: { ...(_headers()), 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (res.status === 409 || res.status === 422) {
    const text = await res.text();
    const e = new Error(`GitHub putFile conflict ${res.status}: ${text.slice(0, 200)}`);
    e.code = 'conflict';
    throw e;
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`GitHub putFile failed ${res.status}: ${text.slice(0, 200)}`);
  }
  const data = await res.json();
  return { sha: data.content && data.content.sha };
}

// List directory entries. Returns [{name, size, sha, type}].
async function listDir(path) {
  const repo = _getRepo();
  const branch = _getBranch();
  const url = `https://api.github.com/repos/${repo}/contents/${encodeURIComponent(path).replace(/%2F/g, '/')}?ref=${encodeURIComponent(branch)}`;
  const res = await fetch(url, { method: 'GET', headers: _headers() });
  if (res.status === 404) return [];
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`GitHub listDir failed ${res.status}: ${text.slice(0, 200)}`);
  }
  const data = await res.json();
  if (!Array.isArray(data)) return [];
  return data.map((e) => ({
    name: e.name, size: e.size, sha: e.sha, type: e.type, path: e.path,
  }));
}

module.exports = { getFile, putFile, listDir };
