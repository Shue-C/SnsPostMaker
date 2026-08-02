#!/usr/bin/env python3
"""design/ の原画から画面用の装飾パーツを切り出す。

装飾はSVG等で描き起こさず、原画のピクセルをそのまま使う。
クリーム地や空の上に描かれた線画は、局所的な地色からの色差をアルファに変換して
切り抜く（アンチエイリアスを保ったまま透過になる）。

    python3 omikuji/tools/slice_assets.py

入力:
    design/sample.png … 画面全体のデザイン原画
    design/maho.png   … 魔法陣（真円・白背景）。sample の魔法陣は楕円に歪んでいて
                        回すと膨らみ縮みして見えるため、こちらを使う。
出力:
    assets/*.png      … パーツ画像（原画の解像度のまま＝高精細）
    css/assets.css    … 設計座標での配置（自動生成）

座標はすべて「設計座標」1024x1536 で書く。原画がこれより大きくても
（現在は 2000x3000）自動で換算するので、この値は書き換えなくてよい。
画面側も同じ 1024x1536 の座標系で組み、表示時に画面サイズへ合わせて拡大縮小する。
"""
import math
import os
import sys

from PIL import Image, ImageChops, ImageEnhance, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'assets')
SRC = os.path.join(ROOT, 'design', 'sample.png')
SRC_SIGIL = os.path.join(ROOT, 'design', 'maho.png')

DESIGN_W, DESIGN_H = 1024, 1536

# --- 魔法陣 ---------------------------------------------------------------
# sample 上での中心と外周半径（設計座標）。ここに maho.png を合わせて置く。
SIGIL_CX, SIGIL_CY = 512, 720
SIGIL_R = 215
# maho.png 側の中心・外周半径・「環と中心の境目」（実測値、maho のピクセル単位）
MAHO_CX, MAHO_CY = 628, 622
MAHO_R = 581.5
MAHO_SPLIT = 402
MAHO_EDGE = 600          # これより外は切り捨てる

# --- リボン ---------------------------------------------------------------
RIBBON_BOX = (318, 800, 706, 945)
# リボンの上、左右の折り返しに挟まれた空きの範囲。sample ではここに
# クリスタルの先端が写り込むので消す（クリスタルは maho 側から重ねる）。
RIBBON_GAP = (462, 562, 850)     # x0, x1, この y より上

# --- 背景バンド -----------------------------------------------------------
BAND_BOX = (33, 500, 991, 1004)
BAND_FADE = 26

# 左右反転して対になる飾り
MIRRORED = ('rule-small', 'cloud', 'section-rule', 'star')

# 切り出した各パーツの設計座標上の位置 name -> (x, y, w, h)
PLACED = {}


# ---------------------------------------------------------------- 基本操作

