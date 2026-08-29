#!/usr/bin/env python3
"""design/o_NN.png（原画）から images/NN.png（印刷用）を作る。

原画は 3215px 幅、印刷は 416px 幅（58mm紙）なので約7.7倍の縮小になる。
そのまま縮めると細線が灰色に薄まり、誤差拡散で網点になって潰れるため、
  帯の間引き → 縮小 → アンシャープ → レベル補正 → Floyd-Steinberg
の順で処理して、線を黒として残したまま2値化する。

出力は 1bit PNG。アプリ側も同じ Floyd-Steinberg をかけるが、
値が 0/255 しかない画像では誤差が出ないので二重処理にはならない。

## 帯の間引き（layout）

紙幅が固定なので、原画の小さい文字は縮小すると読めなくなる。
203dpi のサーマルプリンターで漢字が読める下限は約24ドット（3mm）。
原画の各段を測ると次のようになっている（58mm紙・416ドット幅に換算）。

    冠飾り 47 / タイトル 28 / 大吉 60 / DAIKICHI 11 / 罫線 7 /
    挿絵 280 / 一言 17 / 罫線 7 / 本文4行 9x4 / 運勢表 145 /
    下部の格言4行 6〜9 / 罫線飾り 18 / 下部紋章 41

読めるのは「大吉」「一言」まで。本文・下部の格言・運勢表の中身は
9ドット前後（1.1mm）しかなく、印刷すると黒い塊になる。
そこで、読めない段を切り落とした版を作れるようにしてある。

    full     … 原画のまま（何も削らない）
    trim     … 本文4行と下部の格言ブロックを削る（運勢表は残す）
    minimal  … さらに運勢表も削る。紙に載る文字がすべて読める版

切るのは段と段の間の余白の中央なので、左右の枠線は素直に繋がる。
"""
import os
import sys
from PIL import Image, ImageEnhance, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DESIGN = os.path.join(ROOT, 'design')
OUT = os.path.join(ROOT, 'images')

WIDTH = 416          # 58mm紙の印字幅（8の倍数）
LAYOUT = 'full'      # full | trim | minimal
UNSHARP = (1.2, 260, 2)   # radius, percent, threshold
CONTRAST = 1.30
GAMMA = 0.95         # 1未満で中間調を暗くする（線を残す方向）

# 2値化のしかた
#   'threshold' … 単純な閾値。線画にはこちらが鮮明。既定。
#   'dither'    … Floyd-Steinberg 誤差拡散。写真や本物の階調がある絵向け。
BINARIZE = 'threshold'
THRESHOLD = 135      # 'threshold' のときの境目。上げると線が太る


def load_gray(path):
    im = Image.open(path)
    if im.mode in ('RGBA', 'LA', 'P'):
        bg = Image.new('RGB', im.size, 'white')
        im = im.convert('RGBA')
        bg.paste(im, mask=im.split()[-1])
        im = bg
    return im.convert('L')


def find_bands(g, margin=240, gap=30, ink=6):
    """枠の内側を見て、文字や絵の「段」を拾う。段と段の間は余白。"""
    w, h = g.size
    px = g.load()
    x0, x1 = margin, w - margin
    out, start, blank = [], None, 0
    for y in range(h):
        v = sum(1 for x in range(x0, x1, 4) if px[x, y] < 150) * 4
        if v > ink:
            if start is None:
                start = y
            blank = 0
        elif start is not None:
            blank += 1
            if blank >= gap:
                out.append((start, y - blank))
                start = None
                blank = 0
    if start is not None:
        out.append((start, h - 1))
    return out


# 原画の段構成（5種とも共通）。番号は find_bands の並び順。
#   0 冠飾り / 1 タイトル / 2 運勢名 / 3 ローマ字 / 4 罫線 / 5 挿絵
#   6 一言 / 7 罫線 / 8-11 本文4行 / 12 運勢表 / 13.. 下部の格言 / 最後 下部紋章
BODY_FIRST, BODY_LAST = 8, 11
TABLE = 12


