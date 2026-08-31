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
  var CHECK_HOUR = 5;
  var CHECK_MINUTE = 30;

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
    if (!result.generated) return '[Tribune] ' + today + ' の朝刊が未生成です';
    return '[Tribune] ' + today + ' の朝刊が未反映です（生成は済）';
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
      L.push('【原因の見当】');
      L.push('  GitHub Actions の schedule が発火しなかった、または大幅に遅延している');
      L.push('  可能性があります（2026-08 は +107 分の遅延や +8 時間の遅延が発生）。');
      L.push('');
      L.push('【対処】手動で実行してください');
      L.push('  1. https://github.com/' + GH_OWNER + '/' + GH_REPO + '/actions');
      L.push('  2. 左メニューの「Daily Tribune Generation」を選ぶ');
      L.push('  3. 右上の「Run workflow」→ Branch: ' + GH_BRANCH + ' → Run workflow');
      L.push('     ※ 既に当日分が出ている場合は二重実行ガード（C185）が働いて');
      L.push('       skip されます。意図的に作り直すときだけ force を true に。');
      L.push('  4. 完走まで約 30 分です。');
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
      if (existing[i].getHandlerFunction() === 'checkTribune') {
        ScriptApp.deleteTrigger(existing[i]);
      }
    }
    ScriptApp.newTrigger('checkTribune')
      .timeBased()
      .atHour(CHECK_HOUR)
      .nearMinute(CHECK_MINUTE)
      .everyDays(1)
      .create();
    Logger.log('trigger set: daily around ' + CHECK_HOUR + ':' + CHECK_MINUTE +
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
