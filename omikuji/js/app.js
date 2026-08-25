/**
 * 画面制御とフロー全体。
 *
 *   待機 →（クリスタルをタップ）→ 演出（約3秒）→ 印刷 → 結果 → 待機
 *
 * 画面は原画と同じ 1024px 幅の座標系で組んであり、ここで画面サイズに
 * 合わせた倍率（--s）を計算する。演出中の裏で「抽選」「画像のラスター化」
 * 「プリンター接続」を並行して進めるので、演出が終わった瞬間に印刷が始まる。
 */
(function (global) {
  'use strict';

  var SETTINGS_KEY = 'omikuji.settings.v1';
  var HISTORY_KEY = 'omikuji.history.v1';
  var HISTORY_MAX = 500;

  var TEXT = {
    idle: {
      title: '魔法のおみくじを引いてみましょう',
      sub: 'あなたの運命を導く、魔法の言葉。<br>心を静めて、下のクリスタルをタップしてください。'
    },
    drawing: {
      title: '精霊に伺いを立てています',
      sub: 'クリスタルが今日のことばを選んでいます。'
    },
    result: {
      sub: '転写機から出てくる<br>おみくじをお受け取りください。'
    },
    error: {
      title: 'おみくじを刷れませんでした'
    }
  };

  var DRAWING_TITLES = [
    '精霊に伺いを立てています',
    '刻印盤が回っています',
    '今日のことばを選んでいます'
  ];

  var el = {};
  var cfg, drawer, backend;
  var canvasCache = {};
  var missingImages = [];
  var busy = false;
  var errorAt = 0;
  // localStorage が使えない環境（file:// で開いた場合など）でも設定を変えられるよう、
  // 保存できなかった内容はこの変数に持っておく。
  var sessionOverrides = null;
  var backendHooks = null;
  var timers = [];

  // ------------------------------------------------------------ 画面サイズ

  /**
   * 実際に見えている領域の大きさ。
   * ファイルアプリのプレビューなど viewport 指定が無視される環境では
   * innerWidth が実寸と食い違うので、visualViewport を優先して使う。
   */
  function viewportSize() {
    var vv = global.visualViewport;
    if (vv && vv.width && vv.height) return { w: vv.width, h: vv.height };
    var de = document.documentElement;
    return {
      w: global.innerWidth || de.clientWidth,
      h: global.innerHeight || de.clientHeight
    };
  }

  function fitCanvas() {
    var view = viewportSize();
    var root = document.documentElement.style;
    root.setProperty('--vw', view.w + 'px');
    root.setProperty('--vh', view.h + 'px');
    // キャンバスの実寸（CSS側の width/height）から倍率を出すので、
    // レイアウトを詰めてもここを直す必要はない。
    var w = el.canvas.offsetWidth;
    var h = el.canvas.offsetHeight;
    if (!w || !h) return;
    el.canvas.style.setProperty('--s', Math.min(view.w / w, view.h / h));
  }

  // ------------------------------------------------------------ 設定

  function loadJson(key, fallback) {
    try {
      var v = JSON.parse(global.localStorage.getItem(key));
      return v === null || v === undefined ? fallback : v;
    } catch (e) {
      return fallback;
    }
  }

  function saveJson(key, value) {
    try {
      global.localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch (e) {
      return false;
    }
  }

  function overrides() {
    return sessionOverrides || loadJson(SETTINGS_KEY, {});
  }

  function buildConfig() {
    var base = JSON.parse(JSON.stringify(global.OMIKUJI_CONFIG));
    var ov = overrides();
    if (ov.backend) base.backend = ov.backend;
    if (ov.host) base.printer.host = ov.host;
    if (ov.sdkPort) base.printer.sdkPort = Number(ov.sdkPort);
    if (ov.xmlPort) base.printer.xmlPort = Number(ov.xmlPort);
    if (typeof ov.invertBits === 'boolean') base.print.invertBits = ov.invertBits;
    return base;
  }

  // ------------------------------------------------------------ 状態

  function setState(name, title, sub) {
    document.body.className = 'state-' + name;
    if (title !== undefined) el.leadTitle.textContent = title;
    if (sub !== undefined) el.leadSub.innerHTML = sub;
  }

  function clearTimers() {
    timers.forEach(clearTimeout);
    timers = [];
  }

  function later(fn, ms) {
    var t = setTimeout(fn, ms);
    timers.push(t);
    return t;
  }

  function goIdle() {
    clearTimers();
    busy = false;
    el.drawBtn.disabled = false;
    setState('idle', TEXT.idle.title, TEXT.idle.sub);
  }

  // ------------------------------------------------------------ 印刷素材

  function getCanvas(item) {
    if (canvasCache[item.id]) return Promise.resolve(canvasCache[item.id]);
    return global.Raster.renderItem(item, cfg.paper.widthDots).then(function (r) {
      canvasCache[item.id] = r.canvas;
      if (r.placeholder && missingImages.indexOf(item.id) === -1) {
        missingImages.push(item.id);
      }
      return r.canvas;
    });
  }

  /**
   * 起動時に全画像を読み込んでおき、初回の待ち時間をなくす。
   * プレースホルダーは canvas に文字を描くので、同梱フォントの
   * 読み込みが済むのを待ってから作る（別の書体で焼き付くのを防ぐ）。
   */
  function preloadAll() {
    var chain = document.fonts && document.fonts.ready
      ? document.fonts.ready.catch(function () {})
      : Promise.resolve();
    cfg.items.forEach(function (item) {
      chain = chain.then(function () {
        return getCanvas(item).catch(function () { /* 個別失敗は無視 */ });
      });
    });
    return chain;
  }

  // ------------------------------------------------------------ 履歴

  function recordHistory(item) {
    var list = loadJson(HISTORY_KEY, []);
    list.unshift({ t: Date.now(), id: item.id, label: item.label });
    if (list.length > HISTORY_MAX) list.length = HISTORY_MAX;
    saveJson(HISTORY_KEY, list);
  }

  function renderHistory() {
    var list = loadJson(HISTORY_KEY, []);
    var today = new Date().toDateString();
    var todayCount = 0;
    var byId = {};
    list.forEach(function (r) {
      if (new Date(r.t).toDateString() === today) todayCount++;
      byId[r.label] = (byId[r.label] || 0) + 1;
    });
    var breakdown = Object.keys(byId).sort().map(function (k) {
      return k + ' ' + byId[k];
    }).join(' / ');
    el.historySummary.textContent = list.length
      ? '本日 ' + todayCount + ' 枚 ／ 累計 ' + list.length + ' 枚\n' + breakdown
      : 'まだ記録がありません。';

    el.historyList.innerHTML = '';
    list.slice(0, 60).forEach(function (r) {
      var li = document.createElement('li');
      var d = new Date(r.t);
      var hh = ('0' + d.getHours()).slice(-2);
      var mm = ('0' + d.getMinutes()).slice(-2);
      li.textContent = (d.getMonth() + 1) + '/' + d.getDate() + ' ' + hh + ':' + mm +
                       '　' + r.label;
      el.historyList.appendChild(li);
    });
  }

  // ------------------------------------------------------------ フロー

  function sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  function cycleTitles() {
    var i = 0;
    el.leadTitle.textContent = DRAWING_TITLES[0];
    var step = Math.max(900, Math.floor(cfg.ui.animationMs / DRAWING_TITLES.length));
    var id = setInterval(function () {
      i = (i + 1) % DRAWING_TITLES.length;
      el.leadTitle.textContent = DRAWING_TITLES[i];
    }, step);
    return function stop() { clearInterval(id); };
  }

  function onDraw() {
    if (busy) return;
    busy = true;
    clearTimers();
    el.drawBtn.disabled = true;
    el.preview.hidden = true;
    el.preview.innerHTML = '';

    var item = drawer.draw();
    setState('drawing', TEXT.drawing.title, TEXT.drawing.sub);
    var stopTitles = cycleTitles();

    // 演出を流している裏で素材の準備と接続を済ませる
    var ready = Promise.all([getCanvas(item), backend.ensureReady()]);

    Promise.all([ready, sleep(cfg.ui.animationMs)])
      .then(function (results) {
        return backend.printCanvas(results[0][0], cfg.print);
      })
      .then(function () {
        stopTitles();
        recordHistory(item);
        setState('result', item.label, TEXT.result.sub);
        later(function () {
          goIdle();
          busy = true;                       // 連打防止のクールダウン
          el.drawBtn.disabled = true;
          later(function () {
            busy = false;
            el.drawBtn.disabled = false;
          }, cfg.ui.cooldownMs);
        }, cfg.ui.resultMs);
      })
      .catch(function (err) {
        stopTitles();
        console.error(err);
        var msg = (err && err.message) ? err.message : String(err);
        setState('error', TEXT.error.title,
                 escapeHtml(msg) + '<br>画面のどこかに触れると最初に戻ります。');
        errorAt = Date.now();
        busy = false;
        el.drawBtn.disabled = false;
        later(goIdle, 20000);
      });
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ------------------------------------------------------------ 設定UI

  function openSettings() {
    var ov = overrides();
    el.setBackend.value = cfg.backend;
    el.setHost.value = cfg.printer.host;
    el.setSdkPort.value = cfg.printer.sdkPort;
    el.setXmlPort.value = cfg.printer.xmlPort;
    el.setInvert.checked = !!cfg.print.invertBits;

    var info = ['接続: ' + backend.describe()];
    var rest = drawer.remaining();
    if (rest !== null) info.push('袋の残り: ' + rest + ' 枚');
    info.push('用紙幅: ' + cfg.paper.widthDots + 'ドット');
    if (missingImages.length) {
      info.push('画像が見つからない項目: ' + missingImages.join(', ') +
                '（プレースホルダーを印刷します）');
    } else {
      info.push('おみくじ画像: 全' + cfg.items.length + '種を読み込み済み');
    }
    if (Object.keys(ov).length) {
      info.push('※この端末の保存設定が config.js より優先されています');
    }
    el.settingsInfo.textContent = info.join('\n');

    renderHistory();
    el.settings.hidden = false;
  }

  /**
   * 設定を反映する。保存できた場合もできなかった場合も、その場で
   * 接続先を作り直して効かせる（再読み込みしないので file:// でも使える）。
   */
  function saveSettings() {
    sessionOverrides = {
      backend: el.setBackend.value,
      host: el.setHost.value.trim(),
      sdkPort: Number(el.setSdkPort.value) || undefined,
      xmlPort: Number(el.setXmlPort.value) || undefined,
      invertBits: el.setInvert.checked
    };
    var stored = saveJson(SETTINGS_KEY, sessionOverrides);
    cfg = buildConfig();
    backend = global.PrinterBackend.create(cfg, backendHooks);
    el.settingsInfo.textContent = stored
      ? '設定を反映しました。'
      : '設定を反映しました（この端末には保存できないため、次回起動時は既定値に戻ります）。';
  }

  function testPrint() {
    var canvas = global.Raster.makePlaceholder(
      { id: 'TEST', label: 'テスト印刷' }, cfg.paper.widthDots);
    el.settingsInfo.textContent = '印刷中…';
    backend.ensureReady()
      .then(function () { return backend.printCanvas(canvas, cfg.print); })
      .then(function () { el.settingsInfo.textContent = '印刷しました。'; })
      .catch(function (err) { el.settingsInfo.textContent = '失敗: ' + err.message; });
  }

  function bindLongPress(node, ms, handler) {
    var timer = null;
    var start = function () { clearTimeout(timer); timer = setTimeout(handler, ms); };
    var cancel = function () { clearTimeout(timer); };
    node.addEventListener('touchstart', start, { passive: true });
    node.addEventListener('touchend', cancel);
    node.addEventListener('touchcancel', cancel);
    node.addEventListener('mousedown', start);
    node.addEventListener('mouseup', cancel);
    node.addEventListener('mouseleave', cancel);
  }

  /** iPadの自動スリープを抑止（iOS 16.4以降のSafariのみ有効）。 */
  function keepAwake() {
    if (!global.navigator.wakeLock) return;
    var lock = null;
    var request = function () {
      global.navigator.wakeLock.request('screen').then(function (l) {
        lock = l;
        l.addEventListener('release', function () { lock = null; });
      }).catch(function () { /* 非対応・拒否時は何もしない */ });
    };
    request();
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible' && !lock) request();
    });
  }

  // ------------------------------------------------------------ 起動

  function init() {
    var ids = {
      canvas: 'canvas', drawBtn: 'draw-btn', ribbon: 'ribbon',
      leadTitle: 'lead-title', leadSub: 'lead-sub',
      preview: 'preview', settings: 'settings', settingsToggle: 'settings-toggle',
      settingsInfo: 'settings-info', historySummary: 'history-summary',
      historyList: 'history-list', setClearHistory: 'set-clear-history',
      setBackend: 'set-backend', setHost: 'set-host', setSdkPort: 'set-sdk-port',
      setXmlPort: 'set-xml-port', setInvert: 'set-invert', setTest: 'set-test',
      setResetBag: 'set-reset-bag', setSave: 'set-save', setClose: 'set-close'
    };
    Object.keys(ids).forEach(function (k) { el[k] = document.getElementById(ids[k]); });

    cfg = buildConfig();
    drawer = new global.Drawer(cfg.items, cfg.draw.mode);
    backendHooks = {
      onPreview: function (canvas) {
        var copy = document.createElement('canvas');
        copy.width = canvas.width;
        copy.height = canvas.height;
        copy.getContext('2d').drawImage(canvas, 0, 0);
        el.preview.innerHTML = '';
        el.preview.appendChild(copy);
        el.preview.hidden = false;
      }
    };
    backend = global.PrinterBackend.create(cfg, backendHooks);

    fitCanvas();
    global.addEventListener('resize', fitCanvas);
    global.addEventListener('orientationchange', fitCanvas);
    if (global.visualViewport) {
      global.visualViewport.addEventListener('resize', fitCanvas);
      global.visualViewport.addEventListener('scroll', fitCanvas);
    }
    // 表示直後は実寸が確定していないことがあるので、少し置いてもう一度測る
    // （抽選時に clearTimers されないよう later() は使わない）
    setTimeout(fitCanvas, 300);
    setTimeout(fitCanvas, 1200);

    el.drawBtn.addEventListener('click', onDraw);
    el.drawBtn.addEventListener('touchstart', function () {
      el.ribbon.style.opacity = '.8';
    }, { passive: true });
    ['touchend', 'touchcancel', 'mouseup'].forEach(function (ev) {
      el.drawBtn.addEventListener(ev, function () { el.ribbon.style.opacity = ''; });
    });

    // エラー表示中はどこを触っても最初に戻れるようにする。
    // ただしエラーの原因になったタップ自身を拾わないよう、少し待ってから有効にする。
    document.addEventListener('click', function (e) {
      if (document.body.classList.contains('state-error') &&
          Date.now() - errorAt > 600 &&
          !el.settings.contains(e.target) && e.target !== el.settingsToggle) {
        goIdle();
      }
    });

    bindLongPress(el.settingsToggle, 1500, openSettings);
    el.setClose.addEventListener('click', function () { el.settings.hidden = true; });
    el.setSave.addEventListener('click', saveSettings);
    el.setTest.addEventListener('click', testPrint);
    el.setResetBag.addEventListener('click', function () {
      drawer.reset();
      el.settingsInfo.textContent = '抽選をリセットしました。';
    });
    el.setClearHistory.addEventListener('click', function () {
      saveJson(HISTORY_KEY, []);
      renderHistory();
    });

    // JavaScript が動いている証拠。動かない環境では出たままになる。
    var nojs = document.getElementById('nojs');
    if (nojs && nojs.parentNode) nojs.parentNode.removeChild(nojs);

    goIdle();
    preloadAll();
    keepAwake();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(window);
