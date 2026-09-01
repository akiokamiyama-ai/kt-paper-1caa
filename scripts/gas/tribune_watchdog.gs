  /**
  * Kamiyama Tribune — 朝刊未発行の検知（C186, 2026-08-29）
  * =============================================================================
  *
  * 背景
  * ----
  * GitHub Actions の schedule は実行が保証されず、負荷時は遅延またはスキップ
  * される。2026-08 の実測:
  *
  *   8/23-8/26  +14〜+24 分（正常域）
  *   8/27       +107 分
  *   8/28       schedule が +8 時間遅延し、手動実行の後に発火（二重実行）
  *
  * 現状「神山さんが朝刊の不在に気づく」以外の検知経路が無い。気づかなければ
  * その日は欠号になる。本スクリプトはそれを埋める。
  *
  * 設計方針
  * --------
  * - **認証情報を一切持たない**。リポジトリが PUBLIC なので読み取りだけで済む。
  *   GitHub REST API（contents）は未認証だと 60 req/時/IP の制限があり、GAS は
  *   Google の共有 IP から出るため 403 を踏みうる。よって raw.githubusercontent
  *   と GitHub Pages の**素の GET** だけを使う。
  * - **2 層で見て切り分ける**。
  *     生成されたか  = raw.githubusercontent に archive/<日付>.html があるか
  *     発行されたか  = 公開サイトの index.html の data-date が当日か
  *   これで「未生成」と「生成済みだがデプロイ未反映」を区別できる
  *   （後者は 2026-06-23 に実際に起きている。daily.yml の C93 コメント参照）。
  * - **正常時は無通知**。異常時のみメール。
  * - 宛先はコードに書かない（このリポジトリは PUBLIC）。既定でスクリプト所有者
  *   自身に送る。
  */

  // ============================================================================
  // 設定
  // ============================================================================

  /**
  * 検知時刻の根拠（archive commit の実着弾時刻、JST、2026-08-15〜08-28）:
  *
  *   03:05 03:06 03:07 03:07 03:17 03:21 03:23 03:24 03:25 03:26 03:27 03:50
  *   04:44 （8/27、+107 分の遅延）
  *   09:07 / 11:10 （8/28、手動 + 遅延 schedule の二重実行）
  *
  * 通常の最遅は 03:50、自動での最遅は 04:44。神山さんの起床は 6:30
  * （daily.yml の cron コメント）。
  *
  *   03:30 → 通常時ですら間に合わない日がある。誤検知が多すぎる
  *   05:30 → 通常最遅から +100 分、自動最遅から +46 分、起床の 60 分前  ★既定
  *   07:00 → 余裕は最大だが、起床後なので神山さんが先に気づく
  *
  * 「遅延は後から出る」ので早すぎる検知は「まだ出てないだけ」を拾う。逆に
  * 遅すぎると通知の意味が無い。05:30 なら直近 14 日で誤検知ゼロだった。
  *
  * GAS の時間トリガーは指定時刻から ±15 分のブレがある（仕様）。05:30 指定なら
  * 実際の発火は 05:15〜05:45。上の余裕はこのブレを吸収できる幅にしてある。
  */
  //
  // C191 (2026-09-01): 09-01 05:30 に初の実戦発火。ただし run は遅れて起動中
  // （07:00 起動 / 07:25 着弾）で、実際には待てばよい状況だった。archive の
  // 有無しか見ていないと「遅延中」と「本当に止まった」を区別できず、誤検知が
  // 続けばメールを無視するようになる。fetchRunState_ で run 状態を見て文面を
  // 出し分ける。
  //
  // 検知時刻は配列。複数入れるとその数だけトリガーが作られる。
  //   [[5, 30]]          … 1 日 1 回（既定）
  //   [[5, 30], [8, 0]]  … 早期警戒 + 確定の 2 段
  // C192 (2026-09-01): 2 段構えを既定にした。05:30 は早期警戒（多くは
  // 「実行中」か「まだ起動していない」）、08:00 は確定（この時刻に出ていな
  // ければ本当に手を打つ）。神山さんの方針は「知らせてほしい」なので、
  // in_progress でも 05:30 に送る。
  var CHECK_TIMES = [[5, 30], [8, 0]];

  // 後方互換（ログ表示用）。CHECK_TIMES の先頭を指す。
  var CHECK_HOUR = CHECK_TIMES[0][0];
  var CHECK_MINUTE = CHECK_TIMES[0][1];

  // daily.yml の cron 予定時刻（UTC）。`37 17 * * *`。遅延の算出に使う。
  var CRON_UTC_HOUR = 17;
  var CRON_UTC_MINUTE = 37;

  // 通常ランの所要時間（分）。「あと何分くらい」の目安。
  var TYPICAL_RUN_MINUTES = 30;

  // ---------------------------------------------------------------------
  // C192 (2026-09-01): 起動も GAS から行う（Phase 2）
  //
  // 2026-08 後半から GitHub Actions の schedule 遅延が +107〜+480 分に悪化し
  // （9/1 は +264 分 / 07:25 着弾）、検知を精緻にするより起動を外部へ移す方が
  // 根本的と判断した。daily.yml の schedule は**残す**——GAS / Google 側が
  // 落ちたときの保険になり、二重に起動しても C185 のガードが skip するため。
  // ---------------------------------------------------------------------

  // 起動時刻（JST）。daily.yml の cron と同じ 02:37 に合わせる。
  var DISPATCH_TIME = [2, 37];

  // Script Properties のキー名。**PAT はコードに書かない**（PUBLIC リポジトリ）。
  //   GITHUB_PAT     … fine-grained PAT（対象リポジトリのみ / Actions: write）
  //   PAT_EXPIRY     … 有効期限 YYYY-MM-DD（任意。期限前に警告を出すため）
  var PROP_PAT = 'GITHUB_PAT';
  var PROP_PAT_EXPIRY = 'PAT_EXPIRY';

  // 有効期限の何日前から警告するか。PAT 切れは「静かに止まる」典型
  // （C173 パターン）なので、切れる前に気づけるようにする。
  var PAT_EXPIRY_WARN_DAYS = 14;

  // 監視対象のワークフローファイル名。runs 一覧には
  // "pages build and deployment" も混ざるため、workflow 指定で取る。
  var WORKFLOW_FILE = 'daily.yml';

  /** GitHub リポジトリ（PUBLIC）。 */
  var GH_OWNER = 'akiokamiyama-ai';
  var GH_REPO = 'kt-paper-1caa';
  var GH_BRANCH = 'main';

  /**
  * 公開サイト（「発行されたか」の判定先）。
  * 神山さんが実際に読んでいる面を指すこと。Vercel を主に読んでいるなら
  * その URL に差し替える（末尾スラッシュあり）。
  */
  var PUBLISHED_URL = 'https://akiokamiyama-ai.github.io/kt-paper-1caa/';

  /**
  * 通知先。空なら**スクリプト所有者自身**に送る。
  * このリポジトリは PUBLIC なのでメールアドレスをコードに書かないこと。
  * 別の宛先にしたい場合は GAS の
  *   プロジェクトの設定 → スクリプト プロパティ → NOTIFY_EMAIL
  * に設定する。
  */
  function resolveRecipient_() {
    var override = PropertiesService.getScriptProperties().getProperty('NOTIFY_EMAIL');
    if (override) return override;
    return Session.getEffectiveUser().getEmail();
  }

  // ============================================================================
  // 本体
  // ============================================================================

  /** トリガーから呼ばれるエントリポイント。 */
  function checkTribune() {
    var today = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd');
    var result = inspect_(today);
    Logger.log(JSON.stringify(result));

    if (result.generated && result.published) {
      return; // 正常。無通知。
    }
    // C191: 未生成のときだけ run 状態を取りにいく（正常時は API を叩かない）。
    result.run = fetchRunState_(today);
    Logger.log('run: ' + JSON.stringify(result.run));
    notifyOnce_(today, result);
  }

  /**
  * 当日の紙面の状態を調べる。
  * @return {{generated: boolean, published: boolean, publishedDate: string,
  *           archiveStatus: number, siteStatus: number, error: string}}
  */
  function inspect_(today) {
    var out = {
      generated: false, published: false, publishedDate: '',
      archiveStatus: 0, siteStatus: 0, error: ''
    };

    // 1) 生成されたか — archive/<日付>.html が main にあるか
    var rawUrl = 'https://raw.githubusercontent.com/' + GH_OWNER + '/' + GH_REPO +
                '/' + GH_BRANCH + '/archive/' + today + '.html';
    var a = fetchWithRetry_(rawUrl);
    out.archiveStatus = a.status;
    if (a.error) { out.error += 'archive: ' + a.error + ' '; }
    out.generated = (a.status === 200);

    // 2) 発行されたか — 公開サイトの index.html が当日を指しているか
    var s = fetchWithRetry_(PUBLISHED_URL);
    out.siteStatus = s.status;
    if (s.error) { out.error += 'site: ' + s.error + ' '; }
    if (s.status === 200 && s.body) {
      var m = s.body.match(/data-date="(\d{4}-\d{2}-\d{2})"/);
      if (m) {
        out.publishedDate = m[1];
        out.published = (m[1] === today);
      }
    }
    return out;
  }

  /**
  * 当日ぶんの Daily Tribune Generation の run 状態を取る（C191）。
  *
  * リポジトリが PUBLIC なので未認証で読める（60 req/時/IP の制限があるが
  * 1 日 1-2 回なので当たらない）。取得に失敗したら state='unknown' を返し、
  * 呼び出し側は従来の文面にフォールバックする。
  *
  * 「当日ぶん」の判定: workflow は実行時に JST の当日を紙面日付にするので、
  * run の created_at を JST に直した日付が today と一致するものを探す。
  *
  * @return {{state: string, startedJst: string, elapsedMin: number,
  *           url: string, event: string, recentDelayMin: number, error: string}}
  *   state は 'in_progress' | 'queued' | 'failed' | 'success' | 'none' | 'unknown'
  */
  function fetchRunState_(today) {
    var out = {state: 'unknown', startedJst: '', elapsedMin: 0, url: '',
               event: '', recentDelayMin: 0, error: ''};
    var url = 'https://api.github.com/repos/' + GH_OWNER + '/' + GH_REPO +
              '/actions/workflows/' + WORKFLOW_FILE + '/runs?per_page=20';
    var res = fetchWithRetry_(url);
    if (res.status !== 200 || !res.body) {
      out.error = res.error || ('HTTP ' + res.status);
      return out;
    }
    var data;
    try {
      data = JSON.parse(res.body);
    } catch (e) {
      out.error = 'JSON parse: ' + String(e);
      return out;
    }
    var runs = (data && data.workflow_runs) || [];

    // 直近の schedule 起動の遅延（中央値）を出す。まだ起動していないときに
    // 「最近はこれくらい遅れている」を示すため。
    out.recentDelayMin = medianScheduleDelay_(runs);

    var mine = null;
    for (var i = 0; i < runs.length; i++) {
      var created = new Date(runs[i].created_at);
      if (Utilities.formatDate(created, 'Asia/Tokyo', 'yyyy-MM-dd') === today) {
        mine = runs[i];   // 一覧は新しい順。最初に当たったものが最新。
        break;
      }
    }
    if (!mine) {
      out.state = 'none';
      return out;
    }

    var started = new Date(mine.created_at);
    out.startedJst = Utilities.formatDate(started, 'Asia/Tokyo', 'HH:mm');
    out.elapsedMin = Math.round((new Date().getTime() - started.getTime()) / 60000);
    out.url = mine.html_url || '';
    out.event = mine.event || '';

    if (mine.status !== 'completed') {
      out.state = (mine.status === 'queued' || mine.status === 'waiting')
                  ? 'queued' : 'in_progress';
    } else if (mine.conclusion === 'success') {
      out.state = 'success';
    } else {
      out.state = 'failed';
      out.conclusion = mine.conclusion;
    }
    return out;
  }

  /** 直近の schedule 起動が cron 予定からどれだけ遅れたかの中央値（分）。 */
  function medianScheduleDelay_(runs) {
    var delays = [];
    for (var i = 0; i < runs.length && delays.length < 7; i++) {
      if (runs[i].event !== 'schedule') continue;
      var c = new Date(runs[i].created_at);
      var sched = new Date(Date.UTC(c.getUTCFullYear(), c.getUTCMonth(),
                                    c.getUTCDate(), CRON_UTC_HOUR, CRON_UTC_MINUTE));
      if (c.getTime() < sched.getTime()) sched.setUTCDate(sched.getUTCDate() - 1);
      delays.push(Math.round((c.getTime() - sched.getTime()) / 60000));
    }
    if (!delays.length) return 0;
    delays.sort(function (a, b) { return a - b; });
    return delays[Math.floor(delays.length / 2)];
  }

  /**
  * 一時的なネットワーク障害で誤検知しないよう、失敗時のみ 1 回だけ間を置いて
  * 再試行する。**遅延して後から出るケースの吸収は再試行ではなく検知時刻
  * （CHECK_HOUR）で行う**ので、ここは長く待たない。
  */
  function fetchWithRetry_(url) {
    for (var i = 0; i < 2; i++) {
      try {
        var res = UrlFetchApp.fetch(url, {
          muteHttpExceptions: true,
          followRedirects: true,
          validateHttpsCertificates: true
        });
        var code = res.getResponseCode();
        // 404 は「無い」という確定した答えなので再試行しない。
        if (code === 200 || code === 404) {
          return { status: code, body: code === 200 ? res.getContentText() : '', error: '' };
        }
        if (i === 0) { Utilities.sleep(5000); continue; }
        return { status: code, body: '', error: 'HTTP ' + code };
      } catch (e) {
        if (i === 0) { Utilities.sleep(5000); continue; }
        return { status: 0, body: '', error: String(e) };
      }
    }
    return { status: 0, body: '', error: 'unreachable' };
  }

  /** 同じ日に何度も送らない（手動実行やトリガー重複への保険）。 */
  function notifyOnce_(today, result) {
    var props = PropertiesService.getScriptProperties();
    if (props.getProperty('lastNotified') === today) {
      Logger.log('already notified for ' + today);
      return;
    }
    MailApp.sendEmail({
      to: resolveRecipient_(),
      subject: buildSubject_(today, result),
      body: buildBody_(today, result)
    });
    props.setProperty('lastNotified', today);
  }

  function buildSubject_(today, result) {
    if (result.generated) {
      return '[Tribune] ' + today + ' の朝刊が未反映です（生成は済）';
    }
    // C191: run 状態で件名を変える。「実行中」は行動不要なので区別する。
    var st = result.run && result.run.state;
    if (st === 'in_progress' || st === 'queued') {
      return '[Tribune] ' + today + ' の朝刊は実行中です（対応不要）';
    }
    if (st === 'failed') {
      return '[Tribune] ' + today + ' の朝刊の生成が失敗しました';
    }
    if (st === 'none') {
      return '[Tribune] ' + today + ' の朝刊がまだ起動していません';
    }
    return '[Tribune] ' + today + ' の朝刊が未生成です';
  }

  /** run 状態を 1 行の日本語にする（C191）。 */
  function describeRun_(run) {
    switch (run.state) {
      case 'in_progress':
        return '実行中（' + run.startedJst + ' 開始、経過 ' + run.elapsedMin + ' 分' +
               (run.event === 'workflow_dispatch' ? '、手動起動' : '') + '）';
      case 'queued':
        return '順番待ち（' + run.startedJst + ' 作成、経過 ' + run.elapsedMin + ' 分）';
      case 'failed':
        return '失敗（' + run.startedJst + ' 開始、' + (run.conclusion || 'failure') + '）';
      case 'success':
        return '完了済み（' + run.startedJst + ' 開始）。反映待ちの可能性があります';
      case 'none':
        return '本日ぶんの実行がまだありません';
      default:
        return '取得できませんでした' + (run.error ? '（' + run.error + '）' : '');
    }
  }

  /** 手動実行の手順（C191 で共通化）。 */
  function pushManualSteps_(L) {
    L.push('【対処】手動で実行してください');
    L.push('  1. https://github.com/' + GH_OWNER + '/' + GH_REPO + '/actions');
    L.push('  2. 左メニューの「Daily Tribune Generation」を選ぶ');
    L.push('  3. 右上の「Run workflow」→ Branch: ' + GH_BRANCH + ' → Run workflow');
    L.push('     ※ 既に当日分が出ている場合は二重実行ガード（C185）が働いて');
    L.push('       skip されます。意図的に作り直すときだけ force を true に。');
    L.push('  4. 完走まで約 ' + TYPICAL_RUN_MINUTES + ' 分です。');
  }

  function buildBody_(today, result) {
    var L = [];
    L.push(today + ' 朝の Kamiyama Tribune が確認できませんでした。');
    L.push('');
    L.push('【状態】');
    L.push('  生成（リポジトリ） : ' + (result.generated ? 'OK' : '未生成') +
          '  [HTTP ' + result.archiveStatus + ']');
    L.push('  発行（公開サイト） : ' + (result.published ? 'OK' : '未反映') +
          '  [HTTP ' + result.siteStatus +
          (result.publishedDate ? ' / 表示中: ' + result.publishedDate : '') + ']');
    if (result.error) L.push('  取得エラー         : ' + result.error);
    L.push('');

    if (!result.generated) {
      var run = result.run || {state: 'unknown'};
      L.push('【Actions の状態】' + describeRun_(run));
      L.push('');

      if (run.state === 'in_progress' || run.state === 'queued') {
        // 待てば済む。手動実行を促さない（誤って二重実行させないため）。
        var remain = Math.max(0, TYPICAL_RUN_MINUTES - (run.elapsedMin || 0));
        L.push('【対処】不要です。しばらく待ってください');
        L.push('  通常 ' + TYPICAL_RUN_MINUTES + ' 分ほどで完了します' +
               (remain > 0 ? '（残り目安 ' + remain + ' 分）' : '（まもなく完了見込み）') + '。');
        L.push('  完了すると公開サイトに反映されます。');
        if (run.url) L.push('  実行状況: ' + run.url);
        L.push('');
        L.push('  ※ この時点で手動実行しても、二重実行ガード（C185）が働いて');
        L.push('    skip されます。作り直したいとき以外は不要です。');
      } else if (run.state === 'failed') {
        L.push('【原因の見当】');
        L.push('  生成そのものが失敗しています（' + (run.conclusion || 'failure') + '）。');
        L.push('  ログを見て原因を確認してください。');
        L.push('');
        if (run.url) L.push('  失敗した実行: ' + run.url);
        L.push('');
        pushManualSteps_(L);
      } else if (run.state === 'none') {
        L.push('【原因の見当】');
        L.push('  本日ぶんの実行がまだ作成されていません。GitHub Actions の');
        L.push('  schedule は実行が保証されず、負荷時は遅延またはスキップされます。');
        if (run.recentDelayMin) {
          L.push('  直近の起動は cron 予定から中央値 +' + run.recentDelayMin + ' 分ずれています。');
          L.push('  この傾向なら、まだ後から起動する可能性があります。');
        }
        L.push('');
        L.push('  ※ 2026-08 下旬から遅延が常態化しています（+141 分 / +143 分 /');
        L.push('    +264 分）。しばらく待って再確認する方が安全な場合があります。');
        L.push('');
        pushManualSteps_(L);
      } else {
        // API が読めなかった等。従来どおり手動実行を促す。
        L.push('【原因の見当】');
        L.push('  Actions の状態を取得できませんでした' +
               (run.error ? '（' + run.error + '）' : '') + '。');
        L.push('  schedule が発火しなかった可能性があります。');
        L.push('');
        pushManualSteps_(L);
      }
    } else {
      L.push('【原因の見当】');
      L.push('  紙面は生成・commit されていますが、公開サイトに反映されていません。');
      L.push('  Vercel / GitHub Pages のデプロイが失敗または遅延している可能性が');
      L.push('  あります（2026-06-23 に同種の事故あり）。');
      L.push('');
      L.push('【対処】');
      L.push('  1. https://github.com/' + GH_OWNER + '/' + GH_REPO + '/actions で');
      L.push('     デプロイ系ワークフローの成否を確認');
      L.push('  2. 必要なら Vercel 側で再デプロイ');
    }
    L.push('');
    L.push('【確認 URL】');
    L.push('  公開サイト : ' + PUBLISHED_URL);
    L.push('  当日の紙面 : https://raw.githubusercontent.com/' + GH_OWNER + '/' +
          GH_REPO + '/' + GH_BRANCH + '/archive/' + today + '.html');
    L.push('');
    L.push('-- Tribune watchdog (C186) / scripts/gas/tribune_watchdog.gs');
    return L.join('\n');
  }

  // ==========================================================================
  // C192: 起動（workflow_dispatch）
  // ==========================================================================

  /**
  * トリガーから呼ばれる起動エントリポイント。
  *
  * schedule と併存させる。二重に起動しても daily.yml の二重実行ガード
  * （C185）が「当日の archive が既にある」を見て skip するので、紙面が
  * 二重に作られることはない。
  */
  function dispatchTribune() {
    var today = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd');

    // 既に出来ていれば起動しない（無駄なランを増やさない）。
    var state = inspect_(today);
    if (state.generated) {
      Logger.log('already generated for ' + today + ', skip dispatch');
      return;
    }

    warnIfPatExpiringSoon_();

    var r = triggerWorkflow_();
    Logger.log('dispatch: ' + JSON.stringify(r));
    if (!r.ok) {
      // 起動できなかったこと自体を必ず知らせる。黙って止まるのが最悪。
      notifyDispatchFailure_(today, r);
    }
  }

  /**
  * workflow_dispatch を POST する。
  * @return {{ok: boolean, status: number, error: string}}
  */
  function triggerWorkflow_() {
    var pat = PropertiesService.getScriptProperties().getProperty(PROP_PAT);
    if (!pat) {
      return {ok: false, status: 0,
              error: 'Script Properties に ' + PROP_PAT + ' がありません'};
    }
    var url = 'https://api.github.com/repos/' + GH_OWNER + '/' + GH_REPO +
              '/actions/workflows/' + WORKFLOW_FILE + '/dispatches';
    try {
      var res = UrlFetchApp.fetch(url, {
        method: 'post',
        contentType: 'application/json',
        muteHttpExceptions: true,
        headers: {
          'Authorization': 'Bearer ' + pat,
          'Accept': 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28'
        },
        // date は空 = 実行時の JST 当日（C192 で daily.yml に追加した input）。
        payload: JSON.stringify({ref: GH_BRANCH, inputs: {}})
      });
      var code = res.getResponseCode();
      if (code === 204) return {ok: true, status: 204, error: ''};
      var body = (res.getContentText() || '').slice(0, 200);
      var hint = '';
      if (code === 401) hint = ' — PAT が無効か期限切れの可能性';
      if (code === 403) hint = ' — PAT の権限不足（Actions: write が要る）';
      if (code === 404) hint = ' — リポジトリ名 / workflow 名 / PAT のスコープを確認';
      return {ok: false, status: code, error: 'HTTP ' + code + hint + ': ' + body};
    } catch (e) {
      return {ok: false, status: 0, error: String(e)};
    }
  }

  /** PAT の有効期限が近ければ知らせる（切れてから気づくのを避ける）。 */
  function warnIfPatExpiringSoon_() {
    var props = PropertiesService.getScriptProperties();
    var expiry = props.getProperty(PROP_PAT_EXPIRY);
    if (!expiry) return;                       // 未設定なら何もしない
    var days = Math.floor(
      (new Date(expiry + 'T00:00:00+09:00').getTime() - new Date().getTime())
      / 86400000);
    if (days > PAT_EXPIRY_WARN_DAYS) return;
    var today = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd');
    if (props.getProperty('lastPatWarn') === today) return;   // 1 日 1 通
    MailApp.sendEmail({
      to: resolveRecipient_(),
      subject: '[Tribune] GitHub PAT の有効期限が近づいています（残り ' + days + ' 日）',
      body: [
        'Tribune の朝刊起動に使っている GitHub PAT が ' + expiry + ' に期限切れになります。',
        '',
        '期限が切れると **朝刊が静かに起動しなくなります**（daily.yml の schedule は',
        '残してあるので完全に止まりはしませんが、遅延の大きい schedule 頼みに戻ります）。',
        '',
        '【更新手順】',
        '  1. https://github.com/settings/personal-access-tokens で新しい',
        '     fine-grained PAT を発行',
        '     - Repository access: ' + GH_OWNER + '/' + GH_REPO + ' のみ',
        '     - Permissions: Actions = Read and write（他は不要）',
        '  2. GAS の プロジェクトの設定 → スクリプト プロパティ で',
        '     ' + PROP_PAT + ' を新しい値に更新',
        '  3. ' + PROP_PAT_EXPIRY + ' も新しい期限（YYYY-MM-DD）に更新',
        '  4. testDispatch を実行して 204 が返ることを確認',
        '',
        '-- Tribune watchdog (C192)'
      ].join('\n')
    });
    props.setProperty('lastPatWarn', today);
  }

  /** 起動に失敗したことを知らせる。 */
  function notifyDispatchFailure_(today, r) {
    var props = PropertiesService.getScriptProperties();
    if (props.getProperty('lastDispatchFail') === today) return;
    MailApp.sendEmail({
      to: resolveRecipient_(),
      subject: '[Tribune] ' + today + ' の朝刊を起動できませんでした',
      body: [
        'GAS からの workflow_dispatch が失敗しました。',
        '',
        '  ' + r.error,
        '',
        'daily.yml の schedule は残してあるので、遅れて自動起動する可能性は',
        'あります（2026-08 下旬以降は +140〜+480 分の遅延が発生しています）。',
        '05:30 / 08:00 の検知メールもあわせて確認してください。',
        '',
        '【確認すること】',
        '  1. GAS の スクリプト プロパティ に ' + PROP_PAT + ' があるか',
        '  2. PAT が期限切れでないか（401 なら期限切れの可能性）',
        '  3. PAT の権限が Actions: Read and write か（403 なら権限不足）',
        '  4. 直らないときは手動実行:',
        '     https://github.com/' + GH_OWNER + '/' + GH_REPO + '/actions',
        '',
        '-- Tribune watchdog (C192)'
      ].join('\n')
    });
    props.setProperty('lastDispatchFail', today);
  }

  // ============================================================================
  // セットアップ / 動作確認
  // ============================================================================

  /**
  * 一度だけ実行する。既存の同名トリガーを消してから毎日 CHECK_HOUR:CHECK_MINUTE
  * に再作成する（重複作成の防止）。
  * ※ プロジェクトのタイムゾーンが Asia/Tokyo であること（下の手順 3 参照）。
  */
  function setupTrigger() {
    var existing = ScriptApp.getProjectTriggers();
    for (var i = 0; i < existing.length; i++) {
      var fn = existing[i].getHandlerFunction();
      if (fn === 'checkTribune' || fn === 'dispatchTribune') {
        ScriptApp.deleteTrigger(existing[i]);
      }
    }
    // C191: CHECK_TIMES の要素数だけトリガーを作る。
    var labels = [];
    for (var t = 0; t < CHECK_TIMES.length; t++) {
      ScriptApp.newTrigger('checkTribune')
        .timeBased()
        .atHour(CHECK_TIMES[t][0])
        .nearMinute(CHECK_TIMES[t][1])
        .everyDays(1)
        .create();
      labels.push(CHECK_TIMES[t][0] + ':' +
                  (CHECK_TIMES[t][1] < 10 ? '0' : '') + CHECK_TIMES[t][1]);
    }
    // C192: 起動トリガー。PAT が未設定なら作らない（検知だけで運用できる）。
    var hasPat = !!PropertiesService.getScriptProperties().getProperty(PROP_PAT);
    if (hasPat) {
      ScriptApp.newTrigger('dispatchTribune')
        .timeBased()
        .atHour(DISPATCH_TIME[0])
        .nearMinute(DISPATCH_TIME[1])
        .everyDays(1)
        .create();
    }
    Logger.log('check trigger: daily around ' + labels.join(' / ') +
              ' / dispatch trigger: ' +
              (hasPat ? DISPATCH_TIME[0] + ':' + DISPATCH_TIME[1]
                      : '未作成（' + PROP_PAT + ' が未設定）') +
              ' (' + Session.getScriptTimeZone() + ')');
  }

  /**
  * 動作確認 1：**必ず存在しない日付**で検査し、メール本文を Log に出す。
  * メールは送らないので安全に何度でも試せる。
  */
  function dryRunMissing() {
    var fake = '2099-01-01';
    var result = inspect_(fake);
    Logger.log('result: ' + JSON.stringify(result));
    Logger.log('--- subject ---\n' + buildSubject_(fake, result));
    Logger.log('--- body ---\n' + buildBody_(fake, result));
  }

  /**
  * 動作確認 2：実際にメールを 1 通送る（宛先の疎通確認）。
  * lastNotified を汚さないよう notifyOnce_ を経由しない。
  */
  function sendTestMail() {
    var fake = '2099-01-01';
    var result = inspect_(fake);
    MailApp.sendEmail({
      to: resolveRecipient_(),
      subject: '[TEST] ' + buildSubject_(fake, result),
      body: '※これはテスト送信です。実際の障害ではありません。\n\n' +
            buildBody_(fake, result)
    });
    Logger.log('test mail sent to ' + resolveRecipient_());
  }

  /** 動作確認 3：今日の実際の状態を Log に出す（メールは送らない）。 */
  function dryRunToday() {
    var today = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd');
    Logger.log(today + ' → ' + JSON.stringify(inspect_(today)));
  }

  /**
  * 動作確認 4（C192）：実際に workflow_dispatch を 1 回投げる。
  * **本当にランが走る**ので、当日分が既にある状態で試すこと
  * （C185 のガードで skip されるため紙面は変わらない）。
  */
  function testDispatch() {
    var r = triggerWorkflow_();
    Logger.log(JSON.stringify(r));
    if (r.ok) {
      Logger.log('OK: 204 が返りました。Actions に新しい run が現れます。');
    } else {
      Logger.log('NG: ' + r.error);
    }
  }

  /** 動作確認 5（C192）：PAT と期限の設定状況を確認する（値は表示しない）。 */
  function checkPatSetup() {
    var props = PropertiesService.getScriptProperties();
    var pat = props.getProperty(PROP_PAT);
    var expiry = props.getProperty(PROP_PAT_EXPIRY);
    Logger.log(PROP_PAT + ': ' + (pat ? '設定あり（長さ ' + pat.length + '）' : '未設定'));
    Logger.log(PROP_PAT_EXPIRY + ': ' + (expiry || '未設定'));
    if (expiry) {
      var days = Math.floor(
        (new Date(expiry + 'T00:00:00+09:00').getTime() - new Date().getTime())
        / 86400000);
      Logger.log('残り ' + days + ' 日（' + PAT_EXPIRY_WARN_DAYS + ' 日前から警告）');
    }
  }