def bg_color(im, margin=3):
    """crop の外周ピクセルの中央値を「地の色」とみなす。"""
    w, h = im.size
    margin = max(1, min(margin, w // 2, h // 2))
    px = im.load()
    samples = []
    for x in range(w):
        for y in list(range(margin)) + list(range(h - margin, h)):
            samples.append(px[x, y])
    for y in range(h):
        for x in list(range(margin)) + list(range(w - margin, w)):
            samples.append(px[x, y])
    samples.sort(key=lambda c: c[0] + c[1] + c[2])
    return samples[len(samples) // 2]


def key_out(im, bg=None, low=10, high=60):
    """地の色からの距離をアルファにする。

    low  … これ以下の色差は完全透過
    high … これ以上の色差は完全不透明
    半透明部分は地の色の混色を取り除き、元の絵柄を復元する。
    """
    im = im.convert('RGB')
    if bg is None:
        bg = bg_color(im)
    w, h = im.size
    src = im.load()
    out = Image.new('RGBA', (w, h))
    dst = out.load()
    span = float(high - low)
    for y in range(h):
        for x in range(w):
            r, g, b = src[x, y]
            d = max(abs(r - bg[0]), abs(g - bg[1]), abs(b - bg[2]))
            a = 0 if d <= low else 255 if d >= high else int(255 * (d - low) / span)
            if a == 0:
                dst[x, y] = (0, 0, 0, 0)
            else:
                f = a / 255.0
                rr = int(min(255, max(0, (r - bg[0] * (1 - f)) / f)))
                gg = int(min(255, max(0, (g - bg[1] * (1 - f)) / f)))
                bb = int(min(255, max(0, (b - bg[2] * (1 - f)) / f)))
                dst[x, y] = (rr, gg, bb, a)
    return out


def tighten(im, pad=2):
    """透過部分を刈り取って外接矩形に詰める。(画像, 左上のずれ) を返す。"""
    bbox = im.getbbox()
    if not bbox:
        return im, (0, 0)
    x0, y0, x1, y1 = bbox
    x0 = max(0, x0 - pad); y0 = max(0, y0 - pad)
    return im.crop((x0, y0, min(im.width, x1 + pad), min(im.height, y1 + pad))), (x0, y0)


def keep_largest_blob(im, thresh=40):
    """アルファの最大連結成分だけを残す。

    リボンは空と城の上に描かれているので、色差だけで抜くと周囲の雲や
    城の切れ端が小さな島として残る。ひと続きの本体だけを採用して落とす。
    """
    w, h = im.size
    a = im.getchannel('A').load()
    seen = bytearray(w * h)
    best = None
    best_n = 0
    for sy in range(h):
        for sx in range(w):
            i0 = sy * w + sx
            if seen[i0] or a[sx, sy] < thresh:
                continue
            stack = [i0]
            seen[i0] = 1
            cells = []
            while stack:
                i = stack.pop()
                cells.append(i)
                y, x = divmod(i, w)
                for nx, ny in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
                    if 0 <= nx < w and 0 <= ny < h:
                        j = ny * w + nx
                        if not seen[j] and a[nx, ny] >= thresh:
                            seen[j] = 1
                            stack.append(j)
            if len(cells) > best_n:
                best_n = len(cells)
                best = cells
    if not best:
        return im
    mask = Image.new('L', (w, h), 0)
    mp = mask.load()
    for i in best:
        y, x = divmod(i, w)
        mp[x, y] = 255
    # 本体の内側（文字などの穴）は残すため、輪郭を少し太らせてから塗りつぶす
    mask = mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))
    im = im.copy()
    im.putalpha(ImageChops.multiply(im.getchannel('A'), mask))
    return im


def radial_mask(size, cx, cy, r0, r1, feather=6):
    """r0〜r1 の円環（r0=0 なら円板）のマスク。境界はフェードさせる。"""
    w, h = size
    m = Image.new('L', (w, h), 0)
    px = m.load()
    for y in range(h):
        dy = y - cy
        for x in range(w):
            d = math.hypot(x - cx, dy)
            if d > r1 + feather or (r0 and d < r0 - feather):
                v = 0
            elif d > r1:
                v = int(255 * (r1 + feather - d) / feather)
            elif r0 and d < r0:
                v = int(255 * (d - (r0 - feather)) / feather)
            else:
                v = 255
            px[x, y] = v
    return m


def soften(im, cx, cy, r_full, r_fade, radius=34, clip_below=None):
    """円形の範囲を強くぼかして、そこに描かれた図形を消す。

    水彩の空は元々なめらかなので、ぼかすと線画だけが溶けて地が残る。
    先に彩度を落とすのは、そのまま暈すとクリスタルの青が大きな青いにじみとして
    残ってしまうため。
    """
    blurred = ImageEnhance.Color(im).enhance(0.28).filter(
        ImageFilter.GaussianBlur(radius))
    mask = Image.new('L', im.size, 0)
    px = mask.load()
    for y in range(im.size[1]):
        if clip_below is not None and y > clip_below:
            continue
        for x in range(im.size[0]):
            d = math.hypot(x - cx, y - cy)
            if d <= r_full:
                v = 255
            elif d >= r_fade:
                v = 0
            else:
                v = int(255 * (r_fade - d) / (r_fade - r_full))
            if clip_below is not None and clip_below - y < 12:
                v = int(v * (clip_below - y) / 12.0)
            px[x, y] = v
    return Image.composite(blurred, im, mask)


def flatten_texture(im, blur=24):
    """紙のパッチから大きなムラを取り除き、タイルの継ぎ目を目立たなくする。"""
    im = im.convert('RGB')
    base = im.filter(ImageFilter.GaussianBlur(blur))
    n = im.width * im.height
    mean = tuple(int(sum(im.getchannel(i).getdata()) / n) for i in range(3))
    return ImageChops.add(ImageChops.subtract(im, base, scale=1, offset=0),
                          Image.new('RGB', im.size, mean))


# ---------------------------------------------------------------- パーツ定義

# 設計座標での切り出し範囲。tight=True のものは中身に合わせて自動で詰める。
PARTS = {
    # 外周の飾り
    'corner-tl':     dict(box=(10, 10, 108, 148), alpha=True, tight=True),
    'corner-tr':     dict(box=(916, 10, 1014, 148), alpha=True, tight=True),
    'corner-bl':     dict(box=(10, 1388, 108, 1526), alpha=True, tight=True),
    'corner-br':     dict(box=(916, 1388, 1014, 1526), alpha=True, tight=True),

    # 枠線（1px を繰り返して辺に敷く）
    'border-v':      dict(box=(12, 300, 40, 301), alpha=True),
    'border-h':      dict(box=(200, 12, 201, 40), alpha=True),

    # ヘッダーの紋章
    'emblem-top':    dict(box=(366, 34, 658, 220), alpha=True, tight=True),

    # ARCANE FORTUNE / ORACLE OF FATE 脇の飾り罫
    'rule-small':    dict(box=(105, 111, 290, 144), alpha=True, tight=True, low=7),

    # 見出し脇の四芒星
    'star':          dict(box=(266, 228, 308, 282), alpha=True, tight=True),

    # タイトル下の点線＋小クリスタル
    'divider':       dict(box=(190, 318, 834, 378), alpha=True, tight=True,
                          low=5, high=32),

    # 「魔法のおみくじを〜」脇の雲飾り
    'cloud':         dict(box=(130, 380, 252, 445), alpha=True, tight=True,
                          low=9, high=44),

    # セクション見出しの飾り（見出し文字を巻き込まないよう罫線の範囲だけ切る）
    'section-rule':  dict(box=(325, 1002, 420, 1030), alpha=True, tight=True, low=6),

    # フッターの円形紋章
    'emblem-bottom': dict(box=(438, 1412, 592, 1534), alpha=True, tight=True),
}

# おみくじ5種のカード（静的な図版なので文字ごと1枚絵として使う）。
# 原画のカードは幅も間隔も揃っていないので、1枚ずつ実測した位置で切る。
CARD_BOXES = [
    (111, 1035, 268, 1299),
    (281, 1035, 426, 1299),
    (440, 1035, 584, 1299),
    (598, 1035, 742, 1299),
    (756, 1035, 901, 1299),
]
for _i, _b in enumerate(CARD_BOXES):
    PARTS['card-%d' % (_i + 1)] = dict(box=_b)


# ---------------------------------------------------------------- 生成

def write_css():
    lines = [
        '/* slice_assets.py が自動生成。直接編集しないこと。 */',
        '/* 原画 %dx%d の座標系にパーツを配置する。 */' % (DESIGN_W, DESIGN_H),
        '',
        '.deco {',
        '  position: absolute;',
        '  background-repeat: no-repeat;',
        '  background-size: 100% 100%;',
        '  pointer-events: none;',
        '}',
        '',
    ]
    for name in sorted(PLACED):
        x, y, w, h = PLACED[name]
        lines.append('.a-%s {' % name)
        lines.append('  left: %dpx; top: %dpx; width: %dpx; height: %dpx;' % (x, y, w, h))
        lines.append("  background-image: url('../assets/%s.png');" % name)
        lines.append('}')
        if name in MIRRORED:
            # 対になる飾りは同じ画像を左右反転して使う
            lines.append('.a-%s.mirror-x {' % name)
            lines.append('  left: %dpx;' % (DESIGN_W - x - w))
            lines.append('  transform: scaleX(-1);')
            lines.append('}')
    path = os.path.join(ROOT, 'css', 'assets.css')
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print('%-16s %s' % ('assets.css', path))


def report(name, im, x, y):
    PLACED[name] = (round(x), round(y), round(im.width / SCALE), round(im.height / SCALE))
    print('%-16s %4dx%-4d → 設計 %3dx%-3d @ (%d,%d)' % (
        name, im.width, im.height, PLACED[name][2], PLACED[name][3], PLACED[name][0], PLACED[name][1]))


def build_sigil():
    """魔法陣を「回るルーン環」と「中心の光条＋クリスタル」に分ける。

    maho.png は真円で、リボンにも城にも隠れていないので、
    以前のような欠けの補完や城の写り込み除去は要らない。
    """
    im = Image.open(SRC_SIGIL).convert('RGB')
    keyed = key_out(im, bg=(255, 255, 255), low=12, high=64)

    # sample 上の魔法陣に合わせる倍率（maho ピクセル → 設計座標）
    to_design = SIGIL_R / MAHO_R
    # 出力は sample のパーツと同じ精細さに揃える
    px_per_design = SCALE
    zoom = to_design * px_per_design

    for name, r0, r1 in (('sigil-ring', MAHO_SPLIT, MAHO_EDGE),
                         ('sigil-core', 0, MAHO_SPLIT)):
        part = keyed.copy()
        part.putalpha(ImageChops.multiply(
            part.getchannel('A'),
            radial_mask(part.size, MAHO_CX, MAHO_CY, r0, r1)))
        # 中心が画像のど真ん中に来るよう正方形で切る。
        # tighten で詰めると中心が数pxずれ、CSSで回したときに振れてしまう。
        half = r1 + 8
        part = part.crop((round(MAHO_CX - half), round(MAHO_CY - half),
                          round(MAHO_CX + half), round(MAHO_CY + half)))
        side = max(1, round(2 * half * zoom))
        part = part.resize((side, side), Image.LANCZOS)
        part.save(os.path.join(OUT, name + '.png'))
        report(name, part,
               SIGIL_CX - half * to_design, SIGIL_CY - half * to_design)


def build_ribbon(im):
    box = tuple(round(v * SCALE) for v in RIBBON_BOX)
    rb = key_out(im.crop(box), low=24, high=74)
    # 上辺の中央に写り込むクリスタルの先端を消す
    gx0, gx1, gy = RIBBON_GAP
    px = rb.load()
    for y in range(0, min(rb.height, round((gy - RIBBON_BOX[1]) * SCALE))):
        for x in range(round((gx0 - RIBBON_BOX[0]) * SCALE),
                       min(rb.width, round((gx1 - RIBBON_BOX[0]) * SCALE))):
            px[x, y] = (0, 0, 0, 0)
    rb = keep_largest_blob(rb)
    rb, (ox, oy) = tighten(rb)
    rb.save(os.path.join(OUT, 'ribbon.png'))
    report('ribbon', rb, RIBBON_BOX[0] + ox / SCALE, RIBBON_BOX[1] + oy / SCALE)


def build_background(im):
    """城と空のバンド。魔法陣とクリスタルをぼかして消す（リボンは残す）。

    リボンは動かさない静的な要素なので背景に焼いたまま残し、
    HTML側では同じ位置にリボン画像を重ねる。こうすると回るルーン環が
    背景のリボンより手前・重ねたリボンより奥に入り、原画通りの前後関係になる。
    """
    box = tuple(round(v * SCALE) for v in BAND_BOX)
    band = im.crop(box).convert('RGB')
    band = soften(band,
                  (SIGIL_CX - BAND_BOX[0]) * SCALE,
                  (SIGIL_CY - BAND_BOX[1]) * SCALE,
                  r_full=196 * SCALE, r_fade=252 * SCALE, radius=round(34 * SCALE),
                  clip_below=round((RIBBON_BOX[1] + 12 - BAND_BOX[1]) * SCALE))

    # 上下の端を透過させて紙の地になじませる
    band = band.convert('RGBA')
    fade = round(BAND_FADE * SCALE)
    a = Image.new('L', band.size, 255)
    ap = a.load()
    for y in range(band.height):
        v = 255
        if y < fade:
            v = int(255 * y / fade)
        elif y > band.height - fade:
            v = int(255 * (band.height - y) / fade)
        for x in range(band.width):
            ap[x, y] = v
    band.putalpha(a)
    band.save(os.path.join(OUT, 'bg-castles.png'))
    report('bg-castles', band, BAND_BOX[0], BAND_BOX[1])


def build():
    global SCALE
    if not os.path.exists(SRC) or not os.path.exists(SRC_SIGIL):
        sys.exit('原画が見つかりません: %s / %s' % (SRC, SRC_SIGIL))
    os.makedirs(OUT, exist_ok=True)
    im = Image.open(SRC).convert('RGB')
    SCALE = im.width / float(DESIGN_W)
    print('原画 %dx%d  設計座標との倍率 %.4f\n' % (im.width, im.height, SCALE))

    for name, spec in sorted(PARTS.items()):
        box = tuple(round(v * SCALE) for v in spec['box'])
        crop = im.crop(box)
        ox = oy = 0
        if spec.get('alpha'):
            crop = key_out(crop, bg=spec.get('bg'),
                           low=spec.get('low', 10), high=spec.get('high', 60))
            if spec.get('tight'):
                crop, (ox, oy) = tighten(crop)
        crop.save(os.path.join(OUT, name + '.png'))
        report(name, crop, spec['box'][0] + ox / SCALE, spec['box'][1] + oy / SCALE)

    # 紙の地。タイル用にムラを均す。
    paper = flatten_texture(im.crop(tuple(round(v * SCALE) for v in (60, 150, 240, 310))))
    paper.save(os.path.join(OUT, 'paper.png'))
    print('%-16s %dx%d（タイル）' % ('paper', paper.width, paper.height))

    build_sigil()
    build_ribbon(im)
    build_background(im)
    write_css()


SCALE = 1.0

if __name__ == '__main__':
    build()
