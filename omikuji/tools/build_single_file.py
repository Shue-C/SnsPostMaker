#!/usr/bin/env python3
"""アプリ全体を1枚のHTMLファイルに固める。

画像・フォント・CSS・JS をすべて埋め込むので、Webサーバーが要らなくなる。
iPad の「ファイル」アプリに置いて直接開く運用を想定している。

    python3 omikuji/tools/build_single_file.py [--scale 0.82] [--backend xml]

出力: omikuji/dist/omikuji-standalone.html

注意:
  file:// で開いたページからプリンターへ通信できるかはブラウザ依存で、
  Safari が拒否する可能性がある。実機で確認すること。
  SDK（epos-2.js）は同梱していないので、印刷方式は xml を既定にしている。
"""
import argparse
import base64
import io
import os
import re
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(ROOT, 'dist')
OUT = os.path.join(OUT_DIR, 'omikuji-standalone.html')

CSS_FILES = ['css/assets.css', 'css/style.css']
JS_FILES = ['js/config.js', 'js/raster.js', 'js/printer.js', 'js/draw.js', 'js/app.js']


def read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


# これより大きいPNGは非可逆WebPに置き換える。城の背景のような水彩画は
# PNGだと極端に大きくなるため。金の細線などの小さな線画はPNGのまま残す。
WEBP_THRESHOLD = 60 * 1024
WEBP_QUALITY = 88


def image_data_uri(path, scale):
    """画像をdata URIにする。scale<1 なら縮小して埋め込みサイズを抑える。"""
    im = Image.open(path)
    if scale < 1.0:
        w = max(1, round(im.width * scale))
        h = max(1, round(im.height * scale))
        im = im.resize((w, h), Image.LANCZOS)

    png = io.BytesIO()
    im.save(png, format='PNG', optimize=True)
    if len(png.getvalue()) <= WEBP_THRESHOLD:
        return 'data:image/png;base64,' + base64.b64encode(png.getvalue()).decode(), len(png.getvalue())

    webp = io.BytesIO()
    im.save(webp, format='WEBP', quality=WEBP_QUALITY, method=6)
    if len(webp.getvalue()) < len(png.getvalue()):
        return ('data:image/webp;base64,' + base64.b64encode(webp.getvalue()).decode(),
                len(webp.getvalue()))
    return 'data:image/png;base64,' + base64.b64encode(png.getvalue()).decode(), len(png.getvalue())


def inline_css(rel, scale, stats):
    css = read(rel)
    base = os.path.dirname(os.path.join(ROOT, rel))

    def rep(m):
        path = os.path.normpath(os.path.join(base, m.group(1)))
        uri, size = image_data_uri(path, scale)
        stats[os.path.basename(path)] = size
        return "url('%s')" % uri

    return re.sub(r"url\('([^']+\.png)'\)", rep, css)


# ------------------------------------------------------- フォントのサブセット

def parse_ranges(spec):
    """unicode-range の指定をコードポイントの区間リストにする。"""
    out = []
    for part in spec.split(','):
        part = part.strip().lower()
        if not part.startswith('u+'):
            continue
        part = part[2:]
        if '-' in part:
            a, b = part.split('-')
            out.append((int(a, 16), int(b, 16)))
        elif '?' in part:
            out.append((int(part.replace('?', '0'), 16),
                        int(part.replace('?', 'f'), 16)))
        else:
            v = int(part, 16)
            out.append((v, v))
    return out


def strip_comments(src, html=False):
    """コメントを落とす。画面に出ない漢字までフォントに含めないため。"""
    if html:
        return re.sub(r'<!--.*?-->', '', src, flags=re.S)
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
    return re.sub(r'(^|\s)//[^\n]*', r'\1', src)


def used_characters():
    """このアプリが表示しうる文字をかき集める。"""
    text = strip_comments(read('index.html'), html=True)
    for rel in JS_FILES:
        text += strip_comments(read(rel))
    # 記号や約物も含めてそのまま拾う（多めに入れておくほうが安全）
    return set(text)


