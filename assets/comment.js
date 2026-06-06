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

  // ---------- AI draft panel (C57, Sprint 9, 2026-06-03 / C64 改善 2026-06-06) ----------

  // 対話履歴はクライアント保持（サーバーステートレス）。リロードで消える。
  const aiState = {
    history: [],          // [{role, content}] — Anthropic 呼び出しに使う配列
    lastAi: null,         // 最新の AI メッセージ（採用ボタン用 fallback）
    displaySeed: null,    // C64 Fix 1: 初回 user_draft の表示用 string（無ければ null）
    essayUnavailable: false,  // C64 Fix 1B: 当日論考取得失敗フラグ
    inFlight: false,
    initialized: false,
    date: null,
  };

  // C64 Fix 1: <<user_text>>, <<essay>>, <<past_comments>> など、prompt 内部
  // 構造を UI 露出させない目的で、user メッセージのクリーンアップは regex で。
  // この regex は 表示上の整形のためだけに使い、内部の history[].content には
  // 区切り付き原文をそのまま保持して Anthropic に送り続ける（injection 防御維持）。
  const _USER_TEXT_RE = /<<\/?user_text>>/g;

  function _appendMessage(container, role, content) {
    const wrap = document.createElement('div');
    wrap.className = 'tc-ai-msg tc-ai-msg-' + role;
    const label = document.createElement('div');
    label.className = 'tc-ai-msg-label';
    label.textContent = role === 'assistant' ? 'AI' : '神山さん';
    const body = document.createElement('div');
    body.className = 'tc-ai-msg-body';
    body.textContent = content;
    wrap.appendChild(label);
    wrap.appendChild(body);
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
  }

  // C64 Fix 3: 最新の AI 提案を編集可能な textarea として描画する。
  // 神山さんが採用前に直接微修正できるので、修正フローが 1 ステップ短縮。
  // ID 'tc-ai-edit-area' を持ち、_adoptToTextarea が値を読みに行く。
  function _appendEditableAi(container, content) {
    const wrap = document.createElement('div');
    wrap.className = 'tc-ai-msg tc-ai-msg-assistant tc-ai-msg-editable';
    const label = document.createElement('div');
    label.className = 'tc-ai-msg-label';
    label.textContent = 'AI（編集可：採用前に直接修正できます）';
    const ta = document.createElement('textarea');
    ta.className = 'tc-ai-edit-area';
    ta.id = 'tc-ai-edit-area';
    ta.value = content;
    ta.spellcheck = false;
    wrap.appendChild(label);
    wrap.appendChild(ta);
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
  }

  function _renderHistory(container) {
    container.replaceChildren();
    // C64 Fix 1A: 初回 user メッセージ（seed_user_message）は context
    // 注入用なので UI に出さない。代わりに displaySeed（神山さん本人が
    // textarea に入れた骨子）があればそれを「神山さん」発話として表示。
    if (aiState.displaySeed) {
      _appendMessage(container, 'user', aiState.displaySeed);
    }
    // C64 Fix 1B: essay 取得失敗時のユーザー向けヒント
    if (aiState.essayUnavailable) {
      const hint = document.createElement('div');
      hint.className = 'tc-ai-essay-hint';
      hint.textContent = '当日の論考を取得できませんでした。コメントの骨子を直接入力すると、AI が膨らませる方向で支援します。';
      container.appendChild(hint);
    }
    const total = aiState.history.length;
    for (let i = 0; i < total; i++) {
      const m = aiState.history[i];
      // 先頭の user (seed_user_message) は表示しない（context 注入用）。
      if (i === 0 && m.role === 'user') continue;
      const isLast = (i === total - 1);
      let content = m.content;
      if (m.role === 'user') {
        content = content.replace(_USER_TEXT_RE, '').trim();
      }
      // C64 Fix 3: 最新の assistant メッセージは編集可 textarea で表示。
      if (isLast && m.role === 'assistant') {
        _appendEditableAi(container, content);
      } else {
        _appendMessage(container, m.role, content);
      }
    }
  }

  function _setAdoptEnabled(enabled) {
    const btn = document.getElementById('tc-ai-adopt');
    if (btn) btn.disabled = !enabled;
  }

  function _setInFlight(flag, statusEl) {
    aiState.inFlight = flag;
    const send = document.getElementById('tc-ai-send');
    if (send) send.disabled = flag;
    if (flag) setStatus(statusEl, '生成中… 3-8 秒お待ちください');
    else setStatus(statusEl, '');
  }

  async function _initAiDraft(date, statusEl, container) {
    if (aiState.inFlight) return;
    _setInFlight(true, statusEl);
    const textarea = $('#tc-textarea');
    const userDraft = textarea ? textarea.value : '';
    const { ok, status, data } = await postJson('/api/ai-draft', {
      action: 'init', date, user_draft: userDraft,
    });
    if (!ok) {
      _setInFlight(false, statusEl);
      if (status === 401) {
        setStatus(statusEl, '認証切れです。リロードしてください。', 'error');
        return;
      }
      if (status === 429) {
        setStatus(statusEl, '少し待ってから再試行してください。', 'error');
        return;
      }
      setStatus(statusEl, '初稿生成に失敗しました（' + (data && data.error || status) + '）', 'error');
      return;
    }
    // 履歴に seed_user_message と ai_message を積む。seed は内部用、UI には
    // displaySeed（神山さん本人が入れた骨子）だけを user 発話として出す。
    aiState.history = [
      { role: 'user', content: data.seed_user_message || '【当日論考】（初期化）' },
      { role: 'assistant', content: data.ai_message },
    ];
    aiState.lastAi = data.ai_message;
    aiState.displaySeed = data.user_draft_displayed || null;
    aiState.essayUnavailable = !!data.essay_unavailable;
    aiState.initialized = true;
    _renderHistory(container);
    _setAdoptEnabled(true);
    _setInFlight(false, statusEl);
    if (aiState.essayUnavailable) {
      setStatus(statusEl, '当日論考の取得に失敗しましたが、初稿を提示しました。');
    } else {
      setStatus(statusEl, '初稿提示。修正したい場合はメッセージを入力 → 送信。');
    }
  }

  async function _continueAiDraft(date, message, statusEl, container) {
    if (aiState.inFlight) return;
    if (!message.trim()) {
      setStatus(statusEl, 'メッセージを入力してください。', 'error');
      return;
    }
    _setInFlight(true, statusEl);
    const { ok, status, data } = await postJson('/api/ai-draft', {
      action: 'continue', date, history: aiState.history, message,
    });
    if (!ok) {
      _setInFlight(false, statusEl);
      if (status === 401) {
        setStatus(statusEl, '認証切れです。リロードしてください。', 'error');
        return;
      }
      if (status === 429) {
        setStatus(statusEl, '少し待ってから再試行してください。', 'error');
        return;
      }
      setStatus(statusEl, '応答生成に失敗しました（' + (data && data.error || status) + '）', 'error');
      return;
    }
    aiState.history.push({ role: 'user', content: message });
    aiState.history.push({ role: 'assistant', content: data.ai_message });
    aiState.lastAi = data.ai_message;
    _renderHistory(container);
    _setAdoptEnabled(true);
    _setInFlight(false, statusEl);
    if (data.truncated) {
      setStatus(statusEl, '対話が長くなったため古い往復を一部省略しました。');
    }
  }

  function _resetAi(container, statusEl) {
    aiState.history = [];
    aiState.lastAi = null;
    aiState.displaySeed = null;
    aiState.essayUnavailable = false;
    aiState.initialized = false;
    container.replaceChildren();
    _setAdoptEnabled(false);
    setStatus(statusEl, '履歴をリセットしました。');
  }

  function _adoptToTextarea(statusEl) {
    const textarea = $('#tc-textarea');
    if (!textarea) return;
    // C64 Fix 3: 編集可能 textarea (tc-ai-edit-area) の現在値を優先して読む。
    // 神山さんが採用前にした微修正もそのまま採用される。textarea が DOM 上に
    // 無いとき (初期化前 / 描画後に置換) は aiState.lastAi にフォールバック。
    const editArea = document.getElementById('tc-ai-edit-area');
    const aiContent = (editArea ? editArea.value : aiState.lastAi) || '';
    if (!aiContent.trim()) return;
    const existing = textarea.value.trim();
    if (existing && existing !== aiContent.trim()) {
      const ok = window.confirm(
        '既存のコメント内容を AI 提案で上書きします。よろしいですか？\n\n（既存内容は失われます）'
      );
      if (!ok) return;
    }
    textarea.value = aiContent;
    textarea.focus();
    setStatus(statusEl, 'textarea に反映しました。必要に応じて編集してください。', 'success');
  }

  function initAiPanel(date) {
    const panel = document.getElementById('tc-ai-panel');
    const toggle = document.getElementById('tc-ai-toggle');
    const closeBtn = document.getElementById('tc-ai-close');
    const sendBtn = document.getElementById('tc-ai-send');
    const adoptBtn = document.getElementById('tc-ai-adopt');
    const resetBtn = document.getElementById('tc-ai-reset');
    const inputEl = document.getElementById('tc-ai-input');
    const messagesEl = document.getElementById('tc-ai-messages');
    const statusEl = document.getElementById('tc-ai-status');
    if (!panel || !toggle) return;

    aiState.date = date;

    toggle.addEventListener('click', async () => {
      panel.classList.remove('tc-hidden');
      panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
      if (!aiState.initialized) {
        await _initAiDraft(date, statusEl, messagesEl);
      }
    });

    if (closeBtn) {
      closeBtn.addEventListener('click', () => {
        panel.classList.add('tc-hidden');
      });
    }

    if (sendBtn) {
      sendBtn.addEventListener('click', async () => {
        const msg = inputEl.value;
        if (!msg.trim()) return;
        await _continueAiDraft(date, msg, statusEl, messagesEl);
        inputEl.value = '';
      });
    }

    if (adoptBtn) {
      adoptBtn.addEventListener('click', () => _adoptToTextarea(statusEl));
    }

    if (resetBtn) {
      resetBtn.addEventListener('click', () => {
        if (aiState.history.length > 0
            && !window.confirm('対話履歴をすべて消去します。よろしいですか？')) return;
        _resetAi(messagesEl, statusEl);
      });
    }
  }

  // Hook into initCommentPage
  const _origInitCommentPage = initCommentPage;
  async function initCommentPageWithAi() {
    await _origInitCommentPage();
    const date = parseQueryDate('date') || todayISO();
    initAiPanel(date);
  }

  window.TribuneComment = {
    initCommentPage: initCommentPageWithAi,
    initArchivePage,
  };
})();
