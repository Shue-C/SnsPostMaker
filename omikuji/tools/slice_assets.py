#!/usr/bin/env python3
"""design/sample.png から画面用の装飾パーツを切り出す。

装飾はSVG等で描き起こさず、原画のピクセルをそのまま使う。
クリーム地や空の上に描かれた線画は、局所的な地色からの色差をアルファに変換して
切り抜く（アンチエイリアスを保ったまま透過になる）。

    python3 omikuji/tools/slice_assets.py

出力先: omikuji/assets/
"""
import math
import os
import sys

from PIL import Image, ImageChops, ImageEnhance, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, 'design', 'sample.png')
OUT = os.path.join(ROOT, 'assets')

# 魔法陣の中心と半径（原画の座標）
SIGIL_CX, SIGIL_CY = 512, 715
CORE_R = 145      # 中心の光条＋クリスタル
RING_R0 = 145     # ルーン環の内側
RING_R1 = 215     # ルーン環の外側

# リボンの位置（環の下部を隠している）
RIBBON_BOX = (328, 812, 694, 930)

# 背景バンド（城と空）の切り出し範囲。左右は外周の枠線を避けて内側で切る。
BAND_BOX = (33, 500, 991, 1004)
BAND_FADE = 26      # 上下の端を紙になじませるフェード幅


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


def key_out(im, bg=None, low=10, high=60, warm_only=False):
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
            if warm_only and a:
                # 金の線は暖色（R>B）。城や空の青灰色はここで落とす。
                warm = (r - b - 8) / 28.0
                a = int(a * min(1.0, max(0.0, warm)))
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


def ring_mask(size, cx, cy, r0, r1, feather=6):
    """円環（r0〜r1）のマスク。境界はフェードさせる。"""
    w, h = size
    m = Image.new('L', (w, h), 0)
    px = m.load()
    for y in range(h):
        dy = y - cy
        for x in range(w):
            dx = x - cx
            d = math.hypot(dx, dy)
            if d < r0 - feather or d > r1 + feather:
                v = 0
            elif d < r0:
                v = int(255 * (d - (r0 - feather)) / feather)
            elif d > r1:
                v = int(255 * ((r1 + feather) - d) / feather)
            else:
                v = 255
            px[x, y] = v
    return m


def disc_mask(size, cx, cy, r, feather=6, clip_below=None):
    w, h = size
    m = Image.new('L', (w, h), 0)
    px = m.load()
    for y in range(h):
        if clip_below is not None and y > clip_below:
            continue
        dy = y - cy
        for x in range(w):
            d = math.hypot(x - cx, dy)
            if d > r:
                v = 0
            elif d > r - feather:
                v = int(255 * (r - d) / feather)
            else:
                v = 255
            px[x, y] = v
    return m


def sector_mask(size, cx, cy, a0, a1, feather=12):
    """角度 a0〜a1（度、+x軸から時計回り／下が90度）のマスク。"""
    w, h = size
    m = Image.new('L', (w, h), 0)
    px = m.load()
    for y in range(h):
        for x in range(w):
            ang = math.degrees(math.atan2(y - cy, x - cx)) % 360
            if a0 <= ang <= a1:
                d = min(ang - a0, a1 - ang)
                px[x, y] = 255 if d >= feather else int(255 * d / feather)
    return m


def soften(im, cx, cy, r_full, r_fade, radius=34, clip_below=None):
    """円形の範囲を強くぼかして、そこに描かれた図形を消す。

    水彩の空は元々なめらかなので、ぼかすと線画だけが溶けて地が残る。
    """
    # 先に彩度を落としてからぼかす。そのまま暈すとクリスタルの青が
    # 大きな青いにじみとして残ってしまうため。
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
    mean = tuple(int(sum(im.getdata(i)) / (im.width * im.height)) for i in range(3))
    flat = ImageChops.add(ImageChops.subtract(im, base, scale=1, offset=0),
                          Image.new('RGB', im.size, mean))
    return flat


# 切り出した各パーツの原画上の位置 name -> (x, y, w, h)
PLACED = {}

DESIGN_W, DESIGN_H = 1024, 1536


