/**
 * おみくじアプリ設定
 *
 * ここだけ編集すれば、プリンターの接続先とおみくじの中身を変更できます。
 * ホスト名・バックエンドは画面右上の設定パネル（隠しボタン）からも変更でき、
 * その場合は localStorage の値がこのファイルより優先されます。
 */
window.OMIKUJI_CONFIG = {
  /**
   * 印刷方式
   *   'mock'    … 印刷せず画面にプレビューを出すだけ（プリンター無しで動作確認できる）
   *   'sdk'     … Epson ePOS SDK for JavaScript 経由（LAN接続。epos-2.js が必要）
   *   'xml'     … ePOS-Print XML を直接POST（LAN接続。SDKを置かずに使える代替手段）
   *   'windows' … Windowsのプリンタードライバー経由（USB接続。IPアドレスの設定が要らない）
   */
  backend: 'mock',

  printer: {
    // プリンターのIPアドレス（本体の設定シートを印刷すると確認できます）
    host: '192.168.0.100',

    // --- backend: 'sdk' 用 ---
    sdkPort: 8008,      // ePOS-Device Service の平文ポート
    sdkSslPort: 8043,   // SSL時のポート
    useSsl: false,
    deviceId: 'local_printer',

    // --- backend: 'xml' 用 ---
    xmlPort: 80,
    xmlPath: '/cgi-bin/epos/service.cgi',

    timeout: 60000
  },

  paper: {
    // TM-m30（80mm紙）の印字可能幅は 576ドット。
    // 58mm紙にする場合は 420 に変更してください。必ず8の倍数にすること。
    widthDots: 576
  },

  print: {
    halftone: 'dither',   // 'dither' | 'threshold' | 'error_diffusion'（sdk時のみ有効）
    brightness: 1.0,      // 0.1〜10.0（sdk時のみ有効）
    threshold: 128,       // xml/mock時のディザ閾値
    invertBits: false,    // 白黒が反転して印刷される場合に true にする
    feedUnitsAfter: 60,   // 印字後の紙送り量（ドット）。カット位置の調整用
    cut: true,

    // backend: 'windows' 用。ミリで指定する。
    // paperWidthMm … 印字幅。80mm紙 = 576ドット ÷ 203dpi = 72mm。58mm紙なら 52 前後。
    // paperSizeMm  … ロール紙そのものの幅。80mm紙なら 80、58mm紙なら 58。
    paperWidthMm: 72,
    paperSizeMm: 80,

    // 画像の下に共通のフッターを刷る場合はここを有効にする
    footer: {
      enabled: false,
      text: 'Ceria fi Ixtigna\nhttps://cir.booth.pm/',
      qr: {
        enabled: false,
        data: 'https://cir.booth.pm/',
        size: 4          // 1〜16
      }
    }
  },

  ui: {
    animationMs: 3200,    // ボタンを押してから印刷が始まるまでの演出時間
    resultMs: 6000,       // 結果表示を出しておく時間
    cooldownMs: 1200      // 連打防止（結果表示後、次に押せるまで）
  },

  draw: {
    /**
     * 'bag'      … 12種を1周するまで同じものが出ない（イベント向け・偏りが出にくい）
     * 'weighted' … 毎回独立抽選。items[].weight で出現率を調整
     */
    mode: 'bag'
  },

  /**
   * おみくじ12種。
   * image に用意した画像のパスを入れてください（omikuji/images/ 配下）。
   * label は画面表示とログにしか使わないので、自由に書き換えて構いません。
   */
  items: [
    { id: '01', label: 'おみくじ Ⅰ', image: 'images/01.png', weight: 1 },
    { id: '02', label: 'おみくじ Ⅱ', image: 'images/02.png', weight: 1 },
    { id: '03', label: 'おみくじ Ⅲ', image: 'images/03.png', weight: 1 },
    { id: '04', label: 'おみくじ Ⅳ', image: 'images/04.png', weight: 1 },
    { id: '05', label: 'おみくじ Ⅴ', image: 'images/05.png', weight: 1 },
    { id: '06', label: 'おみくじ Ⅵ', image: 'images/06.png', weight: 1 },
    { id: '07', label: 'おみくじ Ⅶ', image: 'images/07.png', weight: 1 },
    { id: '08', label: 'おみくじ Ⅷ', image: 'images/08.png', weight: 1 },
    { id: '09', label: 'おみくじ Ⅸ', image: 'images/09.png', weight: 1 },
    { id: '10', label: 'おみくじ Ⅹ', image: 'images/10.png', weight: 1 },
    { id: '11', label: 'おみくじ Ⅺ', image: 'images/11.png', weight: 1 },
    { id: '12', label: 'おみくじ Ⅻ', image: 'images/12.png', weight: 1 }
  ]
};
