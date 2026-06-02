// C37 (Sprint 9, 2026-06-02): 共通フロントエンドロジック.
// /comment と /comments/archive の両画面で使う auth + fetch + form 処理.

(function () {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function setStatus(el, msg, kind) {
    if (!el) return;
    el.textContent = msg || '';
    el.classList.remove('tc-error', 'tc-success');
    if (kind === 'error') el.classList.add('tc-error');
    else if (kind === 'success') el.classList.add('tc-success');
  }

  function todayISO() {
    const d = new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  }

  function parseQueryDate(name) {
    const params = new URLSearchParams(window.location.search);
    return params.get(name);
  }

  function formatJaDate(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
    if (!m) return iso;
    return `${m[1]}年${parseInt(m[2], 10)}月${parseInt(m[3], 10)}日`;
  }

  async function postJson(path, body) {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      credentials: 'same-origin',
    });
    let data = null;
    try { data = await res.json(); } catch {}
    return { ok: res.ok, status: res.status, data };
  }

  async function getJson(path) {
    const res = await fetch(path, {
      method: 'GET',
      credentials: 'same-origin',
    });
    let data = null;
    try { data = await res.json(); } catch {}
    return { ok: res.ok, status: res.status, data };
  }

  // ---------- Comment edit page ----------

  async function initCommentPage() {
    const authForm = $('#tc-auth-form');
    const editForm = $('#tc-edit-form');
    const authStatus = $('#tc-auth-status');
    const editStatus = $('#tc-edit-status');
    const textarea = $('#tc-textarea');
    const dateLabel = $('#tc-date-label');
    const shaInput = $('#tc-sha');

    const date = parseQueryDate('date') || todayISO();
    if (dateLabel) dateLabel.textContent = formatJaDate(date);
    const dateInput = $('#tc-date');
    if (dateInput) dateInput.value = date;

    async function loadCurrentComment() {
      setStatus(editStatus, '取得中…');
      const { ok, status, data } = await getJson(`/api/comments?date=${encodeURIComponent(date)}`);
      if (status === 401) {
        showAuth();
        return;
      }
      if (!ok) {
        setStatus(editStatus, '取得に失敗しました（' + (data && data.error || status) + '）', 'error');
        return;
      }
      textarea.value = (data && data.content) || '';
      if (shaInput) shaInput.value = (data && data.sha) || '';
      setStatus(editStatus, data.content ? '既存コメントを読み込みました（編集モード）' : '本日のコメント未投稿（新規モード）');
    }

    function showAuth() {
      authForm && authForm.classList.remove('tc-hidden');
      editForm && editForm.classList.add('tc-hidden');
    }
    function showEdit() {
      authForm && authForm.classList.add('tc-hidden');
      editForm && editForm.classList.remove('tc-hidden');
    }

    if (authForm) {
      authForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const pw = $('#tc-password').value;
        setStatus(authStatus, '認証中…');
        const { ok, status, data } = await postJson('/api/auth', { password: pw });
        if (ok) {
          setStatus(authStatus, '');
          showEdit();
          loadCurrentComment();
        } else if (status === 429) {
          setStatus(authStatus, 'リクエストが多すぎます。少し待ってから再試行してください。', 'error');
        } else {
          setStatus(authStatus, 'パスワードが違います。', 'error');
        }
      });
    }

    if (editForm) {
      editForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const content = textarea.value;
        const sha = shaInput ? shaInput.value : '';
        setStatus(editStatus, '投稿中…');
        const { ok, status, data } = await postJson('/api/comments', {
          date,
          content,
          sha: sha || undefined,
        });
        if (ok) {
          setStatus(editStatus, '投稿しました（' + (data && data.sha ? data.sha.slice(0, 8) : '') + '）', 'success');
          if (shaInput && data && data.sha) shaInput.value = data.sha;
        } else if (status === 401) {
          showAuth();
        } else if (status === 429) {
          setStatus(editStatus, '連投ガード中です。10 秒ほど待ってから再試行してください。', 'error');
        } else {
          setStatus(editStatus, '投稿に失敗しました（' + (data && data.error || status) + '）', 'error');
        }
      });
    }

    // Try fetching first; if 401, fall back to auth form.
    const probe = await getJson(`/api/comments?date=${encodeURIComponent(date)}`);
    if (probe.status === 401) {
      showAuth();
    } else {
      showEdit();
      textarea.value = (probe.data && probe.data.content) || '';
      if (shaInput) shaInput.value = (probe.data && probe.data.sha) || '';
      setStatus(editStatus, probe.data && probe.data.content
        ? '既存コメントを読み込みました（編集モード）'
        : '本日のコメント未投稿（新規モード）');
    }
  }

  // ---------- Archive list page ----------

  async function initArchivePage() {
    const authForm = $('#tc-auth-form');
    const listSection = $('#tc-archive');
    const listEl = $('#tc-list');
    const previewEl = $('#tc-preview');
    const previewMeta = $('#tc-preview-meta');
    const authStatus = $('#tc-auth-status');
    const listStatus = $('#tc-list-status');

    function showAuth() {
      authForm && authForm.classList.remove('tc-hidden');
      listSection && listSection.classList.add('tc-hidden');
    }
    function showList() {
      authForm && authForm.classList.add('tc-hidden');
      listSection && listSection.classList.remove('tc-hidden');
    }

    async function loadList() {
      setStatus(listStatus, '一覧を取得中…');
      const { ok, status, data } = await getJson('/api/comments-list');
      if (status === 401) { showAuth(); return; }
      if (!ok) {
        setStatus(listStatus, '取得失敗（' + (data && data.error || status) + '）', 'error');
        return;
      }
      const today = todayISO();
      listEl.replaceChildren();
      for (const entry of (data.dates || [])) {
        const li = document.createElement('li');
        const dateSpan = document.createElement('span');
        dateSpan.className = 'tc-date';
        dateSpan.textContent = entry.date;
        li.appendChild(dateSpan);
        const sizeSpan = document.createElement('span');
        sizeSpan.className = 'tc-size';
        sizeSpan.textContent = entry.size + ' bytes';
        li.appendChild(sizeSpan);
        if (entry.size === 0) {
          const empty = document.createElement('span');
          empty.className = 'tc-empty-flag';
          empty.textContent = '（空）';
          li.appendChild(empty);
        }
        const view = document.createElement('a');
        view.href = '#';
        view.className = 'tc-view-link';
        view.textContent = '閲覧';
        view.addEventListener('click', (e) => {
          e.preventDefault();
          loadPreview(entry.date);
        });
        li.appendChild(view);
        if (entry.date === today) {
          const edit = document.createElement('a');
          edit.href = '/comment?date=' + encodeURIComponent(entry.date);
          edit.className = 'tc-edit-link';
          edit.textContent = '編集';
          li.appendChild(edit);
        }
        listEl.appendChild(li);
      }
      setStatus(listStatus, data.total ? `${data.total} 件` : '該当なし');
    }

    async function loadPreview(date) {
      setStatus(listStatus, '本文を取得中…');
      const { ok, status, data } = await getJson(`/api/comments?date=${encodeURIComponent(date)}`);
      if (status === 401) { showAuth(); return; }
      if (!ok) {
        setStatus(listStatus, '取得失敗', 'error');
        return;
      }
      previewMeta.textContent = formatJaDate(date) + '（' + (data.content ? data.content.length + ' 字' : '空') + '）';
      previewEl.textContent = data.content || '（このファイルは空です）';
      previewEl.classList.remove('tc-hidden');
      setStatus(listStatus, '');
    }

    if (authForm) {
      authForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const pw = $('#tc-password').value;
        setStatus(authStatus, '認証中…');
        const { ok, status } = await postJson('/api/auth', { password: pw });
        if (ok) {
          setStatus(authStatus, '');
          showList();
          loadList();
        } else if (status === 429) {
          setStatus(authStatus, 'リクエストが多すぎます。', 'error');
        } else {
          setStatus(authStatus, 'パスワードが違います。', 'error');
        }
      });
    }

    const probe = await getJson('/api/comments-list');
    if (probe.status === 401) {
      showAuth();
    } else {
      showList();
      const today = todayISO();
      listEl.replaceChildren();
      for (const entry of (probe.data && probe.data.dates) || []) {
        const li = document.createElement('li');
        const dateSpan = document.createElement('span');
        dateSpan.className = 'tc-date';
        dateSpan.textContent = entry.date;
        li.appendChild(dateSpan);
        const sizeSpan = document.createElement('span');
        sizeSpan.className = 'tc-size';
        sizeSpan.textContent = entry.size + ' bytes';
        li.appendChild(sizeSpan);
        if (entry.size === 0) {
          const empty = document.createElement('span');
          empty.className = 'tc-empty-flag';
          empty.textContent = '（空）';
          li.appendChild(empty);
        }
        const view = document.createElement('a');
        view.href = '#';
        view.className = 'tc-view-link';
        view.textContent = '閲覧';
        view.addEventListener('click', (e) => {
          e.preventDefault();
          loadPreview(entry.date);
        });
        li.appendChild(view);
        if (entry.date === today) {
          const edit = document.createElement('a');
          edit.href = '/comment?date=' + encodeURIComponent(entry.date);
          edit.className = 'tc-edit-link';
          edit.textContent = '編集';
          li.appendChild(edit);
        }
        listEl.appendChild(li);
      }
      setStatus(listStatus, (probe.data && probe.data.total) ? `${probe.data.total} 件` : '該当なし');
    }
  }

  window.TribuneComment = {
    initCommentPage,
    initArchivePage,
  };
})();