def write_css():
    """原画の座標をそのまま使える CSS を生成する。

    画面は 1024x1536 の「原画そのままの座標系」を組み、
    ブラウザ側で画面サイズに合わせて拡大縮小する。
    """
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
    path = os.path.join(ROOT, 'css', 'assets.css')
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print('%-16s %s' % ('assets.css', path))


# ---------------------------------------------------------------- パーツ定義

CARD_CX = [189 + 160 * i for i in range(5)]
CARD_TOP, CARD_BOTTOM, CARD_HALF = 1035, 1299, 77

PARTS = {
    # 外周の飾り
    'corner-tl':     dict(box=(12, 12, 116, 142), alpha=True, tight=True),
    'corner-tr':     dict(box=(908, 12, 1012, 142), alpha=True, tight=True),
    'corner-bl':     dict(box=(12, 1394, 116, 1524), alpha=True, tight=True),
    'corner-br':     dict(box=(908, 1394, 1012, 1524), alpha=True, tight=True),

    # 枠線（1px を繰り返して辺に敷く）
    'border-v':      dict(box=(12, 300, 40, 301), alpha=True, bg=(247, 244, 241)),
    'border-h':      dict(box=(200, 12, 201, 40), alpha=True, bg=(248, 245, 242)),

    # ヘッダーの紋章
    'emblem-top':    dict(box=(376, 30, 648, 208), alpha=True, tight=True),

    # ARCANE FORTUNE / ORACLE OF FATE 脇の飾り罫
    'rule-small':    dict(box=(105, 108, 300, 134), alpha=True, tight=True, low=6),

    # 見出し脇の四芒星
    'star':          dict(box=(266, 234, 310, 278), alpha=True, tight=True),

    # タイトル下の点線＋小クリスタル
    'divider':       dict(box=(200, 318, 824, 378), alpha=True, tight=True,
                          low=4, high=30),

    # 「魔法のおみくじを〜」脇の雲飾り
    'cloud':         dict(box=(140, 378, 258, 440), alpha=True, tight=True,
                          low=6, high=40),

    # セクション見出しの飾り
    'section-rule':  dict(box=(340, 998, 445, 1032), alpha=True, tight=True, low=6),

    # フッターの円形紋章
    'emblem-bottom': dict(box=(444, 1420, 584, 1536), alpha=True, tight=True),
}

# おみくじ5種のカード（静的な図版なので文字ごと1枚絵として使う）
for i, cx in enumerate(CARD_CX):
    PARTS['card-%d' % (i + 1)] = dict(
        box=(cx - CARD_HALF, CARD_TOP, cx + CARD_HALF, CARD_BOTTOM))


def build_sigil(im):
    """魔法陣を「回るルーン環」と「中心の光条＋クリスタル」に分ける。"""
    box = (SIGIL_CX - RING_R1 - 8, SIGIL_CY - RING_R1 - 8,
           SIGIL_CX + RING_R1 + 8, SIGIL_CY + RING_R1 + 8)
    crop = im.crop(box)
    cx = SIGIL_CX - box[0]
    cy = SIGIL_CY - box[1]
    keyed = key_out(crop, low=13, high=68)

    # --- ルーン環 ---
    # 環は城の上に重なっているので、金色（暖色）だけを残して城を落とす。
    ring = key_out(crop, low=21, high=72, warm_only=True)
    ring.putalpha(ImageChops.multiply(
        ring.getchannel('A'), ring_mask(ring.size, cx, cy, RING_R0, RING_R1)))

    # 環の下部はリボンに隠れて欠けている（リボンの金縁も写り込む）ので、
    # リボンが掛かる角度帯をまるごと 180 度回した複製で置き換える。
    # 回転させて使う飾りなので、ルーンの向きの差は目立たない。
    donor = ring.rotate(180, resample=Image.BICUBIC, center=(cx, cy))
    patch = sector_mask(ring.size, cx, cy, 12, 168, feather=16)
    ring = Image.composite(donor, ring, patch)
    PLACED['sigil-ring'] = (box[0], box[1], ring.width, ring.height)
    ring.save(os.path.join(OUT, 'sigil-ring.png'))
    print('%-16s %dx%d' % ('sigil-ring', ring.width, ring.height))

    # --- 中心（光条＋クリスタル）---
    core = keyed.copy()
    core.putalpha(ImageChops.multiply(
        core.getchannel('A'), disc_mask(core.size, cx, cy, CORE_R)))
    # リボンより下は、クリスタルの先端が覗く中央の細い帯だけを残す
    cpx = core.load()
    for y in range(core.height):
        ya = y + box[1]
        if ya < RIBBON_BOX[1]:
            continue
        for x in range(core.width):
            xa = x + box[0]
            if ya > 848 or not (466 <= xa <= 558):
                cpx[x, y] = (0, 0, 0, 0)
    core, (ox, oy) = tighten(core)
    PLACED['sigil-core'] = (box[0] + ox, box[1] + oy, core.width, core.height)
    core.save(os.path.join(OUT, 'sigil-core.png'))
    print('%-16s %dx%d' % ('sigil-core', core.width, core.height))

    # --- リボン ---
    rb = key_out(im.crop(RIBBON_BOX), low=13, high=60)
    # 上辺の中央に写り込むクリスタルの先端を消す
    px = rb.load()
    for y in range(0, 42):
        for x in range(126, 240):
            px[x, y] = (0, 0, 0, 0)
    rb, (ox, oy) = tighten(rb)
    PLACED['ribbon'] = (RIBBON_BOX[0] + ox, RIBBON_BOX[1] + oy, rb.width, rb.height)
    rb.save(os.path.join(OUT, 'ribbon.png'))
    print('%-16s %dx%d' % ('ribbon', rb.width, rb.height))