def drop_ranges(bands, layout):
    """削る段の番号を返す。"""
    if layout == 'full':
        return []
    last = len(bands) - 1
    drops = [(BODY_FIRST, BODY_LAST)]          # 本文4行
    if layout == 'minimal':
        drops.append((TABLE, last - 1))        # 運勢表ごと下部の格言まで
    else:
        drops.append((TABLE + 1, last - 1))    # 下部の格言だけ
    return [(a, b) for a, b in drops if a <= b <= last]


def cut_bands(g, layout):
    """読めない段を切り落とす。切り口は段と段の間の余白の中央。"""
    if layout == 'full':
        return g, []
    bands = find_bands(g)
    if len(bands) < 15:
        raise SystemExit('段の構成が想定と違います（%d段）。layout=full で試してください。' % len(bands))
    removed = []
    for a, b in drop_ranges(bands, layout):
        top = (bands[a - 1][1] + bands[a][0]) // 2
        bottom = (bands[b][1] + bands[b + 1][0]) // 2
        removed.append((top, bottom))
    removed.sort()

    keep, y = [], 0
    for top, bottom in removed:
        if top > y:
            keep.append((y, top))
        y = bottom
    if y < g.height:
        keep.append((y, g.height))

    total = sum(b - a for a, b in keep)
    out = Image.new('L', (g.width, total), 255)
    at = 0
    for a, b in keep:
        out.paste(g.crop((0, a, g.width, b)), (0, at))
        at += b - a
    return out, removed


def to_print(path, width=WIDTH, layout=LAYOUT):
    g = load_gray(path)
    g, _ = cut_bands(g, layout)
    h = max(1, round(g.height * width / g.width))
    g = g.resize((width, h), Image.LANCZOS)
    g = g.filter(ImageFilter.UnsharpMask(*UNSHARP))
    g = ImageEnhance.Contrast(g).enhance(CONTRAST)
    g = g.point([min(255, round(255 * ((i / 255) ** GAMMA))) for i in range(256)])
    return g


def binarize(g, how=None, threshold=None):
    """白黒2値にする。

    この原画は隅々まで線画なので、誤差拡散をかけると線の周りに網点が散って
    かえって汚くなる。単純な閾値のほうが鮮明に出るため、既定は 'threshold'。
    写真や本物の階調がある絵を刷るときだけ 'dither' を使う。
    """
    how = how or BINARIZE
    if how == 'dither':
        return g.convert('1', dither=Image.FLOYDSTEINBERG)
    t = THRESHOLD if threshold is None else threshold
    return g.point(lambda v: 255 if v >= t else 0, mode='1')


def main():
    args = [a for a in sys.argv[1:]]
    layout = LAYOUT
    how = BINARIZE
    for a in list(args):
        if a in ('full', 'trim', 'minimal'):
            layout = a
            args.remove(a)
        elif a in ('threshold', 'dither'):
            how = a
            args.remove(a)
    globals()['BINARIZE'] = how
    width = int(args[0]) if args else WIDTH
    if width % 8:
        raise SystemExit('幅は8の倍数にしてください: %d' % width)
    print('layout=%s  2値化=%s  幅=%dドット（%.1fmm）'
          % (layout, how, width, width / 203 * 25.4))
    os.makedirs(OUT, exist_ok=True)
    names = sorted(f for f in os.listdir(DESIGN)
                   if f.startswith('o_') and f.endswith('.png'))
    if not names:
        raise SystemExit('design/o_*.png が見つかりません')
    for name in names:
        num = name[2:-4]
        src = os.path.join(DESIGN, name)
        dst = os.path.join(OUT, num + '.png')
        g = to_print(src, width, layout)
        bw = binarize(g)
        bw.save(dst, optimize=True)
        black = sum(1 for v in bw.convert('L').tobytes() if v == 0)
        print('%-10s -> images/%-8s %dx%d = %.0f x %.0f mm  黒 %.1f%%  %d KB'
              % (name, num + '.png', bw.width, bw.height,
                 bw.width / 203 * 25.4, bw.height / 203 * 25.4,
                 black / (bw.width * bw.height) * 100,
                 os.path.getsize(dst) // 1024))


if __name__ == '__main__':
    main()
