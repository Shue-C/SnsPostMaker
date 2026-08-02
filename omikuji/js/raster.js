/**
 * 画像の読み込み・レシート幅へのリサイズ・1bitラスター化。
 *
 * サーマルプリンターは白か黒かの2値しか印字できないため、
 * 階調のある画像はディザリング（誤差拡散）で網点に変換してから送る。
 */
(function (global) {
  'use strict';

  /** 画像を読み込む。失敗したら reject。 */
  function loadImage(src) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () { resolve(img); };
      img.onerror = function () { reject(new Error('画像を読み込めませんでした: ' + src)); };
      img.src = src;
    });
  }

  /** 8の倍数に切り下げる（ラスターデータは1行=整数バイトである必要があるため）。 */
  function floorTo8(n) {
    return Math.max(8, Math.floor(n / 8) * 8);
  }

  /**
   * 画像をレシート幅にフィットさせた canvas を返す。
   * 透過部分は白で塗りつぶす（黒く潰れるのを防ぐ）。
   */
  function fitToWidth(img, widthDots) {
    var w = floorTo8(widthDots);
    var h = Math.max(1, Math.round(img.height * (w / img.width)));
    var canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    var ctx = canvas.getContext('2d');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, w, h);
    ctx.drawImage(img, 0, 0, w, h);
    return canvas;
  }

  /**
   * 画像がまだ用意されていないときの代替。
   * ID とラベルを刷った枠だけのおみくじを生成するので、
   * 画像が揃う前でも印刷経路の動作確認ができる。
   */
  function makePlaceholder(item, widthDots) {
    var w = floorTo8(widthDots);
    var h = Math.round(w * 1.4);
    var canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    var ctx = canvas.getContext('2d');

    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = '#000000';
    ctx.lineWidth = 6;
    ctx.strokeRect(20, 20, w - 40, h - 40);
    ctx.lineWidth = 2;
    ctx.strokeRect(36, 36, w - 72, h - 72);

    ctx.fillStyle = '#000000';
    ctx.textAlign = 'center';
    ctx.font = '32px "Hiragino Mincho ProN", serif';
    ctx.fillText('Ceria fi Ixtigna', w / 2, 130);
    ctx.font = 'bold 120px "Hiragino Mincho ProN", serif';
    ctx.fillText(item.id, w / 2, h / 2 + 20);
    ctx.font = '40px "Hiragino Mincho ProN", serif';
    ctx.fillText(item.label, w / 2, h / 2 + 110);
    ctx.font = '24px sans-serif';
    ctx.fillText('（画像未設定のプレースホルダー）', w / 2, h - 90);

    return canvas;
  }

  /**
   * canvas を 1bit ラスターに変換して base64 を返す。
   * Floyd–Steinberg 誤差拡散でディザをかける。
   * 出力は 1画素=1bit、MSB先頭、1行あたり width/8 バイト、1 が黒ドット。
   */
  function toRasterBase64(canvas, options) {
    options = options || {};
    var threshold = typeof options.threshold === 'number' ? options.threshold : 128;
    var invert = !!options.invert;

    var w = canvas.width;
    var h = canvas.height;
    var ctx = canvas.getContext('2d');
    var src = ctx.getImageData(0, 0, w, h).data;

    // グレースケール化（アルファは白背景に合成）
    var gray = new Float32Array(w * h);
    for (var i = 0, p = 0; i < gray.length; i++, p += 4) {
      var a = src[p + 3] / 255;
      var r = src[p] * a + 255 * (1 - a);
      var g = src[p + 1] * a + 255 * (1 - a);
      var b = src[p + 2] * a + 255 * (1 - a);
      gray[i] = 0.299 * r + 0.587 * g + 0.114 * b;
    }

    var bytesPerRow = w / 8;
    var out = new Uint8Array(bytesPerRow * h);

    for (var y = 0; y < h; y++) {
      for (var x = 0; x < w; x++) {
        var idx = y * w + x;
        var old = gray[idx];
        var isBlack = old < threshold;
        var newVal = isBlack ? 0 : 255;
        var err = old - newVal;

        if (isBlack !== invert) {
          out[y * bytesPerRow + (x >> 3)] |= (0x80 >> (x & 7));
        }

        // 誤差を右・左下・下・右下へ拡散
        if (x + 1 < w)              gray[idx + 1]         += err * 7 / 16;
        if (y + 1 < h) {
          if (x > 0)                gray[idx + w - 1]     += err * 3 / 16;
                                    gray[idx + w]         += err * 5 / 16;
          if (x + 1 < w)            gray[idx + w + 1]     += err * 1 / 16;
        }
      }
    }

    return { width: w, height: h, base64: bytesToBase64(out) };
  }

  function bytesToBase64(bytes) {
    var chunk = 0x8000;
    var parts = [];
    for (var i = 0; i < bytes.length; i += chunk) {
      parts.push(String.fromCharCode.apply(null, bytes.subarray(i, i + chunk)));
    }
    return btoa(parts.join(''));
  }

  /**
   * おみくじ1件を印刷用 canvas にする。
   * 画像が無い（未用意・パス違い）場合はプレースホルダーにフォールバックする。
   */
  function renderItem(item, widthDots) {
    if (!item.image) {
      return Promise.resolve({ canvas: makePlaceholder(item, widthDots), placeholder: true });
    }
    return loadImage(item.image).then(function (img) {
      return { canvas: fitToWidth(img, widthDots), placeholder: false };
    }).catch(function () {
      return { canvas: makePlaceholder(item, widthDots), placeholder: true };
    });
  }

  global.Raster = {
    loadImage: loadImage,
    fitToWidth: fitToWidth,
    makePlaceholder: makePlaceholder,
    toRasterBase64: toRasterBase64,
    renderItem: renderItem
  };
})(window);
