/**
 * 画面制御とフロー全体。
 *
 *   待機 →（ボタン）→ 演出（約3秒）→ 印刷 → 結果 → 待機
 *
 * 演出を流している裏で「抽選」「画像のラスター化」「プリンター接続」を
 * 並行して進めるので、演出が終わった瞬間に印刷が始まる。
 */
(function (global) {
  'use strict';

  var SETTINGS_KEY = 'omikuji.settings.v1';

  var DRAWING_MESSAGES = [
    '精霊に伺いを立てています',
    '刻印盤が回っています',
    '今日のことばを選んでいます'
  ];

  var el = {};
  var cfg, drawer, backend;
  var canvasCache = {};
  var missingImages = [];
  var busy = false;
  var timers = [];

  // ------------------------------------------------------------ 設定

  function loadOverrides() {
    try {
      return JSON.parse(global.localStorage.getItem(SETTINGS_KEY)) || {};
    } catch (e) {
      return {};
    }
  }

  function buildConfig() {
    var base = JSON.parse(JSON.stringify(global.OMIKUJI_CONFIG));
    var ov = loadOverrides();
    if (ov.backend) base.backend = ov.backend;
    if (ov.host) base.printer.host = ov.host;
    if (ov.sdkPort) base.printer.sdkPort = Number(ov.sdkPort);
    if (ov.xmlPort) base.printer.xmlPort = Number(ov.xmlPort);
    if (typeof ov.invertBits === 'boolean') base.print.invertBits = ov.invertBits;
    return base;
  }

  // ------------------------------------------------------------ 画面

  function setView(name) {
    ['idle', 'drawing', 'result', 'error'].forEach(function (v) {
      el['view_' + v].classList.toggle('is-active', v === name);
    });
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

  function updateStatus() {
    var parts = [backend.describe()];
    var rest = drawer.remaining();
    if (rest !== null) parts.push('袋の残り ' + rest + ' 枚');
    if (missingImages.length) parts.push('画像未設定 ' + missingImages.length + ' 件');
    el.statusLine.textContent = parts.join('　/　');
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

  /** 起動時に全画像を読み込んでおき、初回の待ち時間をなくす。 */
  function preloadAll() {
    var chain = Promise.resolve();
    cfg.items.forEach(function (item) {
      chain = chain.then(function () {
        return getCanvas(item).catch(function () { /* 個別失敗は無視 */ });
      });
    });
    return chain.then(updateStatus);
  }

  // ------------------------------------------------------------ フロー

  function sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  function cycleDrawingText() {
    var i = 0;
    el.drawingText.textContent = DRAWING_MESSAGES[0];
    var step = Math.max(900, Math.floor(cfg.ui.animationMs / DRAWING_MESSAGES.length));
    var id = setInterval(function () {
      i = (i + 1) % DRAWING_MESSAGES.length;
      el.drawingText.textContent = DRAWING_MESSAGES[i];
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
    setView('drawing');
    var stopText = cycleDrawingText();

    // 演出中に素材の準備と接続を済ませる
    var ready = Promise.all([
      getCanvas(item),
      backend.ensureReady().catch(function (e) { return Promise.reject(e); })
    ]);

    Promise.all([ready, sleep(cfg.ui.animationMs)])
      .then(function (results) {
        var canvas = results[0][0];
        return backend.printCanvas(canvas, cfg.print);
      })
      .then(function () {
        stopText();
        el.resultLabel.textContent = item.label;
        setView('result');
        updateStatus();
        later(function () {
          setView('idle');
          later(function () {
            busy = false;
            el.drawBtn.disabled = false;
          }, cfg.ui.cooldownMs);
        }, cfg.ui.resultMs);
      })
      .catch(function (err) {
        stopText();
        console.error(err);
        el.errorDetail.textContent = (err && err.message) ? err.message : String(err);
        setView('error');
        busy = false;
        el.drawBtn.disabled = false;
        later(backToIdle, 20000);
      });
  }

  function backToIdle() {
    clearTimers();
    busy = false;
    el.drawBtn.disabled = false;
    setView('idle');
  }

  // ------------------------------------------------------------ 設定UI

  function openSettings() {
    var ov = loadOverrides();
    el.setBackend.value = cfg.backend;
    el.setHost.value = cfg.printer.host;
    el.setSdkPort.value = cfg.printer.sdkPort;
    el.setXmlPort.value = cfg.printer.xmlPort;
    el.setInvert.checked = !!cfg.print.invertBits;

    var info = [];
    info.push('用紙幅: ' + cfg.paper.widthDots + 'ドット');
    info.push('抽選方式: ' + (cfg.draw.mode === 'bag' ? '袋引き（1周まで重複なし）' : '重み付き抽選'));
    if (missingImages.length) {
      info.push('画像が見つからない項目: ' + missingImages.join(', ') +
                '\n（プレースホルダーを印刷します）');
    } else {
      info.push('画像: 全' + cfg.items.length + '種を読み込み済み');
    }
    if (ov && Object.keys(ov).length) info.push('※この端末の保存設定が config.js より優先されています');
    el.settingsInfo.textContent = info.join('\n');

    el.settings.hidden = false;
  }

  function saveSettings() {
    var ov = {
      backend: el.setBackend.value,
      host: el.setHost.value.trim(),
      sdkPort: Number(el.setSdkPort.value) || undefined,
      xmlPort: Number(el.setXmlPort.value) || undefined,
      invertBits: el.setInvert.checked
    };
    try {
      global.localStorage.setItem(SETTINGS_KEY, JSON.stringify(ov));
    } catch (e) {
      alert('設定を保存できませんでした（プライベートブラウズ中かもしれません）');
      return;
    }
    global.location.reload();
  }

  function testPrint() {
    var canvas = global.Raster.makePlaceholder(
      { id: 'TEST', label: 'テスト印刷' }, cfg.paper.widthDots
    );
    el.settingsInfo.textContent = '印刷中…';
    backend.ensureReady()
      .then(function () { return backend.printCanvas(canvas, cfg.print); })
      .then(function () { el.settingsInfo.textContent = '印刷しました。'; })
      .catch(function (err) { el.settingsInfo.textContent = '失敗: ' + err.message; });
  }

  function bindLongPress(node, ms, handler) {
    var timer = null;
    function start() {
      clearTimeout(timer);
      timer = setTimeout(handler, ms);
    }
    function cancel() { clearTimeout(timer); }
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
      view_idle: 'view-idle', view_drawing: 'view-drawing',
      view_result: 'view-result', view_error: 'view-error',
      drawBtn: 'draw-btn', drawingText: 'drawing-text', resultLabel: 'result-label',
      preview: 'preview', errorDetail: 'error-detail', errorBack: 'error-back',
      statusLine: 'status-line', settings: 'settings', settingsToggle: 'settings-toggle',
      settingsInfo: 'settings-info', setBackend: 'set-backend', setHost: 'set-host',
      setSdkPort: 'set-sdk-port', setXmlPort: 'set-xml-port', setInvert: 'set-invert',
      setTest: 'set-test', setResetBag: 'set-reset-bag', setSave: 'set-save',
      setClose: 'set-close'
    };
    Object.keys(ids).forEach(function (key) {
      el[key] = document.getElementById(ids[key]);
    });

    cfg = buildConfig();
    drawer = new global.Drawer(cfg.items, cfg.draw.mode);
    backend = global.PrinterBackend.create(cfg, {
      onPreview: function (canvas) {
        var copy = document.createElement('canvas');
        copy.width = canvas.width;
        copy.height = canvas.height;
        copy.getContext('2d').drawImage(canvas, 0, 0);
        el.preview.innerHTML = '';
        el.preview.appendChild(copy);
        el.preview.hidden = false;
      }
    });

    el.drawBtn.addEventListener('click', onDraw);
    el.errorBack.addEventListener('click', backToIdle);
    bindLongPress(el.settingsToggle, 1500, openSettings);
    el.setClose.addEventListener('click', function () { el.settings.hidden = true; });
    el.setSave.addEventListener('click', saveSettings);
    el.setTest.addEventListener('click', testPrint);
    el.setResetBag.addEventListener('click', function () {
      drawer.reset();
      updateStatus();
      el.settingsInfo.textContent = '抽選をリセットしました。';
    });

    setView('idle');
    updateStatus();
    preloadAll();
    keepAwake();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(window);