def inline_fonts(stats):
    css = read('css/fonts.css')
    chars = used_characters()
    codes = sorted(ord(c) for c in chars)
    blocks = re.findall(r'@font-face\s*\{[^}]*\}', css)
    kept = []
    for b in blocks:
        m_url = re.search(r"url\('([^']+)'\)", b)
        m_rng = re.search(r'unicode-range:\s*([^;]+);', b)
        if not m_url:
            continue
        ranges = parse_ranges(m_rng.group(1)) if m_rng else [(0, 0x10FFFF)]
        if not any(a <= c <= z for c in codes for a, z in ranges):
            continue
        path = os.path.normpath(os.path.join(ROOT, 'css', m_url.group(1)))
        with open(path, 'rb') as f:
            data = f.read()
        stats[os.path.basename(path)] = len(data)
        uri = 'data:font/woff2;base64,' + base64.b64encode(data).decode()
        kept.append(b.replace(m_url.group(1), uri))
    return kept, len(blocks)


def embed_item_images(config_src, stats):
    """おみくじ画像（images/NN.png）も埋め込む。

    1ファイルで完結させるため、config.js の items[].image を data URI に置き換える。
    まだ用意されていない画像はパスのまま残し、アプリ側のプレースホルダーに任せる。
    """
    missing = []

    def rep(m):
        rel = m.group(1)
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            missing.append(rel)
            return m.group(0)
        uri, size = image_data_uri(path, 1.0)
        stats[os.path.basename(path)] = size
        return "image: '%s'" % uri

    out = re.sub(r"image: '(images/[^']+)'", rep, config_src)
    if missing:
        print('※ おみくじ画像が未配置のため %d 件はプレースホルダーになります: %s'
              % (len(missing), ', '.join(os.path.basename(m) for m in missing)))
    return out


# ------------------------------------------------------------------ 組み立て

def build(scale, backend):
    os.makedirs(OUT_DIR, exist_ok=True)
    stats = {}

    html = read('index.html')
    # 外部参照のタグをすべて外す（中身はあとで埋め込む）
    html = re.sub(r'\s*<link rel="stylesheet"[^>]*>', '', html)
    html = re.sub(r'\s*<script src="[^"]+"></script>', '', html)
    html = re.sub(r'<!--\s*実機で印刷する.*?-->\s*', '', html, flags=re.S)
    html = re.sub(r'<!--\s*<script src="js/epos-2\.js"></script>\s*-->\s*', '', html)

    faces, total_faces = inline_fonts(stats)
    css = '\n'.join(faces) + '\n'
    for rel in CSS_FILES:
        css += inline_css(rel, scale, stats) + '\n'

    js = []
    for rel in JS_FILES:
        body = read(rel)
        if rel.endswith('config.js'):
            body = re.sub(r"backend: '\w+'", "backend: '%s'" % backend, body, count=1)
            body = embed_item_images(body, stats)
        js.append('/* ===== %s ===== */\n%s' % (rel, body))
    js = '\n'.join(js)

    html = html.replace('</head>', '<style>\n%s</style>\n</head>' % css)
    html = html.replace('</body>', '<script>\n%s\n</script>\n</body>' % js)

    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(html)

    left = [m for m in re.findall(r'(?:src|href)="([^"]+)"', html) if not m.startswith('data:')]
    print('出力: %s' % OUT)
    print('サイズ: %.2f MB' % (os.path.getsize(OUT) / 1e6))
    print('印刷方式: %s / 画像倍率: %.2f' % (backend, scale))
    print('フォント: %d / %d サブセットを同梱' % (len(faces), total_faces))
    print('埋め込んだ素材の元サイズ上位:')
    for k, v in sorted(stats.items(), key=lambda kv: -kv[1])[:5]:
        print('  %-22s %6.0f KB' % (k, v / 1024))
    print('残った外部参照: %s' % (left or 'なし'))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--scale', type=float, default=0.82,
                    help='画像の縮小率。1.0 で原寸のまま（既定 0.82）')
    ap.add_argument('--backend', default='xml', choices=['xml', 'sdk', 'mock'])
    a = ap.parse_args()
    if not os.path.exists(os.path.join(ROOT, 'assets')):
        sys.exit('assets/ がありません。先に slice_assets.py を実行してください。')
    build(a.scale, a.backend)
