/**
 * 印刷バックエンド。
 *
 *   sdk     … Epson ePOS SDK for JavaScript（epos-2.js）経由。ネットワーク接続時の推奨経路。
 *   xml     … ePOS-Print XML を直接HTTP POSTする。SDKを配置せずに動かしたいとき用。
 *   local   … 配信スクリプト（serve.ps1）にESC/POSを渡してもらう。USB/Bluetooth接続用。
 *             ブラウザの印刷機能を使わないので、余白もヘッダーもダイアログも出ない。
 *   windows … Windowsのプリンタードライバー経由（window.print）。localが使えないときの代替。
 *   mock    … 印刷せず画面にプレビューするだけ。プリンター無しでの動作確認用。
 *
 * どのバックエンドも共通で以下を持つ:
 *   ensureReady() -> Promise<void>
 *   printCanvas(canvas, printCfg) -> Promise<void>
 *   describe() -> string
 */
(function (global) {
  'use strict';

  function withTimeout(promise, ms, message) {
    return new Promise(function (resolve, reject) {
      var done = false;
      var timer = setTimeout(function () {
        if (!done) { done = true; reject(new Error(message)); }
      }, ms);
      promise.then(function (v) {
        if (!done) { done = true; clearTimeout(timer); resolve(v); }
      }, function (e) {
        if (!done) { done = true; clearTimeout(timer); reject(e); }
      });
    });
  }

  // ---------------------------------------------------------------- mock

  function MockBackend(cfg, hooks) {
    this.cfg = cfg;
    this.hooks = hooks || {};
  }
  MockBackend.prototype.describe = function () {
    return 'モック（印刷しません）';
  };
  MockBackend.prototype.ensureReady = function () {
    return Promise.resolve();
  };
  MockBackend.prototype.printCanvas = function (canvas, printCfg) {
    if (this.hooks.onPreview) this.hooks.onPreview(canvas);
    console.log('[mock] 印刷:', canvas.width + 'x' + canvas.height, printCfg);
    return new Promise(function (resolve) { setTimeout(resolve, 900); });
  };

  // ----------------------------------------------------------------- sdk

  function SdkBackend(cfg, hooks) {
    this.cfg = cfg;
    this.hooks = hooks || {};
    this.device = null;
    this.printer = null;
  }

  SdkBackend.prototype.describe = function () {
    var p = this.cfg.printer;
    return 'ePOS SDK ' + p.host + ':' + (p.useSsl ? p.sdkSslPort : p.sdkPort);
  };

  SdkBackend.prototype.ensureReady = function () {
    var self = this;
    if (self.printer) return Promise.resolve();

    if (!global.epson || !global.epson.ePOSDevice) {
      return Promise.reject(new Error(
        'epos-2.js が読み込まれていません。' +
        'README の手順で js/epos-2.js を配置してください。'
      ));
    }

    var p = self.cfg.printer;
    var port = p.useSsl ? p.sdkSslPort : p.sdkPort;

    return withTimeout(new Promise(function (resolve, reject) {
      var dev = new global.epson.ePOSDevice();
      dev.ondisconnect = function () {
        self.device = null;
        self.printer = null;
      };
      dev.connect(p.host, port, function (result) {
        if (result !== 'OK' && result !== 'SSL_CONNECT_OK') {
          reject(new Error('プリンターに接続できません (' + result + ')'));
          return;
        }
        dev.createDevice(
          p.deviceId,
          dev.DEVICE_TYPE_PRINTER,
          { crypto: !!p.useSsl, buffer: false },
          function (devobj, code) {
            if (code !== 'OK' || !devobj) {
              reject(new Error('プリンターデバイスを開けません (' + code + ')'));
              return;
            }
            self.device = dev;
            self.printer = devobj;
            resolve();
          }
        );
      }, { eposdevice_version: '2.0.0' });
    }), self.cfg.printer.timeout, 'プリンターへの接続がタイムアウトしました');
  };

  SdkBackend.prototype.printCanvas = function (canvas, printCfg) {
    var self = this;
    return self.ensureReady().then(function () {
      var printer = self.printer;

      var halftones = {
        dither: printer.HALFTONE_DITHER,
        threshold: printer.HALFTONE_THRESHOLD,
        error_diffusion: printer.HALFTONE_ERROR_DIFFUSION
      };
      printer.halftone = halftones[printCfg.halftone] || printer.HALFTONE_DITHER;
      printer.brightness = printCfg.brightness || 1.0;

      return withTimeout(new Promise(function (resolve, reject) {
        printer.onreceive = function (res) {
          printer.onreceive = null;
          printer.onerror = null;
          if (res.success) resolve();
          else reject(new Error(describeCode(res.code) + ' (status=' + res.status + ')'));
        };
        printer.onerror = function (err) {
          printer.onreceive = null;
          printer.onerror = null;
          reject(new Error('印刷エラー: ' + (err && err.status ? err.status : err)));
        };

        printer.addTextAlign(printer.ALIGN_CENTER);
        printer.addImage(
          canvas.getContext('2d'), 0, 0, canvas.width, canvas.height,
          printer.COLOR_1, printer.MODE_MONO
        );

        var footer = printCfg.footer || {};
        if (footer.enabled) {
          if (footer.text) {
            printer.addFeedUnit(20);
            printer.addTextLang('ja');
            printer.addText(footer.text.replace(/\n?$/, '\n'));
          }
          if (footer.qr && footer.qr.enabled && footer.qr.data) {
            printer.addFeedUnit(16);
            printer.addSymbol(
              footer.qr.data,
              printer.SYMBOL_QRCODE_MODEL_2,
              printer.LEVEL_M,
              footer.qr.size || 4, 0, 0
            );
          }
        }

        if (printCfg.feedUnitsAfter) printer.addFeedUnit(printCfg.feedUnitsAfter);
        if (printCfg.cut) printer.addCut(printer.CUT_FEED);
        printer.send();
      }), self.cfg.printer.timeout, '印刷応答がタイムアウトしました');
    });
  };

  /** ePOS の代表的なエラーコードを日本語にする。 */
  function describeCode(code) {
    var map = {
      EPTR_COVER_OPEN: 'カバーが開いています',
      EPTR_REC_EMPTY: '用紙がありません',
      EPTR_AUTOMATICAL: 'プリンターが自動復帰待ちです',
      EPTR_UNRECOVERABLE: 'プリンターに復帰不能なエラーが発生しました',
      EPTR_CUTTER: 'カッターエラーです（紙詰まりを確認してください）',
      EPTR_MECHANICAL: 'メカニカルエラーです',
      SchemaError: '送信データが不正です',
      DeviceNotFound: '指定したデバイスIDが見つかりません',
      PrintSystemError: 'プリンターシステムエラーです',
      EX_BADPORT: '通信ポートに接続できません',
      EX_TIMEOUT: '通信がタイムアウトしました'
    };
    return map[code] || ('印刷に失敗しました (' + code + ')');
  }

  // ----------------------------------------------------------------- xml

  function XmlBackend(cfg, hooks) {
    this.cfg = cfg;
    this.hooks = hooks || {};
  }

  XmlBackend.prototype.describe = function () {
    var p = this.cfg.printer;
    return 'ePOS-Print XML ' + p.host + ':' + p.xmlPort;
  };

  XmlBackend.prototype.ensureReady = function () {
    return Promise.resolve();
  };

  XmlBackend.prototype.printCanvas = function (canvas, printCfg) {
    var p = this.cfg.printer;
    var raster = global.Raster.toRasterBase64(canvas, {
      threshold: printCfg.threshold,
      invert: printCfg.invertBits
    });

    var body = '';
    body += '<text align="center"/>';
    body += '<image width="' + raster.width + '" height="' + raster.height + '"' +
            ' color="color_1" mode="mono">' + raster.base64 + '</image>';

    var footer = printCfg.footer || {};
    if (footer.enabled) {
      if (footer.text) {
        body += '<feed unit="20"/>';
        body += '<text lang="ja"/>';
        body += '<text>' + escapeXml(footer.text.replace(/\n?$/, '\n')) + '</text>';
      }
      if (footer.qr && footer.qr.enabled && footer.qr.data) {
        body += '<feed unit="16"/>';
        body += '<symbol type="qrcode_model_2" level="level_m" width="' +
                (footer.qr.size || 4) + '">' + escapeXml(footer.qr.data) + '</symbol>';
      }
    }

    if (printCfg.feedUnitsAfter) body += '<feed unit="' + printCfg.feedUnitsAfter + '"/>';
    if (printCfg.cut) body += '<cut type="feed"/>';

    var envelope =
      '<?xml version="1.0" encoding="utf-8"?>' +
      '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>' +
      '<epos-print xmlns="http://www.epson-pos.com/schemas/2011/03/epos-print">' +
      body +
      '</epos-print></s:Body></s:Envelope>';

    var url = (p.useSsl ? 'https://' : 'http://') + p.host + ':' + p.xmlPort +
              p.xmlPath + '?devid=' + encodeURIComponent(p.deviceId) +
              '&timeout=' + p.timeout;

    return withTimeout(
      postXml(url, envelope).then(function (text) {
        var doc = new DOMParser().parseFromString(text, 'text/xml');
        var response = doc.getElementsByTagName('response')[0];
        if (!response) throw new Error('プリンターの応答を解釈できませんでした');
        if (response.getAttribute('success') !== 'true') {
          throw new Error(describeCode(response.getAttribute('code')));
        }
      }),
      this.cfg.printer.timeout,
      '印刷応答がタイムアウトしました'
    );
  };

  /**
   * ePOS-Print XML を送る。fetch が使えない環境（file:// で開いた場合など）が
   * あるので、失敗したら XMLHttpRequest でもう一度試す。
   */
  function postXml(url, body) {
    var headers = { 'Content-Type': 'text/xml; charset=utf-8', 'SOAPAction': '""' };
    var viaXhr = function () {
      return new Promise(function (resolve, reject) {
        var xhr = new XMLHttpRequest();
        xhr.open('POST', url, true);
        Object.keys(headers).forEach(function (k) { xhr.setRequestHeader(k, headers[k]); });
        xhr.onload = function () {
          if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.responseText);
          else reject(new Error('プリンターがHTTP ' + xhr.status + ' を返しました'));
        };
        xhr.onerror = function () {
          reject(new Error('プリンターに送信できませんでした（ブラウザに通信を拒否されました）'));
        };
        xhr.send(body);
      });
    };
    if (typeof fetch !== 'function') return viaXhr();
    return fetch(url, { method: 'POST', headers: headers, body: body })
      .then(function (res) {
        if (!res.ok) throw new Error('プリンターがHTTP ' + res.status + ' を返しました');
        return res.text();
      })
      .catch(function (err) {
        // fetch がブラウザの制限で弾かれた場合に備えてもう一度
        return viaXhr().catch(function () { throw err; });
      });
  }

  function escapeXml(s) {
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&apos;');
  }

  // --------------------------------------------------------------- local

  /**
   * 配信スクリプト（serve.ps1）の /print に ESC/POS を投げる。
   *
   * ブラウザの印刷機能を一切使わないので、
   *   - 印刷ダイアログが一瞬映らない
   *   - ブラウザが勝手に足す日時・タイトル・URLが刷られない
   *   - ページ余白が入らず、画像の実寸ちょうどで刷れる
   * という利点がある。同一オリジンへのPOSTなのでCORSの制約も無い。
   *
   * プリンターとの繋ぎ方（USB / Bluetooth / LAN）は Windows 側の
   * プリンター設定の問題になるので、このバックエンドからは見えない。
   */
  function LocalBackend(cfg, hooks) {
    this.cfg = cfg;
    this.hooks = hooks || {};
  }

  LocalBackend.prototype.describe = function () {
    var name = this.cfg.printer.windowsPrinter;
    return 'ローカル印刷サービス（' + (name ? name : '既定のプリンター') + '）';
  };

  LocalBackend.prototype.ensureReady = function () {
    return Promise.resolve();
  };

  /** 利用できるWindowsプリンターの一覧を取りに行く（設定画面用）。 */
  LocalBackend.prototype.listPrinters = function () {
    return fetch(this.cfg.printer.localListPath || 'printers')
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      });
  };

  LocalBackend.prototype.printCanvas = function (canvas, printCfg) {
    var p = this.cfg.printer;
    var raster = global.Raster.toRasterBytes(canvas, {
      threshold: printCfg.threshold,
      invert: printCfg.invertBits
    });
    var data = buildEscPos(raster, printCfg);

    return withTimeout(
      fetch(p.localPrintPath || 'print', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          printer: p.windowsPrinter || '',
          data: global.Raster.bytesToBase64(data)
        })
      }).then(function (res) {
        return res.json().catch(function () {
          throw new Error('印刷サービスの応答を解釈できませんでした（HTTP ' + res.status + '）');
        });
      }).then(function (json) {
        if (!json || !json.ok) {
          throw new Error((json && json.error) || '印刷に失敗しました');
        }
      }).catch(function (err) {
        if (err instanceof TypeError) {
          throw new Error(
            '印刷サービスに繋がりません。kiosk.bat / serve.bat から起動しているか確認してください。'
          );
        }
        throw err;
      }),
      p.timeout || 60000,
      '印刷応答がタイムアウトしました'
    );
  };

  /**
   * ラスターを ESC/POS のコマンド列に組み立てる。
   *
   *   ESC @         初期化
   *   ESC a 0       左寄せ（ラスターは紙の左端から刷られる）
   *   GS v 0 …      ラスタービットイメージ
   *   ESC J n       n ドット紙送り
   *   GS V 66 0     カット位置まで送ってカット
   *
   * GS v 0 はプリンターの受信バッファを超えると取りこぼすので、
   * 高さ256ドットずつの帯に割って送る（継ぎ目は出ない）。
   */
  function buildEscPos(raster, printCfg) {
    var parts = [];
    var push = function (arr) { parts.push(Uint8Array.from(arr)); };

    push([0x1b, 0x40]);        // ESC @
    push([0x1b, 0x61, 0x00]);  // ESC a 0

    var bpr = raster.bytesPerRow;
    var band = 256;
    for (var y = 0; y < raster.height; y += band) {
      var rows = Math.min(band, raster.height - y);
      push([0x1d, 0x76, 0x30, 0x00,
            bpr & 0xff, (bpr >> 8) & 0xff,
            rows & 0xff, (rows >> 8) & 0xff]);
      parts.push(raster.bytes.subarray(y * bpr, (y + rows) * bpr));
    }

    var feed = printCfg.feedUnitsAfter || 0;
    while (feed > 0) {
      var n = Math.min(255, feed);
      push([0x1b, 0x4a, n]);   // ESC J n
      feed -= n;
    }

    if (printCfg.cut !== false) {
      push([0x1d, 0x56, 0x42, 0x00]);  // GS V 66 0
    }

    var total = 0;
    parts.forEach(function (a) { total += a.length; });
    var out = new Uint8Array(total);
    var at = 0;
    parts.forEach(function (a) { out.set(a, at); at += a.length; });
    return out;
  }

  // ------------------------------------------------------------- windows

  /**
   * Windowsのプリンタードライバー経由で刷る。
   *
   * ネットワークを一切使わないので、USBケーブル1本で完結する。
   * プリンター内蔵のWebサービス（ePOS-Print）はEthernet側にしか出ていないため、
   * USB接続で刷るにはこの経路しかない。
   *
   * 絵はラスター送信と同じ Floyd–Steinberg で2値化してから貼る。
   * ドライバー任せの網点にすると絵柄が潰れるため。
   */
  function WindowsBackend(cfg, hooks) {
    this.cfg = cfg;
    this.hooks = hooks || {};
  }

  WindowsBackend.prototype.describe = function () {
    return 'Windowsのプリンタードライバー（USB接続）';
  };

  WindowsBackend.prototype.ensureReady = function () {
    if (typeof global.print !== 'function') {
      return Promise.reject(new Error('このブラウザでは印刷機能を使えません'));
    }
    return Promise.resolve();
  };

  WindowsBackend.prototype.printCanvas = function (canvas, printCfg) {
    var self = this;
    var sheet = document.getElementById('print-sheet');
    if (!sheet) return Promise.reject(new Error('印刷用の領域が見つかりません（index.html を確認してください）'));

    var mono = global.Raster.toMonoCanvas(canvas, {
      threshold: printCfg.threshold,
      invert: printCfg.invertBits
    });

    // 印字幅は mm で指定する。576ドット ÷ 203dpi = 72mm がTM-m30の80mm紙の印字幅。
    var widthMm = printCfg.paperWidthMm || 72;
    var sheetMm = printCfg.paperSizeMm || 80;   // ロール紙そのものの幅
    // 印字後の紙送り（ドット）を mm に直して下余白にする
    var padMm = (printCfg.feedUnitsAfter || 0) / 203 * 25.4;
    // 用紙の長さは絵の高さから決める。
    // CSS の @page は `size: 80mm auto` のような書き方ができない（無効になる）ので、
    // 毎回ここで実寸を計算して差し込む。
    var pageMm = mono.height * (widthMm / mono.width) + padMm;
    setPageSize(sheetMm, pageMm);

    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () {
        sheet.innerHTML = '';
        sheet.style.paddingBottom = padMm.toFixed(2) + 'mm';
        img.style.width = widthMm + 'mm';
        sheet.appendChild(img);

        var done = false;
        var timer = null;
        var finish = function (err) {
          if (done) return;
          done = true;
          global.removeEventListener('afterprint', onAfter);
          if (timer) clearTimeout(timer);
          sheet.innerHTML = '';
          if (err) reject(err); else resolve();
        };
        var onAfter = function () { setTimeout(function () { finish(null); }, 200); };
        global.addEventListener('afterprint', onAfter);

        try {
          // print() は印刷ジョブを投げ終わってから戻る
          // （ダイアログが出る設定なら、閉じてから戻る）。
          global.print();
        } catch (e) {
          finish(new Error('印刷を開始できませんでした: ' + e.message));
          return;
        }
        // afterprint が飛ばない環境もあるので、戻ってきたら少し待って完了扱いにする
        timer = setTimeout(function () { finish(null); }, 1200);
      };
      img.onerror = function () { reject(new Error('印刷用の画像を作れませんでした')); };
      img.src = mono.toDataURL('image/png');
    });
  };

  /** @page の用紙サイズを実寸で差し込む（レシートは1枚ごとに長さが変わるため）。 */
  function setPageSize(widthMm, heightMm) {
    var id = 'print-page-size';
    var style = document.getElementById(id);
    if (!style) {
      style = document.createElement('style');
      style.id = id;
      document.head.appendChild(style);
    }
    style.textContent = '@page { size: ' + widthMm.toFixed(2) + 'mm ' +
                        heightMm.toFixed(2) + 'mm; margin: 0; }';
  }

  // --------------------------------------------------------------- 生成

  function createBackend(cfg, hooks) {
    switch (cfg.backend) {
      case 'sdk': return new SdkBackend(cfg, hooks);
      case 'xml': return new XmlBackend(cfg, hooks);
      case 'local': return new LocalBackend(cfg, hooks);
      case 'windows': return new WindowsBackend(cfg, hooks);
      case 'mock':
      default: return new MockBackend(cfg, hooks);
    }
  }

  global.PrinterBackend = { create: createBackend };
})(window);
