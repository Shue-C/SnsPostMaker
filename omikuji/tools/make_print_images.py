#!/usr/bin/env python3
"""design/o_NN.png（原画）から images/NN.png（印刷用）を作る。

原画は 3215px 幅、印刷は 416px 幅（58mm紙）なので約7.7倍の縮小になる。
そのまま縮めると細線が灰色に薄まり、誤差拡散で網点になって潰れるため、
  縮小 → アンシャープ → レベル補正 → Floyd-Steinberg
の順で処理して、線を黒として残したまま2値化する。

出力は 1bit PNG。アプリ側も同じ Floyd-Steinberg をかけるが、
値が 0/255 しかない画像では誤差が出ないので二重処理にはならない。
"""
import os
import sys
from PIL import Image, ImageEnhance, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DESIGN = os.path.join(ROOT, 'design')
OUT = os.path.join(ROOT, 'images')

WIDTH = 416          # 58mm紙の印字幅（8の倍数）
UNSHARP = (2.0, 180, 3)   # radius, percent, threshold
CONTRAST = 1.35
GAMMA = 0.88         # 1未満で中間調を暗くする（線を残す方向）


def load_gray(path):
    im = Image.open(path)
    if im.mode in ('RGBA', 'LA', 'P'):
        bg = Image.new('RGB', im.size, 'white')
        im = im.convert('RGBA')
        bg.paste(im, mask=im.split()[-1])
        im = bg
    return im.convert('L')


def to_print(path, width=WIDTH):
    g = load_gray(path)
    h = max(1, round(g.height * width / g.width))
    g = g.resize((width, h), Image.LANCZOS)
    g = g.filter(ImageFilter.UnsharpMask(*UNSHARP))
    g = ImageEnhance.Contrast(g).enhance(CONTRAST)
    g = g.point([min(255, round(255 * ((i / 255) ** GAMMA))) for i in range(256)])
    return g


def dither(g):
    """Floyd-Steinberg で2値化（Pillow の convert('1') と同じ拡散）。"""
    return g.convert('1', dither=Image.FLOYDSTEINBERG)


def main():
    width = int(sys.argv[1]) if len(sys.argv) > 1 else WIDTH
    if width % 8:
        raise SystemExit('幅は8の倍数にしてください: %d' % width)
    os.makedirs(OUT, exist_ok=True)
    names = sorted(f for f in os.listdir(DESIGN)
                   if f.startswith('o_') and f.endswith('.png'))
    if not names:
        raise SystemExit('design/o_*.png が見つかりません')
    for name in names:
        num = name[2:-4]
        src = os.path.join(DESIGN, name)
        dst = os.path.join(OUT, num + '.png')
        g = to_print(src, width)
        bw = dither(g)
        bw.save(dst, optimize=True)
        black = sum(1 for v in bw.getdata() if v == 0)
        print('%-10s -> images/%-8s %dx%d  黒 %.1f%%  %d KB'
              % (name, num + '.png', bw.width, bw.height,
                 black / (bw.width * bw.height) * 100,
                 os.path.getsize(dst) // 1024))


if __name__ == '__main__':
    main()
