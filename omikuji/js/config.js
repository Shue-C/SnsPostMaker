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
   *   'local'   … 配信スクリプト（serve.ps1）経由でESC/POSを送る。
   *               USB/Bluetooth/LAN のどれでも使え、IPアドレスの設定も要らない。
   *               ブラウザの印刷機能を使わないので、余白・ヘッダー・ダイアログが出ない。
   *   'sdk'     … Epson ePOS SDK for JavaScript 経由（LAN接続。epos-2.js が必要）
   *   'xml'     … ePOS-Print XML を直接POST（LAN接続。SDKを置かずに使える代替手段）
   *   'windows' … Windowsのプリンタードライバー経由（window.print）。localが使えないときの代替
   */
  backend: 'local',

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

    // --- backend: 'local' 用 ---
    // Windowsのプリンター名。空欄なら既定のプリンターへ刷る。
    // 設定パネルの一覧から選べるので、普段はここを触る必要はない。
    windowsPrinter: '',
    localPrintPath: '/print',
    localListPath: '/printers',

    timeout: 60000
  },

  paper: {
    // 印字可能幅（ドット）。必ず8の倍数にすること。
    //   58mm紙 … 416（TM-m30の印字可能幅420ドットを8の倍数に切り下げた値）
    //   80mm紙 … 576
    widthDots: 416
  },

  print: {
    halftone: 'dither',   // 'dither' | 'threshold' | 'error_diffusion'（sdk時のみ有効）
    brightness: 1.0,      // 0.1〜10.0（sdk時のみ有効）
    threshold: 128,       // xml/mock時のディザ閾値
    invertBits: false,    // 白黒が反転して印刷される場合に true にする
    // 印字後の紙送り量（ドット）。203ドット = 25.4mm。
    // カットは「カット位置まで送ってから」実行されるので、
    // 下余白を足したいときだけ増やす。0 でちょうど良いことが多い。
    feedUnitsAfter: 0,
    cut: true,

    // backend: 'windows' 用。ミリで指定する。
    // paperWidthMm … 印字幅。58mm紙 = 416ドット ÷ 203dpi = 52mm。80mm紙なら 72。
    // paperSizeMm  … ロール紙そのものの幅。58mm紙なら 58、80mm紙なら 80。
    paperWidthMm: 52,
    paperSizeMm: 58,

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
     * 'bag'      … 5種を1周するまで同じものが出ない（同じものが連続しない）
     * 'weighted' … 毎回独立抽選。items[].weight で出現率を調整
     */
    mode: 'bag'
  },

  /**
   * おみくじ5種。design/o_NN.png（原画）から
   * tools/make_print_images.py で images/NN.png（印刷用）を作っています。
   * 原画を描き直したら、そのスクリプトを実行し直してください。
   *
   * weight は出現の重み。draw.mode が 'bag' なら袋に入れる枚数、
   * 'weighted' なら確率の比になります。今は全部同じ（等確率）です。
   */
  items: [
    { id: '01', label: '大吉', image: 'images/01.png', weight: 1 },
    { id: '02', label: '中吉', image: 'images/02.png', weight: 1 },
    { id: '03', label: '小吉', image: 'images/03.png', weight: 1 },
    { id: '04', label: '吉',   image: 'images/04.png', weight: 1 },
    { id: '05', label: '末吉', image: 'images/05.png', weight: 1 }
  ]
};