def build_background(im):
    """城と空のバンド。魔法陣とクリスタルをぼかして消す（リボンは残す）。

    リボンは動かさない静的な要素なので背景に焼いたまま残し、
    HTML側では同じ位置にリボン画像を重ねる。こうすると回るルーン環が
    背景のリボンより手前・重ねたリボンより奥に入り、原画通りの前後関係になる。
    """
    band = im.crop(BAND_BOX).convert('RGB')
    cx = SIGIL_CX - BAND_BOX[0]
    cy = SIGIL_CY - BAND_BOX[1]
    band = soften(band, cx, cy, r_full=196, r_fade=252, radius=34,
                  clip_below=RIBBON_BOX[1] - BAND_BOX[1])

    # 上下の端を透過させて紙の地になじませる
    band = band.convert('RGBA')
    a = Image.new('L', band.size, 255)
    ap = a.load()
    for y in range(band.height):
        v = 255
        if y < BAND_FADE:
            v = int(255 * y / BAND_FADE)
        elif y > band.height - BAND_FADE:
            v = int(255 * (band.height - y) / BAND_FADE)
        for x in range(band.width):
            ap[x, y] = v
    band.putalpha(a)
    PLACED['bg-castles'] = (BAND_BOX[0], BAND_BOX[1], band.width, band.height)
    band.save(os.path.join(OUT, 'bg-castles.png'))
    print('%-16s %dx%d' % ('bg-castles', band.width, band.height))


def build():
    if not os.path.exists(SRC):
        sys.exit('原画が見つかりません: %s' % SRC)
    os.makedirs(OUT, exist_ok=True)
    im = Image.open(SRC).convert('RGB')

    for name, spec in sorted(PARTS.items()):
        crop = im.crop(spec['box'])
        ox = oy = 0
        if spec.get('alpha'):
            crop = key_out(crop, bg=spec.get('bg'),
                           low=spec.get('low', 10), high=spec.get('high', 60))
            if spec.get('tight'):
                crop, (ox, oy) = tighten(crop)
        PLACED[name] = (spec['box'][0] + ox, spec['box'][1] + oy,
                        crop.width, crop.height)
        crop.save(os.path.join(OUT, name + '.png'))
        print('%-16s %dx%d' % (name, crop.width, crop.height))

    # 紙の地。タイル用にムラを均す。
    paper = flatten_texture(im.crop((60, 150, 240, 310)))
    paper.save(os.path.join(OUT, 'paper.png'))
    print('%-16s %dx%d' % ('paper', paper.width, paper.height))

    build_sigil(im)
    build_background(im)
    write_css()


if __name__ == '__main__':
    build()
